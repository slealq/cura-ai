"""Storage service for image files and thumbnails."""
import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
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
        elif self.storage_backend == "azure":
            self._init_azure()

    def _ensure_directories(self):
        """Create necessary directories for local storage."""
        (self.local_path / "images").mkdir(parents=True, exist_ok=True)
        (self.local_path / "thumbnails").mkdir(parents=True, exist_ok=True)
        (self.local_path / "generated").mkdir(parents=True, exist_ok=True)
        (self.local_path / "generated_thumbnails").mkdir(parents=True, exist_ok=True)

    def _init_azure(self):
        """Initialize Azure Blob Storage client."""
        from azure.storage.blob import BlobServiceClient

        self._azure_connection_string = settings.azure_storage_connection_string
        self._azure_container_name = settings.azure_storage_container
        self._blob_service_client = BlobServiceClient.from_connection_string(
            self._azure_connection_string
        )
        self._container_client = self._blob_service_client.get_container_client(
            self._azure_container_name
        )
        # Ensure container exists
        try:
            self._container_client.get_container_properties()
        except Exception:
            self._container_client.create_container()

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

    # --- Save methods ---

    async def save_image(
        self, file_data: bytes, object_key: str, mime_type: str
    ) -> str:
        """Save image to storage. Returns the URI/path where the image was saved."""
        if self.storage_backend == "local":
            return await self._save_local(file_data, object_key, "images")
        elif self.storage_backend == "s3":
            return await self._save_s3(file_data, object_key, mime_type)
        elif self.storage_backend == "azure":
            return await self._save_azure(file_data, f"images/{object_key}", mime_type)
        else:
            raise ValueError(f"Unsupported storage backend: {self.storage_backend}")

    async def save_generated_image(
        self, file_data: bytes, object_key: str, mime_type: str
    ) -> str:
        """Save a generated image to storage."""
        if self.storage_backend == "local":
            return await self._save_local(file_data, object_key, "generated")
        elif self.storage_backend == "s3":
            return await self._save_s3(file_data, f"generated/{object_key}", mime_type)
        elif self.storage_backend == "azure":
            return await self._save_azure(file_data, f"generated/{object_key}", mime_type)
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

    async def _save_azure(self, file_data: bytes, blob_path: str, mime_type: str) -> str:
        """Save file to Azure Blob Storage."""
        from azure.storage.blob import ContentSettings

        blob_client = self._container_client.get_blob_client(blob_path)
        blob_client.upload_blob(
            file_data,
            overwrite=True,
            content_settings=ContentSettings(content_type=mime_type),
        )
        return f"azure://{self._azure_container_name}/{blob_path}"

    # --- Get methods ---

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
        elif self.storage_backend == "azure":
            return await self._get_azure(f"images/{object_key}")
        else:
            raise ValueError(f"Unsupported storage backend: {self.storage_backend}")

    async def get_generated_image(self, object_key: str) -> bytes:
        """Retrieve generated image data from storage."""
        if self.storage_backend == "local":
            file_path = self.local_path / "generated" / object_key
            return file_path.read_bytes()
        elif self.storage_backend == "s3":
            import boto3
            s3 = boto3.client("s3", region_name=settings.s3_region)
            response = s3.get_object(
                Bucket=settings.s3_bucket,
                Key=f"generated/{object_key}"
            )
            return response["Body"].read()
        elif self.storage_backend == "azure":
            return await self._get_azure(f"generated/{object_key}")
        else:
            raise ValueError(f"Unsupported storage backend: {self.storage_backend}")

    async def _get_azure(self, blob_path: str) -> bytes:
        """Download blob bytes from Azure Blob Storage."""
        blob_client = self._container_client.get_blob_client(blob_path)
        downloader = blob_client.download_blob()
        return downloader.readall()

    # --- File response methods (for serving endpoints) ---

    def get_file_response(self, subdir: str, filename: str, media_type: str = "image/jpeg"):
        """
        Return an appropriate response for serving a file.

        For Azure: returns a RedirectResponse to a time-limited SAS URL.
        For local: returns a FileResponse from disk.
        Returns None if the file doesn't exist.
        """
        if self.storage_backend == "azure":
            from fastapi.responses import RedirectResponse

            blob_path = f"{subdir}/{filename}"
            sas_url = self._generate_sas_url(blob_path)
            if sas_url is None:
                return None
            return RedirectResponse(url=sas_url, status_code=302)
        else:
            from fastapi.responses import FileResponse

            file_path = self.local_path / subdir / filename
            if not file_path.exists():
                return None
            return FileResponse(str(file_path), media_type=media_type)

    def get_file_response_with_filename(
        self, subdir: str, filename: str, media_type: str = "image/jpeg",
        download_filename: str | None = None,
    ):
        """
        Like get_file_response but allows setting a download filename.

        For Azure: returns a RedirectResponse to a SAS URL with content-disposition.
        For local: returns a FileResponse with filename.
        """
        if self.storage_backend == "azure":
            from fastapi.responses import RedirectResponse

            blob_path = f"{subdir}/{filename}"
            sas_url = self._generate_sas_url(blob_path, content_disposition=download_filename)
            if sas_url is None:
                return None
            return RedirectResponse(url=sas_url, status_code=302)
        else:
            from fastapi.responses import FileResponse

            file_path = self.local_path / subdir / filename
            if not file_path.exists():
                return None
            return FileResponse(
                str(file_path), media_type=media_type, filename=download_filename
            )

    def _generate_sas_url(
        self, blob_path: str, expiry_minutes: int = 30,
        content_disposition: str | None = None,
    ) -> str | None:
        """Generate a time-limited read-only SAS URL for a blob."""
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        # Check blob exists
        blob_client = self._container_client.get_blob_client(blob_path)
        try:
            blob_client.get_blob_properties()
        except Exception:
            return None

        # Extract account name and key from connection string
        account_name = self._blob_service_client.account_name
        # Parse the account key from the connection string
        account_key = None
        for part in self._azure_connection_string.split(";"):
            if part.startswith("AccountKey="):
                account_key = part[len("AccountKey="):]
                break

        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=self._azure_container_name,
            blob_name=blob_path,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes),
            content_disposition=f'inline; filename="{content_disposition}"' if content_disposition else None,
        )

        return f"{blob_client.url}?{sas_token}"

    # --- Thumbnail generation ---

    async def generate_thumbnails(
        self, file_data: bytes, object_key: str
    ) -> dict[str, str]:
        """Generate thumbnails at configured sizes. Returns dict mapping size names to URIs."""
        thumbnails = {}
        base_name = Path(object_key).stem
        ext = Path(object_key).suffix

        try:
            img = Image.open(BytesIO(file_data))
            img = img.convert("RGB")

            for size in self.thumbnail_sizes:
                thumb_key = f"{base_name}_{size}{ext}"
                thumb_img = img.copy()
                thumb_img.thumbnail((size, size), Image.Resampling.LANCZOS)

                buffer = BytesIO()
                thumb_img.save(buffer, format="JPEG", quality=85)
                thumb_data = buffer.getvalue()

                if self.storage_backend == "local":
                    uri = await self._save_local(thumb_data, thumb_key, "thumbnails")
                elif self.storage_backend == "azure":
                    uri = await self._save_azure(thumb_data, f"thumbnails/{thumb_key}", "image/jpeg")
                else:
                    uri = await self._save_s3(thumb_data, f"thumbnails/{thumb_key}", "image/jpeg")

                thumbnails[str(size)] = uri

        except Exception as e:
            logger.error(f"Failed to generate thumbnails: {e}")

        return thumbnails

    async def generate_generated_thumbnails(
        self, file_data: bytes, object_key: str
    ) -> dict[str, str]:
        """Generate thumbnails for a generated image (small + medium only)."""
        thumbnails = {}
        base_name = Path(object_key).stem
        ext = Path(object_key).suffix

        try:
            img = Image.open(BytesIO(file_data))
            img = img.convert("RGB")

            for size in [200, 400]:
                thumb_key = f"{base_name}_{size}{ext}"
                thumb_img = img.copy()
                thumb_img.thumbnail((size, size), Image.Resampling.LANCZOS)

                buffer = BytesIO()
                thumb_img.save(buffer, format="JPEG", quality=85)
                thumb_data = buffer.getvalue()

                if self.storage_backend == "local":
                    uri = await self._save_local(thumb_data, thumb_key, "generated_thumbnails")
                elif self.storage_backend == "azure":
                    uri = await self._save_azure(
                        thumb_data, f"generated_thumbnails/{thumb_key}", "image/jpeg"
                    )
                else:
                    uri = await self._save_s3(
                        thumb_data, f"generated_thumbnails/{thumb_key}", "image/jpeg"
                    )

                thumbnails[str(size)] = uri

        except Exception as e:
            logger.error(f"Failed to generate thumbnails for generated image: {e}")

        return thumbnails

    # --- Utility methods ---

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
