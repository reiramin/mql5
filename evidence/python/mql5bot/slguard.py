"""mql5bot.slguard — post-fill stop-loss verdict (SPEC §3.2, non-negotiable).

Release-A seed model (see docs/IMPLEMENTATION_AUDIT.md and
docs/DECISIONS.md "Python-first canonical risk/identity models"): the pure
``sl_verdict`` function mirrors ``SlVerdict`` in
``mql5/Include/Mql5Bot/SlGuard.mqh`` byte-for-byte so both sides can be
driven by one test matrix.

A position is *protected* only when it carries an SL that is:

* present and positive (not NaN),
* on the correct side of the entry (buy SL below, sell SL above),
* outside the broker stops level (``stops_level_points * point``), measured
  with a half-tick tolerance for grid effects.

Anything else must be remediated (one modify, re-verify) and, if that fails,
closed. A position that can neither be protected nor closed escalates to the
caller, which halts the engine (``ENGINE_HALT``).

The pump thresholds below are module constants so the MQL side and this
mirror share one reference for review; the MQL side inlines the same numbers.
"""

from __future__ import annotations

from mql5bot.symbolspec import SymbolSpec

# --- verdicts (match ENUM_SL_VERDICT in SlGuard.mqh) -----------------------
SL_VERDICT_OK: int = 0
SL_VERDICT_MISSING: int = 1  # sl <= 0 or NaN
SL_VERDICT_WRONG_SIDE: int = 2  # buy SL above entry / sell SL below entry
SL_VERDICT_TOO_CLOSE: int = 3  # inside the broker stops level
SL_VERDICT_NOT_FOUND: int = 4  # position parameters unusable

# --- position types (match MQL5 ENUM_POSITION_TYPE values) -----------------
POSITION_TYPE_BUY: int = 0
POSITION_TYPE_SELL: int = 1

# --- guard pump thresholds (match SlGuard.mqh; pinned for review) ----------
SLG_MAX_ITEMS: int = 8
SLG_MAX_PUMPS_PER_TICK: int = 3
SLG_NO_POSITION_DROP_PUMPS: int = 10  # unbound item that never filled
SLG_MODIFY_WAIT_PUMPS: int = 8  # pumps to wait for a queued modify
SLG_CLOSE_WAIT_PUMPS: int = 20  # pumps to wait for an issued close
SLG_UNPROTECTABLE_ESCALATE_PUMPS: int = 15  # close-only path escalation


def sl_verdict(spec: SymbolSpec, direction: int, entry: float, sl: float) -> int:
    """Classify the SL of a position. Deterministic and broker-free.

    ``direction`` is an MQL5 ``POSITION_TYPE_*`` integer. Returns one of the
    ``SL_VERDICT_*`` constants.
    """
    if direction not in (POSITION_TYPE_BUY, POSITION_TYPE_SELL):
        return SL_VERDICT_NOT_FOUND
    if entry <= 0.0:
        return SL_VERDICT_NOT_FOUND
    if sl != sl or sl <= 0.0:  # noqa: PLR0124 — NaN (deliberate) or absent
        return SL_VERDICT_MISSING
    min_stop = spec.min_stop_distance()
    eps = spec.tick_size * 0.5 if spec.tick_size > 0.0 else 0.0
    if direction == POSITION_TYPE_BUY:
        if sl >= entry:
            return SL_VERDICT_WRONG_SIDE
        if min_stop > 0.0 and (entry - sl) < min_stop - eps:
            return SL_VERDICT_TOO_CLOSE
    else:
        if sl <= entry:
            return SL_VERDICT_WRONG_SIDE
        if min_stop > 0.0 and (sl - entry) < min_stop - eps:
            return SL_VERDICT_TOO_CLOSE
    return SL_VERDICT_OK
