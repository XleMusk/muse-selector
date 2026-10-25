"""Versioned, dependency-free data contracts.

The contracts are intentionally strict about source evidence and unknown values:
an absent field remains ``None``/``unknown`` instead of being guessed by a model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import math
from typing import Any, Mapping

from .url_policy import is_absolute_http_url


# Nested domain objects retain the historical numeric version.  Result and
# HTTP payloads use a namespaced contract identifier so consumers can route
# envelopes without guessing which object schema they received.
SCHEMA_VERSION = "1.0"
RESULT_SCHEMA_VERSION = "muse.selector.v1"
ZHUANZHUAN_SMOKE_SCHEMA_VERSION = "muse.zhuanzhuan.smoke.v1"
ALLOWED_STATUSES = {"confirmed", "unknown", "conflict", "stale"}
ALLOWED_STOCK = {"in_stock", "out_of_stock", "preorder", "unknown"}
ALLOWED_CONDITION = {"new", "used", "refurbished", "unknown"}
KEY_EVIDENCE_FIELDS = ("title", "url", "price", "condition", "seller", "shippingOptions")
ALLOWED_REGIONS = {"HK", "CN"}
REGION_CURRENCY = {"HK": "HKD", "CN": "CNY"}
DOMESTIC_SOURCE_IDS = {"zhuanzhuan.recommerce.mcp.v1", "xianyu.partner.v1"}
ALLOWED_SOURCE_IDS = {"ebay.browse.hk.v1", *DOMESTIC_SOURCE_IDS}
SOURCE_ACCESS_MODES = {"official_api", "authorized_partner", "user_link", "local_fixture"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _http_url(value: str, name: str = "url") -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    if not is_absolute_http_url(value):
        raise ValueError(f"{name} must be an absolute http(s) URL")
    return value


def _decimal(value: Any, name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a decimal number") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return amount.quantize(Decimal("0.01"))


def _status(value: str | None, name: str = "status") -> str:
    value = value or "unknown"
    if value not in ALLOWED_STATUSES:
        raise ValueError(f"{name} must be one of {sorted(ALLOWED_STATUSES)}")
    return value


def _copy_map(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("expected an object/map")
    return dict(value)


@dataclass(frozen=True)
class SearchSpec:
    """Normalized user intent for a read-only market product search."""

    query: str
    category: str = "computers_hardware"
    region: str = "HK"
    currency: str = "HKD"
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    required_specs: Mapping[str, Any] = dataclass_field(default_factory=dict)
    preferred_specs: Mapping[str, Any] = dataclass_field(default_factory=dict)
    condition: str = "new"
    stock_required: bool = True
    max_delivery_days: int | None = None
    sources: tuple[str, ...] = ()
    risk_tolerance: str = "standard"
    allow_account_listings: bool = False
    product_type: str = "general_hardware"
    parse_confidence: float = 1.0
    unparsed_fragments: tuple[str, ...] = ()
    clarification_fields: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must be non-empty")
        if self.category != "computers_hardware":
            raise ValueError("MVP category must be computers_hardware")
        if self.region not in ALLOWED_REGIONS:
            raise ValueError(f"region must be one of {sorted(ALLOWED_REGIONS)}")
        if self.currency != REGION_CURRENCY[self.region]:
            raise ValueError(f"currency must be {REGION_CURRENCY[self.region]} for region {self.region}")
        if self.condition not in ALLOWED_CONDITION:
            raise ValueError(f"condition must be one of {sorted(ALLOWED_CONDITION)}")
        parse_confidence = float(self.parse_confidence)
        if not math.isfinite(parse_confidence) or not 0 <= parse_confidence <= 1:
            raise ValueError("parse_confidence must be a finite value between 0 and 1")
        object.__setattr__(self, "parse_confidence", round(parse_confidence, 4))
        min_value = _decimal(self.budget_min, "budget_min")
        max_value = _decimal(self.budget_max, "budget_max")
        object.__setattr__(self, "budget_min", min_value)
        object.__setattr__(self, "budget_max", max_value)
        if min_value is not None and max_value is not None and min_value > max_value:
            raise ValueError("budget_min cannot exceed budget_max")
        if self.max_delivery_days is not None and (
            not isinstance(self.max_delivery_days, int) or self.max_delivery_days < 0
        ):
            raise ValueError("max_delivery_days must be a non-negative integer")
        object.__setattr__(self, "required_specs", _copy_map(self.required_specs))
        object.__setattr__(self, "preferred_specs", _copy_map(self.preferred_specs))
        object.__setattr__(self, "sources", tuple(self.sources or ()))
        object.__setattr__(self, "unparsed_fragments", tuple(str(item) for item in self.unparsed_fragments or ()))
        object.__setattr__(self, "clarification_fields", tuple(str(item) for item in self.clarification_fields or ()))
        unsupported_sources = sorted({str(source) for source in self.sources if not isinstance(source, str) or source not in ALLOWED_SOURCE_IDS})
        if unsupported_sources:
            raise ValueError(f"unsupported source(s): {unsupported_sources}")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchSpec":
        if not isinstance(data, Mapping):
            raise ValueError("SearchSpec input must be an object")
        return cls(**dict(data))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("budget_min", "budget_max"):
            if result[key] is not None:
                result[key] = str(result[key])
        for key in ("sources", "unparsed_fragments", "clarification_fields"):
            result[key] = list(result[key])
        return result


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_id: str
    source_url: str
    field: str
    value: Any
    observed_at: str = dataclass_field(default_factory=_now_iso)
    quote: str | None = None
    extraction_method: str = "source_json"
    raw_field: str | None = None
    normalization_rule: str | None = None
    status: str = "confirmed"
    confidence: float = 1.0
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.source_id or not self.field:
            raise ValueError("evidence_id, source_id and field are required")
        _http_url(self.source_url, "source_url")
        _status(self.status)
        if not 0 <= float(self.confidence) <= 1:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductModel:
    """Identity and stable specifications shared by listing instances."""

    product_model_id: str
    category: str
    brand: str | None = None
    model: str | None = None
    mpn: str | None = None
    gtin: str | None = None
    official_attributes: Mapping[str, Any] = dataclass_field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.product_model_id or not self.category:
            raise ValueError("product_model_id and category are required")
        object.__setattr__(self, "official_attributes", _copy_map(self.official_attributes))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids or ()))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence_ids"] = list(result["evidence_ids"])
        return result


@dataclass(frozen=True)
class Product:
    """Backward-compatible product identity contract.

    New code should use :class:`ProductModel`; this name remains stable for
    saved v1 payloads and existing callers.
    """

    product_id: str
    brand: str | None = None
    model: str | None = None
    mpn: str | None = None
    gtin: str | None = None
    attributes: Mapping[str, Any] = dataclass_field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.product_id:
            raise ValueError("product_id is required")
        object.__setattr__(self, "attributes", _copy_map(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Listing:
    listing_id: str
    source_id: str
    title: str
    url: str
    region: str = "HK"
    currency: str = "HKD"
    price: Decimal | None = None
    shipping_cost: Decimal | None = None
    tax: Decimal | None = None
    stock_status: str = "unknown"
    condition: str = "unknown"
    specs: Mapping[str, Any] = dataclass_field(default_factory=dict)
    category_attributes: Mapping[str, Any] = dataclass_field(default_factory=dict)
    product_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    source_observed_at: str = dataclass_field(default_factory=_now_iso)
    risk_flags: tuple[str, ...] = ()
    evidence_coverage: float = 0.0
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.listing_id or not self.source_id or not self.title:
            raise ValueError("listing_id, source_id and title are required")
        _http_url(self.url)
        if self.region not in ALLOWED_REGIONS:
            raise ValueError(f"listing region must be one of {sorted(ALLOWED_REGIONS)}")
        if self.currency != REGION_CURRENCY[self.region]:
            raise ValueError(f"listing currency must be {REGION_CURRENCY[self.region]} for region {self.region}")
        if self.stock_status not in ALLOWED_STOCK:
            raise ValueError(f"stock_status must be one of {sorted(ALLOWED_STOCK)}")
        if self.condition not in ALLOWED_CONDITION:
            raise ValueError(f"condition must be one of {sorted(ALLOWED_CONDITION)}")
        for key in ("price", "shipping_cost", "tax"):
            object.__setattr__(self, key, _decimal(getattr(self, key), key))
        object.__setattr__(self, "specs", _copy_map(self.specs))
        object.__setattr__(self, "category_attributes", _copy_map(self.category_attributes))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids or ()))
        object.__setattr__(self, "risk_flags", tuple(self.risk_flags or ()))
        coverage = float(self.evidence_coverage)
        if not math.isfinite(coverage) or not 0 <= coverage <= 1:
            raise ValueError("evidence_coverage must be a finite value between 0 and 1")
        object.__setattr__(self, "evidence_coverage", round(coverage, 4))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Listing":
        """Build a normalized listing from either v1 or the fixture/API shape."""
        if not isinstance(data, Mapping):
            raise ValueError("Listing input must be an object")
        raw = dict(data)
        price = raw.get("price")
        if isinstance(price, Mapping):
            has_total = price.get("total") is not None
            amount = price.get("total", price.get("amount"))
            # Fixture/API totals are already landed totals. Avoid adding
            # shipping/tax a second time when computing Listing.landed_cost.
            shipping = 0 if has_total else price.get("shipping")
            tax = 0 if has_total else price.get("tax")
            currency = price.get("currency", raw.get("currency", "HKD"))
        else:
            amount = price
            shipping = raw.get("shipping_cost")
            tax = raw.get("tax")
            currency = raw.get("currency", "HKD")
        source_raw = raw.get("source")
        source: Mapping[str, Any] = source_raw if isinstance(source_raw, Mapping) else {}
        source_id = raw.get("source_id", source.get("source_id", "unknown_source"))
        url = raw.get("url", source.get("url"))
        observed = raw.get("source_observed_at", source.get("observed_at", _now_iso()))
        stock = raw.get("stock_status", raw.get("availability", "unknown"))
        stock_map = {"IN_STOCK": "in_stock", "OUT_OF_STOCK": "out_of_stock", "PREORDER": "preorder", "UNKNOWN": "unknown"}
        condition = raw.get("condition", "unknown")
        condition_map = {"NEW": "new", "USED": "used", "REFURBISHED": "refurbished", "UNKNOWN": "unknown"}
        risk = str(raw.get("risk", "")).upper()
        flags = list(raw.get("risk_flags", ()))
        if risk in {"HIGH", "MEDIUM", "BLOCKED"}:
            flags.append(f"risk:{risk.lower()}")
        field_status_raw = raw.get("field_status", {})
        field_status = field_status_raw if isinstance(field_status_raw, Mapping) else {}
        if any(str(v).lower() in {"stale", "conflict"} for v in field_status.values()):
            flags.append("evidence_conflict_or_stale")
        evidence_ids = []
        raw_evidence = raw.get("evidence", ()) or ()
        confirmed_fields = set()
        for index, ev in enumerate(raw_evidence):
            if isinstance(ev, Mapping):
                evidence_ids.append(str(ev.get("evidence_id", f"{raw.get('listing_id', 'listing')}:ev:{index}")))
                if ev.get("field") in KEY_EVIDENCE_FIELDS and ev.get("status") == "confirmed":
                    confirmed_fields.add(ev.get("field"))
        coverage = raw.get("evidence_coverage")
        if coverage is None:
            coverage = len(confirmed_fields) / len(KEY_EVIDENCE_FIELDS)
        shipping_value = _decimal(shipping, "shipping_cost")
        tax_value = _decimal(tax, "tax")
        return cls(
            listing_id=str(raw.get("listing_id", "")),
            source_id=str(source_id),
            title=str(raw.get("title", "")),
            url=_http_url(str(url)),
            region=str(raw.get("region", "HK")),
            currency=str(currency),
            price=amount,
            shipping_cost=shipping_value,
            tax=tax_value,
            stock_status=stock_map.get(str(stock).upper(), str(stock).lower()),
            condition=condition_map.get(str(condition).upper(), str(condition).lower()),
            specs=_copy_map(raw.get("specs")),
            category_attributes=_copy_map(raw.get("category_attributes")),
            product_id=raw.get("product_id"),
            evidence_ids=tuple(evidence_ids or raw.get("evidence_ids", ())),
            source_observed_at=str(observed),
            risk_flags=tuple(dict.fromkeys(flags)),
            evidence_coverage=coverage,
        )

    @property
    def landed_cost(self) -> Decimal | None:
        """Return the computable subtotal; inspect ``cost_status`` before labeling it landed."""
        if self.price is None:
            return None
        return (self.price + (self.shipping_cost or Decimal("0")) + (self.tax or Decimal("0"))).quantize(Decimal("0.01"))

    @property
    def cost_status(self) -> str:
        """Describe whether the displayed subtotal includes all cost components."""
        if self.price is None:
            return "unknown"
        return "complete" if self.shipping_cost is not None and self.tax is not None else "partial"

    @property
    def cost_basis(self) -> str:
        """Identify which explicit components contribute to ``landed_cost``."""
        if self.price is None:
            return "unknown"
        components = ["item_price"]
        if self.shipping_cost is not None:
            components.append("shipping")
        if self.tax is not None:
            components.append("tax")
        return "_plus_".join(components)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("price", "shipping_cost", "tax"):
            result[key] = str(result[key]) if result[key] is not None else None
        result["landed_cost"] = str(self.landed_cost) if self.landed_cost is not None else None
        result["cost_status"] = self.cost_status
        result["cost_basis"] = self.cost_basis
        result["evidence_coverage"] = self.evidence_coverage
        result["evidence_ids"] = list(result["evidence_ids"])
        result["risk_flags"] = list(result["risk_flags"])
        result["category_attributes"] = dict(result["category_attributes"])
        return result


@dataclass(frozen=True)
class ListingInstance:
    """A concrete source listing linked to an optional product model."""

    listing: Listing
    product_model_id: str | None = None
    category_attributes: Mapping[str, Any] = dataclass_field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.listing, Listing):
            raise ValueError("listing must be a Listing instance")
        object.__setattr__(self, "category_attributes", _copy_map(self.category_attributes))

    @classmethod
    def from_listing(
        cls,
        listing: Listing,
        *,
        product_model_id: str | None = None,
        category_attributes: Mapping[str, Any] | None = None,
    ) -> "ListingInstance":
        return cls(
            listing,
            product_model_id=product_model_id or listing.product_id,
            category_attributes=category_attributes or listing.category_attributes or listing.specs,
        )

    def to_dict(self) -> dict[str, Any]:
        result = self.listing.to_dict()
        result["product_model_id"] = self.product_model_id
        result["category_attributes"] = dict(self.category_attributes)
        result["listing_instance_schema_version"] = self.schema_version
        return result


@dataclass(frozen=True)
class PolicyRecord:
    source_id: str
    category: str
    access_mode: str
    authorization_evidence_url: str
    allowed_regions: tuple[str, ...] = ("HK",)
    allowed_fields: tuple[str, ...] = ()
    default_policy: str = "allow_read_only"
    write_actions: tuple[str, ...] = ()
    reviewed_at: str = dataclass_field(default_factory=_now_iso)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_id or not self.category:
            raise ValueError("source_id and category are required")
        if self.access_mode not in {"official_api", "licensed_feed", "user_authorized", "link_only"}:
            raise ValueError("unsupported access_mode")
        _http_url(self.authorization_evidence_url, "authorization_evidence_url")
        object.__setattr__(self, "allowed_regions", tuple(self.allowed_regions or ()))
        object.__setattr__(self, "allowed_fields", tuple(self.allowed_fields or ()))
        object.__setattr__(self, "write_actions", tuple(self.write_actions or ()))
        if self.default_policy != "allow_read_only":
            raise ValueError("MVP policy must be allow_read_only")
        if self.write_actions:
            raise ValueError("read-only MVP cannot register write_actions")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("allowed_regions", "allowed_fields", "write_actions"):
            result[key] = list(result[key])
        return result


@dataclass(frozen=True)
class SourceCapability:
    """Declared read-only capability and status of one external source."""

    source_id: str
    display_name: str
    category: str
    access_mode: str
    read_only: bool = True
    listing_search: bool = False
    status: str = "unavailable"
    allowed_regions: tuple[str, ...] = ()
    allowed_fields: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    write_actions: tuple[str, ...] = ()
    authorization_evidence_url: str | None = None
    retention_days: int | None = None
    cache_ttl_minutes: int | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_id or not self.display_name or not self.category:
            raise ValueError("source_id, display_name and category are required")
        if self.access_mode not in SOURCE_ACCESS_MODES:
            raise ValueError(f"access_mode must be one of {sorted(SOURCE_ACCESS_MODES)}")
        if not self.read_only or self.write_actions:
            raise ValueError("MVP source capabilities must be read-only")
        if self.authorization_evidence_url is not None:
            _http_url(self.authorization_evidence_url, "authorization_evidence_url")
        object.__setattr__(self, "allowed_regions", tuple(self.allowed_regions or ()))
        object.__setattr__(self, "allowed_fields", tuple(self.allowed_fields or ()))
        object.__setattr__(self, "capabilities", tuple(self.capabilities or ()))
        object.__setattr__(self, "write_actions", tuple(self.write_actions or ()))
        for name in ("retention_days", "cache_ttl_minutes"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("allowed_regions", "allowed_fields", "capabilities", "write_actions"):
            result[key] = list(result[key])
        return result
