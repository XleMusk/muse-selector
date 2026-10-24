"""Versioned, dependency-free data contracts.

The contracts are intentionally strict about source evidence and unknown values:
an absent field remains ``None``/``unknown`` instead of being guessed by a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import urlparse


SCHEMA_VERSION = "1.0"
ALLOWED_STATUSES = {"confirmed", "unknown", "conflict", "stale"}
ALLOWED_STOCK = {"in_stock", "out_of_stock", "preorder", "unknown"}
ALLOWED_CONDITION = {"new", "used", "refurbished", "unknown"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _http_url(value: str, name: str = "url") -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
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
    """Normalized user intent for a read-only Hong Kong product search."""

    query: str
    category: str = "computers_hardware"
    region: str = "HK"
    currency: str = "HKD"
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    required_specs: Mapping[str, Any] = field(default_factory=dict)
    preferred_specs: Mapping[str, Any] = field(default_factory=dict)
    condition: str = "new"
    stock_required: bool = True
    max_delivery_days: int | None = None
    sources: tuple[str, ...] = ()
    risk_tolerance: str = "standard"
    allow_account_listings: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must be non-empty")
        if self.category != "computers_hardware":
            raise ValueError("MVP category must be computers_hardware")
        if self.region != "HK":
            raise ValueError("MVP region must be HK")
        if self.currency != "HKD":
            raise ValueError("MVP currency must be HKD")
        if self.condition not in ALLOWED_CONDITION:
            raise ValueError(f"condition must be one of {sorted(ALLOWED_CONDITION)}")
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
        result["sources"] = list(result["sources"])
        return result


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_id: str
    source_url: str
    field: str
    value: Any
    observed_at: str = field(default_factory=_now_iso)
    quote: str | None = None
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
class Product:
    product_id: str
    brand: str | None = None
    model: str | None = None
    mpn: str | None = None
    gtin: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
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
    specs: Mapping[str, Any] = field(default_factory=dict)
    product_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    source_observed_at: str = field(default_factory=_now_iso)
    risk_flags: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.listing_id or not self.source_id or not self.title:
            raise ValueError("listing_id, source_id and title are required")
        _http_url(self.url)
        if self.region != "HK":
            raise ValueError("MVP listing region must be HK")
        if self.currency != "HKD":
            raise ValueError("MVP listing currency must be HKD")
        if self.stock_status not in ALLOWED_STOCK:
            raise ValueError(f"stock_status must be one of {sorted(ALLOWED_STOCK)}")
        if self.condition not in ALLOWED_CONDITION:
            raise ValueError(f"condition must be one of {sorted(ALLOWED_CONDITION)}")
        for key in ("price", "shipping_cost", "tax"):
            object.__setattr__(self, key, _decimal(getattr(self, key), key))
        object.__setattr__(self, "specs", _copy_map(self.specs))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids or ()))
        object.__setattr__(self, "risk_flags", tuple(self.risk_flags or ()))

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
        source = raw.get("source") if isinstance(raw.get("source"), Mapping) else {}
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
        field_status = raw.get("field_status", {})
        if any(str(v).lower() in {"stale", "conflict"} for v in field_status.values()):
            flags.append("evidence_conflict_or_stale")
        evidence_ids = []
        for index, ev in enumerate(raw.get("evidence", ()) or ()):
            if isinstance(ev, Mapping):
                evidence_ids.append(str(ev.get("evidence_id", f"{raw.get('listing_id', 'listing')}:ev:{index}")))
        return cls(
            listing_id=str(raw.get("listing_id", "")),
            source_id=str(source_id),
            title=str(raw.get("title", "")),
            url=_http_url(str(url)),
            region=str(raw.get("region", "HK")),
            currency=str(currency),
            price=amount,
            shipping_cost=shipping,
            tax=tax,
            stock_status=stock_map.get(str(stock).upper(), str(stock).lower()),
            condition=condition_map.get(str(condition).upper(), str(condition).lower()),
            specs=_copy_map(raw.get("specs")),
            product_id=raw.get("product_id"),
            evidence_ids=tuple(evidence_ids or raw.get("evidence_ids", ())),
            source_observed_at=str(observed),
            risk_flags=tuple(dict.fromkeys(flags)),
        )

    @property
    def landed_cost(self) -> Decimal | None:
        if self.price is None:
            return None
        return (self.price + (self.shipping_cost or Decimal("0")) + (self.tax or Decimal("0"))).quantize(Decimal("0.01"))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("price", "shipping_cost", "tax"):
            result[key] = str(result[key]) if result[key] is not None else None
        result["landed_cost"] = str(self.landed_cost) if self.landed_cost is not None else None
        result["evidence_ids"] = list(result["evidence_ids"])
        result["risk_flags"] = list(result["risk_flags"])
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
    reviewed_at: str = field(default_factory=_now_iso)
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
