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
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Mapping


class ConnectorUnavailable(RuntimeError):
    """Raised when the connector cannot run in the requested read-only mode."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so credentials never follow an untrusted Location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OFFICIAL_API_HOSTS = frozenset({"api.ebay.com", "api.sandbox.ebay.com"})
_BROWSE_SEARCH_PATH = "/buy/browse/v1/item_summary/search"
_SENSITIVE_QUERY_KEYS = frozenset({
    "access_token",
    "authorization",
    "client_id",
    "client_secret",
    "id_token",
    "refresh_token",
    "secret",
    "token",
})


def credential_env_names(environment: str) -> tuple[str, str]:
    """Return environment-specific eBay credential variable names."""

    selected = str(environment).strip().lower()
    if selected not in {"production", "sandbox"}:
        raise ValueError("environment must be production or sandbox")
    prefix = selected.upper()
    return f"EBAY_{prefix}_CLIENT_ID", f"EBAY_{prefix}_CLIENT_SECRET"


def resolve_credentials(environment: str, environ: Mapping[str, str] | None = None) -> tuple[str | None, str | None]:
    """Resolve one complete environment keyset, with legacy fallback.

    If either environment-specific variable is supplied, the pair is used as
    a unit so a partial keyset cannot be silently mixed with another
    environment's credentials.
    """

    values = os.environ if environ is None else environ
    specific_id, specific_secret = credential_env_names(environment)
    scoped_id = str(values.get(specific_id) or "").strip()
    scoped_secret = str(values.get(specific_secret) or "").strip()
    if scoped_id or scoped_secret:
        return scoped_id or None, scoped_secret or None
    return (
        str(values.get("EBAY_CLIENT_ID") or "").strip() or None,
        str(values.get("EBAY_CLIENT_SECRET") or "").strip() or None,
    )


def credential_state(environment: str, environ: Mapping[str, str] | None = None) -> str:
    """Return only the selected environment's credential presence state."""

    client_id, client_secret = resolve_credentials(environment, environ)
    return {0: "missing", 1: "partial", 2: "present"}[int(bool(client_id)) + int(bool(client_secret))]


def _allowed_pagination_url(value: Any) -> bool:
    """Accept only official eBay Browse search links from response metadata.

    ``href``, ``next`` and ``prev`` are observability fields. They must never
    become an SSRF or evidence-boundary escape if an upstream response is
    malformed or compromised, even though this connector does not follow them.
    """

    if not isinstance(value, str) or not value or any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in value
    ):
        return False
    try:
        parsed = urllib.parse.urlparse(value)
        port = parsed.port
        query_keys = {
            key.strip().lower()
            for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        }
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in _OFFICIAL_API_HOSTS
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.path == _BROWSE_SEARCH_PATH
        and not parsed.params
        and not parsed.fragment
        and not query_keys.intersection(_SENSITIVE_QUERY_KEYS)
    )


