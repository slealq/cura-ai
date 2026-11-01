"""Canonical paint masks: opaque PNG, white edits, black preserves."""
import base64
import io

from PIL import Image, ImageOps

ORIENTATION = 0x0112
PAINT_MODELS = {"gpt-image-2-edit", "gpt-image-2.5-flare-edit", "gpt-image-2.5-sunburst-edit", "ideogram-v4.5-edit"}


def upright_base(data: bytes) -> bytes:
    """Bake EXIF rotation into the base so it matches the mask painted in the browser."""
    with Image.open(io.BytesIO(data)) as image:
        if image.getexif().get(ORIENTATION, 1) == 1:
            return data
        output = io.BytesIO()
        ImageOps.exif_transpose(image).convert("RGB").save(output, format="PNG")
        return output.getvalue()


def prepare_mask(data: bytes, base_data: bytes, model: str, source_count: int) -> bytes:
    if model not in PAINT_MODELS:
        raise ValueError("This model does not support paint masks")
    with Image.open(io.BytesIO(data)) as mask, Image.open(io.BytesIO(base_data)) as base:
        if mask.format != "PNG" or mask.size != base.size:
            raise ValueError("Mask must be a PNG matching the base image dimensions")
        if "A" in mask.getbands() and mask.getchannel("A").getextrema() != (255, 255):
            raise ValueError("Mask must be opaque")
        selected = mask.convert("L").point(lambda value: 255 if value >= 128 else 0)
        low, high = selected.getextrema()
        if high == 0:
            raise ValueError("Paint an area before applying")
        if model == "ideogram-v4.5-edit":
            if source_count > 4:
                raise ValueError("Ideogram paint accepts one base plus three references")
            if low == 255:
                raise ValueError("Leave part of the base unpainted for Ideogram")
        output = io.BytesIO()
        selected.save(output, format="PNG")
        return output.getvalue()


def provider_mask_url(url: str, model: str) -> str:
    """The worker supplies validated canonical PNG data, never a remote URL."""
    if model not in PAINT_MODELS:
        raise ValueError("This model does not support paint masks")
    if not url.startswith("data:image/png;base64,"):
        raise ValueError("Mask must be resolved before building the provider request")
    if model != "ideogram-v4.5-edit":
        return url
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        output = io.BytesIO()
        ImageOps.invert(image.convert("L")).save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
