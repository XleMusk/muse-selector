"""Small HTTP helpers shared by read-only source connectors."""

from __future__ import annotations

import urllib.request


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so source credentials never follow a new host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


__all__ = ["NoRedirectHandler"]
