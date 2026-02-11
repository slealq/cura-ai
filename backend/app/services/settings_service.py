"""Service for managing application settings."""
from sqlalchemy.orm import Session

from app.models.settings import AppSettings


class SettingsService:
    """Service for managing application settings."""

    def __init__(self, db: Session):
        self.db = db

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Get a setting value by key."""
        setting = self.db.query(AppSettings).filter(AppSettings.key == key).first()
        return setting.value if setting else default

    def set_setting(self, key: str, value: str, description: str | None = None) -> AppSettings:
        """Set or update a setting value."""
        setting = self.db.query(AppSettings).filter(AppSettings.key == key).first()
        if setting:
            setting.value = value
            if description:
                setting.description = description
        else:
            setting = AppSettings(key=key, value=value, description=description)
            self.db.add(setting)
        self.db.commit()
        self.db.refresh(setting)
        return setting

    def get_default_description_guidance(self) -> str | None:
        """Get default description guidance."""
        return self.get_setting("default_description_guidance")

    def set_default_description_guidance(self, guidance: str | None) -> AppSettings:
        """Set default description guidance."""
        if guidance:
            return self.set_setting(
                "default_description_guidance",
                guidance,
                "Default guidance text to influence description generation",
            )
        else:
            # Remove setting if None
            setting = self.db.query(AppSettings).filter(AppSettings.key == "default_description_guidance").first()
            if setting:
                self.db.delete(setting)
                self.db.commit()
            return None

    def get_default_tag_guidance(self) -> str | None:
        """Get default tag guidance."""
        return self.get_setting("default_tag_guidance")

    def set_default_tag_guidance(self, guidance: str | None) -> AppSettings:
        """Set default tag guidance."""
        if guidance:
            return self.set_setting(
                "default_tag_guidance",
                guidance,
                "Default guidance text to influence tag generation",
            )
        else:
            # Remove setting if None
            setting = self.db.query(AppSettings).filter(AppSettings.key == "default_tag_guidance").first()
            if setting:
                self.db.delete(setting)
                self.db.commit()
            return None


def get_settings_service(db: Session) -> SettingsService:
    """Get settings service instance."""
    return SettingsService(db)
