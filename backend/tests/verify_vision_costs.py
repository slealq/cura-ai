#!/usr/bin/env python3
"""Vision Cost Estimation Verification Test

Makes real API calls to OpenAI (gpt-4o-mini, gpt-5-mini) with a known image,
compares estimated vs actual token counts and costs.

Usage:
    cd backend && python tests/verify_vision_costs.py
"""
import asyncio
import base64
import json
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

from openai import AsyncOpenAI

from app.services.settings_service import (
    DEFAULT_DESCRIPTION_GUIDANCE,
    DEFAULT_TAG_GUIDANCE,
    compose_description_prompt,
    compose_tag_prompt,
)
from app.services.token_estimator import (
    DEFAULT_OUTPUT_TOKENS,
    estimate_image_tokens,
    estimate_prompt_tokens,
)

# ── Config ──────────────────────────────────────────────────────────────────
IMAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "storage", "images", "250d1dc1838242b59b03e7380184064e.jpg",
)
IMAGE_DIMS = (4540, 5675)  # From DB: image id=353 alex-ifti-WFp3PHoizDw-unsplash.jpg
IMAGE_NAME = "alex-ifti-WFp3PHoizDw-unsplash.jpg"

MODELS = ["gpt-4o-mini", "gpt-5-mini"]
OPERATIONS = ["tag", "describe"]

# Catalog rates (from cost_catalog table)
CATALOG = {
    "gpt-4o-mini": {"cost_per_input_token": Decimal("0.000000150"), "cost_per_output_token": Decimal("0.000000600"), "markup": Decimal("2.0")},
    "gpt-5-mini":  {"cost_per_input_token": Decimal("0.000000250"), "cost_per_output_token": Decimal("0.000002000"), "markup": Decimal("2.0")},
}
USD_TO_SPARKS = Decimal("1000")


def build_prompts():
    """Build the exact prompts sent to the API."""
    return {
        "tag": compose_tag_prompt(DEFAULT_TAG_GUIDANCE),
        "describe": compose_description_prompt(DEFAULT_DESCRIPTION_GUIDANCE),
    }


def estimate_costs(model, operation, prompt_text, width, height):
    """Compute pre-run cost estimate using our formulas."""
    img_tokens = estimate_image_tokens("openai", model, width, height)
    prompt_tokens = estimate_prompt_tokens(prompt_text)
    est_input = img_tokens + prompt_tokens
    est_output = DEFAULT_OUTPUT_TOKENS.get(operation, 500)

    cat = CATALOG[model]
    raw_cost = cat["cost_per_input_token"] * est_input + cat["cost_per_output_token"] * est_output
    charged = raw_cost * cat["markup"]
    sparks = charged * USD_TO_SPARKS

    return {
        "image_tokens": img_tokens,
        "prompt_tokens": prompt_tokens,
        "est_input_total": est_input,
        "est_output": est_output,
        "raw_cost_usd": raw_cost,
        "charged_cost_usd": charged,
        "sparks": sparks,
    }


def actual_costs(model, input_tokens, output_tokens):
    """Compute actual cost from real token counts."""
    cat = CATALOG[model]
    raw_cost = cat["cost_per_input_token"] * input_tokens + cat["cost_per_output_token"] * output_tokens
    charged = raw_cost * cat["markup"]
    sparks = charged * USD_TO_SPARKS
    return {
        "raw_cost_usd": raw_cost,
        "charged_cost_usd": charged,
        "sparks": sparks,
    }


async def make_api_call(client, model, operation, prompt_text, base64_image, mime_type="image/jpeg"):
    """Make the actual OpenAI API call exactly as the codebase does."""
    max_tok_key = "max_completion_tokens" if model.startswith("gpt-5") else "max_tokens"
    max_tok_val = 1000 if operation == "tag" else 3000
    # Reasoning models get 2x buffer
    if model.startswith("gpt-5"):
        max_tok_val *= 2

    kwargs = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        max_tok_key: max_tok_val,
        "response_format": {"type": "json_object"},
    }

    response = await client.chat.completions.create(**kwargs)

    content = response.choices[0].message.content
    usage = response.usage

    return {
        "content": content,
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "model_reported": response.model,
    }


