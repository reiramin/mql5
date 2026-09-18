"""OOS registry identity hardening (Phase 3 hardening, Blocker 6).

The registry key is the exact certification identity — anchored on the
dataset CONTENT digest with strategy / engine / cost-model / feature /
protocol versions — and a version change can never mint a second look
on the same (dataset content, strategy) pair.  One-look semantics are
stronger than before, never weaker.
"""

import json

import pytest
from mql5bot.data import generate_ohlc
from mql5bot.optimizer import _dataset_digest
from mql5bot.pipeline import (
    OosIdentity,
    OosOneLookViolation,
    OosRegistry,
    oos_identity,
    oos_stage,
)


def _identity(df, strategy="ema_crossover", **over):
    base = {
        "dataset_content_digest": _dataset_digest(df),
        "dataset_tag": "",
        "strategy": strategy,
        "strategy_version": "1.0.0",
        "engine": "truth",
        "engine_version": "1.0.0",
        "cost_model_version": "1.0.0",
        "cost_config_digest": "abc",
        "feature_version": "1.0.0",
        "certification_protocol_version": "2.0.0",
    }
    base.update(over)
    return OosIdentity(**base)


@pytest.fixture
def df():
    return generate_ohlc(days=30, seed=9, start="2024-07-01")


# ---------------------------------------------------------------------------
# Identity mechanics
# ---------------------------------------------------------------------------


def test_identity_id_covers_every_field(df):
    base = _identity(df)
    assert base.identity_id() == _identity(df).identity_id()
    for field, value in (
        ("strategy_version", "1.0.1"),
        ("engine_version", "1.0.1"),
        ("cost_model_version", "1.0.1"),
        ("cost_config_digest", "different"),
        ("feature_version", "1.0.1"),
        ("certification_protocol_version", "2.0.1"),
        ("dataset_content_digest", "other-data"),
        ("dataset_tag", "TAG"),
    ):
        changed = _identity(df, **{field: value})
        assert changed.identity_id() != base.identity_id(), field
        assert base.differ(changed) == [field]


def test_exact_identity_one_look(tmp_path, df):
    reg = OosRegistry(tmp_path / "oos.json")
    ident = _identity(df)
    reg.certify_identity(ident, {"fast": 8})
    with pytest.raises(OosOneLookViolation):
        reg.certify_identity(ident, {"fast": 12})


def test_version_bump_cannot_mint_a_second_look(tmp_path, df):
    """Changing ANY identity version field on the same dataset content +
    strategy is refused — with the changed fields named."""
    reg = OosRegistry(tmp_path / "oos.json")
    reg.certify_identity(_identity(df), {"fast": 8})
    for over in (
        {"strategy_version": "9.9.9"},
        {"cost_model_version": "9.9.9"},
        {"cost_config_digest": "other"},
        {"feature_version": "9.9.9"},
        {"certification_protocol_version": "9.9.9"},
        {"engine_version": "9.9.9"},
        {"dataset_tag": "OOS-REBRANDED"},
    ):
        with pytest.raises(OosOneLookViolation) as exc:
            reg.certify_identity(_identity(df, **over), {"fast": 12})
        msg = str(exc.value)
        assert "Changed identity fields:" in msg
        assert "never-touched" in msg


def test_tag_cannot_weaken_content_identity(tmp_path, df):
    """The same content certified under a tag cannot be re-certified
    under a different tag: the anchor is the content digest."""
    reg = OosRegistry(tmp_path / "oos.json")
    reg.certify_identity(_identity(df, dataset_tag="OOS-2024H2"),
                         {"fast": 8})
    with pytest.raises(OosOneLookViolation):
        reg.certify_identity(_identity(df, dataset_tag="OOS-2025H1"),
                             {"fast": 8})


