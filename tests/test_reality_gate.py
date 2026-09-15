"""AEGIS REALITY GATE — gold-standard execution-parity tests.

Mission: prove that the exact strategy and risk decision produced by
Aegis research is preserved down to the execution boundary.

Ladder proven HERE (sandbox):
    manifest determinism → fixture determinism → Python trace ↔ DSL
    trace EXACT agreement → indicator parity (Python ↔ DSL ↔ MQL5
    formula transcription) → sizing parity (Python sizer ↔ MQL5
    GetLots formula) → Meta seam only-reduces → kill-switch seam
    ordering → allocation round-trip → Python never executes orders.

Ladder owned by the TERMINAL OWNER (never fabricated here):
    MT5 compile → Strategy Tester → Python↔MT5 golden run
    (docs/AEGIS_REALITY_GATE_AUDIT.md §owner-protocol;
    docs/MT5_ROUNDTRIP.md ten-step loop).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))
sys.path.insert(0, str(REPO / "tools"))

GOLD = REPO / "artifacts" / "gold"
BUILD = REPO / "tools" / "build_gold_standard.py"


def _load(name: str) -> dict:
    return json.loads((GOLD / name).read_text())


@pytest.fixture(scope="module")
def gold_df() -> pd.DataFrame:
    df = pd.read_csv(GOLD / "gold_fixture.csv", index_col="time",
                     parse_dates=True)
    return df


@pytest.fixture(scope="module")
def manifest() -> dict:
    return _load("manifest.json")


# --------------------------------------------------- §59.1-3 determinism


def _rebuild(tmp_path: Path, git_commit: str) -> Path:
    out = tmp_path / git_commit
    r = subprocess.run([sys.executable, str(BUILD), "--out", str(out),
                        "--git-commit", git_commit],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return out


def test_gold_manifest_and_fixture_deterministic(tmp_path):
    """Same inputs → byte-identical manifest, fixture, traces (§59.1).

    The committed gold identity is FROZEN: rebuilding under the
    frozen commit pin must reproduce every committed artifact
    byte-for-byte — future code changes may never silently alter the
    Gold Standard (§4)."""
    frozen = json.loads((GOLD / "manifest.json").read_text())[
        "git_commit"]
    a = _rebuild(tmp_path, frozen)
    b = _rebuild(tmp_path, frozen)          # twice: builder determinism
    for name in ("manifest.json", "gold_fixture.csv",
                 "python_trace.json", "dsl_trace.json",
                 "expected_execution.json", "reconciliation.json",
                 "micro_both_touch.csv"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
        assert (GOLD / name).read_bytes() == (a / name).read_bytes(), \
            f"{name} drifted from the frozen gold standard"
    m = json.loads((a / "manifest.json").read_text())
    mh = hashlib.sha256((a / "manifest.json").read_bytes()).hexdigest()
    for artifact in ("python_trace.json", "dsl_trace.json",
                     "expected_execution.json", "reconciliation.json"):
        body = json.loads((a / artifact).read_text())
        assert body["manifest_hash"] == mh, artifact
    assert m["strategy_id"] == "ema_crossover_ref"
    assert m["seed"] == 0 and m["dataset_hash"]


# --------------------------------------------- §7 Python ↔ DSL agreement


def test_python_and_dsl_traces_agree_exactly():
    """§7 hard gate: indicator values, signals, SL/TP-driven trades and
    timing must agree EXACTLY before any MQL5 comparison (§59.15)."""
    py, dsl, recon = (_load("python_trace.json"), _load("dsl_trace.json"),
                      _load("reconciliation.json"))
    assert recon["python_vs_dsl"] == "MATCHED"
    assert dsl["signal_parity_vs_python"] is True
    for b_py, b_dsl in zip(py["bars"], dsl["bars"]):
        assert b_py["timestamp"] == b_dsl["timestamp"]
        assert b_py["desired_position"] == b_dsl["desired_position"]
        assert b_py["ema_fast"] == b_dsl["ema_fast"]
        assert b_py["ema_slow"] == b_dsl["ema_slow"]
        assert b_py["atr14"] == b_dsl["atr14"]
    assert py["trades"] == dsl["trades"]
    reasons = {t["exit_reason"] for t in py["trades"]}
    assert {"stop_loss", "take_profit"} <= reasons          # §5 legs
    sides = {t["side"] for t in py["trades"]}
    assert sides == {"long", "short"}                       # §5 legs


def test_warmup_is_nan_never_zero():
    """§5 invalid-signal leg: before the EMA30 seed the reference is
    NaN, and the desired position is 0 — never a fabricated value."""
    py = _load("python_trace.json")
    warm = py["bars"][:25]
    assert all(b["ema_slow"] is None for b in warm)
    assert all(b["desired_position"] == 0 for b in warm)


# ------------------------------------------------------- §20 causality


def test_future_mutation_never_changes_past_decisions(gold_df):
    """§59.4: mutating data strictly after t0 never changes the trace
    at or before t0 — on the gold fixture itself."""
    from mql5bot.strategies import STRATEGIES
    t0 = 70
    mut = gold_df.copy()
    mut.iloc[t0 + 5:, 0:4] = mut.iloc[t0 + 5:, 0:4] * 1.03 + 0.001
    fn, defaults = STRATEGIES["ema_crossover"]
    a = fn(gold_df, dict(defaults)).to_numpy()
    b = fn(mut, dict(defaults)).to_numpy()
    assert (a[:t0] == b[:t0]).all()


# ------------------------------------------- §61 both-touch micro (stop-first)


def test_both_touch_bar_resolves_stop_first():
    """§5.7/§61: one bar touching BOTH SL and TP must resolve as a
    stop (conservative), never as a take-profit."""
    rec = _load("python_trace.json")["scenario_both_touch"]
    assert rec["exit_reason"] == rec["expected_exit_reason"] \
        == "stop_loss"
    micro = pd.read_csv(GOLD / "micro_both_touch.csv", index_col="time",
                        parse_dates=True)
    bar = micro.iloc[35]
    # the giant bar really touched both levels (sanity of the fixture)
    assert bar["high"] > rec["entry_fill"] + 4.0 * rec["atr_at_entry"]
    assert bar["low"] < rec["entry_fill"] - 2.5 * rec["atr_at_entry"]


# ------------------------------------------------ §8 indicator parity


def test_indicator_parity_python_vs_mql5_ema_transcription(gold_df):
    """§8: EMA — Python reference vs a faithful transcription of the
    MT5 iMA(MODE_EMA) recursion.  Classification: WARMUP (seed differs:
    MT5 seeds ema[0]=price[0]; Python seeds ema[n-1]=SMA(n)).  After
    warmup the difference must decay to numerical noise, never stay
    structural.  ATR: both sides use Wilder with period 14 (identical
    recursion, identical seed) — asserted equal on the trace."""
    close = gold_df["close"].to_numpy()
    from mql5bot.indicators import atr as atr_py
    from mql5bot.indicators import ema as ema_py
    # MT5 iMA EMA transcription (alpha = 2/(period+1), seed price[0])
    def ema_mt5(x, period):
        alpha = 2.0 / (period + 1.0)
        out = np.full(len(x), np.nan)
        out[0] = x[0]
        for i in range(1, len(x)):
            out[i] = out[i - 1] + alpha * (x[i] - out[i - 1])
        return out
    f_py, f_mt5 = ema_py(close, 10), ema_mt5(close, 10)
    s_py, s_mt5 = ema_py(close, 30), ema_mt5(close, 30)
    tail = slice(60, len(close))          # well past both warmups
    assert np.allclose(f_py[tail], f_mt5[tail], atol=1e-9)
    assert np.allclose(s_py[tail], s_mt5[tail], atol=1e-9)
    # the seed difference exists (classified, not hidden) ...
    assert abs(f_py[9] - f_mt5[9]) > 1e-6
    # ... and decays: by bar 60 it is below the noise floor
    assert abs(f_py[60] - f_mt5[60]) < 1e-6
    # ATR: the trace values equal the canonical Wilder ATR(14)
    py = _load("python_trace.json")
    atr_ref = atr_py(gold_df["high"].to_numpy(),
                     gold_df["low"].to_numpy(), close, 14)
    got = [b["atr14"] for b in py["bars"]]
    for i, v in enumerate(got):
        if v is None:
            assert np.isnan(atr_ref[i])
        else:
            assert abs(v - atr_ref[i]) < 1e-9
    # MT5 side uses iATR(symbol, tf, 14) — Wilder, same period:
    # source pin (SignalEngine.mqh construction + EA defaults).
    se = (REPO / "mql5/Include/Mql5Bot/SignalEngine.mqh").read_text()
    assert "iATR(symbol, tf, 14)" in se
    assert "MODE_EMA" in se
    ea = (REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text()
    assert "InpFastEma     = 10;" in ea
    assert "InpSlowEma     = 30;" in ea
    assert "InpSlAtr      = 2.5;" in ea
    assert "InpTpAtr      = 4.0;" in ea


# --------------------------------------------- §12 sizing parity


def _mql5_getlots_transcription(spec, *, mode_value: float, equity: float,
                                stop_distance: float, max_lots: float,
                                profit_to_deposit: float = 1.0):
    """Faithful transcription of RiskManager.GetLots (SIZING_RISK_PERCENT_EQ
    path) over SymbolSpec.mqh primitives.  Kept line-by-line next to the
    MQL5 source; any divergence is a FINDING (§12)."""
    if stop_distance <= 0:
        return 0.0, "missing stop"
    # SpecEnforceMinStop: raise to min stop distance, round TO TICK
    min_dist = spec.stops_level_points * spec.point   # SpecMinStopDistance
    dist = max(stop_distance, min_dist)
    dist = round(dist / spec.tick_size) * spec.tick_size
    ticks = round(dist / spec.tick_size)              # SpecTicksOf
    loss_pl = ticks * spec.tick_value_loss * profit_to_deposit
    if loss_pl <= 0:
        return 0.0, "loss per lot <= 0"
    budget = equity * mode_value / 100.0
    raw = budget / loss_pl
    if budget <= 0 or raw <= 0:
        return 0.0, "budget <= 0"
    if raw < spec.volume_min:
        return 0.0, "below broker minimum volume"
    cap = min(max_lots, spec.volume_max,
              spec.volume_limit if spec.volume_limit > 0 else max_lots)
    if cap < spec.volume_min:
        return 0.0, "effective cap below broker minimum"
    step = spec.volume_step
    lots = min(raw, cap)
    floor = np.floor(lots / step + 1e-9) * step
    floor = max(floor, spec.volume_min)
    if floor > cap:
        floor = np.floor(cap / step + 1e-9) * step
        if floor < spec.volume_min:
            return 0.0, "volume normalisation failed"
    return float(floor), "ok"


def test_sizing_parity_python_sizer_vs_mql5_formula():
    """§12/§14: the canonical Python sizer and the MQL5 GetLots formula
    must agree on lots AND rejection semantics for identical inputs
    (grid over equity × stop distance × caps).  No hidden rounding."""
    from mql5bot.sizer import size_position
    from mql5bot.symbolspec import SymbolSpec
    base = {"name": "EURUSD", "digits": 5, "point": 1e-05,
            "tick_size": 1e-05, "tick_value_profit": 1.0,
            "tick_value_loss": 1.0, "contract_size": 100_000.0,
            "volume_min": 0.01, "volume_max": 100.0,
            "volume_step": 0.01, "volume_limit": 0.0,
            "stops_level_points": 0.0, "freeze_level_points": 0.0,
            "currency_profit": "USD"}
    cases = []
    for equity in (10_000.0, 250.0, 50_000.0):
        for stop in (0.0005, 0.0025, 0.0100):
            cases.append((dict(base), equity, stop, 10.0))
    cases.append((dict(base, volume_limit=0.5), 50_000.0, 0.0005, 10.0))
    cases.append((dict(base, volume_max=0.05), 50_000.0, 0.0005, 10.0))
    cases.append((dict(base, stops_level_points=20.0), 10_000.0,
                  0.00005, 10.0))
    for over, equity, stop, max_lots in cases:
        spec = SymbolSpec(**over)
        py = size_position(spec, mode="risk_percent_equity",
                           equity=equity, stop_distance=stop,
                           value=1.0, max_lots=max_lots)
        mt5_lots, mt5_why = _mql5_getlots_transcription(
            spec, mode_value=1.0, equity=equity, stop_distance=stop,
            max_lots=max_lots)
        if py.rejected:
            assert mt5_lots == 0.0, (over, equity, stop, py.reason)
            if py.reason == "below_min_volume":
                assert mt5_why == "below broker minimum volume"
        else:
            assert abs(py.lots - mt5_lots) < 1e-9, \
                (over, equity, stop, py.lots, mt5_lots)


def test_below_minimum_lots_never_become_orders():
    """§5.11/§15/§59.9: a risk-adequate size below the broker minimum
    is REJECTED (never bumped up) by the Python sizer, and the EA
    source must carry the same rule plus the Meta-seam drop rule."""
    from mql5bot.sizer import size_position
    from mql5bot.symbolspec import SymbolSpec
    spec = SymbolSpec(name="EURUSD", digits=5, point=1e-05,
                      tick_size=1e-05, tick_value_profit=1.0,
                      tick_value_loss=1.0, contract_size=100_000.0,
                      volume_min=0.10, volume_max=100.0,
                      volume_step=0.01, volume_limit=0.0,
                      stops_level_points=0.0, freeze_level_points=0.0,
                      currency_profit="USD")
    r = size_position(spec, mode="risk_percent_equity", equity=100.0,
                      stop_distance=0.0100, value=0.5)   # $0.50 risk
    assert r.rejected and r.reason == "below_min_volume"
    ea = (REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text()
    assert "below broker minimum volume" in \
        (REPO / "mql5/Include/Mql5Bot/RiskManager.mqh").read_text()
    assert "meta scale below broker minimum" in ea
    assert "would exceed the risk budget" in \
        (REPO / "mql5/Include/Mql5Bot/SymbolSpec.mqh").read_text()


# --------------------------------------------- §15 Meta seam parity


def test_meta_seam_only_reduces_and_drops():
    """§15: final lots ≤ risk-approved lots for every weight; the
    0.01/0.0 weights must DROP (never bump to volume_min).  Mirrors
    the EA's ScaleLots → floor → drop sequence; the EA ordering is
    source-pinned."""
    import math
    expected = _load("expected_execution.json")
    assert expected["sizing_mode"] == "risk_percent_equity"
    volume_min, step = 0.01, 0.01
    for row in expected["trades"]:
        approved = row["risk_approved_lots"]
        assert approved > 0
        for w, outcome in row["meta"].items():
            wf = float(w)
            raw = approved * min(max(wf, 0.0), 1.0)     # EA Clamp01
            final = math.floor(raw / step + 1e-9) * step
            if final < volume_min or final > approved:
                assert outcome["action"] == "DROP"
                assert outcome["final_lots"] == 0.0
            else:
                assert outcome["action"] == "SEND"
                assert abs(outcome["final_lots"] - final) < 1e-9
                assert outcome["final_lots"] <= approved
    # even weight 1.0 must never EXCEED the approval
    for row in expected["trades"]:
        assert row["meta"]["1.0"]["final_lots"] <= \
            row["risk_approved_lots"] + 1e-9
    # EA ordering pin: risk sizing → ScaleLots → floor → drop
    ea = (REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text()
    i_risk = ea.index("g_risk.GetLots")
    i_meta = ea.index("g_alloc.ScaleLots")
    i_floor = ea.index("metaLots = MathFloor")
    assert i_risk < i_meta < i_floor
    alloc = (REPO / "mql5/Include/Mql5Bot/Allocation.mqh").read_text()
    assert "return lots * w;" in alloc          # multiply only
    assert "Clamp01" in alloc


# --------------------------------------- §29/§30 kill-switch seam


def test_kill_switch_is_the_first_entry_gate_in_the_ea():
    """§29: the EMERGENCY_HALT veto sits BEFORE signal evaluation in
    the EA entry path — nothing downstream can bypass it.  State is
    hot-persisted (restart cannot clear it); reset is an explicit
    input."""
    ea = (REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text()
    i_gate = ea.index("if(!g_risk.AllowsNewTrades())")
    i_sig = ea.index("g_lastSignal = g_signal.Evaluate(g_strategy);")
    i_size = ea.index("g_risk.GetLots")
    i_send = ea.index("g_trade.OpenMarket")
    assert i_gate < i_sig < i_size < i_send
    rm = (REPO / "mql5/Include/Mql5Bot/RiskManager.mqh").read_text()
    assert "AllowsNewTrades() const { return m_state == ENGINE_NORMAL; }" \
        in rm
    # python side: the entry chain must apply the same veto
    from mql5bot.discovery.entry_chain import ChainContext, EntryRequest, govern_entry
    d = govern_entry(
        EntryRequest(origin="strategy", strategy_id="ema_crossover_ref",
                     symbol="EURUSD", side="long", requested_risk=0.01),
        ChainContext(kill_switch_state="EMERGENCY_HALT"))
    assert d.allowed is False
    assert d.veto_owner == "kill-switch"


# ---------------------------------- §16/§17 allocation round-trip


def test_gold_allocation_roundtrip(tmp_path):
    """§16: a real allocation artifact for the gold strategy round-trips
    through the documented writer/verifier; tampering, unknown ids and
    stale stamps are refused exactly as the EA reader refuses them
    (source pins included)."""
    from datetime import datetime, timezone

    from mql5bot.meta_layer import (
        MetaConfig,
        MetaFileError,
        MetaLayer,
        StrategyMetaInput,
        read_allocation_file,
        write_allocation_file,
    )
    sid = _load("manifest.json")["strategy_id"]
    inputs = [StrategyMetaInput(sid, "EURUSD", 1, "TREND_UP",
                                frozenset({"TREND_UP"}),
                                frozenset({"TREND_UP"}), frozenset(),
                                "VERIFIED", drift_available=True,
                                drift_score=0.0)]
    as_of = datetime(2024, 1, 2, tzinfo=timezone.utc)
    dec = MetaLayer(MetaConfig()).decide(inputs, as_of=as_of,
                                         returns=None,
                                         oos_stats={sid: (0.01, 50)})
    path = tmp_path / "allocation.json"
    write_allocation_file(dec, path)
    body = read_allocation_file(path, max_age_days=7,
                                now=datetime(2024, 1, 3,
                                             tzinfo=timezone.utc))
    entry = next(e for e in body["strategies"] if e["id"] == sid)
    assert 0.0 <= entry["weight"] <= 1.0
    assert body["stale"] is False
    # tamper → digest mismatch refused
    doc = json.loads(path.read_text())
    doc["body"]["strategies"][0]["weight"] = 0.99
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(doc))
    with pytest.raises(MetaFileError):
        read_allocation_file(bad, max_age_days=7,
                             now=datetime(2024, 1, 3, tzinfo=timezone.utc))
    # stale → flagged refused-for-sizing (EA: IsStale → base gate)
    stale_body = read_allocation_file(path, max_age_days=7,
                                      now=datetime(2025, 1, 2,
                                                   tzinfo=timezone.utc))
    assert stale_body["stale"] is True
    ea = (REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text()
    assert 'InpAllocationFile = "in/allocation.json"' in ea
    alloc = (REPO / "mql5/Include/Mql5Bot/Allocation.mqh").read_text()
    assert "unknown id under ACTIVE meta: no trade" in alloc
    assert "ALLOCATION_STALE_DAYS" in alloc


# ------------------------------------------ §19 Python intent boundary


def test_python_never_sends_orders():
    """§19: the Python tree may model ExecutionIntent/decisions but must
    contain no broker-execution vocabulary anywhere."""
    banned = ("OrderSend", "order_send", "CTrade", "positions_create",
              "send_order")
    hits = []
    for py in (REPO / "python" / "mql5bot").rglob("*.py"):
        if py.name == "security.py":
            continue      # sanctioned: the order-send DETECTOR lives here
        text = py.read_text()
        for token in banned:
            if token in text:
                hits.append(f"{py.name}:{token}")
    assert hits == []


# ---------------------------------------------- §41/§60 reconciliation


def test_reconciliation_state_is_explicit():
    """§41/§60: every MT5-dependent field is PENDING_OWNER — never
    fabricated — while the Python↔DSL fields are MATCHED."""
    recon = _load("reconciliation.json")
    assert recon["python_vs_dsl"] == "MATCHED"
    assert recon["python_vs_mql5"] == "PENDING_OWNER"
    assert recon["python_vs_mt5_tester"] == "PENDING_OWNER"
    for row in recon["trades"]:
        assert row["mt5"] is None
        assert row["mt5_status"] == "PENDING_OWNER"
        assert row["python"] == row["dsl"]
    assert (GOLD / "mt5_report.json").exists() is False
    assert (GOLD / "mt5_journal.txt").exists() is False


def test_signal_timing_contract_frozen(manifest):
    """§11: the timing contract is explicit and matches the EA source
    (closed-bar signal → first tick of next bar → market order)."""
    tc = manifest["signal_timing_contract"]
    assert tc["signal_on"] == "closed bar (shift 1)"
    assert tc["action_at"] == "next bar open (EA: first tick of new bar)"
    assert tc["order_type"] == "market"
    assert tc["both_touch_rule"] == \
        "SL assumed hit first (conservative)"
    se = (REPO / "mql5/Include/Mql5Bot/SignalEngine.mqh").read_text()
    assert "EMA(m_hFast, 1)" in se and "EMA(m_hSlow, 1)" in se
    ea = (REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5").read_text()
    assert "if(desired < 0 && !InpAllowShort)" in ea
    # flip: close now, enter next bar (no same-bar reversal)
    assert "signal flipped" in ea and "CloseAllPositions" in ea
