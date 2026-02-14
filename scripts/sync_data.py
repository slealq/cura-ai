#!/usr/bin/env python3
"""
Bidirectional data sync between local and Azure cloud environments.

Syncs database records and files for sync-enabled users between local
Docker Compose and Azure DEV environments.

Usage:
    python scripts/sync_data.py \
        --direction local-to-cloud \
        --local-db "postgresql://postgres:postgres@localhost:5432/design_pipeline" \
        --cloud-db "postgresql://imggenadmin:PASS@psql-imggen-dev2...5432/imggen?sslmode=require" \
        --azure-connection-string "DefaultEndpointsProtocol=..." \
        --azure-container images \
        --local-storage ./storage \
        [--dry-run] [--skip-files] [--skip-db] [--verbose]
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

MAX_WORKERS = 10

# Thumbnail URI patterns
# Local:  /app/storage/thumbnails/abc123_200.jpg
# Azure:  azure://images/thumbnails/abc123_200.jpg
LOCAL_THUMB_PREFIX = "/app/storage/"
AZURE_THUMB_PREFIX = "azure://images/"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class SyncStats:
    """Thread-safe sync counters."""

    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    files_uploaded: int = 0
    files_downloaded: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    _lock: Lock = field(default_factory=Lock)

    def inc(self, counter: str, n: int = 1) -> None:
        with self._lock:
            setattr(self, counter, getattr(self, counter) + n)

    def summary(self) -> str:
        return (
            f"DB: {self.inserted} inserted, {self.updated} updated, "
            f"{self.skipped} skipped, {self.failed} failed | "
            f"Files: {self.files_uploaded} up, {self.files_downloaded} down, "
            f"{self.files_skipped} skipped, {self.files_failed} failed"
        )


# ---------------------------------------------------------------------------
# Thumbnail URI translation
# ---------------------------------------------------------------------------

def translate_thumbnail_uri(uri: str | None, direction: str) -> str | None:
    """Translate thumbnail URI between local and azure formats."""
    if not uri:
        return uri

    if direction == "local-to-cloud":
        # /app/storage/thumbnails/x.jpg -> azure://images/thumbnails/x.jpg
        if uri.startswith(LOCAL_THUMB_PREFIX):
            return AZURE_THUMB_PREFIX + uri[len(LOCAL_THUMB_PREFIX):]
        # Already azure format
        if uri.startswith(AZURE_THUMB_PREFIX):
            return uri
        # Extract just the filename portion and construct azure path
        filename = uri.rsplit("/", 1)[-1]
        # Guess subdirectory from filename patterns
        return AZURE_THUMB_PREFIX + "thumbnails/" + filename

    elif direction == "cloud-to-local":
        # azure://images/thumbnails/x.jpg -> /app/storage/thumbnails/x.jpg
        if uri.startswith(AZURE_THUMB_PREFIX):
            return LOCAL_THUMB_PREFIX + uri[len(AZURE_THUMB_PREFIX):]
        # Already local format
        if uri.startswith(LOCAL_THUMB_PREFIX):
            return uri
        filename = uri.rsplit("/", 1)[-1]
        return LOCAL_THUMB_PREFIX + "thumbnails/" + filename

    return uri


# ---------------------------------------------------------------------------
# Table sync definitions
# ---------------------------------------------------------------------------

# Each entry: (table_name, natural_key_columns, columns_to_sync, fk_remaps, thumbnail_columns)
# fk_remaps: dict of {column_name: (source_table, source_natural_key_cols)}
# thumbnail_columns: list of columns needing URI translation

TABLE_SYNC_ORDER = [
    {
        "table": "users",
        "natural_key": ["email"],
        "exclude_cols": ["id", "hashed_password"],
        "fk_remaps": {},
        "thumbnail_cols": [],
        "filter_by_user": False,
    },
    {
        "table": "images",
        "natural_key": ["object_key"],
        "exclude_cols": ["id"],
        "fk_remaps": {"user_id": "users"},
        "thumbnail_cols": ["thumbnail_uri_small", "thumbnail_uri_medium", "thumbnail_uri_large"],
        "filter_by_user": True,
    },
    {
        "table": "image_metadata",
        "natural_key": ["image_id"],
        "exclude_cols": ["id"],
        "fk_remaps": {"image_id": "images"},
        "thumbnail_cols": [],
        "filter_by_user": False,  # Follows images via FK
        "join_filter": ("image_id", "images"),
    },
    {
        "table": "folders",
        "natural_key": ["user_id", "name"],
        "exclude_cols": ["id"],
        "fk_remaps": {"user_id": "users"},
        "thumbnail_cols": [],
        "filter_by_user": True,
    },
    {
        "table": "folder_images",
        "natural_key": ["folder_id", "image_id"],
        "exclude_cols": ["id"],
        "fk_remaps": {"folder_id": "folders", "image_id": "images"},
        "thumbnail_cols": [],
        "filter_by_user": False,
        "join_filter": ("folder_id", "folders"),
    },
    {
        "table": "clusters",
        "natural_key": ["user_id", "run_id", "created_at"],
        "exclude_cols": ["id"],
        "fk_remaps": {"user_id": "users"},
        "thumbnail_cols": [],
        "filter_by_user": True,
    },
    {
        "table": "cluster_memberships",
        "natural_key": ["cluster_id", "image_id"],
        "exclude_cols": ["id"],
        "fk_remaps": {"cluster_id": "clusters", "image_id": "images"},
        "thumbnail_cols": [],
        "filter_by_user": False,
        "join_filter": ("cluster_id", "clusters"),
    },
    {
        "table": "jobs",
        "natural_key": ["user_id", "created_at", "job_type"],
        "exclude_cols": ["id"],
        "fk_remaps": {"user_id": "users", "image_id": "images"},
        "thumbnail_cols": [],
        "filter_by_user": True,
    },
    {
        "table": "lora_models",
        "natural_key": ["user_id", "name"],
        "exclude_cols": ["id"],
        "fk_remaps": {"user_id": "users", "folder_id": "folders", "cluster_id": "clusters", "job_id": "jobs"},
        "thumbnail_cols": [],
        "filter_by_user": True,
    },
    {
        "table": "generated_images",
        "natural_key": ["object_key"],
        "exclude_cols": ["id"],
        "fk_remaps": {"user_id": "users", "lora_model_id": "lora_models", "job_id": "jobs"},
        "thumbnail_cols": ["thumbnail_uri_small", "thumbnail_uri_medium"],
        "filter_by_user": True,
        # generated_images.object_key can be NULL for pending generations
        "natural_key_fallback": ["user_id", "created_at", "prompt"],
    },
    {
        "table": "lora_evaluations",
        "natural_key": ["user_id", "created_at"],
        "exclude_cols": ["id"],
        "fk_remaps": {"user_id": "users", "lora_model_id": "lora_models", "job_id": "jobs"},
        "thumbnail_cols": [],
        "filter_by_user": True,
    },
    {
        "table": "evaluation_pairs",
        "natural_key": ["generated_object_key"],
        "exclude_cols": ["id"],
        "fk_remaps": {"evaluation_id": "lora_evaluations", "original_image_id": "images"},
        "thumbnail_cols": ["generated_thumbnail_small", "generated_thumbnail_medium"],
        "filter_by_user": False,
        "join_filter": ("evaluation_id", "lora_evaluations"),
    },
    {
        "table": "prompt_presets",
        "natural_key": ["user_id", "name"],
        "exclude_cols": ["id"],
        "fk_remaps": {"user_id": "users"},
        "thumbnail_cols": [],
        "filter_by_user": True,
    },
    {
        "table": "app_settings",
        "natural_key": ["user_id", "key"],
        "exclude_cols": ["id"],
        "fk_remaps": {"user_id": "users"},
        "thumbnail_cols": [],
        "filter_by_user": True,
    },
]


# ---------------------------------------------------------------------------
# Database sync
# ---------------------------------------------------------------------------

def get_table_columns(conn, table_name: str) -> list[str]:
    """Get column names for a table."""
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = :table ORDER BY ordinal_position"
    ), {"table": table_name})
    return [row[0] for row in result]


def get_json_columns(conn, table_name: str) -> set[str]:
    """Get column names that are json or jsonb type."""
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = :table AND data_type IN ('json', 'jsonb') "
        "ORDER BY ordinal_position"
    ), {"table": table_name})
    return {row[0] for row in result}


def serialize_json_values(row: dict, json_cols: set[str]) -> dict:
    """Convert Python objects in JSON columns to JSON strings for insertion."""
    if not json_cols:
        return row
    result = dict(row)
    for col in json_cols:
        val = result.get(col)
        if val is not None and not isinstance(val, str):
            result[col] = json.dumps(val)
    return result


def fetch_sync_enabled_user_ids(conn) -> list[int]:
    """Get IDs of users with sync_enabled=true."""
    result = conn.execute(text(
        "SELECT id FROM users WHERE sync_enabled = true ORDER BY id"
    ))
    return [row[0] for row in result]


def fetch_sync_enabled_user_emails(conn) -> list[str]:
    """Get emails of users with sync_enabled=true."""
    result = conn.execute(text(
        "SELECT email FROM users WHERE sync_enabled = true ORDER BY id"
    ))
    return [row[0] for row in result]


def fetch_rows(conn, table_name: str, columns: list[str],
               user_ids: list[int], table_def: dict) -> list[dict]:
    """Fetch rows from source database for sync-enabled users."""
    cols_str = ", ".join(f'"{c}"' for c in columns)

    if table_def.get("filter_by_user") and user_ids:
        placeholders = ", ".join(f":uid_{i}" for i in range(len(user_ids)))
        query = f'SELECT {cols_str} FROM "{table_name}" WHERE user_id IN ({placeholders})'
        params = {f"uid_{i}": uid for i, uid in enumerate(user_ids)}
    elif table_def.get("join_filter") and user_ids:
        fk_col, parent_table = table_def["join_filter"]
        placeholders = ", ".join(f":uid_{i}" for i in range(len(user_ids)))
        query = (
            f'SELECT t.{cols_str.replace(", ", ", t.")} FROM "{table_name}" t '
            f'JOIN "{parent_table}" p ON t."{fk_col}" = p.id '
            f'WHERE p.user_id IN ({placeholders})'
        )
        # Fix the column references
        t_cols = ", ".join(f't."{c}"' for c in columns)
        query = (
            f'SELECT {t_cols} FROM "{table_name}" t '
            f'JOIN "{parent_table}" p ON t."{fk_col}" = p.id '
            f'WHERE p.user_id IN ({placeholders})'
        )
        params = {f"uid_{i}": uid for i, uid in enumerate(user_ids)}
    elif table_name == "users":
        # Only sync sync-enabled users
        placeholders = ", ".join(f":uid_{i}" for i in range(len(user_ids)))
        query = f'SELECT {cols_str} FROM "{table_name}" WHERE id IN ({placeholders})'
        params = {f"uid_{i}": uid for i, uid in enumerate(user_ids)}
    else:
        query = f'SELECT {cols_str} FROM "{table_name}"'
        params = {}

    result = conn.execute(text(query), params)
    col_names = list(result.keys())
    return [dict(zip(col_names, row)) for row in result]


def build_id_map(conn, table_name: str, natural_key_cols: list[str]) -> dict:
    """Build a mapping of natural key values -> id in destination."""
    nk_cols = ", ".join(f'"{c}"' for c in natural_key_cols)
    result = conn.execute(text(f'SELECT id, {nk_cols} FROM "{table_name}"'))
    id_map = {}
    for row in result:
        row_vals = tuple(row[1:]) if len(natural_key_cols) > 1 else row[1]
        id_map[row_vals] = row[0]
    return id_map


def remap_fk(row: dict, col: str, source_table: str,
             src_id_to_natural: dict, dst_natural_to_id: dict) -> dict:
    """Remap a foreign key column from source ID to destination ID."""
    src_id = row.get(col)
    if src_id is None:
        return row

    natural_key = src_id_to_natural.get(source_table, {}).get(src_id)
    if natural_key is None:
        logger.warning("  FK remap failed: %s.%s=%s not found in source %s ID map",
                       "", col, src_id, source_table)
        row[col] = None
        return row

    dst_id = dst_natural_to_id.get(source_table, {}).get(natural_key)
    if dst_id is None:
        logger.warning("  FK remap failed: %s natural_key=%s not found in dest %s",
                       col, natural_key, source_table)
        row[col] = None
        return row

    row[col] = dst_id
    return row


def upsert_row(conn, table_name: str, row: dict,
               natural_key_cols: list[str], all_cols: list[str]) -> str:
    """Insert or update a row. Returns 'inserted', 'updated', or 'skipped'."""
    # Build WHERE clause for natural key lookup
    where_parts = []
    params = {}
    for i, nk in enumerate(natural_key_cols):
        val = row.get(nk)
        if val is None:
            where_parts.append(f'"{nk}" IS NULL')
        else:
            where_parts.append(f'"{nk}" = :nk_{i}')
            params[f"nk_{i}"] = val

    where_clause = " AND ".join(where_parts)
    existing = conn.execute(
        text(f'SELECT id FROM "{table_name}" WHERE {where_clause}'), params
    ).fetchone()

    if existing:
        # Update
        update_cols = [c for c in all_cols if c not in natural_key_cols and c != "id"]
        if not update_cols:
            return "skipped"

        set_parts = []
        update_params = {"existing_id": existing[0]}
        for col in update_cols:
            set_parts.append(f'"{col}" = :u_{col}')
            update_params[f"u_{col}"] = row.get(col)

        conn.execute(
            text(f'UPDATE "{table_name}" SET {", ".join(set_parts)} WHERE id = :existing_id'),
            update_params,
        )
        return "updated"
    else:
        # Insert
        insert_cols = [c for c in all_cols if c != "id"]
        col_list = ", ".join(f'"{c}"' for c in insert_cols)
        val_list = ", ".join(f":i_{c}" for c in insert_cols)
        insert_params = {f"i_{c}": row.get(c) for c in insert_cols}

        conn.execute(
            text(f'INSERT INTO "{table_name}" ({col_list}) VALUES ({val_list})'),
            insert_params,
        )
        return "inserted"


def sync_table(src_conn, dst_conn, table_def: dict, user_ids_src: list[int],
               user_emails: list[str], direction: str,
               src_id_maps: dict, dst_id_maps: dict,
               stats: SyncStats, dry_run: bool) -> None:
    """Sync a single table from source to destination."""
    table_name = table_def["table"]
    natural_key = table_def["natural_key"]
    exclude_cols = table_def["exclude_cols"]
    fk_remaps = table_def["fk_remaps"]
    thumbnail_cols = table_def["thumbnail_cols"]

    logger.info("Syncing table: %s", table_name)

    # Get columns and detect JSON columns in destination
    all_columns = get_table_columns(src_conn, table_name)
    json_cols = get_json_columns(dst_conn, table_name)
    sync_columns = [c for c in all_columns if c not in exclude_cols]

    # For users table, we need to include some extra columns but exclude hashed_password
    if table_name == "users":
        sync_columns = [c for c in all_columns if c not in ["id", "hashed_password"]]

    # Fetch source rows
    rows = fetch_rows(src_conn, table_name, all_columns, user_ids_src, table_def)
    logger.info("  Found %d rows to sync", len(rows))

    if not rows:
        return

    # Build source ID -> natural key map for this table (for FK remapping by later tables)
    src_nk_map = {}
    for row in rows:
        src_id = row.get("id")
        if len(natural_key) == 1:
            nk_val = row.get(natural_key[0])
        else:
            nk_val = tuple(row.get(k) for k in natural_key)
        src_nk_map[src_id] = nk_val
    src_id_maps[table_name] = src_nk_map

    # Build destination natural key -> id map
    dst_nk_map = build_id_map(dst_conn, table_name, natural_key)
    dst_id_maps[table_name] = dst_nk_map

    # For users table, also build special user email maps
    if table_name == "users":
        # We also need dest user_ids by email for later FK remapping
        result = dst_conn.execute(text("SELECT id, email FROM users"))
        for r in result:
            dst_nk_map[r[1]] = r[0]  # email -> id
        dst_id_maps["users"] = dst_nk_map

        # Source: id -> email
        for row in rows:
            src_nk_map[row["id"]] = row["email"]

    for row in rows:
        # Remove excluded columns
        sync_row = {k: v for k, v in row.items() if k not in exclude_cols}

        # Remap FK columns
        for col, source_table in fk_remaps.items():
            if col in sync_row:
                sync_row = remap_fk(sync_row, col, source_table,
                                    src_id_maps, dst_id_maps)

        # Translate thumbnail URIs
        for col in thumbnail_cols:
            if col in sync_row:
                sync_row[col] = translate_thumbnail_uri(sync_row.get(col), direction)

        # Remap natural key FK values for lookup
        nk_for_lookup = list(natural_key)

        # Serialize JSON column values (Python lists/dicts -> JSON strings)
        if json_cols:
            sync_row = serialize_json_values(sync_row, json_cols)

        if dry_run:
            nk_vals = {k: sync_row.get(k) for k in natural_key}
            logger.info("  [DRY RUN] Would upsert %s: %s", table_name, nk_vals)
            stats.inc("skipped")
            continue

        try:
            # Use savepoint so a single row failure doesn't abort the transaction
            dst_conn.execute(text("SAVEPOINT row_sp"))
            action = upsert_row(dst_conn, table_name, sync_row, natural_key,
                                [c for c in all_columns if c not in exclude_cols])
            dst_conn.execute(text("RELEASE SAVEPOINT row_sp"))
            stats.inc(action)
            logger.debug("  %s: %s", action, {k: sync_row.get(k) for k in natural_key})
        except Exception:
            dst_conn.execute(text("ROLLBACK TO SAVEPOINT row_sp"))
            logger.exception("  Failed to upsert row in %s", table_name)
            stats.inc("failed")

    # Refresh destination ID map after inserts
    dst_id_maps[table_name] = build_id_map(dst_conn, table_name, natural_key)


def sync_database(src_url: str, dst_url: str, direction: str,
                  stats: SyncStats, dry_run: bool) -> tuple[list[int], list[str]]:
    """Sync all tables from source to destination database."""
    src_engine = create_engine(src_url)
    dst_engine = create_engine(dst_url)

    with src_engine.connect() as src_conn, dst_engine.connect() as dst_conn:
        # Find sync-enabled users in source
        user_ids = fetch_sync_enabled_user_ids(src_conn)
        user_emails = fetch_sync_enabled_user_emails(src_conn)

        if not user_ids:
            logger.warning("No sync-enabled users found in source database.")
            return [], []

        logger.info("Found %d sync-enabled users: %s", len(user_ids),
                     ", ".join(user_emails))

        # ID maps: table_name -> {source_id: natural_key} and {natural_key: dest_id}
        src_id_maps: dict[str, dict] = {}
        dst_id_maps: dict[str, dict] = {}

        for table_def in TABLE_SYNC_ORDER:
            sync_table(src_conn, dst_conn, table_def, user_ids, user_emails,
                       direction, src_id_maps, dst_id_maps, stats, dry_run)

        if not dry_run:
            dst_conn.commit()

    return user_ids, user_emails


# ---------------------------------------------------------------------------
# File sync
# ---------------------------------------------------------------------------

def collect_object_keys(conn, user_ids: list[int]) -> list[str]:
    """Collect all object_keys for images and generated images of sync-enabled users."""
    keys = set()

    # Images
    placeholders = ", ".join(f":uid_{i}" for i in range(len(user_ids)))
    result = conn.execute(text(
        f"SELECT object_key FROM images WHERE user_id IN ({placeholders})"
    ), {f"uid_{i}": uid for i, uid in enumerate(user_ids)})
    for row in result:
        if row[0]:
            keys.add(row[0])

    # Generated images
    result = conn.execute(text(
        f"SELECT object_key FROM generated_images WHERE user_id IN ({placeholders})"
    ), {f"uid_{i}": uid for i, uid in enumerate(user_ids)})
    for row in result:
        if row[0]:
            keys.add(row[0])

    return sorted(keys)


def get_file_paths_for_object_key(object_key: str) -> list[str]:
    """
    Given an object_key (e.g., 'abc123.jpg' or 'images/abc123.jpg'),
    return all related file paths (original + thumbnails).
    """
    # Extract directory and filename
    # object_key may be: 'abc123.jpg' (bare), 'images/abc123.jpg', or 'generated/abc123.jpg'
    parts = object_key.rsplit("/", 1)
    if len(parts) == 2:
        directory, filename = parts
    else:
        # Bare filename — assume 'images' directory
        filename = object_key
        directory = "images"

    name, ext = os.path.splitext(filename)
    paths = [f"{directory}/{filename}"]

    # Determine thumbnail directory and sizes
    if directory == "images":
        thumb_dir = "thumbnails"
        sizes = [200, 400, 800]
    elif directory == "generated":
        thumb_dir = "generated_thumbnails"
        sizes = [200, 400]
    else:
        return paths

    for size in sizes:
        paths.append(f"{thumb_dir}/{name}_{size}{ext}")

    return paths


def sync_files_local_to_cloud(
    object_keys: list[str],
    local_storage: Path,
    connection_string: str,
    container_name: str,
    stats: SyncStats,
    dry_run: bool,
) -> None:
    """Upload files from local storage to Azure Blob Storage."""
    from azure.storage.blob import BlobServiceClient, ContentSettings
    from azure.core.exceptions import HttpResponseError

    all_paths = []
    for key in object_keys:
        all_paths.extend(get_file_paths_for_object_key(key))

    logger.info("File sync: %d files to check for upload", len(all_paths))

    if dry_run:
        for path in all_paths:
            local_path = local_storage / path
            if local_path.exists():
                logger.info("  [DRY RUN] Would upload: %s", path)
                stats.inc("files_uploaded")
            else:
                logger.debug("  [DRY RUN] Local file missing: %s", path)
        return

    blob_service = BlobServiceClient.from_connection_string(connection_string)

    def upload_one(blob_path: str) -> None:
        local_path = local_storage / blob_path
        if not local_path.exists():
            logger.debug("  Local file missing, skipping: %s", blob_path)
            return

        blob_client = blob_service.get_blob_client(container=container_name, blob=blob_path)

        # Skip if already exists
        try:
            blob_client.get_blob_properties()
            stats.inc("files_skipped")
            return
        except HttpResponseError as e:
            if e.status_code != 404:
                raise

        import mimetypes
        content_type = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
        with open(local_path, "rb") as f:
            blob_client.upload_blob(f, overwrite=True,
                                    content_settings=ContentSettings(content_type=content_type))
        stats.inc("files_uploaded")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(upload_one, p): p for p in all_paths}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                logger.exception("  Failed to upload %s", futures[future])
                stats.inc("files_failed")


def sync_files_cloud_to_local(
    object_keys: list[str],
    local_storage: Path,
    connection_string: str,
    container_name: str,
    stats: SyncStats,
    dry_run: bool,
) -> None:
    """Download files from Azure Blob Storage to local storage."""
    from azure.storage.blob import BlobServiceClient
    from azure.core.exceptions import HttpResponseError

    all_paths = []
    for key in object_keys:
        all_paths.extend(get_file_paths_for_object_key(key))

    logger.info("File sync: %d files to check for download", len(all_paths))

    if dry_run:
        for path in all_paths:
            local_path = local_storage / path
            if not local_path.exists():
                logger.info("  [DRY RUN] Would download: %s", path)
                stats.inc("files_downloaded")
            else:
                logger.debug("  [DRY RUN] Already exists locally: %s", path)
                stats.inc("files_skipped")
        return

    blob_service = BlobServiceClient.from_connection_string(connection_string)

    def download_one(blob_path: str) -> None:
        local_path = local_storage / blob_path
        if local_path.exists():
            stats.inc("files_skipped")
            return

        blob_client = blob_service.get_blob_client(container=container_name, blob=blob_path)
        try:
            blob_data = blob_client.download_blob()
        except HttpResponseError as e:
            if e.status_code == 404:
                logger.debug("  Blob not found, skipping: %s", blob_path)
                return
            raise

        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as f:
            blob_data.readinto(f)
        stats.inc("files_downloaded")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_one, p): p for p in all_paths}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                logger.exception("  Failed to download %s", futures[future])
                stats.inc("files_failed")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bidirectional data sync between local and Azure cloud.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Dry run local-to-cloud
  python scripts/sync_data.py \\
      --direction local-to-cloud \\
      --local-db "postgresql://postgres:postgres@localhost:5432/design_pipeline" \\
      --cloud-db "postgresql://imggenadmin:PASS@psql-imggen-dev2.postgres.database.azure.com:5432/imggen?sslmode=require" \\
      --azure-connection-string "DefaultEndpointsProtocol=https;..." \\
      --dry-run

  # Full sync cloud-to-local
  python scripts/sync_data.py \\
      --direction cloud-to-local \\
      --local-db "postgresql://postgres:postgres@localhost:5432/design_pipeline" \\
      --cloud-db "postgresql://imggenadmin:PASS@psql-imggen-dev2.postgres.database.azure.com:5432/imggen?sslmode=require" \\
      --azure-connection-string "DefaultEndpointsProtocol=https;..." \\
      --local-storage ./storage
""",
    )

    parser.add_argument("--direction", required=True,
                        choices=["local-to-cloud", "cloud-to-local"],
                        help="Sync direction")
    parser.add_argument("--local-db", required=True,
                        help="Local PostgreSQL connection string")
    parser.add_argument("--cloud-db", required=True,
                        help="Cloud PostgreSQL connection string")
    parser.add_argument("--azure-connection-string", default=None,
                        help="Azure Storage connection string (required for file sync)")
    parser.add_argument("--azure-container", default="images",
                        help="Azure Blob container name (default: images)")
    parser.add_argument("--local-storage", default="./storage",
                        help="Local storage path (default: ./storage)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without making changes")
    parser.add_argument("--skip-files", action="store_true",
                        help="Skip file sync, only sync database")
    parser.add_argument("--skip-db", action="store_true",
                        help="Skip database sync, only sync files")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable debug logging")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if not args.verbose:
        logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
        logging.getLogger("azure").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    stats = SyncStats()
    direction = args.direction

    if direction == "local-to-cloud":
        src_url = args.local_db
        dst_url = args.cloud_db
    else:
        src_url = args.cloud_db
        dst_url = args.local_db

    logger.info("=== Data Sync: %s ===", direction)
    logger.info("  Source: %s", re.sub(r"://[^@]+@", "://***@", src_url))
    logger.info("  Dest:   %s", re.sub(r"://[^@]+@", "://***@", dst_url))
    logger.info("  Dry run: %s", args.dry_run)

    start_time = time.monotonic()

    # Database sync
    user_ids_src = []
    if not args.skip_db:
        user_ids_src, user_emails = sync_database(src_url, dst_url, direction, stats, args.dry_run)
    else:
        logger.info("Skipping database sync (--skip-db)")
        # Still need user IDs for file sync
        src_engine = create_engine(src_url)
        with src_engine.connect() as conn:
            user_ids_src = fetch_sync_enabled_user_ids(conn)

    # File sync
    if not args.skip_files and args.azure_connection_string and user_ids_src:
        logger.info("")
        logger.info("=== File Sync ===")

        src_engine = create_engine(src_url)
        with src_engine.connect() as conn:
            object_keys = collect_object_keys(conn, user_ids_src)

        logger.info("Found %d object keys to sync", len(object_keys))

        if direction == "local-to-cloud":
            sync_files_local_to_cloud(
                object_keys, Path(args.local_storage),
                args.azure_connection_string, args.azure_container,
                stats, args.dry_run,
            )
        else:
            sync_files_cloud_to_local(
                object_keys, Path(args.local_storage),
                args.azure_connection_string, args.azure_container,
                stats, args.dry_run,
            )
    elif args.skip_files:
        logger.info("Skipping file sync (--skip-files)")
    elif not args.azure_connection_string:
        logger.info("Skipping file sync (no --azure-connection-string)")

    elapsed = time.monotonic() - start_time
    logger.info("")
    logger.info("=== Sync completed in %.1f seconds ===", elapsed)
    logger.info(stats.summary())

    if stats.failed > 0 or stats.files_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
