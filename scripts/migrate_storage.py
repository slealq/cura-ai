#!/usr/bin/env python3
"""
Migrate local file storage to Azure Blob Storage.

Reads all files from the local ./storage/ directory (images, thumbnails,
generated, generated_thumbnails) and uploads them to Azure Blob Storage,
preserving the virtual directory structure.

Usage:
    python scripts/migrate_storage.py \
        --connection-string "DefaultEndpointsProtocol=https;AccountName=..." \
        --container images \
        --storage-path ./storage \
        --skip-existing \
        --dry-run
"""

import argparse
import logging
import mimetypes
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import ResourceExistsError, HttpResponseError

logger = logging.getLogger(__name__)

# Subdirectories within the storage root to migrate
STORAGE_SUBDIRS = ["images", "thumbnails", "generated", "generated_thumbnails"]

# Additional MIME type mappings beyond what mimetypes provides
EXTRA_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".svg": "image/svg+xml",
    ".avif": "image/avif",
}

MAX_WORKERS = 10


@dataclass
class MigrationStats:
    """Thread-safe counters for migration progress."""

    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0
    _lock: Lock = field(default_factory=Lock)

    def increment_uploaded(self) -> None:
        with self._lock:
            self.uploaded += 1

    def increment_skipped(self) -> None:
        with self._lock:
            self.skipped += 1

    def increment_failed(self) -> None:
        with self._lock:
            self.failed += 1

    def summary(self) -> str:
        return (
            f"Total: {self.total} | "
            f"Uploaded: {self.uploaded} | "
            f"Skipped: {self.skipped} | "
            f"Failed: {self.failed}"
        )


def get_content_type(file_path: str) -> str:
    """Determine the Content-Type for a file based on its extension."""
    ext = os.path.splitext(file_path)[1].lower()

    # Check our explicit mapping first
    if ext in EXTRA_MIME_TYPES:
        return EXTRA_MIME_TYPES[ext]

    # Fall back to mimetypes module
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        return mime_type

    # Default to binary octet-stream
    return "application/octet-stream"


def collect_files(storage_path: Path) -> list[tuple[Path, str]]:
    """
    Collect all files to migrate from the storage subdirectories.

    Returns a list of (local_file_path, blob_name) tuples.
    """
    files = []

    for subdir in STORAGE_SUBDIRS:
        subdir_path = storage_path / subdir
        if not subdir_path.is_dir():
            logger.info("Subdirectory '%s' does not exist, skipping", subdir)
            continue

        for root, _dirs, filenames in os.walk(subdir_path):
            for filename in filenames:
                # Skip hidden files and system files
                if filename.startswith("."):
                    continue

                local_path = Path(root) / filename
                # Build the blob name relative to the storage root
                # e.g., images/abc123.jpg, thumbnails/abc123_400.jpg
                blob_name = local_path.relative_to(storage_path).as_posix()
                files.append((local_path, blob_name))

    return files


def upload_file(
    blob_service_client: BlobServiceClient,
    container_name: str,
    local_path: Path,
    blob_name: str,
    skip_existing: bool,
    dry_run: bool,
    stats: MigrationStats,
) -> None:
    """Upload a single file to Azure Blob Storage."""
    try:
        if dry_run:
            content_type = get_content_type(str(local_path))
            file_size = local_path.stat().st_size
            logger.info(
                "[DRY RUN] Would upload: %s -> %s (%s, %.1f KB)",
                local_path,
                blob_name,
                content_type,
                file_size / 1024,
            )
            stats.increment_uploaded()
            return

        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )

        # Check if blob already exists when skip_existing is enabled
        if skip_existing:
            try:
                blob_client.get_blob_properties()
                logger.debug("Skipping existing blob: %s", blob_name)
                stats.increment_skipped()
                return
            except HttpResponseError as e:
                if e.status_code != 404:
                    raise

        # Determine content type
        content_type = get_content_type(str(local_path))
        content_settings = ContentSettings(content_type=content_type)

        # Upload the file
        with open(local_path, "rb") as f:
            blob_client.upload_blob(
                f,
                overwrite=True,
                content_settings=content_settings,
            )

        file_size = local_path.stat().st_size
        logger.info(
            "Uploaded: %s -> %s (%s, %.1f KB)",
            local_path,
            blob_name,
            content_type,
            file_size / 1024,
        )
        stats.increment_uploaded()

    except Exception:
        logger.exception("Failed to upload %s", blob_name)
        stats.increment_failed()


