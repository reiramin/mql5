# WINDOWS OWNER CERTIFICATION — HANDOFF PACKAGE

**Purpose.** This is the entry point for the Windows Owner Certification
Campaign. It binds the exact inputs (source, compile command, targets,
symbols) and points to the ONE canonical runtime protocol. It does **not**
define a new or shorter protocol — the authority is `docs/MT5_ROUNDTRIP.md`
(ten steps + sub-checks) and `docs/CERTIFICATION.md` (two lanes, five
states).

The Mac engineering phase is **FROZEN** at this handoff. No MT5 runtime,
Strategy Tester, real-tick, Gold runtime, demo, live or empirical result is
produced or simulated on Mac. Everything below is **owner/Windows work**.

---

## 1. Source under certification

| Item | Value |
|---|---|
| Repository | `https://github.com/reiramin/mql5` |
| Branch | `master` |
| **Compile target (frozen anchor)** | commit `227bf665654b2d2491c89c226dcff735570b915a` — pinned by `artifacts/owner_mt5_gate/frozen_inputs.json` (`source.commit`) |
| Docs/tests tip | `origin/master` HEAD (Wave-2.1 freeze — the commit that adds this file) |
| MQL5 source equivalence | `git diff 227bf665654b2d2491c89c226dcff735570b915a origin/master -- mql5/` is **empty** — the EA/scripts are byte-identical between the frozen anchor and the current tip, so compiling either yields the same `.ex5`. Waves 1–2 changed only Python, docs and the owner-gate metadata. |

**Before anything:** checkout the frozen anchor, then verify every hash in
`artifacts/owner_mt5_gate/frozen_inputs.json` (gold_1 / gold_2 fixture,
manifest, config, spec, expected-execution SHA-256). Any mismatch → **STOP**.

## 2. Compile command (step 1)

```powershell
powershell -ExecutionPolicy Bypass -File tools\compile.ps1 -Strict `
    -MetaEditorPath "D:\MT5\metaeditor64.exe"
