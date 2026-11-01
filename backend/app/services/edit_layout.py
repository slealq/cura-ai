"""Validated normalized layouts and source-pixel precision regions."""
import io
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Box(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x_min: float = Field(ge=0, le=1, allow_inf_nan=False)
    y_min: float = Field(ge=0, le=1, allow_inf_nan=False)
    x_max: float = Field(ge=0, le=1, allow_inf_nan=False)
    y_max: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self):
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("Box must have positive width and height")
        return self


class ObjectBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    description: str = Field(min_length=1, max_length=500)
    action: Literal["Place", "Move", "Remove"]
    source_box: Box | None = None
    target_box: Box | None = None

    @model_validator(mode="after")
    def required_boxes(self):
        if not self.description.strip():
            raise ValueError("Describe the object")
        if self.action != "Place" and self.source_box is None:
            raise ValueError("Move and Remove require a source box")
        if self.action != "Remove" and self.target_box is None:
            raise ValueError("Place and Move require a target box")
        return self


def layout_payload(objects, prompt):
    boxes = []
    instructions = []
    for entry in objects:
        obj = ObjectBox.model_validate(entry)
        box = {"label": obj.label, "description": obj.description}
        if obj.action == "Place":
            box["box"] = obj.target_box.model_dump()
        else:
            box.update(source_image_index=0, source_box=obj.source_box.model_dump())
            if obj.action == "Move":
                box["target_box"] = obj.target_box.model_dump()
        boxes.append(box)
        instructions.append(f"{obj.action} <{obj.label}>: {obj.description}.")
    return boxes, prompt + "\n" + "\n".join(instructions)


def precision_box(box, base_data):
    box = Box.model_validate(box)
    with Image.open(io.BytesIO(base_data)) as image:
        width, height = image.size
    result = {"x_min": round(box.x_min * width), "x_max": round(box.x_max * width),
              "y_min": round(box.y_min * height), "y_max": round(box.y_max * height)}
    w, h = result["x_max"] - result["x_min"], result["y_max"] - result["y_min"]
    if min(w, h) < 256 or w * h > 4194304 or not 1 / 6 <= w / h <= 6:
        raise ValueError("Precision box needs sides ≥256px, area ≤4194304px and aspect between 1:6 and 6:1")
    return result
