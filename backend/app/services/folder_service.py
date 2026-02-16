"""Folder service for managing folder operations."""
import logging
from io import BytesIO

from PIL import Image as PILImage
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.folder import Folder, FolderImage
from app.models.image import STATUS_ORDER, Image, ImageStatus
from app.services.cover_utils import generate_cover_composite, sample_candidates
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)


class FolderService:
    """Service for folder CRUD and image management."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id

    def create_folder(self, name: str, description: str | None = None) -> Folder:
        folder = Folder(name=name, description=description, user_id=self.user_id)
        self.db.add(folder)
        self.db.commit()
        self.db.refresh(folder)
        return folder

    def get_folder(self, folder_id: int) -> Folder | None:
        return (
            self.db.query(Folder)
            .options(joinedload(Folder.cover_image))
            .filter(Folder.id == folder_id, Folder.user_id == self.user_id)
            .first()
        )

    def get_folders(self, skip: int = 0, limit: int = 50) -> list[Folder]:
        return (
            self.db.query(Folder)
            .options(joinedload(Folder.cover_image))
            .filter(Folder.user_id == self.user_id)
            .order_by(Folder.updated_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_folders(self) -> int:
        return self.db.query(Folder).filter(Folder.user_id == self.user_id).count()

    def update_folder(
        self, folder_id: int, name: str | None = None, description: str | None = None
    ) -> Folder | None:
        folder = self.get_folder(folder_id)
        if not folder:
            return None
        if name is not None:
            folder.name = name
        if description is not None:
            folder.description = description
        self.db.commit()
        self.db.refresh(folder)
        return folder

    def delete_folder(self, folder_id: int) -> bool:
        folder = self.get_folder(folder_id)
        if not folder:
            return False
        self.db.delete(folder)
        self.db.commit()
        return True

    def delete_folder_with_images(self, folder_id: int) -> dict | None:
        """Delete folder and all its images. Returns info for storage cleanup, or None if not found."""
        folder = self.get_folder(folder_id)
        if not folder:
            return None

        # Query images in folder with their thumbnail URIs
        images = (
            self.db.query(Image)
            .join(FolderImage, FolderImage.image_id == Image.id)
            .filter(FolderImage.folder_id == folder_id)
            .all()
        )

        # Collect file references before deletion
        image_files = []
        for img in images:
            thumbnail_uris = [
                uri for uri in [
                    img.thumbnail_uri_small,
                    img.thumbnail_uri_medium,
                    img.thumbnail_uri_large,
                ] if uri
            ]
            image_files.append({
                "object_key": img.object_key,
                "thumbnail_uris": thumbnail_uris,
            })

        images_deleted = len(images)

        # Delete Image records (ORM cascade handles ImageMetadata,
        # ClusterMembership, FolderImage for ALL folders)
        for img in images:
            self.db.delete(img)

        # Delete the folder itself
        self.db.delete(folder)
        self.db.commit()

        return {
            "folder_id": folder_id,
            "images_deleted": images_deleted,
            "image_files": image_files,
        }

    def refresh_cover_image(self, folder_id: int) -> None:
        """Set cover_image_id to the most recently added image in the folder."""
        folder = self.db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == self.user_id).first()
        if not folder:
            return
        newest = (
            self.db.query(FolderImage.image_id)
            .filter(FolderImage.folder_id == folder_id)
            .order_by(FolderImage.added_at.desc())
            .first()
        )
        folder.cover_image_id = newest[0] if newest else None
        self.db.commit()

    def add_images_to_folder(self, folder_id: int, image_ids: list[int]) -> int:
        """Add images to a folder. Returns count of newly added."""
        # Verify folder belongs to user
        folder_check = self.get_folder(folder_id)
        if not folder_check:
            return 0
        existing = set(
            r[0]
            for r in self.db.query(FolderImage.image_id)
            .filter(FolderImage.folder_id == folder_id, FolderImage.image_id.in_(image_ids))
            .all()
        )
        added = 0
        for image_id in image_ids:
            if image_id not in existing:
                self.db.add(FolderImage(folder_id=folder_id, image_id=image_id))
                added += 1
        if added:
            folder = self.db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == self.user_id).first()
            if folder:
                folder.image_count = (
                    self.db.query(func.count(FolderImage.id))
                    .filter(FolderImage.folder_id == folder_id)
                    .scalar()
                    or 0
                ) + added
            self.db.commit()
            self.refresh_cover_image(folder_id)
            self.generate_cover_composite(folder_id)
        return added

    def remove_images_from_folder(self, folder_id: int, image_ids: list[int]) -> int:
        """Remove images from a folder. Returns count removed."""
        # Verify folder belongs to user
        folder_check = self.get_folder(folder_id)
        if not folder_check:
            return 0
        deleted = (
            self.db.query(FolderImage)
            .filter(FolderImage.folder_id == folder_id, FolderImage.image_id.in_(image_ids))
            .delete(synchronize_session=False)
        )
        if deleted:
            folder = self.db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == self.user_id).first()
            if folder:
                folder.image_count = (
                    self.db.query(func.count(FolderImage.id))
                    .filter(FolderImage.folder_id == folder_id)
                    .scalar()
                    or 0
                )
            self.db.commit()
            self.refresh_cover_image(folder_id)
            self.generate_cover_composite(folder_id)
        return deleted

    def get_folder_images(
        self,
        folder_id: int,
        status: ImageStatus | None = None,
        min_status: ImageStatus | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Image]:
        query = (
            self.db.query(Image)
            .options(joinedload(Image.image_metadata))
            .join(FolderImage, FolderImage.image_id == Image.id)
            .filter(FolderImage.folder_id == folder_id)
        )
        if status:
            query = query.filter(Image.status == status)
        elif min_status:
            min_rank = STATUS_ORDER.get(min_status, 0)
            eligible = [s for s, rank in STATUS_ORDER.items() if rank >= min_rank]
            query = query.filter(Image.status.in_(eligible))
        return query.order_by(FolderImage.added_at.desc()).offset(skip).limit(limit).all()

    def count_folder_images(
        self,
        folder_id: int,
        status: ImageStatus | None = None,
        min_status: ImageStatus | None = None,
    ) -> int:
        query = (
            self.db.query(func.count(FolderImage.id))
            .join(Image, FolderImage.image_id == Image.id)
            .filter(FolderImage.folder_id == folder_id)
        )
        if status:
            query = query.filter(Image.status == status)
        elif min_status:
            min_rank = STATUS_ORDER.get(min_status, 0)
            eligible = [s for s, rank in STATUS_ORDER.items() if rank >= min_rank]
            query = query.filter(Image.status.in_(eligible))
        return query.scalar() or 0

    def get_folder_image_ids(self, folder_id: int) -> list[int]:
        rows = (
            self.db.query(FolderImage.image_id)
            .filter(FolderImage.folder_id == folder_id)
            .all()
        )
        return [r[0] for r in rows]

    def generate_cover_composite(self, folder_id: int) -> None:
        """Generate a justified-row composite JPEG for a folder cover."""
        storage = get_storage_service()

        # Fetch up to 20 candidates, sample up to 6
        candidates = self.get_folder_preview_images(folder_id, count=20)

        if not candidates:
            # No images — clear the cover
            folder = self.db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == self.user_id).first()
            if folder:
                storage.delete_folder_cover_sync(folder_id)
                folder.cover_thumbnail_uri = None
                self.db.commit()
            return

        selected = sample_candidates(candidates)

        # Load PIL images from thumbnails
        pil_images: list[PILImage.Image] = []
        for img in selected:
            uri = img.thumbnail_uri_medium or img.thumbnail_uri_small
            if not uri:
                continue
            data = storage.get_thumbnail_bytes_sync(uri)
            if data:
                try:
                    pil_images.append(PILImage.open(BytesIO(data)).convert("RGB"))
                except Exception:
                    continue

        jpeg_data = generate_cover_composite(pil_images)
        if jpeg_data is None:
            return

        uri = storage.save_folder_cover_sync(jpeg_data, folder_id)

        folder = self.db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == self.user_id).first()
        if folder:
            folder.cover_thumbnail_uri = uri
            self.db.commit()

    def get_folder_preview_images(self, folder_id: int, count: int = 4) -> list[Image]:
        return (
            self.db.query(Image)
            .join(FolderImage, FolderImage.image_id == Image.id)
            .filter(FolderImage.folder_id == folder_id)
            .order_by(FolderImage.added_at.desc())
            .limit(count)
            .all()
        )

    def get_image_folders(self, image_id: int) -> list[Folder]:
        return (
            self.db.query(Folder)
            .join(FolderImage, FolderImage.folder_id == Folder.id)
            .filter(FolderImage.image_id == image_id, Folder.user_id == self.user_id)
            .order_by(Folder.name)
            .all()
        )


def get_folder_service(db: Session, user_id: int) -> FolderService:
    """Get folder service instance."""
    return FolderService(db, user_id)
