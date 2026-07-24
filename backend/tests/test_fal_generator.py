"""Hermetic unit tests for fal.ai generation request construction."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fal_client.client import Completed

from app.providers import fal_provider as fal_provider_module
from app.providers.fal_provider import FAL_MODEL_CONFIG, FalGenerator


class FakeResponse:
    """Minimal HTTP response returned by the mocked image download client."""

    content = b"fake-image-bytes"

    def raise_for_status(self):
        """Match httpx's successful-response interface."""


class FakeAsyncClient:
    """Async HTTP client that prevents image downloads from leaving the process."""

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _url):
        return FakeResponse()


@pytest.fixture
def fal_submit(monkeypatch):
    """Replace fal submission, downloads, and database logging with local fakes."""
    handle = Mock()
    handle.request_id = "request-123"
    handle.status.return_value = Completed(logs=None, metrics={})
    handle.get.return_value = {
        "images": [{"url": "https://example.com/fake.png", "width": 1024, "height": 1024}],
        "seed": 42,
    }
    submit = Mock(return_value=handle)
    monkeypatch.setattr(fal_provider_module, "fal_client", SimpleNamespace(submit=submit))
    monkeypatch.setattr(fal_provider_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(fal_provider_module, "write_log", Mock())
    return submit


@pytest.mark.asyncio
@pytest.mark.parametrize("base_model", ["flux-dev", "qwen-2.5", "flux-2", "qwen-image-2512"])
async def test_generate_with_loras_uses_lora_endpoint_and_supported_arguments(fal_submit, base_model):
    result = await FalGenerator(base_model=base_model).generate(
        "painted fox",
        width=768,
        height=512,
        num_inference_steps=31,
        guidance_scale=4.5,
        seed=123,
        loras=[{"path": "https://example.com/style.safetensors", "scale": 0.8}],
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_MODEL_CONFIG[base_model]["generation_lora_endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "painted fox",
        "image_size": {"width": 768, "height": 512},
        "num_inference_steps": 31,
        "guidance_scale": 4.5,
        "loras": [{"path": "https://example.com/style.safetensors", "scale": 0.8}],
        "output_format": "png",
        "enable_safety_checker": base_model == "flux-2",
        "seed": 123,
    }
    assert result.provider == "fal"
    assert result.image_data == b"fake-image-bytes"


@pytest.mark.asyncio
@pytest.mark.parametrize("base_model", ["flux-dev", "qwen-2.5", "flux-2", "qwen-image-2512"])
async def test_generate_without_loras_uses_base_endpoint_and_omits_seed(fal_submit, base_model):
    await FalGenerator(base_model=base_model).generate(
        "painted fox", width=768, height=512, num_inference_steps=31, guidance_scale=4.5
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_MODEL_CONFIG[base_model]["generation_base_endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "painted fox",
        "image_size": {"width": 768, "height": 512},
        "output_format": "png",
        "num_inference_steps": 31,
        "guidance_scale": 4.5,
        "enable_safety_checker": base_model == "flux-2",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_model", "seed", "expected_seed"),
    [("nano-banana-pro", 123, {"seed": 123}), ("nano-banana-2", None, {})],
)
async def test_generate_nano_banana_models_use_resolution_aspect_arguments(
    fal_submit, base_model, seed, expected_seed
):
    await FalGenerator(base_model=base_model).generate(
        "painted fox",
        num_inference_steps=31,
        guidance_scale=4.5,
        seed=seed,
        resolution="2K",
        aspect_ratio="16:9",
        safety_tolerance="5",
        enable_web_search=True,
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_MODEL_CONFIG[base_model]["generation_base_endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "painted fox",
        "output_format": "png",
        "resolution": "2K",
        "aspect_ratio": "16:9",
        "safety_tolerance": "5",
        "enable_web_search": True,
        **expected_seed,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("image_size", "expected_image_size"),
    [("square_hd", "square_hd"), (None, {"width": 768, "height": 512})],
)
async def test_generate_flux_2_pro_uses_preset_or_custom_image_size(fal_submit, image_size, expected_image_size):
    await FalGenerator(base_model="flux-2-pro").generate(
        "painted fox", width=768, height=512, image_size=image_size, safety_tolerance="3"
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_MODEL_CONFIG["flux-2-pro"]["generation_base_endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "painted fox",
        "output_format": "png",
        "image_size": expected_image_size,
        "safety_tolerance": "3",
    }


@pytest.mark.asyncio
async def test_generate_seedream_5_pro_uses_its_image_size_enum(fal_submit):
    await FalGenerator(base_model="seedream-5-pro").generate(
        "painted fox",
        image_size="portrait_4_3",
        seed=123,
        num_inference_steps=31,
        guidance_scale=4.5,
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_MODEL_CONFIG["seedream-5-pro"]["generation_base_endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "painted fox",
        "image_size": "portrait_4_3",
        "output_format": "png",
        "enable_safety_checker": True,
    }
