"""Storage service for image files and thumbnails."""
import hashlib
import logging
import os
import uuid
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import imagehash
from PIL import Image

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class StorageService:
    """Service for storing and retrieving image files."""

    def __init__(self):
        self.storage_backend = settings.storage_backend
        self.local_path = Path(settings.local_storage_path)
        self.thumbnail_sizes = settings.thumbnail_sizes

        if self.storage_backend == "local":
            self._ensure_directories()

    def _ensure_directories(self):
        """Create necessary directories for local storage."""
        (self.local_path / "images").mkdir(parents=True, exist_ok=True)
        (self.local_path / "thumbnails").mkdir(parents=True, exist_ok=True)

    def compute_file_hash(self, file_data: bytes) -> str:
        """Compute SHA-256 hash of file data."""
        return hashlib.sha256(file_data).hexdigest()

    def compute_perceptual_hash(self, file_data: bytes) -> str | None:
        """Compute perceptual hash for image deduplication."""
        try:
            img = Image.open(BytesIO(file_data))
            phash = imagehash.phash(img)
            return str(phash)
        except Exception as e:
            logger.warning(f"Failed to compute perceptual hash: {e}")
            return None

    def generate_object_key(self, original_filename: str) -> str:
        """Generate a unique object key for storage."""
        ext = Path(original_filename).suffix.lower() or ".jpg"
        unique_id = uuid.uuid4().hex
        return f"{unique_id}{ext}"

    async def save_image(
        self, file_data: bytes, object_key: str, mime_type: str
    ) -> str:
        """
        Save image to storage.

        Returns:
            The URI/path where the image was saved
        """
        if self.storage_backend == "local":
            return await self._save_local(file_data, object_key, "images")
        elif self.storage_backend == "s3":
            return await self._save_s3(file_data, object_key, mime_type)
        else:
            raise ValueError(f"Unsupported storage backend: {self.storage_backend}")

    async def _save_local(self, file_data: bytes, object_key: str, subdir: str) -> str:
        """Save file to local filesystem."""
        file_path = self.local_path / subdir / object_key
        file_path.write_bytes(file_data)
        return str(file_path)

    async def _save_s3(self, file_data: bytes, object_key: str, mime_type: str) -> str:
        """Save file to S3."""
        import boto3
        s3 = boto3.client("s3", region_name=settings.s3_region)
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=f"images/{object_key}",
            Body=file_data,
            ContentType=mime_type,
        )
        return f"s3://{settings.s3_bucket}/images/{object_key}"

    async def get_image(self, object_key: str) -> bytes:
        """Retrieve image data from storage."""
        if self.storage_backend == "local":
            file_path = self.local_path / "images" / object_key
            return file_path.read_bytes()
        elif self.storage_backend == "s3":
            import boto3
            s3 = boto3.client("s3", region_name=settings.s3_region)
            response = s3.get_object(
                Bucket=settings.s3_bucket,
                Key=f"images/{object_key}"
            )
            return response["Body"].read()
        else:
            raise ValueError(f"Unsupported storage backend: {self.storage_backend}")

    async def generate_thumbnails(
        self, file_data: bytes, object_key: str
    ) -> dict[str, str]:
        """
        Generate thumbnails at configured sizes.

        Returns:
            Dict mapping size names to URIs
        """
        thumbnails = {}
        base_name = Path(object_key).stem
        ext = Path(object_key).suffix

        try:
            img = Image.open(BytesIO(file_data))
            img = img.convert("RGB")  # Ensure consistent format

            for size in self.thumbnail_sizes:
                thumb_key = f"{base_name}_{size}{ext}"
                thumb_img = img.copy()
                thumb_img.thumbnail((size, size), Image.Resampling.LANCZOS)

                buffer = BytesIO()
                thumb_img.save(buffer, format="JPEG", quality=85)
                thumb_data = buffer.getvalue()

                if self.storage_backend == "local":
                    uri = await self._save_local(thumb_data, thumb_key, "thumbnails")
                else:
                    uri = await self._save_s3(thumb_data, f"thumbnails/{thumb_key}", "image/jpeg")

                thumbnails[str(size)] = uri

        except Exception as e:
            logger.error(f"Failed to generate thumbnails: {e}")

        return thumbnails

    def get_image_dimensions(self, file_data: bytes) -> tuple[int, int]:
        """Get image width and height."""
        img = Image.open(BytesIO(file_data))
        return img.size

    def get_mime_type(self, file_data: bytes) -> str:
        """Detect MIME type from image data."""
        img = Image.open(BytesIO(file_data))
        format_to_mime = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "GIF": "image/gif",
            "WEBP": "image/webp",
            "BMP": "image/bmp",
            "TIFF": "image/tiff",
        }
        return format_to_mime.get(img.format, "image/jpeg")

    def get_thumbnail_url(self, object_key: str, size: str = "medium") -> str:
        """Get URL for thumbnail based on object key and size."""
        size_map = {"small": 200, "medium": 400, "large": 800}
        actual_size = size_map.get(size, 400)
        base_name = Path(object_key).stem
        ext = Path(object_key).suffix
        return f"/api/images/thumbnails/{base_name}_{actual_size}{ext}"


# Singleton instance
_storage_service: StorageService | None = None


def get_storage_service() -> StorageService:
    """Get storage service singleton."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
