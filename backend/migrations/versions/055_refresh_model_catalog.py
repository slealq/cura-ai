"""Refresh the model catalog: fal-only vision/language, new image models, billing rows.

Seeds cost_catalog rows for every model offered by ``app.services.model_catalog``,
deactivates (never deletes) rows for providers/models that were removed, and resets
stored per-user model settings to the new defaults.

The data below is deliberately literal (no app imports) so the migration stays
reproducible; ``tests/test_model_catalog_billing_drift.py`` keeps it in sync with
the catalog.

Revision ID: 055_refresh_model_catalog
Revises: 054_add_frontier_fal_models
Create Date: 2026-10-30
"""
import json
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "055_refresh_model_catalog"
down_revision: Union[str, None] = "054_add_frontier_fal_models"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

PLATFORM_MARKUP = "2.0"

# Operations that call a language/vision model (mirrors model_catalog.LANGUAGE_OPERATIONS).
LANGUAGE_OPERATIONS = (
    "tag", "describe", "custom", "evaluate", "evaluate_creative",
    "summarize_eval", "generate_prompts", "summarize", "expand_prompt", "suggest_prompt",
)

# {model_id: (input USD per token, output USD per token)} via fal's OpenRouter routers.
# Base rates are stored here; catalog metadata applies long-prompt tiers in fallback
# calculations. The higher time-dependent rate is used as an estimate.
LANGUAGE_RATES = {
    "anthropic/claude-haiku-5.5": ("0.0000001", "0.0000005"),
    "anthropic/claude-sonnet-5.5": ("0.000002", "0.00001"),
    "anthropic/claude-opus-5.5": ("0.000004", "0.00002"),
    "openai/gpt-6-luna": ("0.0000001", "0.0000005"),
    "openai/gpt-6.1-terra": ("0.000001", "0.000005"),
    "openai/gpt-6.1-sol": ("0.000002", "0.00001"),
    "openai/gpt-6-astra": ("0.00001", "0.00005"),
    "google/gemini-3.5-flash-lite": ("0.0000003", "0.0000025"),
    "google/gemini-3.8-flash": ("0.000000825", "0.000004125"),
    "google/gemini-4-argon": ("0.000002", "0.00001"),
    "x-ai/grok-4.3": ("0.00000125", "0.0000025"),
    "deepseek/deepseek-v4.1-flash": ("0.000000045", "0.0000005"),
    "moonshotai/kimi-k3.1-pro": ("0.000002", "0.00001"),
    "z-ai/glm-5.3-flash": ("0.000000018", "0.0000001402"),
    "z-ai/glm-5.3-flashx": ("0.00000037", "0.00000125"),
    "minimax/minimax-m3.1-flash": ("0.00000015", "0.0000006"),
    "minimax/minimax-m3": ("0.0000003", "0.0000012"),
}

FLUX_2_BASE_RULES = json.dumps({'pricing_type': 'megapixel', 'first_mp_cost': 0.012, 'extra_mp_cost': 0.012, 'default_width': 1024, 'default_height': 1024})
FLUX_2_LORA_RULES = json.dumps({
    "pricing_type": "megapixel",
    "first_mp_cost": 0.021,
    "extra_mp_cost": 0.021,
    "default_width": 1024,
    "default_height": 1024,
})

