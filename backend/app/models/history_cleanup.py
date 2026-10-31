"""Post-commit history copy garbage collection hooks."""
import logging

logger = logging.getLogger(__name__)


def install_cleanup_hooks():
    """Collect references before ORM/account cascades, enqueue only after commit."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from app.models import GeneratedImage, Image, User

    @event.listens_for(Session, "before_flush")
    def collect(session, flush_context, instances):
        from app.services.image_history import copy_keys
        keys = session.info.setdefault("history_cleanup_keys", set())
        for row in session.deleted:
            if isinstance(row, (Image, GeneratedImage)):
                keys.update(copy_keys(row.history))
            elif isinstance(row, User):
                for model in (Image, GeneratedImage):
                    for (history,) in session.query(model.history).filter(model.user_id == row.id):
                        keys.update(copy_keys(history))

    @event.listens_for(Session, "after_commit")
    def enqueue(session):
        keys = session.info.pop("history_cleanup_keys", set())
        if keys:
            try:
                from app.workers.tasks import cleanup_history_copies
                cleanup_history_copies.delay(sorted(keys))
            except Exception:
                logger.warning("Could not queue history cleanup", exc_info=True)

    @event.listens_for(Session, "after_rollback")
    def rollback(session):
        session.info.pop("history_cleanup_keys", None)
