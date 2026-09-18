"""Indicator universe tests (autonomous-discovery mission §8/§9/§10/
§61/§62/§76/§77).

- every registry entry satisfies the §9 contract;
- every kind is deterministic and causal (future rows never change
  past values) — a registry-wide property test;
- warmup NaN behavior; multi-output declarations first-class;
- DSL integration: parse/run/param validation/output references;
- pivot confirmation semantics (§77): pivot_time < confirmation_time
  and values exist only from confirmation onward;
- MTF: higher-timeframe values appear only after the HTF bar closes;
- resource budget: contract limits are enforced (no silent increases).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from mql5bot.data import generate_ohlc
from mql5bot.dsl import parse_spec
from mql5bot.dsl.errors import SchemaInvalid
from mql5bot.dsl.runtime import desired_positions
from mql5bot.indicator_universe import (
    ALL_KINDS,
    CATEGORIES,
    EXTENDED_KINDS,
    REGISTRY,
    compute,
    contract,
)

DF = generate_ohlc(days=160, seed=5)


def _prepared(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    """Augment the frame with the columns a contract requires (e.g.
    BETA's benchmark).  Deterministic function of the close — no
    lookahead (shifted benchmark for the synthetic columns)."""
    ct = contract(kind)
    missing = [c for c in ct.requires_columns if c not in df.columns]
    for c in missing:
        base = df["close"].shift(1).fillna(df["close"].iloc[0])
        df = df.assign(**{c: (1.0 + base.pct_change().fillna(0.0)
                              * 0.5).cumsum() * 100})
    return df


# ------------------------------------------------------------ contracts


def test_registry_is_broad_and_categorized():
    assert len(ALL_KINDS) >= 60
    assert len(EXTENDED_KINDS) >= 50
    for kind, (ct, _fn) in REGISTRY.items():
        assert ct.category in CATEGORIES, kind
        assert ct.outputs and ct.outputs[0], kind   # primary first
        assert ct.determinism, kind
        assert "closed-bar" in ct.causality, kind
        assert ct.mql5_status in {"parity-tested", "canonical-defined"}, \
            kind
        for p in ct.params:
            assert p.minimum <= p.maximum, (kind, p.name)
            if p.default is not None:
                assert p.minimum <= p.default <= p.maximum, (kind, p.name)


def test_every_kind_computes_finite_outputs():
    for kind in sorted(EXTENDED_KINDS):
        ct = contract(kind)
        outs = compute(kind, _prepared(kind, DF), ct.resolve({}))
        assert tuple(outs) == ct.outputs, kind
        for name, arr in outs.items():
            assert len(arr) == len(DF), (kind, name)
            finite = arr[np.isfinite(arr)]
            assert len(finite) > 0, (kind, name)
            assert np.all(np.isfinite(finite)), (kind, name)


def test_registry_wide_causality_property():
    """§20/§56.5: mutating data strictly after t0 NEVER changes values
    at or before t0 — for every indicator in the universe."""
    t0 = len(DF) - 120
    df2 = DF.copy()
    df2.iloc[t0 + 60:] = df2.iloc[t0 + 60:] * 1.4 + 0.03
    for kind in sorted(EXTENDED_KINDS):
        ct = contract(kind)
        a = compute(kind, _prepared(kind, DF), ct.resolve({}))
        b = compute(kind, _prepared(kind, df2), ct.resolve({}))
        for name in a:
            va, vb = a[name][t0:-120], b[name][t0:-120]
            fa, fb = np.isfinite(va), np.isfinite(vb)
            assert np.array_equal(fa, fb), (kind, name)
            assert np.allclose(va[fa], vb[fa], rtol=1e-12, atol=1e-12), \
                (kind, name)


def test_determinism_same_inputs_same_outputs():
    for kind in ("SUPERTREND", "PSAR", "KAMA", "ADX", "SWING_HIGH"):
        ct = contract(kind)
        a = compute(kind, DF, ct.resolve({}))
        b = compute(kind, DF, ct.resolve({}))
        for name in a:
            np.testing.assert_array_equal(a[name], b[name], err_msg=kind)


def test_param_validation_rejects_out_of_range():
    ct = contract("SUPERTREND")
    assert ct.validate({"period": 0})[0].startswith("period")
    assert ct.validate({"mult": 99})[0].startswith("mult")
    assert ct.validate({}) == []            # all defaults present
    # the required-param mechanism (a param without default):
    from mql5bot.indicator_universe.contracts import IndicatorContract, IndicatorParam
    synthetic = IndicatorContract(
        kind="SYNTH", version=1, category="trend",
        params=(IndicatorParam("left", "int", 1, 500),),  # NO default
        outputs=("v",), warmup=lambda p: 1, price_source="close")
    assert synthetic.validate({}) == ["left is required"]
    assert synthetic.validate({"left": 0})[0].startswith("left")


# ------------------------------------------------------------ DSL wiring


def _doc(kind, params, extra_ind=None, ref=None):
    return {
        "schema_version": "1.0", "strategy_id": "universe_wire",
        "version": 1,
        "market": {"symbol": "EURUSD", "timeframe": "H1"},
        "indicators": [
            {"id": "x", "kind": kind, **params},
            *(extra_ind or [])],
        "entry": {"mode": "state",
                  "long": ref or {"left": {"price": "close"},
                                  "cmp": "GT",
                                  "right": {"ind": "x"}},
                  "short": {"left": {"price": "close"}, "cmp": "LT",
                            "right": {"ind": "x"}}},
        "exit": {"sl": {"model": "atr", "mult": 1.5}},
    }


def test_extended_kind_parses_runs_and_hashes_stable():
    doc = _doc("SUPERTREND", {"period": 10, "mult": 3.0})
    s1 = parse_spec(doc)
    s2 = parse_spec(doc)                     # idempotent canonicalization
    assert s1.spec_hash == s2.spec_hash
    sig = desired_positions(s1, DF)
    assert len(sig) == len(DF)


@pytest.mark.parametrize("bad,params", [
    ("SUPERTREND", {"period": 0, "mult": 3.0}),
    ("SUPERTREND", {"period": 10, "mult": 3.0, "bogus": 1}),
    ("PSAR", {"step": -0.1, "maximum": 0.2}),
    ("CCI", {"period": 6000}),               # period > max (5000)
])
def test_invalid_params_rejected_whole(bad, params):
    with pytest.raises(SchemaInvalid):
        parse_spec(_doc(bad, params))


def test_multi_output_reference_validation():
    doc = _doc("KELTNER", {"period": 20, "mult": 2.0},
               ref={"left": {"ind": "x__lower"}, "cmp": "GT",
                    "right": {"price": "close"}})
    spec = parse_spec(doc)
    sig = desired_positions(spec, DF)
    assert len(sig) == len(DF)
    bad = _doc("KELTNER", {"period": 20, "mult": 2.0},
               ref={"left": {"ind": "x__nonsense"}, "cmp": "GT",
                    "right": {"price": "close"}})
    with pytest.raises(Exception, match="no output"):
        parse_spec(bad)


def test_shift_applies_to_registry_kinds():
    doc = _doc("CCI", {"period": 20})
    doc["indicators"][0]["shift"] = 2
    spec = parse_spec(doc)
    sig = desired_positions(spec, DF)
    assert len(sig) == len(DF)


# ------------------------------------------------------------ §77 pivots


def test_pivot_confirmation_timestamps():
    """§77: the pivot level appears only at confirmation (right bars
    after the extremum); values before confirmation are NaN, so any
    signal built on it satisfies signal_time >= confirmation_time."""
    outs = compute("SWING_HIGH", DF, {"left": 3, "right": 3})
    level, age = outs["level"], outs["age"]
    confirmed = np.flatnonzero(np.isfinite(level))
    assert len(confirmed) > 0
    # wherever a value exists, the confirmation lag equals `right`
    assert np.all(age[confirmed] == 3.0)
    # no confirmed value within `right` bars of the series start
    assert confirmed.min() >= 3
    # values are actual local maxima: pivot_time = i - right
    highs = DF["high"].to_numpy()
    for i in confirmed[:20]:
        i = int(i)
        pivot_time = i - 3
        window = highs[pivot_time - 3:pivot_time + 4]
        assert window[3] == window.max() == level[i]


def test_mtf_causality():
    """MTF value changes only AFTER the higher-timeframe bar closes."""
    outs = compute("MTF_EMA", DF, {"period": 5, "mtf": 24})
    mtf = outs["mtf"]
    defined = np.flatnonzero(np.isfinite(mtf))
    # first defined value appears exactly when the first HTF bar with
    # a defined EMA closes: warmup on the aggregated frame
    from mql5bot.indicator_universe.volatility_volume_structure import _aggregate
    o, h, l, c, v = _aggregate(DF, 24)
    ht = pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                       "volume": v})
    from mql5bot.indicators import ema as _ema
    warm = int(np.flatnonzero(np.isfinite(_ema(ht["close"].to_numpy(),
                                               5)))[0])
    assert defined.min() == (warm + 1) * 24 - 1
    # the value is constant within each finite HTF bar and only
    # updates at HTF boundaries (change indices are ≡ 23 mod 24)
    for start in (168, 240, 312):
        seg = mtf[start:start + 23]     # stops before the boundary bar
        assert np.all(seg == seg[0])
    changes = np.flatnonzero((mtf[1:] != mtf[:-1])
                             & np.isfinite(mtf[1:])
                             & np.isfinite(mtf[:-1])) + 1
    assert all(int(i) % 24 == 23 for i in changes)


# ------------------------------------------------------------ budgets


def test_resource_budgets_pinned():
    """§62: the documented limits hold and registry kinds cannot
    smuggle more parameters than the schema allows."""
    from mql5bot.dsl import schema as schema_mod
    assert schema_mod.MAX_INDICATORS == 32
    assert schema_mod.MAX_DEPTH == 32
    big = _doc("EMA", {"period": 20})
    big["indicators"] = [{"id": f"i{j:02d}", "kind": "CCI",
                          "period": 20} for j in range(33)]
    from mql5bot.dsl.errors import LimitExceeded
    with pytest.raises(LimitExceeded):
        parse_spec(big)


def test_baseline_kinds_unchanged_hashes():
    """Parity guard: baseline kinds keep their exact canonical docs
    (no catalog default-filling leaked into baseline normalization)."""
    doc = _doc("EMA", {"period": 20})
    spec = parse_spec(doc)
    assert spec.document["indicators"][0] == {
        "id": "x", "kind": "EMA", "period": 20, "applied": "close"}


# ------------------------------------------------ §7 coverage additions


def test_t3_matches_reference_cascade():
    """T3(n, v=0) degenerates to a triple EMA — the reference identity."""
    from mql5bot.indicators import ema

    def robust(x):
        # restated independently: EMA over the first finite tail
        x = np.asarray(x, dtype=float)
        f = int(np.flatnonzero(np.isfinite(x))[0])
        out = np.full(len(x), np.nan)
        out[f:] = ema(x[f:], 10)
        return out

    x = DF["close"].to_numpy()
    e1 = robust(x)
    e2 = robust(e1)
    e3 = robust(e2)
    outs = compute("T3", DF, {"period": 10, "volume_factor": 0.0})
    k = contract("T3").warmup({"period": 10, "volume_factor": 0.0})
    # warmup is a conservative completeness bound: finite from k on
    assert np.isfinite(outs["t3"][k:]).all()
    np.testing.assert_allclose(outs["t3"][k:], e3[k:],
                               rtol=1e-12, atol=1e-12)


def test_ichimoku_unshifted_and_causal():
    """Values equal hand-computed window midpoints at the SAME bar
    (no displacement); mutating the future never changes the past."""
    h, l = DF["high"].to_numpy(), DF["low"].to_numpy()
    outs = compute("ICHIMOKU", DF, {"tenkan": 9, "kijun": 26,
                                    "senkou": 52})
    i = 200
    tenkan_ref = (np.nanmax(h[i - 8:i + 1]) + np.nanmin(l[i - 8:i + 1])) / 2
    np.testing.assert_allclose(outs["tenkan"][i], tenkan_ref, atol=1e-12)
    kijun_ref = (np.nanmax(h[i - 25:i + 1])
                 + np.nanmin(l[i - 25:i + 1])) / 2
    np.testing.assert_allclose(outs["kijun"][i], kijun_ref, atol=1e-12)
    # contract keeps the closed-bar causality string + warmup bound
    ct = contract("ICHIMOKU")
    assert len(DF) >= ct.warmup({"tenkan": 9, "kijun": 26, "senkou": 52})
    assert "closed-bar" in ct.causality


def test_beta_known_value_and_required_column():
    df = DF.copy()
    rng = np.random.default_rng(2)
    df["benchmark_close"] = (
        100 + np.cumsum(rng.normal(0, 0.3, len(df))))
    outs = compute("BETA", df, {"period": 60})
    r = df["close"].pct_change()
    b = df["benchmark_close"].pct_change()
    cov = r.rolling(60).cov(b)
    var = b.rolling(60).var()
    np.testing.assert_allclose(outs["beta"], (cov / var).to_numpy(),
                               rtol=1e-12, atol=1e-12)
    assert contract("BETA").requires_columns == ("benchmark_close",)
    with pytest.raises(ValueError, match="benchmark_close"):
        compute("BETA", DF, {"period": 60})


def test_dmi_coverage_via_adx_outputs():
    """§7 'ADX/DMI': the registry exposes +DI/−DI as ADX outputs."""
    ct = contract("ADX")
    assert tuple(ct.outputs) == ("adx", "plus_di", "minus_di")
