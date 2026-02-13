"""Service for managing application settings."""
import json

from sqlalchemy.orm import Session

from app.models.prompt_preset import PromptPreset
from app.models.settings import AppSettings

DEFAULT_GENERATION_CONFIG = {
    "width": 1024,
    "height": 1024,
    "num_inference_steps": 28,
    "guidance_scale": 3.5,
    "default_lora_scale": 1.0,
}

DEFAULT_TRAINING_CONFIG = {
    "steps": 1000,
    "is_style": False,
    "learning_rate": 0.0005,
}

# Per-model defaults
DEFAULT_TRAINING_CONFIGS = {
    "flux-dev": {"steps": 1000, "is_style": False},
    "qwen-2.5": {"steps": 2000, "learning_rate": 0.0005},
}

DEFAULT_GENERATION_CONFIGS = {
    "flux-dev": {"width": 1024, "height": 1024, "num_inference_steps": 28, "guidance_scale": 3.5, "default_lora_scale": 1.0},
    "qwen-2.5": {"width": 1024, "height": 1024, "num_inference_steps": 28, "guidance_scale": 4.0, "default_lora_scale": 1.0},
}

DEFAULT_BASE_MODEL = "flux-dev"

DEFAULT_PROVIDER_CONFIG = {
    "vision_provider": "openai",
    "embedding_provider": "openai",
    "openai_vision_model": "gpt-4o",
    "openai_embedding_model": "text-embedding-3-small",
    "anthropic_vision_model": "claude-sonnet-4-20250514",
    "max_tokens_tagging": 1000,
    "max_tokens_description": 3000,
    "max_tokens_summarization": 500,
}

DEFAULT_CLUSTERING_CONFIG = {
    "method": "hdbscan",
    "use_umap": True,
    "umap_n_components": 15,
    "umap_n_neighbors": 15,
    "umap_min_dist": 0.0,
    "umap_metric": "cosine",
    "hdbscan_min_cluster_size": 15,
    "hdbscan_min_samples": 5,
    "hdbscan_cluster_selection_method": "eom",
    "kmeans_max_clusters": 50,
}


# Factory-default GUIDANCE (user-controlled portion only).
# The system wraps these with JSON format + error handling instructions.
DEFAULT_TAG_GUIDANCE = """Tags should categorize the image across these dimensions:
- Framing: full-body, upper-body, lower-body, feet-close-up, face-close-up, hands-close-up, medium-shot, wide-shot
- People: single-woman, single-man, multiple-people, couple, group
- Clothing: nude, semi-nude, clothed, lingerie, swimwear, dress, casual, formal, heels, barefoot
- Body features: soles-visible, toenails-visible, fingernails-visible, tattoos, piercings
- Activity: standing, sitting, lying-down, walking, posing, kneeling, bending-over
- Setting: indoor, outdoor, studio, bedroom, bathroom, beach, nature, urban
- Content: portrait, candid, artistic, professional, selfie, mirror

Only include tags that are clearly present or relevant."""

DEFAULT_DESCRIPTION_GUIDANCE = """Analyze this image and provide a detailed description organized by sections. The goal is that if someone uses this description to generate an image via AI, the result should match the original image as closely as possible.

Sections to cover (include all that are relevant):

**Subject**: Person(s) - clothing, pose, position of hands and legs, action, body position and orientation.

**Face & Hair**: Hair style, color, length. Facial expression, makeup, notable features.

**Body Details**: Nails (fingers/toes) - colors, shape, length. Accessories, jewelry, tattoos.

**Camera**: Camera angle, distance, perspective relative to subject. Framing (close-up, medium shot, full body).

**Background**: Setting description, colors, objects, depth of field.

**Lighting**: Quality, direction, color temperature, shadows.

**Special Focus**: If the image emphasizes feet, describe feet in detail - toenails, nail colors, nail shapes, sole visibility, toe positioning. If adult content, describe what is visible, body positioning, and physical details explicitly.

Be specific, observational, and thorough. Write in plain descriptive language. The description should be long and detailed enough to reproduce the image."""

# Keep old names as aliases for backward compatibility with imports
DEFAULT_TAG_PROMPT = DEFAULT_TAG_GUIDANCE
DEFAULT_DESCRIPTION_PROMPT = DEFAULT_DESCRIPTION_GUIDANCE


# --- System format templates (not user-editable) ---

TAG_SYSTEM_TEMPLATE = """Analyze this image and return a JSON object with a flat list of tags for categorization purposes.

Return ONLY a valid JSON object with a single key "tags" containing an array of relevant tags (lowercase, hyphenated for multi-word).

{guidance}

If you cannot generate tags for this image for any reason, return the JSON with an empty tags array and include an "error" key with a brief explanation of why.

Return ONLY valid JSON in one of these exact formats:
Success: {{"tags": ["tag-1", "tag-2", "tag-3"]}}
Failure: {{"tags": [], "error": "brief reason"}}"""

