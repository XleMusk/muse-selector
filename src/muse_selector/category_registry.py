"""Small, explicit registry for category-specific hardware attributes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class CategoryAttribute:
    """Contract for one category attribute used by search and evidence."""

    name: str
    value_type: str
    unit: str | None = None
    hard_filterable: bool = False
    evidence_required: bool = True
    normalization_rule: str = "as_observed"
    compatibility_role: str | None = None
    min_value: Decimal | None = None
    max_value: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.value_type:
            raise ValueError("category attribute name and value_type are required")
        for field_name in ("min_value", "max_value"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, Decimal(str(value)))
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError("category attribute min_value cannot exceed max_value")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("min_value", "max_value"):
            if result[key] is not None:
                result[key] = str(result[key])
        return result


@dataclass(frozen=True)
class CategorySchema:
    """Registered attributes for one product category."""

    category_id: str
    display_name: str
    attributes: tuple[CategoryAttribute, ...]

    def __post_init__(self) -> None:
        if not self.category_id or not self.display_name:
            raise ValueError("category_id and display_name are required")
        names = [attribute.name for attribute in self.attributes]
        if len(names) != len(set(names)):
            raise ValueError("category attributes must have unique names")

    def attribute(self, name: str) -> CategoryAttribute | None:
        return next((item for item in self.attributes if item.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category_id": self.category_id,
            "display_name": self.display_name,
            "attributes": [item.to_dict() for item in self.attributes],
        }


_CATEGORY_SCHEMAS: dict[str, CategorySchema] = {
    "smartphone": CategorySchema(
        "smartphone",
        "手机",
        (
            CategoryAttribute("storage_gb", "integer", "GB", True, True, "normalize_storage_gb"),
            CategoryAttribute("battery_health_pct", "number", "%", True, True, "normalize_percentage"),
            CategoryAttribute("screen_size_in", "number", "in", False, True, "normalize_decimal"),
            CategoryAttribute("model_number", "string", None, True, True, "normalize_model_number"),
        ),
    ),
    "laptop": CategorySchema(
        "laptop",
        "笔记本电脑",
        (
            CategoryAttribute("ram_gb", "integer", "GB", True, True, "normalize_storage_gb"),
            CategoryAttribute("storage_gb", "integer", "GB", True, True, "normalize_storage_gb"),
            CategoryAttribute("battery_health_pct", "number", "%", False, True, "normalize_percentage"),
            CategoryAttribute("cpu_model", "string", None, True, True, "normalize_model_number"),
            CategoryAttribute("gpu_model", "string", None, False, True, "normalize_model_number"),
        ),
    ),
    "gpu": CategorySchema(
        "gpu",
        "显卡",
        (
            CategoryAttribute("vram_gb", "integer", "GB", True, True, "normalize_storage_gb", "memory"),
            CategoryAttribute("length_mm", "number", "mm", True, True, "normalize_decimal", "size"),
            CategoryAttribute("power_w", "number", "W", True, True, "normalize_decimal", "power"),
            CategoryAttribute("interface", "string", None, True, True, "normalize_interface", "interface"),
        ),
    ),
}

_CATEGORY_ALIASES = {
    "手机": "smartphone",
    "智能手机": "smartphone",
    "iphone": "smartphone",
    "android": "smartphone",
    "笔记本": "laptop",
    "轻薄本": "laptop",
    "laptop": "laptop",
    "显卡": "gpu",
    "gpu": "gpu",
    "graphics card": "gpu",
}


def get_category_schema(category_id: str) -> CategorySchema:
    """Return a registered schema or fail clearly for an unsupported type."""

    try:
        return _CATEGORY_SCHEMAS[category_id]
    except KeyError as exc:
        raise ValueError(f"unsupported product category: {category_id}") from exc


def resolve_product_category(text: str) -> str:
    """Resolve an explicit product type without guessing from a bare budget."""

    lowered = text.lower()
    for token, category_id in sorted(_CATEGORY_ALIASES.items(), key=lambda item: -len(item[0])):
        if token in lowered:
            return category_id
    return "general_hardware"


def category_registry() -> dict[str, CategorySchema]:
    """Return a copy so callers cannot mutate the shared registry."""

    return dict(_CATEGORY_SCHEMAS)


__all__ = ["CategoryAttribute", "CategorySchema", "category_registry", "get_category_schema", "resolve_product_category"]
