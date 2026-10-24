import json
import io
import unittest
from pathlib import Path
from urllib.error import HTTPError

from muse_selector.connectors.ebay import ConnectorUnavailable, EbayBrowseConnector


class _Response:
    def __init__(self, payload, status=200):
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


class _Opener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append((request.get_method(), request.full_url, dict(request.headers)))
        if request.full_url.endswith("/identity/v1/oauth2/token"):
            return _Response({"access_token": "test-token", "expires_in": 7200})
        return _Response({
            "itemSummaries": [{
                "itemId": "live|1|0",
                "title": "Mini PC 32GB 1TB NVMe",
                "itemWebUrl": "https://www.ebay.com.hk/itm/live-1",
                "price": {"value": "4999.00", "currency": "HKD"},
                "condition": "New",
                "estimatedAvailabilityStatus": "IN_STOCK",
                "itemCreationDate": "2026-10-20T00:00:00.000Z",
                "itemEndDate": "2099-01-01T00:00:00.000Z",
            }]
        })


class _NonObjectOpener(_Opener):
    def open(self, request, timeout=None):
        self.requests.append((request.get_method(), request.full_url, dict(request.headers)))
        if request.full_url.endswith("/identity/v1/oauth2/token"):
            return _Response({"access_token": "test-token"})
        return _Response(["unexpected", "array"])


class _HttpErrorOpener(_Opener):
    def __init__(self, *, fail_on: str):
        super().__init__()
        self.fail_on = fail_on

    def open(self, request, timeout=None):
        self.requests.append((request.get_method(), request.full_url, dict(request.headers)))
        if self.fail_on == request.get_method():
            raise HTTPError(
                request.full_url,
                503,
                "service unavailable",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"temporary"}'),
            )
        if request.full_url.endswith("/identity/v1/oauth2/token"):
            return _Response({"access_token": "test-token"})
        return _Response({"itemSummaries": []})


class EbayLiveAdapterTests(unittest.TestCase):
    def test_oauth_and_browse_are_read_only_and_normalized(self):
        opener = _Opener()
        connector = EbayBrowseConnector(client_id="id", client_secret="secret", opener=opener)
        rows = connector.search({"query": "mini pc", "limit": 1})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"]["currency"], "HKD")
        self.assertEqual(rows[0]["availability"], "IN_STOCK")
        self.assertEqual(rows[0]["evidence"][0]["observed_at"], "2026-10-20T00:00:00.000Z")
        self.assertEqual(rows[0]["source_observed_at"], "2026-10-20T00:00:00.000Z")
        self.assertEqual([method for method, _, _ in opener.requests], ["POST", "GET"])
        self.assertEqual(opener.requests[1][2].get("X-ebay-c-marketplace-id"), "EBAY_HK")
        self.assertEqual(
            opener.requests[1][2].get("X-ebay-c-enduserctx"),
            "contextualLocation=country%3DHK",
        )
        self.assertIn("deliveryCountry%3AHK", opener.requests[1][1])

    def test_non_object_browse_response_fails_closed(self):
        connector = EbayBrowseConnector(client_id="id", client_secret="secret", opener=_NonObjectOpener())
        with self.assertRaises(ConnectorUnavailable):
            connector.search({"query": "mini pc"})

    def test_oauth_http_error_fails_closed(self):
        connector = EbayBrowseConnector(client_id="id", client_secret="secret", opener=_HttpErrorOpener(fail_on="POST"))
        with self.assertRaises(ConnectorUnavailable):
            connector.search({"query": "mini pc"})

    def test_browse_http_error_fails_closed(self):
        connector = EbayBrowseConnector(client_id="id", client_secret="secret", opener=_HttpErrorOpener(fail_on="GET"))
        with self.assertRaises(ConnectorUnavailable):
            connector.search({"query": "mini pc"})


if __name__ == "__main__":
    unittest.main()

