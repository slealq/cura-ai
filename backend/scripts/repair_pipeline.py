"""Repair lost jobs and obsolete-model failures after deployment.

Run from backend with DATABASE_URL/CELERY_* configured for the target environment:
    python -m scripts.repair_pipeline --user-id 1 --folder-name Jazz --dry-run
    python -m scripts.repair_pipeline --user-id 1 --folder-name Jazz

No providers are called. Existing descriptions and legitimate provider refusals
are preserved. Re-running is safe. Dry-run rolls back and makes no data changes.
"""
import argparse
from decimal import Decimal

from sqlalchemy import func, or_

from app.db.base import SessionLocal
from app.models import CostDecision, Folder, FolderImage, Image, ImageMetadata, ImageStatus, Job, UserBalance
from app.services.job_recovery import ACTIVE, reap_stale_jobs


def repair(db, user_id, folder_name, dry_run):
    zombies = reap_stale_jobs(db, user_id, dry_run=dry_run)
    # Serialize legacy balance reconciliation with new reservations. Never
    # infer ownership of an in-memory legacy hold while user tasks are active.
    balance_query = db.query(UserBalance).filter(UserBalance.user_id == user_id)
    balance = (balance_query if dry_run else balance_query.with_for_update()).first()
    active = db.query(Job).filter(Job.user_id == user_id, Job.status.in_(ACTIVE)).count()
    tracked = db.query(func.coalesce(func.sum(CostDecision.reserved_sparks), 0)).filter(
        CostDecision.user_id == user_id, CostDecision.reserved_sparks > 0,
    ).scalar()
    orphaned = Decimal('0')
    if balance and (not active or (dry_run and active == zombies)):
        orphaned = max(Decimal('0'), balance.reserved_sparks - tracked)
        if not dry_run:
            balance.reserved_sparks -= orphaned

    images = db.query(Image).join(FolderImage).join(Folder).outerjoin(ImageMetadata).filter(
        Image.user_id == user_id, Folder.user_id == user_id, Folder.name == folder_name,
        Image.status == ImageStatus.FAILED,
        or_(ImageMetadata.description_long.is_(None), ImageMetadata.description_long == ''),
        or_(Image.error_message.is_(None), Image.error_message == '',
            Image.error_message.ilike('%Grok 4 Fast is deprecated%')),
    ).all()
    print(f'Zombie jobs: {zombies}; obsolete/empty-error image failures: {len(images)}; '
          f'legacy untracked reservation to release: {orphaned} sparks')
    if active and not (dry_run and active == zombies):
        print('Active jobs remain: legacy balance reconciliation skipped; rerun after they finish.')
    if not dry_run:
        for image in images:
            image.status = ImageStatus.INGESTED
            image.error_message = None
        db.commit()
    else:
        db.rollback()
    return len(images)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', type=int, required=True)
    parser.add_argument('--folder-name', default='Jazz')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    with SessionLocal() as db:
        repair(db, args.user_id, args.folder_name, args.dry_run)


if __name__ == '__main__':
    main()
