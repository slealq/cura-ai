"""fal.ai provider for LoRA training and image generation."""
import copy
import logging
import time
from collections.abc import Callable
from typing import Any

import fal_client
import httpx

from app.core.config import get_settings
from app.models.pipeline_log import LogCategory, LogLevel
from app.providers.base import BaseEditor, BaseGenerator, BaseTrainer, EditResult, GenerationResult, TrainingResult
from app.providers.tracing import provider_span
from app.services.log_service import write_log
from app.services.model_catalog import (
    DEFAULT_EDIT_MODEL,
    DEFAULT_GENERATION_MODEL,
    IMAGE_MODELS,
    LEGACY_TRAINER_ENDPOINTS,
    ImageModel,
    get_image_model,
    image_models,
)


class GenerationCancelledError(Exception):
    """Raised when a generation task is cancelled during polling."""
    pass

logger = logging.getLogger(__name__)
settings = get_settings()

# Per-model request config, derived from the model catalog (the single source of truth).
FAL_MODEL_CONFIG: dict[str, dict[str, Any]] = {
    m.key: {
        "generation_base_endpoint": m.endpoint,
        "generation_lora_endpoint": m.lora_endpoint,
        "supports_lora": m.supports_lora,
        "training_endpoint": m.trainer_endpoint,
    }
    for m in image_models("generate")
}

FAL_EDIT_MODEL_CONFIG: dict[str, dict[str, Any]] = {
    m.key: {
        "endpoint": m.endpoint,
        "max_source_images": m.max_source_images,
        "max_num_images": m.max_num_images,
        "uses_single_image_url": m.uses_single_image_url,
    }
    for m in image_models("edit")
}

# Both trainable base models share the same trainer-v2 request shape.
_TRAINER_FLAGS: dict[str, Any] = {
    "zip_param": "image_data_url",
    "supports_trigger_word": False,
    "supports_is_style": False,
    "supports_base64": False,
}

# Trainer config for every base model that can have a LoRA row: the offered
# trainable models plus the legacy ones (kept so historical rows stay readable).
FAL_TRAINER_CONFIG: dict[str, dict[str, Any]] = {
    **{
        m.key: {"training_endpoint": m.trainer_endpoint, **_TRAINER_FLAGS}
        for m in IMAGE_MODELS if m.trainable
    },
    **LEGACY_TRAINER_ENDPOINTS,
}


def get_trainer_config(base_model: str) -> dict[str, Any]:
    """Return the trainer config for *base_model*; raises ValueError if unknown."""
    config = FAL_TRAINER_CONFIG.get(base_model)
    if config is None:
        raise ValueError(f"Unknown base model for training: {base_model!r}")
    return config


