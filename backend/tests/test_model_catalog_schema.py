"""Check every catalog request payload against a snapshot of fal's OpenAPI inputs.

``fixtures/fal_input_schemas.json`` records, per endpoint, the required fields and
each property's enum / types / bounds.  The payloads below are built by the real
``FalGenerator`` / ``FalEditor`` builders, so a catalog change that would send fal an
unknown field or an out-of-enum value fails here instead of at runtime.
"""
import json
from pathlib import Path

import pytest

from app.providers.fal_provider import FalEditor, FalGenerator
from app.providers.fal_vision_provider import build_router_request
from app.services.model_catalog import IMAGE_MODELS, LANGUAGE_MODELS, image_models

SCHEMAS = json.loads((Path(__file__).parent / "fixtures" / "fal_input_schemas.json").read_text())

_OPTION_PARAMS = ("resolution", "aspect_ratio", "image_size", "quality", "safety_tolerance")
_PYTHON_TYPES = {
    "string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list,
}


def _check_value(endpoint: str, name: str, value) -> None:
    prop = SCHEMAS[endpoint]["properties"][name]
    where = f"{endpoint}.{name}={value!r}"
    if isinstance(value, dict):
        # Custom size object: only endpoints that declare custom_size accept it.
        assert prop.get("custom_size"), f"{where}: custom size not accepted"
        assert set(value) == {"width", "height"}, where
        return
    types = prop.get("types") or []
    if types:
        # bool is an int subclass; check booleans explicitly.
        ok = any(
            isinstance(value, _PYTHON_TYPES[t]) and (t == "boolean") == isinstance(value, bool)
            for t in types
        )
        assert ok, f"{where}: expected one of {types}"
    if "enum" in prop:
        assert value in prop["enum"], f"{where}: not in enum {prop['enum']}"
    if "minimum" in prop:
        assert value >= prop["minimum"], where
    if "maximum" in prop:
        assert value <= prop["maximum"], where
    if "maxItems" in prop:
        assert len(value) <= prop["maxItems"], where


def assert_payload_fits(endpoint: str, arguments: dict) -> None:
    assert endpoint in SCHEMAS, f"{endpoint} missing from the fal schema fixture"
    schema = SCHEMAS[endpoint]
    for name, value in arguments.items():
        assert name in schema["properties"], f"{endpoint}: unknown property {name!r}"
        _check_value(endpoint, name, value)
    for name in schema["required"]:
        assert name in arguments, f"{endpoint}: missing required property {name!r}"


def _build(model, loras=None, **values):
    sources = [f"https://example.com/{i}.png" for i in range(model.max_source_images)]
    if model.kind == "generate":
        builder = FalGenerator(base_model=model.key).build_arguments
        return builder("a fox", loras=loras, **values)
    return FalEditor(edit_model=model.key).build_arguments(sources, "a fox", **values)


def _option_cases():
    for model in IMAGE_MODELS:
        yield pytest.param(model, None, None, id=f"{model.key}:defaults")
        for name in _OPTION_PARAMS:
            spec = model.params.get(name)
            if spec:
                for option in spec["options"]:
                    yield pytest.param(model, name, option, id=f"{model.key}:{name}={option}")


@pytest.mark.parametrize(("model", "name", "option"), _option_cases())
def test_payload_fits_fal_schema(model, name, option):
    values = {name: option} if name else {}
    endpoint, arguments = _build(model, **values)
    assert endpoint == model.endpoint
    assert_payload_fits(endpoint, arguments)
    if name:
        assert arguments[name] == option


@pytest.mark.parametrize("model", IMAGE_MODELS, ids=lambda m: m.key)
def test_payload_with_every_supported_param_fits_fal_schema(model):
    values = {"seed": 1, "negative_prompt": "blur", "enable_web_search": True, "width": 768, "height": 512}
    endpoint, arguments = _build(model, **values)
    assert_payload_fits(endpoint, arguments)
    assert ("seed" in arguments) == ("seed" in model.params)
    assert ("negative_prompt" in arguments) == ("negative_prompt" in model.params)
    assert ("enable_web_search" in arguments) == ("enable_web_search" in model.params)


