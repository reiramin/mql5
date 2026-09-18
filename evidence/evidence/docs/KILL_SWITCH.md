# Kill Switch (mission §42–§43)

**Status: IMPLEMENTED.**

## States

`NORMAL` / `NO_NEW_TRADES` / `EMERGENCY_HALT` (`discovery/safety.py:KillSwitchState`).

- `NO_NEW_TRADES`: any policy threshold trips (daily/weekly/total DD, trade rate > `max_trade_rate_per_hour`, execution failure rate, stale heartbeat, exposure breach, broker disconnected). Auto-clears when the observation is clean again.
- `EMERGENCY_HALT`: severe trips only — equity below `equity_floor_pct` of reference, impossible position state, or total-DD breach. **Sticky**: further clean observations do NOT clear it; only `explicit_reset(actor, reason)` does, and it is recorded in the append-only history (bounded 500 entries, persisted through the injected `state_sink`).

## Triggers monitored (§42)

Equity/daily-DD/weekly-DD/total-DD, abnormal trade rate, execution failure rate, stale telemetry heartbeat, impossible position states, exposure breach, broker connectivity. All thresholds come from `discovery.yaml:kill_switch` (policy-driven; `KillSwitchPolicy.validate` rejects degenerate values).

## Ordering guarantees

- `may_open_new_trades()` is consulted by the governor: a halted or no-new-trades switch yields ZERO allocations (capital case D fixture) regardless of scores.
- The ramp refuses to size anything while `kill_switch_active` (attack 19).
- `close_all_requested` is true ONLY for `EMERGENCY_HALT` AND `close_all_on_emergency=true` — the default policy keeps managing protected positions instead of dumping them (§42).
- NaN-poisoned observations cannot disarm the trigger logic (attack 24: honest severe inputs still trip).

**MQL5 side: PARTIAL** — the EA-side enforcement point exists in the safety chain, but a live-terminal proof is owner-compilable only (§75/§76); no MT5 claims are made.
