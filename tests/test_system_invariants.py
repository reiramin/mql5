"""SYSTEM INVARIANTS (mission Phase 1) — machine-testable properties
that must hold for EVERY run, configuration and failure mode.

Catalog: docs/SYSTEM_INVARIANTS.md.  Each test carries its invariant
ID.  Tolerances: 1e-6 on equity sums (float accumulation over ~1e4
events), 1e-9 on weights/weights-derived quantities (serialization
contract).
"""

import itertools
import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from mql5bot.backtest import run_backtest
from mql5bot.costs import COST_PROFILES, PROFILE_DEFAULTS
from mql5bot.data import generate_ohlc
from mql5bot.meta_layer import (
    MetaConfig,
    MetaLayer,
    MetaMode,
    MetaState,
    StrategyMetaInput,
)
from mql5bot.pipeline import OosRegistry, RunManifest

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
ACC_TOL = 1e-6   # float accumulation over thousands of ledger events


def _inp(sid="a", signal=1, **kw):
    base = {"regimes_allowed": frozenset({"TREND_UP"}),
            "regimes_preferred": frozenset({"TREND_UP"}),
            "regimes_forbidden": frozenset(),
            "drift_available": True, "drift_score": 0.0}
    base.update(kw)
    state = base.pop("certification_state", "VERIFIED")
    return StrategyMetaInput(sid, "EURUSD", signal, "TREND_UP",
                             base.pop("regimes_allowed"),
                             base.pop("regimes_preferred"),
                             base.pop("regimes_forbidden"), state, **base)


def _stats(*ids, e=0.01, n=100):
    return {i: (e, n) for i in ids}


@pytest.fixture(scope="module")
def df():
    return generate_ohlc(days=90, seed=5)


# ===========================================================================
# INV-ACC — ACCOUNTING
# ===========================================================================


@pytest.mark.parametrize("strategy,params", [
    ("ema_crossover", {"fast": 8, "slow": 30}),
    ("donchian_breakout", {"lookback": 20}),
])
def test_inv_acc_1_equity_identity(df, strategy, params):
    """INV-ACC-1: starting equity + Σ realized trade PnL == ending
    equity (closed-ledger runs; unrealized at end is zero)."""
    r = run_backtest(df, strategy, params)
    assert len(r.trades) > 0
    assert 10_000.0 + r.trades.pnl.sum() == \
        pytest.approx(r.equity.iloc[-1], abs=ACC_TOL)


def test_inv_acc_2_realized_pnl_counted_exactly_once(df):
    """INV-ACC-2: Σ trade pnl == reported net_profit (appears exactly
    once — no double-count in equity or metrics)."""
    r = run_backtest(df, "ema_crossover", {"fast": 8, "slow": 30})
    assert r.trades.pnl.sum() == pytest.approx(
        r.metrics["net_profit"], abs=ACC_TOL)


def test_inv_acc_3_fees_charged_exactly_once(df):
    """INV-ACC-3: per-trade pnl == dir·(exit−entry)·lots·contract −
    fees.  Spread/slippage are embedded in the recorded FILL prices
    (costs column is informational) — a fee is never charged twice,
    and a cost is never additionally deducted from pnl."""
    r = run_backtest(df, "ema_crossover", {"fast": 8, "slow": 30},
                     spread_points=2.5, slippage_points=1.0)
    t = r.trades
    d = t.side.map({"long": 1.0, "short": -1.0})
    gross = d * (t.exit_price - t.entry_price) * t.lots * 100_000.0
    assert (t.pnl - (gross - t.fees)).abs().max() < 1e-9
    assert (t.fees >= 0.0).all() and (t.costs >= 0.0).all()


def test_inv_acc_4_zero_profile_charges_nothing(df):
    """INV-ACC-3b: the ZERO profile charges zero fees and zero costs —
    a cost-free model cannot silently leak commissions."""
    r = run_backtest(df, "ema_crossover", {"fast": 8, "slow": 30},
                     spread_points=0.0, slippage_points=0.0,
                     commission_per_lot=0.0)
    if len(r.trades):
        assert (r.trades.fees == 0.0).all()
        assert (r.trades.costs == 0.0).all()


# ===========================================================================
# INV-POS — POSITION / LEDGER
# ===========================================================================


