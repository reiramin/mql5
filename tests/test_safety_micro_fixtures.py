"""Safety micro-fixtures (mission §7–§11, §16–§17).

Each micro-fixture exercises EXACTLY ONE safety invariant on a minimal
tape, deliberately kept out of the Gold #2 integration fixture so that
Gold #2 stays a realistic multi-factor scenario instead of a forced
spectacle.

Covered here:

* daily-loss halt threshold semantics — the comparator is pinned by
  bracketing (halt strictly below, no halt strictly above) and by the
  literal source expression (equality halts: ``<=``).
* Meta allocation reduce-only monotonicity across many weights — a
  weight can only shrink a risk-approved size, floor-to-grid, and drops
  it entirely below the broker minimum.

The daily-loss/drawdown halt mechanism itself is additionally covered
by ``tests/test_engine.py``; the seam mechanics (weight-1 identity,
weight-0 block, single reduce-only case) by ``tests/test_meta_portfolio.py``.
"""

from __future__ import annotations

import inspect
import math

import numpy as np
import pandas as pd
import pytest
from mql5bot.costs import CostConfig
from mql5bot.engine import MODE_NETTING, Instrument, PortfolioEngine, RunConfig
from mql5bot.sizer import size_position
from mql5bot.symbolspec import SymbolSpec

SPEC = SymbolSpec(
    name="MICRO", digits=3, point=1e-3, tick_size=1e-3,
    tick_value_profit=1.0, tick_value_loss=1.0, contract_size=100_000,
    volume_min=0.01, volume_max=100.0, volume_step=0.01, volume_limit=0.0,
    stops_level_points=0, freeze_level_points=0, currency_profit="USD")
COSTS = CostConfig(symbol="MICRO", spread_points=0.0, slippage_points=0.0,
                   commission_per_lot=0.0)


def _flat_frame(n: int = 300) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01 00:00", periods=n, freq="min")
    df = pd.DataFrame({"open": 100.0, "high": 100.001, "low": 99.999,
                       "close": 100.0}, index=idx)
    return df


def _run(df, signal, **cfg_extra):
    cfg = RunConfig(initial_capital=10_000.0, mode=MODE_NETTING,
                    sizing_mode="risk_percent_equity", risk_value=1.0,
                    allow_signal_exit=True, **cfg_extra)
    ins = Instrument(symbol="MICRO", strategy="micro", df=df, costs=COSTS,
                     spec=SPEC, signal=signal, profit_to_deposit=1.0,
                     params={"sl_atr": 2.0, "tp_atr": 3.0})
    return PortfolioEngine(cfg).run([ins])


# -----------------------------------------------------------------------
# daily-loss halt: threshold semantics (§9)
# -----------------------------------------------------------------------
# One entry, one full-risk stop-out (exactly the 1% risk amount), then a
# second entry window.  The halt must block the second entry exactly when
# the realized loss breaches the daily threshold:
#   engine.py:  basis <= day_start_equity * (1.0 - lim / 100.0)
# i.e. EQUALITY halts (<=), and the check acts on the previous-close
# basis at the open of the next bar.

def _loss_tape() -> tuple[pd.DataFrame, pd.Series]:
    df = _flat_frame()
    closes = df["close"].to_numpy().copy()
    closes[22:25] = [99.99, 99.98, 99.97]     # waterfall pierces the SL
    df["close"] = closes
    df.loc[df.index[1:], "open"] = closes[:-1]
    df["high"] = np.maximum(df["open"], df["close"]) + 1e-6
    df["low"] = np.minimum(df["open"], df["close"]) - 1e-6
    sig = np.zeros(len(df), dtype=int)
    sig[20:30] = 1                             # first entry window
    sig[60:90] = 1                             # second entry window
    return df, pd.Series(sig, index=df.index, name="micro")


def test_daily_loss_halt_brackets_the_threshold():
    df, sig = _loss_tape()

    # First stop-out realizes the full 1% risk amount = $100 -> basis
    # 9900.0.  Note the persisted signal would re-enter after the stop;
    # the bracket limits are chosen far enough apart that the halted
    # leg stops at ONE trade while the inside leg may cascade several
    # stop-outs (each -$100) without breaching the loose threshold.
    halted = _run(df, sig, max_daily_loss_pct=0.5)     # 9950 >= 9900
    assert len(halted.trades) == 1
    assert halted.trades["exit_reason"].iloc[0] == "stop_loss"
    halts = [e for e in halted.events if e["type"] == "halt"]
    assert len(halts) == 1
    assert halts[0]["code"] == "daily_loss_limit"
    opens = [e for e in halted.events if e["type"] == "open"]
    assert len(opens) == 1                     # second window blocked

    inside = _run(df, sig, max_daily_loss_pct=5.0)     # 9500 < 9900
    assert len(inside.trades) >= 2             # re-entry still allowed
    assert [e for e in inside.events if e["type"] == "halt"] == []


def test_daily_loss_halt_comparator_is_equality_inclusive():
    """Pin the exact comparator from the implementation: equality
    breaches HALT (``<=``).  Bracketing alone cannot distinguish <=
    from <, so the source contract is pinned literally."""
    from mql5bot import engine as engine_mod
    src = inspect.getsource(engine_mod)
    assert "basis <= day_start_equity * (1.0 - lim / 100.0)" in src


# -----------------------------------------------------------------------
# Meta seam: reduce-only monotonicity across many weights (§17)
# -----------------------------------------------------------------------

def _approved_lots(df: pd.DataFrame) -> float:
    """Risk-approved size for the single entry of the flat tape."""
    from mql5bot.indicators import atr as atr_fn
    a = atr_fn(df["high"].to_numpy(float), df["low"].to_numpy(float),
               df["close"].to_numpy(float), 14)
    sig_bar = 20
    r = size_position(SPEC, mode="risk_percent_equity", equity=10_000.0,
                      stop_distance=2.0 * float(a[sig_bar]), value=1.0)
    assert not r.rejected
    return float(r.lots)


@pytest.mark.parametrize("weight", [1.0, 0.9, 0.5, 0.3, 0.1, 0.07, 0.05,
                                    0.03, 0.0])
def test_meta_weight_is_reduce_only_and_floors_to_grid(weight):
    df = _flat_frame(120)
    sig = pd.Series(np.where(np.arange(len(df)) >= 20, 1, 0),
                    index=df.index, name="micro")
    schedule = ((df.index[0], weight),)
    ins = Instrument(symbol="MICRO", strategy="micro", df=df, costs=COSTS,
                     spec=SPEC, signal=sig, profit_to_deposit=1.0,
                     params={"sl_atr": 2.0, "tp_atr": 3.0},
                     allocation_schedule=schedule)
    cfg = RunConfig(initial_capital=10_000.0, mode=MODE_NETTING,
                    sizing_mode="risk_percent_equity", risk_value=1.0,
                    allow_signal_exit=True)
    res = PortfolioEngine(cfg).run([ins])

    approved = _approved_lots(df)
    step = SPEC.volume_step
    scaled = math.floor(approved * weight / step + 1e-9) * step
    if weight < 1.0 and scaled < SPEC.volume_min:
        assert len(res.trades) == 0            # dropped below minimum
        drops = [e for e in res.events
                 if e.get("code") == "meta_scale_dropped"]
        assert drops
    else:
        assert len(res.trades) == 1
        fill = float(res.trades["lots"].iloc[0])
        assert fill == pytest.approx(approved if weight >= 1.0 else scaled,
                                     abs=1e-12)
        assert fill <= approved + 1e-12        # reduce-only: never > risk
        assert abs(fill / step - round(fill / step)) < 1e-9  # on grid
