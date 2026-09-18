# EXECUTION STRESS — OBSERVED DEGRADATION (AEGIS Phase 10)

Fixture: Bollinger reversal (default params) on 1y synthetic H1,
BASE costs spread=1pt, commission=7/lot/side. Every number below
is the
**observed** engine output for that scenario — no target, no
threshold. Per Mission-3 rules a fixed figure like "30–50%"
degradation is context, never a gate.

| scenario | dimension | net | Δnet vs BASE | PF | sharpe | maxDD | trades |
|---|---|---|---|---|---|---|---|
| BASE | baseline | 8023.55 | +0.00 | 1.450 | 3.046 | -9.3433 | 287 |
| SPREAD_X3 | spread | 8023.47 | -0.08 | 1.450 | 3.046 | -9.3430 | 287 |
| SPREAD_X10 | spread | 7869.96 | -153.59 | 1.441 | 3.003 | -9.3758 | 288 |
| SLIPPAGE_X3 | slippage | 7982.47 | -41.08 | 1.447 | 3.034 | -9.2966 | 287 |
| COMMISSION_X2 | commission | 7752.79 | -270.76 | 1.437 | 2.970 | -9.4180 | 287 |
| SWAP_STRESS | swap | 7890.39 | -133.16 | 1.444 | 3.012 | -9.2684 | 287 |
| SPIKES | spikes | 3445.10 | -4578.45 | 1.242 | 1.633 | -13.9742 | 268 |
| GAPS | gaps | 12039.88 | +4016.33 | 1.558 | 3.818 | -8.7992 | 292 |
| GAP_REJECT_1PCT | gap_rejection | 11725.69 | +3702.14 | 1.536 | 3.736 | -9.0311 | 291 |
| COMBINED_SEVERE | combined | 4626.07 | -3397.48 | 1.283 | 2.006 | -14.0107 | 272 |

## NOT modelled in Python (live-path, owner/demo evidence)

- **latency** — MQL5 path: EXEC audit lines carry latencyMs; owner/demo evidence
- **partial_fills** — MQL5 path: DONE_PARTIAL handling + RetryQueue (source-pinned)
- **rejections** — MQL5 path: retryable-vs-final retcode ladder (source-pinned)


