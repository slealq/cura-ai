#!/usr/bin/env python3
"""Quick verification of gpt-5.2 image tokenization.

Tests multiple image sizes to find the actual formula.
Usage: cd backend && python tests/verify_gpt52_tokens.py
"""
import asyncio
import base64
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AsyncOpenAI
from PIL import Image

# Test a range of image sizes to determine the formula
TEST_SIZES = [
    (100, 100),    # tiny
    (299, 168),    # the user's test image
    (512, 512),    # 1 tile
    (768, 768),    # medium
    (1024, 1024),  # standard
    (2048, 1024),  # wide
    (4000, 3000),  # large
    (4540, 5675),  # alex-ifti test image
]

PROMPT = "Say OK"  # Minimal prompt to isolate image tokens


def make_test_image(width: int, height: int) -> str:
    """Create a solid color test image and return base64."""
    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=50)
    return base64.b64encode(buf.getvalue()).decode()


async def test_image(client, width: int, height: int, base64_image: str):
    """Make API call and return token usage."""
    response = await client.chat.completions.create(
        model="gpt-5.2",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}",
                        "detail": "high",
                    },
                },
            ],
        }],
        max_completion_tokens=10,
    )
    usage = response.usage
    model = response.model
    return {
        "model": model,
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


async def test_text_only(client):
    """Get baseline prompt tokens with no image."""
    response = await client.chat.completions.create(
        model="gpt-5.2",
        messages=[{"role": "user", "content": PROMPT}],
        max_completion_tokens=10,
    )
    return {
        "model": response.model,
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
    }


async def main():
    # Get API key
    from app.db.base import SessionLocal
    from app.models.api_key import APIProvider
    from app.services.api_key_service import APIKeyService

    db = SessionLocal()
    api_key_svc = APIKeyService(db, user_id=1)
    api_key = api_key_svc.resolve_key(APIProvider.OPENAI)
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
    db.close()
    if not api_key:
        print("ERROR: No API key found")
        sys.exit(1)

    client = AsyncOpenAI(api_key=api_key)

    # Baseline: text-only to find prompt overhead
    print("=== BASELINE (text only) ===")
    baseline = await test_text_only(client)
    prompt_overhead = baseline["input_tokens"]
    print(f"Model: {baseline['model']}")
    print(f"Prompt overhead ('{PROMPT}'): {prompt_overhead} tokens")
    print()

    # Test each image size
    print(f"{'Dimensions':>12s} {'Pixels':>10s} {'Input':>7s} {'ImgTok':>7s} {'px/tok':>7s} {'px/500':>7s} {'tiles':>5s} {'tile*170+85':>12s}")
    print("-" * 80)

    for w, h in TEST_SIZES:
        base64_img = make_test_image(w, h)
        try:
            result = await test_image(client, w, h, base64_img)
            img_tokens = result["input_tokens"] - prompt_overhead
            pixels = w * h
            px_per_tok = pixels / img_tokens if img_tokens > 0 else 0

            # Check tile formula (gpt-4o style)
            from app.services.token_estimator import _scale_image
            sw, sh = _scale_image(w, h, 2048, 768)
            import math
            tiles_w = math.ceil(sw / 512)
            tiles_h = math.ceil(sh / 512)
            tiles = tiles_w * tiles_h
            tile_formula = tiles * 170 + 85

            print(
                f"{w:>5d}x{h:<5d} {pixels:>10d} {result['input_tokens']:>7d} {img_tokens:>7d} "
                f"{px_per_tok:>7.0f} {pixels//500:>7d} {tiles:>5d} {tile_formula:>12d}"
            )
        except Exception as e:
            print(f"{w:>5d}x{h:<5d} ERROR: {e}")

    print()
    print("ImgTok = actual image tokens (input - prompt overhead)")
    print("px/tok = pixels per token ratio")
    print("px/500 = our current gpt-5 formula (without min 800)")
    print("tile*170+85 = gpt-4o documented formula")


if __name__ == "__main__":
    asyncio.run(main())