def build_image_request(
    model: ImageModel,
    prompt: str,
    values: dict[str, Any],
    loras: list[dict] | None = None,
    source_urls: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build (endpoint, arguments) for a generate/edit request from the catalog.

    Only params the model declares are sent; anything else in *values* is
    ignored.  Raises ValueError when LoRAs are requested on a model without LoRA
    support, so they are never silently dropped.
    """
    if loras and not model.supports_lora:
        raise ValueError(f"Model {model.key!r} does not support LoRAs")
    endpoint = model.lora_endpoint if loras else model.endpoint
    arguments: dict[str, Any] = {"prompt": prompt}
    if model.supports_output_format:
        arguments["output_format"] = "png"

    if model.kind == "edit":
        urls = source_urls or []
        if not urls:
            raise ValueError("At least one source image is required for editing")
        if len(urls) > model.max_source_images and not (model.key == "kling-image" and values.get("subject_sources")):
            raise ValueError(f"{model.key!r} accepts at most {model.max_source_images} source images")
        if model.uses_single_image_url:
            arguments["image_url"] = urls[0]
            if len(urls) > 1:
                arguments["reference_image_urls"] = urls[1:]
        else:
            arguments["image_urls"] = urls
        if model.max_num_images:
            arguments["num_images"] = values.get("num_images") or 1

    for name, spec in model.params.items():
        if name == "steps_guidance":
            arguments["num_inference_steps"] = values.get("num_inference_steps", spec.get("steps", {}).get("default", 28))
            arguments["guidance_scale"] = values.get("guidance_scale", spec.get("guidance", {}).get("default", 3.5))
        elif name in ("seed", "enable_web_search"):
            if values.get(name) is not None:
                arguments[name] = values[name]
        elif name == "negative_prompt":
            if values.get(name):
                arguments[name] = values[name]
        else:
            value = values.get(name)
            if value is None and name == "image_size" and spec.get("custom_size") and values.get("width"):
                # No preset chosen: send a custom size object.
                value = {"width": values["width"], "height": values["height"]}
            if value is None:
                value = spec.get("default")
            if value is not None:
                arguments[name] = value

    if model.kind == "edit" and model.key == "kling-image":
        from app.services.edit_subject import subject_inputs
        if len(prompt) > 2500:
            raise ValueError("Kling prompts accept up to 2500 characters")
        sources = values.get("subject_sources")
        if sources is not None:
            arguments["image_urls"], arguments["elements"] = subject_inputs(sources, source_urls or [])
        mode = values.get("result_type", "single")
        if mode not in ("single", "series"):
            raise ValueError("Invalid Kling result type")
        if values.get("result_type") is not None:
            arguments["result_type"] = mode
        if mode == "series":
            count = values.get("series_amount")
            if not isinstance(count, int) or not 2 <= count <= 9:
                raise ValueError("Series requires 2–9 images")
            arguments["series_amount"] = count
            arguments.pop("num_images", None)
    if values.get("mask_url"):
        from app.services.edit_mask import provider_mask_url
        if model.key == "ideogram-v4.5-edit":
            if len(source_urls or []) > 4:
                raise ValueError("Ideogram paint accepts one base plus three references")
            if arguments.get("image_size", "auto") != "auto":
                raise ValueError("Ideogram paint requires automatic output size")
        arguments["mask_url"] = provider_mask_url(values["mask_url"], model.key)
    if values.get("object_boxes") is not None:
        from app.services.edit_layout import layout_payload
        if model.key != "flux-3-klein-edit" or len(values["object_boxes"]) > 32:
            raise ValueError("Object boxes require Klein and at most 32 boxes")
        arguments["bounding_boxes"], arguments["prompt"] = layout_payload(values["object_boxes"], prompt)
    if values.get("precision_area") is not None:
        if model.key != "ideogram-v4.5-edit":
            raise ValueError("Precision area requires Ideogram")
        area = values["precision_area"]
        if area not in ("none", "auto", "box"):
            raise ValueError("Invalid precision area")
        arguments["edit_precision"] = "regular" if area == "none" else "high"
        arguments["context_window"] = "auto" if area == "auto" else "none"
        if area == "auto" and not values.get("mask_url"):
            raise ValueError("Automatic precision area requires a mask")
        if area == "box":
            if not values.get("context_window_box"):
                raise ValueError("Precision box must be resolved before provider request")
            arguments["context_window_box"] = values["context_window_box"]
    arguments.update(copy.deepcopy(model.fixed_payload))
    if loras:
        arguments["loras"] = loras
    return endpoint, arguments


def _ensure_fal_key(api_key: str | None = None):
    """Set FAL_KEY env var for fal_client if not already set."""
    import os
    key = api_key
    if key:
        os.environ["FAL_KEY"] = key


class FalTrainer(BaseTrainer):
    """fal.ai LoRA training provider supporting multiple base models."""

    def __init__(self, api_key: str | None = None, base_model: str = "flux-2"):
        _ensure_fal_key(api_key)
        self.config = get_trainer_config(base_model)
        self.base_model = base_model

    async def start_training(
        self,
        image_urls: list[str],
        trigger_word: str | None = None,
        steps: int = 1000,
        is_style: bool = False,
        **kwargs: Any,
    ) -> str:
        """Submit LoRA training job to fal.ai."""
        task_start = time.monotonic()
        endpoint = self.config["training_endpoint"]

        arguments: dict[str, Any] = {
            "steps": steps,
        }

        # Only include trigger_word and is_style for models that support them
        if self.config["supports_trigger_word"] and trigger_word:
            arguments["trigger_word"] = trigger_word
        if self.config["supports_is_style"]:
            arguments["is_style"] = is_style

        # Use the correct ZIP param name from config if provided in kwargs
        zip_param = self.config["zip_param"]
        if zip_param in kwargs:
            arguments[zip_param] = kwargs.pop(zip_param)
        elif "images_data_url" in kwargs and zip_param != "images_data_url":
            # Remap if caller used the flux param name but we need the qwen one
            arguments[zip_param] = kwargs.pop("images_data_url")
        elif image_urls:
            arguments[zip_param] = image_urls

        arguments.update(kwargs)

        try:
            logger.info("FAL REQUEST | endpoint=%s args=%s", endpoint, arguments)
            handle = fal_client.submit(
                endpoint,
                arguments=arguments,
            )
            request_id = handle.request_id

            elapsed = (time.monotonic() - task_start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai training submitted: {request_id}",
                provider="fal",
                model=endpoint,
                operation="start_training",
                duration_ms=round(elapsed, 1),
                success=True,
                extra={"request_id": request_id, "steps": steps, "trigger_word": trigger_word, "base_model": self.base_model},
            )

            return request_id

        except Exception as e:
            elapsed = (time.monotonic() - task_start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai training submission failed: {e}",
                level=LogLevel.ERROR,
                provider="fal",
                model=endpoint,
                operation="start_training",
                duration_ms=round(elapsed, 1),
                success=False,
                extra={"error": str(e)},
            )
            raise

    async def check_training_status(self, request_id: str) -> dict[str, Any]:
        """Check fal.ai training job status."""
        endpoint = self.config["training_endpoint"]
        try:
            status = fal_client.status(
                endpoint,
                request_id,
                with_logs=True,
            )
            return {
                "status": type(status).__name__,
                "logs": getattr(status, "logs", []),
            }
        except Exception as e:
            logger.error(f"Failed to check training status {request_id}: {e}")
            return {"status": "error", "error": str(e)}

    async def get_training_result(self, request_id: str) -> TrainingResult:
        """Get completed training result from fal.ai."""
        task_start = time.monotonic()
        endpoint = self.config["training_endpoint"]

        try:
            result = fal_client.result(
                endpoint,
                request_id,
            )
            logger.info("FAL RESPONSE | endpoint=%s request_id=%s result=%s", endpoint, request_id, result)
            fal_cost = result.get("cost")

            lora_url = result.get("diffusers_lora_file", {}).get("url", "")
            if not lora_url:
                lora_url = result.get("config_file", {}).get("url", "")

            elapsed = (time.monotonic() - task_start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai training result retrieved: {request_id}",
                provider="fal",
                model=endpoint,
                operation="get_training_result",
                duration_ms=round(elapsed, 1),
                provider_cost=fal_cost,
                success=True,
            )

            return TrainingResult(
                lora_url=lora_url,
                request_id=request_id,
                provider="fal",
                metadata=result,
            )

        except Exception as e:
            elapsed = (time.monotonic() - task_start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai training result retrieval failed: {e}",
                level=LogLevel.ERROR,
                provider="fal",
                model=endpoint,
                operation="get_training_result",
                duration_ms=round(elapsed, 1),
                success=False,
            )
            raise

    def get_provider_name(self) -> str:
        return "fal"


class FalGenerator(BaseGenerator):
    """fal.ai image generation provider supporting multiple base models."""

    def __init__(self, api_key: str | None = None, base_model: str = DEFAULT_GENERATION_MODEL):
        _ensure_fal_key(api_key)
        model = get_image_model(base_model, "generate")
        if model is None:
            raise ValueError(f"Unknown generation model: {base_model!r}")
        self.model = model
        self.base_model = base_model

    def build_arguments(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 28,
        guidance_scale: float = 3.5,
        seed: int | None = None,
        loras: list[dict] | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
        safety_tolerance: str | None = None,
        enable_web_search: bool | None = None,
        image_size: str | None = None,
        quality: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Build (endpoint, arguments) for a generation request."""
        return build_image_request(
            self.model,
            prompt,
            {
                "negative_prompt": negative_prompt,
                "width": width,
                "height": height,
                "num_inference_steps": num_inference_steps,
                "guidance_scale": guidance_scale,
                "seed": seed,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "safety_tolerance": safety_tolerance,
                "enable_web_search": enable_web_search,
                "image_size": image_size,
                "quality": quality,
            },
            loras=loras,
        )

    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 28,
        guidance_scale: float = 3.5,
        seed: int | None = None,
        loras: list[dict] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
        safety_tolerance: str | None = None,
        enable_web_search: bool | None = None,
        image_size: str | None = None,
        quality: str | None = None,
    ) -> GenerationResult:
        """Generate an image via fal.ai.

        Uses submit + manual polling instead of subscribe, so that
        cancel_check can be evaluated between polls and the remote
        fal.ai request cancelled promptly.
        """
        task_start = time.monotonic()
        poll_interval = 2.0  # seconds between status polls

        endpoint, arguments = self.build_arguments(
            prompt, negative_prompt, width, height, num_inference_steps, guidance_scale, seed, loras,
            resolution, aspect_ratio, safety_tolerance, enable_web_search, image_size, quality,
        )

        request_id = None
        try:
            with provider_span("fal", "generate", endpoint) as _span:  # noqa: F841
                # Submit (non-blocking) instead of subscribe (blocking)
                logger.info("FAL REQUEST | endpoint=%s args=%s", endpoint, arguments)
                handle = fal_client.submit(endpoint, arguments=arguments)
                request_id = handle.request_id

                # Poll for completion with cancellation checks
                from fal_client.client import Completed
                while True:
                    if cancel_check and cancel_check():
                        logger.info(f"Generation cancelled during polling (request_id={request_id})")
                        try:
                            fal_client.cancel(endpoint, request_id)
                        except Exception:
                            pass  # best-effort remote cancel
                        raise GenerationCancelledError(f"Generation cancelled (request_id={request_id})")

                    status = handle.status(with_logs=False)
                    if isinstance(status, Completed):
                        break
                    time.sleep(poll_interval)

                result = handle.get()
            logger.info("FAL RESPONSE | endpoint=%s request_id=%s result=%s", endpoint, request_id, result)
            fal_cost = result.get("cost")

            # Extract image URL and download
            images = result.get("images", [])
            if not images:
                raise RuntimeError("No images returned from fal.ai")

            image_info = images[0]
            image_url = image_info.get("url", "")
            result_width = image_info.get("width", width)
            result_height = image_info.get("height", height)
            result_seed = result.get("seed")

            # Download the image
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(image_url)
                response.raise_for_status()
                image_data = response.content

            elapsed = (time.monotonic() - task_start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai generation completed ({result_width}x{result_height})",
                provider="fal",
                model=endpoint,
                operation="generate",
                duration_ms=round(elapsed, 1),
                provider_cost=fal_cost,
                success=True,
                extra={"seed": result_seed, "lora_count": len(loras) if loras else 0, "base_model": self.base_model, "request_id": request_id},
            )

            # Build response snapshot (exclude binary image data)
            fal_response = {k: v for k, v in result.items() if k != "images"}
            fal_response["image_count"] = len(images)
            fal_response["image_dimensions"] = [
                {"width": img.get("width"), "height": img.get("height")}
                for img in images
            ]

            # Build request snapshot (redact prompt to first 200 chars for size)
            request_args = {**arguments}
            if "prompt" in request_args and len(request_args["prompt"]) > 200:
                request_args["prompt"] = request_args["prompt"][:200] + "..."

            return GenerationResult(
                image_data=image_data,
                width=result_width,
                height=result_height,
                seed=result_seed,
                provider="fal",
                metadata={
                    "endpoint": endpoint,
                    "request_id": request_id,
                    "has_nsfw_concepts": result.get("has_nsfw_concepts", []),
                    "request_arguments": request_args,
                    "fal_response": fal_response,
                },
            )

        except GenerationCancelledError:
            raise
        except Exception as e:
            elapsed = (time.monotonic() - task_start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai generation failed: {e}",
                level=LogLevel.ERROR,
                provider="fal",
                model=endpoint,
                operation="generate",
                duration_ms=round(elapsed, 1),
                success=False,
                extra={"error": str(e), "request_id": request_id},
            )
            raise

    def get_provider_name(self) -> str:
        return "fal"


