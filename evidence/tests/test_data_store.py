"""AEGIS Phase 6 — RAW/CLEAN/DERIVED dataset store + backtest digest hookup.

Pins: RAW immutability, explicit clean change-log with raw parent linkage,
derived lineage (parent sha + transform), the dual-digest reference that
binds any backtest to its exact dataset (content sha256 + RunManifest
digest), and the CORRUPT-refusal gate.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

from mql5bot.data_layer import (
    DatasetStore,
    audit_ohlcv,
    content_digest,
)
from mql5bot.optimizer import _dataset_digest


def _clean_frame(days: int = 60, seed: int = 3) -> pd.DataFrame:
    from mql5bot.data import generate_ohlc
    return generate_ohlc(days=days, seed=seed)


def _corrupt_frame() -> pd.DataFrame:
    df = _clean_frame(30, seed=7).copy()
    df.iloc[5, df.columns.get_loc("high")] = \
        min(df.iloc[5]["open"], df.iloc[5]["close"]) - 1.0  # impossible OHLC
    return df


def _register(store, frame, name="gen"):
    return store.save_raw(frame, name, instrument="EURUSD", timeframe="H1",
                          tz="UTC", source="synthetic-test")


# ---------------------------------------------------------------------------
# RAW layer
# ---------------------------------------------------------------------------


def test_raw_layer_is_immutable(tmp_path):
    store = DatasetStore(tmp_path / "data")
    df = _clean_frame()
    reg = _register(store, df)
    assert reg["layer"] == "raw"
    first = (tmp_path / "data/raw/gen.csv").read_bytes()
    assert reg["file_sha256"] == __import__("hashlib").sha256(first).hexdigest()
    with pytest.raises(FileExistsError, match="immutable"):
        _register(store, df)
    assert (tmp_path / "data/raw/gen.csv").read_bytes() == first


def test_raw_identity_records_quality_and_both_digests(tmp_path):
    store = DatasetStore(tmp_path / "data")
    reg = _register(store, _clean_frame())
    assert reg["identity"]["quality"] in ("OK", "WARNINGS")
    assert reg["manifest_digest"] == reg["manifest_digest"]  # present
    df = pd.read_csv(reg["file"], index_col=0, parse_dates=True)
    assert reg["manifest_digest"] == _dataset_digest(df)
    assert reg["identity"]["sha256"] == content_digest(df)


def test_raw_corrupt_still_registered_but_flagged(tmp_path):
    store = DatasetStore(tmp_path / "data")
    reg = _register(store, _corrupt_frame(), name="bad")
    assert reg["identity"]["quality"] == "CORRUPT"
    audit_types = {f["type"] for f in reg["audit"]["findings"]}
    assert "impossible_ohlc" in audit_types


# ---------------------------------------------------------------------------
# CLEAN layer
# ---------------------------------------------------------------------------


def test_clean_promotion_names_raw_parent_and_change_log(tmp_path):
    store = DatasetStore(tmp_path / "data")
    raw = _register(store, _corrupt_frame(), name="bad")
    clean = store.promote_clean("bad")
    assert clean["layer"] == "clean"
    assert clean["parent"]["layer"] == "raw"
    assert clean["parent"]["file_sha256"] == raw["file_sha256"]
    assert clean["change_log"], "cleaning must be explicit"
    # raw audit is preserved for inspection (never hidden)
    assert clean["audit_raw"]["quality"] == "CORRUPT"
    # cleaned frame passes the hard classes
    cleaned = pd.read_csv(clean["file"], index_col=0, parse_dates=True)
    assert audit_ohlcv(cleaned)["quality"] != "CORRUPT"


def test_clean_of_healthy_data_is_identity_with_empty_log(tmp_path):
    store = DatasetStore(tmp_path / "data")
    _register(store, _clean_frame())
    clean = store.promote_clean("gen")
    df_raw = pd.read_csv(store.root / "raw/gen.csv", index_col=0,
                         parse_dates=True)
    df_clean = pd.read_csv(clean["file"], index_col=0, parse_dates=True)
    pd.testing.assert_frame_equal(df_raw, df_clean)
    assert clean["change_log"] == []


def test_uncleanable_corrupt_refuses_promotion(tmp_path):
    store = DatasetStore(tmp_path / "data")
    df = _clean_frame(30, seed=11).copy()
    df = pd.concat([df, df.iloc[[-1]]])  # duplicate timestamp (hard class)
    _register(store, df, name="hard")
    with pytest.raises(ValueError, match="uncleanable"):
        store.promote_clean("hard")


# ---------------------------------------------------------------------------
# DERIVED layer
# ---------------------------------------------------------------------------


def test_derived_names_clean_parent_and_transform(tmp_path):
    store = DatasetStore(tmp_path / "data")
    _register(store, _clean_frame())
    clean = store.promote_clean("gen")
    der = store.add_derived(
        "gen_clean", "resample_d1", lambda df: df.resample("1D").last().dropna())
    assert der["layer"] == "derived"
    assert der["parent"]["name"] == "gen_clean"
    assert der["parent"]["file_sha256"] == clean["file_sha256"]
    assert der["transform"] == "resample_d1"
    dfd = pd.read_csv(der["file"], index_col=0, parse_dates=True)
    assert der["manifest_digest"] == _dataset_digest(dfd)


# ---------------------------------------------------------------------------
# backtest reference + digest hookup
# ---------------------------------------------------------------------------


def test_ref_binds_both_digests_and_corrupt_is_refused(tmp_path):
    store = DatasetStore(tmp_path / "data")
    _register(store, _corrupt_frame(), name="bad")
    _register(store, _clean_frame(), name="gen")
    store.promote_clean("bad")
    store.promote_clean("gen")
    # CORRUPT raw is refused for backtests
    with pytest.raises(ValueError, match="CORRUPT"):
        store.ref("raw", "bad")
    # explicit override is possible but loudly labelled
    ref = store.ref("raw", "bad", allow_corrupt=True)
    assert ref["quality"] == "CORRUPT"
    # healthy clean reference carries the full binding
    good = store.ref("clean", "gen_clean")
    df = pd.read_csv(good["file"], index_col=0, parse_dates=True)
    assert good["manifest_digest"] == _dataset_digest(df)
    assert good["content_sha256"] == content_digest(df)
    assert good["parent"]["layer"] == "raw"


def test_runmanifest_dataset_version_traces_to_store(tmp_path):
    """A backtest that consumes THROUGH the store (store.load) records
    ``dataset_version == ref.manifest_digest`` — the hookup that makes every
    backtest name its exact stored dataset. (The writer's in-memory copy is
    NOT the authority: CSV storage defines the dataset, digests are bound to
    the read-back frame.)"""
    from mql5bot.pipeline import RunManifest
    store = DatasetStore(tmp_path / "data")
    _register(store, _clean_frame())
    ref = store.ref("raw", "gen")
    df = store.load("raw", "gen")
    manifest = RunManifest(stage="test", strategy="ema_crossover",
                           params={"fast": 8, "slow": 30}, engine="event",
                           dataset_version=_dataset_digest(df))
    assert manifest.dataset_version == ref["manifest_digest"]
    assert ref["content_sha256"] == content_digest(df)


def test_full_lineage_chain_raw_to_derived(tmp_path):
    store = DatasetStore(tmp_path / "data")
    raw = _register(store, _clean_frame())
    clean = store.promote_clean("gen")
    store.add_derived("gen_clean", "feat", lambda df: df.assign(
        ret=df["close"].pct_change().fillna(0.0)))
    ref = store.ref("derived", "gen_clean_feat")
    assert ref["parent"]["name"] == "gen_clean"
    assert ref["parent"]["file_sha256"] == clean["file_sha256"]
    assert clean["parent"]["file_sha256"] == raw["file_sha256"]
    chain = [ref["layer"], ref["parent"]["layer"]]
    assert chain == ["derived", "clean"]


def test_store_missing_dataset_fails_loudly(tmp_path):
    store = DatasetStore(tmp_path / "data")
    with pytest.raises(FileNotFoundError):
        store.ref("raw", "never_registered")
    with pytest.raises(ValueError, match="unknown layer"):
        store.ref("bogus", "x")
