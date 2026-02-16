"""Shared cover composite generation using justified row layout.

Produces Google-Photos-style mosaics where each image keeps its natural
aspect ratio.  Row heights are computed so the full canvas is filled
edge-to-edge with only thin 2 px gaps between cells.

Canvas is 800x450 (16:9) to match the frontend ``aspect-video`` class,
so ``object-cover`` in the UI becomes a no-op.
"""

import logging
import random
from io import BytesIO

from PIL import Image as PILImage

logger = logging.getLogger(__name__)

CANVAS_W = 800
CANVAS_H = 450
GAP = 2

# Row distributions keyed by image count
_ROW_LAYOUTS: dict[int, list[int]] = {
    1: [1],
    2: [2],
    3: [3],
    4: [2, 2],
    5: [3, 2],
    6: [3, 3],
}


def generate_cover_composite(pil_images: list[PILImage.Image]) -> bytes | None:
    """Build a justified-row composite JPEG from a list of PIL images.

    Returns JPEG bytes, or *None* if the list is empty.
    """
    if not pil_images:
        return None

    n = len(pil_images)

    # Single image: cover-fit to full canvas
    if n == 1:
        canvas = PILImage.new("RGB", (CANVAS_W, CANVAS_H), (24, 24, 27))
        fitted = _cover_fit(pil_images[0], CANVAS_W, CANVAS_H)
        canvas.paste(fitted, (0, 0))
        return _to_jpeg(canvas)

    # Clamp to 6
    if n > 6:
        pil_images = pil_images[:6]
        n = 6

    aspect_ratios = [max(img.width / img.height, 0.2) for img in pil_images]
    rows = _assign_rows(n)
    row_rects = _compute_row_layout(rows, aspect_ratios)

    canvas = PILImage.new("RGB", (CANVAS_W, CANVAS_H), (24, 24, 27))
    idx = 0
    for rects in row_rects:
        for x, y, w, h in rects:
            fitted = _cover_fit(pil_images[idx], w, h)
            canvas.paste(fitted, (x, y))
            idx += 1

    return _to_jpeg(canvas)


def sample_candidates(images: list, max_pool: int = 20, max_select: int = 6) -> list:
    """From *images* take up to *max_pool*, then randomly sample *max_select*."""
    pool = images[:max_pool]
    if len(pool) <= max_select:
        return pool
    return random.sample(pool, max_select)


# ── internal helpers ────────────────────────────────────────────────


def _assign_rows(n: int) -> list[int]:
    """Return the per-row image counts for *n* images (clamped 1..6)."""
    n = max(1, min(n, 6))
    return _ROW_LAYOUTS[n]


def _compute_row_layout(
    rows: list[int], aspect_ratios: list[float]
) -> list[list[tuple[int, int, int, int]]]:
    """Compute (x, y, w, h) rects for every image.

    Each row's height is proportional to 1 / (sum of aspect ratios in that row),
    then scaled so the total height fills ``CANVAS_H`` minus inter-row gaps.
    """
    num_rows = len(rows)
    total_v_gap = GAP * (num_rows - 1)

    # Step 1 – raw inverse-sum weights per row
    idx = 0
    raw_weights: list[float] = []
    for count in rows:
        row_ar_sum = sum(aspect_ratios[idx: idx + count])
        # weight ∝ 1/ar_sum  (wider rows → shorter)
        raw_weights.append(1.0 / max(row_ar_sum, 0.01))
        idx += count

    weight_total = sum(raw_weights)

    # Step 2 – distribute available height proportionally
    avail_h = CANVAS_H - total_v_gap
    row_heights: list[int] = []
    remaining_h = avail_h
    for i, w in enumerate(raw_weights):
        if i == num_rows - 1:
            h = remaining_h  # last row gets remainder
        else:
            h = round(avail_h * w / weight_total)
        row_heights.append(max(h, 1))
        remaining_h -= row_heights[-1]

    # Step 3 – lay out cells in each row
    result: list[list[tuple[int, int, int, int]]] = []
    idx = 0
    y = 0
    for ri, count in enumerate(rows):
        rh = row_heights[ri]
        h_gap_total = GAP * (count - 1)
        avail_w = CANVAS_W - h_gap_total

        row_ars = aspect_ratios[idx: idx + count]
        ar_sum = sum(row_ars)

        rects: list[tuple[int, int, int, int]] = []
        x = 0
        for ci in range(count):
            if ci == count - 1:
                cw = CANVAS_W - x  # last cell absorbs rounding
            else:
                cw = round(avail_w * row_ars[ci] / ar_sum)
            rects.append((x, y, cw, rh))
            x += cw + GAP
            idx += 1

        result.append(rects)
        y += rh + GAP

    return result


def _cover_fit(
    img: PILImage.Image, target_w: int, target_h: int
) -> PILImage.Image:
    """Scale + center-crop to fill *target_w* x *target_h* exactly (CSS cover).

    Because each cell's width is already proportional to the image's aspect
    ratio, the actual crop is negligible.
    """
    if target_w <= 0 or target_h <= 0:
        return PILImage.new("RGB", (max(target_w, 1), max(target_h, 1)), (24, 24, 27))

    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    img = img.resize((new_w, new_h), PILImage.Resampling.LANCZOS)

    # Center-crop
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _to_jpeg(canvas: PILImage.Image, quality: int = 90) -> bytes:
    buf = BytesIO()
    canvas.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
