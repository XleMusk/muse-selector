import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from muse_selector.connectors.ebay import ConnectorUnavailable, EbayBrowseConnector, EbayConnectorConfig


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class EbayBrowseConnectorTests(unittest.TestCase):
    def test_fixture_normalizes_and_filters_budget(self):
        rows = EbayBrowseConnector(fixture_path=FIXTURE).search({"query": "mini pc", "budget_max": 7000})
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["source_id"], "ebay.browse.hk.v1")
        self.assertEqual(rows[0]["source_rank"], 1)
        self.assertEqual(rows[0]["source_metadata"]["href"], "https://api.ebay.com/buy/browse/v1/item_summary/search?q=mini%20pc")
        self.assertEqual(rows[0]["source_metadata"]["total"], 5)
        self.assertIsNone(rows[0]["source_metadata"]["next"])
        self.assertIsNone(rows[0]["source_metadata"]["limit"])
        self.assertIsNone(rows[0]["source_metadata"]["offset"])
        self.assertEqual(rows[0]["price"]["currency"], "HKD")
        self.assertEqual(rows[0]["availability"], "IN_STOCK")
        unknown = next(row for row in rows if row["listing_id"].endswith("004|0"))
        self.assertIsNone(unknown["url"])
        self.assertEqual(unknown["availability"], "unknown")

    def test_fixture_filters_budget_range_at_connector_boundary(self):
        rows = EbayBrowseConnector(fixture_path=FIXTURE).search({"query": "mini pc", "budget_min": 5000, "budget_max": 7000})
        self.assertEqual([row["listing_id"] for row in rows], ["v1|100000000001|0"])

    def test_budget_filter_keeps_unknown_price(self):
        data = {"itemSummaries": [{"itemId": "x", "title": "unknown price"}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            rows = EbayBrowseConnector(fixture_path=p).search({"budget_max": 100})
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["price"]["value"])

    def test_response_metadata_preserves_page_links_and_counters(self):
        data = {
            "href": "https://api.ebay.com/buy/browse/v1/item_summary/search?q=mini%20pc&limit=1&offset=1",
            "next": "https://api.ebay.com/buy/browse/v1/item_summary/search?q=mini%20pc&limit=1&offset=2",
            "prev": "https://api.ebay.com/buy/browse/v1/item_summary/search?q=mini%20pc&limit=1&offset=0",
            "total": 9,
            "limit": 1,
            "offset": 1,
            "itemSummaries": [{"itemId": "x", "title": "Mini PC"}],
        }
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            connector = EbayBrowseConnector(fixture_path=p)
            rows = connector.search({"query": "mini pc"})
        expected = {key: data[key] for key in ("href", "next", "prev", "total", "limit", "offset")}
        self.assertEqual(rows[0]["source_metadata"], expected)
        self.assertEqual(connector.source_metadata, expected)

    def test_non_object_fixture_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.json"
            p.write_text(json.dumps([{"itemId": "x"}]), encoding="utf-8")
            with self.assertRaises(ConnectorUnavailable):
                EbayBrowseConnector(fixture_path=p).search({"query": "mini pc"})

    def test_non_object_item_fails_closed(self):
        data = {"itemSummaries": [{"itemId": "x"}, "unexpected"]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ConnectorUnavailable):
                EbayBrowseConnector(fixture_path=p).search({"query": "mini pc"})

    def test_duplicate_item_ids_fail_closed(self):
        data = {"itemSummaries": [{"itemId": "duplicate"}, {"itemId": "duplicate"}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ConnectorUnavailable):
                EbayBrowseConnector(fixture_path=p).search({"query": "mini pc"})

    def test_malformed_item_summaries_shape_fails_closed(self):
        data = {"itemSummaries": {"unexpected": True}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ConnectorUnavailable):
                EbayBrowseConnector(fixture_path=p).search({"query": "mini pc"})

    def test_connector_config_rejects_invalid_timeout_and_limit(self):
        with self.assertRaises(ValueError):
            EbayConnectorConfig(timeout_seconds=0)
        with self.assertRaises(ValueError):
            EbayConnectorConfig(timeout_seconds=float("nan"))
        with self.assertRaises(ValueError):
            EbayConnectorConfig(default_limit=201)

    def test_live_mode_is_closed_without_credentials(self):
        connector = EbayBrowseConnector(config=EbayConnectorConfig())
        with self.assertRaises(ConnectorUnavailable):
            connector.search({"query": "mini pc"})

    def test_live_kill_switch_fails_closed_before_network(self):
        opener = Mock()
        with patch.dict(os.environ, {"MUSE_SOURCE_EBAY_BROWSE_HK_DISABLED": "true"}, clear=False):
            connector = EbayBrowseConnector(client_id="id", client_secret="secret", opener=opener)
            with self.assertRaises(ConnectorUnavailable):
                connector.search({"query": "mini pc"})
        opener.open.assert_not_called()

    def test_query_params_are_read_only_hk_fixed_price(self):
        params = EbayBrowseConnector()._query_params({"query": "rtx 4070", "limit": 999})
        self.assertEqual(params["q"], "rtx 4070")
        self.assertEqual(params["limit"], "200")
        self.assertIn("deliveryCountry:HK", params["filter"])
        self.assertIn("buyingOptions:{FIXED_PRICE}", params["filter"])

    def test_connector_cannot_be_reconfigured_outside_hk(self):
        with self.assertRaises(ValueError):
            EbayConnectorConfig(marketplace_id="EBAY_US")

    def test_connector_cannot_be_reconfigured_to_untrusted_network(self):
        with self.assertRaises(ValueError):
            EbayConnectorConfig(api_base="http://127.0.0.1:8080")

    def test_connector_rejects_endpoint_userinfo_and_nonstandard_port(self):
        with self.assertRaises(ValueError):
            EbayConnectorConfig(api_base="https://user:secret@api.ebay.com")
        with self.assertRaises(ValueError):
            EbayConnectorConfig(token_url="https://api.ebay.com:8443/identity/v1/oauth2/token")


if __name__ == "__main__":
    unittest.main()

