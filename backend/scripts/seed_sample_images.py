#!/usr/bin/env python3
"""
Seed script to download sample images for testing.

Usage:
    python scripts/seed_sample_images.py [--count N]

Downloads sample design/inspiration images from Unsplash for testing.
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx

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

# Sample image URLs from Unsplash (free to use)
SAMPLE_IMAGES = [
    ("minimal-interior.jpg", "https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=800"),
    ("product-photography.jpg", "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=800"),
    ("typography-poster.jpg", "https://images.unsplash.com/photo-1561070791-2526d30994b5?w=800"),
    ("architecture-modern.jpg", "https://images.unsplash.com/photo-1486325212027-8081e485255e?w=800"),
    ("fashion-editorial.jpg", "https://images.unsplash.com/photo-1509631179647-0177331693ae?w=800"),
    ("food-styling.jpg", "https://images.unsplash.com/photo-1476224203421-9ac39bcb3327?w=800"),
    ("abstract-art.jpg", "https://images.unsplash.com/photo-1541701494587-cb58502866ab?w=800"),
    ("nature-landscape.jpg", "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=800"),
    ("tech-product.jpg", "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=800"),
    ("vintage-poster.jpg", "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=800"),
    ("geometric-pattern.jpg", "https://images.unsplash.com/photo-1557683316-973673baf926?w=800"),
    ("portrait-studio.jpg", "https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=800"),
    ("interior-scandinavian.jpg", "https://images.unsplash.com/photo-1618221195710-dd6b41faaea6?w=800"),
    ("branding-mockup.jpg", "https://images.unsplash.com/photo-1586717791821-3f44a563fa4c?w=800"),
    ("texture-concrete.jpg", "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=800"),
]


async def download_image(client: httpx.AsyncClient, url: str) -> bytes | None:
    """Download image from URL."""
    try:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return None


async def seed_images(count: int = 10):
    """Download and ingest sample images."""
    db = SessionLocal()
    image_service = get_image_service(db)

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, (filename, url) in enumerate(SAMPLE_IMAGES[:count]):
            logger.info(f"Downloading {i+1}/{count}: {filename}")

            image_data = await download_image(client, url)
            if not image_data:
                continue

            try:
                image = await image_service.ingest_image(
                    file_data=image_data,
                    filename=filename,
                    source=ImageSource.UPLOAD,
                    original_uri=url,
                )

                # Queue for processing
                process_image_pipeline.delay(image.id)

                logger.info(f"Ingested: {filename} (ID: {image.id})")

            except Exception as e:
                logger.error(f"Failed to ingest {filename}: {e}")

    db.close()
    logger.info(f"Seeding complete. Ingested {count} images.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Seed sample images for testing")
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of images to download (max 15)",
    )
    args = parser.parse_args()

    count = min(args.count, len(SAMPLE_IMAGES))

    logger.info(f"Seeding {count} sample images...")
    asyncio.run(seed_images(count))


if __name__ == "__main__":
    main()