DESCRIPTION_SYSTEM_TEMPLATE = """{guidance}

You MUST return your response as a valid JSON object in one of these exact formats:
Success: {{"description": "your full description text here"}}
Failure: {{"description": null, "error": "brief reason why the description could not be generated"}}

If you cannot generate a description for this image for any reason, you MUST still return valid JSON with the error format above. Never refuse without using the JSON error format.

Return ONLY valid JSON, no other text."""


def compose_tag_prompt(guidance: str) -> str:
    """Wrap user tag guidance with system format instructions."""
    return TAG_SYSTEM_TEMPLATE.format(guidance=guidance)


def compose_description_prompt(guidance: str) -> str:
    """Wrap user description guidance with system format instructions."""
    return DESCRIPTION_SYSTEM_TEMPLATE.format(guidance=guidance)


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

    def delete_setting(self, key: str) -> None:
        """Delete a setting by key."""
        setting = self.db.query(AppSettings).filter(AppSettings.key == key).first()
        if setting:
            self.db.delete(setting)
            self.db.commit()

    # --- Prompt Preset methods ---

    def list_presets(self) -> list[PromptPreset]:
        """List all prompt presets, ordered by name."""
        return self.db.query(PromptPreset).order_by(PromptPreset.name).all()

    def get_preset(self, preset_id: int) -> PromptPreset | None:
        """Get a single preset by ID."""
        return self.db.query(PromptPreset).filter(PromptPreset.id == preset_id).first()

    def get_default_preset(self) -> PromptPreset | None:
        """Get the currently active (default) preset."""
        return self.db.query(PromptPreset).filter(PromptPreset.is_default.is_(True)).first()

    def _ensure_default_preset(self) -> PromptPreset:
        """Get the active preset, creating a Default one if none exists."""
        preset = self.get_default_preset()
        if preset:
            return preset
        preset = PromptPreset(
            name="Default",
            tag_prompt=DEFAULT_TAG_GUIDANCE,
            description_prompt=DEFAULT_DESCRIPTION_GUIDANCE,
            is_default=True,
        )
        self.db.add(preset)
        self.db.commit()
        self.db.refresh(preset)
        return preset

    def create_preset(self, name: str, tag_prompt: str, description_prompt: str) -> PromptPreset:
        """Create a new preset."""
        preset = PromptPreset(
            name=name,
            tag_prompt=tag_prompt,
            description_prompt=description_prompt,
            is_default=False,
        )
        self.db.add(preset)
        self.db.commit()
        self.db.refresh(preset)
        return preset

    def update_preset(self, preset_id: int, name: str | None = None, tag_prompt: str | None = None, description_prompt: str | None = None) -> PromptPreset | None:
        """Update an existing preset's fields."""
        preset = self.get_preset(preset_id)
        if not preset:
            return None
        if name is not None:
            preset.name = name
        if tag_prompt is not None:
            preset.tag_prompt = tag_prompt
        if description_prompt is not None:
            preset.description_prompt = description_prompt
        self.db.commit()
        self.db.refresh(preset)
        return preset

    def delete_preset(self, preset_id: int) -> bool:
        """Delete a preset. Returns False if it's the active preset (cannot delete)."""
        preset = self.get_preset(preset_id)
        if not preset:
            return False
        if preset.is_default:
            return False
        self.db.delete(preset)
        self.db.commit()
        return True

    def set_default_preset(self, preset_id: int) -> PromptPreset | None:
        """Set a preset as the active default. Clears is_default on all others."""
        preset = self.get_preset(preset_id)
        if not preset:
            return None
        self.db.query(PromptPreset).filter(PromptPreset.is_default.is_(True)).update({"is_default": False})
        preset.is_default = True
        self.db.commit()
        self.db.refresh(preset)
        return preset

    # --- Clustering config ---

    def get_clustering_config(self) -> dict:
        """Get clustering configuration from DB, or return defaults."""
        raw = self.get_setting("clustering_config")
        if raw:
            try:
                config = json.loads(raw)
                # Merge with defaults so new keys are always present
                merged = {**DEFAULT_CLUSTERING_CONFIG, **config}
                return merged
            except (json.JSONDecodeError, TypeError):
                pass
        return dict(DEFAULT_CLUSTERING_CONFIG)

    def set_clustering_config(self, config: dict) -> dict:
        """Validate and store clustering config. Accepts partial dict, merges with defaults."""
        current = self.get_clustering_config()
        # Only keep known keys
        for key in config:
            if key in DEFAULT_CLUSTERING_CONFIG:
                current[key] = config[key]
        self.set_setting("clustering_config", json.dumps(current), description="Clustering parameters")
        return current

    # --- Base model ---

    def get_base_model(self) -> str:
        """Get the active base model."""
        return self.get_setting("base_model", DEFAULT_BASE_MODEL) or DEFAULT_BASE_MODEL

    def set_base_model(self, base_model: str) -> str:
        """Set the active base model."""
        self.set_setting("base_model", base_model, description="Active base model for generation/training")
        return base_model

    # --- Generation / Training config ---

    def get_generation_config(self, base_model: str | None = None) -> dict:
        """Get generation configuration, optionally scoped to a base model."""
        if base_model:
            # Try model-scoped key first
            raw = self.get_setting(f"generation_config:{base_model}")
            if raw:
                try:
                    config = json.loads(raw)
                    defaults = DEFAULT_GENERATION_CONFIGS.get(base_model, DEFAULT_GENERATION_CONFIG)
                    return {**defaults, **config}
                except (json.JSONDecodeError, TypeError):
                    pass
            # Fall back to model defaults
            return dict(DEFAULT_GENERATION_CONFIGS.get(base_model, DEFAULT_GENERATION_CONFIG))

        # Legacy: unscoped
        raw = self.get_setting("generation_config")
        if raw:
            try:
                config = json.loads(raw)
                return {**DEFAULT_GENERATION_CONFIG, **config}
            except (json.JSONDecodeError, TypeError):
                pass
        return dict(DEFAULT_GENERATION_CONFIG)

    def set_generation_config(self, config: dict, base_model: str | None = None) -> dict:
        """Validate and store generation config, optionally scoped to a base model."""
        if base_model:
            current = self.get_generation_config(base_model)
            defaults = DEFAULT_GENERATION_CONFIGS.get(base_model, DEFAULT_GENERATION_CONFIG)
            for key in config:
                if key in defaults:
                    current[key] = config[key]
            self.set_setting(f"generation_config:{base_model}", json.dumps(current), description=f"Generation parameters ({base_model})")
            return current

        # Legacy: unscoped
        current = self.get_generation_config()
        for key in config:
            if key in DEFAULT_GENERATION_CONFIG:
                current[key] = config[key]
        self.set_setting("generation_config", json.dumps(current), description="Generation parameters")
        return current

    def get_training_config(self, base_model: str | None = None) -> dict:
        """Get training configuration, optionally scoped to a base model."""
        if base_model:
            raw = self.get_setting(f"training_config:{base_model}")
            if raw:
                try:
                    config = json.loads(raw)
                    defaults = DEFAULT_TRAINING_CONFIGS.get(base_model, DEFAULT_TRAINING_CONFIG)
                    return {**defaults, **config}
                except (json.JSONDecodeError, TypeError):
                    pass
            return dict(DEFAULT_TRAINING_CONFIGS.get(base_model, DEFAULT_TRAINING_CONFIG))

        # Legacy: unscoped
        raw = self.get_setting("training_config")
        if raw:
            try:
                config = json.loads(raw)
                return {**DEFAULT_TRAINING_CONFIG, **config}
            except (json.JSONDecodeError, TypeError):
                pass
        return dict(DEFAULT_TRAINING_CONFIG)

    def set_training_config(self, config: dict, base_model: str | None = None) -> dict:
        """Validate and store training config, optionally scoped to a base model."""
        if base_model:
            current = self.get_training_config(base_model)
            defaults = DEFAULT_TRAINING_CONFIGS.get(base_model, DEFAULT_TRAINING_CONFIG)
            for key in config:
                if key in defaults:
                    current[key] = config[key]
            self.set_setting(f"training_config:{base_model}", json.dumps(current), description=f"Training parameters ({base_model})")
            return current

        # Legacy: unscoped
        current = self.get_training_config()
        for key in config:
            if key in DEFAULT_TRAINING_CONFIG:
                current[key] = config[key]
        self.set_setting("training_config", json.dumps(current), description="Training parameters")
        return current

    # --- Provider config ---

    def get_provider_config(self) -> dict:
        """Get provider configuration from DB, or return defaults."""
        raw = self.get_setting("provider_config")
        if raw:
            try:
                config = json.loads(raw)
                return {**DEFAULT_PROVIDER_CONFIG, **config}
            except (json.JSONDecodeError, TypeError):
                pass
        return dict(DEFAULT_PROVIDER_CONFIG)

    def set_provider_config(self, config: dict) -> dict:
        """Validate and store provider config. Accepts partial dict, merges with defaults."""
        current = self.get_provider_config()
        for key in config:
            if key in DEFAULT_PROVIDER_CONFIG:
                current[key] = config[key]
        self.set_setting("provider_config", json.dumps(current), description="Provider configuration")
        return current

    # --- Prompt getters (compose system format + guidance from active preset) ---

    def get_tag_prompt(self) -> str:
        """Get the full composed tag prompt (system format + active preset guidance)."""
        guidance = self._ensure_default_preset().tag_prompt
        return compose_tag_prompt(guidance)

    def get_description_prompt(self) -> str:
        """Get the full composed description prompt (system format + active preset guidance)."""
        guidance = self._ensure_default_preset().description_prompt
        return compose_description_prompt(guidance)


def get_settings_service(db: Session) -> SettingsService:
    """Get settings service instance."""
    return SettingsService(db)
