"""Pure functions for estimating token counts for vision API cost previews.

No DB dependency except the static model catalog — caller provides dimensions and text.
All vision/language calls run through fal's OpenRouter routers, so image
formulas are chosen by the model's vendor prefix (``anthropic/...``):
  - anthropic:           pixels/750 with 1568px side cap + ~1.19M pixel area cap
  - openai:              not officially documented, empirical ~pixels/850 (2048 long cap + 1.5M area cap)
  - google (Gemini):     tile-based (768x768 tiles, 258 tokens/tile; <=384px = 258 flat)
  - qwen:                32x32 effective patches (pixels/1024)
  - x-ai (Grok):         undisclosed formula, documented range 256–1792 tokens/image
  - others:              Anthropic-style heuristic

Cost estimation always uses these formulas. Actual billing uses real token
counts from provider API responses.
"""
import logging
import math

from app.services.model_catalog import get_language_model

logger = logging.getLogger(__name__)

# --- Output token estimates by mode ---
# Non-reasoning models produce only visible output tokens.  Reasoning-heavy
# models (flagged ``reasoning_heavy`` in the model catalog) also burn invisible
# reasoning tokens that providers count as completion_tokens.
#
# Empirical data (gpt-5-mini, 4 tag / 5 describe samples):
#   tag:      avg 823 total (avg ~700 reasoning + ~100 visible)
#   describe: avg 723 total (avg ~350 reasoning + ~350 visible)
_OUTPUT_TOKENS_STANDARD = {"tag": 50, "describe": 300, "custom": 250}
_OUTPUT_TOKENS_REASONING = {"tag": 2048, "describe": 2048, "custom": 2048}

# Keep for backward compatibility — callers that don't pass model info
DEFAULT_OUTPUT_TOKENS = {"tag": 500, "describe": 700, "custom": 600}


def estimate_output_tokens(model: str, mode: str) -> int:
    """Estimate output tokens for a vision operation, accounting for reasoning overhead."""
    lm = get_language_model(model)
    if lm is not None and lm.reasoning_heavy:
        return _OUTPUT_TOKENS_REASONING.get(mode, 2048)
    return _OUTPUT_TOKENS_STANDARD.get(mode, 250)


def estimate_image_tokens(model: str, width: int, height: int) -> int:
    """Estimate input tokens consumed by an image for a given OpenRouter model id."""
    vendor = model.split("/", 1)[0] if "/" in model else ""
    if vendor == "openai":
        tokens = _gpt5_standard_image_tokens(width, height)
    elif vendor == "google":
        tokens = _gemini_image_tokens(width, height)
    elif vendor == "qwen":
        tokens = _qwen3_image_tokens(width, height)
    elif vendor == "x-ai":
        tokens = _grok_image_tokens(width, height)
    else:
        # anthropic and models without a published formula
        tokens = _anthropic_image_tokens(width, height)
    logger.debug("IMAGE_TOKENS | %s %dx%d → %d tokens", model, width, height, tokens)
    return tokens