```

`-Strict` fails the build on any warning token. Exit codes: `0` PASS,
`1/2/3/4` → stop and record `SOFTWARE_FAIL` (MT5 stays NOT VERIFIED). See the
header of `tools/compile.ps1`.

## 3. Required MQL5 targets

Every `*.mq5` under `Experts\Mql5Bot` and `Scripts\Mql5Bot` must compile
0 errors / 0 warnings:

- `mql5/Experts/Mql5Bot/Mql5Bot.mq5` — the EA (only execution surface;
  five built-in engines via `ENUM_MQL5BOT_STRATEGY`, no DSL interpreter).
- `mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5` — SymbolSpec + Stage-A
  denomination-probe exporter (step 3).
- `mql5/Scripts/Mql5Bot/Mql5BotDownloadData.mq5` — data fetch for fixture
  preparation (step 4, alternative lane).

## 4. Required owner SymbolSpec exports (step 3)

Run `Mql5BotExportSymbolSpec.mq5` on the live account of record, at least one
symbol per asset class, and commit the produced
`MQL5\Files\Mql5Bot\broker_exports\*.json` under `data/broker_exports/` on the
certification host, then run `python tools/broker_symbol_parity.py`.

Required broker symbols (one per asset class the broker offers):

| Asset class | Symbol |
|---|---|
| FX | `EURUSD` |
| METAL | `XAUEUR` |
| INDEX CFD | `US30` |
| CRYPTO | `BTC` (broker's BTC symbol) |

Each export must carry a successful `denomination_probe`
(`ok=true`, `source=OrderCalcProfit`). **Note:** the owner has already
captured these probes on Windows (2026-09-16); they are NOT committed to Git
(`data/` is gitignored), so the parity **verdict is still PENDING in the
repository** until the exports are committed on the certification host and the
harness renders an accepted `ACCOUNT_CURRENCY` / `PROFIT_CURRENCY` verdict.
`probe.ok=true` is a precondition, not a PASS. See
`docs/BROKER_SYMBOL_PARITY.md` → "Owner-evidence provenance".

The tick-value **denomination decision remains owner-gated** (PENDING): it is
resolved only by the harness verdict above, never by inventing an FX rate and
never by deriving it circularly from `tick_value` (see `docs/DECISIONS.md`
2026-09-16 Wave-1 entry).

## 5. Canonical runtime sequence (authority: `docs/MT5_ROUNDTRIP.md`)

Run the ten-step owner sequence exactly. The twelve owner actions map onto it
as follows (they are the SAME protocol — steps 9–10 are sub-checks 8a/8b, not
extra steps):

| Owner action | Canonical step (`MT5_ROUNDTRIP.md`) |
|---|---|
| 1. exact-source compile | Step 1 — strict compile |
| 2. compile-log verification | Step 2 — 0 errors / 0 warnings from the LOG + `.ex5` SHA-256 |
| 3. SymbolSpec export + parity | Step 3 — export → `broker_symbol_parity.py` |
| 4. fixture / data preparation | Step 4 — frozen gold fixtures; dataset hash == manifest before any run |
| 5. M1-OHLC leg | Step 5 — baseline leg (gold lane + empirical lane) |
| 6. Every Tick leg | Step 6 |
| 7. Every Tick + real ticks | Step 7 — plus real-tick coverage record |
| 8. Python↔MT5 reconciliation | Step 8 — field-by-field vs `artifacts/gold*/expected_execution.json`, closed classification set |
| 9. kill-switch seam | Step 8 sub-check **8a** — zero new orders while latched; required BEFORE first live order |
| 10. restart proof | Step 8 sub-check **8b** — no duplicate exposure, state reload |
| 11. immutable owner archive | Step 9 — one append-only certification manifest binding every artifact + SHA-256 |
| 12. certification-state assignment | Step 10 — exactly one of the five states |

Also required by step 8 (do not skip): sub-check **8c** execution-path proofs
(retry/backoff, lost-response adoption, SlGuard verify→modify→re-verify) and
**8d** account-type legs (NETTING and HEDGING).

**Reconciliation bindings (step 8 — the verifier fails closed without them).**
Each `reconciliation/gold{1,2}.json` must carry a `bindings` object with ALL
of: `source_commit`, `fixture_sha256`, `config_hash`, `dataset_hash`,
`symbolspec_sha256`, `ex5_sha256`, `expected_execution_sha256` (anchors the
python column to the frozen truth engine — must equal
`frozen_inputs.json` `gold_X.expected_execution_sha256`), `tester_models`
(covering every model: m1_ohlc, every_tick, real_ticks), `raw_report_hashes`
and `parsed_report_hashes`. Every per-event field records `{"python": …,
"mt5": …, "status": …}`; divergence is computed from the python vs mt5
VALUES (the `status` label is advisory and cannot hide a value mismatch).
Generate every hash with `python tools/owner_evidence_bind.py bind …` — never
hand-type one. The verifier (`tools/verify_owner_mt5_gate.py`) names any
missing/mismatched binding in its `reasons`.

Two independent lanes (never conflate — `docs/CERTIFICATION.md`): the **GOLD
lane** (frozen Gold #1/#2 reconciliation, no trade-count gate) and the
**EMPIRICAL lane** (regime × model ladder, 100-trade minimum). A gold pass can
never mint `VERIFIED`; `VERIFIED` requires the empirical ladder pass WITH the
step-8 reconciliation recorded.

## 6. Current status the owner inherits (do not collapse)

| Lane | Status |
|---|---|
| CODE side | **COMPLETE** (Mac, frozen) |
| RESEARCH side | **COMPLETE** to the current declared scope (ML = estimation-only interfaces) |
| Owner MT5 compile | **PENDING — OWNER GATE** |
| Real-tick | **PENDING — OWNER GATE** |
| Gold runtime reconciliation | **PENDING — OWNER GATE** |
| Empirical ladder | **PENDING — OWNER GATE** |
| Broker parity verdict | **PENDING** (probes captured on Windows, exports not committed) |
| DEMO | **NOT_READY** (owner gates precede it) |
| LIVE | **NOT_READY** |

Overall certification state: **REALITY_GATE_BLOCKED** until the owner
round-trip runs. No profit claims; nothing is runtime-certified.

## 7. Owner evidence package

The frozen input contract and scaffold for the owner run live in
`artifacts/owner_mt5_gate/` (`frozen_inputs.json`, `certification_manifest.json`
with `PENDING_OWNER` fields, `real_tick_coverage.json`, `checklist.md`,
`report_template.md`, `README.md` describing the 29-file layout). Fill the
`PENDING_OWNER` fields from the owner's real `MT5_` evidence — never copy
Python values.
