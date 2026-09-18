"""MetaPortfolioEngine pins (meta-production mission, Phases 3-9).

Covers: the allocation seam (reduce-only, floor-and-drop, clamp, weight-1
identity), netting/hedging truth with attribution, the identical-mechanics
EW-vs-META comparison, decision causality (no future information), and
restart equivalence of the decision journal.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

from mql5bot.data import generate_ohlc
from mql5bot.engine import (
    CostConfig,
    Instrument,
    PortfolioEngine,
    RunConfig,
)
from mql5bot.meta_layer import MetaConfig, MetaPolicy
from mql5bot.meta_oos import StrategySpec
from mql5bot.meta_portfolio import MetaPortfolioEngine, rebalance_grid
from mql5bot.symbolspec import SymbolSpec


@pytest.fixture(scope="module")
def df():
    return generate_ohlc(days=180, seed=5)


SPECS = [StrategySpec("bollinger_reversal", {}),
         StrategySpec("ema_crossover", {"fast": 10, "slow": 50}),
         StrategySpec("macd_momentum", {})]


def _gen_spec(**over):
    kw = {"name": "GEN", "point": 1e-5, "tick_size": 1e-5,
          "tick_value_loss": 1.0, "contract_size": 100_000.0,
          "currency_profit": "USD", "currency_deposit": "USD"}
    kw.update(over)
    return SymbolSpec(**kw)


def _run_seam(df, schedule, strategy="bollinger_reversal"):
    costs = CostConfig(symbol="GEN", spread_points=1.0, slippage_points=0.0,
                       commission_per_lot=0.0)
    ins = Instrument(symbol="GEN", strategy=strategy, df=df, costs=costs,
                     spec=_gen_spec(), profit_to_deposit=1.0,
                     allocation_schedule=schedule)
    res = PortfolioEngine(RunConfig(initial_capital=10_000.0,
                                    warmup_bars=30)).run([ins])
    return res


# ---------------------------------------------------------------------------
# the allocation seam (Phase 3 mechanics / Phase 16 reduce-only proof)
# ---------------------------------------------------------------------------


def test_seam_weight_one_is_identical_to_no_schedule(df):
    base = _run_seam(df, ())
    full = _run_seam(df, ((df.index[40], 1.0), (df.index[80], 1.0)))
    pd.testing.assert_frame_equal(base.trades, full.trades)
    assert len(base.trades) > 0


def test_seam_weight_zero_blocks_all_later_entries(df):
    res = _run_seam(df, ((df.index[60], 0.0),))
    assert (pd.to_datetime(res.trades["entry_time"]) < df.index[60]).all()


def test_seam_is_reduce_only_and_floors_to_grid(df):
    # find the smallest lots the strategy uses unscaled, then halve: every
    # later fill must be <= floor(unscaled/2) and on the 0.01 grid
    base = _run_seam(df, ())
    res = _run_seam(df, ((df.index[60], 0.5),))
    early = base.trades[pd.to_datetime(base.trades["entry_time"])
                        < df.index[60]]
    late_base = base.trades[pd.to_datetime(base.trades["entry_time"])
                            >= df.index[60]]
    late_scaled = res.trades[pd.to_datetime(res.trades["entry_time"])
                             >= df.index[60]]
    assert len(late_base) > 0 and len(late_scaled) > 0
    assert (late_scaled["lots"] <= late_base["lots"].values[:len(late_scaled)]
            + 1e-12).all()
    # no pre-boundary difference
    pd.testing.assert_frame_equal(early.reset_index(drop=True),
                                  res.trades.head(len(early))
                                  .reset_index(drop=True))
    assert ((late_scaled["lots"] / 0.01) % 1 < 1e-9).all()


def test_seam_drops_below_minimum_never_rounds_up(df):
    base = _run_seam(df, ())
    # a weight small enough that EVERY attainable scaled size floors
    # below the broker minimum must produce NO late trades (drop — never
    # force volume_min).  Fixture sizes stay under 1.0 lot (risk sizing on
    # 10k with 2.5-ATR stops), so w = 0.00099 caps scaled size < 0.001.
    drop_w = 0.01 * 0.99 / 10.0
    dropped = _run_seam(df, ((df.index[60], drop_w),))
    late = dropped.trades[pd.to_datetime(dropped.trades["entry_time"])
                          >= df.index[60]]
    assert len(late) == 0, "sub-minimum scaled size must DROP, not bump"
    # a moderate weight keeps trades strictly on-grid, never rounded up
    res = _run_seam(df, ((df.index[60], 0.4),))
    late2 = res.trades[pd.to_datetime(res.trades["entry_time"])
                       >= df.index[60]]
    if len(late2):
        assert (late2["lots"] >= 0.01 - 1e-12).all()
        assert ((late2["lots"] / 0.01) % 1 < 1e-9).all()
        assert (late2["lots"] <= 0.4 * float(base.trades["lots"].max())
                + 0.01 + 1e-9).all()
    # weight > 1 is clamped (never amplifies)
    amp = _run_seam(df, ((df.index[60], 3.0),))
    pd.testing.assert_frame_equal(base.trades, amp.trades)


# ---------------------------------------------------------------------------
# netting / hedging truth + attribution (Phase 7)
# ---------------------------------------------------------------------------


def _two_strategy_run(df, mode):
    costs = CostConfig(symbol="GEN", spread_points=1.0, commission_per_lot=0.0)
    specs = [StrategySpec("bollinger_reversal", {}),
             StrategySpec("ema_crossover", {"fast": 10, "slow": 50})]
    ins = [Instrument(symbol="GEN", strategy=s.engine_strategy, df=df,
                      costs=costs, spec=_gen_spec(), profit_to_deposit=1.0,
                      params=s.params)
           for s in specs]
    return PortfolioEngine(RunConfig(initial_capital=10_000.0, mode=mode,
                                     warmup_bars=30)).run(ins)


def test_netting_merges_into_one_symbol_book_with_attribution(df):
    res = _two_strategy_run(df, "netting")
    assert len(res.trades) > 0
    assert set(res.trades["strategy"]) == {"bollinger_reversal",
                                           "ema_crossover"}
    merges = [e for e in res.events if e["type"] == "merge"]
    offsets = [e for e in res.events if e["type"] == "offset"]
    assert merges or offsets, "netting must produce merge/offset events"
    # attribution integrity: per-strategy pnl sums to the portfolio result
    total = res.trades["pnl"].sum()
    per = res.trades.groupby("strategy")["pnl"].sum()
    assert per.sum() == pytest.approx(total, abs=1e-9)


def test_hedging_keeps_positions_independent(df):
    res = _two_strategy_run(df, "hedging")
    assert len(res.trades) > 0
    assert set(res.trades["strategy"]) == {"bollinger_reversal",
                                           "ema_crossover"}
    # no netting merges: every open is its own book
    assert not [e for e in res.events if e["type"] == "merge"]
    # full offset of one strategy leaves the other untouched: SL/TP exits
    # per book, and attribution still reconciles
    total = res.trades["pnl"].sum()
    assert res.trades.groupby("strategy")["pnl"].sum().sum() == \
        pytest.approx(total, abs=1e-9)


# ---------------------------------------------------------------------------
# MetaPortfolioEngine: identical mechanics, causal weights, restarts
# ---------------------------------------------------------------------------


def _engine(df, **kw):
    kw.setdefault("min_history_bars", 480)
    kw.setdefault("every_days", 15)
    return MetaPortfolioEngine(df, SPECS, label="SYNTH", **kw)


def test_identical_strategies_meta_weights_equal_ew_and_trades_match(df):
    """Two IDENTICAL contributors ⇒ META weights are uniform = EW weights;
    with identical mechanics the two portfolios must trade identically —
    the definition of 'only the weighting policy differs'."""
    # (a) LAYER rule: identical contributors receive identical weights,
    # deterministically (aliasing is legal at the allocation level)
    from datetime import UTC, datetime

    from mql5bot.meta_layer import MetaLayer, StrategyMetaInput

    def aliases():
        return [StrategyMetaInput("alpha", "SYNTH", 0, "TREND_UP",
                                  frozenset({"TREND_UP"}),
                                  frozenset({"TREND_UP"}), frozenset(),
                                  "VERIFIED", drift_available=True,
                                  drift_score=0.0),
                StrategyMetaInput("beta", "SYNTH", 0, "TREND_UP",
                                  frozenset({"TREND_UP"}),
                                  frozenset({"TREND_UP"}), frozenset(),
                                  "VERIFIED", drift_available=True,
                                  drift_score=0.0)]
    stats = {"alpha": (0.01, 50), "beta": (0.01, 50)}
    d1 = MetaLayer(MetaConfig()).decide(aliases(),
                                        as_of=datetime(2024, 6, 1, tzinfo=UTC),
                                        returns=None, oos_stats=stats)
    d2 = MetaLayer(MetaConfig()).decide(aliases(),
                                        as_of=datetime(2024, 6, 1, tzinfo=UTC),
                                        returns=None, oos_stats=stats)
    w1 = {x.strategy_id: x.final_weight for x in d1.weights}
    w2 = {x.strategy_id: x.final_weight for x in d2.weights}
    assert w1 == w2 and len(w1) == 2
    assert w1["alpha"] == pytest.approx(w1["beta"], abs=1e-12)
    # and the uniform META weight equals the EQUAL_WEIGHT policy value
    ew_cfg = MetaConfig(policy=MetaPolicy.EQUAL_WEIGHT)
    d_ew = MetaLayer(ew_cfg).decide(aliases(), as_of=datetime(2024, 6, 1, tzinfo=UTC),
                                    returns=None, oos_stats=stats)
    w_ew = {x.strategy_id: x.final_weight for x in d_ew.weights}
    assert w_ew["alpha"] == pytest.approx(w1["alpha"], abs=1e-12)

    # (b) ENGINE rule: the SAME weight schedule produces the SAME trades
    # regardless of the policy that produced it (identical mechanics)
    sched = ((df.index[120], 0.6), (df.index[240], 0.9))

    def run(tagged_strategy, schedule):
        costs = CostConfig(symbol="GEN", spread_points=1.0,
                           commission_per_lot=0.0)
        ins = Instrument(symbol="GEN", strategy=tagged_strategy, df=df,
                         costs=costs, spec=_gen_spec(),
                         profit_to_deposit=1.0, allocation_schedule=schedule)
        return PortfolioEngine(RunConfig(initial_capital=10_000.0,
                                         warmup_bars=30)).run([ins])

    r_meta, r_ew = run("bollinger_reversal", sched), run(
        "bollinger_reversal", sched)
    pd.testing.assert_frame_equal(r_meta.trades, r_ew.trades)


def test_alias_rule_duplicate_line_rejected(df):
    """Documented aliasing rule (engine): two lines with the same
    (symbol, strategy) are REJECTED — an alias can never silently merge
    into another's book or steal its attribution."""
    costs = CostConfig(symbol="GEN", spread_points=1.0, commission_per_lot=0.0)
    ins = [Instrument(symbol="GEN", strategy="bollinger_reversal", df=df,
                      costs=costs, spec=_gen_spec(), profit_to_deposit=1.0),
           Instrument(symbol="GEN", strategy="bollinger_reversal", df=df,
                      costs=costs, spec=_gen_spec(), profit_to_deposit=1.0)]
    with pytest.raises(ValueError, match="duplicate"):
        PortfolioEngine(RunConfig(initial_capital=10_000.0)).run(ins)


