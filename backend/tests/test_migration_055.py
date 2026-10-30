"""Run migration 055's upgrade/downgrade SQL against an in-memory SQLite database.

SQLite understands the migration's upsert syntax; the Postgres-only ``NOW()`` is
registered as a function.  This covers the data logic (rows seeded, old rows
deactivated and restored, user settings rewritten) but not Postgres itself.
"""
import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa

_PATH = Path(__file__).parent.parent / "migrations" / "versions" / "055_refresh_model_catalog.py"
_spec = importlib.util.spec_from_file_location("migration_055_sqlite", _PATH)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


@pytest.fixture
def conn(monkeypatch):
    engine = sa.create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _record):
        dbapi_conn.create_function("NOW", 0, lambda: "2026-10-30 00:00:00")

    with engine.begin() as connection:
        connection.execute(sa.text("""
            CREATE TABLE cost_catalog (
                id INTEGER PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL, operation TEXT NOT NULL,
                cost_per_input_token NUMERIC DEFAULT 0, cost_per_output_token NUMERIC DEFAULT 0,
                cost_per_call NUMERIC DEFAULT 0, pricing_rules TEXT, platform_markup NUMERIC NOT NULL DEFAULT 2.0,
                is_active BOOLEAN NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT,
                UNIQUE (provider, model, operation)
            )
        """))
        connection.execute(sa.text(
            "CREATE TABLE app_settings (id INTEGER PRIMARY KEY, user_id INTEGER, key TEXT, value TEXT, updated_at TEXT)"
        ))
        old_rows = [
            ("openai", "gpt-4o", "tag"), ("openai", "text-embedding-3-small", "embed"), ("openai", "*", "tag"),
            ("anthropic", "claude-3-haiku-20240307", "describe"), ("fal", "x-ai/grok-4-fast", "tag"),
            ("fal", "fal-ai/flux/dev", "generate"), ("fal", "fal-ai/flux-lora-fast-training", "train"),
            ("fal", "fal-ai/flux-2", "generate"), ("fal", "fal-ai/qwen-image-max/edit", "edit"),
            ("fal", "fal-ai/nano-banana-pro/edit", "edit"), ("fal", "qwen/qwen3.8-flash", "tag"),
        ]
        for provider, model, operation in old_rows:
            connection.execute(
                sa.text("INSERT INTO cost_catalog (provider, model, operation, cost_per_call, pricing_rules) "
                        "VALUES (:p, :m, :o, 0.021, :rules)"),
                {"p": provider, "m": model, "o": operation, "rules": "OLD" if model == "fal-ai/flux-2" else None},
            )
        connection.execute(sa.text("INSERT INTO app_settings (user_id, key, value) VALUES (1, 'provider_config', :v)"), {
            "v": json.dumps({"vision_provider": "openai", "openai_vision_model": "gpt-4o", "fal_vision_model": "x-ai/grok-4-fast",
                             "max_tokens_tagging": 777}),
        })
        connection.execute(sa.text("INSERT INTO app_settings (user_id, key, value) VALUES (1, 'base_model', 'flux-dev')"))
        connection.execute(sa.text("INSERT INTO app_settings (user_id, key, value) VALUES (1, 'edit_model', 'face-swap')"))
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        yield connection


def _active(conn, provider, model, operation):
    return conn.execute(
        sa.text("SELECT is_active FROM cost_catalog WHERE provider=:p AND model=:m AND operation=:o"),
        {"p": provider, "m": model, "o": operation},
    ).scalar()


