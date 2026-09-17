"""mql5bot.dsl.parity — the cross-engine PARITY CONTRACT (§12/§13).

A *parity trace* is the canonical, JSON-serializable record of what a
strategy DOES over a fixed OHLC fixture, at the granularity both runtimes
must agree on bar-for-bar:

    positions      desired position in {-1, 0, +1} per CLOSED bar (LOGICAL
                   — compared EXACTLY; no tolerance)
    events         state transitions (bar, from, to) — LOGICAL, exact
    exit_geometry  SL/TP/trailing/breakeven parameters (spec constants)
    position_hash  sha256 of the position vector — a compact equality key

The Python DSL runtime produces this trace here.  The MQL5 generic
runtime (``mql5_dsl_runtime/``, owner-compiled) must produce a
byte-identical ``positions`` vector and the same ``events`` for the same
fixture + bundle; :func:`compare_traces` renders the verdict.

DESIGN NOTE — what parity covers.  The generic-runtime contract is the
SIGNAL and its geometry: the desired-position series and the exit
parameters (ATR multiples etc.) are spec-derived and platform-independent,
so they are compared EXACTLY.  Actual SL/TP *prices*, fills and spread are
the EXECUTION layer's concern (Python engine bridge vs MQL5 TradeManager)
and are covered by the execution audit + the owner Strategy-Tester leg —
never claimed as proven here.
"""

from __future__ import annotations

import hashlib

import numpy as np

from .model import StrategySpec
from .normalize import canon_json
from .runtime import desired_positions, exit_params


def parity_trace(spec: StrategySpec, df, *, spread_points=None,
                 regime_series=None, apply_filters: bool = True) -> dict:
    """Canonical parity trace for ``spec`` over ``df`` (deterministic)."""
    pos = desired_positions(spec, df, spread_points=spread_points,
                            regime_series=regime_series,
                            apply_filters=apply_filters).to_numpy()
    pos = pos.astype(int)
    events: list[dict] = []
    prev = 0
    for i, p in enumerate(pos):
        p = int(p)
        if p != prev:
            events.append({"bar": int(i), "from": int(prev), "to": p})
            prev = p
    pos_list = [int(x) for x in pos.tolist()]
    return {
        "strategy_id": spec.strategy_id,
        "strategy_version": int(spec.version),
        "spec_hash": spec.spec_hash,
        "n_bars": len(pos),
        "positions": pos_list,
        "events": events,
        "exit_geometry": exit_params(spec),
        "position_hash": hashlib.sha256(
            canon_json(pos_list).encode()).hexdigest(),
    }


def compare_traces(reference: dict, other: dict, *,
                   float_tol: float = 0.0) -> list[str]:
    """Return a list of discrepancy strings (empty == parity).

    LOGICAL fields (positions, events, n_bars) are compared EXACTLY.
    Numeric exit-geometry values are compared within ``float_tol`` (0.0 =
    exact, which is correct for spec-constant geometry)."""
    diffs: list[str] = []
    if reference["n_bars"] != other["n_bars"]:
        diffs.append(f"n_bars {reference['n_bars']} != {other['n_bars']}")
        return diffs                          # length mismatch: stop
    rp, op = reference["positions"], other["positions"]
    mism = [i for i, (a, b) in enumerate(zip(rp, op)) if a != b]
    if mism:
        head = mism[:10]
        diffs.append(f"{len(mism)} position mismatches at bars "
                     f"{head}{'…' if len(mism) > 10 else ''}")
    if reference["events"] != other["events"]:
        diffs.append("event streams differ "
                     f"(ref {len(reference['events'])} vs "
                     f"{len(other['events'])} transitions)")
    rg = reference.get("exit_geometry", {})
    og = other.get("exit_geometry", {})
    for key in sorted(set(rg) | set(og)):
        a, b = rg.get(key), og.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(float(a) - float(b)) > float_tol:
                diffs.append(f"exit_geometry.{key}: {a} != {b}")
        elif a != b:
            diffs.append(f"exit_geometry.{key}: {a!r} != {b!r}")
    return diffs


def traces_agree(reference: dict, other: dict, **kw) -> bool:
    return not compare_traces(reference, other, **kw)


def positions_from_series(series) -> list[int]:
    """Helper for owner-side tooling: coerce an MQL5-exported position
    series (any int-like iterable) to the canonical list form."""
    return [int(x) for x in np.asarray(series).astype(int).tolist()]
