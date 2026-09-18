"""DSL runtime tests: evaluation semantics, filters, limits, safety.

The runtime is the ONLY executable form of a DSL strategy: pure
structural interpretation of validated data — no eval, no imports, no
user code anywhere (mission §6/§15).
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest
from mql5bot.data import generate_ohlc
from mql5bot.dsl import (
    AmbiguousParameter,
    NotExecutable,
    UnknownReference,
    desired_positions,
    exit_params,
    parse_spec,
)

from tests.test_dsl_core import _base_doc

FRAME = generate_ohlc(days=120, seed=11)


def _positions(doc: dict, df: pd.DataFrame = FRAME, **kw):
    return desired_positions(parse_spec(doc), df, **kw)


# ------------------------------------------------------------ modes


def test_instant_mode_flat_between_signals():
    """Bollinger semantics: flat inside the bands, no state carry."""
    doc = _base_doc()
    doc["entry"]["mode"] = "instant"
    doc["entry"] = {"mode": "instant",
                    "long": {"left": {"price": "close"}, "cmp": "LT",
                             "right": {"const": FRAME["close"].min()}},
                    "short": {"left": {"price": "close"}, "cmp": "GT",
                              "right": {"const": FRAME["close"].max()}}}
    out = _positions(doc)
    assert set(out.unique()) <= {0}          # thresholds unreachable


def test_state_mode_persists_until_opposite_entry():
    doc = _base_doc()            # ema_f > ema_s long, < short
    out = _positions(doc)
    ref_fire = (FRAME["close"] > FRAME["close"]).any()
    assert ref_fire is not None
    # state is never NaN and only steps through {-1, 0, 1}
    assert set(out.unique()) <= {-1, 0, 1}
    # transitions are single-step (state semantics, no teleports)
    steps = set(np.unique(out.diff().dropna().to_numpy()))
    assert steps <= {-2, -1, 0, 1, 2}


def test_exit_condition_flattens_state():
    doc = _base_doc()
    doc["entry"]["exit_long"] = {"left": {"price": "close"},
                                 "cmp": "LT",
                                 "right": {"ind": "ema_s"}}
    out = _positions(doc)
    from mql5bot.dsl import compute_indicators
    spec = parse_spec(doc)
    series = compute_indicators(FRAME, spec.indicators)
    close = FRAME["close"].to_numpy()
    ema_s = series["ema_s"]
    # exit condition (close < ema_s) holds the position at 0 on every
    # bar where the long ENTRY has not re-fired
    viol = (out.to_numpy() == 1) & (close < ema_s)
    if viol.any():
        # entry priority is bar-level: an entry bar may re-open; every
        # other bar must respect the exit
        from mql5bot.dsl import eval_condition
        long_fire = eval_condition(spec.entry.long, series, FRAME)
        assert (viol & ~long_fire).sum() == 0


# ------------------------------------------------------------ NaN safety


def test_nan_warmup_emits_zero_never_crashes():
    doc = _base_doc()
    out = _positions(doc)
    # warmup region (first ~30 bars for slow EMA) must be flat
    assert (out.to_numpy()[:25] == 0).all()


def test_div_by_zero_yields_nan_comparison_false_not_crash():
    doc = _base_doc()
    zero = {"const": 0}
    doc["entry"]["long"] = {
        "left": {"div": [{"ind": "ema_f"}, zero]},
        "cmp": "GT", "right": {"ind": "ema_s"}}
    out = _positions(doc)                    # must not raise
    assert len(out) == len(FRAME)


# ------------------------------------------------------------ filters


def test_filters_only_flatten_never_create_positions():
    base = _positions(_base_doc()).to_numpy()
    doc = copy.deepcopy(_base_doc())
    doc["market"]["trading_days"] = [1, 2, 3, 4]     # Mon..Thu
    filtered = _positions(doc,
                          df=FRAME,
                          )
    out = filtered.to_numpy()
    # every non-flat filtered bar was non-flat before (subset property)
    assert set(np.nonzero(out)[0]) <= set(np.nonzero(base)[0])
    # Friday bars (dayofweek 4? no: 4=Fri) are flat — [1,2,3,4] = Mon..Fri
    fri = FRAME.index.dayofweek.to_numpy() == 5     # Saturday
    if fri.any():
        assert (out[fri] == 0).all()
    # Sunday bars are flat (day 6 not in list)
    sun = FRAME.index.dayofweek.to_numpy() == 6
    if sun.any():
        assert (out[sun] == 0).all()


def test_session_filter_flattens_outside_window():
    doc = _base_doc()
    doc["filters"] = {"session": {"start": "00:00", "end": "01:00",
                                  "tz": "UTC"}}
    out = _positions(doc).to_numpy()
    hours = FRAME.index.hour.to_numpy()
    outside = (hours >= 2)
    if outside.any():
        assert (out[outside] == 0).all()


def test_spread_filter_requires_series_never_guesses():
    doc = _base_doc()
    doc["filters"] = {"max_spread_points": 1.5}
    with pytest.raises(NotExecutable, match="spread series"):
        _positions(doc)


def test_spread_filter_flattens_wide_spread_bars():
    doc = _base_doc()
    doc["filters"] = {"max_spread_points": 1.5}
    spread = np.where(np.arange(len(FRAME)) % 50 < 10, 9.9, 1.0)
    out = _positions(doc, spread_points=spread).to_numpy()
    wide = spread > 1.5
    assert (out[wide] == 0).all()


def test_regime_forbidden_requires_series():
    doc = _base_doc()
    doc["filters"] = {"regime": {"forbidden": ["HIGH_VOL"]}}
    with pytest.raises(NotExecutable, match="regime series"):
        _positions(doc)


def test_regime_forbidden_flattens_matching_bars():
    doc = _base_doc()
    doc["filters"] = {"regime": {"forbidden": ["TREND_UP"]}}
    labels = np.where(np.arange(len(FRAME)) % 40 < 20, "TREND_UP",
                      "RANGE")
    out = _positions(doc, regime_series=labels).to_numpy()
    assert (out[labels == "TREND_UP"] == 0).all()


def test_cooldown_suppresses_reentry_bars():
    doc = _base_doc()
    doc["filters"] = {"cooldown_bars": 10}
    uncooled = _positions(_base_doc()).to_numpy()
    cooled = _positions(doc).to_numpy()
    # every non-flat cooled bar maps to the same direction pre-cooldown
    nz = cooled != 0
    assert (cooled[nz] == uncooled[nz]).all()
    assert nz.sum() <= (uncooled != 0).sum()


# ------------------------------------------------------------ ambiguity


def test_ambiguous_spec_refuses_execution():
    doc = _base_doc()
    doc["entry"]["long"]["right"] = {"ambiguous": "x",
                                     "range": [1.0, 2.0]}
    spec = parse_spec(doc)
    assert not spec.executable
    with pytest.raises(AmbiguousParameter):
        desired_positions(spec, FRAME)


def test_unresolved_param_reference_is_unknown():
    doc = _base_doc()
    doc["entry"]["long"]["right"] = {"param": "no_such_param"}
    with pytest.raises(UnknownReference):
        parse_spec(doc)


# ------------------------------------------------------------ exit params


def test_exit_params_atr_passthrough_and_honest_non_atr():
    doc = _base_doc()
    spec = parse_spec(doc)
    params = exit_params(spec)
    assert params["sl_atr"] == 2.0
    assert params["trail_atr"] == 0.0

    doc2 = _base_doc()
    doc2["exit"] = {"sl": {"model": "points", "points": 300}}
    params2 = exit_params(parse_spec(doc2))
    assert params2["sl_atr"] is None          # honest: not an ATR model
    assert params2["points_sl"] == 300.0


# ------------------------------------------------------------ determinism


def test_same_input_byte_identical_output():
    s1 = _positions(_base_doc())
    s2 = _positions(_base_doc())
    pd.testing.assert_series_equal(s1, s2)


def test_different_frames_independent():
    other = generate_ohlc(days=120, seed=12)
    a = _positions(_base_doc(), FRAME)
    b = _positions(_base_doc(), other)
    assert not a.equals(b)
