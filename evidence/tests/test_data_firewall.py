"""Data-quality firewall (§52) and research cache identity (§54).

§52: OHLCV entering any research/backtest path must be finite and
time-monotonic — NaN/Inf prices and shuffled timestamps are refused at
the boundary, never silently coerced.
§54: every stage cache key carries the research identity (engine /
cost-model / feature / DSL-schema versions), so evidence produced by
different code is never reused across versions.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from mql5bot.data import generate_ohlc, validate_ohlc
from mql5bot.pipeline import research_identity
from mql5bot.versions import COST_MODEL_VERSION, ENGINE_VERSION, FEATURE_VERSION

# ------------------------------------------------------- §52 data firewall


def test_nan_and_inf_prices_rejected():
    df = generate_ohlc(days=60, seed=3)
    bad = df.copy()
    bad.iloc[5, bad.columns.get_loc("close")] = np.nan
    with pytest.raises(ValueError, match="finite"):
        validate_ohlc(bad)
    bad2 = df.copy()
    bad2.iloc[7, bad2.columns.get_loc("high")] = np.inf
    with pytest.raises(ValueError, match="finite"):
        validate_ohlc(bad2)
    bad3 = df.copy()
    bad3.iloc[9, bad3.columns.get_loc("low")] = -np.inf
    with pytest.raises(ValueError, match="finite"):
        validate_ohlc(bad3)
    validate_ohlc(df)  # clean data passes


def test_non_monotonic_timestamps_rejected():
    df = generate_ohlc(days=60, seed=4)
    shuffled = df.iloc[np.random.default_rng(0).permutation(len(df))]
    with pytest.raises(ValueError, match="monotonic"):
        validate_ohlc(shuffled)
    # sorting restores acceptance
    validate_ohlc(shuffled.sort_index())


# -------------------------------------------------- §54 research identity


def test_research_identity_complete_and_deterministic():
    from mql5bot.dsl.schema import SCHEMA_VERSION
    want = {"engine_version": ENGINE_VERSION,
            "cost_model_version": COST_MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "dsl_schema_version": SCHEMA_VERSION}
    got = research_identity()
    assert got == want
    # byte-stable serialization: cache keys are reproducible
    assert (json.dumps(got, sort_keys=True)
            == json.dumps(research_identity(), sort_keys=True))


def test_identity_change_invalidates_stage_cache(monkeypatch, tmp_path):
    """Bumping any identity component must change every stage key."""
    import mql5bot.pipeline as pl

    def key(tag):
        return pl._cache_key(tag, {"x": 1, "identity":
                                   research_identity()})

    before = [key(f"s{i}") for i in (1, 2, 3)]
    import mql5bot.versions as v
    monkeypatch.setattr(v, "ENGINE_VERSION", "9.9.9")
    after = [key(f"s{i}") for i in (1, 2, 3)]
    assert before != after
    assert len(set(after)) == 3