def _gpt5_standard_image_tokens(width: int, height: int) -> int:
    """OpenAI GPT image token estimation (empirically derived on GPT-5.2).

    Empirically derived (2026-02-25) from 8 test images (100x100 to 4540x5675):
      1. Cap longest side at 2048 (consistent with OpenAI high-detail behavior)
      2. Cap total pixel area at ~1,500,000 (similar to Anthropic's area cap)
      3. Divide by 850

    Accuracy: <3% error for images >250K pixels. Small images may underestimate.
    """
    w, h = width, height

    # Step 1: cap longest side at 2048
    longest = max(w, h)
    if longest > 2048:
        scale = 2048 / longest
        w = int(w * scale)
        h = int(h * scale)

    # Step 2: cap total area at ~1,500,000 pixels
    max_pixels = 1_500_000
    pixels = w * h
    if pixels > max_pixels:
        pixels = max_pixels

    return max(20, pixels // 850)


def _anthropic_image_tokens(width: int, height: int) -> int:
    """Anthropic image token estimation.

    Anthropic applies two constraints before tokenizing:
      1. No side exceeds 1568px (scale longest side down)
      2. Total area doesn't exceed ~1,192,500 pixels (~1590 tokens)
    Then charges pixels / 750.

    Reference (no-resize max sizes from Anthropic docs):
      1:1 → 1092x1092 → ~1590 tokens
      3:4 → 951x1268  → ~1608 tokens
      1:2 → 784x1568  → ~1639 tokens
    """
    w, h = width, height

    # Constraint 1: cap longest side at 1568px
    longest = max(w, h)
    if longest > 1568:
        scale = 1568 / longest
        w = int(w * scale)
        h = int(h * scale)

    # Constraint 2: cap total area at ~1,192,500 pixels (~1590 tokens)
    max_pixels = 1_192_500
    if w * h > max_pixels:
        scale = (max_pixels / (w * h)) ** 0.5
        w = int(w * scale)
        h = int(h * scale)

    return max(1, (w * h) // 750)


def _gemini_image_tokens(width: int, height: int) -> int:
    """Gemini image token estimation.

    If both dimensions <= 384px: 258 tokens flat.
    Otherwise: ceil(w/768) * ceil(h/768) tiles, 258 tokens per tile.
    """
    if width <= 384 and height <= 384:
        return 258
    tiles_w = math.ceil(width / 768)
    tiles_h = math.ceil(height / 768)
    return tiles_w * tiles_h * 258


def _qwen3_image_tokens(width: int, height: int) -> int:
    """Qwen3-VL image token estimation.

    Uses 32x32 effective patches (16x16 base with 4-patch merging).
    Default range: 4–16,384 tokens per image.
    """
    patches_w = math.ceil(width / 32)
    patches_h = math.ceil(height / 32)
    return max(4, min(16384, patches_w * patches_h))


def _grok_image_tokens(width: int, height: int) -> int:
    """Grok (xAI) image token estimation.

    xAI documents 256–1792 tokens per image with no public formula.
    Empirical data shows ~668-739 input tokens for typical images via OpenRouter,
    suggesting aggressive resizing. Approximate as pixels/1600 clamped to
    the documented range.
    """
    tokens = max(1, (width * height) // 1600)
    return max(256, min(1792, tokens))


def _scale_image(width: int, height: int, max_long: int, max_short: int) -> tuple[int, int]:
    """Scale image dimensions like OpenAI's high-detail processing."""
    w, h = width, height

    # Step 1: scale so longest side <= max_long
    longest = max(w, h)
    if longest > max_long:
        scale = max_long / longest
        w = int(w * scale)
        h = int(h * scale)

    # Step 2: scale so shortest side <= max_short
    shortest = min(w, h)
    if shortest > max_short:
        scale = max_short / shortest
        w = int(w * scale)
        h = int(h * scale)

    return max(1, w), max(1, h)


def estimate_prompt_tokens(text: str) -> int:
    """Estimate tokens from text.

    BPE tokenizers (cl100k, o200k) average ~4.3 chars per token for English
    with mixed technical content. Verified against tiktoken:
      1356-char prompt → 318 tokens (4.26 chars/tok)
      1240-char prompt → 243 tokens (5.10 chars/tok)
    """
    if not text:
        return 0
    return max(1, int(len(text) / 4.3))


def estimate_vision_input_tokens(model: str, width: int, height: int, prompt_text: str) -> int:
    """Total input tokens: image tokens + prompt tokens."""
    img = estimate_image_tokens(model, width, height)
    prompt = estimate_prompt_tokens(prompt_text)
    total = img + prompt
    logger.debug("VISION_INPUT | %s | img=%d + prompt=%d = %d total", model, img, prompt, total)
    return total


def estimate_embed_tokens(tags: list[str] | None = None, description: str | None = None) -> int:
    """Estimate embedding input tokens from actual metadata text.

    When metadata is available, compute from real text. Otherwise default ~350.
    """
    if tags is None and description is None:
        return 350

    text_parts = []
    if tags:
        text_parts.append(", ".join(tags))
    if description:
        text_parts.append(description)

    combined = " ".join(text_parts)
    tokens = estimate_prompt_tokens(combined)
    return max(1, tokens) if combined else 350
