"""Kling subject roles shared by validation, provider payloads and history."""
import io

from PIL import Image, ImageOps


def subject_inputs(sources, urls):
    references = []
    elements = {}
    for source, url in zip(sources, urls, strict=True):
        role = source.get("role", "reference")
        number = source.get("element")
        if role == "reference":
            if number is not None:
                raise ValueError("Composition references cannot belong to an element")
            references.append(url)
            continue
        if role not in ("element_main", "element_angle") or not isinstance(number, int) or number < 1:
            raise ValueError("Identity photos require an element number and main or angle role")
        element = elements.setdefault(number, {"frontal_image_url": None, "reference_image_urls": []})
        if role == "element_main":
            if element["frontal_image_url"]:
                raise ValueError("Each element needs exactly one main photo")
            element["frontal_image_url"] = url
        else:
            element["reference_image_urls"].append(url)
    if len(references) > 10:
        raise ValueError("Kling accepts up to 10 composition references")
    if sorted(elements) != list(range(1, len(elements) + 1)):
        raise ValueError("Element numbers must be consecutive starting at 1")
    for element in elements.values():
        if not element["frontal_image_url"] or len(element["reference_image_urls"]) > 3:
            raise ValueError("Each element needs a main photo and up to 3 alternate angles")
    ordered = [elements[number] for number in sorted(elements)]
    # Kling rejects an element with no reference images, though its schema marks them optional.
    for element in ordered:
        element["reference_image_urls"] = element["reference_image_urls"] or [element["frontal_image_url"]]
    # Kling requires at least one image_urls entry, even when only elements are used.
    return references or [ordered[0]["frontal_image_url"]] if ordered else references, ordered


def validate_subject_media(data):
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("Kling images must be at most 10 MiB")
    with Image.open(io.BytesIO(data)) as image:
        width, height = ImageOps.exif_transpose(image).size
    if min(width, height) < 300 or not 0.4 <= width / height <= 2.5:
        raise ValueError("Kling images need sides of at least 300px and aspect ratio 0.4–2.5")