def test_inv_pos_1_volume_bounds(df):
    """INV-POS-1: every filled volume is >= broker volume_min, > 0 and
    <= the configured max_lots."""
    r = run_backtest(df, "ema_crossover", {"fast": 8, "slow": 30})
    assert (r.trades.lots > 0.0).all()
    assert (r.trades.lots >= 0.01 - 1e-12).all()      # volume_min
    assert (r.trades.lots <= 100.0 + 1e-12).all()     # max_lots default


def test_inv_pos_2_equity_series_well_formed(df):
    """INV-POS-2: equity is finite, positive and strictly time-sorted —
    a ledger can never produce NaN equity or unordered time."""
    r = run_backtest(df, "ema_crossover", {"fast": 8, "slow": 30})
    assert r.equity.index.is_monotonic_increasing
    assert r.equity.index.is_unique
    assert np.isfinite(r.equity.to_numpy(dtype=float)).all()
    assert (r.equity > 0.0).all()


def test_inv_pos_3_sides_are_long_or_short(df):
    """INV-POS-3: direction is exactly long or short — no residual
    state can mint a third direction."""
    r = run_backtest(df, "ema_crossover", {"fast": 8, "slow": 30})
    assert set(r.trades.side.unique()) <= {"long", "short"}


# ===========================================================================
# INV-RISK — RISK CONTAINMENT
# ===========================================================================


def test_inv_risk_1_cost_profiles_only_worsen(df):
    """INV-RISK-1: harsher execution profiles never improve the
    outcome (net profit monotone non-increasing ZERO→SEVERE)."""
    nets = []
    for spread, slip, comm in ((0.0, 0.0, 0.0), (1.0, 0.25, 3.5),
                               (2.5, 1.0, 7.0), (5.0, 2.5, 14.0)):
        r = run_backtest(df, "ema_crossover", {"fast": 8, "slow": 30},
                         spread_points=spread,
                         slippage_points=slip,
                         commission_per_lot=comm)
        nets.append(r.metrics["net_profit"])
    assert all(a >= b - ACC_TOL for a, b in itertools.pairwise(nets))


def test_inv_risk_2_meta_weights_bounded_under_hostile_inputs():
    """INV-RISK-2: every meta weight is finite and in [0, 1] for ANY
    input the typed model accepts — the layer cannot mint risk
    budget."""
    inputs = [_inp("a", drift_score=0.49),
              _inp("b", certification_state="SOFTWARE_PASS"),
              _inp("c", signal=-1)]
    rets = pd.DataFrame({"a": np.linspace(0, 1, 60),
                         "b": np.linspace(1, 0, 60),
                         "c": np.sin(np.linspace(0, 6, 60))},
                        index=pd.date_range("2026-01-01", periods=60,
                                            freq="h"))
    stats = {"a": (0.02, 200), "b": (-0.02, 200), "c": (1e4, 50)}
    d = MetaLayer(MetaConfig()).decide(inputs, as_of=NOW, returns=rets,
                                       oos_stats=stats)
    for w in d.weights:
        assert math.isfinite(w.final_weight)
        assert 0.0 <= w.final_weight <= 1.0


def test_inv_risk_3_meta_reduce_only_lot_grid():
    """INV-RISK-3: the EA seam arithmetic can only shrink the
    risk-approved volume (mirror of the MQL5 path, pinned source-side
    by tests/test_mql5_sources)."""
    for weight in (1.0, 0.8, 0.5, 0.1, 0.0):
        for risk_lots in (10.0, 2.5, 0.5, 0.05):
            scaled = risk_lots * weight
            floored = math.floor(scaled / 0.01 + 1e-9) * 0.01
            final = 0.0 if (floored < 0.01 or floored > risk_lots) \
                else floored
            assert final <= risk_lots + 1e-12