async def run_tests():
    """Run all verification tests."""
    # Load image
    with open(IMAGE_PATH, "rb") as f:
        image_data = f.read()
    base64_image = base64.b64encode(image_data).decode("utf-8")
    image_size_kb = len(image_data) / 1024

    prompts = build_prompts()
    width, height = IMAGE_DIMS

    # Get the API key from the app's encrypted key store (same as the app uses)
    from app.db.base import SessionLocal
    from app.models.api_key import APIProvider
    from app.services.api_key_service import APIKeyService

    db = SessionLocal()
    api_key_svc = APIKeyService(db, user_id=1)  # admin user
    api_key = api_key_svc.resolve_key(APIProvider.OPENAI)
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
    db.close()
    if not api_key:
        print("ERROR: No OpenAI API key found in DB or environment")
        sys.exit(1)

    client = AsyncOpenAI(api_key=api_key)

    results = []

    for model in MODELS:
        for operation in OPERATIONS:
            prompt_text = prompts[operation]

            # Pre-compute estimates
            est = estimate_costs(model, operation, prompt_text, width, height)

            print(f"\n{'='*80}")
            print(f"TEST: {model} / {operation}")
            print(f"{'='*80}")
            print(f"Image: {IMAGE_NAME} ({width}x{height}, {image_size_kb:.0f} KB)")
            print(f"Prompt: {len(prompt_text)} chars")
            print()

            # Estimation breakdown
            print("── ESTIMATION (pre-run) ──")
            print(f"  Image tokens (formula):    {est['image_tokens']}")
            print(f"  Prompt tokens (chars/4):   {est['prompt_tokens']}")
            print(f"  Est. total input:          {est['est_input_total']}")
            print(f"  Est. output (default):     {est['est_output']}")
            print(f"  Est. raw cost:             ${float(est['raw_cost_usd']):.8f}")
            print(f"  Est. charged (2x markup):  ${float(est['charged_cost_usd']):.8f}")
            print(f"  Est. sparks:               {float(est['sparks']):.2f}")
            print()

            # Make actual API call
            print("── ACTUAL API CALL ──")
            try:
                resp = await make_api_call(client, model, operation, prompt_text, base64_image)
            except Exception as e:
                print(f"  ERROR: {e}")
                continue

            act = actual_costs(model, resp["input_tokens"], resp["output_tokens"])

            print(f"  Model returned:            {resp['model_reported']}")
            print(f"  Actual input tokens:       {resp['input_tokens']}")
            print(f"  Actual output tokens:      {resp['output_tokens']}")
            print(f"  Actual total tokens:       {resp['total_tokens']}")
            print(f"  Actual raw cost:           ${float(act['raw_cost_usd']):.8f}")
            print(f"  Actual charged (2x):       ${float(act['charged_cost_usd']):.8f}")
            print(f"  Actual sparks:             {float(act['sparks']):.2f}")
            print()

            # Parse response content
            try:
                parsed = json.loads(resp["content"])
                if operation == "tag":
                    tags = parsed.get("tags", [])
                    print(f"  Tags returned: {len(tags)} — {tags[:5]}{'...' if len(tags) > 5 else ''}")
                else:
                    desc = parsed.get("description", "")
                    print(f"  Description: {len(desc)} chars — \"{desc[:80]}...\"")
            except json.JSONDecodeError:
                print(f"  Raw content: {resp['content'][:200]}")
            print()

            # Comparison
            print("── COMPARISON ──")
            input_delta = resp["input_tokens"] - est["est_input_total"]
            input_pct = (input_delta / resp["input_tokens"]) * 100 if resp["input_tokens"] > 0 else 0
            output_delta = resp["output_tokens"] - est["est_output"]
            spark_delta = float(act["sparks"]) - float(est["sparks"])
            spark_pct = (spark_delta / float(act["sparks"])) * 100 if float(act["sparks"]) > 0 else 0

            print(f"  Input tokens:  est={est['est_input_total']:>6d}  actual={resp['input_tokens']:>6d}  delta={input_delta:>+6d} ({input_pct:>+.1f}%)")
            print(f"  Output tokens: est={est['est_output']:>6d}  actual={resp['output_tokens']:>6d}  delta={output_delta:>+6d}")
            print(f"  Sparks:        est={float(est['sparks']):>7.2f}  actual={float(act['sparks']):>7.2f}  delta={spark_delta:>+.2f} ({spark_pct:>+.1f}%)")

            results.append({
                "model": model,
                "operation": operation,
                "image": IMAGE_NAME,
                "dims": f"{width}x{height}",
                "est_input": est["est_input_total"],
                "actual_input": resp["input_tokens"],
                "input_delta_pct": input_pct,
                "est_output": est["est_output"],
                "actual_output": resp["output_tokens"],
                "est_sparks": float(est["sparks"]),
                "actual_sparks": float(act["sparks"]),
                "spark_delta_pct": spark_pct,
            })

    # Summary table
    print(f"\n\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"{'Model':<14s} {'Op':<10s} {'Est In':>8s} {'Act In':>8s} {'Δ%':>8s} {'Est Out':>8s} {'Act Out':>8s} {'Est ⚡':>8s} {'Act ⚡':>8s} {'Δ%':>8s}")
    print("-" * 98)
    for r in results:
        print(f"{r['model']:<14s} {r['operation']:<10s} {r['est_input']:>8d} {r['actual_input']:>8d} {r['input_delta_pct']:>+7.1f}% {r['est_output']:>8d} {r['actual_output']:>8d} {r['est_sparks']:>8.2f} {r['actual_sparks']:>8.2f} {r['spark_delta_pct']:>+7.1f}%")


if __name__ == "__main__":
    asyncio.run(run_tests())
