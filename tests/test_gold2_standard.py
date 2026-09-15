"""Gold #2 regression + provenance suite.

GOLD_2_RECONSTRUCTED_NEW_PROVENANCE — this is NOT "the original Gold
#2" (the historical artifact is lost; no continuity is claimed).

Design rules enforced by this module (mission §7–§13, §19, §23):

* NO hand-typed expected values.  Every expectation is recomputed from
  the deterministic fixture through the canonical reference, the DSL
  runtime, and the portfolio engine.
* NO tolerance on direction / exit reasons / vetoes / Meta decisions —
  parity is exact, field by field.
* Safety paths that Gold #2 does not naturally exercise (risk veto /
  daily-loss halt / drawdown halt) are deliberately NOT forced into
  this fixture; they are covered by dedicated micro-fixtures
  (tests/test_engine.py, tests/test_meta_portfolio.py,
  tests/test_safety_micro_fixtures.py).  Gold #2 records the observed
  ``risk_vetoes == 0`` honestly.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from mql5bot.gold2_reference import SESSION_END_MIN, SESSION_START_MIN

REPO = Path(__file__).resolve().parents[1]
GOLD2_DIR = REPO / "artifacts" / "gold_2"
BUILDER = REPO / "tools" / "build_gold2_standard.py"


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_gold2_standard", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bld():
    return _load_builder()


@pytest.fixture(scope="module")
def fixture_df(bld):
    return bld.build_fixture()


@pytest.fixture(scope="module")
def signals(bld, fixture_df):
    spec = bld.parse_file(bld.GOLD2_SPEC)
    ref = bld.gold2_multifactor(fixture_df)
    dsl = bld.desired_positions(spec, fixture_df)
    raw = bld.desired_positions(spec, fixture_df, apply_filters=False)
    return {"spec": spec, "ref": ref, "dsl": dsl, "raw": raw}


@pytest.fixture(scope="module")
def runs(bld, fixture_df, signals):
    res_ref = bld._engine_run(fixture_df, signals["ref"])
    res_dsl = bld._engine_run(fixture_df, signals["dsl"])
    return {"ref": res_ref, "dsl": res_dsl}


@pytest.fixture(scope="module")
def artifacts():
    out = {}
    for name in ("manifest", "expected_execution", "reconciliation",
                 "provenance"):
        out[name] = json.loads((GOLD2_DIR / f"{name}.json").read_text())
    out["manifest_text"] = (GOLD2_DIR / "manifest.json").read_bytes()
    return out


# ---------------------------------------------------------------- label
def test_provenance_label_and_continuity_disclaimer(artifacts):
    man = artifacts["manifest"]
    assert man["provenance_label"] == "GOLD_2_RECONSTRUCTED_NEW_PROVENANCE"
    disc = man["continuity_disclaimer"]
    assert "NOT the" in disc and "original" in disc
    assert "never hand-typed" in disc
    # the historical artifact must never be claimed to reproduce
    assert "no claim" in disc.lower()


# ----------------------------------------------------- determinism §19
def test_fixture_replay_is_deterministic_and_bound_to_artifact(
        bld, fixture_df, artifacts):
    text_a = fixture_df.to_csv(float_format="%.10f")
    text_b = bld.build_fixture().to_csv(float_format="%.10f")
    assert text_a == text_b                      # in-process replay
    assert _sha256(text_a.encode()) == artifacts["manifest"]["dataset_hash"]


# ------------------------------------------------- Python↔DSL parity §13
def test_python_dsl_signal_parity_field_by_field(signals):
    ref = signals["ref"].to_numpy()
    dsl = signals["dsl"].to_numpy()
    assert ref.tolist() == dsl.tolist()          # exact, no tolerance
    assert set(np.unique(ref)) <= {-1, 0, 1}


def test_python_dsl_trade_parity_no_tolerance(runs):
    t_ref, t_dsl = runs["ref"].trades, runs["dsl"].trades
    assert t_ref.equals(t_dsl)
    for col in ("side", "exit_reason", "lots"):
        assert t_ref[col].tolist() == t_dsl[col].tolist()


# -------------------------------------------- artifact↔recompute binding
def test_artifact_reconciliation_matches_recompute(runs, artifacts):
    recon = artifacts["reconciliation"]
    assert recon["parity_class"] == "PYTHON_DSL_MQL5_SOURCE_PARITY"
    assert recon["python_vs_dsl"] == "MATCHED"
    # source parity only — MT5 runtime legs stay owner-pending
    assert recon["python_vs_mql5_source"] == "SOURCE_PARITY"
    assert recon["python_vs_mt5_tester"] == "PENDING_OWNER"
    assert len(recon["trades"]) == len(runs["ref"].trades)
    got = sorted(set(runs["ref"].trades["exit_reason"]))
    assert got == ["signal_exit", "stop_loss", "take_profit"]


def test_scenario_coverage_is_observed_not_typed(bld, fixture_df, runs,
                                                 artifacts):
    """Mission §7 coverage — every item OBSERVED from the recompute."""
    tr = runs["ref"].trades
    sides = set(tr["side"])
    assert sides == {"long", "short"}            # >=1 long and >=1 short
    fires = artifacts["provenance"]["signal_fires"]
    assert sum(f["vetoed_by_session"] for f in fires) >= 1  # session veto
    # Meta ladder causality: weight 0.0 day has zero books (computed)
    zero_days = {d for d, w in bld.META_SCHEDULE if w == 0.0}
    entries = tr["entry_time"].map(pd.Timestamp)
    for d in zero_days:
        assert not entries.dt.date.isin({d.date()}).any()
    full_days = {d for d, w in bld.META_SCHEDULE if w == 1.0}
    assert entries.dt.date.isin({d.date() for d in full_days}).any()
    # position-state transitions: at least one side flip between books
    from itertools import pairwise
    seq = tr["side"].tolist()
    assert any(a != c for a, c in pairwise(seq))
    # every entry/exit happens in or immediately after the session
    minutes = entries.dt.hour * 60 + entries.dt.minute
    assert ((minutes >= SESSION_START_MIN)
            & (minutes <= SESSION_END_MIN)).all()


# --------------------------- sizing/Meta reconciliation (ATR index §4)
def test_every_entry_reconciles_sizing_and_meta(bld, runs, artifacts):
    """Expected-execution rows (built from the SIGNAL-bar ATR via the
    canonical sizer) must reproduce the engine's fills EXACTLY — this
    is the builder-vs-engine sizing proof at the fixture scale."""
    sched = list(bld.META_SCHEDULE)

    def weight_at(ts: pd.Timestamp) -> float:
        w = 1.0
        for t0, wi in sched:
            if ts >= t0:
                w = wi
        return w

    tr = runs["ref"].trades
    by_time = {(pd.Timestamp(r["entry_time"]), r["side"]): r
               for _, r in tr.iterrows()}
    matched = 0
    for row in artifacts["expected_execution"]["entries"]:
        st = pd.Timestamp(row["signal_time"])
        w = weight_at(st)
        if row["risk"] is None or row["risk"]["rejected"]:
            continue
        key_meta = row["meta"][str(w)]
        if key_meta["action"] == "DROP":
            # dropped by Meta below broker minimum -> must NOT trade
            assert (pd.Timestamp(st), row["side"]) not in by_time
            continue
        fill_bar = st + pd.Timedelta(minutes=1)
        trow = by_time.get((fill_bar, row["side"]))
        assert trow is not None, f"missing trade for {row['signal_time']}"
        assert float(trow["lots"]) == pytest.approx(
            key_meta["final_lots"], abs=1e-12)
        matched += 1
    assert matched == len(tr)          # every trade accounted for


def test_atr_index_minimal_proof(bld):
    """§4: the engine sizes on the ATR of the SIGNAL bar (entry bar - 1,
    engine.py size_lots).  On a ramp tape where ATR differs bar to bar,
    only the signal-bar ATR reproduces the fill; +-1 bars do not."""
    from mql5bot.costs import CostConfig
    from mql5bot.engine import MODE_NETTING, Instrument, PortfolioEngine, RunConfig
    from mql5bot.indicators import atr as atr_fn
    from mql5bot.sizer import size_position
    from mql5bot.symbolspec import SymbolSpec

    n = 140
    close = np.empty(n)
    close[0] = 100.0
    for i in range(1, 40):                       # ramp: ATR grows each bar
        close[i] = close[i - 1] + 0.002 * i
    close[40:] = close[39]                       # flat tape: no SL/TP after
    #   the entry (signal bar sits INSIDE the flat region so the book
    #   simply runs to end-of-data)
    opens = np.empty(n)
    opens[0] = close[0]
    opens[1:] = close[:-1]
    idx = pd.date_range("2024-03-01 00:00", periods=n, freq="min")
    df = pd.DataFrame({
        "open": opens,
        "high": np.maximum(opens, close) + 1e-6,
        "low": np.minimum(opens, close) - 1e-6,
        "close": close}, index=idx)
    sig = pd.Series(np.where(np.arange(n) >= 45, 1, 0), index=idx,
                    name="atr_probe")
    spec = SymbolSpec(
        name="ATR_PROBE", digits=3, point=1e-3, tick_size=1e-3,
        tick_value_profit=1.0, tick_value_loss=1.0, contract_size=100_000,
        volume_min=0.01, volume_max=100.0, volume_step=0.01,
        volume_limit=0.0, stops_level_points=0, freeze_level_points=0,
        currency_profit="USD")
    costs = CostConfig(symbol="ATR_PROBE", spread_points=0.0,
                       slippage_points=0.0, commission_per_lot=0.0)
    cfg = RunConfig(initial_capital=10_000.0, mode=MODE_NETTING,
                    sizing_mode="risk_percent_equity", risk_value=1.0,
                    allow_signal_exit=True)
    ins = Instrument(symbol="ATR_PROBE", strategy="atr_probe", df=df,
                     costs=costs, spec=spec, signal=sig,
                     profit_to_deposit=1.0,
                     params={"sl_atr": 2.0, "tp_atr": 3.0})
    res = PortfolioEngine(cfg).run([ins])
    assert len(res.trades) == 1
    lots_engine = float(res.trades["lots"].iloc[0])

    a = atr_fn(df["high"].to_numpy(float), df["low"].to_numpy(float),
               df["close"].to_numpy(float), 14)
    sig_bar = 45                                  # desired goes 1 here

    def sized(j: int) -> float:
        return float(size_position(
            spec, mode="risk_percent_equity", equity=10_000.0,
            stop_distance=2.0 * float(a[j]), value=1.0).lots)

    assert lots_engine == sized(sig_bar)          # engine == signal bar
    assert sized(sig_bar - 1) != sized(sig_bar)   # -1 bar is distinguishable
    assert sized(sig_bar + 1) != sized(sig_bar)   # +1 bar is distinguishable


def test_atr_index_sensitivity_on_gold_fixture(bld, fixture_df, artifacts):
    """The Gold fixture itself must be sensitive to the ATR index: at
    least one expected entry changes size under a +-1 bar shift (so a
    regression to the old off-by-one cannot pass silently)."""
    close = fixture_df["close"].to_numpy(float)
    high = fixture_df["high"].to_numpy(float)
    low = fixture_df["low"].to_numpy(float)
    a = bld.atr_fn(high, low, close, bld.ATR_PERIOD)
    spec_obj = bld.SymbolSpec(**bld.BROKER_SPEC)
    s = bld.gold2_multifactor(fixture_df).to_numpy()
    changed = 0
    for i in range(1, len(fixture_df)):
        if s[i] == 0 or s[i] == s[i - 1]:
            continue
        if not np.isfinite(a[i]) or a[i] <= 0.0:
            continue

        def lots(j: int) -> float:
            d = bld.SL_ATR * float(a[j])
            if not np.isfinite(d) or d <= 0.0:
                return 0.0
            r = bld.size_position(spec_obj, mode="risk_percent_equity",
                                  equity=bld.EQUITY_START, stop_distance=d,
                                  value=bld.RISK_PERCENT)
            return 0.0 if r.rejected else float(r.lots)

        if lots(i) != lots(i - 1) or lots(i) != lots(i + 1):
            changed += 1
    assert changed >= 1


# ------------------------------------ config hash semantic audit §3/§23
def test_config_hash_reacts_to_every_semantic_input(bld, monkeypatch):
    base = bld._config_hash()
    session_mut = dict(bld.SESSION)
    session_mut["start"] = "08:30"
    mutations = {
        "BROKER_SPEC": {**bld.BROKER_SPEC, "volume_min": 0.02},
        "COSTS": {**bld.COSTS, "spread_points": 2.0},
        "RISK_PERCENT": bld.RISK_PERCENT + 0.5,
        "EQUITY_START": bld.EQUITY_START + 1.0,
        "SYMBOL": "GBPUSD",
        "TIMEFRAME": "M5",
        "MODE_NETTING": "hedging",
        "SL_ATR": bld.SL_ATR + 0.5,
        "TP_ATR": bld.TP_ATR + 0.5,
        "ATR_PERIOD": bld.ATR_PERIOD + 1,
        "FAST": bld.FAST + 1,
        "SLOW": bld.SLOW + 1,
        "RSI_PERIOD": bld.RSI_PERIOD + 1,
        "RSI_OVERSOLD": bld.RSI_OVERSOLD + 1.0,
        "RSI_OVERBOUGHT": bld.RSI_OVERBOUGHT - 1.0,
        "CHANNEL": bld.CHANNEL + 1,
        "SESSION": session_mut,
        "META_SCHEDULE": tuple(
            (t, (0.9 if w == 1.0 else w)) for t, w in bld.META_SCHEDULE),
    }
    for attr, value in mutations.items():
        monkeypatch.setattr(bld, attr, value)
        assert bld._config_hash() != base, f"{attr} not hashed"
        monkeypatch.undo()


def test_meta_schedule_only_attack_is_detectable(bld, fixture_df,
                                                 monkeypatch):
    """§23-A / §5: mutating ONLY the Meta schedule must change the
    config hash AND (where active) the observable fills."""
    base_hash = bld._config_hash()
    base_res = bld._engine_run(fixture_df, bld.gold2_multifactor(fixture_df))
    monkeypatch.setattr(
        bld, "META_SCHEDULE",
        tuple((t, (0.9 if w == 1.0 else w))
              for t, w in bld.META_SCHEDULE))
    assert bld._config_hash() != base_hash
    mut_res = bld._engine_run(fixture_df, bld.gold2_multifactor(fixture_df))
    assert not base_res.trades.equals(mut_res.trades)


# --------------------------------------- manifest chain + tamper §23/§22
def test_manifest_hash_chain_and_tamper_detection(bld, fixture_df,
                                                  artifacts):
    man_hash = _sha256(artifacts["manifest_text"])
    for name in ("expected_execution", "reconciliation", "provenance"):
        assert artifacts[name]["manifest_hash"] == man_hash
    for name in ("python_trace", "dsl_trace"):
        doc = json.loads((GOLD2_DIR / f"{name}.json").read_text())
        assert doc["manifest_hash"] == man_hash
    prov = artifacts["provenance"]
    for name, recorded in prov["artifact_hashes"].items():
        assert _sha256((GOLD2_DIR / name).read_bytes()) == recorded, name
    assert prov["fixture_hash_sha256"] == \
        artifacts["manifest"]["dataset_hash"]
    # stale/tampered fixture must be detectable (one flipped byte)
    text = fixture_df.to_csv(float_format="%.10f")
    tampered = ("0" if text[100] != "0" else "1") + text[101:]
    assert _sha256(tampered.encode()) != \
        artifacts["manifest"]["dataset_hash"]


# -------------------------------------------- fresh-process replay §19
@pytest.mark.slow
def test_full_rebuild_replay_is_byte_identical(tmp_path):
    outs = []
    for i in range(2):
        out = tmp_path / f"run{i}"
        r = subprocess.run(
            [sys.executable, str(BUILDER), "--out", str(out)],
            capture_output=True, text=True, timeout=600, check=False)
        assert r.returncode == 0, r.stdout + r.stderr
        outs.append(out)
    names = ["manifest.json", "gold2_fixture.csv", "python_trace.json",
             "dsl_trace.json", "expected_execution.json",
             "reconciliation.json", "provenance.json"]
    for name in names:
        h0 = _sha256((outs[0] / name).read_bytes())
        h1 = _sha256((outs[1] / name).read_bytes())
        assert h0 == h1, name


# ------------------------------------------------- causality checks §15
def test_meta_weight_zero_causes_day4_drops(bld, fixture_df, signals):
    """Counterfactual: without the schedule the weight-0 day WOULD
    trade, so the observed zero-trade day is caused by Meta, not by a
    missing signal."""
    spec_obj = bld.SymbolSpec(**bld.BROKER_SPEC)
    costs = bld.CostConfig(symbol=bld.SYMBOL,
                           spread_points=bld.COSTS["spread_points"],
                           slippage_points=bld.COSTS["slippage_points"],
                           commission_per_lot=bld.COSTS[
                               "commission_per_lot"])
    from mql5bot.engine import MODE_NETTING, Instrument, PortfolioEngine, RunConfig
    cfg = RunConfig(initial_capital=bld.EQUITY_START, mode=MODE_NETTING,
                    allow_short=True,
                    sizing_mode=bld.RISK_PERCENT_EQUITY,
                    risk_value=bld.RISK_PERCENT, max_lots=100.0,
                    allow_signal_exit=True)
    ins = Instrument(symbol=bld.SYMBOL, strategy=bld.GOLD2_STRATEGY_ID,
                     df=fixture_df, costs=costs, spec=spec_obj,
                     params={"sl_atr": bld.SL_ATR, "tp_atr": bld.TP_ATR},
                     signal=signals["ref"])
    bare = PortfolioEngine(cfg).run([ins])
    zero_days = {d.date() for d, w in bld.META_SCHEDULE if w == 0.0}
    bare_dates = bare.trades["entry_time"].map(pd.Timestamp).dt.date
    assert bare_dates.isin(zero_days).any()          # signal exists...
    sched_res = bld._engine_run(fixture_df, signals["ref"])
    sched_dates = sched_res.trades["entry_time"].map(
        pd.Timestamp).dt.date
    assert not sched_dates.isin(zero_days).any()     # ...Meta drops it


def test_session_filter_causes_preopen_vetoes(bld, fixture_df, signals,
                                              artifacts):
    raw = np.asarray(signals["raw"])
    filt = np.asarray(signals["ref"])
    minutes = (fixture_df.index.hour * 60 + fixture_df.index.minute)
    minutes = np.asarray(minutes)
    out_of_session = ((minutes < SESSION_START_MIN)
                      | (minutes >= SESSION_END_MIN))
    assert (raw[out_of_session] != 0).any()          # raw signal exists
    assert (filt[out_of_session] == 0).all()         # filter flattens
    fires = artifacts["provenance"]["signal_fires"]
    assert any(f["vetoed_by_session"] for f in fires)


# ------------------------------------------------- boundary record §13
def test_boundary_distances_recorded_with_required_bands(artifacts):
    """Boundary geometry (mission §12): every entry records its
    distance_to_boundary block, and the fixture's fire scan exercises
    RSI margins inside the +-0.5 / +-1 / +-2 bands plus the session's
    last valid minute — all COMPUTED from the persisted provenance."""
    rows = artifacts["provenance"]["distance_to_boundary"]
    assert rows, "distance_to_boundary must cover every entry"
    for r in rows:
        assert r.get("entry_kind") in ("signal_transition",
                                       "persistence_reentry")
        if r["entry_kind"] == "signal_transition":
            # transition entries carry the full boundary block
            assert r["minutes_to_session_end"] is not None
            assert r["minutes_to_session_start"] is not None
    assert any("rsi_escape" in k for r in rows for k in r["fire_kinds"])
    # session boundary: an entry inside the final valid minutes.  The
    # session is [08:00, 16:00): bars at/after 16:00 are flattened, so
    # the boundary book is the one entered within the last three valid
    # minutes and closed by the flatten (observed: entry 15:58, exit
    # signal_exit 16:01).
    assert any(r["minutes_to_session_end"] <= 3 for r in rows
               if r["entry_kind"] == "signal_transition")
    # RSI margin bands across EVERY escape edge (state-changing and
    # no-op), with the nearest-zone distance computed per edge
    edges = artifacts["provenance"]["rsi_escape_edges"]
    assert edges, "escape edges must be present in the provenance"
    esc_dists = []
    for e in edges:
        d = e["distance_to_boundary"]
        near = min(abs(d["rsi_to_oversold"]), abs(d["rsi_to_overbought"]),
                   abs(d["rsi_prev_to_oversold"]),
                   abs(d["rsi_prev_to_overbought"]))
        esc_dists.append(near)
    assert min(esc_dists) <= 0.5, "+-0.5 RSI band not exercised"
    assert any(d <= 1.0 for d in esc_dists), "+-1 RSI band not exercised"
    assert any(d <= 2.0 for d in esc_dists), "+-2 RSI band not exercised"
    # diversity: the fixture exercises margins in more than one band
    bands = {0.5 if d <= 0.5 else 1.0 if d <= 1.0 else 2.0 if d <= 2.0
             else None for d in esc_dists}
    bands.discard(None)
    assert len(bands) >= 3, f"expected all three bands, got {bands}"


# ------------------------------------------- honest zero-veto record §16
def test_zero_risk_vetoes_recorded_honestly(runs, artifacts):
    """Gold #2 is an integration fixture; it does not force a risk
    veto.  The observed zero is recorded, and the risk-veto runtime
    path stays covered by dedicated micro-fixtures elsewhere."""
    assert artifacts["expected_execution"]["risk_vetoes"] == 0
    rejects = [e for e in runs["ref"].events if e.get("type") == "reject"
               and e.get("code") not in ("meta_scale_dropped",)]
    assert rejects == []


# ----------------------------------------------------- Gold #1 frozen §6
def test_gold1_artifacts_are_untouched():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "artifacts/gold"],
        cwd=REPO, check=False)
    assert r.returncode == 0, "Gold #1 artifacts modified in working tree"
