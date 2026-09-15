"""Alembic migration tests (mission §72): schema changes go through
Alembic; the baseline creates the full §18 table set and reverses."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "strategies", "strategy_versions", "strategy_sources",
    "strategy_claims", "validation_runs", "validation_metrics",
    "validation_artifacts", "lifecycle_events", "promotion_decisions",
    "shadow_observations", "live_observations", "alerts",
    "discovery_campaigns",
}


def _run(*args: str, db: str) -> None:
    env = dict(os.environ, AEGIS_FACTORY_DB=db)
    subprocess.run([sys.executable, "-m", "alembic", *args],
                   check=True, env=env, cwd=REPO,
                   capture_output=True)


def test_baseline_upgrade_downgrade_upgrade(tmp_path):
    db = str(tmp_path / "mig.db")
    _run("upgrade", "head", db=db)
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert EXPECTED_TABLES <= tables

    _run("downgrade", "base", db=db)
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert EXPECTED_TABLES.isdisjoint(tables)

    _run("upgrade", "head", db=db)
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert EXPECTED_TABLES <= tables


def test_store_and_migrations_agree_on_schema(tmp_path):
    """The ORM's create_all (store path) and the Alembic baseline must
    produce the same table set — no ad-hoc schema drift."""
    db = str(tmp_path / "orm.db")
    from mql5bot.factory.store import FactoryStore
    FactoryStore(db)
    con = sqlite3.connect(db)
    orm_tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    mig_db = str(tmp_path / "mig.db")
    _run("upgrade", "head", db=mig_db)
    con = sqlite3.connect(mig_db)
    mig_tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    # alembic_version is migration bookkeeping, not schema
    assert orm_tables == mig_tables - {"alembic_version"}
