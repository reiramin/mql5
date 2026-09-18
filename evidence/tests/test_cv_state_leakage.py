"""Adversarial state-leakage tests for purged CPCV (Phase 3 hardening).

These tests formalise the distinction between DATA leakage (observations
from a fold's test region entering its training score) and STATE leakage
(state created by observations outside a scored span influencing that
span's simulation: equity-based sizing, daily-loss halts, permanent
drawdown halts, open-position carry, exposure caps).

The implementation under test must evaluate every scored span on an
ISOLATED, cold-start simulation whose state derives only from data
allowed by the fold.  The adversarial property asserted everywhere:

    For every fold whose test region contains ALL modified bars, the
    training configuration selection and the training (IS) scores must
    remain EXACTLY unchanged when only the test region changes — while
    that fold's test score MUST change (the modification is really seen).

Each trigger test additionally proves the modification really flows
through engine STATE by demonstrating that a full-sample-stateful
backtest (the pre-hardening design: one simulation, trades masked per
fold) DOES change its masked IS scores — i.e. these tests would catch
the leaky design they guard against.
"""

import itertools

import numpy as np
import pandas as pd
import pytest
from mql5bot.backtest import run_backtest
from mql5bot.fast_engine import run_fast
from mql5bot.pipeline import (
    _block_edges,
    _complement_spans,
    _embargoed_test_spans,
    _entry_index_map,
    _pnl_per_bar,
    _sharpe_of_pnl,
    _warmup_allowed,
    purged_cv_stage,
)

