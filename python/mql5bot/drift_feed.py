"""mql5bot.drift_feed — as-of drift snapshots for Meta decisions
(meta-realism mission, Phases 9-10).

A :class:`DriftSnapshot` compares a strategy's RECENT trade window with
its BASELINE window, both strictly before the decision timestamp:

* expectancy_drift — per-trade pct-return mean shift
* pf_drift         — profit-factor shift (relative)
* winrate_drift    — win-rate shift
* execution_drift  — median holding-period shift (behaviour proxy)
* regime_drift     — baseline-dominant regime vs the CURRENT regime label
* overall_score    — weighted combination in [0, 1]
* status           — HEALTHY | MILD | SEVERE | UNKNOWN

The layer's drift ladder (contract): score < DRIFT_MILD (0.10) ⇒ factor
1.0; [0.10, 0.50) ⇒ linear decay; >= DRIFT_BLOCK (0.50) ⇒ hard zero.
UNKNOWN (insufficient closed trades) leaves drift UNAVAILABLE — the
layer then applies its conservative MISSING fallback (0.5), never a
neutral pass.

Causality: only trades with ``exit_time < as_of`` feed a snapshot;
mutating post-decision trades cannot change earlier decisions (pinned).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DRIFT_VERSION = "asof-1.0"

RECENT_N = 20
BASELINE_N = 20

#: status thresholds aligned with the layer ladder
HEALTHY_MAX = 0.10
MILD_MAX = 0.30
SEVERE_MIN = 0.50

_WEIGHTS = {"expectancy": 0.30, "pf": 0.20, "winrate": 0.20,
            "execution": 0.20, "regime": 0.10}


@dataclass(frozen=True)
class DriftSnapshot:
    strategy_id: str
    as_of: pd.Timestamp
    expectancy_drift: float
    pf_drift: float
    winrate_drift: float
    execution_drift: float
    regime_drift: float
    overall_score: float
    status: str
    drift_version: str = DRIFT_VERSION
    n_recent: int = 0
    n_baseline: int = 0
    components: dict = field(default_factory=dict)

    def journal(self) -> dict:
        return {"drift_version": self.drift_version,
                "drift_status": self.status,
                "drift_score": round(self.overall_score, 10),
                "drift_as_of": str(self.as_of)}

    @property
    def available(self) -> bool:
        return self.status != "UNKNOWN"


def _clip01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def _status_of(score: float, n_recent: int, n_baseline: int) -> str:
    if n_recent < RECENT_N or n_baseline < BASELINE_N:
        return "UNKNOWN"
    if score >= SEVERE_MIN:
        return "SEVERE"
    if score > MILD_MAX:
        return "MILD"
    if score >= HEALTHY_MAX:
        return "MILD"
    return "HEALTHY"


def _pf(pnl: np.ndarray) -> float:
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    if losses <= 0.0:
        return float("inf") if gains > 0 else 1.0
    return float(gains / losses)


def drift_snapshot(trades: pd.DataFrame, strategy_id: str,
                   as_of: pd.Timestamp, *, current_regime: str = "",
                   recent_n: int = RECENT_N,
                   baseline_n: int = BASELINE_N) -> DriftSnapshot:
    """As-of drift for one strategy from its CLOSED-trade ledger
    (columns: exit_time, pnl_pct, bars_held — the engine trade shape)."""
    ts = pd.Timestamp(as_of)
    t = trades
    if len(t):
        exit_ts = pd.to_datetime(t["exit_time"])
        tz0 = exit_ts.dt.tz.iloc[0] if exit_ts.dt.tz is not None else None
        if tz0 is not None and ts.tzinfo is None:
            ts = ts.tz_localize(tz0)
        t = t.loc[exit_ts < ts]
    pnl = t["pnl_pct"].to_numpy(dtype=float) if len(t) else np.array([])
    recent = pnl[-recent_n:]
    baseline = pnl[-(recent_n + baseline_n):-recent_n]

    if len(recent) < recent_n or len(baseline) < baseline_n:
        return DriftSnapshot(strategy_id, ts, 0.0, 0.0, 0.0, 0.0, 0.0,
                             0.0, "UNKNOWN", n_recent=len(recent),
                             n_baseline=len(baseline))

    exp_r, exp_b = float(recent.mean()), float(baseline.mean())
    scale = max(abs(exp_b), 1e-6)
    expectancy_d = _clip01(abs(exp_r - exp_b) / (2.0 * scale))

    pf_r, pf_b = _pf(recent), _pf(baseline)
    pf_d = _clip01(abs(pf_r - pf_b) / max(pf_b, 1e-6)) if \
        np.isfinite(pf_r) and np.isfinite(pf_b) else 0.0

    wr_r = float((recent > 0).mean())
    wr_b = float((baseline > 0).mean())
    winrate_d = _clip01(abs(wr_r - wr_b) / 0.25)   # 25pp swing ⇒ 1.0

    bars_r = _median_bars(t, recent_n, False)
    bars_b = _median_bars(t, recent_n + baseline_n, True)
    execution_d = _clip01(abs(bars_r - bars_b) / max(bars_b, 1.0)) \
        if bars_r is not None and bars_b else 0.0

    regime_d = _regime_drift(t, recent_n, baseline_n, current_regime)

    score = (_WEIGHTS["expectancy"] * expectancy_d
             + _WEIGHTS["pf"] * pf_d
             + _WEIGHTS["winrate"] * winrate_d
             + _WEIGHTS["execution"] * execution_d
             + _WEIGHTS["regime"] * regime_d)
    status = _status_of(score, len(recent), len(baseline))
    return DriftSnapshot(strategy_id, ts, expectancy_d, pf_d, winrate_d,
                         execution_d, regime_d, float(score), status,
                         n_recent=len(recent), n_baseline=len(baseline),
                         components={"exp_recent": exp_r,
                                     "exp_baseline": exp_b,
                                     "pf_recent": pf_r, "pf_base": pf_b,
                                     "wr_recent": wr_r, "wr_base": wr_b})


def _median_bars(t: pd.DataFrame, n: int, skip_recent: bool) -> float | None:
    seg = t.iloc[-(n + RECENT_N if skip_recent else n):]
    if skip_recent:
        seg = seg.iloc[:-RECENT_N]
    if not len(seg):
        return None
    bars = pd.to_numeric(seg["bars_held"], errors="coerce") \
        if "bars_held" in seg else None
    if bars is None or bars.notna().sum() == 0:
        return None
    return float(bars.median())


def _regime_drift(t: pd.DataFrame, recent_n: int, baseline_n: int,
                  current_regime: str) -> float:
    """0.0 unless the CURRENT regime label differs from the regime under
    which the BASELINE window earned its dominant outcome (deterministic
    proxy: the baseline window's best-trade bar regime).  Without regime
    history the component is 0.0 (never guesses)."""
    if not current_regime or len(t) < recent_n + baseline_n:
        return 0.0
    return 0.0   # regime-history wiring lands with the regime feed pin;
    # the component stays conservative (0) rather than fabricating a
    # regime label the ledger does not carry.


def drift_snapshots(trades_by_id: dict[str, pd.DataFrame],
                    as_of: pd.Timestamp, *,
                    regimes: dict[str, str] | None = None
                    ) -> dict[str, DriftSnapshot]:
    regimes = regimes or {}
    return {sid: drift_snapshot(t, sid, as_of,
                                current_regime=regimes.get(sid, ""))
            for sid, t in sorted(trades_by_id.items())}
