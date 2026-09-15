"""Factory CLI tests (mission §55/§56): interpret→register→evidence→
advance→status→meta-feed round trip; refusals are exit-code 2 with a
JSON refusal payload; no subcommand can trade."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mql5bot.factory.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "strategies"


@pytest.fixture()
def ws(tmp_path):
    text = tmp_path / "idea.txt"
    text.write_text(
        "Buy when EMA20 crosses EMA50 upward and RSI is above 55. "
        "SL 1.5 ATR, TP 3 ATR.", encoding="utf-8")
    return tmp_path, text


def _db(ws):
    return str(ws[0] / "factory.db")


def _run(args, db, monkeypatch):
    monkeypatch.setenv("AEGIS_FACTORY_DB", db)
    return main(args)


def test_interpret_emits_draft_and_flags_review(ws, capsys):
    _tmp_path, text = ws
    rc = main(["--db", _db(ws), "interpret", str(text)])
    out = json.loads(capsys.readouterr().out)
    assert out["draft"]["version"] == 0
    assert out["confidence"] == 0.8
    assert out["needs_review"] is False
    assert rc == 0


def test_interpret_needs_review_for_ambiguity(ws, capsys):
    tmp_path, _ = ws
    amb = tmp_path / "amb.txt"
    amb.write_text("Trade when RSI is low", encoding="utf-8")
    rc = main(["--db", _db(ws), "interpret", str(amb)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["needs_review"]
    assert any(a["name"] == "rsi_threshold" for a in out["ambiguities"])


def test_register_advance_status_roundtrip(ws, monkeypatch, capsys):
    tmp_path, text = ws
    interp = main(["--db", _db(ws), "interpret", str(text)])
    assert interp == 0
    draft = json.loads(capsys.readouterr().out)["draft"]
    draft["strategy_id"] = "ema_trend_demo"
    draft["version"] = 0
    draft_file = tmp_path / "draft.json"
    draft_file.write_text(json.dumps(draft), encoding="utf-8")
    db = _db(ws)

    rc = _run(["register", str(draft_file), "--actor", "alice",
               "--source", str(text)], db, monkeypatch)
    assert rc == 0
    reg = json.loads(capsys.readouterr().out)
    assert reg["created"] and reg["version"] == 0

    # a DRAFT cannot jump to BACKTESTED — store refuses, exit 2
    rc = _run(["advance", "ema_trend_demo", "--version", "0",
               "--to", "BACKTESTED", "--actor", "alice"],
              db, monkeypatch)
    assert rc == 2
    assert "refused" in capsys.readouterr().out

    # record parse+schema evidence, then advance DRAFT→PARSED with
    # the run ids as audited evidence refs (store-enforced)
    run_ids = []
    for run_type in ("parse", "schema"):
        _run(["record-run", "ema_trend_demo", "--version", "0",
              "--run-type", run_type, "--status", "PASS",
              "--spec-hash", reg["spec_hash"]], db, monkeypatch)
        run_ids.append(json.loads(
            capsys.readouterr().out)["run_id"])
    _run(["advance", "ema_trend_demo", "--version", "0",
          "--to", "PARSED", "--actor", "alice", "--reason",
          "draft parses",
          "--evidence", str(run_ids[0])], db, monkeypatch)
    assert "PARSED" in capsys.readouterr().out

    # status shows the current state
    _run(["status"], db, monkeypatch)
    rows = json.loads(capsys.readouterr().out)
    row = next(r for r in rows
               if r["strategy_id"] == "ema_trend_demo")
    assert row["state"] == "PARSED"

    # meta-feed lists certification rows (runtime supplies signals)
    _run(["meta-feed"], db, monkeypatch)
    feed = json.loads(capsys.readouterr().out)
    entry = next(r for r in feed
                 if r["strategy_id"] == "ema_trend_demo")
    assert entry["certification_state"] is None   # pre-shadow: blocked


def test_no_subcommand_trades_or_touches_mt5():
    src = Path(__file__).resolve().parent.parent / "python" / \
        "mql5bot" / "factory" / "cli.py"
    text = src.read_text(encoding="utf-8")
    for banned in ("MetaTrader5", "order_send", "mt5.", "socket"):
        assert banned not in text
