# OWNER ACTION REQUIRED NOW

### First command

```
powershell -ExecutionPolicy Bypass -File tools\compile.ps1 -Strict
```

Run it in the repository folder, checked out at the frozen commit
(see "Frozen inputs" below).

### First return package

* the verbatim compiler log (`compile/compile.log` — do not edit it)
* the fresh EX5 SHA-256 hashes
* the compiler version
* the terminal version/build
* the source commit

Put them into the evidence directory exactly as named in "Evidence
directory contract" below, then verify with:

```
python tools/verify_owner_mt5_gate.py <evidence-dir>
```

**PASS** = exit code 0 and verdict `MT5_VALIDATED`.
**FAIL** = exit code 1 with the exact reasons printed — return the
directory AS-IS with those artifacts; do not improvise, do not edit
fixtures, do not regenerate golds. A difference is evidence, not a
failure of the owner.

### Next

Run the canonical ten-step MT5 protocol (`docs/MT5_ROUNDTRIP.md`).
Do not improvise.

## The ten-step owner flow (follow in order, no skipping)

Every step: run the command, confirm the expected file exists, compute
its hash with `tools/owner_evidence_bind.py`, and on any failure stop
and return what you have. Never edit a fixture or invent a metric.

| Step | Action | Command / source | Expected artifact | Failure condition |
|---|---|---|---|---|
| 1 | Compile | `powershell -ExecutionPolicy Bypass -File tools\compile.ps1 -Strict` | `compile/compile.log`, `compile/compile_metadata.json`, fresh `compile/Mql5Bot.ex5` | non-zero exit; any error/warning |
| 2 | Export SymbolSpec | run `Mql5BotExportSymbolSpec.mq5` on the real terminal/broker | `symbolspec/symbolspec.json` | export missing fields; synthetic spec |
| 3 | Prepare frozen Golds | verify `artifacts/owner_mt5_gate/frozen_inputs.json` hashes match | frozen fixtures present, hashes match | any hash mismatch ⇒ STOP |
| 4 | Gold #1/#2 M1 leg | `run_mt5_backtest.py run` at model M1-OHLC | `gold1/m1_ohlc.htm`, `gold2/m1_ohlc.htm` (+ parsed) | missing raw report |
| 5 | Gold #1/#2 Every Tick | `run` at model Every Tick | `gold1/every_tick.htm`, `gold2/every_tick.htm` (+ parsed) | missing raw report |
| 6 | Gold #1/#2 Real Ticks | `run` at model Every-tick-real-ticks | `gold1/real_ticks.htm`, `gold2/real_ticks.htm` (+ parsed) + real-tick journal | no broker ticks ⇒ UNAVAILABLE, recorded |
| 7 | Safety runtime tests | follow `docs/MT5_ROUNDTRIP.md` §Owner runtime safety procedures | `safety/*.json` + one bound evidence file each | any missing raw artifact |
| 8 | Reconciliation | `certify_strategy.py --reconciliation` | `reconciliation/gold1.json`, `reconciliation/gold2.json` | divergence ⇒ FIRST_DIVERGENT EVENT |
| 9 | Archive | `owner_evidence_bind.py manifest <evidence-dir>` | `archive_manifest.json` binding every file | manifest not last / not complete |
| 10 | Verify | `python tools/verify_owner_mt5_gate.py <evidence-dir> --repo . --out report.json` | `report.json` + verdict | exit 1 ⇒ return directory AS-IS |

Step 10 is the ONLY place a verdict is assigned. Steps 1–9 only
produce bound artifacts.

# OWNER MT5 EXECUTION PACKAGE (OWNER MT5 EXECUTION GATE)

One directory, one attempt, raw artifacts only. This package defines
EXACTLY what the owner executes and returns. The canonical procedure is
the TEN-step protocol in `docs/MT5_ROUNDTRIP.md` (single source of
truth); this directory is its artifact scaffold.

