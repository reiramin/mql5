# Automated owner gate (`tools/owner_gate.ps1`)

One command the Windows owner runs. Every DECISION lives in committed code
(`python/mql5bot/gate_selfcheck.py`, invoked through
`tools/owner_gate_decide.py`, plus the existing verifiers), never in a
prompt: the script orchestrates, records, and stops; it does not judge by
hand.

This document describes what the script DOES. It makes no claim that any
compile, tester run, dataset import, broker-parity or certification step has
passed — those outcomes are produced only when the owner runs the command on
a real terminal, and each is recorded truthfully (PASS / FAIL / SKIP /
DIVERGENCE_EXPECTED) in the evidence directory.

## The single command

```
powershell -ExecutionPolicy Bypass -File tools\owner_gate.ps1 -DataFolder <MT5 data folder> [-Portable]
```

Optional overrides: `-TerminalPath`, `-MetaEditorPath`, `-SymbolSpecExport`,
`-TimeoutSec`. Environment fallbacks: `MQL5BOT_TERMINAL`,
`MQL5BOT_METAEDITOR`, `MQL5BOT_DATA_FOLDER`, `MQL5BOT_PYTHON`,
`MQL5BOT_EVIDENCE_DIR`.

All output lands under `evidence\owner_gate\<UTC>\`, append-only: one
`stage_<n>.json` per stage, a `gate_summary.json`, and a final line
`GATE_RESULT=<stage-name>`.

## Stages (stop at the first FAIL)

- **A. Self-protection** — aborts with a NAMED reason unless: `HEAD` relates
  to the frozen `source.commit` acceptably (it equals the anchor, or is a
  clean **descendant** of it — a legitimate newer commit, recorded as a NOTE,
  never a hard abort; an **older**, **diverged**, or **unknown** anchor
  fails); the working tree is clean; `core.autocrlf` is not `true`/`input`;
  `frozen_inputs.json` is byte-identical to its committed blob (no
  hand-written record); every frozen hash matches the committed bytes; the
  dsl-parity manifest binds and all 42 files verify; and `terminal64.exe` /
  `metaeditor64.exe` are located. What is certified is that the frozen
  ARTIFACTS are byte-unchanged and the tree is clean, not that `HEAD` is one
  historical SHA. Optionally, pass `-CloneInto <dir>` and the gate refuses by
  name up front if that fresh-clone directory already exists, rather than
  letting a later `git clone` fail and leaving you to move directories by
  hand.
- **1. Strict compile** — runs `compile.ps1 -Strict`, decodes the LOG
  BOM-aware (owner logs are UTF-16 or UTF-8-BOM), and requires `0 errors, 0
  warnings` with every compiled target the repo ships reported clean. The
  target set is derived from the committed sources, so it tracks the tree
  (four sources at the calibration commit; five once the fixture importer is
  present).
- **2. DSL parity** — runs `run_dsl_parity.ps1` and requires `14/14 fixtures
  EXACT` with the tampered bundle refused.
- **3. SymbolSpec + broker parity** — runs `broker_symbol_parity.py`; a
  `MISMATCH` on any row aborts, while a PENDING crypto/BTC row is excluded
  from certification scope (an open owner-side measurement, never a silent
  pass, never an abort).
- **4. Fixture import** — stages each committed gold fixture + its manifest +
  the stage-3 SymbolSpec export under `MQL5\Files`, runs
  `Mql5BotImportFixture.mq5` to build a custom symbol via
  `CustomRatesUpdate`, and requires the round-tripped dataset hash to
  re-derive the manifest `dataset_hash`. The importer refuses and creates
  nothing on any missing property or hash mismatch.
- **5-7. Tester legs** — the six legs (Gold #1/#2 × m1_ohlc / every_tick /
  real_ticks); the raw report and sidecar are archived and the ACTUAL model
  is read from the report and journal, not the requested one.
- **8. Reconciliation** — the full bindings object plus the safety sub-checks
  (kill-switch; restart; retry/adoption/SlGuard; netting and hedging) via
  `verify_owner_mt5_gate.py`. A first divergence on a volume/risk field is
  the EXPECTED consequence of the 4257f1e sizing fix: it is classified
  (`SIZING_MISMATCH` / `RISK_MISMATCH`) and recorded as
  `DIVERGENCE_EXPECTED` with an owner/build follow-up note to regenerate the
  affected `expected_execution` with NEW provenance. The script never reverts
  the fix and never patches the gold artifacts.
- **9. Archive manifest** — `owner_evidence_bind.py` only; no hand-typed
  hash.
- **10. Certify** — `certify_strategy.py` records whatever state it assigns.

## Hard rules (in the script, not the operator)

The script never writes `frozen_inputs.json`; never edits
`certification_manifest.json` outside the binder; never substitutes live
chart history for a committed fixture; never amends or force-pushes (it does
not commit at all); and records/classifies divergences rather than patching
them.

## Re-anchor note

The frozen record is governed by an owner-authority re-anchor (see
`artifacts/owner_mt5_gate/frozen_inputs.json` `source.note` and the
`docs/DECISIONS.md` 2026-09-18 entry). The anchor is now `a85cba3` — the
227bf66 anchor predated the generic DSL runtime, the reserved-word compile
fix and the P0-1 sizing fix (`4257f1e`), so it could never be the commit to
run. Stage A no longer requires `HEAD` to equal the anchor: a clean `HEAD`
that **descends** from the anchor, with every frozen artifact byte-identical,
PASSES with a recorded NOTE (`SELF_PROTECT_HEAD_AHEAD_OF_ANCHOR`). Only an
**older** HEAD, a **diverged** HEAD, an **unknown** anchor, a changed frozen
artifact, a dirty tree, or `core.autocrlf=true/input` fails
(`SELF_PROTECT_HEAD_MISMATCH` / `SELF_PROTECT_FROZEN_HASH_MISMATCH` /
`SELF_PROTECT_DIRTY_TREE` / `SELF_PROTECT_AUTOCRLF_NOT_FALSE`). The owner
performs any re-anchor; the gate never writes `frozen_inputs.json`.

## Verifying the decision engine on any host

`tools/owner_gate_decide.py` and `mql5bot.gate_selfcheck` run anywhere;
`tests/test_owner_gate_ps1.py` exercises the self-protection failures, the
BOM-aware log parse, the parity and broker-scope decisions, and the dataset
hash against the committed calibration fixtures. A green test there proves
the gate fails closed; it is not an MT5 or certification claim.
