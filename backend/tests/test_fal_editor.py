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
async def test_edit_qwen_image_3_sends_fixed_flags_and_supported_params(fal_submit):
    result = await FalEditor(edit_model="qwen-image-3-edit").edit(
        ["https://example.com/source.png"],
        "replace the sky",
        negative_prompt="rain",
        image_size="square_hd",
        seed=123,
        # Request-level flags are ignored: the catalog fixes them for this model.
        enable_safety_checker=False,
        enable_prompt_expansion=True,
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG["qwen-image-3-edit"]["endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 1,
        "output_format": "png",
        "image_urls": ["https://example.com/source.png"],
        "negative_prompt": "rain",
        "image_size": "square_hd",
        "seed": 123,
        "enable_safety_checker": True,
        "enable_prompt_expansion": False,
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
async def test_edit_ideogram_uses_singular_image_url_and_no_output_format(fal_submit):
    await FalEditor(edit_model="ideogram-v4.5-edit").edit(
        ["https://example.com/source.png"], "replace the sky", quality="high", seed=7,
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG["ideogram-v4.5-edit"]["endpoint"]
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 1,
        "image_url": "https://example.com/source.png",
        "image_size": "auto",
        "quality": "high",
        "seed": 7,
        "enable_safety_checker": True,
    }


@pytest.mark.asyncio
async def test_edit_grok_uses_plural_image_urls_and_fixed_quality(fal_submit):
    await FalEditor(edit_model="grok-imagine-v2-edit").edit(
        ["https://example.com/a.png", "https://example.com/b.png"], "replace the sky",
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == "xai/grok-imagine-image/v2.0/edit"
    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 1,
        "output_format": "png",
        "image_urls": ["https://example.com/a.png", "https://example.com/b.png"],
        "aspect_ratio": "auto",
        "resolution": "1k",
        "quality": "medium",
    }


@pytest.mark.asyncio
async def test_edit_nano_banana_uses_resolution_safety_and_web_search_arguments(fal_submit):
    await FalEditor(edit_model="nano-banana-2.1-edit").edit(
        ["https://example.com/source.png"],
        "replace the sky",
        resolution="2K",
        aspect_ratio="16:9",
        safety_tolerance="5",
        enable_web_search=True,
    )

    endpoint, = fal_submit.call_args.args
    assert endpoint == FAL_EDIT_MODEL_CONFIG["nano-banana-2.1-edit"]["endpoint"]
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
async def test_edit_nano_banana_lite_omits_resolution_and_web_search(fal_submit):
    await FalEditor(edit_model="nano-banana-lite-edit").edit(
        ["https://example.com/source.png"], "replace the sky", resolution="2K", enable_web_search=True,
    )

    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "num_images": 1,
        "output_format": "png",
        "image_urls": ["https://example.com/source.png"],
        "aspect_ratio": "auto",
        "safety_tolerance": "4",
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
        "enable_safety_checker": True,
        "image_size": "auto_2K",
    }


@pytest.mark.asyncio
async def test_edit_flux_3_has_no_num_images_and_fixes_resolution(fal_submit):
    await FalEditor(edit_model="flux-3-edit").edit(["https://example.com/source.png"], "replace the sky", seed=5)

    assert fal_submit.call_args.kwargs["arguments"] == {
        "prompt": "replace the sky",
        "output_format": "png",
        "image_urls": ["https://example.com/source.png"],
        "aspect_ratio": "auto",
        "resolution": "1k",
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
        "enable_prompt_expansion": False,
        "image_size": "landscape_4_3",
        "seed": 123,
    }


def test_edit_rejects_unknown_and_removed_models():
    for removed in ("face-swap", "wan-25", "grok-imagine", "qwen-image-max-edit", "qwen-image-2-pro-edit", "nope"):
        with pytest.raises(ValueError):
            FalEditor(edit_model=removed)


def test_edit_rejects_too_many_source_images():
    editor = FalEditor(edit_model="ideogram-v4.5-edit")
    with pytest.raises(ValueError):
        editor.build_arguments(["https://example.com/a.png"] * 6, "x")


@pytest.mark.asyncio
@pytest.mark.parametrize("returned,provider_cost", [(2, None), (9, None), (3, 0.4)])
async def test_kling_series_one_call_downloads_all_and_records_total_cost(fal_submit, returned, provider_cost):
    response = {"images": [{"url": f"https://example.com/{index}.png", "width": 512, "height": 512} for index in range(returned)]}
    if provider_cost is not None:
        response["cost"] = provider_cost
    fal_submit.return_value.get.return_value = response
    result = await FalEditor(edit_model="kling-image").edit(["composition"], "@Image1", result_type="series", series_amount=9, resolution="4K")
    fal_submit.assert_called_once()
    assert len(result.images) == returned
    assert len(result.widths) == len(result.heights) == returned
    assert fal_provider_module.write_log.call_args.kwargs["provider_cost"] == pytest.approx(provider_cost if provider_cost is not None else 0.056 * returned)