**Certification status while this package is unexecuted:**
`REALITY_GATE_BLOCKED` · `PRODUCTION = NOT_READY`. No screenshot is
evidence; no text summary substitutes a raw artifact.

## Machine

Windows · MetaTrader 5 (broker build) · MetaEditor 5 · PowerShell.

## Frozen inputs (verify BEFORE any run — §2)

`frozen_inputs.json` (generated mechanically from the frozen manifests)
lists every hash the owner must reproduce locally:

* Gold #1 fixture / manifest / expected-execution SHA-256 + dataset hash
* Gold #2 fixture / manifest / expected-execution SHA-256 + dataset hash
  + the full six-artifact provenance chain
  (`GOLD_2_RECONSTRUCTED_NEW_PROVENANCE` — never regenerated, never
  enlarged; 56 trades IS the semantic contract)
* the exact source commit to compile

Any hash mismatch ⇒ STOP. Do not regenerate, do not re-download,
re-clone the pinned commit and re-verify. The owner executes the exact
frozen artifacts — nothing else.

## The 19 returned artifact groups — exact paths in §Evidence directory contract

The verifier (`tools/verify_owner_mt5_gate.py`) requires exactly ONE
layout: 29 individual files. They correspond to these 19 return groups:

| # | artifact group | exact path(s) in the evidence directory |
|---|---|---|
| 1 | strict compile log | `compile/compile.log` |
| 2 | fresh EX5 + SHA-256 | `compile/Mql5Bot.ex5` (hash recorded in metadata) |
| 3 | compiler/terminal metadata | `compile/compile_metadata.json` (six provenance fields) |
| 4 | actual broker SymbolSpec | `symbolspec/symbolspec.json` |
| 5–7 | Gold #1 M1 / Every Tick / real-tick reports | `gold1/m1_ohlc.htm`, `gold1/every_tick.htm`, `gold1/real_ticks.htm` |
| 8–10 | Gold #2 M1 / Every Tick / real-tick reports | `gold2/m1_ohlc.htm`, `gold2/every_tick.htm`, `gold2/real_ticks.htm` |
| 11 | parsed reports | `parsed/gold1_m1_ohlc.json`, `parsed/gold1_every_tick.json`, `parsed/gold1_real_ticks.json`, `parsed/gold2_m1_ohlc.json`, `parsed/gold2_every_tick.json`, `parsed/gold2_real_ticks.json` |
| 12 | Gold #1 reconciliation | `reconciliation/gold1.json` (bindings + events) |
| 13 | Gold #2 reconciliation | `reconciliation/gold2.json` (bindings + events) |
| 14 | real-tick coverage | `real_tick_coverage.json` |
| 15 | safety artifacts | `safety/kill_switch.json`, `safety/risk_veto.json`, `safety/meta_reduce.json`, `safety/sl_verify.json`, `safety/lost_response.json`, `safety/restart.json` |
| 16 | netting artifact | `safety/netting.json` |
| 17 | hedging artifact | `safety/hedging.json` |
| 18 | environment metadata | `environment.json` |
| 19 | archive manifest | `archive_manifest.json` |

The machine-readable authority is `LAYOUT` in
`python/mql5bot/owner_gate.py` — this table is pinned to it by
`tests/test_docs_contract.py`. No screenshots as primary evidence:
every raw evidence field must bind a journal/log/report artifact.

## Compiler provenance (§6) — the six mandatory fields

`compile_metadata.json` must contain (raw evidence, not prose):

| field | source |
|---|---|
| `SOURCE_COMMIT` | `git rev-parse HEAD` in the owner's clone (must equal `frozen_inputs.json`) |
| `COMPILER_VERSION` | MetaEditor Help → About (exact build) |
| `TERMINAL_BUILD` | terminal Help → About (exact build) |
| `EX5_SHA256` | `Get-FileHash <each fresh .ex5> -Algorithm SHA256` |
| `COMPILE_TIMESTAMP` | UTC ISO-8601 of the compile run |
| `COMPILER_LOG_SHA256` | `Get-FileHash <compile log> -Algorithm SHA256` |