NSPLITS = 4
CFG_A = {"fast": 8, "slow": 24}
CFG_B = {"fast": 20, "slow": 64}
PARAMS = [CFG_A, CFG_B]
RUN_KW = {"risk_percent": 1.0, "max_lots": 5.0, "spread_points": 1.0,
          "commission_per_lot": 7.0}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _trend_frame(n: int = 720, seed: int = 11,
                 drift: float = 0.00035) -> pd.DataFrame:
    """Strongly trending random walk: ema_crossover trades throughout."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    px = 1.10 * np.exp(np.cumsum(rng.normal(drift, 0.0009, n)))
    o = px * (1 + rng.normal(0, 1.5e-5, n))
    c = px * (1 + rng.normal(0, 1.5e-5, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 1.5e-5, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 1.5e-5, n)))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c},
                        index=idx)


def _modify_block(df: pd.DataFrame, n_splits: int, block: int,
                  mode: str) -> pd.DataFrame:
    """Return a copy of ``df`` where ONLY block ``block``'s prices change.

    ``mode='crash'``  — a violent ~45% drawdown ramp (triggers dd halts,
                        daily-loss halts, shrinks equity-based sizing);
    ``mode='rally'``  — a violent monotone ~+45% ramp (keeps longs open
                        across the block boundary, inflates equity);
    ``mode='mixed'``  — rally then crash (huge profit then huge loss).
    """
    out = df.copy()
    n = len(df)
    lo, hi = _block_edges(n, n_splits)[block]
    k = np.arange(hi - lo)
    if mode == "crash":
        factor = 1.0 - 0.45 * (k / max(1, hi - lo - 1))
    elif mode == "rally":
        factor = 1.0 + 0.45 * (k / max(1, hi - lo - 1))
    elif mode == "mixed":
        half = max(1, (hi - lo) // 2)
        factor = np.concatenate([
            1.0 + 0.30 * (np.arange(half) / max(1, half - 1)),
            (1.30) * (1.0 - 0.55 * (np.arange(hi - lo - half)
                                    / max(1, hi - lo - half - 1))),
        ])
    elif mode == "spike":
        # fast +40% in the first third, then flat at the spike level
        third = max(1, (hi - lo) // 3)
        factor = np.concatenate([
            1.0 + 0.40 * (np.arange(third) / max(1, third - 1)),
            np.full(hi - lo - third, 1.40),
        ])
    elif mode in ("profit", "loss"):
        # explicit aliases: huge profit = rally-like doubling, huge loss
        # = crash-like halving (kept distinct from the halt triggers)
        sign = 1.0 if mode == "profit" else -1.0
        factor = 1.0 + sign * 0.60 * (k / max(1, hi - lo - 1))
    else:
        raise ValueError(mode)
    for col in ("open", "high", "low", "close"):
        out.iloc[lo:hi, out.columns.get_loc(col)] = \
            df[col].to_numpy()[lo:hi] * factor
    return out


def _fold(out: dict, test_blocks: tuple[int, ...]) -> dict:
    for f in out["manifest"].artifacts["folds"]:
        if tuple(f["test_blocks"]) == tuple(test_blocks):
            return f
    raise AssertionError(f"fold {test_blocks} missing")


def _full_sample_is_scores(df: pd.DataFrame, params_list, **kw) -> dict:
    """EXACT replica of the pre-hardening design: one full-sample stateful
    backtest per configuration; per-fold leaky-trade masking on the
    realised trades; IS Sharpe over the remaining train bars.  Used ONLY
    to demonstrate that the adversarial modifications genuinely flow
    through engine state — the new stage must NOT reproduce it."""
    n = len(df)
    n_splits = kw.pop("n_splits")
    embargo_bars = kw.pop("embargo_bars")
    edges = _block_edges(n, n_splits)
    pos = _entry_index_map(df.index)
    n_test = n_splits // 2
    per_cfg = []
    for params in params_list:
        res = run_backtest(df, "ema_crossover", params, **kw)
        pnl = _pnl_per_bar(res.trades, pos, n)
        eb = np.asarray([pos.get(t, -1) for t in res.trades["entry_time"]])
        xb = np.asarray([pos.get(t, -1) for t in res.trades["exit_time"]])
        per_cfg.append((pnl, eb, xb))
    out = {}
    for tb in itertools.combinations(range(n_splits), n_test):
        emb = [(max(0, edges[b][0] - embargo_bars),
                min(n, edges[b][1] + embargo_bars)) for b in tb]
        in_test = np.zeros(n, dtype=bool)
        for lo, hi in emb:
            in_test[lo:hi] = True
        scores = []
        for pnl, eb, xb in per_cfg:
            leaky = np.zeros(max(eb.size, 0), dtype=bool)
            for lo, hi in emb:
                leaky |= (xb > lo) & (eb < hi)
            arr = np.zeros(n)
            keep_idx = eb[~leaky]
            if keep_idx.size:
                np.add.at(arr, keep_idx, pnl[keep_idx])
            scores.append(_sharpe_of_pnl(arr[~in_test]))
        out[tb] = scores
    return out


# ---------------------------------------------------------------------------
# Geometry helpers (embargo margins, complement spans, warmup truncation)
# ---------------------------------------------------------------------------


def test_embargo_spans_expand_merge_and_train_complement():
    n = 400
    edges = _block_edges(n, 4)  # (0,100) (100,200) (200,300) (300,400)
    # blocks 1 and 2 adjacent: embargoed spans must merge into one
    spans = _embargoed_test_spans(edges, (1, 2), n, 10)
    assert spans == [(90, 310)]
    # complement excludes the whole embargoed region
    assert _complement_spans(n, spans) == [(0, 90), (310, 400)]
    # non-adjacent test blocks stay separate spans
    spans = _embargoed_test_spans(edges, (0, 3), n, 5)
    assert spans == [(0, 105), (295, 400)]
    assert _complement_spans(n, spans) == [(105, 295)]
    # zero embargo: plain blocks
    assert _embargoed_test_spans(edges, (1, 2), n, 0) == [(100, 300)]
    assert _complement_spans(n, [(100, 300)]) == [(0, 100), (300, 400)]


def test_warmup_never_reaches_test_interior():
    n = 400
    interior = np.zeros(n, dtype=bool)
    interior[100:200] = True  # block 1 interior
    # span starts directly at the test edge: bar 199 is interior -> 0
    assert _warmup_allowed(200, 50, interior) == 0
    # 10 bars past the edge: only the 10 non-interior bars may warm up
    assert _warmup_allowed(210, 50, interior) == 10
    # fully clear of the interior: full warmup
    assert _warmup_allowed(260, 50, interior) == 50
    # span inside the interior itself (a test span): warmup stops at its
    # own edge immediately
    assert _warmup_allowed(150, 50, interior) == 0
    # span at frame start: no history
    assert _warmup_allowed(0, 50, interior) == 0


# ---------------------------------------------------------------------------
# MASTER adversarial test — the blocker's literal scenario
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["mixed", "crash", "rally"])
def test_modified_test_segment_cannot_change_training(mode):
    """Modify ONLY a later test segment (huge profit AND huge loss, dd /
    daily-loss / position-cap / equity-sizing triggers).  For every fold
    whose test region contains the modified bars and whose train spans
    are clear of them: identical selection, identical IS scores; the
    fold's OOS test score must change (the modification is really seen)."""
    df_a = _trend_frame(n=720)
    df_b = _modify_block(df_a, NSPLITS, 3, mode)
    modified_lo, modified_hi = 540, 720  # block 3

    kw = {"n_splits": NSPLITS, "embargo_bars": 6, "warmup_bars": 60,
          "engine": "truth", "seed": 0, **RUN_KW}
    out_a = purged_cv_stage(df_a, "ema_crossover", PARAMS, **kw)
    out_b = purged_cv_stage(df_b, "ema_crossover", PARAMS, **kw)
    folds_a = {tuple(f["test_blocks"]): f
               for f in out_a["manifest"].artifacts["folds"]}
    folds_b = {tuple(f["test_blocks"]): f
               for f in out_b["manifest"].artifacts["folds"]}

    checked = 0
    for blocks, fa in folds_a.items():
        fb = folds_b[blocks]
        train_covers_modified = any(
            lo < modified_hi and hi > modified_lo
            for lo, hi in fa["train_spans"])
        if not train_covers_modified:
            # the fold sees the modified segment ONLY as test data
            assert fa["selected"] == fb["selected"], blocks
            assert fa["is_scores"] == fb["is_scores"], blocks
            assert fa["oos_sharpe"] != fb["oos_sharpe"], (
                "modification must be visible to the test score")
            checked += 1
    assert checked == 3  # folds (0,3), (1,3), (2,3)


