"""fal.ai provider for LoRA training and image generation."""
import logging
import time
from collections.abc import Callable
from typing import Any

import fal_client
import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.models.pipeline_log import LogCategory, LogLevel
from app.providers.base import BaseEditor, BaseGenerator, BaseTrainer, EditResult, GenerationResult, TrainingResult
from app.services.log_service import write_log


class GenerationCancelledError(Exception):
    """Raised when a generation task is cancelled during polling."""
    pass

logger = logging.getLogger(__name__)
settings = get_settings()

# Model configuration: maps base_model keys to fal.ai endpoints and parameter differences
FAL_MODEL_CONFIG = {
    "flux-dev": {
        "training_endpoint": "fal-ai/flux-lora-fast-training",
        "generation_lora_endpoint": "fal-ai/flux-lora",
        "generation_base_endpoint": "fal-ai/flux/dev",
        "zip_param": "images_data_url",
        "supports_trigger_word": True,
        "supports_is_style": True,
        "supports_base64": True,
        "default_steps": 1000,
        "default_guidance": 3.5,
    },
    "qwen-2.5": {
        "training_endpoint": "fal-ai/qwen-image-2512-trainer-v2",
        "generation_lora_endpoint": "fal-ai/qwen-image-2512/lora",
        "generation_base_endpoint": "fal-ai/qwen-image-2512",
        "zip_param": "image_data_url",
        "supports_trigger_word": False,
        "supports_is_style": False,
        "supports_base64": False,
        "default_steps": 2000,
        "default_guidance": 4.0,
    },
}


def _ensure_fal_key(api_key: str | None = None):
    """Set FAL_KEY env var for fal_client if not already set."""
    import os
    key = api_key
    if key:
        os.environ["FAL_KEY"] = key


class FalTrainer(BaseTrainer):
    """fal.ai LoRA training provider supporting multiple base models."""

    def __init__(self, api_key: str | None = None, base_model: str = "flux-dev"):
        _ensure_fal_key(api_key)
        self.config = FAL_MODEL_CONFIG.get(base_model, FAL_MODEL_CONFIG["flux-dev"])
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

    def __init__(self, api_key: str | None = None, base_model: str = "flux-dev"):
        _ensure_fal_key(api_key)
        self.config = FAL_MODEL_CONFIG.get(base_model, FAL_MODEL_CONFIG["flux-dev"])
        self.base_model = base_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30),
           retry=retry_if_not_exception_type(GenerationCancelledError))
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
    ) -> GenerationResult:
        """Generate an image via fal.ai.

        Uses submit + manual polling instead of subscribe, so that
        cancel_check can be evaluated between polls and the remote
        fal.ai request cancelled promptly.
        """
        task_start = time.monotonic()
        poll_interval = 2.0  # seconds between status polls

        # Choose endpoint based on LoRA
        if loras:
            endpoint = self.config["generation_lora_endpoint"]
            arguments: dict[str, Any] = {
                "prompt": prompt,
                "image_size": {"width": width, "height": height},
                "num_inference_steps": num_inference_steps,
                "guidance_scale": guidance_scale,
                "loras": loras,
                "output_format": "png",
                "enable_safety_checker": False,
            }
        else:
            endpoint = self.config["generation_base_endpoint"]
            arguments = {
                "prompt": prompt,
                "image_size": {"width": width, "height": height},
                "num_inference_steps": num_inference_steps,
                "guidance_scale": guidance_scale,
                "output_format": "png",
                "enable_safety_checker": False,
            }

        if seed is not None:
            arguments["seed"] = seed

        request_id = None
        try:
            # Submit (non-blocking) instead of subscribe (blocking)
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
                success=True,
                extra={"seed": result_seed, "lora_count": len(loras) if loras else 0, "base_model": self.base_model, "request_id": request_id},
            )

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
                model=endpoint if loras else self.config["generation_base_endpoint"],
                operation="generate",
                duration_ms=round(elapsed, 1),
                success=False,
                extra={"error": str(e), "request_id": request_id},
            )
            raise

    def get_provider_name(self) -> str:
        return "fal"


# --- Edit model configuration ---

FAL_EDIT_MODEL_CONFIG = {
    "qwen-image-max-edit": {
        "endpoint": "fal-ai/qwen-image-max/edit",
        "supports_negative_prompt": True,
        "supports_prompt_expansion": True,
        "supports_safety_checker": True,
        "max_source_images": 3,
        "max_num_images": 6,
    },
    "kling-image": {
        "endpoint": "fal-ai/kling-image/o3/image-to-image",
        "supports_negative_prompt": False,
        "supports_prompt_expansion": False,
        "supports_safety_checker": False,
        "max_source_images": 10,
        "max_num_images": 9,
        "uses_resolution": True,
        "uses_aspect_ratio": True,
    },
    "wan-25": {
        "endpoint": "fal-ai/wan-25-preview/image-to-image",
        "supports_negative_prompt": True,
        "supports_prompt_expansion": False,
        "supports_safety_checker": True,
        "max_source_images": 2,
        "max_num_images": 4,
    },
}


class FalEditor(BaseEditor):
    """fal.ai image editing provider."""

    def __init__(self, api_key: str | None = None, edit_model: str = "qwen-image-max-edit"):
        _ensure_fal_key(api_key)
        self.config = FAL_EDIT_MODEL_CONFIG.get(edit_model, FAL_EDIT_MODEL_CONFIG["qwen-image-max-edit"])
        self.edit_model = edit_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30),
           retry=retry_if_not_exception_type(GenerationCancelledError))
    async def edit(
        self,
        image_urls: list[str],
        prompt: str,
        negative_prompt: str | None = None,
        image_size: dict | str | None = None,
        num_images: int = 1,
        seed: int | None = None,
        output_format: str = "png",
        enable_prompt_expansion: bool = True,
        enable_safety_checker: bool = True,
        cancel_check: Callable[[], bool] | None = None,
        **kwargs: Any,
    ) -> EditResult:
        """Edit images via fal.ai using submit + manual polling."""
        task_start = time.monotonic()
        poll_interval = 2.0
        endpoint = self.config["endpoint"]

        arguments: dict[str, Any] = {
            "prompt": prompt,
            "image_urls": image_urls,
            "num_images": num_images,
            "output_format": output_format,
        }

        if self.config.get("uses_resolution"):
            # Kling-style: resolution + aspect_ratio instead of image_size
            resolution = kwargs.get("resolution", "1K")
            arguments["resolution"] = resolution
            aspect_ratio = kwargs.get("aspect_ratio", "auto")
            arguments["aspect_ratio"] = aspect_ratio
        else:
            # Qwen-style: image_size + safety/expansion toggles
            arguments["enable_safety_checker"] = enable_safety_checker
            if self.config["supports_prompt_expansion"]:
                arguments["enable_prompt_expansion"] = enable_prompt_expansion
            if negative_prompt and self.config["supports_negative_prompt"]:
                arguments["negative_prompt"] = negative_prompt
            if image_size is not None:
                arguments["image_size"] = image_size

        if seed is not None:
            arguments["seed"] = seed

        request_id = None
        try:
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

            images_data = result.get("images", [])
            if not images_data:
                raise RuntimeError("No images returned from fal.ai edit")

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

            result_seed = result.get("seed")

            elapsed = (time.monotonic() - task_start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai edit completed ({len(downloaded)} images)",
                provider="fal",
                model=endpoint,
                operation="edit",
                duration_ms=round(elapsed, 1),
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