Reject and re-compile: a stale or cached `.ex5`, a missing log, a
warning-bearing build (`-Strict` exit ≠ 0), an unknown source revision.
"Compiled successfully" text without raw evidence is worthless.

## SymbolSpec comparison classes (§8)

Compare the actual export against the frozen gold assumptions
(`broker_symbol_parity.py` FIELD_MAP). Every field gets EXACTLY one
class:

* `EXACT_MATCH` — identical value;
* `SEMANTICALLY_COMPATIBLE` — differs without changing any decision
  (e.g. display rounding only) — justification recorded;
* `DECISION_CHANGING_MISMATCH` — sizing / stop constraint / volume grid
  / margin / execution differs ⇒ **STOP**; do NOT silently rewrite
  Gold #1/#2; report the mismatch as the evidence;
* `UNSUPPORTED_BROKER_DIFFERENCE` — broker cannot express the field —
  recorded, leg constrained accordingly.

## Tester model identity (§9) — the triad, per leg

Every leg records: `requested_model` (command line), `actual_model`
(report's Model line — parsed, never copied), and the terminal's model
identifier from the tester journal. Command line alone is never proof
of the model actually used.

## Real-tick coverage (§12/§13)

Official MetaTrader semantics: missing tick history makes the tester
GENERATE ticks in Every-tick mode. Therefore:

* `REAL_TICK_COVERAGE_FULL` — only with positive evidence that real
  ticks covered the WHOLE requested interval (journal/data evidence);
* `REAL_TICK_COVERAGE_PARTIAL` — any fallback interval (list them);
* `REAL_TICK_COVERAGE_UNKNOWN` — coverage cannot be proven. **This is
  the default.** Selecting the mode is NOT evidence of FULL.

## First-divergence procedure (§16/§17)

If reconciliation fails: locate the FIRST divergent bar/tick — not the
final PnL. Record Python state, MQL5 state, inputs, indicator values,
strategy/session/Meta/Risk/execution state at that event; classify with
the closed 14-class taxonomy; determine the causal source (data
modeling / indicator init / warmup / numeric representation / session
time / broker spec / normalization / Bid-Ask / spread / tick ordering /
latency / tester model) BEFORE any patch. Neither side is patched
blindly; a gold artifact is NEVER rewritten because MT5 disagrees —
the discrepancy IS the evidence (§18/§19).

## Stale-artifact defense (§29)

Every attack fails closed: old EX5 + new source, new EX5 + old config,
old report + new fixture, wrong broker SymbolSpec / symbol / timeframe /
model / source commit. Enforcement: compile.ps1 freshness + `-Strict`
(§5), `frozen_inputs.json` pre-flight hash check (§2), report model
line vs requested model (§9), manifest bindings in
`certification_manifest.json`, `report_gate` (empty/edited reports
refused), NOT_EXECUTABLE seam, and the red-team battery
(`tests/test_certify_redteam.py`). Any mismatch invalidates the
corresponding certification leg.

## Safety runtime tests (§20–§22) — after the gold runs

Kill Switch (zero new orders), Risk veto (order rejected), Meta reduce
(size ≤ Risk-approved), SL verify→modify→re-verify, lost-response
adoption-before-retry, restart matrix (pending/retry/open/allocation),
netting proof, hedging proof — exact procedures in
`docs/MT5_ROUNDTRIP.md` §Owner runtime safety procedures. If the
account type cannot exercise hedging: record
`BLOCKED_OWNER_ENVIRONMENT`, never a fabricated pass.

## Evidence directory contract (§6) — exactly one layout

The owner returns ONE directory with exactly these deterministic file
names. Missing mandatory files, duplicates, ambiguous names, stale
files, wrong-source-commit files and edited reports are all rejected by
the verifier — never silently repaired.

```
<evidence-dir>/
  compile/compile.log                      # verbatim MetaEditor output
  compile/compile_metadata.json            # the six provenance fields
  compile/Mql5Bot.ex5                      # fresh binary, hashed
  symbolspec/symbolspec.json               # full broker SymbolSpec dump
  gold1/m1_ohlc.htm  gold1/every_tick.htm  gold1/real_ticks.htm
  gold2/m1_ohlc.htm  gold2/every_tick.htm  gold2/real_ticks.htm
  parsed/gold1_m1_ohlc.json  parsed/gold1_every_tick.json
  parsed/gold1_real_ticks.json  parsed/gold2_m1_ohlc.json
  parsed/gold2_every_tick.json  parsed/gold2_real_ticks.json
  reconciliation/gold1.json                # bindings + per-event states
  reconciliation/gold2.json
  real_tick_coverage.json                  # requested/actual model+range
  safety/kill_switch.json  safety/risk_veto.json  safety/meta_reduce.json
  safety/sl_verify.json  safety/lost_response.json  safety/restart.json
  safety/netting.json  safety/hedging.json # raw evidence each
  environment.json
  archive_manifest.json                    # full identity chain
```

### File-bound evidence — a path string is NOT evidence

* Real-tick coverage evidence and every safety `raw_evidence` field is
  a binding object `{"path": <relative path>, "sha256": <hash>}`.
* The bound file must exist INSIDE the evidence directory (path
  escapes are rejected) and its bytes must match the recorded hash.
* `environment.json` must carry `os`, `terminal_build`, `broker`,
  `server`, `account_mode`, `symbol`, `timezone`, `run_timestamp` and
  must not contradict the owner SymbolSpec.
* `archive_manifest.json` binds EVERY file in the directory by SHA-256
  plus the frozen source/fixture identities; build it LAST with:
  `python tools/owner_evidence_bind.py manifest <evidence-dir>`.
* Compute any single binding with:
  `python tools/owner_evidence_bind.py bind <file> --root <evidence-dir>`.
* The owner NEVER hand-types a hash; every hash is generated by tooling.

Every artifact is classified by the verifier into exactly one of:
`MISSING / PRESENT_UNVERIFIED / VALID / INVALID / STALE / MISMATCHED /
PENDING_OWNER` — never a single boolean.

## Consuming the evidence — one command (§32)

```
python tools/verify_owner_mt5_gate.py <evidence-dir> --repo . [--out report.json]
```

The command mechanically answers completeness, freshness, identity
binding (source commit by hash, never branch name), tester-model
identity, real-tick coverage, Gold #1/#2 reconciliation, the FIRST
divergence and its deterministic mismatch class, safety/netting/hedging
evidence, and assigns one explainable verdict:
`MT5_VALIDATED` or one of `NOT_VERIFIED_MISSING_MT5_EVIDENCE /
NOT_VERIFIED_RECONCILIATION_MISSING / NOT_VERIFIED_ARTIFACT_MISMATCH /
NOT_VERIFIED_REAL_TICK_COVERAGE_UNKNOWN`. Exit code is nonzero on every
negative verdict; missing, stale, wrong, partial or simulated evidence
can never become a positive verdict.

## Hard rules

* **No live capital** — Strategy Tester + controlled demo + owner
  environment only; no automated capital activation (§23).
* **Gold ≠ empirical** — the gold runs are semantic parity tests; the
  100-trade empirical regime ladder is a SEPARATE lane and is never
  satisfied by gold fixtures (§24).
* **Demo never auto-starts** — demo requires runtime validation + clean
  reconciliation + safety tests + confirmed SymbolSpec + operator
  review (§26).
* **Forbidden claims** unless directly evidenced: "works on MT5",
  "broker validated", "production ready", "safe for live", "real ticks
  passed", "profitable", "live validated" (§33). Use exact evidence
  terminology.