# ---------------------------------------------------------------------------
# Trigger-specific adversarial tests (1-5)
# ---------------------------------------------------------------------------


def _run_pair(df_a, df_b, block, params_list=None, **stage_kw):
    """Stage the pair; return folds keyed by test blocks."""
    kw = {"n_splits": NSPLITS, "embargo_bars": 6, "warmup_bars": 60,
          "engine": "truth", "seed": 0, **RUN_KW}
    kw.update(stage_kw)
    params = params_list or PARAMS
    out_a = purged_cv_stage(df_a, "ema_crossover", params, **kw)
    out_b = purged_cv_stage(df_b, "ema_crossover", params, **kw)
    fa = {tuple(f["test_blocks"]): f
          for f in out_a["manifest"].artifacts["folds"]}
    fb = {tuple(f["test_blocks"]): f
          for f in out_b["manifest"].artifacts["folds"]}
    return fa, fb


def _assert_fold_invariant(fa, fb, blocks):
    assert fa[blocks]["selected"] == fb[blocks]["selected"], blocks
    assert fa[blocks]["is_scores"] == fb[blocks]["is_scores"], blocks


def _assert_fold_oos_changes(fa, fb, blocks):
    assert fa[blocks]["oos_sharpe"] != fb[blocks]["oos_sharpe"], blocks


