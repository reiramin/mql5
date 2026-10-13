# MT5 Setup and Operation (Owner Runbook)

This is the owner-side operating manual. The certification protocol is the
automated gate, `tools/owner_gate.ps1` ([OWNER_GATE.md](OWNER_GATE.md)),
which runs the steps below itself; the frozen artifact package is
`artifacts/owner_mt5_gate/`. The manual ten-step protocol in
`MT5_ROUNDTRIP.md` is historical. Known gate failure modes and their
remedies are in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

> **The bot trades only while MetaTrader 5 is running and connected.** If
> you close the terminal or the PC sleeps, it stops — there is no
> background service that keeps trading. For unattended operation you need
> an always-on host; the recommended split (MT5 on a small Windows host,
> the Python services on a cheap Linux host) and its restart-on-boot steps
> are in [DEPLOYMENT.md](DEPLOYMENT.md). That deployment has **never been
> deployed or drilled** — it is a procedure, not a proven configuration.
> What is certified (gate_run59): MT5 execution-parity and safety
> certificate, bar models, no real-tick claim, no profitability claim — see
> the README "Certification status".

## Before first compile

| Requirement | Detail |
|---|---|
| Terminal | MetaTrader 5 from your broker (record the build number) |
| MetaEditor | bundled with the terminal (open with F4) |
| Repository | checkout of `main` at the pinned commit; do NOT edit files after checkout |
| Tools | PowerShell (Windows built-in), Python 3.10+ for the verifier |
| Account | **demo account** for every step of certification — never live money |

Verify the frozen inputs before any run:

```powershell
type artifacts\owner_mt5_gate\frozen_inputs.json
```

and confirm the source commit matches your checkout
(`git rev-parse HEAD`). Any hash mismatch ⇒ STOP; re-clone the pinned
commit.

## Compilation (strict gate)

```powershell
powershell -ExecutionPolicy Bypass -File tools\compile.ps1 -Strict
```

Expected:

- exit code 0
- **0 errors, 0 warnings** (the `-Strict` gate fails on any warning)
- `compile/compile.log` — the verbatim MetaEditor output
- `compile/compile_metadata.json` — six provenance fields:
  `SOURCE_COMMIT`, `COMPILER_VERSION`, `TERMINAL_BUILD`, `EX5_SHA256`,
  `COMPILE_TIMESTAMP`, `COMPILER_LOG_SHA256`
- `compile/Mql5Bot.ex5` — a fresh binary whose bytes match the
  recorded hash

If compilation fails: STOP. Record the exact error (file, line,
column, compiler build) and the raw log; classify
(`COMPILE_ERROR` / `COMPILE_WARNING` / `TOOLCHAIN_ERROR` / `PATH_ERROR`
/ `ENVIRONMENT_ERROR`) before considering any source change. "The
editor opened" is not compile evidence; only the strict gate counts.

## EA installation

Automated:

```powershell
python scripts\install_mql5.py
```

Manual (if detection fails):

1. Copy `mql5/Include/Mql5Bot/` → `<MT5 Data Folder>/MQL5/Include/Mql5Bot/`
2. Copy `mql5/Experts/Mql5Bot/Mql5Bot.mq5` → `<MT5 Data Folder>/MQL5/Experts/Mql5Bot/`
3. Refresh the Navigator in MT5; compile from MetaEditor (F7) — the
   strict script remains the evidence gate.

Attach the EA to a chart of the certification symbol and select a
preset/inputs. For telemetry, allow the collector URL via
**Tools → Options → Expert Advisors → Allow WebRequest for listed URL**.

## What the EA can execute

1. The five built-in engines — `ema_crossover`, `rsi_reversal`,
   `donchian_breakout`, `bollinger_reversal`, `macd_momentum` — chosen with
   the `InpStrategy` input.
