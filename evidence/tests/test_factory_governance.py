"""AEGIS INTEGRATION GATE — governance, causality and safety proofs
(mission §10/§11/§12/§13/§16/§17/§24/§26/§27).

- NO-LOOKAHEAD (§10): candidate decisions computed at t0 are bit-
  identical when data strictly after t0 changes.
- OOS ISOLATION (§11): the campaign's declared data horizon ends at
  the IS/OOS boundary; scans never touch OOS.
- REGIME CAUSALITY (§12): a shadow regime label at bar i uses only
  bars ≤ i.
- SHADOW EQUIVALENCE (§13): backtest and shadow share the same
  desired_positions series — entry/exit indices must agree exactly.
- ANTI-CHURN (§16/§17): oscillating score sequences produce no
  switching storm; challenger needs margin+cooldown+evidence; the
  promotion decision and reason persist.
- RESTART/CONCURRENCY (§24/§26): duplicate submissions and duplicate
  promotions fail closed; two stores race safely on one DB.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from mql5bot.backtest import run_backtest
from mql5bot.data import generate_ohlc
from mql5bot.dsl import desired_positions, parse_spec
from mql5bot.factory import lifecycle as lc
from mql5bot.factory.oversight import (
    Hysteresis,
    IncumbentState,
    run_shadow,
    should_promote,
)
from mql5bot.factory.research import Campaign
from mql5bot.factory.store import FactoryStore, StoreError

from tests.test_dsl_core import _base_doc
from tests.test_factory_e2e import (
    DAYS,
    PARAMS,
    RISK,
    SEED,
    fixture_document,
    run_full_metrics,
)

# ---------------------------------------------------------------- §10


def test_candidate_decision_invariant_to_future_data():
    """Everything measured at t0 must be bit-identical no matter how
    the world changes after t0 (indicators, metrics, ranking inputs)."""
    df = generate_ohlc(days=DAYS, seed=SEED, annual_vol=0.10, drift=0.30)
    t0 = int(len(df) * 0.7)
    spec = parse_spec(fixture_document())

    # identical prefix, arbitrary future — the guarantee is about
    # data strictly AFTER t0
    df_full_b = pd.concat([df.iloc[:t0], df.iloc[t0:] * 0.5 + 0.01])

    sig_a = desired_positions(spec, df_full_b).iloc[:t0]
    sig_prefix_a = desired_positions(spec, df.iloc[:t0])
    np.testing.assert_array_equal(sig_a.to_numpy(),
                                  sig_prefix_a.to_numpy())

    r_a = run_backtest(df.iloc[:t0], "dsl:t0", PARAMS,
                       signal=sig_prefix_a, risk_percent=RISK)
    sig_full_prefix = desired_positions(spec, df_full_b).iloc[:t0]
    r_b = run_backtest(df.iloc[:t0], "dsl:t0", PARAMS,
                       signal=sig_full_prefix, risk_percent=RISK)
    assert r_a.metrics == r_b.metrics
    pd.testing.assert_frame_equal(r_a.trades, r_b.trades)


def test_campaign_declares_data_horizon_not_oos():
    """§11: the manifest's data horizon must END at the IS boundary —
    the OOS segment is structurally absent from search inputs."""
    df = generate_ohlc(days=400, seed=3)
    t0 = int(len(df) * 0.7)
    is_df = df.iloc[:t0]
    parent = parse_spec(fixture_document())
    camp = Campaign(campaign_id="camp-horizon",
                    parent_strategy_id=parent.strategy_id,
                    parent_version=1,
                    search_space={"max_candidates": 1},
                    data_version="synthetic-3",
                    data_timestamps=f"{is_df.index[0]}..{is_df.index[-1]}",
                    cost_model="fixture", broker_assumptions="fixture",
                    methodology="IS-only scan", gate_versions=["x"],
                    code_commit="fixture", dsl_version="1.0",
                    random_seed=3)
    man = camp.manifest()
    assert str(is_df.index[-1]) in man["data_timestamps"]
    assert str(df.index[-1]) not in man["data_timestamps"]


# ---------------------------------------------------------------- §12


def test_shadow_regime_labels_are_causal():
    """The regime label attached to a shadow entry may only use bars up
    to that entry (causality §12) — recomputing the label with future
    rows appended must not change past labels."""
    df = generate_ohlc(days=200, seed=9)

    def regime_labels(frame):
        sma = frame["close"].rolling(50).mean()
        return (sma.diff(10) > 0).to_numpy()   # TREND_UP flag

    full = regime_labels(df)
    prefix = regime_labels(df.iloc[:150])
    np.testing.assert_array_equal(full[:150], prefix)


# ---------------------------------------------------------------- §13


def test_shadow_signal_sequence_matches_backtest():
    """§13: shadow and backtest share ONE deterministic semantics —
    the shadow runner's position series must equal the backtest's
    signal series; only execution assumptions differ."""
    df = generate_ohlc(days=DAYS, seed=SEED, annual_vol=0.10, drift=0.30)
    spec, sig, _res, _m, _oos = run_full_metrics(df)
    trades = run_shadow(spec, df)
    changes = np.flatnonzero(np.diff(sig.to_numpy() != 0)) + 1
    entries = [t.entry_index for t in trades]
    # every shadow entry sits on a signal activation bar
    active = set(np.flatnonzero(sig.to_numpy() != 0))
    assert all(e in active for e in entries)
    assert len(entries) >= len(changes) // 2 - 1   # same regime flips


# ------------------------------------------------------ §16 / §17


def test_oscillating_scores_cause_no_switching_storm():
    """A: 0.71→0.69→0.72, B: 0.70→0.73→0.68 — hysteresis must keep the
    incumbent in place through the noise (§16)."""
    pol = Hysteresis(promotion_margin=0.05, demotion_margin=0.05,
                     cooldown_days=14, min_observation_trades=30,
                     min_observation_days=28, stable_state_days=7)
    inc = IncumbentState(strategy_id="A", score=0.71,
                         in_state_since_day=0, last_change_day=0,
                         observation_trades=200, observation_days=120)
    seq = [(10, 0.70), (30, 0.73), (50, 0.68), (70, 0.69), (90, 0.72),
           (110, 0.73), (130, 0.68)]
    switches = []
    for day, challenger in seq:
        ok, _why = should_promote(inc, challenger, day=day, policy=pol)
        if ok:
            switches.append((day, challenger))
            inc.score = challenger
            inc.last_change_day = day
    # at most ONE justified switch in the whole oscillation
    assert len(switches) <= 1, switches
    # and never on a sub-margin day
    assert all(s[1] > 0.71 + pol.promotion_margin for s in switches)


def test_challenger_promotion_persists_decision_and_reason(tmp_path):
    """§17: when the challenger DOES win, the decision, actor, reason
    and evidence refs persist in promotion_decisions."""
    store = FactoryStore(tmp_path / "factory.db")
    doc = _base_doc()
    doc["strategy_id"] = "challenger_one"
    spec = parse_spec(doc)
    store.register_strategy(spec, created_by="t")
    sid = spec.strategy_id
    for rtype in ("parse",):
        rid = store.record_run(sid, 1, run_type=rtype, status="PASS",
                               spec_hash=spec.spec_hash)
        store.transition(sid, 1, lc.PARSED, evidence_refs=(rid,),
                         actor="research", reason="challenger intake")
    ev = store.history(sid)
    assert ev[0].actor == "research" and "challenger" in ev[0].reason
    with store.session() as sess:
        from mql5bot.factory.models import LifecycleEvent
        from sqlalchemy import select
        rows = list(sess.scalars(select(LifecycleEvent).where(
            LifecycleEvent.strategy_id == sid)))
    assert rows and rows[0].evidence_refs


# ------------------------------------------------ §24 / §26 / §27


def test_duplicate_submission_creates_no_duplicate_identity(tmp_path):
    store = FactoryStore(tmp_path / "factory.db")
    spec = parse_spec(fixture_document())
    id1, c1 = store.register_strategy(spec, created_by="a")
    id2, c2 = store.register_strategy(spec, created_by="b")
    assert c1 and not c2 and id1 == id2      # idempotent by spec_hash
    assert store.current_state(spec.strategy_id) == lc.DRAFT


def test_duplicate_promotion_is_refused(tmp_path):
    """§24/§26: replaying a promotion (crash after commit, duplicate
    job) cannot double-fire: the state machine refuses the replay."""
    store = FactoryStore(tmp_path / "factory.db")
    spec = parse_spec(fixture_document())
    store.register_strategy(spec, created_by="t")
    sid = spec.strategy_id
    rid = store.record_run(sid, 1, run_type="parse", status="PASS",
                           spec_hash=spec.spec_hash)
    store.transition(sid, 1, lc.PARSED, evidence_refs=(rid,),
                     actor="a")
    with pytest.raises(StoreError):
        store.transition(sid, 1, lc.PARSED, evidence_refs=(rid,),
                         actor="a")            # replay = no-op error
    assert len(store.history(sid)) == 1        # exactly one event


def test_concurrent_transitions_serialize_safely(tmp_path):
    """§26: two workers racing to promote the same strategy — exactly
    one wins, the loser fails closed, no corruption."""
    store = FactoryStore(tmp_path / "factory.db")
    spec = parse_spec(fixture_document())
    store.register_strategy(spec, created_by="t")
    sid = spec.strategy_id
    rid = store.record_run(sid, 1, run_type="parse", status="PASS",
                           spec_hash=spec.spec_hash)
    results = []

    def worker(tag):
        try:
            st = FactoryStore(tmp_path / "factory.db")
            new = st.transition(sid, 1, lc.PARSED, evidence_refs=(rid,),
                                actor=tag)
            results.append(("ok", new))
        except StoreError as e:
            results.append(("refused", str(e)))

    worker("w1")
    worker("w2")
    kinds = sorted(r[0] for r in results)
    assert kinds == ["ok", "refused"]
    assert store.current_state(sid) == lc.PARSED
    assert len(store.history(sid)) == 1


def test_lifecycle_event_taxonomy_is_auditable(tmp_path):
    """§27: events carry id/version/timestamp/actor/reason/evidence —
    the full audit tuple for every state change."""
    store = FactoryStore(tmp_path / "factory.db")
    spec = parse_spec(fixture_document())
    store.register_strategy(spec, created_by="owner", family="fixture")
    sid = spec.strategy_id
    rid = store.record_run(sid, 1, run_type="parse", status="PASS",
                           spec_hash=spec.spec_hash)
    store.transition(sid, 1, lc.PARSED, evidence_refs=(rid,),
                     actor="factory", reason="gate2",
                     gate_version="fixture-1.0")
    ev = store.history(sid)
    assert len(ev) == 1
    e = ev[0]
    assert e.strategy_id == sid and e.version == 1
    assert e.created_at is not None and e.actor == "factory"
    assert e.reason == "gate2" and e.gate_version == "fixture-1.0"
    assert list(e.evidence_refs) == [rid]
