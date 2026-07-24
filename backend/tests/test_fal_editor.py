"""Hermetic unit tests for fal.ai image editing request construction."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fal_client.client import Completed

from app.providers import fal_provider as fal_provider_module
from app.providers.fal_provider import FAL_EDIT_MODEL_CONFIG, FalEditor


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
        "image": {"url": "https://example.com/fake.png", "width": 1024, "height": 1024},
        "seed": 42,
    }
    submit = Mock(return_value=handle)
    monkeypatch.setattr(fal_provider_module, "fal_client", SimpleNamespace(submit=submit))
    monkeypatch.setattr(fal_provider_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(fal_provider_module, "write_log", Mock())
    return submit


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("edit_model", "expected_flags"),
    [
        ("qwen-image-max-edit", {"enable_safety_checker": False, "enable_prompt_expansion": False}),
        ("wan-25", {"enable_safety_checker": False}),
    ],
)
async def test_edit_qwen_and_wan_include_supported_optional_arguments(fal_submit, edit_model, expected_flags):
    result = await FalEditor(edit_model=edit_model).edit(
        ["https://example.com/source.png"],
        "replace the sky",
        negative_prompt="rain",
        image_size={"width": 768, "height": 512},
        seed=123,
        enable_safety_checker=False,
        enable_prompt_expansion=False,
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG[edit_model]["endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 1,
        "output_format": "png",
        "image_urls": ["https://example.com/source.png"],
        **expected_flags,
        "negative_prompt": "rain",
        "image_size": {"width": 768, "height": 512},
        "seed": 123,
    }
    assert result.provider == "fal"
    assert result.images == [b"fake-image-bytes"]


@pytest.mark.asyncio
async def test_edit_kling_uses_resolution_and_aspect_ratio_defaults(fal_submit):
    await FalEditor(edit_model="kling-image").edit(["https://example.com/source.png"], "replace the sky")

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG["kling-image"]["endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 1,
        "output_format": "png",
        "image_urls": ["https://example.com/source.png"],
        "resolution": "1K",
        "aspect_ratio": "auto",
    }


@pytest.mark.asyncio
async def test_edit_grok_uses_singular_image_url(fal_submit):
    await FalEditor(edit_model="grok-imagine").edit(["https://example.com/source.png"], "replace the sky")

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG["grok-imagine"]["endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 1,
        "output_format": "png",
        "image_url": "https://example.com/source.png",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("image_urls", "target_image_url"),
    [
        (["https://example.com/source.png", "https://example.com/target.png"], "https://example.com/target.png"),
        (["https://example.com/source.png"], "https://example.com/source.png"),
    ],
)
async def test_edit_face_swap_uses_source_and_target_urls_only(fal_submit, image_urls, target_image_url):
    await FalEditor(edit_model="face-swap").edit(image_urls, "ignored prompt", num_images=3, output_format="jpeg")

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG["face-swap"]["endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "source_face_url": "https://example.com/source.png",
        "target_image_url": target_image_url,
    }


@pytest.mark.asyncio
async def test_edit_nano_banana_uses_resolution_safety_and_web_search_arguments(fal_submit):
    await FalEditor(edit_model="nano-banana-pro-edit").edit(
        ["https://example.com/source.png"],
        "replace the sky",
        resolution="2K",
        aspect_ratio="16:9",
        safety_tolerance="5",
        enable_web_search=True,
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG["nano-banana-pro-edit"]["endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 1,
        "output_format": "png",
        "image_urls": ["https://example.com/source.png"],
        "resolution": "2K",
        "aspect_ratio": "16:9",
        "safety_tolerance": "5",
        "enable_web_search": True,
    }


@pytest.mark.asyncio
async def test_edit_seedream_5_pro_uses_image_size_enum_without_prompt_expansion(fal_submit):
    await FalEditor(edit_model="seedream-5-pro-edit").edit(
        ["https://example.com/source.png"],
        "replace the sky",
        negative_prompt="rain",
        image_size="auto_2K",
        num_images=2,
        enable_safety_checker=False,
        enable_prompt_expansion=True,
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG["seedream-5-pro-edit"]["endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 2,
        "output_format": "png",
        "image_urls": ["https://example.com/source.png"],
        "enable_safety_checker": False,
        "image_size": "auto_2K",
    }


@pytest.mark.asyncio
async def test_edit_qwen_image_2_pro_includes_supported_arguments(fal_submit):
    await FalEditor(edit_model="qwen-image-2-pro-edit").edit(
        ["https://example.com/source.png"],
        "replace the sky",
        negative_prompt="rain",
        image_size={"width": 768, "height": 512},
        seed=123,
        enable_safety_checker=False,
        enable_prompt_expansion=False,
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG["qwen-image-2-pro-edit"]["endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 1,
        "output_format": "png",
        "image_urls": ["https://example.com/source.png"],
        "enable_safety_checker": False,
        "enable_prompt_expansion": False,
        "negative_prompt": "rain",
        "image_size": {"width": 768, "height": 512},
        "seed": 123,
    }


@pytest.mark.asyncio
async def test_edit_flux_2_lora_uses_empty_loras_and_omits_negative_prompt(fal_submit):
    await FalEditor(edit_model="flux-2-lora-edit").edit(
        ["https://example.com/source.png"],
        "replace the sky",
        negative_prompt="rain",
        image_size="landscape_4_3",
        seed=123,
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG["flux-2-lora-edit"]["endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 1,
        "output_format": "png",
        "image_urls": ["https://example.com/source.png"],
        "loras": [],
        "enable_safety_checker": True,
        "enable_prompt_expansion": True,
        "image_size": "landscape_4_3",
        "seed": 123,
    }
