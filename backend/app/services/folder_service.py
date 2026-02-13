"""Folder service for managing folder operations."""
import logging

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.folder import Folder, FolderImage
from app.models.image import Image, ImageStatus
from app.models.image import STATUS_ORDER

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
        return self.db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == self.user_id).first()

    def get_folders(self, skip: int = 0, limit: int = 50) -> list[Folder]:
        return (
            self.db.query(Folder)
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
            folder = self.get_folder(folder_id)
            if folder:
                folder.image_count = (
                    self.db.query(func.count(FolderImage.id))
                    .filter(FolderImage.folder_id == folder_id)
                    .scalar()
                    or 0
                ) + added
            self.db.commit()
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
            folder = self.get_folder(folder_id)
            if folder:
                folder.image_count = (
                    self.db.query(func.count(FolderImage.id))
                    .filter(FolderImage.folder_id == folder_id)
                    .scalar()
                    or 0
                )
            self.db.commit()
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
