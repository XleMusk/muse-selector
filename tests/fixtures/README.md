# Offline regression set

`queries.json` contains the Hong Kong computer/hardware SearchSpec cases, including
missing fields, stale/conflict evidence, account-policy blocking, prompt injection,
SSRF and replay stability.

`listings.json` is a deterministic eBay Browse API-shaped fixture. It is not a live
snapshot and must not be presented as current inventory or price data.

`category_golden.json` adds one evidence-complete phone, laptop and GPU record for
the shared category-attribute and hard-filter contract tests.

`regression_policy.json` records the invariants for the read-only MVP:
`hard_constraint_violation_rate=0`, unknown values are not inferred, conflict/stale
states remain visible, external listing text is untrusted, and replay is stable.
Positive cases in `queries.json` also carry curated `relevant_listing_ids` labels;
the harness reports reproducible Precision@10, Recall@20, NDCG@10 and replay
Top-k Jaccard baselines over those labels. These are fixture metrics, not live-market
quality claims.
The regression output also includes a deterministic `quality_report`: identity keys
use only explicit GTIN/EPID/MPN/SKU or brand/model fields, duplicate groups are
counted, and freshness uses the fixture's newest observation as the reference time.
Titles never supply an inferred identity.

Run without network or credentials from the repository root:

```powershell
$env:PYTHONPATH = "$PWD\\src;$PWD\\tests"
python tests/regression_harness.py
python -m unittest discover -s tests -p "test_*.py" -v
```