def test_adversarial_1_drawdown_trigger_state():
    """Modified test block triggers the PERMANENT drawdown kill switch.
    A full-sample stateful run suppresses every later train-block trade
    (state leak the pre-hardening design suffered); the fold-isolated
    stage keeps training scores identical."""
    df_a = _trend_frame()
    df_b = _modify_block(df_a, NSPLITS, 1, "crash")
    kw = {"risk_percent": 1.0, "max_lots": 5.0, "max_drawdown_pct": 5.0,
          "spread_points": 1.0, "commission_per_lot": 7.0}

    # mechanism: in the full-sample B run the crash fires the permanent
    # halt inside block 1, so NO trade can enter in the later train
    # block 2 — while A's run still trades there.
    n = len(df_a)
    b2 = _block_edges(n, NSPLITS)[2]
    res_a = run_backtest(df_a, "ema_crossover", CFG_A, **kw)
    res_b = run_backtest(df_b, "ema_crossover", CFG_A, **kw)
    ent_a = {str(t): i for i, t in enumerate(df_a.index)}
    ent_b = {str(t): i for i, t in enumerate(df_b.index)}
    trades_b2_a = sum(b2[0] <= ent_a[r] < b2[1]
                      for r in res_a.trades["entry_time"])
    trades_b2_b = sum(b2[0] <= ent_b[r] < b2[1]
                      for r in res_b.trades["entry_time"])
    assert trades_b2_a > 0, "baseline must trade in the later train block"
    assert trades_b2_b == 0, "the halt must suppress block-2 trades in B"
    assert (res_b.trades["exit_reason"] == "max_drawdown").any()

    # counterfactual: the full-sample masked design IS contaminated
    fs_a = _full_sample_is_scores(df_a, PARAMS, n_splits=NSPLITS,
                                  embargo_bars=6, **kw)
    fs_b = _full_sample_is_scores(df_b, PARAMS, n_splits=NSPLITS,
                                  embargo_bars=6, **kw)
    assert fs_a[(1, 3)] != fs_b[(1, 3)], (
        "trigger must genuinely flow through full-sample state")

    fa, fb = _run_pair(df_a, df_b, 1, max_drawdown_pct=5.0)
    # folds with block 1 in test: training identical, OOS changes
    for blocks in ((0, 1), (1, 2), (1, 3)):
        _assert_fold_invariant(fa, fb, blocks)
        _assert_fold_oos_changes(fa, fb, blocks)


def test_adversarial_2_equity_dependent_sizing():
    """Modified test block inflates/deflates equity; risk-percent sizing
    scales later train-block lots in a full-sample run (leak), while the
    isolated stage's training scores are unchanged."""
    df_a = _trend_frame()
    df_b = _modify_block(df_a, NSPLITS, 1, "rally")
    kw = {"risk_percent": 1.0, "max_lots": 5.0, "spread_points": 1.0,
          "commission_per_lot": 7.0}
    fs_a = _full_sample_is_scores(df_a, PARAMS, n_splits=NSPLITS,
                                  embargo_bars=6, **kw)
    fs_b = _full_sample_is_scores(df_b, PARAMS, n_splits=NSPLITS,
                                  embargo_bars=6, **kw)
    assert fs_a[(1, 3)] != fs_b[(1, 3)]
    fa, fb = _run_pair(df_a, df_b, 1)
    for blocks in ((0, 1), (1, 2), (1, 3)):
        _assert_fold_invariant(fa, fb, blocks)
        _assert_fold_oos_changes(fa, fb, blocks)