# (catalog_model, operation, cost_per_call, pricing_rules). pricing_rules=None keeps any
# existing rules on the row.  Variable pricing itself lives in app.services.pricing_engine.
IMAGE_ROWS = [
    ("fal-ai/nano-banana-pro", "generate", 0.15, None),
    ("google/nano-banana-lite", "generate", 0.042, None),
    ("openai/gpt-image-2.5/flare/text-to-image", "generate", 0.05268, None),
    ("openai/gpt-image-2.5/sunburst/text-to-image", "generate", 0.05268, None),
    ("openai/gpt-image-2", "generate", 0.211, None),
    ("blackforestlabs/flux-3/text-to-image", "generate", 0.048, None),
    ("blackforestlabs/flux-3/klein/text-to-image", "generate", 0.009, None),
    ("fal-ai/flux-2-pro", "generate", 0.03, None),
    ("fal-ai/flux-2-max", "generate", 0.07, None),
    ("fal-ai/flux-2", "generate", 0.012, FLUX_2_BASE_RULES),
    ("fal-ai/flux-2/lora", "generate", 0.021, FLUX_2_LORA_RULES),
    ("fal-ai/qwen-image-2512", "generate", 0.02, None),
    ("fal-ai/qwen-image-2512/lora", "generate", 0.035, None),
    ("bytedance/seedream/v5/pro/text-to-image", "generate", 0.135, None),
    ("bytedance/seedream/v5/flash/text-to-image", "generate", 0.027, None),
    ("alibaba/qwen-image-3/text-to-image", "generate", 0.04, None),
    ("xai/grok-imagine-image/quality/text-to-image", "generate", 0.05, None),
    ("xai/grok-imagine-image/v2.0/text-to-image", "generate", 0.06, None),
    ("ideogram/v4.5", "generate", 0.06, None),
    ("google/nano-banana-2.1/edit", "edit", 0.044, None),
    ("google/nano-banana-lite/edit", "edit", 0.042, None),
    ("openai/gpt-image-2.5/flare/edit", "edit", 0.05268, None),
    ("openai/gpt-image-2.5/sunburst/edit", "edit", 0.05268, None),
    ("openai/gpt-image-2/edit", "edit", 0.211, None),
    ("blackforestlabs/flux-3/edit-image", "edit", 0.048, None),
    ("blackforestlabs/flux-3/klein/edit-image", "edit", 0.009, None),
    ("fal-ai/flux-2-pro/edit", "edit", 0.045, None),
    ("fal-ai/flux-2-max/edit", "edit", 0.1, None),
    ("fal-ai/flux-2/lora/edit", "edit", 0.042, None),
    ("bytedance/seedream/v5/pro/edit", "edit", 0.135, None),
    ("bytedance/seedream/v5/flash/edit", "edit", 0.027, None),
    ("alibaba/qwen-image-3/edit", "edit", 0.04, None),
    ("xai/grok-imagine-image/quality/edit", "edit", 0.06, None),
    ("xai/grok-imagine-image/v2.0/edit", "edit", 0.07, None),
    ("fal-ai/kling-image/o3/image-to-image", "edit", 0.028, None),
    ("ideogram/v4.5/edit", "edit", 0.06, None),
]

# Rows whose per-call price changed and whose old JSON rules would now be misleading.
CLEAR_RULES = [
    ("bytedance/seedream/v5/pro/text-to-image", "generate"),
    ("bytedance/seedream/v5/pro/edit", "edit"),
    ("fal-ai/flux-2/lora/edit", "edit"),
]

# IMAGE_ROWS entries that already existed before this migration (see 029/047/054).
# Downgrade deletes every other IMAGE_ROWS entry; these keep their (possibly updated) values.
PRE_EXISTING_IMAGE_ROWS = {
    ("fal-ai/flux-2", "generate"),
    ("fal-ai/flux-2/lora", "generate"),
    ("fal-ai/qwen-image-2512", "generate"),
    ("fal-ai/qwen-image-2512/lora", "generate"),
    ("fal-ai/nano-banana-pro", "generate"),
    ("fal-ai/flux-2-pro", "generate"),
    ("bytedance/seedream/v5/pro/text-to-image", "generate"),
    ("fal-ai/nano-banana-pro/edit", "edit"),
    ("fal-ai/kling-image/o3/image-to-image", "edit"),
    ("bytedance/seedream/v5/pro/edit", "edit"),
    ("fal-ai/flux-2/lora/edit", "edit"),
}

# fal language models removed from the catalog (all operations).
REMOVED_FAL_LANGUAGE_MODELS = (
    "x-ai/grok-4.7",
    "qwen/qwen3.8-flash",
    "qwen/qwen3.8-max-0902",
    "qwen/qwen3.8-max-prime",
    "x-ai/grok-4-fast",
    "x-ai/grok-2-vision-1212",
    "qwen/qwen3-vl-235b-a22b-instruct",
    "google/gemini-2.5-flash",
)

# fal image rows for removed models: (model, operation).
REMOVED_FAL_IMAGE_ROWS = (
    ("google/nano-banana-2.1", "generate"),
    ("fal-ai/nano-banana-pro/edit", "edit"),
    ("fal-ai/flux/dev", "generate"),
    ("fal-ai/flux-lora", "generate"),
    ("fal-ai/nano-banana-2", "generate"),
    ("fal-ai/qwen-image-max/edit", "edit"),
    ("fal-ai/qwen-image-2/pro/edit", "edit"),
    ("fal-ai/wan-25-preview/image-to-image", "edit"),
    ("xai/grok-imagine-image/edit", "edit"),
    ("half-moon-ai/ai-face-swap/faceswapimage", "edit"),
)