@dataclass(frozen=True)
class EbayConnectorConfig:
    marketplace_id: str = "EBAY_HK"
    delivery_country: str = "HK"
    api_base: str = "https://api.ebay.com"
    token_url: str = "https://api.ebay.com/identity/v1/oauth2/token"
    timeout_seconds: float = 15.0
    default_limit: int = 20
    default_buying_option: str = "FIXED_PRICE"
    environment: str = "production"
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.marketplace_id != "EBAY_HK":
            raise ValueError("MVP connector is locked to EBAY_HK")
        if self.delivery_country != "HK":
            raise ValueError("MVP connector is locked to delivery country HK")
        if self.default_buying_option != "FIXED_PRICE":
            raise ValueError("MVP connector is read-only fixed-price search")
        if self.environment not in {"production", "sandbox"}:
            raise ValueError("environment must be production or sandbox")
        if not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number")
        if not isinstance(self.default_limit, int) or isinstance(self.default_limit, bool) or not 1 <= self.default_limit <= 200:
            raise ValueError("default_limit must be an integer between 1 and 200")
        if not isinstance(self.max_retries, int) or isinstance(self.max_retries, bool) or not 0 <= self.max_retries <= 5:
            raise ValueError("max_retries must be an integer between 0 and 5")
        if (
            not isinstance(self.retry_backoff_seconds, (int, float))
            or isinstance(self.retry_backoff_seconds, bool)
            or not math.isfinite(float(self.retry_backoff_seconds))
            or self.retry_backoff_seconds < 0
            or self.retry_backoff_seconds > 30
        ):
            raise ValueError("retry_backoff_seconds must be a finite number between 0 and 30")
        expected_host = "api.ebay.com" if self.environment == "production" else "api.sandbox.ebay.com"
        for name, value in (("api_base", self.api_base), ("token_url", self.token_url)):
            parsed = urllib.parse.urlparse(value)
            try:
                port = parsed.port
            except ValueError as exc:
                raise ValueError(f"{name} must use the official https://api.ebay.com host") from exc
            if (
                parsed.scheme != "https"
                or parsed.hostname != expected_host
                or parsed.username is not None
                or parsed.password is not None
                or port not in (None, 443)
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"{name} must use the official https://api.ebay.com host")
            expected_path = "" if name == "api_base" else "/identity/v1/oauth2/token"
            if parsed.path.rstrip("/") != expected_path.rstrip("/"):
                raise ValueError(f"{name} must use the registered eBay endpoint path")

    @classmethod
    def from_env(cls, environment: str | None = None) -> "EbayConnectorConfig":
        environment = str(environment if environment is not None else os.getenv("EBAY_ENVIRONMENT", "production")).strip().lower()
        default_host = "api.ebay.com" if environment == "production" else "api.sandbox.ebay.com"
        return cls(
            marketplace_id=os.getenv("EBAY_MARKETPLACE_ID", "EBAY_HK"),
            delivery_country=os.getenv("EBAY_DELIVERY_COUNTRY", "HK"),
            api_base=os.getenv("EBAY_API_BASE", f"https://{default_host}").rstrip("/"),
            token_url=os.getenv("EBAY_TOKEN_URL", f"https://{default_host}/identity/v1/oauth2/token"),
            timeout_seconds=float(os.getenv("EBAY_TIMEOUT_SECONDS", "15")),
            default_limit=int(os.getenv("EBAY_DEFAULT_LIMIT", "20")),
            environment=environment,
            max_retries=int(os.getenv("EBAY_MAX_RETRIES", "2")),
            retry_backoff_seconds=float(os.getenv("EBAY_RETRY_BACKOFF_SECONDS", "0.25")),
        )


