"""Model catalog — single source of truth for every model the product offers.

Pure data plus small helpers (no DB imports).  ``FAL_MODEL_CONFIG``,
``FAL_EDIT_MODEL_CONFIG`` and the ``model_registry`` registrations are all
derived from this module, and ``GET /api/settings/model-catalog`` serves it to
the frontend.  Billing rows for everything listed here are seeded by migration
055 (``tests/test_model_catalog_billing_drift.py`` keeps the two in sync).

Language models run through fal's OpenRouter routers.  Prices are USD per 1M
tokens and were verified live on 2026-10-30.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Operations that call a language/vision model and need a billing row per model.
LANGUAGE_OPERATIONS: tuple[str, ...] = (
    "tag",
    "describe",
    "custom",
    "evaluate",
    "evaluate_creative",
    "summarize_eval",
    "generate_prompts",
    "summarize",
    "expand_prompt",
    "suggest_prompt",
)


# ---------------------------------------------------------------------------
# Language models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LanguageModel:
    id: str
    label: str
    vendor: str
    capabilities: frozenset[str]
    supports_temperature: bool
    input_rate: float
    """USD per 1M input tokens (base tier)."""
    output_rate: float
    """USD per 1M output tokens (base tier)."""
    tier: dict | None = None
    """Long-prompt pricing, e.g. {"min_prompt_tokens": 100000, "input": 0.5, "output": 2.5}."""
    requires_reasoning: bool = False
    reasoning_heavy: bool = False
    """True when output estimates must include invisible reasoning tokens."""
    is_default: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "vendor": self.vendor,
            "capabilities": sorted(self.capabilities),
            "supports_temperature": self.supports_temperature,
            "input_rate": self.input_rate,
            "output_rate": self.output_rate,
            "tier": dict(self.tier) if self.tier else None,
            "requires_reasoning": self.requires_reasoning,
            "reasoning_heavy": self.reasoning_heavy,
            "is_default": self.is_default,
        }


# OpenRouter reasoning.mandatory metadata, researched 2026-10-30.
_MANDATORY_REASONING = frozenset({
    "anthropic/claude-sonnet-5.5", "anthropic/claude-opus-5.5",
    "openai/gpt-6.1-sol", "openai/gpt-6-astra", "google/gemini-3.5-flash-lite",
    "google/gemini-3.8-flash", "google/gemini-4-argon", "x-ai/grok-4.7",
    "qwen/qwen3.8-max-0902", "qwen/qwen3.8-max-prime", "z-ai/glm-5.3-flash",
    "z-ai/glm-5.3-flashx", "minimax/minimax-m3.1-flash",
})

_VT = frozenset({"vision", "text"})


def _lm(
    id: str, label: str, input_rate: float, output_rate: float, supports_temperature: bool,
    tier: dict | None = None, reasoning_heavy: bool = False, is_default: bool = False,
) -> LanguageModel:
    return LanguageModel(
        id=id, label=label, vendor=id.split("/", 1)[0], capabilities=_VT,
        supports_temperature=supports_temperature, input_rate=input_rate,
        output_rate=output_rate, tier=tier,
        requires_reasoning=id in _MANDATORY_REASONING,
        reasoning_heavy=reasoning_heavy or id in _MANDATORY_REASONING,
        is_default=is_default,
    )


def _tier(min_prompt_tokens: int, input: float, output: float) -> dict:
    return {"min_prompt_tokens": min_prompt_tokens, "input": input, "output": output}


LANGUAGE_MODELS: tuple[LanguageModel, ...] = (
    _lm("anthropic/claude-haiku-5.5", "Claude Haiku 5.5", 0.10, 0.50, False, _tier(100000, 0.50, 2.50), is_default=True),
    _lm("anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5", 2, 10, False),
    _lm("anthropic/claude-opus-5.5", "Claude Opus 5.5", 4, 20, False),
    _lm("openai/gpt-6-luna", "GPT-6 Luna", 0.10, 0.50, False, _tier(272000, 0.20, 0.75)),
    _lm("openai/gpt-6.1-terra", "GPT-6.1 Terra", 1, 5, False, _tier(272000, 2, 7.5)),
    _lm("openai/gpt-6.1-sol", "GPT-6.1 Sol", 2, 10, False, _tier(272000, 4, 15)),
    _lm("openai/gpt-6-astra", "GPT-6 Astra", 10, 50, False, _tier(272000, 20, 75)),
    _lm("google/gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite", 0.30, 2.50, True),
    _lm("google/gemini-3.8-flash", "Gemini 3.8 Flash", 0.825, 4.125, True),
    _lm("google/gemini-4-argon", "Gemini 4 Argon", 2, 10, True),
    _lm("x-ai/grok-4.3", "Grok 4.3", 1.25, 2.50, True, _tier(200000, 2.5, 5)),
    _lm("x-ai/grok-4.7", "Grok 4.7", 2, 6, True, _tier(200000, 4, 12)),
    _lm("qwen/qwen3.8-flash", "Qwen3.8 Flash", 0.15, 0.47, True),
    _lm("qwen/qwen3.8-max-0902", "Qwen3.8 Max 0902", 2, 6, True),
    _lm("qwen/qwen3.8-max-prime", "Qwen3.8 Max Prime", 4, 12, True),
    _lm("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash", 0.045, 0.50, True),
    _lm("moonshotai/kimi-k3.1-pro", "Kimi K3.1 Pro", 2, 10, False),
    _lm("z-ai/glm-5.3-flash", "GLM 5.3 Flash", 0.018, 0.1402, True),
    _lm("z-ai/glm-5.3-flashx", "GLM 5.3 FlashX", 0.37, 1.25, True),
    # Time-of-day pricing (0.075/0.30 off-peak); the catalog stores the higher rate.
    _lm("minimax/minimax-m3.1-flash", "MiniMax M3.1 Flash", 0.15, 0.60, True),
    _lm("minimax/minimax-m3", "MiniMax M3", 0.30, 1.20, True),
)

_LANGUAGE_BY_ID: dict[str, LanguageModel] = {m.id: m for m in LANGUAGE_MODELS}

DEFAULT_LANGUAGE_MODEL = next(m.id for m in LANGUAGE_MODELS if m.is_default)
# Vision and language share one list; the defaults are separate settings.
DEFAULT_VISION_MODEL = DEFAULT_LANGUAGE_MODEL


def get_language_model(model_id: str | None) -> LanguageModel | None:
    """Return the offered language model for *model_id*, or None."""
    return _LANGUAGE_BY_ID.get(model_id) if model_id else None


def offered_language_ids() -> list[str]:
    return [m.id for m in LANGUAGE_MODELS]


# ---------------------------------------------------------------------------
# Image models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ImageModel:
    key: str
    label: str
    vendor: str
    kind: str
    """"generate" or "edit"."""
    endpoint: str
    lora_endpoint: str | None = None
    supports_lora: bool = False
    trainable: bool = False
    trainer_endpoint: str | None = None
    params: dict = field(default_factory=dict)
    """Declarative request params the model accepts (JSON-serializable)."""
    fixed_payload: dict = field(default_factory=dict)
    """Keys always sent with the request."""
    max_source_images: int = 0
    uses_single_image_url: bool = False
    max_num_images: int = 0
    """Max ``num_images`` per edit request; 0 means the endpoint has no such param."""
    supports_output_format: bool = True
    base_price: float = 0.0
    """Flat USD per call at the default option (the catalog ``cost_per_call``)."""
    price_param: str | None = None
    price_table: dict | None = None
    lora_price: float | None = None
    pricing_strategy_key: str | None = None
    """Hand-written strategy in pricing_engine (otherwise price_table drives variable pricing)."""
    is_default: bool = False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "vendor": self.vendor,
            "kind": self.kind,
            "endpoint": self.endpoint,
            "lora_endpoint": self.lora_endpoint,
            "supports_lora": self.supports_lora,
            "trainable": self.trainable,
            "params": self.params,
            "fixed_payload": self.fixed_payload,
            "max_source_images": self.max_source_images,
            "max_num_images": self.max_num_images if self.kind == "edit" else 8,
            "uses_single_image_url": self.uses_single_image_url,
            "base_price": self.base_price,
            "price_param": self.price_param,
            "price_table": self.price_table,
            "lora_price": self.lora_price,
            "is_default": self.is_default,
        }


def _opt(options: list[str], default: str | None) -> dict:
    return {"options": list(options), "default": default}


IMAGE_SIZE_PRESETS = ["square_hd", "square", "portrait_4_3", "portrait_16_9", "landscape_4_3", "landscape_16_9"]
SEEDREAM_SIZES = IMAGE_SIZE_PRESETS + ["auto_1K", "auto_1.5K", "auto_2K"]
NANO_ASPECTS = ["auto", "21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4", "2:3", "9:16"]
FLUX3_ASPECTS = ["auto", "21:9", "2:1", "16:9", "3:2", "7:5", "4:3", "5:4", "1:1", "4:5", "3:4", "5:7", "2:3", "9:16", "1:2"]
GROK_ASPECTS = ["2:1", "20:9", "19.5:9", "16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16", "9:19.5", "9:20", "1:2"]
KLING_ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9", "auto"]
SAFETY_1_6 = ["1", "2", "3", "4", "5", "6"]
SAFETY_1_5 = ["1", "2", "3", "4", "5"]
_RES_1K_4K = ["1K", "2K", "4K"]
_GPT_QUALITY = ["low", "medium", "high", "xhigh", "max"]
_GPT2_QUALITY = ["low", "medium", "high"]
_NO_ARG: dict = {}


def _nano_params(resolution: bool, web_search: bool, aspect_default: str) -> dict:
    params: dict = {}
    if resolution:
        params["resolution"] = _opt(_RES_1K_4K, "1K")
    params["aspect_ratio"] = _opt(NANO_ASPECTS, aspect_default)
    params["safety_tolerance"] = _opt(SAFETY_1_6, "4")
    if web_search:
        params["enable_web_search"] = {}
    params["seed"] = {}
    return params


def _size_param(default: str | None, extra: list[str] | None = None, custom: bool = False,
                presets: list[str] | None = None) -> dict:
    spec = _opt((extra or []) + (presets or IMAGE_SIZE_PRESETS), default)
    if custom:
        spec["custom_size"] = True
    return spec


def _table(options: list[str], prices: list[float]) -> dict:
    return dict(zip(options, prices, strict=True))


_SAFE = {"enable_safety_checker": True}
_SAFE_NOEXP = {"enable_safety_checker": True, "enable_prompt_expansion": False}

_GEN = "generate"
_EDIT = "edit"


def _gen(key, label, vendor, endpoint, params, base_price, **kw) -> ImageModel:
    return ImageModel(key=key, label=label, vendor=vendor, kind=_GEN, endpoint=endpoint,
                      params=params, base_price=base_price, **kw)


def _edit(key, label, vendor, endpoint, params, base_price, max_sources, max_num_images=4, **kw) -> ImageModel:
    return ImageModel(key=key, label=label, vendor=vendor, kind=_EDIT, endpoint=endpoint, params=params,
                      base_price=base_price, max_source_images=max_sources, max_num_images=max_num_images, **kw)


_GPT25_TABLE = {"low": 0.00588, "medium": 0.01317, "high": 0.05268, "xhigh": 0.09366, "max": 0.21072}
_GPT2_TABLE = {"low": 0.006, "medium": 0.053, "high": 0.211}
_NB21_TABLE = {"1K": 0.040, "2K": 0.059, "4K": 0.134}
_NB21_EDIT_TABLE = {"1K": 0.044, "2K": 0.063, "4K": 0.138}
_SEEDREAM_PRO_TABLE = {opt: (0.135 if opt == "auto_2K" else 0.0675) for opt in SEEDREAM_SIZES}
_IDEOGRAM_TABLE = {"low": 0.03, "medium": 0.06, "high": 0.22}

# Params shared by the gpt-image generate / edit families.
_GPT25_GEN_PARAMS = {"image_size": _size_param("square_hd"), "quality": _opt(_GPT_QUALITY, "high")}
_GPT25_EDIT_PARAMS = {"image_size": _size_param("auto", ["auto"]), "quality": _opt(_GPT_QUALITY, "high")}
def _steps_params(min_steps: int, guidance: float) -> dict:
    return {"image_size": _size_param("landscape_4_3", custom=True), "seed": {},
            "steps_guidance": {"steps": {"minimum": min_steps, "maximum": 50, "default": 28},
                               "guidance": {"minimum": 0, "maximum": 20, "default": guidance}}}



IMAGE_MODELS: tuple[ImageModel, ...] = (
    # --- Generation ---
    _gen("nano-banana-2.1", "Nano Banana 2.1", "google", "google/nano-banana-2.1",
         _nano_params(True, True, "1:1"), 0.040, price_param="resolution", price_table=_NB21_TABLE,
         is_default=True),
    _gen("nano-banana-pro", "Nano Banana Pro", "google", "fal-ai/nano-banana-pro",
         _nano_params(True, True, "1:1"), 0.15, pricing_strategy_key="nano_banana_pro"),
    _gen("nano-banana-lite", "Nano Banana Lite", "google", "google/nano-banana-lite",
         _nano_params(False, False, "1:1"), 0.042),
    _gen("gpt-image-2.5-flare", "GPT Image 2.5 Flare", "openai", "openai/gpt-image-2.5/flare/text-to-image",
         _GPT25_GEN_PARAMS, 0.05268, price_param="quality", price_table=_GPT25_TABLE, fixed_payload=_SAFE),
    _gen("gpt-image-2.5-sunburst", "GPT Image 2.5 Sunburst", "openai", "openai/gpt-image-2.5/sunburst/text-to-image",
         _GPT25_GEN_PARAMS, 0.05268, price_param="quality", price_table=_GPT25_TABLE, fixed_payload=_SAFE),
    _gen("gpt-image-2", "GPT Image 2", "openai", "openai/gpt-image-2",
         {"image_size": _size_param("square_hd"), "quality": _opt(_GPT2_QUALITY, "high")}, 0.211,
         price_param="quality", price_table=_GPT2_TABLE, fixed_payload=_SAFE),
    # Pricing above 1k is unpublished, so resolution stays fixed. safety_tolerance is an integer here: never sent.
    _gen("flux-3", "FLUX.3", "black-forest-labs", "blackforestlabs/flux-3/text-to-image",
         {"aspect_ratio": _opt(FLUX3_ASPECTS, "1:1")}, 0.048, fixed_payload={"resolution": "1k"}),
    _gen("flux-3-klein", "FLUX.3 Klein", "black-forest-labs", "blackforestlabs/flux-3/klein/text-to-image",
         {"image_size": _size_param("square_hd"), "seed": {}}, 0.009, fixed_payload=_SAFE_NOEXP),
    _gen("flux-2-pro", "FLUX.2 Pro", "black-forest-labs", "fal-ai/flux-2-pro",
         {"image_size": _size_param("landscape_4_3", custom=True), "safety_tolerance": _opt(SAFETY_1_5, "2"), "seed": {}},
         0.03, pricing_strategy_key="flux_2_pro_mp"),
    _gen("flux-2-max", "FLUX.2 Max", "black-forest-labs", "fal-ai/flux-2-max",
         {"image_size": _size_param("landscape_4_3", custom=True), "safety_tolerance": _opt(SAFETY_1_5, "2"), "seed": {}},
         0.07),
    _gen("flux-2", "FLUX.2", "black-forest-labs", "fal-ai/flux-2", _steps_params(4, 2.5), 0.012,
         lora_endpoint="fal-ai/flux-2/lora", supports_lora=True, trainable=True,
         trainer_endpoint="fal-ai/flux-2-trainer-v2", lora_price=0.021, fixed_payload=_SAFE),
    _gen("qwen-image-2512", "Qwen Image 2512", "alibaba", "fal-ai/qwen-image-2512", _steps_params(1, 4.0), 0.02,
         lora_endpoint="fal-ai/qwen-image-2512/lora", supports_lora=True, trainable=True,
         trainer_endpoint="fal-ai/qwen-image-2512-trainer-v2", lora_price=0.035,
         fixed_payload={"enable_safety_checker": False}),
    _gen("seedream-5-pro", "Seedream 5 Pro", "bytedance", "bytedance/seedream/v5/pro/text-to-image",
         {"image_size": _size_param("auto_2K", presets=SEEDREAM_SIZES)}, 0.135,
         price_param="image_size", price_table=_SEEDREAM_PRO_TABLE, fixed_payload=_SAFE),
    _gen("seedream-5-flash", "Seedream 5 Flash", "bytedance", "bytedance/seedream/v5/flash/text-to-image",
         {"image_size": _size_param("auto_2K", presets=SEEDREAM_SIZES)}, 0.027, fixed_payload=_SAFE),
    _gen("qwen-image-3", "Qwen Image 3", "alibaba", "alibaba/qwen-image-3/text-to-image",
         {"image_size": _size_param("square_hd"), "negative_prompt": {}, "seed": {}}, 0.04,
         fixed_payload=_SAFE_NOEXP),
    _gen("grok-imagine-quality", "Grok Imagine Quality", "xai", "xai/grok-imagine-image/quality/text-to-image",
         {"aspect_ratio": _opt(GROK_ASPECTS, "1:1"), "resolution": _opt(["1k", "2k"], "1k")}, 0.05,
         price_param="resolution", price_table={"1k": 0.05, "2k": 0.07}),
    _gen("grok-imagine-v2", "Grok Imagine v2", "xai", "xai/grok-imagine-image/v2.0/text-to-image",
         {"aspect_ratio": _opt(GROK_ASPECTS, "1:1"), "resolution": _opt(["1k", "2k"], "1k")}, 0.06,
         price_param="resolution", price_table={"1k": 0.06, "2k": 0.08}, fixed_payload={"quality": "medium"}),
    _gen("ideogram-v4.5", "Ideogram v4.5", "ideogram", "ideogram/v4.5",
         {"image_size": _size_param("square_hd"), "quality": _opt(_GPT2_QUALITY, "medium"), "seed": {}}, 0.06,
         price_param="quality", price_table=_IDEOGRAM_TABLE, supports_output_format=False,
         fixed_payload=_SAFE_NOEXP),
    # --- Edit ---
    _edit("nano-banana-2.1-edit", "Nano Banana 2.1", "google", "google/nano-banana-2.1/edit",
          _nano_params(True, True, "auto"), 0.044, 14, price_param="resolution", price_table=_NB21_EDIT_TABLE,
          is_default=True),
    _edit("nano-banana-pro-edit", "Nano Banana Pro", "google", "fal-ai/nano-banana-pro/edit",
          _nano_params(True, True, "auto"), 0.15, 14, pricing_strategy_key="nano_banana_pro_edit"),
    _edit("nano-banana-lite-edit", "Nano Banana Lite", "google", "google/nano-banana-lite/edit",
          _nano_params(False, False, "auto"), 0.042, 14),
    _edit("gpt-image-2.5-flare-edit", "GPT Image 2.5 Flare", "openai", "openai/gpt-image-2.5/flare/edit",
          _GPT25_EDIT_PARAMS, 0.05268, 16, price_param="quality", price_table=_GPT25_TABLE, fixed_payload=_SAFE),
    _edit("gpt-image-2.5-sunburst-edit", "GPT Image 2.5 Sunburst", "openai", "openai/gpt-image-2.5/sunburst/edit",
          _GPT25_EDIT_PARAMS, 0.05268, 16, price_param="quality", price_table=_GPT25_TABLE, fixed_payload=_SAFE),
    _edit("gpt-image-2-edit", "GPT Image 2", "openai", "openai/gpt-image-2/edit",
          {"image_size": _size_param("auto", ["auto"]), "quality": _opt(_GPT2_QUALITY, "high")}, 0.211, 16,
          price_param="quality", price_table=_GPT2_TABLE, fixed_payload=_SAFE),
    _edit("flux-3-edit", "FLUX.3", "black-forest-labs", "blackforestlabs/flux-3/edit-image",
          {"aspect_ratio": _opt(FLUX3_ASPECTS, "auto")}, 0.048, 10, max_num_images=0,
          fixed_payload={"resolution": "1k"}),
    _edit("flux-3-klein-edit", "FLUX.3 Klein", "black-forest-labs", "blackforestlabs/flux-3/klein/edit-image",
          {"image_size": _size_param(None), "seed": {}}, 0.009, 10, fixed_payload=_SAFE_NOEXP),
    _edit("flux-2-pro-edit", "FLUX.2 Pro", "black-forest-labs", "fal-ai/flux-2-pro/edit",
          {"image_size": _size_param("auto", ["auto"]), "safety_tolerance": _opt(SAFETY_1_5, "2"), "seed": {}},
          0.045, 8, max_num_images=0),
    _edit("flux-2-max-edit", "FLUX.2 Max", "black-forest-labs", "fal-ai/flux-2-max/edit",
          {"image_size": _size_param("auto", ["auto"]), "safety_tolerance": _opt(SAFETY_1_5, "2"), "seed": {}},
          0.10, 8, max_num_images=0),
    _edit("flux-2-lora-edit", "FLUX.2 LoRA", "black-forest-labs", "fal-ai/flux-2/lora/edit",
          {"image_size": _size_param("landscape_4_3", custom=True), "seed": {}}, 0.042, 4,
          fixed_payload={"loras": [], "enable_safety_checker": True, "enable_prompt_expansion": False}),
    _edit("seedream-5-pro-edit", "Seedream 5 Pro", "bytedance", "bytedance/seedream/v5/pro/edit",
          {"image_size": _size_param("auto_2K", presets=SEEDREAM_SIZES)}, 0.135, 10,
          price_param="image_size", price_table=_SEEDREAM_PRO_TABLE, fixed_payload=_SAFE),
    _edit("seedream-5-flash-edit", "Seedream 5 Flash", "bytedance", "bytedance/seedream/v5/flash/edit",
          {"image_size": _size_param("auto_2K", presets=SEEDREAM_SIZES)}, 0.027, 10, fixed_payload=_SAFE),
    _edit("qwen-image-3-edit", "Qwen Image 3", "alibaba", "alibaba/qwen-image-3/edit",
          {"image_size": _size_param(None), "negative_prompt": {}, "seed": {}}, 0.04, 6,
          fixed_payload=_SAFE_NOEXP),
    _edit("grok-imagine-quality-edit", "Grok Imagine Quality", "xai", "xai/grok-imagine-image/quality/edit",
          {"aspect_ratio": _opt(["auto"] + GROK_ASPECTS, "auto"), "resolution": _opt(["1k", "2k"], "1k")}, 0.06, 4,
          price_param="resolution", price_table={"1k": 0.06, "2k": 0.08}),
    _edit("grok-imagine-v2-edit", "Grok Imagine v2", "xai", "xai/grok-imagine-image/v2.0/edit",
          {"aspect_ratio": _opt(["auto"] + GROK_ASPECTS, "auto"), "resolution": _opt(["1k", "2k"], "1k")}, 0.07, 4,
          price_param="resolution", price_table={"1k": 0.07, "2k": 0.09}, fixed_payload={"quality": "medium"}),
    _edit("kling-image", "Kling Image", "kuaishou", "fal-ai/kling-image/o3/image-to-image",
          {"resolution": _opt(_RES_1K_4K, "1K"), "aspect_ratio": _opt(KLING_ASPECTS, "auto")}, 0.028, 10,
          max_num_images=9, price_param="resolution", price_table={"1K": 0.028, "2K": 0.028, "4K": 0.056}),
    # The singular image_url endpoint takes exactly one source image.
    _edit("ideogram-v4.5-edit", "Ideogram v4.5", "ideogram", "ideogram/v4.5/edit",
          {"image_size": _size_param("auto", ["auto"]), "quality": _opt(_GPT2_QUALITY, "medium"), "seed": {}},
          0.06, 1, uses_single_image_url=True, supports_output_format=False,
          price_param="quality", price_table=_IDEOGRAM_TABLE, fixed_payload=_SAFE),
)

_IMAGE_BY_KEY: dict[tuple[str, str], ImageModel] = {(m.kind, m.key): m for m in IMAGE_MODELS}

DEFAULT_GENERATION_MODEL = next(m.key for m in IMAGE_MODELS if m.kind == _GEN and m.is_default)
DEFAULT_EDIT_MODEL = next(m.key for m in IMAGE_MODELS if m.kind == _EDIT and m.is_default)

# Base models that were offered before the 2026-10 refresh.  Historical LoRA rows
# can still reference them (listing, detail, recover) but they are never offered
# for new generation, training or editing.
LEGACY_TRAINER_ENDPOINTS: dict[str, dict] = {
    "flux-dev": {
        "training_endpoint": "fal-ai/flux-lora-fast-training",
        "zip_param": "images_data_url",
        "supports_trigger_word": True,
        "supports_is_style": True,
        "supports_base64": True,
    },
    "qwen-2.5": {
        "training_endpoint": "fal-ai/qwen-image-2512-trainer-v2",
        "zip_param": "image_data_url",
        "supports_trigger_word": False,
        "supports_is_style": False,
        "supports_base64": False,
    },
}


def get_image_model(key: str | None, kind: str) -> ImageModel | None:
    """Return the offered image model for (*key*, *kind*), or None."""
    return _IMAGE_BY_KEY.get((kind, key)) if key else None


def offered_keys(kind: str) -> list[str]:
    return [m.key for m in IMAGE_MODELS if m.kind == kind]


def image_models(kind: str) -> list[ImageModel]:
    return [m for m in IMAGE_MODELS if m.kind == kind]


def trainable_keys() -> list[str]:
    return [m.key for m in IMAGE_MODELS if m.trainable]


def image_model_for_endpoint(endpoint: str, kind: str) -> tuple[ImageModel, bool] | None:
    """Reverse lookup by fal endpoint → (model, is_lora_endpoint)."""
    for m in IMAGE_MODELS:
        if m.kind != kind:
            continue
        if m.endpoint == endpoint:
            return m, False
        if m.lora_endpoint == endpoint:
            return m, True
    return None
