"""Offline-first end-to-end search pipeline for the Hong Kong MVP."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .connectors.ebay import ConnectorUnavailable, EbayBrowseConnector
from .contracts import ALLOWED_STATUSES, KEY_EVIDENCE_FIELDS, Evidence, Listing
from .filtering import filter_listings
from .query_parser import PolicyBlockedError, has_explicit_unbounded_budget, parse_query
from .result_card import build_card


_RAM_TITLE = re.compile(r"(\d+)\s*GB\s*(?:RAM|内存|(?=\s+\d+(?:GB|TB)\s*(?:NVMe|SSD)))", re.I)
_STORAGE_TITLE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|TB)\s*(?:NVMe|SSD|存储)", re.I)
# Only infer VRAM when the title labels it explicitly.  A broad ``RTX ... GB``
# pattern misread system RAM (for example ``RTX 4090 64GB RAM``) as VRAM.
_VRAM_TITLE = re.compile(r"\b(?:RTX|GTX)\s*\d+\D+(\d+)\s*GB\s*(?:VRAM|显存)\b", re.I)
_ALLOWED_SOURCE_HOSTS = {"ebay.com.hk", "www.ebay.com.hk", "ebay.com", "www.ebay.com"}
_MIN_EVIDENCE_COVERAGE = 0.95


def _allowed_source_url(value: str) -> bool:
    if not isinstance(value, str) or not value or any(ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        return False
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in _ALLOWED_SOURCE_HOSTS
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
    )


def _extract_specs(title: str) -> dict[str, Any]:
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


def _extract_delivery_max_days(shipping: Any, observed_at: str | None) -> int | None:
    """Derive a conservative delivery bound from eBay's dated options."""

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


def _query_matches_title(query: str, title: str) -> bool:
    """Apply a small deterministic relevance gate before ranking.

    The first fixture is intentionally heterogeneous. A budget match alone must
    not make a dock or enclosure look like a mini PC recommendation.
    """

    q = query.lower()
    t = title.lower()
    groups = (
        (("mini pc", "迷你主机", "迷你电脑"), ("mini pc", "mini computer", "迷你", "主机")),
        (("扩展坞", "dock", "enclosure", "usb4"), ("扩展坞", "dock", "enclosure", "usb4")),
        (("显卡", "gpu", "显存", "rtx", "gtx"), ("显卡", "gpu", "显存", "rtx", "gtx")),
        (("笔记本", "轻薄本", "laptop"), ("笔记本", "轻薄本", "laptop")),
    )
    for needles, matches in groups:
        if any(needle in q for needle in needles):
            return any(match in t for match in matches)
    return True


def _fit_explanation(spec: Any, listing: Listing) -> tuple[float, dict[str, Any]]:
    """Explain fit without changing the source's mandated result ordering."""

    preferred = dict(spec.preferred_specs or {})
    matched = 0
    for key, expected in preferred.items():
        actual = listing.specs.get(key)
        if actual is not None and str(actual).strip().lower() == str(expected).strip().lower():
            matched += 1
    preferred_ratio = matched / len(preferred) if preferred else 1.0
    availability = {"in_stock": 1.0, "preorder": 0.5}.get(listing.stock_status, 0.0)
    score = round((preferred_ratio * 0.4 + listing.evidence_coverage * 0.4 + availability * 0.2) * 100, 2)
    return score, {
        "preferred_specs": f"{matched}/{len(preferred)}" if preferred else "not specified",
        "evidence_coverage": listing.evidence_coverage,
        "availability": listing.stock_status,
        "policy": "source_order_preserved",
    }


def _to_listing(row: dict[str, Any]) -> tuple[Listing | None, list[Evidence], str | None]:
    if not row.get("listing_id"):
        return None, [], "missing_listing_id"
    if not row.get("title"):
        return None, [], "missing_title"
    url = row.get("url")
    if not url:
        return None, [], "missing_source_url"
    if not _allowed_source_url(str(url)):
        return None, [], "untrusted_source_url"
    price = row.get("price") or {}
    if str(price.get("currency") or "HKD") != "HKD":
        return None, [], "currency_mismatch"
    shipping = row.get("shipping_options")
    shipping_values: list[Any] = []
    if isinstance(shipping, list):
        for option in shipping:
            if not isinstance(option, dict):
                continue
            cost = option.get("shippingCost")
            if not isinstance(cost, dict) or cost.get("value") is None:
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
    for index, item in enumerate(row.get("evidence") or []):
        if not item.get("source_url") or not _allowed_source_url(str(item["source_url"])):
            continue
        value = item.get("value")
        status = str(item.get("status") or "unknown")
        if status not in ALLOWED_STATUSES or (status == "confirmed" and value in (None, "", [], {})):
            status = "unknown"
        evidence.append(Evidence(
            evidence_id=f"{row['listing_id']}:ev:{index}",
            source_id=str(item.get("source_id") or row.get("source_id")),
            source_url=str(item["source_url"]),
            field=str(item.get("field") or "unknown"),
            value=value,
            observed_at=str(item.get("observed_at") or "unknown"),
            status=status,
            confidence=1.0 if status == "confirmed" else 0.5,
        ))
    if any(item.status in {"stale", "conflict"} for item in evidence):
        flags.append("evidence_conflict_or_stale")
    observed_at = str(row.get("source_observed_at") or "unknown")
    delivery_max_days = _extract_delivery_max_days(shipping, observed_at)
    confirmed_fields = {item.field for item in evidence if item.status == "confirmed" and item.field in KEY_EVIDENCE_FIELDS}
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
        stock_status={"IN_STOCK": "in_stock", "OUT_OF_STOCK": "out_of_stock"}.get(str(row.get("availability")), "unknown"),
        condition={"New": "new", "Used": "used", "Refurbished": "refurbished"}.get(str(row.get("condition")), "unknown"),
        specs={
            **_extract_specs(str(row.get("title") or "")),
            **(dict(row.get("specs")) if isinstance(row.get("specs"), Mapping) else {}),
            **({"delivery_max_days": delivery_max_days} if delivery_max_days is not None else {}),
        },
        evidence_ids=tuple(item.evidence_id for item in evidence),
        source_observed_at=observed_at,
        risk_flags=tuple(flags),
        evidence_coverage=evidence_coverage,
    )
    return listing, evidence, None