class EbayBrowseConnector:
    """A read-only implementation of eBay ``item_summary/search``."""

    source_id = "ebay.browse.hk.v1"
    _RESPONSE_METADATA_FIELDS = ("href", "next", "prev", "total", "limit", "offset")
    _RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
    _MAX_RESPONSE_BYTES = 4_000_000
    _MAX_RETRY_AFTER_SECONDS = 30.0

    def __init__(
        self,
        config: EbayConnectorConfig | None = None,
        *,
        fixture_path: str | Path | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        opener: Any | None = None,
        environment: str | None = None,
    ) -> None:
        self.config = config or EbayConnectorConfig.from_env(environment=environment)
        self.fixture_path = Path(fixture_path) if fixture_path else None
        resolved_id, resolved_secret = resolve_credentials(self.config.environment)
        self.client_id = client_id if client_id is not None else resolved_id
        self.client_secret = client_secret if client_secret is not None else resolved_secret
        # The official endpoints are fixed above. Do not let urllib follow a
        # redirect and replay Basic/Bearer headers at another host.
        self.opener = opener or urllib.request.build_opener(_NoRedirectHandler())
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._last_latency_ms: float | None = None
        self._source_metadata = self._empty_source_metadata()

    @property
    def live_enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def credential_state(self) -> str:
        """Return credential presence without exposing credential values."""

        return {0: "missing", 1: "partial", 2: "present"}[
            int(bool(self.client_id)) + int(bool(self.client_secret))
        ]

    @staticmethod
    def _kill_switch_active() -> bool:
        """Honor the source registry kill switch before any live request."""

        return os.getenv("MUSE_SOURCE_EBAY_BROWSE_HK_DISABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

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
            metadata[field] = value if _allowed_pagination_url(value) else None
        for field in ("total", "limit", "offset"):
            value = payload.get(field)
            metadata[field] = value if isinstance(value, int) and not isinstance(value, bool) else None
        return metadata

    @staticmethod
    def _fetch_timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _listing_ended(item_end_date: Any, observed_at: str | None) -> bool:
        """Return true only when a valid end date precedes live observation.

        Fixture rows intentionally have an unknown observation clock, so their
        dates are retained as evidence but never compared with the local clock.
        This keeps offline regression results deterministic.
        """

        if not isinstance(item_end_date, str) or not item_end_date or not observed_at or observed_at == "unknown":
            return False
        try:
            end = datetime.fromisoformat(item_end_date.replace("Z", "+00:00"))
            observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return end <= observed

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

    @classmethod
    def _retry_after_seconds(cls, headers: Any) -> float | None:
        """Parse a bounded Retry-After value from an official response."""

        if headers is None:
            return None
        getter = getattr(headers, "get", None)
        raw = getter("Retry-After") if callable(getter) else None
        if raw in (None, ""):
            return None
        text = str(raw).strip()
        try:
            delay = float(text)
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(text)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        if not math.isfinite(delay) or delay < 0:
            return None
        return min(delay, cls._MAX_RETRY_AFTER_SECONDS)

    def _retry_delay(self, attempt: int, headers: Any = None) -> None:
        """Back off between bounded retries without retrying arbitrary errors."""

        delay = self._retry_after_seconds(headers)
        if delay is None:
            delay = float(self.config.retry_backoff_seconds) * (2**attempt)
        if delay > 0:
            time.sleep(delay)

    def _open_http(self, request: urllib.request.Request, context: str, *sensitive: Any) -> tuple[int, bytes]:
        """Read one official response, retrying only explicitly transient statuses."""

        for attempt in range(self.config.max_retries + 1):
            started = time.monotonic()
            try:
                with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                    status = self._response_status(response, context)
                    body = response.read(self._MAX_RESPONSE_BYTES + 1)
                    if not isinstance(body, (bytes, bytearray)):
                        raise ConnectorUnavailable(f"eBay {context} returned a non-byte response")
                    if len(body) > self._MAX_RESPONSE_BYTES:
                        raise ConnectorUnavailable(f"eBay {context} response exceeded the size limit")
            except urllib.error.HTTPError as exc:
                detail = exc.read(min(self._MAX_RESPONSE_BYTES + 1, 4096)).decode("utf-8", errors="replace")[:500]
                if exc.code in self._RETRYABLE_HTTP_STATUSES and attempt < self.config.max_retries:
                    self._retry_delay(attempt, getattr(exc, "headers", None) or getattr(exc, "hdrs", None))
                    continue
                raise ConnectorUnavailable(
                    self._redact_error(f"eBay {context} HTTP {exc.code}: {detail}", *sensitive)
                ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                raise ConnectorUnavailable(self._redact_error(f"eBay {context} unavailable: {exc}", *sensitive)) from exc
            if status in self._RETRYABLE_HTTP_STATUSES and attempt < self.config.max_retries:
                self._retry_delay(attempt, getattr(response, "headers", None))
                continue
            self._last_latency_ms = round((time.monotonic() - started) * 1000, 3)
            return status, body
        raise ConnectorUnavailable(f"eBay {context} retry loop exhausted")  # pragma: no cover

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
        if live:
            self._source_metadata["environment"] = self.config.environment
            self._source_metadata["latency_ms"] = self._last_latency_ms
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
        if self._kill_switch_active():
            raise ConnectorUnavailable("eBay live connector disabled by source kill switch")
        if not self.live_enabled:
            scoped_id, scoped_secret = credential_env_names(self.config.environment)
            raise ConnectorUnavailable(
                f"eBay live connector disabled: set {scoped_id} and {scoped_secret} "
                "(or legacy EBAY_CLIENT_ID and EBAY_CLIENT_SECRET), or pass fixture_path for offline mode"
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
        status, body = self._open_http(request, "Browse API", token)
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
        status, body = self._open_http(request, "OAuth")
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
        filters = [
            f"deliveryCountry:{self.config.delivery_country}",
            f"buyingOptions:{{{self.config.default_buying_option}}}",
        ]
        budget_min = search_spec.get("budget_min")
        budget_max = search_spec.get("budget_max")
        if isinstance(search_spec.get("budget"), Mapping):
            budget = search_spec["budget"]
            budget_min = budget_min if budget_min is not None else budget.get("min")
            budget_max = budget_max if budget_max is not None else budget.get("max")
        minimum = self._format_filter_amount(budget_min, "budget_min")
        maximum = self._format_filter_amount(budget_max, "budget_max")
        if minimum is not None or maximum is not None:
            if minimum is not None and maximum is not None and Decimal(minimum) > Decimal(maximum):
                raise ValueError("budget_min cannot exceed budget_max")
            filters.append(f"price:[{minimum or ''}..{maximum or ''}]")
            # Browse requires an explicit currency alongside a price filter.
            params["priceCurrency"] = "HKD"
        params["filter"] = ",".join(filters)
        return params

    @staticmethod
    def _format_filter_amount(value: Any, field: str) -> str | None:
        """Format a non-negative budget value for Browse's price filter."""

        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError(f"{field} must be a non-negative number")
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a non-negative number") from exc
        if not amount.is_finite() or amount < 0:
            raise ValueError(f"{field} must be a non-negative number")
        rendered = format(amount, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered or "0"

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
        # ``itemCreationDate`` describes the listing, not when this connector
        # observed the source. Live responses use the fetch timestamp; an
        # offline fixture has no observation clock and must remain unknown.
        observed_at = fetched_at or "unknown"
        specs = self._normalize_aspects(item.get("localizedAspects"))
        for identity_key in ("brand", "model", "mpn", "gtin", "epid"):
            identity_value = item.get(identity_key)
            if isinstance(identity_value, str) and identity_value.strip():
                specs[identity_key] = identity_value.strip()
        item_end_date = item.get("itemEndDate")
        if self._listing_ended(item_end_date, observed_at):
            specs["listing_ended"] = True
        evidence_fields = {
            "title": item.get("title"),
            "url": item.get("itemWebUrl"),
            "price": price,
            "condition": item.get("condition"),
            "seller": seller,
            "shippingOptions": shipping,
            "specs": specs,
        }
        if isinstance(item_end_date, str) and item_end_date:
            evidence_fields["itemEndDate"] = item_end_date
        identity = {key: specs[key] for key in ("brand", "model", "mpn", "gtin", "epid") if key in specs}
        if identity:
            evidence_fields["identity"] = identity
        raw_fields = {
            "title": "title",
            "url": "itemWebUrl",
            "price": "price",
            "condition": "condition",
            "seller": "seller",
            "shippingOptions": "shippingOptions",
            "specs": "localizedAspects",
            "itemEndDate": "itemEndDate",
            "identity": "identity_fields",
        }
        normalization_rules = {
            "specs": "normalize_localized_aspects",
            "identity": "normalize_identity_fields",
        }
        evidence = [
            {
                "field": field,
                "value": value,
                "source_id": self.source_id,
                "source_url": item.get("itemWebUrl"),
                "observed_at": observed_at,
                "extraction_method": "source_json",
                "raw_field": raw_fields.get(field, field),
                "normalization_rule": normalization_rules.get(field, "source_field"),
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
            "product_id": item.get("epid") or specs.get("gtin") or specs.get("mpn"),
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
                continue
            if name in {"warranty", "warranty duration", "manufacturer warranty", "seller warranty"}:
                specs["warranty"] = raw_value
                continue
            if name in {"brand", "manufacturer", "make"}:
                specs["brand"] = raw_value
                continue
            if name in {"model", "model number", "model name"}:
                specs["model"] = raw_value
                continue
            if name in {"mpn", "manufacturer part number", "part number"}:
                specs["mpn"] = raw_value
                continue
            if name in {"gtin", "upc", "ean", "isbn"}:
                specs["gtin"] = raw_value
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

