# Real-tick certification protocol (plan Phase F)

`mql5bot.certify` + `tools/certify_strategy.py`. One idea: a result is
VERIFIED only through the graded data ladder on the same EA and the
same terminal, per regime — never through a single OHLC print.

**Canonical owner protocol.** The ladder below runs inside the canonical
TEN-step owner sequence defined in `docs/MT5_ROUNDTRIP.md` (single
source of truth: strict compile → compiler-log verification → SymbolSpec
export → fixture/data preparation → M1-OHLC baseline leg → Every-Tick
leg → Every-Tick-real-ticks leg → Python↔MT5 comparison incl. the
kill-switch seam and restart sub-checks → immutable archive/manifest →
certification-state assignment). The data-grade ladder, regime sample
and gates of this document are the CONTENT of canonical steps 5–8 and
the input to step 10; they are not an independent protocol. Any
shortened checklist must label itself a SHORTCUT and map its items onto
those canonical step numbers.

## Two certification lanes (binding — FINAL CERTIFICATION MODEL LOCK)

The repository distinguishes TWO lanes that must never be conflated and
never substitute for each other:

### GOLD / SEMANTIC lane

* Purpose: cross-runtime CORRECTNESS — signal parity, sizing parity,
  state transitions, barrier semantics, session semantics, Meta/Risk
  seams — on a controlled deterministic fixture.
* Artifacts: Gold #1 (`artifacts/gold/`) and Gold #2
  (`artifacts/gold_2/`, `GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`, frozen).
* Acceptance question: "does actual MQL5 execution reproduce the
  frozen semantic fixture?" — field-by-field exact reconciliation
  (signal, direction, entry, volume, SL, TP, exit, exit reason,
  session, Meta, Risk, state) where the contract says exact.
* **No minimum trade count.** Gold #2 is valid with its 56 trades;
  enlarging it to satisfy an empirical threshold is forbidden.
* Dimension: `GOLD_SEMANTIC_PASS` (`mql5bot.status.gold_semantic_status`).

### EMPIRICAL / CERTIFICATION lane

* Purpose: does the strategy maintain acceptable execution and
  statistical behavior across REQUIRED real-data regimes — the regime ×
  model ladder below, on broker data.
* Gates: the **100-trade minimum per required leg**, spread floor,
  slippage tiers, degradation reported as observed — these gates belong
  HERE, never to the gold lane.
* Dimension: the MT5 ladder verdict (`VERIFIED` only from a real
  terminal pass WITH recorded reconciliation — `reconciliation_ok`).

Hard rules: a gold pass can NEVER produce `MT5_VALIDATED` or
`VERIFIED`; a 100-trade empirical pass can NEVER produce
`GOLD_SEMANTIC_PASS`; `VERIFIED` requires BOTH the empirical ladder
pass AND the recorded Python↔MT5 reconciliation (fail-closed in
`certify.run_certification`).

## Canonical evidence layers (A–F, binding — no layer substitutes another)

| Layer | Name | Evidence |
|---|---|---|
| A | SOFTWARE | unit tests, property tests, provenance chains, source audits, certification-tooling tests |
| B | GOLD SEMANTICS | Gold #1, Gold #2, Python↔DSL parity, Python↔MQL5 source parity |
| C | MT5 RUNTIME | actual compile, actual `.ex5`, actual broker SymbolSpec, actual tester reports, actual real-tick run |
| D | EMPIRICAL | large sample, regime × model ladder, spread/slippage, real ticks, degradation, the required minimum trade count |
| E | DEMO | actual demo-account observation (separate phase, never automatic after tester success) |
| F | LIVE | actual capital (decision only after E and explicit human approval) |

Layer A+B are PROVEN locally; C+D are BLOCKED_OWNER_ENVIRONMENT; E+F
are not begun and never begin automatically.

## Data-grade ladder (tester models, per regime)

