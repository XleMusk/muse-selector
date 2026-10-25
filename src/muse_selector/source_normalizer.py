"""Pure normalization of source rows into domain listings and evidence."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from .category_registry import get_category_schema
from .contracts import (
    ALLOWED_SOURCE_IDS,
    ALLOWED_STATUSES,
    KEY_EVIDENCE_FIELDS,
    Evidence,
    Listing,
)
from .url_policy import is_allowed_market_url


_RAM_TITLE = re.compile(r"(\d+)\s*GB\s*(?:RAM|内存|(?=\s+\d+(?:GB|TB)\s*(?:NVMe|SSD)))", re.I)
_STORAGE_TITLE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|TB)\s*(?:NVMe|SSD|存储)", re.I)
_VRAM_TITLE = re.compile(r"\b(?:RTX|GTX)\s*\d+\D+(\d+)\s*GB\s*(?:VRAM|显存)\b", re.I)
_MIN_EVIDENCE_COVERAGE = 0.95


def extract_specs(title: str) -> dict[str, Any]:
    """Infer only specifications explicitly labelled in a source title."""

    specs: dict[str, Any] = {}
    ram = _RAM_TITLE.search(title)
    if ram:
        specs["ram_gb"] = int(ram.group(1))
    storage = _STORAGE_TITLE.search(title)
    if storage:
        specs["storage_gb"] = int(float(storage.group(1)) * (1024 if storage.group(2).upper() == "TB" else 1))
    vram = _VRAM_TITLE.search(title)
    if vram:
        specs["vram_gb"] = int(vram.group(1))
    if re.search(r"USB\s*4", title, re.I):
        specs["usb4"] = True
    return specs


def extract_delivery_max_days(shipping: Any, observed_at: str | None) -> int | None:
    """Derive a conservative delivery bound from dated shipping options."""

    if not isinstance(shipping, list) or not observed_at or observed_at == "unknown":
        return None
    try:
        observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    candidates: list[int] = []
    for option in shipping:
        if not isinstance(option, Mapping):
            continue
        raw_date = option.get("maxEstimatedDeliveryDate") or option.get("max_estimated_delivery_date")
        if not isinstance(raw_date, str) or not raw_date:
            continue
        try:
            delivery = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if delivery.tzinfo is None:
                delivery = delivery.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        delta_days = math.ceil((delivery - observed).total_seconds() / 86400)
        if delta_days >= 0:
            candidates.append(delta_days)
    return min(candidates) if candidates else None


def normalize_source_row(
    row: Mapping[str, Any],
    *,
    product_type: str = "general_hardware",
) -> tuple[Listing | None, list[Evidence], str | None]:
    """Validate and normalize one external row without performing I/O."""

    if not row.get("listing_id"):
        return None, [], "missing_listing_id"
    if row.get("source_id") not in ALLOWED_SOURCE_IDS:
        return None, [], "untrusted_source_id"
    if not row.get("title"):
        return None, [], "missing_title"
    url = row.get("url")
    if not url:
        return None, [], "missing_source_url"
    if not is_allowed_market_url(str(url)):
        return None, [], "untrusted_source_url"
    price = row.get("price") or {}
    if str(price.get("currency") or "HKD") != "HKD":
        return None, [], "currency_mismatch"
    shipping = row.get("shipping_options")
    shipping_values: list[Any] = []
    if isinstance(shipping, list):
        for option in shipping:
            if not isinstance(option, Mapping):
                continue
            cost = option.get("shippingCost")
            if not isinstance(cost, Mapping) or cost.get("value") is None:
                continue
            if str(cost.get("currency") or "HKD") != "HKD":
                continue
            shipping_values.append(cost["value"])
    unique_shipping_values = {str(value) for value in shipping_values}
    shipping_value = shipping_values[0] if len(unique_shipping_values) == 1 else None
    feedback = (row.get("seller") or {}).get("feedback_percentage")
    flags: list[str] = []
    try:
        if feedback is not None and float(feedback) < 90:
            flags.append("seller_feedback_low")
    except (TypeError, ValueError):
        flags.append("seller_feedback_unknown")
    if row.get("availability") == "unknown":
        flags.append("availability_unknown")
    if price.get("value") is None:
        flags.append("price_unknown")
    if not shipping_values:
        flags.append("shipping_unknown")
    elif len(unique_shipping_values) > 1:
        flags.append("shipping_ambiguous")

    evidence: list[Evidence] = []
    evidence_attribution_issue = False
    for index, item in enumerate(row.get("evidence") or []):
        if not isinstance(item, Mapping):
            continue
        source_url = item.get("source_url")
        if not source_url or not is_allowed_market_url(str(source_url)):
            continue
        evidence_source_id = str(item.get("source_id") or row.get("source_id") or "")
        if evidence_source_id != str(row.get("source_id") or "") or str(source_url) != str(url):
            evidence_attribution_issue = True
            continue
        value = item.get("value")
        status = str(item.get("status") or "unknown")
        if status not in ALLOWED_STATUSES or (status == "confirmed" and value in (None, "", [], {})):
            status = "unknown"
        evidence.append(
            Evidence(
                evidence_id=f"{row['listing_id']}:ev:{index}",
                source_id=str(item.get("source_id") or row.get("source_id")),
                source_url=str(source_url),
                field=str(item.get("field") or "unknown"),
                value=value,
                observed_at=str(item.get("observed_at") or "unknown"),
                extraction_method=str(item.get("extraction_method") or "source_json"),
                raw_field=str(item.get("raw_field") or item.get("field") or "unknown"),
                normalization_rule=str(item.get("normalization_rule") or "source_field"),
                status=status,
                confidence=1.0 if status == "confirmed" else 0.5,
            )
        )
    if any(item.status in {"stale", "conflict"} for item in evidence):
        flags.append("evidence_conflict_or_stale")
    if evidence_attribution_issue:
        flags.append("evidence_source_mismatch")
    observed_at = str(row.get("source_observed_at") or "unknown")
    delivery_max_days = extract_delivery_max_days(shipping, observed_at)
    raw_specs = row.get("specs")
    source_specs = dict(raw_specs) if isinstance(raw_specs, Mapping) else {}
    category_attributes: dict[str, Any] = {}
    try:
        registered_attributes = {item.name for item in get_category_schema(product_type).attributes}
    except ValueError:
        registered_attributes = set()
    for key in registered_attributes:
        if key in source_specs:
            category_attributes[key] = source_specs[key]
    for key, value in extract_specs(str(row.get("title") or "")).items():
        if key in registered_attributes:
            category_attributes[key] = value
    confirmed_fields = {
        item.field for item in evidence if item.status == "confirmed" and item.field in KEY_EVIDENCE_FIELDS
    }
    evidence_coverage = round(len(confirmed_fields) / len(KEY_EVIDENCE_FIELDS), 4)
    if evidence_coverage < _MIN_EVIDENCE_COVERAGE:
        flags.append("evidence_coverage_low")
    listing = Listing(
        listing_id=str(row["listing_id"]),
        source_id=str(row["source_id"]),
        title=str(row.get("title") or "unknown"),
        url=str(url),
        region="HK",
        currency=str(price.get("currency") or "HKD"),
        price=price.get("value"),
        shipping_cost=shipping_value,
        stock_status={"IN_STOCK": "in_stock", "OUT_OF_STOCK": "out_of_stock"}.get(
            str(row.get("availability")), "unknown"
        ),
        condition={"New": "new", "Used": "used", "Refurbished": "refurbished"}.get(
            str(row.get("condition")), "unknown"
        ),
        specs={
            **extract_specs(str(row.get("title") or "")),
            **source_specs,
            **({"delivery_max_days": delivery_max_days} if delivery_max_days is not None else {}),
        },
        category_attributes=category_attributes,
        product_id=str(row.get("product_id")) if row.get("product_id") not in (None, "") else None,
        evidence_ids=tuple(item.evidence_id for item in evidence),
        source_observed_at=observed_at,
        risk_flags=tuple(flags),
        evidence_coverage=evidence_coverage,
    )
    return listing, evidence, None
