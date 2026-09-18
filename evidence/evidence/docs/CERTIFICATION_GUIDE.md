# Certification Guide — the validation ladder

This is the human-facing view. Binding definitions: `CERTIFICATION.md`
(scope surfaces, two lanes, evidence layers A–F), `MT5_ROUNDTRIP.md`
(TEN-step owner protocol), `AEGIS_REALITY_GATE_AUDIT.md` (attack
matrices), `AEGIS_EMPIRICAL_LANE_PACKAGE.md` (empirical package).

## The core rule

**One evidence class may never impersonate another.** Software pass ⇏
MT5 validation; gold pass ⇏ empirical qualification; empirical pass
without reconciliation ⇏ VERIFIED; parser success ⇏ anything runtime.

## Lane 1 — GOLD semantic lane

Question: *do the Python, DSL and MQL5 implementations agree on the
controlled fixture?*

- **Gold #1** — 16-trade fixture, frozen at `artifacts/gold/`
  (manifest, fixture, traces, expected execution, reconciliation).
- **Gold #2** — 56-trade fixture,
  `GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`, frozen at `artifacts/gold_2/`.
- Deterministic, replayable, hash-chained. The golds are NEVER
  regenerated to match reality — a mismatch is evidence, investigated
  from the FIRST divergent event with the closed 14-class taxonomy
  (`SIGNAL/INDICATOR/WARMUP/SESSION/SIZING/ROUNDING/META/RISK/
  EXECUTION/DATA/TIMESTAMP/STATE/BROKER_SPEC/UNKNOWN` — no
  CLOSE_ENOUGH, no custom classes).
- **Gold semantic validation is NOT trading validation.** No
  trade-count minimum applies (56 trades is valid), and
  GOLD_SEMANTIC_PASS never implies MT5-VALIDATED or VERIFIED.

## Lane 2 — MT5 runtime lane

Question: *does the actual compiled EA behave as the deterministic
contract predicts?*

- Requires the owner's Windows/MetaEditor/terminal: strict compile,
  broker SymbolSpec export, gold legs on three tester models, model
  identity triad, real-tick coverage record, field-by-field
  reconciliation, safety exercises.
- The verifier (`tools/verify_owner_mt5_gate.py`) consumes the
  returned directory and assigns the verdict mechanically. Until owner
  artifacts exist this lane is **BLOCKED_OWNER_ENVIRONMENT**.

## Lane 3 — EMPIRICAL lane

Question: *does the strategy hold up across real regimes at sufficient
sample?*

- Separate dataset/symbols/windows, regime partition, full tester-model
  ladder, cost assumptions, degradation reporting, statistical gates —
  defined exactly in `AEGIS_EMPIRICAL_LANE_PACKAGE.md` (prepared, not
  executed).
- The **≥100-trade minimum lives ONLY here**. Applying it to golds (or
  letting golds satisfy it) is a contract violation.
- Empirical without reconciliation can never become VERIFIED.

## Lane 4 — DEMO lane

Adds live-like operation on a demo account: order routing, fills,
restart behavior, monitoring — after MT5 validation + clean
reconciliation + safety evidence + broker SymbolSpec confirmation +
human approval. Demo never auto-starts.

## Lane 5 — LIVE lane

Real money. A separate state with its own evidence; never implied by
any earlier lane; never started by tooling.

## Evidence layers A–F

A software → B gold semantics → C MT5 runtime → D empirical → E demo →
F live. Each layer has its own artifacts and its own gate; none
substitutes for another. Current states: A/B PROVEN locally; C/D/E
BLOCKED_OWNER_ENVIRONMENT / PENDING; F not begun.

## Statuses you will see

`GOLD_SEMANTIC_PASS` · `MT5_VALIDATED` · `EMPIRICAL_VALIDATED` ·
`DEMO_VALIDATED` · `VERIFIED` · `NOT_VERIFIED_*` (with exact reasons) ·
`BLOCKED_OWNER_ENVIRONMENT` · `REALITY_GATE_BLOCKED` ·
`REALITY_GATE_INCOMPLETE` · `OWNER_EXECUTION_READY` ·
`PRODUCTION = NOT_READY`. These are distinct states, not synonyms.

## If MT5 disagrees with a gold

1. STOP. 2. Find the FIRST divergent event (index/bar/time/field,
both values, full state snapshot). 3. Classify with the closed
taxonomy. 4. Determine the authoritative contract (SPEC / MQL5
behavior / broker spec / deterministic test). 5. Change EXACTLY ONE
side. 6. Re-run affected regressions AND both golds. Never dual-patch;
never move the expected result to match reality.
