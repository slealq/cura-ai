#!/usr/bin/env python3
"""
Initialize the database schema.

Usage:
    python scripts/init_db.py

Creates all tables defined in the SQLAlchemy models.
"""
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def init_db():
    """Initialize database tables."""
    from sqlalchemy import text

    from app.db.base import Base, engine

    # Import all models to register them with Base
    from app.models import Cluster, ClusterMembership, Image, ImageMetadata, Job

    logger.info("Creating database tables...")

    # Create pgvector extension
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    # Create all tables
    Base.metadata.create_all(bind=engine)

    logger.info("Database tables created successfully!")


def main():
    """Main entry point."""
    try:
        init_db()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
