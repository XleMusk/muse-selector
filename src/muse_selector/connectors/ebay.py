"""Read-only eBay Browse API connector for Hong Kong hardware discovery.

Fixture mode is the default for local development. Live calls are opt-in and
require official application credentials; the module intentionally exposes no
write operations.
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ConnectorUnavailable(RuntimeError):
    """Raised when the connector cannot run in the requested read-only mode."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so credentials never follow an untrusted Location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


@dataclass(frozen=True)
class EbayConnectorConfig:
    marketplace_id: str = "EBAY_HK"
    delivery_country: str = "HK"
    api_base: str = "https://api.ebay.com"
    token_url: str = "https://api.ebay.com/identity/v1/oauth2/token"
    timeout_seconds: float = 15.0
    default_limit: int = 20
    default_buying_option: str = "FIXED_PRICE"

    def __post_init__(self) -> None:
        if self.marketplace_id != "EBAY_HK":
            raise ValueError("MVP connector is locked to EBAY_HK")
        if self.delivery_country != "HK":
            raise ValueError("MVP connector is locked to delivery country HK")
        if self.default_buying_option != "FIXED_PRICE":
            raise ValueError("MVP connector is read-only fixed-price search")
        if not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number")
        if not isinstance(self.default_limit, int) or isinstance(self.default_limit, bool) or not 1 <= self.default_limit <= 200:
            raise ValueError("default_limit must be an integer between 1 and 200")
        for name, value in (("api_base", self.api_base), ("token_url", self.token_url)):
            parsed = urllib.parse.urlparse(value)
            try:
                port = parsed.port
            except ValueError as exc:
                raise ValueError(f"{name} must use the official https://api.ebay.com host") from exc
            if (
                parsed.scheme != "https"
                or parsed.hostname != "api.ebay.com"
                or parsed.username is not None
                or parsed.password is not None
                or port not in (None, 443)
            ):
                raise ValueError(f"{name} must use the official https://api.ebay.com host")

    @classmethod
    def from_env(cls) -> "EbayConnectorConfig":
        return cls(
            marketplace_id=os.getenv("EBAY_MARKETPLACE_ID", "EBAY_HK"),
            delivery_country=os.getenv("EBAY_DELIVERY_COUNTRY", "HK"),
            api_base=os.getenv("EBAY_API_BASE", "https://api.ebay.com").rstrip("/"),
            token_url=os.getenv("EBAY_TOKEN_URL", "https://api.ebay.com/identity/v1/oauth2/token"),
            timeout_seconds=float(os.getenv("EBAY_TIMEOUT_SECONDS", "15")),
            default_limit=int(os.getenv("EBAY_DEFAULT_LIMIT", "20")),
        )


