# Safety Governance (mission §41–§45/§79–§81)

**Status: IMPLEMENTED.**

Three deliberately boring, independent components in `discovery/safety.py`:

| Component | Guards | Authority |
|---|---|---|
| Kill switch | the ACCOUNT (equity, DDs, abnormal trade rate, execution failures, stale heartbeat, impossible positions, exposure breach, connectivity) | overrides ALL new-entry authorization; outside Strategy/Factory/Meta/LLM |
| Allocation circuit breaker | DECISION behavior (gross jumps, strategy-count collapse, candidate explosions, per-strategy weight teleports) | freezes NEW allocation, keeps last safe allocation, requires human review; never closes positions |
| Watchdog | OBSERVATION (heartbeat age, daily DD, engine state, impossible position counts) | alerts only (rate-limited); no trade/allocation authority |

## Distinctions that matter

- Circuit breaker ≠ kill switch: the breaker freezes allocations (capital keeps being MANAGED per last safe weights); the kill switch stops new trades (and only CLOSES ALL if the policy explicitly sets `close_all_on_emergency`, default false — never indiscriminate liquidation on a crash, §42).
- Neither is reachable from the strategy, factory, Meta or LLM layers; the UI can VIEW and explicitly RESET (audited, actor+reason) but not silently clear.
- Veto order (§48/§104): KillSwitch → circuit breaker → governor → Meta → Risk. No layer can remove a lower layer's veto; `governor.recommend` checks the kill switch FIRST and returns an empty allocation set with status `KILL_SWITCH`.
