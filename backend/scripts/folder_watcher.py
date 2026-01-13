#!/usr/bin/env python3
"""
Folder watcher script for auto-ingesting images.

Usage:
    python scripts/folder_watcher.py [--watch-path PATH]

This script watches a folder for new image files and automatically
ingests them into the pipeline.
"""
import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_settings
from app.db.base import SessionLocal
from app.models import ImageSource
from app.services.image_service import get_image_service
from app.workers.tasks import process_image_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}


class ImageHandler(FileSystemEventHandler):
    """Handler for new image files."""

    def __init__(self):
        self.processing = set()

    def on_created(self, event):
        """Handle new file creation."""
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return

        # Avoid duplicate processing
        if event.src_path in self.processing:
            return

        self.processing.add(event.src_path)

        # Wait for file to be fully written
        time.sleep(1)

        try:
            self._ingest_image(path)
        finally:
            self.processing.discard(event.src_path)

    def _ingest_image(self, path: Path):
        """Ingest a single image file."""
        logger.info(f"Detected new image: {path.name}")

        try:
            # Read file
            file_data = path.read_bytes()

            # Create database session
            db = SessionLocal()
            try:
                image_service = get_image_service(db)

                # Ingest image
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    image = loop.run_until_complete(
                        image_service.ingest_image(
                            file_data=file_data,
                            filename=path.name,
                            source=ImageSource.FOLDER_WATCHER,
                            original_uri=str(path.absolute()),
                        )
                    )
                finally:
                    loop.close()

                # Queue for processing
                process_image_pipeline.delay(image.id)

                logger.info(f"Ingested and queued: {path.name} (ID: {image.id})")

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Failed to ingest {path.name}: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Watch folder for new images")
    parser.add_argument(
        "--watch-path",
        type=str,
        default=settings.watch_folder_path,
        help="Path to watch for new images",
    )
    args = parser.parse_args()

    watch_path = Path(args.watch_path)
    watch_path.mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting folder watcher on: {watch_path.absolute()}")

    # Set up watchdog
    event_handler = ImageHandler()
    observer = Observer()
    observer.schedule(event_handler, str(watch_path), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping folder watcher...")
        observer.stop()

    observer.join()
    logger.info("Folder watcher stopped")


if __name__ == "__main__":
    main()