class FalEditor(BaseEditor):
    """fal.ai image editing provider."""

    def __init__(self, api_key: str | None = None, edit_model: str = DEFAULT_EDIT_MODEL):
        _ensure_fal_key(api_key)
        model = get_image_model(edit_model, "edit")
        if model is None:
            raise ValueError(f"Unknown edit model: {edit_model!r}")
        self.model = model
        self.edit_model = edit_model

    def build_arguments(
        self,
        image_urls: list[str],
        prompt: str,
        negative_prompt: str | None = None,
        image_size: dict | str | None = None,
        num_images: int = 1,
        seed: int | None = None,
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        """Build (endpoint, arguments) for an edit request.

        *kwargs* carries model-specific params (resolution, aspect_ratio, quality,
        safety_tolerance, enable_web_search); unsupported ones are ignored.
        """
        values = {
            **kwargs,
            "negative_prompt": negative_prompt,
            "image_size": image_size,
            "num_images": num_images,
            "seed": seed,
        }
        return build_image_request(self.model, prompt, values, source_urls=image_urls)

    async def edit(
        self,
        image_urls: list[str],
        prompt: str,
        negative_prompt: str | None = None,
        image_size: dict | str | None = None,
        num_images: int = 1,
        seed: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
        **kwargs: Any,
    ) -> EditResult:
        """Edit images via fal.ai using submit + manual polling."""
        task_start = time.monotonic()
        poll_interval = 2.0

        endpoint, arguments = self.build_arguments(
            image_urls, prompt, negative_prompt, image_size, num_images, seed, **kwargs,
        )

        request_id = None
        try:
            with provider_span("fal", "edit", self.edit_model) as _span:  # noqa: F841
                logger.info("FAL REQUEST | endpoint=%s args=%s", endpoint, arguments)
                handle = fal_client.submit(endpoint, arguments=arguments)
                request_id = handle.request_id

                from fal_client.client import Completed
                while True:
                    if cancel_check and cancel_check():
                        logger.info(f"Edit cancelled during polling (request_id={request_id})")
                        try:
                            fal_client.cancel(endpoint, request_id)
                        except Exception:
                            pass
                        raise GenerationCancelledError(f"Edit cancelled (request_id={request_id})")

                    status = handle.status(with_logs=False)
                    if isinstance(status, Completed):
                        break
                    time.sleep(poll_interval)

                result = handle.get()
            logger.info("FAL RESPONSE | endpoint=%s request_id=%s result=%s", endpoint, request_id, result)
            fal_cost = result.get("cost")

            images_data = result.get("images", [])
            if not images_data:
                raise RuntimeError(f"No images returned from fal.ai edit (response fields: {sorted(result)})")

            downloaded: list[bytes] = []
            widths: list[int] = []
            heights: list[int] = []

            async with httpx.AsyncClient(timeout=60) as client:
                for img_info in images_data:
                    response = await client.get(img_info["url"])
                    response.raise_for_status()
                    downloaded.append(response.content)
                    widths.append(img_info.get("width", 1024))
                    heights.append(img_info.get("height", 1024))

            if fal_cost is None and self.edit_model == "kling-image" and arguments.get("result_type") == "series":
                from app.services.pricing_engine import compute_raw_cost
                # Settle the actual delivered count once when fal omits invoice cost.
                raw = compute_raw_cost("fal", endpoint, "edit", {
                    **arguments, "series_amount": len(downloaded),
                })
                if raw is not None:
                    fal_cost = float(raw)

            result_seed = result.get("seed")

            elapsed = (time.monotonic() - task_start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai edit completed ({len(downloaded)} images)",
                provider="fal",
                model=endpoint,
                operation="edit",
                duration_ms=round(elapsed, 1),
                provider_cost=fal_cost,
                success=True,
                extra={"seed": result_seed, "edit_model": self.edit_model, "request_id": request_id},
            )

            return EditResult(
                images=downloaded,
                widths=widths,
                heights=heights,
                seed=result_seed,
                provider="fal",
                metadata={
                    "endpoint": endpoint,
                    "request_id": request_id,
                    "has_nsfw_concepts": result.get("has_nsfw_concepts", []),
                },
            )

        except GenerationCancelledError:
            raise
        except Exception as e:
            elapsed = (time.monotonic() - task_start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai edit failed: {e}",
                level=LogLevel.ERROR,
                provider="fal",
                model=endpoint,
                operation="edit",
                duration_ms=round(elapsed, 1),
                success=False,
                extra={"error": str(e), "request_id": request_id},
            )
            raise

    def get_provider_name(self) -> str:
        return "fal"
