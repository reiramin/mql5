# tampered_bundle — negative fixture (MUST be refused)

`bundle.json` is the `ema_gt` bundle with ONE hashed-body byte changed
(`spec.indicators[0].period` 20.0 → 21.0) while `bundle_hash` and the
`identity` block keep their ORIGINAL values. Any loader that verifies
`bundle_hash` by canonical re-serialization + SHA-256 must detect the
mismatch and REFUSE to run a single bar.

Expected MQL5 runner output for this fixture
(`Mql5Bot\dsl_parity_out\tampered_bundle.json`):

```json
{"error":"bundle_hash mismatch ...","fixture":"tampered_bundle","refused":true}
```

`tools/compare_dsl_parity.py` FAILS the whole comparison if this fixture
produces a parity trace instead of a refusal. This fixture is deliberately
NOT in `manifest.json` (it is not part of the 14-fixture golden set and
`build_dsl_parity_golden.py` cannot generate an intentionally-broken
hash); the Python-side refusal is pinned by
`tests/test_compare_dsl_parity.py::test_python_loader_refuses_tampered_fixture`
(companion to `test_dsl_parity_golden.py::test_refusal_hash_mismatch`).
