"""URL rules shared by source adapters and presentation boundaries."""

from __future__ import annotations

from urllib.parse import urlparse


MARKET_SOURCE_HOSTS = frozenset(
    {
        "ebay.com.hk",
        "www.ebay.com.hk",
        "ebay.com",
        "www.ebay.com",
    }
)


def is_absolute_http_url(value: str) -> bool:
    """Return whether ``value`` is an absolute HTTP or HTTPS URL."""

    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_allowed_market_url(value: str, *, hosts: frozenset[str] = MARKET_SOURCE_HOSTS) -> bool:
    """Return whether ``value`` is a safe read-only market listing URL."""

    if not isinstance(value, str) or not value or any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in value
    ):
        return False
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in hosts
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
    )
