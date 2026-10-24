import json
import tempfile
import unittest
from pathlib import Path

from muse_selector.connectors.ebay import ConnectorUnavailable, EbayBrowseConnector, EbayConnectorConfig


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class EbayBrowseConnectorTests(unittest.TestCase):
    def test_fixture_normalizes_and_filters_budget(self):
        rows = EbayBrowseConnector(fixture_path=FIXTURE).search({"query": "mini pc", "budget_max": 7000})
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["source_id"], "ebay.browse.hk.v1")
        self.assertEqual(rows[0]["price"]["currency"], "HKD")
        self.assertEqual(rows[0]["availability"], "IN_STOCK")
        unknown = next(row for row in rows if row["listing_id"].endswith("004|0"))
        self.assertIsNone(unknown["url"])
        self.assertEqual(unknown["availability"], "unknown")

    def test_budget_filter_keeps_unknown_price(self):
        data = {"itemSummaries": [{"itemId": "x", "title": "unknown price"}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fixture.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            rows = EbayBrowseConnector(fixture_path=p).search({"budget_max": 100})
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["price"]["value"])

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

    def test_live_mode_is_closed_without_credentials(self):
        connector = EbayBrowseConnector(config=EbayConnectorConfig())
        with self.assertRaises(ConnectorUnavailable):
            connector.search({"query": "mini pc"})

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


if __name__ == "__main__":
    unittest.main()

