"""Request-time checks that a model id is still in the model catalog."""
from fastapi import HTTPException

from app.services.model_catalog import get_image_model, get_language_model

MODEL_NOT_SUPPORTED = "model no longer supported"


def require_language_model(model: str | None) -> None:
    """Raise 400 when *model* is set but is not an offered vision/language model."""
    if model is not None and get_language_model(model) is None:
        raise HTTPException(status_code=400, detail=MODEL_NOT_SUPPORTED)


def require_image_model(key: str | None, kind: str):
    """Return the offered image model for *key*, or raise 400."""
    model = get_image_model(key, kind)
    if model is None:
        raise HTTPException(status_code=400, detail=MODEL_NOT_SUPPORTED)
    return model


_OPTION_PARAMS = ("resolution", "aspect_ratio", "image_size", "quality", "safety_tolerance")
_FREE_PARAMS = ("seed", "enable_web_search", "negative_prompt")


def validate_model_params(model, values: dict) -> dict:
    """Return the request params *model* accepts, validated against its declared options.

    A param the model does not declare is ignored (not sent, not stored); an
    invalid option for a declared param raises 400.
    """
    accepted: dict = {}
    for name in _OPTION_PARAMS:
        value = values.get(name)
        spec = model.params.get(name)
        if value is None or spec is None:
            continue
        if isinstance(value, dict):
            if not (spec.get("custom_size") and set(value) == {"width", "height"}
                    and all(type(value[k]) is int and 256 <= value[k] <= 2048 for k in ("width", "height"))):
                raise HTTPException(status_code=400, detail=f"Invalid {name} for {model.key}")
        elif value not in spec.get("options", []):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {name} '{value}' for {model.key}; must be one of: {', '.join(spec['options'])}",
            )
        accepted[name] = value
    for name in _FREE_PARAMS:
        if name in model.params and values.get(name) is not None:
            accepted[name] = values[name]
    return accepted


def validate_steps_guidance(model, steps: int, guidance: float) -> None:
    spec = model.params.get("steps_guidance")
    if not spec:
        return
    for name, value in (("steps", steps), ("guidance", guidance)):
        bounds = spec[name]
        if not bounds["minimum"] <= value <= bounds["maximum"]:
            raise HTTPException(status_code=400, detail=f"Invalid {name} for {model.key}")
