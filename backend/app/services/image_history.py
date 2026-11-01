"""Immutable run snapshots. References are resolved by stable keys, never trusted JSON IDs."""
import copy
import hashlib
import io
import logging

from PIL import Image as PILImage
from PIL import ImageOps
from sqlalchemy import func

from app.models import GeneratedImage, Image, ImageHistoryLink, LoraModel
from app.services.model_catalog import get_image_model

logger = logging.getLogger(__name__)


def snapshot(db, gen, inputs=None, partial=False):
    backfilled = partial
    params = gen.generation_params or {}
    kind = "edit" if params.get("mode") == "edit" else "generate"
    key = params.get("edit_model", gen.base_model) if kind == "edit" else gen.base_model
    model = get_image_model(key, kind)
    loras = []
    entries = params.get("loras", [])
    if "loras" not in params and gen.lora_model_id:
        entries = [{"lora_model_id": gen.lora_model_id, "lora_scale": gen.lora_scale or 1.0}]
    for entry in entries:
        lora = db.query(LoraModel).filter(LoraModel.id == entry["lora_model_id"], LoraModel.user_id == gen.user_id).first()
        loras.append({"id": entry["lora_model_id"], "name": lora.name if lora else entry.get("lora_model_name") or "Unknown LoRA",
                      "strength": entry.get("lora_scale", 1.0),
                      "base_model": lora.base_model if lora else None, "trigger_word": lora.trigger_word if lora else None})
        created_at = getattr(lora, "created_at", None) if lora else None
        if created_at:
            loras[-1]["created_at"] = created_at.isoformat()
        partial = partial or lora is None
    run_prompt = gen.prompt
    settings = {k: v for k, v in params.items() if k not in ("sources", "loras", "actual_seed", "mode", "edit_model")}
    partial = partial or any(not item.get("copy_key") for item in inputs or [])
    if model and not backfilled:
        from app.providers.fal_provider import build_image_request
        values = dict(params, negative_prompt=gen.negative_prompt)
        # Mask bytes are stored as a separate input, not a provider URL in params.
        if key == "kling-image" and "ordered" in params.get("sources", {}):
            values["subject_sources"] = params["sources"]["ordered"]
        auto_context = values.get("precision_area") == "auto"
        if auto_context:
            values.pop("precision_area")
        if kind == "generate":
            values = {"width": 1024, "height": 1024, "num_inference_steps": 28, "guidance_scale": 3.5, **values}
        _, arguments = build_image_request(model, gen.prompt, values,
                                            source_urls=["input"] * len([item for item in inputs or [] if item.get("role") != "mask"]) if kind == "edit" else None)
        if auto_context:
            arguments.update(edit_precision="high", context_window="auto")
        run_prompt = arguments["prompt"]
        settings = {k: v for k, v in arguments.items() if k not in ("prompt", "negative_prompt", "image_url", "image_urls", "reference_image_urls", "loras")}
    return {"version": 1, "job_type": kind, "date": gen.created_at.isoformat() + ("Z" if gen.created_at.tzinfo is None else ""),
            "prompt": run_prompt, "negative_prompt": gen.negative_prompt,
            "model": {"key": key, "name": model.label if model else key}, "provider": gen.generation_provider,
            "settings": settings,
            "seed": params.get("actual_seed"), "charged_cost": None,
            "loras": loras, "inputs": inputs or [], "partial": partial}


def safe_snapshot(db, gen, inputs=None):
    """History is best effort: a snapshot bug must never fail a paid job."""
    try:
        return snapshot(db, gen, inputs)
    except Exception:
        logger.warning("Could not build history for generation %s", gen.id, exc_info=True)
        return None


async def input_snapshot(storage, user_id, data, filename, source_key=None, role="image", uploaded=False):
    """Copy failure is isolated from the model call; hashes share copies per user."""
    item = {"role": role, "filename": filename, "source_key": source_key, "copy_key": None,
            "width": None, "height": None, "file_hash": None, "uploaded": uploaded}
    try:
        digest = hashlib.sha256(data).hexdigest()
        item["file_hash"] = digest
        with PILImage.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            item["width"], item["height"] = image.size
            output = io.BytesIO()
            if role == "mask":
                # Retain the exact canonical mask, independently of temporary uploads.
                image.convert("L").save(output, format="PNG")
            else:
                image = image.convert("RGB")
                image.thumbnail((800, 800))
                image.save(output, format="JPEG", quality=85)
        key = f"{user_id}-{digest}{'-mask.png' if role == 'mask' else '.jpg'}"
        import asyncio
        await asyncio.wait_for(storage.save_history_copy(output.getvalue(), key), timeout=5)
        item["copy_key"] = key
    except Exception:
        logger.warning("Could not save history input copy", exc_info=True)
    return item


def attach_history(db, image, history):
    if image.history or not history:
        return
    image.history = copy.deepcopy(history)
    db.flush()
    for item in history.get("inputs", []):
        key = item.get("source_key")
        if not key:
            continue
        source = db.query(Image).filter(Image.object_key == key, Image.user_id == image.user_id).first()
        if not db.query(ImageHistoryLink).filter_by(result_key=image.object_key, source_key=key).first():
            db.add(ImageHistoryLink(user_id=image.user_id, result_image_id=image.id,
                                    source_image_id=source.id if source else None,
                                    result_key=image.object_key, source_key=key))


def read_history(db, image):
    history = copy.deepcopy(image.history)
    if not history and image.generated_image_id:
        # Not yet backfilled: show what the generation record still holds.
        gen = db.query(GeneratedImage).filter_by(id=image.generated_image_id, user_id=image.user_id).first()
        history = snapshot(db, gen, partial=True) if gen else None
    if not history:
        return None
    history["model"]["offered"] = get_image_model(history["model"]["key"], history["job_type"]) is not None
    for lora in history.get("loras", []):
        # Match on id so a renamed LoRA isn't reported as deleted.
        query = db.query(LoraModel).filter_by(user_id=image.user_id)
        current = (query.filter_by(id=lora["id"]) if lora.get("id") else query.filter_by(name=lora["name"])).first()
        lora["deleted"] = current is None or bool(
            lora.get("created_at") and current.created_at.isoformat() != lora["created_at"])
    for item in history.get("inputs", []):
        source = db.query(Image).filter_by(user_id=image.user_id, object_key=item.get("source_key")).first() if item.get("source_key") else None
        item["image_id"] = source.id if source else None
    return history


def used_by(db, user_id, ids=None, folder_id=None):
    from app.models import FolderImage

    owned = db.query(Image.id).filter(Image.user_id == user_id)
    if folder_id is not None:
        owned = owned.join(FolderImage, FolderImage.image_id == Image.id).filter(FolderImage.folder_id == folder_id)
    else:
        owned = owned.filter(Image.id.in_(ids or []))
    links = db.query(ImageHistoryLink).filter(ImageHistoryLink.user_id == user_id, ImageHistoryLink.source_image_id.in_(owned))
    return links.with_entities(func.count(func.distinct(ImageHistoryLink.result_image_id))).scalar()


def copy_keys(history):
    return {item["copy_key"] for item in (history or {}).get("inputs", []) if item.get("copy_key")}


async def remove_unused_copies(db, storage, keys):
    # Copy keys start with their owner's id, so only that user's histories can use them.
    used = set()
    owners = {int(key.split("-", 1)[0]) for key in keys}
    for model in (Image, GeneratedImage):
        rows = db.query(model.history).filter(model.history.isnot(None), model.user_id.in_(owners))
        for (history,) in rows:
            used.update(copy_keys(history))
    for key in set(keys) - used:
        await storage.delete_file("history", key)