| Grade | MT5 model | Meaning |
|---|---|---|
| M1 OHLC | 1 | baseline built from 1-minute bars |
| Every tick | 0 | synthetic ticks interpolated from M1 |
| Every tick on real ticks | 3 | real-tick tick structure |
| Real ticks | 4 | broker tick history |

Every required leg of the ladder must run and pass its gates for a
VERIFIED verdict. Without an MT5 terminal host the legs cannot run and
the verdict is NOT VERIFIED with the reason — nothing is guessed.

## Regime sample (multi-regime, incl. bear and crash)

| regime | window | character |
|---|---|---|
| bear_2022 | 2022.01.01–2022.06.30 | Fed-hike bear trend |
| crash_2020 | 2020.02.20–2020.04.30 | COVID crash + whipsaw recovery |
| trend_2021 | 2021.01.01–2021.06.30 | sustained trend |
| range_2023 | 2023.01.01–2023.06.30 | choppy range |

## Gates and explicit reports

- **100-trade minimum** per required leg (and asserted in the verdict)
  — EMPIRICAL lane only; the gold fixtures are semantic correctness
  tests and are exempt by design (see §Two certification lanes).
- **Spread floor**: the modelled average spread vs the configured floor,
  in pips; a missing average fails loudly (floors are never assumed).
- **Slippage surcharge tiers 0.5–3.0 pips**: applied analytically to the
  canonical Python TRUTH M1-OHLC leg (per side, tick-valued) and
  reported per tier.
- **OHLC-vs-tick degradation**: every tick grade vs its own M1-OHLC
  baseline per regime — the OBSERVED relative net-profit change in
  percent, reported as measured (10%, 20%, 60%, 80%: whatever the run
  actually shows).  The historical **30–50%** band is INFORMATIVE ONLY:
  it is stated alongside the observation (`inside_band` flag) and is
  NEVER a pass/fail requirement — a valid strategy must not be rejected
  for landing outside an arbitrary range.  Degradation never gates the
  verdict; it is a finding on every leg that ran, never hidden, never
  silently waived.  Undefined baselines (non-positive base net profit)
  are reported as `None`, not guessed.  Treating the band as a hard
  gate would require new empirical evidence, documented as a protocol
  revision.
- **Python cross-check leg**: an independent canonical TRUTH-engine M1
  run bound to the same (strategy, params) manifest; recorded, never
  gates the verdict.

## Usage

```bash
# config.json mirrors mql5bot.certify.CertifyConfig
python tools/certify_strategy.py --config config.json --out report.md \
    [--data ohlc.parquet]     # optional python cross-check leg
```

Exit code 0 = VERIFIED; 1 = anything else (including every NOT VERIFIED
case). The MT5 runner binds only on Windows terminal hosts
(`mt5tester.RunSettings`); everywhere else every tester leg is reported
as not run.

## Honesty rules

- `VERIFIED` / `NOT VERIFIED` are derived only from leg outcomes above
  them in the report; never typed by hand, never carried over.
- Backtests — Python or tester — are research evidence, not a promise
  of live profit (README "Research evidence, not promises").

## Certification scope surfaces (binding)

Certification claims must always name WHICH surface they cover. The
repository distinguishes exactly three surfaces; conflating them (e.g.
"71 indicator kinds = MT5 certified") is a documentation defect.

1. **Execution-certified surface** — the concrete MQL5 EA and its five
   built-in strategy engines (`STRAT_EMA_CROSSOVER`,
   `STRAT_RSI_REVERSAL`, `STRAT_DONCHIAN_BREAKOUT`,
   `STRAT_BOLLINGER_REVERSAL`, `STRAT_MACD_MOMENTUM`) plus the
   EA-side seams (session, risk, kill switch, SL guard, meta
   allocation, retry/adoption). This is the ONLY surface that can ever
   reach `VERIFIED` through the canonical TEN-step owner protocol
   (`docs/MT5_ROUNDTRIP.md`), and every `VERIFIED` claim must cite
   legs run on this surface.
