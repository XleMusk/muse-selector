# Offline regression set

`queries.json` contains the Hong Kong computer/hardware SearchSpec cases, including
missing fields, stale/conflict evidence, account-policy blocking, prompt injection,
SSRF and replay stability.

`listings.json` is a deterministic eBay Browse API-shaped fixture. It is not a live
snapshot and must not be presented as current inventory or price data.

`regression_policy.json` records the invariants for the read-only MVP:
`hard_constraint_violation_rate=0`, unknown values are not inferred, conflict/stale
states remain visible, external listing text is untrusted, and replay is stable.

Run without network or credentials from the repository root:

```powershell
$env:PYTHONPATH = "$PWD\\src;$PWD\\tests"
python tests/regression_harness.py
python -m unittest discover -s tests -p "test_*.py" -v
```