def test_fresh_content_is_a_fresh_slice(tmp_path, df):
    other = generate_ohlc(days=30, seed=10, start="2025-01-01")
    assert _dataset_digest(other) != _dataset_digest(df)
    reg = OosRegistry(tmp_path / "oos.json")
    reg.certify_identity(_identity(df), {"fast": 8})
    reg.certify_identity(_identity(other), {"fast": 8})  # new data: ok
    assert len(OosRegistry(tmp_path / "oos.json")._load()["entries"]) == 2


def test_different_strategy_same_content_is_fresh(tmp_path, df):
    """Policy unchanged: the one-look anchor is (dataset content,
    strategy) — another strategy still gets its own look."""
    reg = OosRegistry(tmp_path / "oos.json")
    reg.certify_identity(_identity(df), {})
    reg.certify_identity(_identity(df, strategy="rsi_reversal"), {})
    assert len(OosRegistry(tmp_path / "oos.json")._load()["entries"]) == 2


def test_non_truth_engine_never_certifies(tmp_path, df):
    reg = OosRegistry(tmp_path / "oos.json")
    with pytest.raises(ValueError, match="TRUTH"):
        reg.certify_identity(_identity(df, engine="fast"), {})


# ---------------------------------------------------------------------------
# oos_stage integration
# ---------------------------------------------------------------------------


def test_oos_stage_records_full_identity(tmp_path, df):
    reg = OosRegistry(tmp_path / "oos.json")
    out = oos_stage(df, "ema_crossover", {"fast": 8, "slow": 24},
                    registry=reg, dataset_tag="OOS-2024H2",
                    spread_points=1.5, commission_per_lot=7.0)
    entry = out["manifest"]
    ident = entry.artifacts["identity"]
    assert ident["dataset_content_digest"] == _dataset_digest(df)
    assert ident["dataset_tag"] == "OOS-2024H2"
    assert ident["strategy"] == "ema_crossover"
    assert ident["strategy_version"] == "1.0.0"
    assert ident["engine"] == "truth"
    assert ident["engine_version"]
    assert ident["cost_model_version"]
    assert ident["cost_config_digest"]
    assert ident["feature_version"]
    assert ident["certification_protocol_version"]
    assert entry.artifacts["identity_id"] == oos_identity(
        df, "ema_crossover", dataset_tag="OOS-2024H2",
        spread_points=1.5, commission_per_lot=7.0).identity_id()
    # the oos_identity helper itself is content-anchored
    helper = oos_identity(df, "ema_crossover", dataset_tag="WHATEVER")
    assert helper.dataset_content_digest == _dataset_digest(df)


def test_oos_stage_second_look_refused_before_run(tmp_path, df):
    reg = OosRegistry(tmp_path / "oos.json")
    oos_stage(df, "ema_crossover", {"fast": 8, "slow": 24}, registry=reg,
              dataset_tag="OOS-A")
    called = {"n": 0}
    import mql5bot.pipeline as pl

    real = pl.run_backtest

    def spy(*a, **kw):
        called["n"] += 1
        return real(*a, **kw)

    pl.run_backtest = spy
    try:
        with pytest.raises(OosOneLookViolation):
            oos_stage(df, "ema_crossover", {"fast": 9, "slow": 30},
                      registry=reg, dataset_tag="OOS-A")
        with pytest.raises(OosOneLookViolation):
            oos_stage(df, "ema_crossover", {"fast": 9, "slow": 30},
                      registry=reg, dataset_tag="OOS-B")  # tag change: no
        assert called["n"] == 0  # refused BEFORE any run
    finally:
        pl.run_backtest = real


# ---------------------------------------------------------------------------
# Persistence + legacy migration
# ---------------------------------------------------------------------------


def test_persistence_across_instances(tmp_path, df):
    reg = OosRegistry(tmp_path / "oos.json")
    reg.certify_identity(_identity(df), {"fast": 8})
    reg2 = OosRegistry(tmp_path / "oos.json")
    with pytest.raises(OosOneLookViolation):
        reg2.certify_identity(_identity(df), {"fast": 9})