# provider_config keys that no longer exist.
STALE_PROVIDER_CONFIG_KEYS = (
    "vision_provider", "language_provider",
    "openai_vision_model", "openai_language_model",
    "anthropic_vision_model", "anthropic_language_model",
)
DEFAULT_LANGUAGE_MODEL = "anthropic/claude-haiku-5.5"
DEFAULT_GENERATION_MODEL = "nano-banana-pro"
DEFAULT_EDIT_MODEL = "nano-banana-2.1-edit"


def _upsert_language(conn, model: str, operation: str, input_rate: str, output_rate: str) -> None:
    conn.execute(
        sa.text("""
            INSERT INTO cost_catalog (provider, model, operation, cost_per_input_token,
                cost_per_output_token, cost_per_call, platform_markup, is_active, created_at, updated_at)
            VALUES ('fal', :model, :operation, :input_rate, :output_rate, 0, :markup, true, NOW(), NOW())
            ON CONFLICT (provider, model, operation) DO UPDATE SET
                cost_per_input_token = EXCLUDED.cost_per_input_token,
                cost_per_output_token = EXCLUDED.cost_per_output_token,
                cost_per_call = EXCLUDED.cost_per_call,
                platform_markup = EXCLUDED.platform_markup,
                is_active = EXCLUDED.is_active,
                updated_at = NOW()
        """),
        {
            "model": model,
            "operation": operation,
            "input_rate": input_rate,
            "output_rate": output_rate,
            "markup": PLATFORM_MARKUP,
        },
    )


def _upsert_image(conn, model: str, operation: str, cost_per_call: float, pricing_rules: str | None) -> None:
    conn.execute(
        sa.text("""
            INSERT INTO cost_catalog (provider, model, operation, cost_per_call, platform_markup,
                pricing_rules, is_active, created_at, updated_at)
            VALUES ('fal', :model, :operation, :cost_per_call, :markup,
                :pricing_rules, true, NOW(), NOW())
            ON CONFLICT (provider, model, operation) DO UPDATE SET
                cost_per_call = EXCLUDED.cost_per_call,
                platform_markup = EXCLUDED.platform_markup,
                pricing_rules = COALESCE(EXCLUDED.pricing_rules, cost_catalog.pricing_rules),
                is_active = EXCLUDED.is_active,
                updated_at = NOW()
        """),
        {
            "model": model,
            "operation": operation,
            "cost_per_call": cost_per_call,
            "markup": PLATFORM_MARKUP,
            "pricing_rules": pricing_rules,
        },
    )


def _set_active(conn, active: bool) -> None:
    """Flip is_active on every row this migration deactivates (and downgrade restores)."""
    # Direct OpenAI/Anthropic vision & language rows. OpenAI embeddings stay active, and
    # wildcard rows ('*' / 'prefix*') are left alone: they are admin-managed fallbacks.
    conn.execute(
        sa.text("""
            UPDATE cost_catalog SET is_active = :active, updated_at = NOW()
            WHERE provider = 'openai' AND operation <> 'embed' AND model NOT LIKE '%*%'
        """),
        {"active": active},
    )
    conn.execute(
        sa.text("""
            UPDATE cost_catalog SET is_active = :active, updated_at = NOW()
            WHERE provider = 'anthropic' AND model NOT LIKE '%*%'
        """),
        {"active": active},
    )
    for model in REMOVED_FAL_LANGUAGE_MODELS:
        conn.execute(
            sa.text("UPDATE cost_catalog SET is_active = :active, updated_at = NOW() "
                    "WHERE provider = 'fal' AND model = :model"),
            {"active": active, "model": model},
        )
    for model, operation in REMOVED_FAL_IMAGE_ROWS:
        conn.execute(
            sa.text("UPDATE cost_catalog SET is_active = :active, updated_at = NOW() "
                    "WHERE provider = 'fal' AND model = :model AND operation = :operation"),
            {"active": active, "model": model, "operation": operation},
        )


def _reset_user_settings(conn) -> None:
    """Point every user's stored model settings at the new defaults."""
    rows = conn.execute(sa.text("SELECT id, value FROM app_settings WHERE key = 'provider_config'")).fetchall()
    for row_id, value in rows:
        try:
            config = json.loads(value)
        except (TypeError, ValueError):
            config = None
        if not isinstance(config, dict):
            config = {}
        for key in STALE_PROVIDER_CONFIG_KEYS:
            config.pop(key, None)
        config["fal_vision_model"] = DEFAULT_LANGUAGE_MODEL
        config["fal_language_model"] = DEFAULT_LANGUAGE_MODEL
        conn.execute(
            sa.text("UPDATE app_settings SET value = :value, updated_at = NOW() WHERE id = :id"),
            {"value": json.dumps(config), "id": row_id},
        )
    for key, default in (("base_model", DEFAULT_GENERATION_MODEL), ("edit_model", DEFAULT_EDIT_MODEL)):
        conn.execute(
            sa.text("UPDATE app_settings SET value = :value, updated_at = NOW() WHERE key = :key"),
            {"value": default, "key": key},
        )


