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
    "nano-banana-pro": {"width": 1024, "height": 1024, "num_inference_steps": 28, "guidance_scale": 3.5, "default_lora_scale": 1.0},
    "flux-dev": {"width": 1024, "height": 1024, "num_inference_steps": 28, "guidance_scale": 3.5, "default_lora_scale": 1.0},
    "qwen-2.5": {"width": 1024, "height": 1024, "num_inference_steps": 28, "guidance_scale": 4.0, "default_lora_scale": 1.0},
}

DEFAULT_EDIT_CONFIGS = {
    "qwen-image-max-edit": {
        "image_size": "square_hd",
        "num_images": 1,
        "output_format": "png",
        "enable_prompt_expansion": True,
        "enable_safety_checker": True,
    },
    "kling-image": {
        "resolution": "1K",
        "aspect_ratio": "auto",
        "num_images": 1,
        "output_format": "png",
    },
    "wan-25": {
        "image_size": "square",
        "num_images": 1,
        "output_format": "png",
        "enable_safety_checker": True,
    },
    "grok-imagine": {
        "num_images": 1,
        "output_format": "jpeg",
    },
    "face-swap": {
        "num_images": 1,
        "enable_occlusion_prevention": False,
    },
}

DEFAULT_BASE_MODEL = "nano-banana-pro"
DEFAULT_EDIT_MODEL = "qwen-image-max-edit"

DEFAULT_PROVIDER_CONFIG = {
    "vision_provider": "openai",
    "embedding_provider": "openai",
    "openai_vision_model": "gpt-4o-mini",
    "openai_embedding_model": "text-embedding-3-small",
    "anthropic_vision_model": "claude-3-haiku-20240307",
    "fal_vision_model": "x-ai/grok-4-fast",
    "max_tokens_tagging": 1000,
    "max_tokens_description": 3000,
    "max_tokens_summarization": 500,
    # Language model settings (text-only tasks: summarization, expansion, suggestions)
    "language_provider": "openai",
    "openai_language_model": "gpt-4o-mini",
    "anthropic_language_model": "claude-3-haiku-20240307",
    "fal_language_model": "x-ai/grok-4-fast",
    "max_tokens_expansion": 500,
    "max_tokens_suggestion": 2000,
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
- Subject type: person, animal, object, food, landscape, architecture, vehicle, artwork, text, abstract
- Framing: close-up, medium-shot, wide-shot, aerial, macro, panoramic
- People (if present): single-person, couple, group, child, adult
- Appearance: clothing style, colors, accessories, notable features
- Activity: standing, sitting, walking, running, eating, working, playing, posing, resting
- Setting: indoor, outdoor, studio, nature, urban, rural, underwater
- Scene: portrait, candid, street, product, food, wildlife, sports, event, still-life
- Mood: bright, dark, warm, cool, dramatic, calm, energetic, moody
- Style: photography, illustration, painting, digital-art, sketch, 3d-render

Only include tags that are clearly present or relevant."""

DEFAULT_DESCRIPTION_GUIDANCE = """Analyze this image and write a single flowing description as one continuous block of text. The image could be anything — a photograph, illustration, painting, screenshot, diagram, or any other visual. The goal is that if someone uses this description to generate an image via AI, the result should match the original as closely as possible.

Start by identifying what the image depicts, then describe it in detail — what is shown, how it is arranged, the composition and framing, the colors, lighting, textures, and any notable details. Work from the most prominent elements to the finer ones.

Do not use headings, bullet points, or labeled sections. Write in plain, specific, observational language as a single cohesive paragraph. Be thorough enough to reproduce the image."""

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

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Get a setting value by key."""
        setting = self.db.query(AppSettings).filter(
            AppSettings.key == key, AppSettings.user_id == self.user_id
        ).first()
        return setting.value if setting else default

    def set_setting(self, key: str, value: str, description: str | None = None) -> AppSettings:
        """Set or update a setting value."""
        setting = self.db.query(AppSettings).filter(
            AppSettings.key == key, AppSettings.user_id == self.user_id
        ).first()
        if setting:
            setting.value = value
            if description:
                setting.description = description
        else:
            setting = AppSettings(key=key, value=value, description=description, user_id=self.user_id)
            self.db.add(setting)
        self.db.commit()
        self.db.refresh(setting)
        return setting

    def delete_setting(self, key: str) -> None:
        """Delete a setting by key."""
        setting = self.db.query(AppSettings).filter(
            AppSettings.key == key, AppSettings.user_id == self.user_id
        ).first()
        if setting:
            self.db.delete(setting)
            self.db.commit()

    # --- Prompt Preset methods ---

    def list_presets(self) -> list[PromptPreset]:
        """List all prompt presets, ordered by name."""
        return self.db.query(PromptPreset).filter(
            PromptPreset.user_id == self.user_id
        ).order_by(PromptPreset.name).all()

    def get_preset(self, preset_id: int) -> PromptPreset | None:
        """Get a single preset by ID."""
        return self.db.query(PromptPreset).filter(
            PromptPreset.id == preset_id, PromptPreset.user_id == self.user_id
        ).first()

    def get_default_preset(self) -> PromptPreset | None:
        """Get the currently active (default) preset."""
        return self.db.query(PromptPreset).filter(
            PromptPreset.is_default.is_(True), PromptPreset.user_id == self.user_id
        ).first()

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
            user_id=self.user_id,
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
            user_id=self.user_id,
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
        self.db.query(PromptPreset).filter(
            PromptPreset.is_default.is_(True), PromptPreset.user_id == self.user_id
        ).update({"is_default": False})
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

    # --- Edit model ---

    def get_edit_model(self) -> str:
        """Get the default edit model."""
        return self.get_setting("edit_model", DEFAULT_EDIT_MODEL) or DEFAULT_EDIT_MODEL

    def set_edit_model(self, edit_model: str) -> str:
        """Set the default edit model."""
        self.set_setting("edit_model", edit_model, description="Default edit model")
        return edit_model

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

    # --- Edit config ---

    def get_edit_config(self, edit_model: str = "qwen-image-max-edit") -> dict:
        """Get edit configuration scoped to an edit model."""
        raw = self.get_setting(f"edit_config:{edit_model}")
        defaults = DEFAULT_EDIT_CONFIGS.get(edit_model, {})
        if raw:
            try:
                config = json.loads(raw)
                return {**defaults, **config}
            except (json.JSONDecodeError, TypeError):
                pass
        return dict(defaults)

    def set_edit_config(self, config: dict, edit_model: str = "qwen-image-max-edit") -> dict:
        """Validate and store edit config scoped to an edit model."""
        current = self.get_edit_config(edit_model)
        defaults = DEFAULT_EDIT_CONFIGS.get(edit_model, {})
        for key in config:
            if key in defaults:
                current[key] = config[key]
        self.set_setting(f"edit_config:{edit_model}", json.dumps(current), description=f"Edit parameters ({edit_model})")
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


def get_settings_service(db: Session, user_id: int) -> SettingsService:
    """Get settings service instance."""
    return SettingsService(db, user_id)