def run_search(query: str, fixture_path: str | Path | None = None, *, limit: int = 10) -> dict[str, Any]:
    """Run a fully offline search and return serializable result cards."""

    try:
        spec = parse_query(query)
    except PolicyBlockedError as exc:
        return {
            "ok": False,
            "status": "policy_blocked",
            "message": str(exc),
            "search_spec": None,
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "policy.guard",
            "read_only": True,
        }
    except ValueError as exc:
        return {
            "ok": False,
            "status": "invalid_query",
            "message": str(exc),
            "search_spec": None,
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "policy.guard",
            "read_only": True,
        }
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        return {
            "ok": False,
            "status": "invalid_query",
            "message": "limit must be a positive integer",
            "search_spec": spec.to_dict(),
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "policy.guard",
            "read_only": True,
        }
    limit = min(limit, 200)
    if spec.budget_max is None and not has_explicit_unbounded_budget(query):
        return {
            "ok": False,
            "status": "needs_clarification",
            "message": "请补充配送地区和 HKD 预算上限；如无预算限制，请明确写“价格不限”。",
            "ask": ["location", "max_total_hkd"],
            "search_spec": spec.to_dict(),
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "policy.guard",
            "read_only": True,
        }
    try:
        connector = EbayBrowseConnector(fixture_path=fixture_path)
        connector_spec = spec.to_dict()
        # Keep the source request bounded by the caller's result limit.  The
        # pipeline still preserves source order and applies the final limit
        # after hard filtering, but never fetches an unbounded default page.
        connector_spec["limit"] = limit
        rows = connector.search(connector_spec)
    except (ConnectorUnavailable, ValueError) as exc:
        source_metadata = connector.source_metadata if "connector" in locals() else None
        return {
            "ok": False,
            "status": "source_unavailable",
            "message": str(exc),
            "search_spec": spec.to_dict(),
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "ebay.browse.hk.v1",
            "source_metadata": source_metadata,
            "read_only": True,
        }
    source_metadata = connector.source_metadata
    listings: list[Listing] = []
    evidence_by_id: dict[str, list[Evidence]] = {}
    source_rank_by_id: dict[str, int] = {}
    dropped: list[dict[str, str]] = []
    for source_rank, row in enumerate(rows, 1):
        listing, evidence, reason = _to_listing(row)
        if reason or listing is None:
            dropped.append({"listing_id": str(row.get("listing_id", "unknown")), "reason": reason or "invalid_source_record"})
            continue
        if not _query_matches_title(spec.query, listing.title):
            listing = Listing(
                listing_id=listing.listing_id,
                source_id=listing.source_id,
                title=listing.title,
                url=listing.url,
                region=listing.region,
                currency=listing.currency,
                price=listing.price,
                shipping_cost=listing.shipping_cost,
                tax=listing.tax,
                stock_status=listing.stock_status,
                condition=listing.condition,
                specs=listing.specs,
                product_id=listing.product_id,
                evidence_ids=listing.evidence_ids,
                source_observed_at=listing.source_observed_at,
                risk_flags=tuple((*listing.risk_flags, "query_mismatch")),
                evidence_coverage=listing.evidence_coverage,
            )
        listings.append(listing)
        evidence_by_id[listing.listing_id] = evidence
        item_rank = row.get("source_rank")
        source_rank_by_id[listing.listing_id] = (
            item_rank
            if isinstance(item_rank, int) and not isinstance(item_rank, bool) and item_rank > 0
            else source_rank
        )
    accepted, decisions = filter_listings(spec, listings)
    # eBay's Buy API requirements prohibit partner-side re-sorting. Preserve
    # the source's best-match order and expose an explainable fit score instead.
    accepted = accepted[:limit]
    accepted_ids = {item.listing_id for item in accepted}
    decision_by_id = {item.listing_id: item for item in decisions}
    recommended_cards = []
    for index, item in enumerate(accepted, 1):
        fit_score, fit_breakdown = _fit_explanation(spec, item)
        recommended_cards.append(
            build_card(
                item,
                evidence_by_id[item.listing_id],
                source_rank=source_rank_by_id[item.listing_id],
                fit_score=fit_score,
                fit_breakdown=fit_breakdown,
            ).to_dict()
        )
    rejected = [
        {"listing_id": item.listing_id, "reasons": list(decision_by_id[item.listing_id].reasons)}
        for item in listings
        if item.listing_id not in accepted_ids
    ]
    return {
        "ok": True,
        "status": "complete",
        "search_spec": spec.to_dict(),
        "recommended": recommended_cards,
        "ranking_policy": "source_order_preserved",
        "rejected": rejected,
        "dropped": dropped,
        "source": "ebay.browse.hk.v1",
        "source_metadata": source_metadata,
        "read_only": True,
    }

