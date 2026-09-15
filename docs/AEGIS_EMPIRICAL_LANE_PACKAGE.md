# AEGIS — EMPIRICAL LANE OWNER PACKAGE DEFINITION (prepared, NOT executed)

Status: **PENDING_OWNER / NOT_EXECUTED.** This document DEFINES the
empirical-lane owner package. It is preparation only: execution happens
after the Gold MT5 lane returns runtime evidence and passes
reconciliation. Until then no empirical run may be claimed, and this
file must not be read as evidence of any kind.

## Lane separation (why this exists)

* **Gold lane** = semantic parity. Gold #1 (22 trades) and Gold #2
  (56 trades, `GOLD_2_RECONSTRUCTED_NEW_PROVENANCE`) prove the Python
  engine and the MQL5 engine decide the same things on identical data.
  Gold fixtures are NEVER regenerated, enlarged or tuned; a gold pass
  never produces `MT5_VALIDATED` and never substitutes for this lane.
* **Empirical lane** = robustness on unseen data: does the strategy
  behave consistently across regimes, models and costs? The 100-trade
  per-regime minimum belongs HERE, never to the gold lane.

One evidence class may never impersonate another:
`SOFTWARE_PASS !⇒ MT5_VALIDATED`, gold pass `!⇒` empirical
qualification, empirical pass without reconciliation `!⇒ VERIFIED`.

## Package definition (exact, frozen at execution time)

| Item | Definition |
|------|------------|
| Symbols | EURUSD primary; one cross (GBPUSD) as out-of-sample symbol |
| History | last 24 calendar months ending at the execution date; M1 data |
| Timeframe | M1 execution timeframe (matching the gold runs) |
| Regime partition | trend-up / trend-down / range / high-volatility; partition rules fixed BEFORE runs and recorded in the manifest |
| Models | full ladder: `1 minute OHLC` → `Every tick` → `Every tick based on real ticks` per symbol×regime |
| Minimum trades | ≥ 100 trades per regime per model before that cell counts |
| Costs | broker spread recorded per session; slippage model: real fills from tester reports only, never simulated |
| Real ticks | same coverage rules as the gold lane (`REAL_TICK_COVERAGE_FULL` requires positive whole-interval proof; silent per-bar fallback keeps the status `PARTIAL`/`UNKNOWN`) |
| Degradation | walk-forward: train window decisions replayed on the following hold-out window; degradation measured per regime |
| Statistical gates | per-regime trade count, win/loss distribution, max drawdown, expectancy — reported raw; NO optimization of thresholds after seeing results |
| Reconciliation | every empirical run reconciles against the Python engine like the golds; first divergence → STOP + causal chain before anything continues |

## Execution preconditions (fail-closed)

1. Gold lane returned owner evidence and the verifier assigned
   `MT5_VALIDATED` on the frozen anchor.
2. Reconciliation clean on both golds.
3. Safety runtime tests returned with raw evidence (screenshots alone
   never qualify).
4. Broker SymbolSpec confirmed with no `DECISION_CHANGING_MISMATCH`.
5. Human approval to spend owner compute time on the empirical ladder.

Any precondition missing ⇒ this package stays `PENDING_OWNER`.

## Forbidden

* No tuning, re-freezing or threshold change after seeing results.
* No mixing empirical results into gold verdicts or vice versa.
* No claim of profitability, robustness or "validated" from this
  definition alone — it is a plan, not evidence.
