# External Watchdog (mission §44–§45/§81)

**Status: IMPLEMENTED (in-process component designed for external hosting); deployment harness PARTIAL.**

`discovery/safety.py:Watchdog` — deliberately minimal:

- **No strategy logic, no LLM, no allocation authority**: it reads a `WatchdogObservation` (equity, daily DD, open positions, trades/hour, heartbeat age, engine state) and emits alerts. It cannot trade, size, or promote.
- **Fail-safe both directions** (§45, tested):
  - watchdog broken → a raising alert channel NEVER stops monitoring (attack 18; errors are breadcrumb-logged to `_channel_errors`);
  - engine broken → stale heartbeat (`heartbeat_age_seconds > max`) and `emergency_state != NORMAL` alert independently of the engine's own telemetry.
- **Rate-limited**: per-alert-kind, `alert_rate_limit_seconds` (default 300s) — an attacker cannot spam the operator channel into silence.
- **No secrets**: the default channel is stdout/log; a webhook URL may be injected via environment by the host process, never hardcoded.

## External hosting (§44)

The component takes injected `clock` and `channel`, holds no global state, and is safe to run in a separate process (`python -c "from mql5bot.discovery.safety import Watchdog; ..."`). The shipped deployment harness (systemd/container) is **NOT_IMPLEMENTED** in this mission; when hosted externally it must use a read-only view of equity/telemetry and its own clock, so a Factory crash cannot silence it (§81 failure-model: engine-dead and watchdog-dead are independently observable).