2. A certified DSL bundle named by `InpDslBundleFile` (read from the
   terminal's `MQL5\Files` or the common files folder). The loader is
   fail-closed: the bundle hash, `spec_hash` and `semantic_hash` must
   re-derive, only EMA, RSI, ATR, DONCHIAN, HIGHEST and LOWEST are
   accepted, and the bundle's market must equal the chart. The gate's gold
   legs run this way.

**The Python Factory / DSL / 71-indicator research universe does NOT mean
arbitrary generated strategies can execute in the EA.** A bundle using any
other kind is refused at OnInit; it stays on the research surface until a
real owner validation exists for it (BLOCKED_OWNER_ENVIRONMENT). Do not
improvise a workaround.

## Strategy Tester — three separate evidence layers

| Model | What it is | Evidence meaning |
|---|---|---|
| **1 minute OHLC** | decisions on M1 bars only | coarsest model; baseline leg |
| **Every Tick** | ticks *generated* from M1 bars, fixed spread | tick-resolution semantics, synthetic ticks |
| **Every Tick based on real ticks** | broker tick history where available | closest to live — **with silent per-bar fallback** |

Official MT5 semantics: in real-tick mode the tester silently falls
back to generated ticks for any minute bar without tick history.
Therefore:

- selecting the real-tick option is NOT coverage proof;
- `REAL_TICK_COVERAGE_FULL` requires positive whole-interval proof from
  the journal/report;
- any fallback ⇒ `REAL_TICK_COVERAGE_PARTIAL`; unprovable ⇒
  `REAL_TICK_COVERAGE_UNKNOWN`;
- results from one model can never be substituted for another.

The model identity triad must agree for every leg: REQUESTED (your
config) vs REPORT (the report's Model line) vs RUNTIME/JOURNAL. Any
disagreement ⇒ `MODEL_IDENTITY_MISMATCH` — stop normal certification.

## SymbolSpec export

Run the actual exporter (`Mql5BotExportSymbolSpec.mq5`) on the real
terminal/broker — never the synthetic parity spec. The artifact lands
in the evidence directory as `symbolspec/symbolspec.json` (broker,
server, account mode, symbol, point, tick size/value, contract size,
volume min/max/step/limit, stops/freeze levels, trade/filling/
expiration modes, margin mode, currencies, timestamp, terminal build).

The exporter writes that file as UTF-8 with no BOM (its `FileOpen` pins the
`CP_UTF8` code page), which is exactly what
`tools/broker_symbol_parity.py` decodes: never re-save an export through an
editor that adds a BOM or converts it to a local ANSI code page, and never
"repair" a rejected export by hand — re-run the exporter instead.

Comparison classes per field: `EXACT_MATCH` /
`SEMANTICALLY_COMPATIBLE` / `DECISION_CHANGING_MISMATCH` (STOP — never
rewrite the gold fixtures to fit the broker) /
`UNSUPPORTED_BROKER_DIFFERENCE`.

## Gold runs

Run frozen Gold #1 (16 trades) and Gold #2 (56 trades,
`GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`) on all three models with the
frozen config/dataset. Gold #2 is valid AT 56 TRADES — the 100-trade
minimum belongs to the separate empirical lane and must never be
applied to golds. If MT5 disagrees with a gold: the disagreement is
evidence. Capture the FIRST divergent event (bar/tick, field, both
values, state snapshot) — never compare only final PnL. Never edit a
fixture, expected execution, Meta schedule or strategy parameter to
make reality match.

## Evidence binding and verification

Bind every evidence file (the owner never hand-types a hash):

```bash
python tools/owner_evidence_bind.py bind <file> --root <evidence-dir>
python tools/owner_evidence_bind.py manifest <evidence-dir>   # LAST
```

Then verify:

```bash
python tools/verify_owner_mt5_gate.py <evidence-dir> --repo . --out report.json
```

Exit 0 = positive verdict (`MT5_VALIDATED` or `MT5_VALIDATED_BAR_MODELS`;
`MT5_VALIDATED_PARTIAL_SCOPE` is never positive). Exit 1 = negative with the
exact reasons — return the directory AS-IS; do not repair artifacts.
Exit 2 = usage/configuration error.

## Safety exercises

The gate runs all eight itself. Kill Switch, Risk veto, Meta reduce, SL
verification and lost response are Strategy Tester legs in stage 8
(docs/SAFETY_8A_8D_PLAN.md); restart, netting and hedging run on demo
accounts in stage 7 with `-DemoSafety` (docs/SAFETY_DEMO_PLAN.md). Each
result requires action / initial state / resulting state / observed result
/ a bound raw-evidence artifact, and is VALID only when the observed result
equals the pinned expected one.
Screenshots alone and prose ("passed") are rejected by the verifier.
If the account type cannot exercise hedging: record
`BLOCKED_OWNER_ENVIRONMENT`, not PASS.

## Hard rules

1. No live capital anywhere in this workflow.
2. Gold ≠ empirical; never mix lanes or verdicts.
3. Demo never auto-starts: MT5 validation + clean reconciliation +
   safety evidence + confirmed SymbolSpec + human approval first.
4. Forbidden claims without direct evidence: "works on MT5", "broker
   validated", "production ready", "safe for live", "real ticks
   passed", "profitable", "live validated".