def test_adversarial_3_daily_loss_state():
    """Modified test block fires the daily-loss halt (halts NEW trades
    until the next server-day reset).  Full-sample masked IS scores
    change; the isolated stage's do not."""
    df_a = _trend_frame()
    df_b = _modify_block(df_a, NSPLITS, 1, "mixed")
    kw = {"risk_percent": 1.0, "max_lots": 5.0, "max_daily_loss_pct": 1.0,
          "spread_points": 1.0, "commission_per_lot": 7.0}
    res = run_backtest(df_b, "ema_crossover", CFG_A, **kw)
    daily_hits = res.trades["exit_reason"] == "daily_loss_limit"
    assert not res.trades.empty and bool(daily_hits.any()), (
        "the modification must fire the daily-loss halt at all")
    fs_a = _full_sample_is_scores(df_a, PARAMS, n_splits=NSPLITS,
                                  embargo_bars=6, **kw)
    fs_b = _full_sample_is_scores(df_b, PARAMS, n_splits=NSPLITS,
                                  embargo_bars=6, **kw)
    assert fs_a[(1, 3)] != fs_b[(1, 3)]
    fa, fb = _run_pair(df_a, df_b, 1, max_daily_loss_pct=1.0)
    for blocks in ((0, 1), (1, 2), (1, 3)):
        _assert_fold_invariant(fa, fb, blocks)
        _assert_fold_oos_changes(fa, fb, blocks)


def test_adversarial_4_open_position_carry():
    """A position opened in the modified test block that STAYS OPEN
    across the block boundary carries engine state (side, entry, SL/TP,
    entry fee) into the NEXT span in a full-sample run — so the next
    span's outcomes (train data for folds where it trains) depend on a
    test segment's state.  The isolated stage starts every span flat, so
    its training scores are unchanged."""
    wide = {"sl_atr": 3.0, "tp_atr": 6.0}
    params_wide = [{**CFG_A, **wide}, {**CFG_B, **wide}]
    base = _trend_frame(drift=0.00035)
    # crash in A carries a SHORT across the boundary; rally in B carries
    # a LONG — the carried book itself is test-segment state
    df_a = _modify_block(base, NSPLITS, 1, "crash")
    df_b = _modify_block(base, NSPLITS, 1, "rally")
    kw = {"risk_percent": 1.0, "max_lots": 5.0,
          "spread_points": 1.0, "commission_per_lot": 7.0}
    n = len(base)
    lo, hi = _block_edges(n, NSPLITS)[1]
    def _carried(df):
        res = run_backtest(df, "ema_crossover", params_wide[0], **kw)
        ent = {str(t): i for i, t in enumerate(df.index)}
        return [(ent[e], ent[x], r["side"]) for e, x, r in
                zip(res.trades["entry_time"], res.trades["exit_time"],
                    res.trades.to_dict("records"))
                if lo <= ent.get(e, -1) < hi and ent.get(x, -1) >= hi]
    carried_a, carried_b = _carried(df_a), _carried(df_b)
    assert carried_a and carried_b, (
        "the carry path must be active in both runs")
    assert {c[2] for c in carried_a} != {c[2] for c in carried_b}, (
        "the carried state itself must be modified by the test segment")

    fs_a = _full_sample_is_scores(df_a, params_wide, n_splits=NSPLITS,
                                  embargo_bars=6, **kw)
    fs_b = _full_sample_is_scores(df_b, params_wide, n_splits=NSPLITS,
                                  embargo_bars=6, **kw)
    assert fs_a[(1, 3)] != fs_b[(1, 3)]
    fa, fb = _run_pair(df_a, df_b, 1, params_list=params_wide, **kw)
    for blocks in ((0, 1), (1, 2), (1, 3)):
        _assert_fold_invariant(fa, fb, blocks)
        _assert_fold_oos_changes(fa, fb, blocks)