def _snapshot(conn) -> None:
    # Only rows touched by this migration are retained for a faithful downgrade.
    conn.execute(sa.text("CREATE TABLE migration_055_cost_snapshot AS SELECT * FROM cost_catalog WHERE 1=0"))
    conn.execute(sa.text("CREATE TABLE migration_055_settings_snapshot AS SELECT id, value, updated_at FROM app_settings WHERE key IN ('provider_config', 'base_model', 'edit_model')"))

    def save(where, args):
        conn.execute(sa.text("INSERT INTO migration_055_cost_snapshot SELECT c.* FROM cost_catalog c WHERE " + where +
                             " AND NOT EXISTS (SELECT 1 FROM migration_055_cost_snapshot s WHERE s.id = c.id)"), args)

    save("c.provider = 'openai' AND c.operation <> 'embed' AND c.model NOT LIKE '%*%'", {})
    save("c.provider = 'anthropic' AND c.model NOT LIKE '%*%'", {})
    for model in REMOVED_FAL_LANGUAGE_MODELS:
        save("c.provider = 'fal' AND c.model = :model", {"model": model})
    for model, operation in (*REMOVED_FAL_IMAGE_ROWS, *[(m, o) for m, o, _, _ in IMAGE_ROWS], *CLEAR_RULES):
        save("c.provider = 'fal' AND c.model = :model AND c.operation = :operation", {"model": model, "operation": operation})
    for model in LANGUAGE_RATES:
        for operation in LANGUAGE_OPERATIONS:
            save("c.provider = 'fal' AND c.model = :model AND c.operation = :operation", {"model": model, "operation": operation})


def upgrade() -> None:
    conn = op.get_bind()
    _snapshot(conn)

    for model, (input_rate, output_rate) in LANGUAGE_RATES.items():
        for operation in LANGUAGE_OPERATIONS:
            _upsert_language(conn, model, operation, input_rate, output_rate)

    for model, operation, cost_per_call, pricing_rules in IMAGE_ROWS:
        _upsert_image(conn, model, operation, cost_per_call, pricing_rules)
    for model, operation in CLEAR_RULES:
        conn.execute(
            sa.text("UPDATE cost_catalog SET pricing_rules = NULL WHERE provider = 'fal' "
                    "AND model = :model AND operation = :operation"),
            {"model": model, "operation": operation},
        )

    _set_active(conn, False)
    _reset_user_settings(conn)


def downgrade() -> None:
    conn = op.get_bind()

    # Remove only rows introduced by the upgrade, leaving later unrelated rows alone.
    for model in LANGUAGE_RATES:
        for operation in LANGUAGE_OPERATIONS:
            conn.execute(sa.text("DELETE FROM cost_catalog WHERE provider='fal' AND model=:model AND operation=:operation "
                                 "AND NOT EXISTS (SELECT 1 FROM migration_055_cost_snapshot s WHERE s.id = cost_catalog.id)"),
                         {"model": model, "operation": operation})
    for model, operation, _cost, _rules in IMAGE_ROWS:
        conn.execute(sa.text("DELETE FROM cost_catalog WHERE provider='fal' AND model=:model AND operation=:operation "
                             "AND NOT EXISTS (SELECT 1 FROM migration_055_cost_snapshot s WHERE s.id = cost_catalog.id)"),
                     {"model": model, "operation": operation})
    for column in ("cost_per_input_token", "cost_per_output_token", "cost_per_call", "pricing_rules", "platform_markup", "is_active", "updated_at"):
        conn.execute(sa.text(f"UPDATE cost_catalog SET {column} = (SELECT s.{column} FROM migration_055_cost_snapshot s WHERE s.id = cost_catalog.id) "
                             "WHERE EXISTS (SELECT 1 FROM migration_055_cost_snapshot s WHERE s.id = cost_catalog.id)"))
    for column in ("value", "updated_at"):
        conn.execute(sa.text(f"UPDATE app_settings SET {column} = (SELECT s.{column} FROM migration_055_settings_snapshot s WHERE s.id = app_settings.id) "
                             "WHERE EXISTS (SELECT 1 FROM migration_055_settings_snapshot s WHERE s.id = app_settings.id)"))
    conn.execute(sa.text("DROP TABLE migration_055_cost_snapshot"))
    conn.execute(sa.text("DROP TABLE migration_055_settings_snapshot"))
