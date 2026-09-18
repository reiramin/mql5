# DSL generic-runtime parity golden set (§12/§13)

Python-side reference for cross-engine parity. Each `<name>/` holds:
- `bundle.json` — the executable bundle (load into the generic runtime)
- `ohlc.csv` — the deterministic OHLC fixture (import as an offline symbol)
- `expected_trace.json` — the Python parity trace

## Owner MQL5 parity procedure (OWNER-PENDING — never faked on Mac)
1. Compile the generic runtime (`mql5_dsl_runtime/`) in MetaEditor.
2. For each fixture: import `ohlc.csv`, load `bundle.json`, run the
   runtime over the bars, export the per-bar desired-position vector.
3. Compare to `expected_trace.json["positions"]` — EXACT match required
   (logical values carry no tolerance). Report discrepancies bar-indexed.

`manifest.json` binds every file's sha256 + `position_hash`. Regenerate
with `python tools/build_dsl_parity_golden.py`; a changed digest is a
DECISION-CHANGING event (new provenance required).