def test_v1_file_migrates_and_stays_enforced(tmp_path):
    """A pre-identity registry file (flat keys) keeps working: has_look
    matches, a second legacy look is refused, and the file is upgraded
    to schema 2."""
    p = tmp_path / "oos.json"
    p.write_text(json.dumps({
        "DATA-v1::ema_crossover": {
            "params": {"fast": 8}, "manifest_id": "m",
            "strategy_version": "1.0.0", "engine": "truth",
            "metrics": {}, "cost_config": {}, "certified": "t0",
        },
    }))
    reg = OosRegistry(p)
    assert reg.has_look("ema_crossover", "DATA-v1")
    with pytest.raises(OosOneLookViolation):
        reg.certify("ema_crossover", "DATA-v1", {"fast": 12})
    data = json.loads(p.read_text())
    assert data["_schema"] == 2
    assert "DATA-v1::ema_crossover" in data["legacy"]


def test_legacy_certify_still_one_look_per_version(tmp_path):
    reg = OosRegistry(tmp_path / "oos.json")
    reg.certify("ema_crossover", "DATA-v1", {"fast": 8})
    assert reg.has_look("ema_crossover", "DATA-v1")
    with pytest.raises(OosOneLookViolation):
        reg.certify("ema_crossover", "DATA-v1", {"fast": 12})
    reg.certify("ema_crossover", "DATA-v2", {"fast": 8})   # new version
    reg.certify("rsi_reversal", "DATA-v1", {})             # new strategy
    with pytest.raises(OosOneLookViolation):
        reg.certify("ema_crossover", "DATA-v1", {"fast": 30})


# ---------------------------------------------------------------------------
# Failure/recovery policy (documented in docs/CERTIFICATION.md)
# ---------------------------------------------------------------------------


def test_failed_attempt_consumes_nothing_retry_permitted_once_locked(
        tmp_path, df):
    """Documented failure/recovery policy: an attempt whose RUN FAILS
    (exception) records NOTHING and consumes NO look — no result was
    observed, so no knowledge leaked; a retry after fixing the cause is
    permitted.  A SUCCESSFUL run records the look and locks the
    (content, strategy) pair forever."""
    reg = OosRegistry(tmp_path / "oos.json")
    import mql5bot.pipeline as pl

    real = pl.run_backtest
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated terminal/engine failure")
        return real(*a, **kw)

    pl.run_backtest = flaky
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            oos_stage(df, "ema_crossover", {"fast": 8, "slow": 24},
                      registry=reg, dataset_tag="OOS-FAIL")
        # nothing recorded: the failed attempt consumed nothing
        assert reg._load()["entries"] == []
        assert not reg.has_look("ema_crossover", _dataset_digest(df))
        # retry after fixing the cause succeeds and locks
        oos_stage(df, "ema_crossover", {"fast": 8, "slow": 24},
                  registry=reg, dataset_tag="OOS-FAIL")
        assert reg.has_look("ema_crossover", _dataset_digest(df))
        with pytest.raises(OosOneLookViolation):
            oos_stage(df, "ema_crossover", {"fast": 8, "slow": 24},
                      registry=reg, dataset_tag="OOS-FAIL")
    finally:
        pl.run_backtest = real


def test_failed_attempt_cannot_be_used_to_shop_parameters(tmp_path, df):
    """The failure path grants no parameter-shopping latitude beyond the
    documented policy: after ANY successful look the pair is locked,
    whatever happened before."""
    reg = OosRegistry(tmp_path / "oos.json")
    import mql5bot.pipeline as pl

    real = pl.run_backtest
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("simulated failure")
        return real(*a, **kw)

    pl.run_backtest = flaky
    try:
        for _ in range(2):
            with pytest.raises(RuntimeError):
                oos_stage(df, "ema_crossover", {"fast": 9, "slow": 40},
                          registry=reg)
        oos_stage(df, "ema_crossover", {"fast": 8, "slow": 24},
                  registry=reg)
        with pytest.raises(OosOneLookViolation):
            oos_stage(df, "ema_crossover", {"fast": 12, "slow": 48},
                      registry=reg)
    finally:
        pl.run_backtest = real
