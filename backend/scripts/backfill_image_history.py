"""Backfill surviving generation parameters. Run manually; never part of migrations."""
import argparse
import logging

from app.db.base import SessionLocal
from app.models import GeneratedImage, Image
from app.services.image_history import attach_history, snapshot
from app.workers.generation_tasks import _resolve_edit_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        for gen in db.query(GeneratedImage).order_by(GeneratedImage.id).all():
            if not gen.history:
                if args.dry_run:
                    print(f"Would backfill generation {gen.id}")
                    continue
                inputs = []
                # Resolve each source independently, preserving provider ordering even across gaps.
                sources = (gen.generation_params or {}).get("sources", {})
                for group in ("image_ids", "generated_ids", "upload_keys"):
                    for value in sources.get(group, []):
                        try:
                            _resolve_edit_sources(db, {"sources": {group: [value], "upload_names": sources.get("upload_names", {})}}, gen.user_id, inputs)
                        except Exception:
                            inputs.append({"role": "image", "filename": "Unavailable input", "copy_key": None, "source_key": None})
                for index, item in enumerate(inputs):
                    item["label"] = f"Image {index + 1}"
                gen.history = snapshot(db, gen, inputs, partial=True)
            if not args.dry_run:
                for image in db.query(Image).filter_by(user_id=gen.user_id, generated_image_id=gen.id):
                    attach_history(db, image, gen.history)
                db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
