"""Database base configuration and session management."""
import logging
import time

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

_db_logger = logging.getLogger("cura.db.slow_query")
_SLOW_QUERY_THRESHOLD_MS = 100

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=300,
    connect_args={
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    },
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Slow query detection via SQLAlchemy event listeners
@event.listens_for(engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info["query_start_time"] = time.monotonic()


@event.listens_for(engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    start = conn.info.pop("query_start_time", None)
    if start is None:
        return
    elapsed_ms = (time.monotonic() - start) * 1000
    if elapsed_ms > _SLOW_QUERY_THRESHOLD_MS:
        truncated = statement[:200] + "..." if len(statement) > 200 else statement
        _db_logger.warning(
            f"Slow query ({elapsed_ms:.0f}ms): {truncated}",
            extra={"event_type": "slow_query", "duration_ms": round(elapsed_ms, 1), "statement": truncated},
        )


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


def get_db():
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
