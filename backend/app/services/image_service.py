"""Image service for managing image operations."""
import logging
import time
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import Image, ImageMetadata, ImageSource, ImageStatus
from app.models.folder import FolderImage
from app.models.image import STATUS_ORDER
from app.models.pipeline_log import LogCategory, LogLevel
from app.services.log_service import write_log
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)


class ImageService:
    """Service for image CRUD and management operations."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.storage = get_storage_service()

    async def ingest_image(
        self,
        file_data: bytes,
        filename: str,
        source: ImageSource,
        original_uri: str | None = None,
        job_id: int | None = None,
    ) -> Image:
        """
        Ingest a new image into the system.

        Args:
            file_data: Raw image bytes
            filename: Original filename
            source: Image source type
            original_uri: Original file URI if applicable

        Returns:
            Created Image model
        """
        start = time.monotonic()

        # Compute hashes for deduplication
        file_hash = self.storage.compute_file_hash(file_data)

        # Check for duplicate (scoped to this user)
        existing = self.db.query(Image).filter(
            Image.file_hash == file_hash,
            Image.user_id == self.user_id,
        ).first()
        if existing:
            logger.info(f"Duplicate image detected: {filename} (hash: {file_hash[:16]}...)")
            write_log(
                category=LogCategory.PIPELINE,
                message=f"Duplicate skipped: {filename}",
                image_id=existing.id,
                job_id=job_id,
                user_id=self.user_id,
                operation="ingest",
                duration_ms=round((time.monotonic() - start) * 1000, 1),
                success=True,
                extra={"duplicate_of": existing.id, "filename": filename},
            )
            return existing

        # Generate unique object key and save
        object_key = self.storage.generate_object_key(filename)
        mime_type = self.storage.get_mime_type(file_data)
        width, height = self.storage.get_image_dimensions(file_data)

        try:
            # Save image
            await self.storage.save_image(file_data, object_key, mime_type)

            # Generate thumbnails
            thumbnails = await self.storage.generate_thumbnails(file_data, object_key)

            # Compute perceptual hash
            perceptual_hash = self.storage.compute_perceptual_hash(file_data)

            # Create database record
            image = Image(
                user_id=self.user_id,
                source=source,
                original_uri=original_uri,
                object_key=object_key,
                original_filename=filename,
                file_hash=file_hash,
                perceptual_hash=perceptual_hash,
                width=width,
                height=height,
                file_size=len(file_data),
                mime_type=mime_type,
                thumbnail_uri_small=thumbnails.get("200"),
                thumbnail_uri_medium=thumbnails.get("400"),
                thumbnail_uri_large=thumbnails.get("800"),
                status=ImageStatus.INGESTED,
                ingested_at=datetime.utcnow(),
            )

            self.db.add(image)
            self.db.commit()
            self.db.refresh(image)

            elapsed = round((time.monotonic() - start) * 1000, 1)
            logger.info(f"Ingested image: {filename} -> {object_key}")
            write_log(
                category=LogCategory.PIPELINE,
                message=f"Ingested: {filename} ({width}x{height}, {len(file_data)} bytes)",
                image_id=image.id,
                job_id=job_id,
                user_id=self.user_id,
                operation="ingest",
                duration_ms=elapsed,
                success=True,
                extra={"filename": filename, "object_key": object_key, "mime_type": mime_type},
            )
            return image
        except Exception as e:
            elapsed = round((time.monotonic() - start) * 1000, 1)
            logger.error(f"Failed to ingest {filename}: {e}")
            write_log(
                category=LogCategory.PIPELINE,
                message=f"Ingest failed: {filename} — {e}",
                level=LogLevel.ERROR,
                job_id=job_id,
                user_id=self.user_id,
                operation="ingest",
                duration_ms=elapsed,
                success=False,
                extra={"filename": filename, "error": str(e)},
            )
            raise

    async def fast_ingest(
        self,
        file_data: bytes,
        filename: str,
        source: ImageSource,
        original_uri: str | None = None,
    ) -> Image | None:
        """
        Fast ingest: minimal processing for batch uploads.

        Only computes SHA-256 hash, checks duplicates, saves the raw file,
        and creates a PENDING Image record. No PIL, no thumbnails, no
        perceptual hash. Uses db.flush() so the caller can batch commits.

        Returns the Image if new, or None if duplicate.
        """
        # Compute SHA-256 hash (fast, ~5ms for 5MB)
        file_hash = self.storage.compute_file_hash(file_data)

        # Check for duplicate (scoped to this user)
        existing = self.db.query(Image).filter(
            Image.file_hash == file_hash,
            Image.user_id == self.user_id,
        ).first()
        if existing:
            logger.info(f"Duplicate image detected: {filename} (hash: {file_hash[:16]}...)")
            return None

        # Generate unique object key
        object_key = self.storage.generate_object_key(filename)

        # Detect MIME type only — dimensions and phash are deferred to the
        # Celery worker (process_ingest_batch) to keep the HTTP handler fast.
        mime_type = self.storage.get_mime_type(file_data)

        # Save raw original to storage (1 write)
        await self.storage.save_image(file_data, object_key, mime_type)

        # Create PENDING record — Celery will populate width/height/phash
        image = Image(
            user_id=self.user_id,
            source=source,
            original_uri=original_uri,
            object_key=object_key,
            original_filename=filename,
            file_hash=file_hash,
            file_size=len(file_data),
            mime_type=mime_type,
            width=None,
            height=None,
            perceptual_hash=None,
            status=ImageStatus.PENDING,
        )

        self.db.add(image)
        try:
            self.db.flush()  # Get the ID without committing — caller batches the commit
        except IntegrityError:
            # Concurrent duplicate: another chunk inserted the same file_hash
            # between our check and this flush. Treat as duplicate.
            self.db.rollback()
            return None

        return image

    def get_image(self, image_id: int) -> Image | None:
        """Get image by ID."""
        return self.db.query(Image).options(
            joinedload(Image.image_metadata)
        ).filter(Image.id == image_id, Image.user_id == self.user_id).first()

    def get_images(
        self,
        status: ImageStatus | None = None,
        min_status: ImageStatus | None = None,
        max_status: ImageStatus | None = None,
        source: ImageSource | None = None,
        in_folder: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Image]:
        """Get paginated list of images."""
        query = self.db.query(Image).options(joinedload(Image.image_metadata)).filter(
            Image.user_id == self.user_id
        )

        if status:
            query = query.filter(Image.status == status)
        elif min_status:
            min_rank = STATUS_ORDER.get(min_status, 0)
            eligible = [s for s, rank in STATUS_ORDER.items() if rank >= min_rank]
            query = query.filter(Image.status.in_(eligible))
        elif max_status:
            max_rank = STATUS_ORDER.get(max_status, 6)
            eligible = [s for s, rank in STATUS_ORDER.items() if rank <= max_rank]
            query = query.filter(Image.status.in_(eligible))
        if source:
            query = query.filter(Image.source == source)
        if in_folder is not None:
            folder_subq = self.db.query(FolderImage.image_id).distinct().subquery()
            if in_folder:
                query = query.filter(Image.id.in_(self.db.query(folder_subq.c.image_id)))
            else:
                query = query.filter(~Image.id.in_(self.db.query(folder_subq.c.image_id)))

        return query.order_by(Image.created_at.desc()).offset(skip).limit(limit).all()

    def get_images_by_ids(self, image_ids: list[int]) -> list[Image]:
        """Get images by list of IDs."""
        return self.db.query(Image).options(
            joinedload(Image.image_metadata)
        ).filter(Image.id.in_(image_ids), Image.user_id == self.user_id).all()

    def get_images_for_clustering(self) -> list[Image]:
        """Get all images with embeddings for clustering (includes already-clustered)."""
        return (
            self.db.query(Image)
            .options(joinedload(Image.image_metadata))
            .filter(
                Image.user_id == self.user_id,
                Image.status.in_([ImageStatus.EMBEDDED, ImageStatus.CLUSTERED]),
            )
            .all()
        )

    def update_status(
        self,
        image_id: int,
        status: ImageStatus,
        error_message: str | None = None,
    ) -> Image | None:
        """Update image processing status."""
        image = self.db.query(Image).filter(Image.id == image_id, Image.user_id == self.user_id).first()
        if image:
            image.status = status
            if error_message:
                image.error_message = error_message
                image.retry_count += 1
            self.db.commit()
            self.db.refresh(image)
        return image

    def save_metadata(
        self,
        image_id: int,
        tags: list[str] | None = None,
        dominant_colors: list[dict] | None = None,
        description_long: str | None = None,
        embedding: list[float] | None = None,
        tagging_model: str | None = None,
        caption_model: str | None = None,
        embedding_model: str | None = None,
        tagging_prompt_version: str | None = None,
        tag_prompt_text: str | None = None,
        description_prompt_text: str | None = None,
        tagged_at: datetime | None = None,
        described_at: datetime | None = None,
        tagging_duration_ms: int | None = None,
        caption_duration_ms: int | None = None,
        embedded_at: datetime | None = None,
        embedding_duration_ms: int | None = None,
    ) -> ImageMetadata | None:
        """Save or update image metadata."""
        metadata = self.db.query(ImageMetadata).filter(
            ImageMetadata.image_id == image_id
        ).first()

        if not metadata:
            metadata = ImageMetadata(image_id=image_id)
            self.db.add(metadata)

        if tags is not None:
            metadata.tags = tags
        if dominant_colors is not None:
            metadata.dominant_colors = dominant_colors
        if description_long is not None:
            metadata.description_long = description_long
        if embedding is not None:
            metadata.embedding = embedding
        if tagging_model is not None:
            metadata.tagging_model = tagging_model
        if caption_model is not None:
            metadata.caption_model = caption_model
        if embedding_model is not None:
            metadata.embedding_model = embedding_model
        if tagging_prompt_version is not None:
            metadata.tagging_prompt_version = tagging_prompt_version
        if tag_prompt_text is not None:
            metadata.tag_prompt_text = tag_prompt_text
        if description_prompt_text is not None:
            metadata.description_prompt_text = description_prompt_text
        if tagged_at is not None:
            metadata.tagged_at = tagged_at
        if described_at is not None:
            metadata.described_at = described_at
        if tagging_duration_ms is not None:
            metadata.tagging_duration_ms = tagging_duration_ms
        if caption_duration_ms is not None:
            metadata.caption_duration_ms = caption_duration_ms
        if embedded_at is not None:
            metadata.embedded_at = embedded_at
        if embedding_duration_ms is not None:
            metadata.embedding_duration_ms = embedding_duration_ms

        self.db.commit()
        self.db.refresh(metadata)
        return metadata

    def count_images(
        self,
        status: ImageStatus | None = None,
        min_status: ImageStatus | None = None,
        max_status: ImageStatus | None = None,
        in_folder: bool | None = None,
    ) -> int:
        """Count images with optional status filter."""
        query = self.db.query(Image).filter(Image.user_id == self.user_id)
        if status:
            query = query.filter(Image.status == status)
        elif min_status:
            min_rank = STATUS_ORDER.get(min_status, 0)
            eligible = [s for s, rank in STATUS_ORDER.items() if rank >= min_rank]
            query = query.filter(Image.status.in_(eligible))
        elif max_status:
            max_rank = STATUS_ORDER.get(max_status, 6)
            eligible = [s for s, rank in STATUS_ORDER.items() if rank <= max_rank]
            query = query.filter(Image.status.in_(eligible))
        if in_folder is not None:
            folder_subq = self.db.query(FolderImage.image_id).distinct().subquery()
            if in_folder:
                query = query.filter(Image.id.in_(self.db.query(folder_subq.c.image_id)))
            else:
                query = query.filter(~Image.id.in_(self.db.query(folder_subq.c.image_id)))
        return query.count()

    async def get_image_data(self, image_id: int) -> bytes | None:
        """Get raw image data for processing."""
        image = self.get_image(image_id)
        if not image:
            return None
        return await self.storage.get_image(image.object_key)

    def delete_image(self, image_id: int) -> bool:
        """Delete an image and its metadata."""
        image = self.db.query(Image).filter(Image.id == image_id, Image.user_id == self.user_id).first()
        if image:
            self.db.delete(image)
            self.db.commit()
            return True
        return False

    def delete_images_batch(self, image_ids: list[int]) -> int:
        """Delete multiple images. Returns count of deleted images."""
        images = self.db.query(Image).filter(
            Image.id.in_(image_ids), Image.user_id == self.user_id
        ).all()
        count = len(images)
        for image in images:
            self.db.delete(image)
        self.db.commit()
        return count


def get_image_service(db: Session, user_id: int) -> ImageService:
    """Get image service instance."""
    return ImageService(db, user_id)