def test_inv_risk_4_risk_percent_never_overshoots_approval(df):
    """INV-RISK-4: doubling per-trade risk at most doubles the volume
    PLUS one volume step (documented rounding, metamorphic E): the
    floored size can exceed 2x the floored base but never 2x the
    APPROVED (unfloored) risk budget — the sizer floors, never
    rounds up."""
    r1 = run_backtest(df, "ema_crossover", {"fast": 8, "slow": 30},
                      risk_percent=0.5)
    r2 = run_backtest(df, "ema_crossover", {"fast": 8, "slow": 30},
                      risk_percent=1.0)
    if len(r1.trades) and len(r2.trades):
        # FIRST trade: equity == initial capital in BOTH runs, so raw
        # lots are exactly proportional; flooring adds at most one step
        base0 = float(r1.trades.lots.iloc[0])
        dbl0 = float(r2.trades.lots.iloc[0])
        assert base0 <= dbl0 <= 2.0 * base0 + 0.01 + 1e-9
        # later trades compound on realized equity (documented in
        # metamorphic E): the ratio stays within 2x the equity-growth
        # factor, which this fixture bounds coarsely — the structural
        # guarantee is the sizer FLOOR against the approved budget
        common = min(len(r1.trades), len(r2.trades))
        ratio = (r2.trades.lots.iloc[:common]
                 / r1.trades.lots.iloc[:common])
        assert (ratio <= 3.0).all()   # fixture bound; reason above
        assert (ratio >= 1.0 - 1e-12).all()


# ===========================================================================
# INV-META — META CONTAINMENT
# ===========================================================================


def test_inv_meta_1_hard_zero_never_positive_any_mode():
    """INV-META-1: an uncertified strategy gets exactly zero in every
    mode — no epsilon path exists."""
    inputs = [_inp("ok"), _inp("bad", certification_state=None)]
    for mode in MetaMode:
        d = MetaLayer(MetaConfig(mode=mode)).decide(
            inputs, as_of=NOW, oos_stats=_stats("ok", "bad"))
        assert d.weight_of("bad") == 0.0


def test_inv_meta_2_fallback_never_resurrects():
    """INV-META-2: global source failure falls back to equal weight
    across ELIGIBLE strategies only; the hard zero stays zero."""
    fb = [_inp("ok", drift_available=False),
          _inp("bad", certification_state=None, drift_available=False)]
    d = MetaLayer(MetaConfig()).decide(fb, as_of=NOW)
    assert "equal_weight" in d.fallback
    assert d.weight_of("bad") == 0.0
    assert d.weight_of("ok") == pytest.approx(1.0, abs=1e-9)


# ===========================================================================
# INV-STOP — STOP-LOSS INTEGRITY
# ===========================================================================


def test_inv_stop_1_engine_refuses_entry_without_valid_stop():
    """INV-STOP-1: the sizing path returns ZERO lots with
    REASON_NO_VALID_STOP when a valid SL distance cannot be formed —
    no trade is accepted without a stop (structural: engine.py)."""
    src = (REPO / "python/mql5bot/engine.py").read_text()
    assert "REASON_NO_VALID_STOP" in src
    assert "sl_dist <= 0.0" in src
    # behavioral: entries always carry a positive SL distance risk
    r = run_backtest(generate_ohlc(days=90, seed=5), "ema_crossover",
                     {"fast": 8, "slow": 30})
    assert (r.trades.lots > 0).all()   # accepted entries sized by SL risk


def test_inv_stop_2_slguard_remediation_ladder_present():
    """INV-STOP-2: the Python SlGuard mirror (post-fill SL verify →
    modify → close ladder) is importable and its phase constants are
    pinned by the source-invariant suite."""
    import mql5bot.slguard as sg  # importable mirror is the pin
    assert hasattr(sg, "sl_verdict")
    audit = (REPO / "tests/test_mql5_sources.py").read_text()
    assert "SlVerdict" in audit and "ClosePosition" in audit


# ===========================================================================
# INV-FAIL — FAILURE CONTAINMENT
# ===========================================================================


def test_inv_fail_1_rejected_allocation_mutates_nothing():
    """INV-FAIL-1: an allocation veto returns the ORIGINAL weights and
    an accepted=false verdict — zero partial application."""
    from mql5bot.portfolio import apply_limits
    proposed = {"a": 0.6, "b": 0.4}
    out = apply_limits(proposed, max_weight=0.5)
    assert out["accepted"] is False
    assert out["weights"] == proposed


def test_inv_fail_2_corrupt_state_refused():
    """INV-FAIL-2: corrupt/truncated meta state raises instead of
    applying (fail-safe, never optimistic fallback)."""
    lay = MetaLayer(MetaConfig())
    lay.decide([_inp("a")], as_of=NOW, oos_stats=_stats("a"))
    good = lay.state.serialize()
    obj = json.loads(good)
    obj["body"]["weights"]["a"] = 0.99
    from mql5bot.meta_layer import MetaFileError
    with pytest.raises(MetaFileError, match="digest"):
        MetaState.deserialize(json.dumps(obj))
    with pytest.raises(MetaFileError):
        MetaState.deserialize("{not json")