@pytest.mark.parametrize("model", [m for m in IMAGE_MODELS if m.params.get("image_size", {}).get("custom_size")],
                         ids=lambda m: m.key)
def test_custom_size_is_sent_as_width_height_only_where_the_schema_allows(model):
    endpoint, arguments = _build(model, width=768, height=512)
    if model.kind == "generate":
        assert arguments["image_size"] == {"width": 768, "height": 512}
    assert_payload_fits(endpoint, arguments)


@pytest.mark.parametrize("model", [m for m in IMAGE_MODELS if m.supports_lora], ids=lambda m: m.key)
def test_lora_payload_fits_lora_endpoint_schema(model):
    loras = [{"path": "https://example.com/a.safetensors", "scale": 0.8}]
    endpoint, arguments = _build(model, loras=loras, seed=3)
    assert endpoint == model.lora_endpoint
    assert arguments["loras"] == loras
    assert_payload_fits(endpoint, arguments)


@pytest.mark.parametrize("model", IMAGE_MODELS, ids=lambda m: m.key)
def test_catalog_options_and_limits_match_fal_schema(model):
    props = SCHEMAS[model.endpoint]["properties"]
    for name, spec in model.params.items():
        if "options" in spec and name in props and "enum" in props[name]:
            assert set(spec["options"]) <= set(props[name]["enum"]), f"{model.key}.{name}"
        if spec.get("default") is not None and "enum" in props.get(name, {}):
            assert spec["default"] in props[name]["enum"], f"{model.key}.{name} default"
    if model.kind == "edit":
        max_items = props.get("image_urls", {}).get("maxItems")
        if max_items is not None:
            assert model.max_source_images <= max_items
        field = "image_url" if model.uses_single_image_url else "image_urls"
        assert field in props
    if model.lora_endpoint:
        assert model.lora_endpoint in SCHEMAS
    for name, value in model.fixed_payload.items():
        assert name in props, f"{model.key}: fixed {name} not an endpoint property"
        _check_value(model.endpoint, name, value)


def test_catalog_is_json_serializable():
    for model in IMAGE_MODELS:
        json.dumps(model.to_dict())
    for model in LANGUAGE_MODELS:
        json.dumps(model.to_dict())


def test_params_only_declare_what_the_endpoint_accepts():
    for model in image_models("generate") + image_models("edit"):
        props = SCHEMAS[model.endpoint]["properties"]
        for name in model.params:
            if name == "steps_guidance":
                assert {"num_inference_steps", "guidance_scale"} <= props.keys()
            else:
                assert name in props, f"{model.key} declares {name} but {model.endpoint} has no such property"


@pytest.mark.parametrize("with_images", [False, True])
@pytest.mark.parametrize("model", LANGUAGE_MODELS, ids=lambda m: m.id)
def test_router_payload_fits_openrouter_schema(model, with_images):
    images = ["data:image/png;base64,AAAA"] if with_images else None
    endpoint, arguments = build_router_request(model.id, "describe", 100, image_urls=images, temperature=0.7)
    assert endpoint == ("openrouter/router/vision" if with_images else "openrouter/router")
    assert_payload_fits(endpoint, arguments)


def test_custom_image_dimensions_and_steps_are_validated():
    from fastapi import HTTPException

    from app.api.model_validation import validate_model_params, validate_steps_guidance
    from app.services.model_catalog import get_image_model

    model = get_image_model("flux-2", "generate")
    assert validate_model_params(model, {"image_size": {"width": 512, "height": 768}})["image_size"]["width"] == 512
    for size in ({"width": 1, "height": 512}, {"width": True, "height": 512}, {"width": 512, "height": 512, "extra": 1}):
        with pytest.raises(HTTPException):
            validate_model_params(model, {"image_size": size})
    validate_steps_guidance(model, 4, 2.5)
    with pytest.raises(HTTPException):
        validate_steps_guidance(model, 3, 2.5)
    with pytest.raises(HTTPException):
        validate_steps_guidance(model, 28, 21)