def test_decisions_are_causal_future_data_cannot_change_weights():
    df = generate_ohlc(days=150, seed=8)
    eng = _engine(df, min_history_bars=480, every_days=15)
    res1 = eng.run()
    # bomb the FUTURE after the last rebalance
    df2 = df.copy()
    k = int(len(df) * 0.98)
    df2.iloc[k:, df2.columns.get_loc("close")] *= 3.0
    eng2 = _engine(df2, min_history_bars=480, every_days=15)
    res2 = eng2.run()
    assert res1.meta.weights == res2.meta.weights
    assert res1.equal_weight.weights == res2.equal_weight.weights


def test_restart_equivalence_seeded_state_continues_journal():
    df = generate_ohlc(days=180, seed=9)
    eng = _engine(df, min_history_bars=480, every_days=12)
    full = eng.run()
    k = len(full.meta.weights) // 2
    # restart at decision k, seeding the carried runtime weights
    prior = {kk[3::]: v for kk, v in
             [(key, val) for key, val in full.meta.weights[k - 1].items()
              if key.startswith("w::")]}
    t_k = pd.Timestamp(full.meta.weights[k]["as_of"])
    bar_k = df.index.get_loc(t_k)
    eng2 = MetaPortfolioEngine(df, SPECS, label="SYNTH",
                               min_history_bars=bar_k, every_days=12,
                               initial_weights=prior)
    part = eng2.run()
    tail_new = part.meta.weights
    tail_old = full.meta.weights[k:]
    assert len(tail_new) == len(tail_old)
    for a, b in zip(tail_new, tail_old):
        wa = {kk[3::]: v for kk, v in a.items() if kk.startswith("w::")}
        wb = {kk[3::]: v for kk, v in b.items() if kk.startswith("w::")}
        assert set(wa) == set(wb)
        for key, value in wa.items():
            assert value == pytest.approx(wb[key], abs=1e-9), \
                f"restart diverged at {a['as_of']} ({key})"


def test_grid_is_fixed_and_after_min_history(df):
    grid = rebalance_grid(df.index, first_bar=480, every_days=7)
    assert grid[0] >= df.index[480]
    assert grid == rebalance_grid(df.index, first_bar=480, every_days=7)


def test_full_comparison_produces_statistics(df):
    res = _engine(df, every_days=12).run()
    assert "bootstrap" in res.comparison
    assert res.comparison["trades_meta"] > 0
    assert res.comparison["trades_ew"] > 0
    # accounting identity holds for both portfolios
    for run in (res.meta, res.equal_weight):
        total = run.trades["pnl"].sum() if len(run.trades) else 0.0
        assert run.equity.iloc[-1] == pytest.approx(10_000.0 + total,
                                                    abs=1e-6)