def test_adversarial_5_position_cap_via_inflated_equity():
    """Exposure cap state: the modified test block multiplies equity, so
    risk-percent sizing WANTS more volume than ``max_lots`` allows; in a
    full-sample run the later train-block trades sit pinned at the cap
    (lots == max_lots) while A's do not — the isolated stage keeps its
    training scores identical.  (Portfolio-level exposure caps — max
    positions, notional/heat shares — are the same state class; see the
    engine state audit in docs/CV_STATE_CONTRACT.md.)"""
    df_a = _trend_frame()
    df_b = _modify_block(df_a, NSPLITS, 1, "rally")
    kw = {"risk_percent": 4.0, "max_lots": 0.05,  # cap binds on equity
          "spread_points": 1.0, "commission_per_lot": 7.0}
    n = len(df_a)
    t_lo, t_hi = _block_edges(n, NSPLITS)[2]  # train block AFTER block 1
    def _capped_lots(df):
        res = run_backtest(df, "ema_crossover", CFG_A, **kw)
        ent = {str(t): i for i, t in enumerate(df.index)}
        return sum(
            1 for _, r in res.trades.iterrows()
            if t_lo <= ent.get(r["entry_time"], -1) < t_hi
            and abs(r["lots"] - 0.05) < 1e-9)
    assert _capped_lots(df_b) > 0 and _capped_lots(df_a) != _capped_lots(df_b)
    fs_a = _full_sample_is_scores(df_a, PARAMS, n_splits=NSPLITS,
                                  embargo_bars=6, **kw)
    fs_b = _full_sample_is_scores(df_b, PARAMS, n_splits=NSPLITS,
                                  embargo_bars=6, **kw)
    assert fs_a[(1, 3)] != fs_b[(1, 3)]
    fa, fb = _run_pair(df_a, df_b, 1, risk_percent=4.0, max_lots=0.05)
    for blocks in ((0, 1), (1, 2), (1, 3)):
        _assert_fold_invariant(fa, fb, blocks)
        _assert_fold_oos_changes(fa, fb, blocks)


# ---------------------------------------------------------------------------
# Warmup semantics of the engines (fold-isolation primitive)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runner", [run_backtest, run_fast])
def test_engine_warmup_blocks_entries_and_state(runner):
    """warmup_bars blocks entries on [0, warmup_bars): equity stays at
    initial capital, no trades can exist with entry inside the warmup —
    the primitive that makes span-isolated CPCV state cold-started."""
    df = _trend_frame(n=300)
    res = runner(df, "ema_crossover", CFG_A, warmup_bars=120, **RUN_KW)
    pos = {str(t): i for i, t in enumerate(df.index)}
    assert len(res.trades) > 0
    assert min(pos[r] for r in res.trades["entry_time"]) >= 120
    assert float(res.equity.iloc[:120].min()) == 10_000.0
    assert float(res.equity.iloc[:120].max()) == 10_000.0
    # identical prefix must be trade-free for any warmup length
    res2 = runner(df, "ema_crossover", CFG_A, warmup_bars=250, **RUN_KW)
    assert min(pos[r] for r in res2.trades["entry_time"]) >= 250
    with pytest.raises(ValueError):
        runner(df, "ema_crossover", CFG_A, warmup_bars=-1, **RUN_KW)


def test_stage_records_state_model_and_fold_geometry():
    df = _trend_frame(n=480)
    out = purged_cv_stage(df, "ema_crossover", PARAMS, n_splits=4,
                          embargo_bars=5, warmup_bars=40, engine="truth",
                          seed=0, **RUN_KW)
    art = out["manifest"].artifacts
    sm = art["state_model"]
    for key in ("mode", "engine_init", "capital_state", "position_state",
                "daily_loss_state", "drawdown_state", "strategy_state",
                "parameter_state", "warmup_policy"):
        assert sm[key]
    assert sm["mode"] == "isolated_span_cold_start"
    assert art["n_folds"] == 6
    edges = _block_edges(len(df), 4)
    f = art["folds"][0]
    assert f["test_spans"] == [list(s) for s in
                               _embargoed_test_spans(edges,
                                                     tuple(f["test_blocks"]),
                                                     len(df), 5)]
    assert f["train_spans"] == [list(s) for s in
                                _complement_spans(
                                    len(df),
                                    _embargoed_test_spans(
                                        edges, tuple(f["test_blocks"]),
                                        len(df), 5))]
    # no full-sample simulation: manifest exposes no full-sample trades
    assert all(c["n_trades"] >= 0 for c in art["configs"])