class EbayBrowseConnector:
    """A read-only implementation of eBay ``item_summary/search``."""

    source_id = "ebay.browse.hk.v1"
    _RESPONSE_METADATA_FIELDS = ("href", "next", "prev", "total", "limit", "offset")

    def __init__(
        self,
        config: EbayConnectorConfig | None = None,
        *,
        fixture_path: str | Path | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        opener: Any | None = None,
    ) -> None:
        self.config = config or EbayConnectorConfig.from_env()
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.client_id = client_id if client_id is not None else os.getenv("EBAY_CLIENT_ID")
        self.client_secret = client_secret if client_secret is not None else os.getenv("EBAY_CLIENT_SECRET")
        # The official endpoints are fixed above. Do not let urllib follow a
        # redirect and replay Basic/Bearer headers at another host.
        self.opener = opener or urllib.request.build_opener(_NoRedirectHandler())
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._source_metadata = self._empty_source_metadata()

    @property
    def live_enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @classmethod
    def _empty_source_metadata(cls) -> dict[str, Any]:
        """Return the stable response metadata shape for unavailable fields."""

        return {field: None for field in cls._RESPONSE_METADATA_FIELDS}

    @property
    def source_metadata(self) -> dict[str, Any]:
        """Expose the last response's pagination metadata without issuing a call."""

        return dict(self._source_metadata)

    @classmethod
    def _normalize_source_metadata(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Keep Browse response pagination links and counters traceable.

        These values describe the response page that was already fetched. They
        are returned for observability only; the connector never follows the
        links or performs automatic pagination.
        """

        metadata = cls._empty_source_metadata()
        for field in ("href", "next", "prev"):
            value = payload.get(field)
            metadata[field] = value if isinstance(value, str) and value else None
        for field in ("total", "limit", "offset"):
            value = payload.get(field)
            metadata[field] = value if isinstance(value, int) and not isinstance(value, bool) else None
        return metadata

    @staticmethod
    def _fetch_timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _response_status(response: Any, context: str) -> int:
        status = getattr(response, "status", 200)
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise ConnectorUnavailable(f"eBay {context} returned an invalid HTTP status")
        return status

    def _redact_error(self, message: Any, *extra_values: Any) -> str:
        """Keep connector diagnostics useful without echoing credentials/tokens."""

        text = str(message)
        sensitive = (self.client_id, self.client_secret, self._token, *extra_values)
        for value in sensitive:
            if value is None:
                continue
            candidate = str(value)
            if candidate:
                text = text.replace(candidate, "[redacted]")
        return text

    def search(self, search_spec: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Search listings and return canonical-ish dictionaries."""
        self._source_metadata = self._empty_source_metadata()
        live = self.fixture_path is None
        payload = self._load_fixture() if not live else self._live_search(search_spec)
        fetched_at = self._fetch_timestamp() if live else None
        items = payload.get("itemSummaries", [])
        if not isinstance(items, list):
            raise ConnectorUnavailable("eBay response itemSummaries must be a list")
        if any(not isinstance(item, dict) for item in items):
            raise ConnectorUnavailable("eBay response itemSummaries must contain only JSON objects")
        listing_ids: list[str] = []
        for item in items:
            item_id = item.get("itemId")
            if item_id is not None and not isinstance(item_id, str):
                raise ConnectorUnavailable("eBay response itemSummaries itemId values must be strings")
            if item_id:
                listing_ids.append(item_id)
        if len(listing_ids) != len(set(listing_ids)):
            raise ConnectorUnavailable("eBay response itemSummaries contains duplicate itemId values")
        self._source_metadata = self._normalize_source_metadata(payload)
        listings = [
            self._normalize_item(
                item,
                fetched_at=fetched_at,
                source_metadata=self._source_metadata,
                source_rank=index,
            )
            for index, item in enumerate(items, 1)
        ]
        return self._apply_local_constraints(listings, search_spec)

    def _load_fixture(self) -> dict[str, Any]:
        if not self.fixture_path or not self.fixture_path.exists():
            raise ConnectorUnavailable(f"fixture not found: {self.fixture_path}")
        try:
            payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConnectorUnavailable(f"invalid eBay fixture: {exc}") from exc
        if not isinstance(payload, dict):
            raise ConnectorUnavailable("invalid eBay fixture: expected a JSON object")
        return payload

    def _live_search(self, search_spec: Mapping[str, Any]) -> dict[str, Any]:
        if not self.live_enabled:
            raise ConnectorUnavailable(
                "eBay live connector disabled: set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET, "
                "or pass fixture_path for offline mode"
            )
        token = self._application_token()
        params = self._query_params(search_spec)
        url = f"{self.config.api_base}/buy/browse/v1/item_summary/search?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Accept-Language": "zh-HK",
                "X-EBAY-C-MARKETPLACE-ID": self.config.marketplace_id,
                # eBay recommends contextualLocation for more accurate
                # delivery estimates; HK does not use postal codes here.
                "X-EBAY-C-ENDUSERCTX": "contextualLocation=country%3DHK",
            },
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                status = self._response_status(response, "Browse API")
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ConnectorUnavailable(self._redact_error(f"eBay Browse API HTTP {exc.code}: {detail}", token)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ConnectorUnavailable(self._redact_error(f"eBay Browse API unavailable: {exc}", token)) from exc
        if status >= 400:
            raise ConnectorUnavailable(f"eBay Browse API HTTP {status}")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectorUnavailable("eBay Browse API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ConnectorUnavailable("eBay Browse API returned a non-object JSON payload")
        return payload

    def _application_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        auth = base64.b64encode(raw).decode("ascii")
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }).encode("ascii")
        request = urllib.request.Request(
            self.config.token_url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                status = self._response_status(response, "OAuth")
                body = response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            raise ConnectorUnavailable(self._redact_error(f"eBay OAuth token request failed: {exc}")) from exc
        if status >= 400:
            raise ConnectorUnavailable(f"eBay OAuth token request failed: HTTP {status}")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectorUnavailable("eBay OAuth response was invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ConnectorUnavailable("eBay OAuth response was not a JSON object")
        token = payload.get("access_token")
        if not token:
            raise ConnectorUnavailable("eBay OAuth response did not contain access_token")
        self._token = str(token)
        try:
            expires_in = float(payload.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600.0
        if not math.isfinite(expires_in) or expires_in <= 0:
            expires_in = 3600.0
        self._token_expires_at = time.monotonic() + max(1.0, expires_in - 60.0)
        return self._token

    def _query_params(self, search_spec: Mapping[str, Any]) -> dict[str, str]:
        query = str(
            search_spec.get("query")
            or search_spec.get("keywords")
            or search_spec.get("text")
            or "computer hardware"
        ).strip()
        if not query:
            raise ValueError("SearchSpec query cannot be empty")
        limit = int(search_spec.get("limit", self.config.default_limit))
        limit = max(1, min(limit, 200))
        params: dict[str, str] = {"q": query, "limit": str(limit)}
        if search_spec.get("offset") is not None:
            params["offset"] = str(max(0, int(search_spec["offset"])))
        category_id = search_spec.get("category_id") or search_spec.get("categoryId")
        if category_id:
            params["category_ids"] = str(category_id)
        params["filter"] = ",".join([
            f"deliveryCountry:{self.config.delivery_country}",
            f"buyingOptions:{{{self.config.default_buying_option}}}",
        ])
        return params

    def _normalize_item(
        self,
        item: Mapping[str, Any],
        *,
        fetched_at: str | None = None,
        source_metadata: Mapping[str, Any] | None = None,
        source_rank: int | None = None,
    ) -> dict[str, Any]:
        price = item.get("price") if isinstance(item.get("price"), dict) else {}
        seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}
        shipping = item.get("shippingOptions")
        if not isinstance(shipping, list):
            shipping = []
        # ``itemCreationDate`` describes the listing, while ``fetched_at`` is
        # the time this connector observed the source. Result cards must use
        # the latter for live evidence freshness.
        item_created_at = item.get("itemCreationDate")
        observed_at = fetched_at or item_created_at
        specs = self._normalize_aspects(item.get("localizedAspects"))
        evidence_fields = {
            "title": item.get("title"),
            "url": item.get("itemWebUrl"),
            "price": price,
            "condition": item.get("condition"),
            "seller": seller,
            "shippingOptions": shipping,
            "specs": specs,
        }
        evidence = [
            {
                "field": field,
                "value": value,
                "source_id": self.source_id,
                "source_url": item.get("itemWebUrl"),
                "observed_at": observed_at,
                "status": "confirmed" if value not in (None, "", [], {}) else "unknown",
            }
            for field, value in evidence_fields.items()
        ]
        value = price.get("value")
        try:
            numeric_price = float(value) if value is not None else None
        except (TypeError, ValueError):
            numeric_price = None
        normalized = {
            "source_id": self.source_id,
            "listing_id": item.get("itemId"),
            "title": item.get("title"),
            "url": item.get("itemWebUrl"),
            "price": {"value": numeric_price, "currency": price.get("currency")},
            "condition": item.get("condition") or "unknown",
            "availability": item.get("estimatedAvailabilityStatus") or "unknown",
            "seller": {
                "username": seller.get("username"),
                "feedback_percentage": seller.get("feedbackPercentage"),
            },
            "shipping_options": shipping,
            "specs": specs,
            "source_observed_at": observed_at,
            "source_metadata": dict(source_metadata or self._empty_source_metadata()),
            "evidence": evidence,
            "raw": dict(item),
        }
        if source_rank is not None:
            normalized["source_rank"] = source_rank
        return normalized

    @staticmethod
    def _normalize_aspects(value: Any) -> dict[str, Any]:
        """Map explicit Browse localizedAspects into safe canonical specs."""

        if not isinstance(value, list):
            return {}
        specs: dict[str, Any] = {}
        for aspect in value:
            if not isinstance(aspect, Mapping):
                continue
            name = str(aspect.get("name") or "").strip().lower()
            raw_value = str(aspect.get("value") or "").strip()
            if not name or not raw_value:
                continue
            size_key = None
            if name in {
                "ram",
                "ram size",
                "memory",
                "memory (ram)",
                "memory size",
                "system memory",
                "installed memory",
            }:
                size_key = "ram_gb"
            elif name in {
                "ssd",
                "ssd capacity",
                "storage",
                "storage capacity",
                "total storage",
                "hard drive",
                "hard drive capacity",
                "drive capacity",
            }:
                size_key = "storage_gb"
            elif name in {
                "video memory",
                "vram",
                "graphics memory",
                "graphics memory size",
                "dedicated graphics memory",
                "dedicated video memory",
            }:
                size_key = "vram_gb"
            if size_key:
                match = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)\b", raw_value, re.I)
                if match:
                    number = float(match.group(1))
                    specs[size_key] = int(number * (1024 if match.group(2).upper() == "TB" else 1))
                continue
            if name in {"usb", "usb version", "usb type", "usb ports"} and re.search(r"\bUSB\s*4\b", raw_value, re.I):
                specs["usb4"] = True
                continue
            if name in {"power delivery", "power delivery wattage", "usb power delivery", "pd"}:
                match = re.search(r"(\d+(?:\.\d+)?)\s*W\b", raw_value, re.I)
                if match:
                    specs["pd_watt"] = int(float(match.group(1)))
                continue
            if name in {
                "maximum resolution",
                "maximum supported resolution",
                "display resolution",
                "video output",
                "video outputs",
            } and re.search(r"(?:dual|2\s*[x×*]?)\s*4K", raw_value, re.I):
                specs["display_4k_count"] = 2
        return specs

    @staticmethod
    def _apply_local_constraints(
        listings: list[dict[str, Any]], search_spec: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        budget_min = search_spec.get("budget_min")
        budget_max = search_spec.get("budget_max")
        if isinstance(search_spec.get("budget"), dict):
            budget_min = budget_min if budget_min is not None else search_spec["budget"].get("min")
            budget_max = budget_max if budget_max is not None else search_spec["budget"].get("max")
        if budget_min is None and budget_max is None:
            return listings
        try:
            min_price = float(budget_min) if budget_min is not None else None
            max_price = float(budget_max) if budget_max is not None else None
        except (TypeError, ValueError):
            return listings
        filtered: list[dict[str, Any]] = []
        for listing in listings:
            value = listing.get("price", {}).get("value")
            if value is None:
                filtered.append(listing)
                continue
            numeric_value = float(value)
            if min_price is not None and numeric_value < min_price:
                continue
            if max_price is not None and numeric_value > max_price:
                continue
            filtered.append(listing)
        return filtered