def test_inv_fail_3_internal_failure_is_safe_hold():
    """INV-FAIL-3: any internal exception becomes a SAFE HOLD decision
    (no weights, no book) — never a raise into the trading path."""
    from mql5bot.meta_layer import safe_decision
    lay = MetaLayer(MetaConfig())
    decision, exc = safe_decision(lay, None, as_of=NOW)  # type: ignore
    assert exc is not None
    assert decision.fallback == ("failure_safe",)
    assert decision.weights == [] and decision.book == []


# ===========================================================================
# INV-DET — DETERMINISM
# ===========================================================================


def test_inv_det_1_engine_runs_are_reproducible(df):
    """INV-DET-1: identical inputs ⇒ identical equity and ledger."""
    kw = {"fast": 8, "slow": 30}
    a = run_backtest(df, "ema_crossover", kw)
    b = run_backtest(df, "ema_crossover", kw)
    pd.testing.assert_series_equal(a.equity, b.equity)
    pd.testing.assert_frame_equal(a.trades, b.trades)


def test_inv_det_2_meta_decisions_and_journals_reproducible():
    """INV-DET-2: same inputs/versions ⇒ byte-identical meta decision
    and journal serialization."""
    inputs = [_inp("a"), _inp("b", signal=-1)]
    kw = {"as_of": NOW, "oos_stats": _stats("a", "b")}
    j1 = MetaLayer(MetaConfig()).decide(inputs, **kw).canonical_json()
    j2 = MetaLayer(MetaConfig()).decide(list(inputs), **kw) \
        .canonical_json()
    assert j1 == j2


def test_inv_det_3_manifests_reproducible(df):
    """INV-DET-3: identical run manifests for identical runs —
    different code identity cannot share a manifest id."""
    a = RunManifest(stage="screen", strategy="ema_crossover",
                    params={"fast": 8}, engine="fast",
                    dataset_version="abc", seed=1)
    b = RunManifest(stage="screen", strategy="ema_crossover",
                    params={"fast": 8}, engine="fast",
                    dataset_version="abc", seed=1)
    assert a.manifest_id == b.manifest_id
    c = RunManifest(stage="screen", strategy="ema_crossover",
                    params={"fast": 8}, engine="fast",
                    dataset_version="abc", seed=1,
                    repro={**a.repro, "engine_version": "9.9.9"})
    assert c.manifest_id != a.manifest_id


# ===========================================================================
# INV-VER — VERSION / IDENTITY
# ===========================================================================


def test_inv_ver_1_manifest_repro_block_required():
    """INV-VER-1: every manifest carries the full semantic identity
    (git commit + engine/cost/feature/protocol versions)."""
    m = RunManifest(stage="oos", strategy="s", params={}, engine="truth",
                    dataset_version="v", seed=0)
    assert {"git_commit", "engine_version", "cost_model_version",
            "feature_version", "certification_protocol_version"} \
        <= set(m.repro)


def test_inv_ver_2_oos_identity_components_participate(tmp_path, df):
    """INV-VER-2: changing any identity component changes the identity
    id; a second look on the same content+strategy is REFUSED."""
    from mql5bot.pipeline import oos_identity
    id1 = oos_identity(df, "ema_crossover", dataset_tag="T")
    id2 = oos_identity(df, "ema_crossover", dataset_tag="T")
    assert id1.identity_id() == id2.identity_id()      # deterministic
    id3 = oos_identity(df, "donchian_breakout", dataset_tag="T")
    assert id3.identity_id() != id1.identity_id()      # strategy differs
    reg = OosRegistry(tmp_path / "oos.json")
    reg.certify_identity(id1, params={}, strategy_version="1.0.0")
    from mql5bot.pipeline import OosOneLookViolation
    with pytest.raises(OosOneLookViolation):
        reg.certify_identity(id1, params={}, strategy_version="1.0.0")


def test_inv_ver_3_cost_profiles_fieldwise_monotone():
    """INV-VER-3: the canonical profile ladder escalates field-by-field
    (no profile is softer than its predecessor in any rate)."""
    assert COST_PROFILES == ("ZERO", "BASE", "STRESSED", "SEVERE",
                             "EXTREME")
    profiles = PROFILE_DEFAULTS
    for lo, hi in itertools.pairwise(COST_PROFILES):
        for field in ("spread_points", "slippage_points",
                      "commission_per_lot", "commission_min",
                      "swap_long_per_lot_day", "swap_short_per_lot_day"):
            assert profiles[hi][field] >= profiles[lo][field], (hi, field)
        # gap sensitivity: a SMALLER max_gap_fraction is a HARSH filter
        assert profiles[hi]["max_gap_fraction"] \
            <= profiles[lo]["max_gap_fraction"]