def test_fold_training_score_is_a_function_of_its_span_slice_only():
    """The strongest form: changing data OUTSIDE every scored span plus
    its allowed warmup cannot change ANY fold's training scores.  Modify
    bars 300-340 (inside block 1 for n_splits=4? no — inside block 2's
    heart) and compare a fold whose train and test spans both avoid the
    modified region... such a fold does not exist in CPCV (spans tile the
    frame), so instead: modify a region strictly inside a TEST span of
    the fold and verify per-fold invariance — already covered above.
    Here: byte-identity of train slices across the pair (guard against a
    buggy modifier)."""
    df_a = _trend_frame()
    df_b = _modify_block(df_a, NSPLITS, 1, "crash")
    n = len(df_a)
    edges = _block_edges(n, NSPLITS)
    spans = _embargoed_test_spans(edges, (1, 3), n, 6)
    trains = _complement_spans(n, spans)
    for lo, hi in trains:
        # train spans of fold (1,3) may not touch block 1 at all
        assert hi <= edges[1][0] or lo >= edges[1][1]
        pd.testing.assert_frame_equal(df_a.iloc[lo:hi], df_b.iloc[lo:hi])


# ---------------------------------------------------------------------------
# Phase-5 matrix: ONLY future/test data changes (7 named scenarios)
# ---------------------------------------------------------------------------

_FUTURE_MATRIX = [
    # (scenario, block modifier mode, run_kwargs)
    ("huge_future_profit", "rally", {}),
    ("huge_future_loss", "crash", {}),
    ("future_drawdown_trigger", "crash", {"max_drawdown_pct": 5.0}),
    ("future_daily_loss_trigger", "mixed", {"max_daily_loss_pct": 1.0}),
    ("future_equity_spike", "spike", {}),
    ("future_exposure_cap_trigger", "rally",
     {"risk_percent": 4.0, "max_lots": 0.05}),
    ("future_open_position_difference", "rally",
     {"sl_atr": None}),  # sentinel: wide stops via params
]


@pytest.mark.parametrize(
    "scenario,mode,extra",
    _FUTURE_MATRIX,
    ids=[m[0] for m in _FUTURE_MATRIX],
)
def test_future_only_perturbation_matrix(scenario, mode, extra):
    """For EVERY scenario: modify ONLY a later test block.  Folds whose
    train spans exclude the modified bars must keep EXACTLY the same
    training selection and IS scores; their OOS scores may (and for a
    real modification should) change.  Scenarios 3/4/6/7 additionally
    have dedicated trigger-mechanism tests above (halt/halt/cap/carry)."""
    if scenario == "future_open_position_difference":
        params_list = [{**CFG_A, "sl_atr": 3.0, "tp_atr": 6.0},
                       {**CFG_B, "sl_atr": 3.0, "tp_atr": 6.0}]
        extra = {}
    else:
        params_list = PARAMS
    run_kw = {**RUN_KW, **{k: v for k, v in extra.items()}}

    df_a = _trend_frame()
    df_b = _modify_block(df_a, NSPLITS, 1, mode)
    block = _block_edges(len(df_a), NSPLITS)[1]

    def _folds(df):
        out = purged_cv_stage(df, "ema_crossover", params_list,
                              n_splits=NSPLITS, embargo_bars=6,
                              warmup_bars=60, engine="truth", seed=0,
                              **run_kw)
        return {tuple(f["test_blocks"]): f
                for f in out["manifest"].artifacts["folds"]}

    fa, fb = _folds(df_a), _folds(df_b)
    checked = 0
    for blocks in ((0, 1), (1, 2), (1, 3)):
        a, b = fa[blocks], fb[blocks]
        # train spans exclude block 1 entirely for these folds
        assert all(hi <= block[0] or lo >= block[1]
                   for lo, hi in a["train_spans"])
        assert a["selected"] == b["selected"]
        assert a["is_scores"] == b["is_scores"]
        checked += 1
    assert checked == 3