2. **Research-certified surface** — the Python/DSL stack: the 71-kind
   indicator universe, the DSL runtime, the backtest/portfolio engine,
   the factory lifecycle, Gold #1 and Gold #2
   (`GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`). These are PROVEN sandbox
   semantics (deterministic, replay-verified, parity-proven between
   the Python reference and the DSL runtime). PROVEN here NEVER means
   MT5-validated; it is a separate evidence class.
3. **Owner-pending surface** — MQL5 parity of new/extended indicator
   kinds and any generated-strategy execution path beyond the five
   built-ins. Status: BLOCKED_OWNER_ENVIRONMENT until the owner leg
   exists. Unknown/unsupported kinds FAIL CLOSED at three layers:
   (a) the DSL schema rejects unknown indicators (`SchemaInvalid`,
   pinned by `tests/test_dsl_core.py`); (b) the EA exposes only the
   five-engine enum — there is no DSL interpreter in the MQL5 tree, so
   an unsupported kind is structurally unable to enter execution;
   (c) the factory lifecycle refuses unevidenced promotions
   (`lifecycle.py`: every promotion requires named evidence kinds).

Generated-strategy trace: Factory intake → DSL spec (schema-gated) →
Python research execution + evidence gates → promotion ladder
(OOS_SURVIVOR → SHADOW → DEMO → LIVE_SMALL → LIVE, evidence-gated,
human approvals) → MQL5 representation exists ONLY for the five
built-in engines; anything else stays research-only. Nothing in the
Factory, Research, ML, LLM, or Meta layers can send an order
(source-scanned; red-team tests enforce the boundary).

## Certification identity (Phase 3 hardening — one-look registry)

The OOS one-look registry (`mql5bot.pipeline.OosRegistry`, schema 2) keys
every certification on the EXACT identity
(`mql5bot.pipeline.OosIdentity`):

| Field | Source |
|---|---|
| `dataset_content_digest` | content digest of the OOS frame (always; an explicit `dataset_tag` is carried but never the anchor) |
| `strategy` / `strategy_version` | registry declaration |
| `engine` / `engine_version` | `truth` + `mql5bot.versions.ENGINE_VERSION` |
| `cost_model_version` / `cost_config_digest` | `mql5bot.versions.COST_MODEL_VERSION` + content digest of the cost kwargs |
| `feature_version` | `mql5bot.versions.FEATURE_VERSION` (signal/indicator semantics) |
| `certification_protocol_version` | `mql5bot.versions.CERTIFICATION_PROTOCOL_VERSION` |

Enforcement is intentionally STRONGER than "one look per
(dataset_version, strategy)":

1. the exact identity is refused on a second look (one look, recorded,
   forever);
2. the same (dataset content, strategy) pair is refused under ANY
   identity — bumping a strategy version, cost model, feature version or
   protocol version cannot mint a fresh look on the same data; the
   violation names exactly which identity fields changed;
3. a tag change on the same content is refused (tags never weaken the
   identity).

Every recorded entry carries its full identity, the honest status model
(`EMPIRICAL_VALIDATION_PENDING`, MT5 `NOT VERIFIED`) and the complete
cost configuration, so a certification is reproducible and auditable
from the registry alone.

### Failure/recovery policy (explicit)

* A REFUSED look (second attempt on a used slice) raises before any
  run and records nothing.
* An attempt whose RUN FAILS (engine/terminal exception) records
  nothing and consumes NO look: no result was observed, so no knowledge
  leaked; a retry after fixing the cause is permitted
  (`tests/test_oos_registry.py::test_failed_attempt_consumes_nothing_
  retry_permitted_once_locked`).  This grants no parameter-shopping
  latitude: the FIRST successful look locks the (dataset content,
  strategy) pair forever, whatever attempts preceded it.
* No other recovery path exists.  There is no "re-certify", "reset" or
  "force" operation on the registry, and none may be added without a
  documented protocol revision.
