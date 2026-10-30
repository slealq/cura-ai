#!/usr/bin/env python3
"""
One-time backfill: copy finished generations and edits into the image library.

New generations are added automatically (GenerationService.add_to_library).
This script covers the ones created before migration 056. It is idempotent:
generations that already have a library copy are skipped.

Usage (after `alembic upgrade head`):
    python scripts/backfill_generated_library.py [--dry-run] [--user-id N] [--limit N]

On DEV:
    az containerapp exec --name cae-imggen-dev-backend --resource-group rg-imggen-dev \
        --command "python scripts/backfill_generated_library.py"
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.base import SessionLocal  # noqa: E402
from app.models.generated_image import GeneratedImage, GenerationStatus  # noqa: E402
from app.models.image import Image  # noqa: E402
from app.services.generation_service import GenerationService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("backfill_generated_library")


async def backfill(dry_run: bool, user_id: int | None, limit: int | None) -> None:
    db = SessionLocal()
    try:
        linked = db.query(Image.generated_image_id).filter(Image.generated_image_id.isnot(None))
        query = (
            db.query(GeneratedImage)
            .filter(
                GeneratedImage.status == GenerationStatus.COMPLETED,
                GeneratedImage.object_key.isnot(None),
                ~GeneratedImage.id.in_(linked),
            )
            .order_by(GeneratedImage.id)
        )
        if user_id is not None:
            query = query.filter(GeneratedImage.user_id == user_id)
        if limit:
            query = query.limit(limit)
        pending = query.all()
        logger.info("%d generations/edits without a library copy", len(pending))
        if dry_run:
            for gen in pending:
                mode = (gen.generation_params or {}).get("mode") or "generate"
                logger.info("  would add #%s (user %s, %s)", gen.id, gen.user_id, mode)
            return

        added = skipped = failed = 0
        for gen in pending:
            service = GenerationService(db, gen.user_id)
            try:
                data = await service.storage.get_generated_image(gen.object_key)
            except Exception as e:
                failed += 1
                logger.warning("  #%s: could not read %s: %s", gen.id, gen.object_key, e)
                continue
            image = await service.add_to_library(gen, data)
            if image is None:
                skipped += 1
                logger.info("  #%s: skipped (already in library or failed, see warnings)", gen.id)
            else:
                added += 1
                logger.info("  #%s -> image %s (%s)", gen.id, image.id, image.source.value)
        logger.info("Done: %d added, %d skipped, %d unreadable", added, skipped, failed)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="List what would be added without writing")
    parser.add_argument("--user-id", type=int, help="Only backfill this user's generations")
    parser.add_argument("--limit", type=int, help="Process at most N generations")
    args = parser.parse_args()
    asyncio.run(backfill(args.dry_run, args.user_id, args.limit))


if __name__ == "__main__":
    main()