def run_migration(
    connection_string: str,
    container_name: str,
    storage_path: Path,
    dry_run: bool,
    skip_existing: bool,
) -> MigrationStats:
    """Execute the storage migration."""
    stats = MigrationStats()

    # Validate local storage path
    if not storage_path.is_dir():
        logger.error("Storage path does not exist: %s", storage_path)
        sys.exit(1)

    # Collect all files to migrate
    logger.info("Scanning local storage at: %s", storage_path.resolve())
    files = collect_files(storage_path)
    stats.total = len(files)

    if stats.total == 0:
        logger.warning("No files found to migrate in %s", storage_path)
        return stats

    logger.info("Found %d files to migrate", stats.total)

    if dry_run:
        logger.info("=== DRY RUN MODE - no files will be uploaded ===")

    # Initialize Azure Blob Service client (skip in dry-run for convenience,
    # but still validate the connection string by creating the client)
    blob_service_client = None
    if not dry_run:
        try:
            blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
        except Exception:
            logger.exception("Failed to connect to Azure Blob Storage")
            sys.exit(1)

        # Ensure container exists
        try:
            container_client = blob_service_client.get_container_client(container_name)
            if not container_client.exists():
                logger.info("Creating container: %s", container_name)
                blob_service_client.create_container(container_name)
            else:
                logger.info("Using existing container: %s", container_name)
        except Exception:
            logger.exception("Failed to access or create container '%s'", container_name)
            sys.exit(1)

    # Upload files concurrently
    start_time = time.monotonic()
    workers = 1 if dry_run else MAX_WORKERS

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                upload_file,
                blob_service_client,
                container_name,
                local_path,
                blob_name,
                skip_existing,
                dry_run,
                stats,
            ): blob_name
            for local_path, blob_name in files
        }

        for future in as_completed(futures):
            blob_name = futures[future]
            try:
                future.result()
            except Exception:
                logger.exception("Unexpected error processing %s", blob_name)
                stats.increment_failed()

    elapsed = time.monotonic() - start_time
    logger.info("Migration completed in %.1f seconds", elapsed)
    logger.info(stats.summary())

    return stats


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Migrate local file storage to Azure Blob Storage.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Dry run to see what would be uploaded
  python scripts/migrate_storage.py \\
      --connection-string "DefaultEndpointsProtocol=https;..." \\
      --dry-run

  # Full migration with incremental support
  python scripts/migrate_storage.py \\
      --connection-string "DefaultEndpointsProtocol=https;..." \\
      --container images \\
      --skip-existing

  # Migrate from a custom storage path
  python scripts/migrate_storage.py \\
      --connection-string "DefaultEndpointsProtocol=https;..." \\
      --storage-path /data/storage
""",
    )

    parser.add_argument(
        "--connection-string",
        required=True,
        help="Azure Storage account connection string",
    )
    parser.add_argument(
        "--container",
        default="images",
        help="Azure Blob container name (default: images)",
    )
    parser.add_argument(
        "--storage-path",
        default="./storage",
        help="Local storage path to migrate from (default: ./storage)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be uploaded without actually uploading",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip blobs that already exist in Azure (incremental migration)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )

    return parser.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Suppress noisy Azure SDK loggers unless verbose
    if not args.verbose:
        logging.getLogger("azure").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    storage_path = Path(args.storage_path)

    logger.info("Starting storage migration to Azure Blob Storage")
    logger.info("  Container:     %s", args.container)
    logger.info("  Storage path:  %s", storage_path.resolve())
    logger.info("  Dry run:       %s", args.dry_run)
    logger.info("  Skip existing: %s", args.skip_existing)
    logger.info("  Max workers:   %d", MAX_WORKERS)

    stats = run_migration(
        connection_string=args.connection_string,
        container_name=args.container,
        storage_path=storage_path,
        dry_run=args.dry_run,
        skip_existing=args.skip_existing,
    )

    # Exit with error code if any files failed
    if stats.failed > 0:
        logger.warning("%d file(s) failed to upload", stats.failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
