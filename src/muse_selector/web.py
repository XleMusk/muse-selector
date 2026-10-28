"""Minimal local read-only web view for Muse Selector results."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .application import search as run_search
from .contracts import RESULT_SCHEMA_VERSION
from .persistence import SelectorStore
from .source_capabilities import source_capability_registry
from .source_factory import describe_default_source
from . import web_views as _web_views

# Keep the historical symbols importable from ``muse_selector.web``.
_capability_label = _web_views._capability_label
_compatibility_matrix_markup = _web_views._compatibility_matrix_markup
_evidence_excerpt = _web_views._evidence_excerpt
_safe_href = _web_views._safe_href
_safe_manual_href = _web_views._safe_manual_href
_source_metadata_markup = _web_views._source_metadata_markup
_text = _web_views._text
render_html = _web_views.render_html


def _validate_bind_host(host: str) -> str:
    """Keep the local result page on loopback to prevent cross-tenant reads."""

    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("local result page host must be 127.0.0.1 or ::1")
    return host


def capability_snapshot(environment: str | None = None) -> dict[str, Any]:
    """Return local source readiness without issuing any network request."""

    selected_environment = str(
        environment if environment is not None else os.environ.get("EBAY_ENVIRONMENT", "production")
    ).strip().lower()
    source_registry = source_capability_registry()
    sources: dict[str, dict[str, Any]] = {}
    for source_id, capability in source_registry.items():
        source = capability.to_dict()
        if len(capability.allowed_regions) == 1:
            region = capability.allowed_regions[0]
            source["region"] = region
            source["currency"] = {"HK": "HKD", "CN": "CNY"}.get(region)
        sources[source_id] = source
    ebay = sources["ebay.browse.hk.v1"]
    ebay.update(describe_default_source(selected_environment))
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "ok": True,
        "read_only": True,
        "sources": sources,
    }


def make_handler(
    fixture_path: str | Path | None = None,
    store: SelectorStore | None = None,
    environment: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Create a request handler bound to one fixture or source configuration."""
    fixture = str(fixture_path) if fixture_path is not None else None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                self._send_json(200, {"ok": True, "read_only": True})
                return
            if parsed.path == "/api/capabilities":
                self._send_json(200, capability_snapshot(environment))
                return
            if parsed.path == "/api/watches":
                if store is None:
                    self._send_json(
                        503,
                        {
                            "ok": False,
                            "status": "watch_unavailable",
                            "message": "start the web view with --db to expose persisted watches",
                            "read_only": True,
                        },
                    )
                    return
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "status": "watches_ready",
                        "read_only": True,
                        "watches": store.list_watches(),
                    },
                )
                return
            if parsed.path == "/api/watch":
                watch_id = parse_qs(parsed.query).get("watch_id", [""])[0].strip()
                if not watch_id:
                    self._send_json(
                        400,
                        {
                            "ok": False,
                            "status": "invalid_query",
                            "message": "watch_id is required",
                            "read_only": True,
                        },
                    )
                    return
                if store is None:
                    self._send_json(
                        503,
                        {
                            "ok": False,
                            "status": "watch_unavailable",
                            "message": "start the web view with --db to expose persisted watch snapshots",
                            "read_only": True,
                        },
                    )
                    return
                watch = store.get_watch(watch_id)
                if watch is None:
                    self._send_json(
                        404,
                        {
                            "ok": False,
                            "status": "watch_not_found",
                            "message": f"unknown watch_id: {watch_id}",
                            "read_only": True,
                        },
                    )
                    return
                result: dict[str, Any] = {
                    "ok": True,
                    "status": "watch_ready",
                    "read_only": True,
                    "watch": watch,
                }
                run_id = watch.get("last_run_id")
                if run_id:
                    try:
                        result["payload"] = store.replay_run(str(run_id))
                    except KeyError as exc:
                        self._send_json(
                            409,
                            {
                                "ok": False,
                                "status": "watch_unavailable",
                                "message": str(exc.args[0]) if exc.args else str(exc),
                                "watch_id": watch_id,
                                "read_only": True,
                            },
                        )
                        return
                self._send_json(200, result)
                return
            if parsed.path == "/api/watch/changes":
                params = parse_qs(parsed.query)
                watch_id = params.get("watch_id", [""])[0].strip()
                if not watch_id:
                    self._send_json(
                        400,
                        {
                            "ok": False,
                            "status": "invalid_query",
                            "message": "watch_id is required",
                            "read_only": True,
                        },
                    )
                    return
                if store is None:
                    self._send_json(
                        503,
                        {
                            "ok": False,
                            "status": "watch_unavailable",
                            "message": "start the web view with --db to expose persisted watch changes",
                            "read_only": True,
                        },
                    )
                    return
                try:
                    limit = int(params.get("limit", ["100"])[0])
                    offset_changes = int(params.get("offset", ["0"])[0])
                    if limit <= 0 or limit > 1000 or offset_changes < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    self._send_json(
                        400,
                        {
                            "ok": False,
                            "status": "invalid_query",
                            "message": "limit must be 1..1000 and offset must be non-negative",
                            "read_only": True,
                        },
                    )
                    return
                include_payload = params.get("include_payload", [""])[0].lower() in {"1", "true", "yes"}
                try:
                    changes = store.list_watch_changes(
                        watch_id,
                        limit=limit,
                        offset=offset_changes,
                        include_payload=include_payload,
                    )
                except KeyError:
                    self._send_json(
                        404,
                        {
                            "ok": False,
                            "status": "watch_not_found",
                            "message": f"unknown watch_id: {watch_id}",
                            "read_only": True,
                        },
                    )
                    return
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "status": "watch_changes_ready",
                        "read_only": True,
                        "watch_id": watch_id,
                        "limit": limit,
                        "offset": offset_changes,
                        "changes": changes,
                    },
                )
                return
            if parsed.path == "/api/watch/events":
                params = parse_qs(parsed.query)
                watch_id = params.get("watch_id", [""])[0].strip()
                if not watch_id:
                    self._send_json(400, {"ok": False, "status": "invalid_query", "message": "watch_id is required", "read_only": True})
                    return
                if store is None:
                    self._send_json(503, {"ok": False, "status": "watch_unavailable", "message": "start the web view with --db to expose persisted watch events", "read_only": True})
                    return
                try:
                    limit = int(params.get("limit", ["100"])[0])
                    offset_events = int(params.get("offset", ["0"])[0])
                    if limit <= 0 or limit > 1000 or offset_events < 0:
                        raise ValueError
                    events = [
                        event.to_dict()
                        for event in store.list_watch_event_models(watch_id, limit=limit, offset=offset_events)
                    ]
                except ValueError:
                    self._send_json(400, {"ok": False, "status": "invalid_query", "message": "limit must be 1..1000 and offset must be non-negative", "read_only": True})
                    return
                except KeyError:
                    self._send_json(404, {"ok": False, "status": "watch_not_found", "message": f"unknown watch_id: {watch_id}", "read_only": True})
                    return
                self._send_json(200, {"ok": True, "status": "watch_events_ready", "read_only": True, "watch_id": watch_id, "limit": limit, "offset": offset_events, "events": events})
                return
            if parsed.path == "/api/search":
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0]
                raw_limit = params.get("limit", ["10"])[0]
                raw_offset = params.get("offset", ["0"])[0]
                try:
                    limit = int(raw_limit)
                except (TypeError, ValueError):
                    limit = 0
                try:
                    offset_search: int | str = int(raw_offset)
                except (TypeError, ValueError):
                    # Preserve malformed input so run_search returns its
                    # structured invalid_query response instead of silently
                    # changing the requested page to offset zero.
                    offset_search = raw_offset
                search_kwargs: dict[str, Any] = {"limit": limit, "offset": offset_search}
                if environment is not None:
                    search_kwargs["environment"] = environment
                payload = run_search(query, fixture, **search_kwargs)
                self._send_json(200, payload)
                return
            if parsed.path != "/":
                self._send(404, "text/plain; charset=utf-8", b"not found")
                return
            query = parse_qs(parsed.query).get("q", ["国内预算 CNY 8000 以内的二手迷你主机"])[0]
            search_kwargs = {"environment": environment} if environment is not None else {}
            content = render_html(run_search(query, fixture, **search_kwargs), query).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", content)

        def _send(self, status: int, content_type: str, content: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            # Every JSON endpoint carries the same additive envelope marker.
            # Existing fields remain untouched for older clients.
            body = dict(payload)
            body.setdefault("schema_version", RESULT_SCHEMA_VERSION)
            content = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self._send(status, "application/json; charset=utf-8", content)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def serve(
    fixture_path: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: str | Path | None = None,
    environment: str | None = None,
) -> None:
    host = _validate_bind_host(host)
    store = SelectorStore(db_path, search_fn=run_search) if db_path is not None else None
    server = ThreadingHTTPServer((host, port), make_handler(fixture_path, store, environment))
    print(f"Muse Selector read-only web view: http://{host}:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Local read-only Muse Selector web view")
    parser.add_argument("--fixture", default=None, help="offline fixture; omit to use live read-only API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    parser.add_argument("--db", default=None, help="local SQLite database for read-only /api/watch snapshots")
    args = parser.parse_args()
    serve(
        Path(args.fixture) if args.fixture else None,
        args.host,
        args.port,
        Path(args.db) if args.db else None,
        args.environment,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