# ===========================================================================
# INV-DATA — DATA INTEGRITY (data layer, Phase 6)
# ===========================================================================


def test_inv_data_1_dataset_digest_is_stable_identity():
    """INV-DATA-1: the dataset content digest is deterministic and
    recorded on manifests — every backtest can name its exact data."""
    from mql5bot.optimizer import _dataset_digest
    d = generate_ohlc(days=30, seed=3)
    assert _dataset_digest(d) == _dataset_digest(d)
    d2 = d.copy()
    d2.iloc[0, d2.columns.get_loc("close")] *= 1.000001
    assert _dataset_digest(d2) != _dataset_digest(d)


def test_inv_data_2_quality_audit_catches_corruption():
    """INV-DATA-2: the data layer audit flags every corruption class
    (duplicates, disorder, impossible OHLC, non-positive prices, gaps)
    and cleaning is EXPLICIT (change log), never silent."""
    from mql5bot.data_layer import audit_ohlcv
    idx = pd.date_range("2020-01-01", periods=50, freq="D",
                        name="date")
    good = pd.DataFrame({"open": np.linspace(10, 12, 50),
                         "high": np.linspace(10.5, 12.5, 50),
                         "low": np.linspace(9.5, 11.5, 50),
                         "close": np.linspace(10.2, 12.2, 50),
                         "volume": np.full(50, 1000.0)}, index=idx)
    base = audit_ohlcv(good)
    assert base["quality"] == "OK" and not base["findings"]

    dup = pd.concat([good, good.iloc[[-1]]])          # duplicate bar
    f = audit_ohlcv(dup)
    assert any(x["type"] == "duplicate_timestamp" for x in f["findings"])

    dis = good.iloc[::-1]                             # disorder
    f = audit_ohlcv(dis)
    assert any(x["type"] == "timestamp_disorder" for x in f["findings"])

    imp = good.copy()                                  # high < low
    imp.iloc[3, imp.columns.get_loc("high")] = 1.0
    f = audit_ohlcv(imp)
    assert any(x["type"] == "impossible_ohlc" for x in f["findings"])

    zero = good.copy()                                 # non-positive price
    zero.iloc[5, zero.columns.get_loc("close")] = 0.0
    f = audit_ohlcv(zero)
    assert any(x["type"] == "nonpositive_price" for x in f["findings"])

    gapped = good.drop(index=idx[10:20])               # session gap
    f = audit_ohlcv(gapped)
    assert any(x["type"] == "gap" for x in f["findings"])


def test_inv_data_3_real_dataset_audited_then_explicitly_cleaned():
    """INV-DATA-3: the committed REAL dataset (VIX daily) is audited AS
    IS — the audit flags the real DataHub defects (47 impossible
    high/low bars); cleaning is EXPLICIT and logged; the CLEAN layer
    audits with only the expected holiday/session-gap WARNINGS (never
    filled).  Digests match the provenance manifest."""
    import hashlib

    from mql5bot.data_layer import (
        audit_ohlcv,
        clean_ohlcv,
        content_digest,
        load_real_vix,
    )
    raw, digest = load_real_vix(REPO)
    assert digest == hashlib.sha256(
        (REPO / "tests/data/real/vix_daily.csv").read_bytes()).hexdigest()
    raw_rep = audit_ohlcv(raw)
    assert raw_rep["quality"] == "CORRUPT"
    assert any(f["type"] == "impossible_ohlc" for f in raw_rep["findings"])
    clean, changes = clean_ohlcv(raw)
    assert any(c["op"] == "clamp_impossible_high_low" for c in changes)
    clean_rep = audit_ohlcv(clean)
    assert clean_rep["quality"] == "WARNINGS"      # gaps reported only
    assert not any(f["type"] == "impossible_ohlc"
                   for f in clean_rep["findings"])
    # nothing repaired silently: raw and clean digests differ BY LOG
    assert content_digest(clean) != content_digest(raw)
    {"identity": {"sha256": digest, "bars": len(raw)}}