def test_upgrade_seeds_rows_deactivates_old_ones_and_resets_settings(conn):
    migration.upgrade()

    languages = conn.execute(sa.text(
        "SELECT COUNT(*) FROM cost_catalog WHERE provider='fal' AND cost_per_input_token > 0"
    )).scalar()
    assert languages == len(migration.LANGUAGE_RATES) * len(migration.LANGUAGE_OPERATIONS)
    row = conn.execute(sa.text(
        "SELECT cost_per_input_token, cost_per_output_token, platform_markup FROM cost_catalog "
        "WHERE model='anthropic/claude-haiku-5.5' AND operation='suggest_prompt'"
    )).one()
    assert (float(row[0]), float(row[1]), float(row[2])) == (1e-7, 5e-7, 2.0)

    for model, operation, cost, _rules in migration.IMAGE_ROWS:
        assert _active(conn, "fal", model, operation) == 1
    flux2 = conn.execute(sa.text("SELECT cost_per_call, pricing_rules FROM cost_catalog WHERE model='fal-ai/flux-2'")).one()
    assert float(flux2[0]) == 0.012 and "0.012" in flux2[1]

    assert _active(conn, "openai", "gpt-4o", "tag") == 0
    assert _active(conn, "openai", "text-embedding-3-small", "embed") == 1
    assert _active(conn, "openai", "*", "tag") == 1  # wildcard rows are left alone
    assert _active(conn, "anthropic", "claude-3-haiku-20240307", "describe") == 0
    assert _active(conn, "fal", "x-ai/grok-4-fast", "tag") == 0
    assert _active(conn, "fal", "fal-ai/flux/dev", "generate") == 0
    assert _active(conn, "fal", "fal-ai/qwen-image-max/edit", "edit") == 0
    assert _active(conn, "fal", "fal-ai/nano-banana-pro/edit", "edit") == 0
    assert _active(conn, "fal", "qwen/qwen3.8-flash", "tag") == 0
    assert _active(conn, "fal", "fal-ai/flux-lora-fast-training", "train") == 1

    stored = json.loads(conn.execute(sa.text("SELECT value FROM app_settings WHERE key='provider_config'")).scalar())
    assert stored == {"fal_vision_model": "anthropic/claude-haiku-5.5", "fal_language_model": "anthropic/claude-haiku-5.5",
                      "max_tokens_tagging": 777}
    assert conn.execute(sa.text("SELECT value FROM app_settings WHERE key='base_model'")).scalar() == "nano-banana-pro"
    assert conn.execute(sa.text("SELECT value FROM app_settings WHERE key='edit_model'")).scalar() == "nano-banana-2.1-edit"


def test_downgrade_removes_new_rows_and_reactivates_old_ones_then_upgrade_reruns_cleanly(conn):
    conn.execute(sa.text("UPDATE cost_catalog SET is_active=0 WHERE model='fal-ai/qwen-image-max/edit'"))
    before_cost = conn.execute(sa.text("SELECT cost_per_call, pricing_rules, is_active FROM cost_catalog WHERE model='fal-ai/flux-2'" )).one()
    before_settings = conn.execute(sa.text("SELECT id, value FROM app_settings ORDER BY id")).all()
    migration.upgrade()
    migration.downgrade()
    assert conn.execute(sa.text("SELECT cost_per_call, pricing_rules, is_active FROM cost_catalog WHERE model='fal-ai/flux-2'" )).one() == before_cost
    assert conn.execute(sa.text("SELECT id, value FROM app_settings ORDER BY id")).all() == before_settings

    # Rows that did not exist before 055 are gone (pre-existing endpoints such as flux-2 stay).
    assert conn.execute(sa.text("SELECT COUNT(*) FROM cost_catalog WHERE model='google/nano-banana-2.1'")).scalar() == 0
    assert conn.execute(sa.text("SELECT COUNT(*) FROM cost_catalog WHERE model='fal-ai/flux-2'")).scalar() == 1
    assert _active(conn, "openai", "gpt-4o", "tag") == 1
    assert _active(conn, "fal", "x-ai/grok-4-fast", "tag") == 1
    assert _active(conn, "fal", "fal-ai/nano-banana-pro/edit", "edit") == 1
    assert _active(conn, "fal", "qwen/qwen3.8-flash", "tag") == 1
    assert _active(conn, "fal", "fal-ai/qwen-image-max/edit", "edit") == 0
    assert conn.execute(sa.text("SELECT COUNT(*) FROM cost_catalog WHERE model='anthropic/claude-haiku-5.5'")).scalar() == 0

    migration.upgrade()
    assert _active(conn, "openai", "gpt-4o", "tag") == 0
    assert _active(conn, "fal", "fal-ai/nano-banana-pro", "generate") == 1
