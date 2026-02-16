"""Storage service for image files and thumbnails."""
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

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
        (self.local_path / "lora_weights").mkdir(parents=True, exist_ok=True)
        (self.local_path / "folder_covers").mkdir(parents=True, exist_ok=True)
        (self.local_path / "cluster_covers").mkdir(parents=True, exist_ok=True)

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

    async def save_lora_weights(
        self, file_data: bytes, object_key: str, mime_type: str = "application/octet-stream"
    ) -> str:
        """Save LoRA weights file to storage."""
        if self.storage_backend == "local":
            return await self._save_local(file_data, object_key, "lora_weights")
        elif self.storage_backend == "s3":
            return await self._save_s3(file_data, f"lora_weights/{object_key}", mime_type)
        elif self.storage_backend == "azure":
            return await self._save_azure(file_data, f"lora_weights/{object_key}", mime_type)
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

    async def get_lora_weights(self, object_key: str) -> bytes:
        """Retrieve LoRA weights data from storage."""
        if self.storage_backend == "local":
            file_path = self.local_path / "lora_weights" / object_key
            return file_path.read_bytes()
        elif self.storage_backend == "s3":
            import boto3
            s3 = boto3.client("s3", region_name=settings.s3_region)
            response = s3.get_object(
                Bucket=settings.s3_bucket,
                Key=f"lora_weights/{object_key}"
            )
            return response["Body"].read()
        elif self.storage_backend == "azure":
            return await self._get_azure(f"lora_weights/{object_key}")
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

    def generate_thumbnail_sas_url(self, thumbnail_uri: str | None) -> str | None:
        """Generate a direct SAS URL for a thumbnail without any Azure API calls.

        For Azure: uses local HMAC crypto (generate_blob_sas) — zero network calls.
        For local: returns a relative /api/ path that the frontend wraps with authUrl().
        """
        if not thumbnail_uri:
            return None

        filename = self._extract_filename_from_uri(thumbnail_uri)
        if not filename:
            return None

        if self.storage_backend == "azure":
            from azure.storage.blob import BlobSasPermissions, generate_blob_sas

            blob_path = f"thumbnails/{filename}"
            account_name = self._blob_service_client.account_name
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
                expiry=datetime.now(timezone.utc) + timedelta(minutes=30),
            )

            blob_url = f"https://{account_name}.blob.core.windows.net/{self._azure_container_name}/{blob_path}"
            return f"{blob_url}?{sas_token}"
        else:
            return f"/api/images/thumbnails/{filename}"

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

    # --- Delete methods ---

    async def delete_file(self, subdir: str, filename: str) -> bool:
        """Delete a single file from storage. Returns True if deleted, False if not found."""
        if self.storage_backend == "local":
            file_path = self.local_path / subdir / filename
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        elif self.storage_backend == "azure":
            blob_path = f"{subdir}/{filename}"
            blob_client = self._container_client.get_blob_client(blob_path)
            try:
                blob_client.delete_blob()
                return True
            except Exception:
                return False
        else:
            raise ValueError(f"Unsupported storage backend: {self.storage_backend}")

    async def delete_image_files(
        self, object_key: str, thumbnail_uris: list[str]
    ) -> dict[str, int]:
        """Delete original image + all thumbnails. Returns {deleted, failed} counts."""
        deleted = 0
        failed = 0

        # Delete original image
        try:
            if await self.delete_file("images", object_key):
                deleted += 1
        except Exception as e:
            logger.warning(f"Failed to delete image file {object_key}: {e}")
            failed += 1

        # Delete thumbnails
        for uri in thumbnail_uris:
            thumb_filename = self._extract_filename_from_uri(uri)
            if not thumb_filename:
                continue
            try:
                if await self.delete_file("thumbnails", thumb_filename):
                    deleted += 1
            except Exception as e:
                logger.warning(f"Failed to delete thumbnail {thumb_filename}: {e}")
                failed += 1

        return {"deleted": deleted, "failed": failed}

    def _extract_filename_from_uri(self, uri: str) -> str | None:
        """Extract the filename from a storage URI (local path or azure:// URI)."""
        if not uri:
            return None
        # Azure: "azure://images/thumbnails/abc123_200.jpg" → "abc123_200.jpg"
        if uri.startswith("azure://"):
            parts = uri.split("/")
            return parts[-1] if parts else None
        # Local: "/app/storage/thumbnails/abc123_200.jpg" → "abc123_200.jpg"
        return Path(uri).name

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

    # --- Folder cover methods (synchronous for PIL compositing) ---

    def get_thumbnail_bytes_sync(self, thumbnail_uri: str) -> bytes | None:
        """Read thumbnail file bytes synchronously (for PIL compositing)."""
        filename = self._extract_filename_from_uri(thumbnail_uri)
        if not filename:
            return None

        if self.storage_backend == "local":
            file_path = self.local_path / "thumbnails" / filename
            if file_path.exists():
                return file_path.read_bytes()
            return None
        elif self.storage_backend == "azure":
            blob_path = f"thumbnails/{filename}"
            blob_client = self._container_client.get_blob_client(blob_path)
            try:
                downloader = blob_client.download_blob()
                return downloader.readall()
            except Exception:
                return None
        return None

    def save_cover_sync(self, file_data: bytes, subdir: str, filename: str) -> str:
        """Save a cover composite image. Returns the storage URI."""
        if self.storage_backend == "local":
            file_path = self.local_path / subdir / filename
            file_path.write_bytes(file_data)
            return str(file_path)
        elif self.storage_backend == "azure":
            from azure.storage.blob import ContentSettings

            blob_path = f"{subdir}/{filename}"
            blob_client = self._container_client.get_blob_client(blob_path)
            blob_client.upload_blob(
                file_data,
                overwrite=True,
                content_settings=ContentSettings(content_type="image/jpeg"),
            )
            return f"azure://{self._azure_container_name}/{blob_path}"
        else:
            raise ValueError(f"Unsupported storage backend: {self.storage_backend}")

    def save_folder_cover_sync(self, file_data: bytes, folder_id: int) -> str:
        """Save a folder cover composite image. Returns the storage URI."""
        return self.save_cover_sync(file_data, "folder_covers", f"folder_{folder_id}.jpg")

    def save_cluster_cover_sync(self, file_data: bytes, cluster_id: int) -> str:
        """Save a cluster cover composite image. Returns the storage URI."""
        return self.save_cover_sync(file_data, "cluster_covers", f"cluster_{cluster_id}.jpg")

    def delete_cover_sync(self, subdir: str, filename: str) -> bool:
        """Delete a cover composite image. Returns True if deleted."""
        if self.storage_backend == "local":
            file_path = self.local_path / subdir / filename
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        elif self.storage_backend == "azure":
            blob_path = f"{subdir}/{filename}"
            blob_client = self._container_client.get_blob_client(blob_path)
            try:
                blob_client.delete_blob()
                return True
            except Exception:
                return False
        return False

    def delete_folder_cover_sync(self, folder_id: int) -> bool:
        """Delete a folder cover composite image."""
        return self.delete_cover_sync("folder_covers", f"folder_{folder_id}.jpg")

    def delete_cluster_cover_sync(self, cluster_id: int) -> bool:
        """Delete a cluster cover composite image."""
        return self.delete_cover_sync("cluster_covers", f"cluster_{cluster_id}.jpg")

    def generate_cover_sas_url(self, cover_uri: str | None, subdir: str, api_prefix: str) -> str | None:
        """Generate a URL for a cover composite image.

        For Azure: generates a SAS URL via local HMAC crypto.
        For local: returns a relative /api/ path using api_prefix.
        """
        if not cover_uri:
            return None

        filename = self._extract_filename_from_uri(cover_uri)
        if not filename:
            return None

        if self.storage_backend == "azure":
            from azure.storage.blob import BlobSasPermissions, generate_blob_sas

            blob_path = f"{subdir}/{filename}"
            account_name = self._blob_service_client.account_name
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
                expiry=datetime.now(timezone.utc) + timedelta(minutes=30),
            )

            blob_url = f"https://{account_name}.blob.core.windows.net/{self._azure_container_name}/{blob_path}"
            return f"{blob_url}?{sas_token}"
        else:
            return f"{api_prefix}/{filename}"

    def generate_folder_cover_sas_url(self, cover_uri: str | None) -> str | None:
        """Generate a URL for a folder cover composite image."""
        return self.generate_cover_sas_url(cover_uri, "folder_covers", "/api/folders/covers")

    def generate_cluster_cover_sas_url(self, cover_uri: str | None) -> str | None:
        """Generate a URL for a cluster cover composite image."""
        return self.generate_cover_sas_url(cover_uri, "cluster_covers", "/api/clusters/covers")

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
