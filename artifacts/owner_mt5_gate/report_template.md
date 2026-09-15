# OWNER MT5 EXECUTION REPORT (template — §32)

The owner (or the agent assisting the owner) fills this template from
the RAW artifacts in this directory. Every field comes from an
artifact; nothing is inferred. Forbidden claims (§33): "works on MT5",
"broker validated", "production ready", "safe for live", "real ticks
passed", "profitable", "live validated" — unless directly evidenced by
a named artifact.

## Environment

* OS:
* MT5 version/build:
* Tester build:
* broker/server:
* account mode (netting/hedging):
* symbol:
* timeframe: M1

## Compile

* source commit: (must equal `frozen_inputs.json`)
* compiler version:
* EX5 SHA-256 (per target):
* compiler result: (0 errors / 0 warnings, counted from the log)
* compile timestamp (UTC):
* compiler log SHA-256:

## SymbolSpec

* export result: (path + SHA-256)
* divergence classification (per field): EXACT_MATCH /
  SEMANTICALLY_COMPATIBLE / DECISION_CHANGING_MISMATCH /
  UNSUPPORTED_BROKER_DIFFERENCE
* action taken on any DECISION_CHANGING_MISMATCH: (STOP required)

## Gold #1

| Model | Status | Trades | First Divergence | Reconciliation |
|---|---|---|---|---|
| M1 OHLC | | | | |
| Every Tick | | | | |
| Every Tick based on real ticks | | | | |

## Gold #2 (`GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`, frozen, 56-trade semantic contract)

| Model | Status | Trades | First Divergence | Reconciliation |
|---|---|---|---|---|
| M1 OHLC | | | | |
| Every Tick | | | | |
| Every Tick based on real ticks | | | | |

## Real-Tick Coverage

* requested model:
* actual model (from report):
* coverage: REAL_TICK_COVERAGE_FULL / _PARTIAL / _UNKNOWN
* fallback intervals:
* broker tick availability evidence:

## Safety Runtime

| Test | Status | Evidence |
|---|---|---|
| Kill Switch | | |
| Risk veto | | |
| Meta reduce-only | | |
| SL verify→modify→re-verify | | |
| Lost response adoption | | |
| Restart matrix | | |

## Netting/Hedging

| Test | Status | Evidence |
|---|---|---|
| Netting | | |
| Hedging (or BLOCKED_OWNER_ENVIRONMENT) | | |

## Mismatch Triage

For each mismatch:

* class: (one of the closed 14-class taxonomy)
* first divergent event: (bar/tick)
* cause: (proven, not assumed)
* financial impact: (decision-changing? Y/N)
* fix required: (Python / MQL5 / contract / data adapter / broker
  mapping / none)

## Certification

Exactly one (assigned by `tools/certify_strategy.py --reconciliation`):

* [ ] `MT5_VALIDATED`
* [ ] `REALITY_GATE_BLOCKED`
* [ ] `REALITY_GATE_INCOMPLETE`
