"""Stage 8: the gate builds the evidence package from its OWN measured outputs.

gate_run26 (HEAD 918f7bf, -Golds gold2) FAILED stage 8
NOT_VERIFIED_RECONCILIATION_MISSING with a package holding only the two log
trade lists; first_divergence was None because the trade comparison never ran.

These tests build a tmp tree shaped like gate_run26 and pin:

  * the builder writes compile/, symbolspec/, gate/stage_5.json,
    real_tick_coverage.json (NONE), environment.json (measured fields only),
    reconciliation/gold2.json and archive_manifest.json (owner_evidence_bind);
  * a NOT_APPLICABLE leg is state NOT_APPLICABLE -- never MISSING, never a
    fabricated raw/parsed report -- and NONE coverage never reaches
    MT5_VALIDATED;
  * safety/*.json are never written;
  * first_divergence (and the per-trade one) is surfaced while stage 8 FAILs.

The tester windows are assembled from MEASURED lines (gate runs 16/17) plus
DEAL lines in the EA's own Logger format; the log trade list is produced by
the real tester_log_grader. The compile log is the real owner log with its
Mql5Bot ex5 hash replaced by the hash of the fake EX5 bytes (SYNTHETIC). None
of this is MT5 evidence.

PAIRING (gate_run27, HEAD 8966969, -Golds gold2): the first stage-8 trade
comparison paired by LIST POSITION, so event 0 compared python
2024-01-01T08:01 (1.4 lots) with MT5 2024-01-02T08:01 (0.01 lots) ->
TIMESTAMP_MISMATCH, while MT5 never traded 2024-01-01 at all ("start time
changed to 2024.01.02 00:00 to provide data at beginning", measured in
gate_run23/25/26/27). These tests pin the time-based pairing that replaced
it: same-day, same fill-minute matching; OUT_OF_TESTED_WINDOW for python
trades before the measured MT5 start (quoted, uncompared, never a
divergence); MISSING_IN_MT5 / EXTRA_IN_MT5 divergences inside the window;
and side / entry price compared from MT5's own journal deal lines
(`deal #N buy|sell VOL SYMBOL at PRICE`), never left unmeasured when stated.
The window lines used here are in tests/data/owner_gate/
tester_window_gate_run27_lines.txt.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import gate_selfcheck as gs
from mql5bot import owner_gate as og
from mql5bot import stage8_package as s8p
from mql5bot import tester_log_grader as tlg

REPO = Path(__file__).resolve().parents[1]
CAPTURE = REPO / "tests" / "data" / "owner_gate" / "tester_log_gate_runs_16_17.txt"
OWNER_COMPILE_LOG = REPO / "logs_owner" / "compile-20260917-201954.log"
VERIFY = REPO / "tools" / "verify_owner_mt5_gate.py"
DECIDE = REPO / "tools" / "owner_gate_decide.py"
PS1 = (REPO / "tools" / "owner_gate.ps1").read_text(encoding="utf-8")
REAL_EA_HASH = "64EE5F824E4B6B55327DF10125866D173F85484053392590279E53647E0BDB7E"

# 2 round trips (4 deals): entries pnl 0, exits pnl != 0 (EA DEAL format)
DEALS = [
    "[2024.01.02 08:01:00] [INFO] DEAL #2 EURUSD.G2 vol=0.01 price=1.09589 pnl=0.00",
    "[2024.01.02 08:07:00] [INFO] DEAL #3 EURUSD.G2 vol=0.01 price=1.09659 pnl=-0.70",
    "[2024.01.02 08:46:00] [INFO] DEAL #4 EURUSD.G2 vol=0.28 price=1.09700 pnl=0.00",
    "[2024.01.02 09:12:00] [INFO] DEAL #5 EURUSD.G2 vol=0.28 price=1.09650 pnl=-14.00",
]
# window-start + MT5 journal deal lines (provenance in the file header)
RUN27_LINES = [
    ln for ln in (REPO / "tests" / "data" / "owner_gate"
                  / "tester_window_gate_run27_lines.txt"
                  ).read_text(encoding="utf-8").splitlines()
    if ln and not ln.startswith("#")]
WINDOW_START_LINE = next(ln for ln in RUN27_LINES if "start time" in ln)


def _window(model_line: str) -> str:
    lines = [ln for ln in CAPTURE.read_text(encoding="utf-8").splitlines()
             if ln and not ln.startswith("#") and "EURUSD.G1" not in ln
             and "generating" not in ln]
    return "\n".join([model_line, *lines, *RUN27_LINES,
                      ("[2024.01.02 00:00:00] [INFO] generic DSL execution "
                       "enabled: gold2_multifactor"), *DEALS]) + "\n"


def _stage5_record() -> dict:
    """The stage-5 record shape owner_gate.ps1 Record-Stage writes, with the
    real NOT_APPLICABLE reason the decider produces for the committed gold2."""
    d = gs.derive_tester_inputs(REPO / "artifacts/gold_2/manifest.json",
                                REPO / "artifacts/gold_2/gold2_fixture.csv",
                                "artifacts/gold_2/gold2_fixture.csv")
    na = d["real_ticks_leg"]["reason"]
    return {"stage": 5, "name": "tester_legs", "status": "PASS_FROM_LOG",
            "reason": ("[scope: gold2; PARTIAL run -- certifies nothing] legs: "
                       "0 passed from report, 2 passed from log, 0 blocked, 0 "
                       "failed, 1 not applicable. gold2_m1_ohlc: exit 1; "
                       "PASS_FROM_LOG; gold2_every_tick: exit 1; PASS_FROM_LOG; "
                       f"gold2_real_ticks: {na} -- leg NOT launched, NOT a pass"),
            "scope": ["gold2"], "partial": True, "artifacts": [],
            "utc": "2026-10-03T12:00:00.0000000Z"}


@pytest.fixture()
def run26(tmp_path):
    """gate evidence dir + data folder + package, as after gate_run26's
    stage 5 and the stage-8 log-trade placement."""
    ev, data, pkg = tmp_path / "gate_ev", tmp_path / "data", tmp_path / "pkg"
    ev.mkdir()
    ex5 = data / "MQL5" / "Experts" / "Mql5Bot" / "Mql5Bot.ex5"
    ex5.parent.mkdir(parents=True)
    ex5.write_bytes(b"synthetic ex5 bytes for the package test")
    fake = s8p._sha(ex5).upper()
    log = OWNER_COMPILE_LOG.read_text(encoding="utf-8-sig").replace(
        REAL_EA_HASH, fake)
    (ev / "compile-20260917-201954.log").write_text(log, encoding="utf-8")
    (ev / "stage_5.json").write_text(json.dumps(_stage5_record()),
                                     encoding="ascii")
    spec = tmp_path / "EURUSD.json"
    spec.write_text(json.dumps({"symbol": "EURUSD", "server": "MetaQuotes-Demo",
                                "point": 1e-05, "exported_at": "2026.10.03 11:00"}),
                    encoding="utf-8")
    for model, req, line in (
            ("m1_ohlc", 1, "EURUSD.G2,M1 (MetaQuotes-Demo): 1 minutes OHLC ticks generating"),
            ("every_tick", 0, "EURUSD.G2,M1 (MetaQuotes-Demo): every tick generating")):
        win = _window(line)
        (ev / f"tester_gold2_{model}_window.txt").write_text(win, encoding="utf-8")
        grade = tlg.grade_leg_from_log(window_text=win, symbol="EURUSD.G2",
                                       requested_model=req,
                                       leg=f"gold2_{model}",
                                       expected_strategy="gold2_multifactor")
        assert grade["outcome"] == "PASS_FROM_LOG", grade["reason"]
        trades = ev / f"tester_gold2_{model}_log_trades.json"
        trades.write_text(json.dumps(tlg.log_trade_list(grade, win.encode())),
                          encoding="utf-8")
        placed = tlg.place_log_trades(trades, pkg, "gold2", model, REPO)
        assert placed["ok"], placed["reasons"]
    rec = s8p.build_package(repo=REPO, package=pkg, gate_evidence=ev,
                            data_folder=data, golds=["gold2"],
                            symbolspec_export=spec,
                            host={"os": "Windows (test)", "timezone": "UTC"})
    return rec, pkg, ev


def _verify(pkg: Path, tmp_path: Path) -> dict:
    out = tmp_path / "reconciliation_verify.json"
    cp = subprocess.run([sys.executable, str(VERIFY), str(pkg), "--repo",
                         str(REPO), "--golds", "gold2", "--out", str(out)],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 1, cp.stdout + cp.stderr   # never positive
    return json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# the builder
# ---------------------------------------------------------------------------

def test_builder_writes_the_gate_measured_artifacts(run26):
    rec, pkg, _ = run26
    assert rec["ok"], rec
    for rel in ("compile/compile.log", "compile/compile_metadata.json",
                "compile/Mql5Bot.ex5", "symbolspec/symbolspec.json",
                "gate/stage_5.json", "real_tick_coverage.json",
                "environment.json", "reconciliation/gold2.json",
                "archive_manifest.json"):
        assert (pkg / rel).is_file(), rel
    meta = json.loads((pkg / "compile/compile_metadata.json").read_text())
    assert meta["EX5_SHA256"] == s8p._sha(pkg / "compile/Mql5Bot.ex5")
    assert meta["COMPILER_LOG_SHA256"] == s8p._sha(pkg / "compile/compile.log")
    assert meta["COMPILE_TIMESTAMP"] == "2026-09-17T20:19:54+00:00"
    assert meta["COMPILER_VERSION"] == "5.0.0.6184"
    assert (meta["ERRORS"], meta["WARNINGS"]) == (0, 0)
    # nothing measured the terminal build in these windows: omitted, not filled
    assert "TERMINAL_BUILD" not in meta


def test_coverage_is_none_for_the_bar_only_gold_never_full(run26):
    _, pkg, _ = run26
    cov = json.loads((pkg / "real_tick_coverage.json").read_text())
    assert cov["coverage"] == og.REAL_TICK_COVERAGE_NONE
    assert cov["leg_launched"] is False
    assert cov["golds"]["gold2"]["fixture"] == "artifacts/gold_2/gold2_fixture.csv"
    assert cov["golds"]["gold2"]["leg"] == "not launched"
    assert "actual_model_from_report" not in cov


def test_environment_carries_measured_fields_only(run26):
    _, pkg, _ = run26
    env = json.loads((pkg / "environment.json").read_text())
    assert env["server"] == "MetaQuotes-Demo"
    assert env["symbol"] == "EURUSD"
    assert env["tester_symbols"] == {"gold2": "EURUSD.G2"}
    for gap in ("broker", "terminal_build", "account_mode"):
        assert gap not in env and gap in env["unmeasured"]


def test_not_applicable_leg_gets_no_fabricated_report(run26):
    _, pkg, _ = run26
    assert not (pkg / "gold2" / "real_ticks.htm").exists()
    assert not (pkg / "parsed" / "gold2_real_ticks.json").exists()
    recon = json.loads((pkg / "reconciliation/gold2.json").read_text())
    rt = recon["bindings"]["tester_models"]["real_ticks"]
    assert rt == {"not_applicable": True, "outcome": og.STAGE5_NOT_APPLICABLE,
                  "requested": 4,
                  "fixture": "artifacts/gold_2/gold2_fixture.csv"}


def test_safety_is_never_fabricated(run26):
    rec, pkg, _ = run26
    assert not (pkg / "safety").exists()
    for name in og.SAFETY_TESTS + ("netting", "hedging"):
        assert f"safety/{name}.json" in rec["not_built"]


def test_archive_manifest_is_owner_evidence_bind_output(run26):
    _, pkg, _ = run26
    man = json.loads((pkg / "archive_manifest.json").read_text())
    files = {str(p.relative_to(pkg)).replace("\\", "/")
             for p in pkg.rglob("*") if p.is_file()} - {"archive_manifest.json"}
    assert set(man["artifacts"]) == files
    for rel, digest in man["artifacts"].items():
        assert s8p._sha(pkg / rel) == digest


def test_reconciliation_pairs_by_time_never_by_position(run26):
    _, pkg, _ = run26
    recon = json.loads((pkg / "reconciliation/gold2.json").read_text())
    trades = [e for e in recon["events"] if "trade_index" in e]
    first = [e for e in trades if e["trade_index"] == 0]
    assert {e["model"] for e in first} == {"m1_ohlc", "every_tick"}
    e0 = first[0]
    # trade 0 = the FIRST in-window python entry (2024-01-02T08:00 signal,
    # filled next M1 minute 08:01, short 0.01) paired BY TIME with MT5 deal
    # #2 at the same minute -- NOT python entry 0 (2024-01-01, 1.4 lots),
    # which positional pairing compared and which MT5 never tested
    assert e0["pairing"] == s8p.PAIRED_BY_TIME
    assert e0["fields"]["timestamp"] == {"python": "2024-01-02T08:01:00",
                                         "mt5": "2024-01-02T08:01:00"}
    assert e0["fields"]["volume"] == {"python": 0.01, "mt5": 0.01}
    # side and entry price are parsed from MT5's own journal deal line,
    # not left unmeasured: sell 0.01 at 1.09589 (= fixture open at 08:01)
    assert e0["fields"]["entry_side"] == {"python": "sell", "mt5": "sell"}
    assert e0["fields"]["entry_price"] == {"python": 1.09589, "mt5": 1.09589}
    assert "unmeasured_mt5_fields" not in e0
    assert "deal #2 sell 0.01 EURUSD.G2 at 1.09589" in e0["mt5_deal_line"]
    # S8-WEIGHT-1: the python column is the weight-in-force window run,
    # cross-referenced to the frozen row (08:00 signal = array index 19)
    assert e0["expected_set"] == s8p.EXPECTED_SET_WINDOW_RUN
    assert e0["frozen_row_index"] == 19
    # entry counts compare INSIDE the window: 37 in-window entries of the
    # weight-1.0 window run (the frozen trace's 62 approved rows are the
    # cross-reference, never the compared set)
    count = recon["events"][-1]
    assert count["fields"]["entry_count:m1_ohlc"] == {"python": 37, "mt5": 2}
    assert count["python_out_of_tested_window"]["m1_ohlc"] == 30
    assert count["python_frozen_only_scheduled_weight"]["m1_ohlc"] == 21


def test_out_of_window_and_frozen_only_rows_are_never_divergences(run26):
    _, pkg, _ = run26
    recon = json.loads((pkg / "reconciliation/gold2.json").read_text())
    out = [e for e in recon["events"]
           if e.get("pairing") == s8p.OUT_OF_TESTED_WINDOW]
    # S8-WEIGHT-1: the expected set is the weight-1.0 window run, flat
    # before the measured start -- nothing can fill before it. Its 30
    # 2024-01-04 entries (the ToDate day; MT5 ToDate is exclusive) are
    # OUT per model, recorded uncompared
    assert len(out) == 60
    for e in out:
        assert e["python_fill_time"] >= "2024-01-04T00:00:00"
        assert e["mt5_window_end"] == "2024-01-04T00:00:00"
        assert "ToDate 2024.01.04" in e["mt5_window_end_source"]
        assert "exclusive" in e["mt5_window_end_source"]
        assert e["expected_set"] == s8p.EXPECTED_SET_WINDOW_RUN
        assert e["fields"] == {}
        assert "trade_index" not in e
    # the 2024-01-01 frozen rows (19), the 08:08 scheduled-weight
    # persistence re-entry (1) and the frozen 01-04 10:38 row the
    # weight-1.0 run does not make (1) are FROZEN_ONLY_SCHEDULED_WEIGHT:
    # informational, NO compared fields, never divergences
    fo = [e for e in recon["events"]
          if e.get("pairing") == s8p.FROZEN_ONLY_SCHEDULED_WEIGHT]
    assert len(fo) == 42
    reasons = sorted(e["reason"] for e in fo
                     if e["model"] == "m1_ohlc")
    assert reasons.count("before_window_start") == 19
    assert reasons.count("scheduled_weight_only") == 1
    assert reasons.count("at_or_after_window_end") == 1
    sw = next(e for e in fo if e["reason"] == "scheduled_weight_only"
              and e["model"] == "m1_ohlc")
    assert sw["python_signal_time"] == "2024-01-02T08:07:00"
    assert sw["entry_kind"] == "persistence_reentry"
    assert sw["frozen_row_index"] == 20
    assert sw["python_volume_frozen_basis"] == 0.02
    for e in fo:
        assert e["fields"] == {}
        assert "trade_index" not in e
    # window and frozen-only are NAMED LIMITATIONS, never divergences
    assert any("OUT_OF_TESTED_WINDOW" in lim
               and "never this comparison's divergence" in lim
               for lim in recon["limitations"])
    assert any("window end 2024-01-04T00:00:00" in lim
               for lim in recon["limitations"])
    assert any("FROZEN_ONLY_SCHEDULED_WEIGHT" in lim
               and "1 scheduled_weight_only" in lim
               for lim in recon["limitations"])


def test_unpaired_trades_inside_the_window_are_divergences(run26):
    _, pkg, _ = run26
    recon = json.loads((pkg / "reconciliation/gold2.json").read_text())
    missing = [e for e in recon["events"]
               if e.get("pairing") == s8p.MISSING_IN_MT5]
    # 37 in-window entries of the weight-1.0 run, 2 paired per model ->
    # 35 missing each (S8-WEIGHT-1: the 08:08 scheduled-weight re-entry is
    # FROZEN_ONLY, no longer a MISSING_IN_MT5 divergence)
    assert len(missing) == 70
    # nothing on the excluded ToDate day is ever MISSING_IN_MT5
    assert all(e["python_signal_time"] < "2024-01-04" for e in missing)
    assert not any(e["python_signal_time"] == "2024-01-02T08:07:00"
                   for e in missing)
    m0 = min(missing, key=lambda e: e["index"])
    assert m0["python_signal_time"] == "2024-01-02T09:12:00"
    spec = m0["fields"]["state"]
    assert spec["python"] == "entry 2024-01-02T09:13:00 short 0.98 lots"
    assert spec["mt5"].startswith("MISSING_IN_MT5")
    assert og.classify_field("state") == og.STATE_MISMATCH
    # paired volume/price divergences stay measured: 08:46 buy 0.28 at
    # 1.09700 (MT5, synthetic) vs python at the named buy fill model
    # ask = open 1.09725 + 1 spread point. The volume compared is the
    # WINDOW basis (0.28, re-run from 10000 at the 2024-01-02 start); the
    # frozen-basis 0.25 (basis 9085.28, carries 2024-01-01) stays beside
    e46 = next(e for e in recon["events"]
               if e.get("pairing") == s8p.PAIRED_BY_TIME
               and e["time"] == "2024-01-02T08:46:00")
    assert e46["fields"]["volume"] == {"python": 0.28, "mt5": 0.28}
    assert e46["python_volume_frozen_basis"] == 0.25
    assert e46["python_volume_window_basis"] == 0.28
    assert e46["python_volume_basis"].startswith("WINDOW_RUN: ")
    assert e46["fill_model"] == s8p.FILL_MODEL_BUY
    assert e46["fields"]["entry_price"] == {"python": 1.09726, "mt5": 1.097}
    assert e46["fields"]["entry_side"] == {"python": "buy", "mt5": "buy"}


def test_extra_mt5_entries_are_divergences():
    py = [{"signal_time": "2024-01-02T08:00:00",
           "fill_time": "2024-01-02T08:01:00", "side": "short",
           "lots": 0.01}]
    deals = [
        {"ticket": 2, "time": "2024.01.02 08:01:00", "volume": 0.01,
         "pnl": 0.0, "lines": []},
        {"ticket": 4, "time": "2024.01.02 09:30:00", "volume": 0.5,
         "pnl": 0.0, "lines": []},
    ]
    events, summary = s8p.reconciliation_events(
        py, {"m1_ohlc": deals}, "EURUSD.G2")
    extra = [e for e in events if e.get("pairing") == s8p.EXTRA_IN_MT5]
    assert len(extra) == 1 and extra[0]["mt5_ticket"] == 4
    assert extra[0]["fields"]["state"]["python"].startswith("EXTRA_IN_MT5")
    assert "deal #4 at 2024-01-02T09:30:00" in \
        extra[0]["fields"]["state"]["mt5"]
    assert summary["m1_ohlc"] == {
        "paired": 1, "missing_in_mt5": 0, "extra_in_mt5": 1,
        "out_of_tested_window": 0, "out_before_start": 0,
        "out_at_or_after_end": 0, "frozen_only_scheduled_weight": 0,
        "expected_set": (s8p.EXPECTED_SET_FROZEN
                         + " (fallback: no expected-set run supplied)"),
        "mt5_window_start": None,
        "mt5_window_start_line": None, "mt5_window_end": None}
    # no measured window start -> nothing is out of window, and the paired
    # event's side/price stay unmeasured when no MT5 journal line states them
    paired = next(e for e in events if e.get("pairing") == s8p.PAIRED_BY_TIME)
    assert paired["unmeasured_mt5_fields"] == ["side", "entry_price"]
    assert "entry_side" not in paired["fields"]


def test_volume_compares_the_tester_weight_column_never_the_closest():
    """gate_run28 finding 3: MT5 runs at InpBaseGateWeight=1.0 (no
    allocation file), so the python volume column is meta['1.0'].final_lots
    — fixed, recorded per event, with approved_lots kept beside it
    labelled. A DROP/absent column leaves the volume UNCOMPARED with the
    reason stated; nothing is substituted or matched-to-closest."""
    expected = {"entries": [
        {"signal_time": "2024-01-02T08:00:00", "side": "short",
         "risk": {"approved_lots": 4.58, "rejected": False},
         "meta": {"1.0": {"action": "SEND", "final_lots": 4.58},
                  "0.1": {"action": "SEND", "final_lots": 0.45}}},
        {"signal_time": "2024-01-02T08:05:00", "side": "long",
         "risk": {"approved_lots": 0.009, "rejected": False},
         "meta": {"1.0": {"action": "DROP", "final_lots": 0.0}}},
        {"signal_time": "2024-01-02T08:10:00", "side": "long",
         "risk": {"approved_lots": 1.0, "rejected": False}},
    ]}
    py, note = s8p.python_entries(expected, "M1")
    assert 'meta["1.0"].final_lots' in note
    assert py[0]["compare_lots"] == 4.58 and py[0]["lots"] == 4.58
    assert py[1]["compare_lots"] is None
    assert "action 'DROP'" in py[1]["compare_lots_note"]
    assert py[2]["compare_lots"] is None
    assert "no meta['1.0'] expectation" in py[2]["compare_lots_note"]
    deals = [{"ticket": k, "time": f"2024.01.02 08:{m:02d}:00",
              "volume": 0.45, "pnl": 0.0, "lines": []}
             for k, m in ((2, 1), (4, 6), (6, 11))]
    events, _ = s8p.reconciliation_events(py, {"m1_ohlc": deals},
                                          "EURUSD.G2")
    paired = [e for e in events if e.get("pairing") == s8p.PAIRED_BY_TIME]
    assert len(paired) == 3
    # SEND: compared against the 1.0 column (4.58 vs 0.45 diverges) even
    # though the 0.1 column (0.45) would match — never pick the closest
    assert paired[0]["fields"]["volume"] == {"python": 4.58, "mt5": 0.45}
    assert paired[0]["python_volume_column"] == s8p.TESTER_WEIGHT_SOURCE
    assert paired[0]["python_approved_lots"] == 4.58
    # DROP / absent column: MT5 side stays measured, python side absent
    # with the reason stated — and the verifier's completeness rule is
    # satisfied (no python value without an mt5 observation)
    for e, why in ((paired[1], "DROP"), (paired[2], "no meta")):
        assert e["fields"]["volume"] == {"mt5": 0.45}
        assert why in e["python_volume_unavailable"]
        assert e["python_approved_lots"] is not None


def test_window_end_is_exclusive_and_out_is_never_a_divergence():
    py = [
        {"signal_time": "2024-01-03T23:58:00",
         "fill_time": "2024-01-03T23:59:00", "side": "short", "lots": 0.5},
        {"signal_time": "2024-01-03T23:59:00",
         "fill_time": "2024-01-04T00:00:00", "side": "long", "lots": 0.5},
        {"signal_time": "2024-01-04T08:00:00",
         "fill_time": "2024-01-04T08:01:00", "side": "long", "lots": 0.5},
    ]
    deals = [{"ticket": 2, "time": "2024.01.03 23:59:00", "volume": 0.5,
              "pnl": 0.0, "lines": []}]
    events, summary = s8p.reconciliation_events(
        py, {"m1_ohlc": deals}, "EURUSD.G2",
        window_end="2024-01-04T00:00:00",
        window_end_source="tester ToDate 2024.01.04 derived from the "
                          "fixture; MT5 ToDate is exclusive")
    # 23:59 is the last tested minute and pairs; 00:00 exactly at the end
    # and 08:01 after it are OUT, never MISSING_IN_MT5
    assert summary["m1_ohlc"]["paired"] == 1
    assert summary["m1_ohlc"]["missing_in_mt5"] == 0
    assert summary["m1_ohlc"]["out_at_or_after_end"] == 2
    out = [e for e in events if e.get("pairing") == s8p.OUT_OF_TESTED_WINDOW]
    assert [e["python_fill_time"] for e in out] == [
        "2024-01-04T00:00:00", "2024-01-04T08:01:00"]
    for e in out:
        assert e["fields"] == {} and "ToDate" in e["mt5_window_end_source"]
    # the in-window count excludes them
    assert events[-1]["fields"]["entry_count:m1_ohlc"] == {
        "python": 1, "mt5": 1}


def test_tested_window_start_reads_the_measured_line():
    # the real measured format (gate_run23 capture in tests/data/owner_gate)
    line = ("Core 1\tEURUSD.G1: start time changed to 2024.01.06 00:00 "
            "to provide data at beginning")
    assert s8p.tested_window_start(line, "EURUSD.G1") == \
        ("2024-01-06T00:00:00", line)
    # scoped to the leg's symbol; another symbol's line is never used
    assert s8p.tested_window_start(line, "EURUSD.G2") == (None, None)
    assert s8p.tested_window_start("", "EURUSD.G1") == (None, None)


def test_mt5_deal_line_facts_requires_ticket_and_symbol():
    line = "Core 1\tdeal #4 buy 0.28 EURUSD.G2 at 1.09700 done (based on order #4)"
    deal = {"ticket": 4, "lines": ["[EA line]", line]}
    assert s8p.mt5_deal_line_facts(deal, "EURUSD.G2") == {
        "side": "buy", "volume": 0.28, "price": 1.097, "line": line}
    # wrong ticket or wrong symbol: nothing is inferred
    assert s8p.mt5_deal_line_facts({"ticket": 5, "lines": [line]},
                                   "EURUSD.G2") == {}
    assert s8p.mt5_deal_line_facts(deal, "EURUSD.G1") == {}


def test_rebuild_replaces_only_what_the_gate_built(run26, tmp_path):
    _, pkg, ev = run26
    owner_file = pkg / "safety" / "owner_note.txt"
    owner_file.parent.mkdir()
    owner_file.write_text("owner", encoding="utf-8")
    rec = s8p.build_package(repo=REPO, package=pkg, gate_evidence=ev,
                            data_folder=None, golds=["gold2"],
                            symbolspec_export=None)
    assert owner_file.is_file()
    # the EX5 and symbolspec could not be rebuilt: the stale copies are gone
    assert not (pkg / "compile/Mql5Bot.ex5").exists()
    assert not (pkg / "symbolspec/symbolspec.json").exists()
    assert "compile/Mql5Bot.ex5" in rec["removed_previous_build"]


def test_mt5_entry_pairing_is_refused_when_alternation_fails():
    deals = [{"ticket": 1, "pnl": 0.0}, {"ticket": 2, "pnl": 3.0},
             {"ticket": 3, "pnl": 5.0}]
    entries, why = s8p.mt5_entries(deals)
    assert entries is None and "refused" in why


def test_ex5_not_matching_the_stage1_hash_is_not_packaged(tmp_path, run26):
    _, _, ev = run26
    data = tmp_path / "other_data"
    ex5 = data / "MQL5" / "Experts" / "Mql5Bot" / "Mql5Bot.ex5"
    ex5.parent.mkdir(parents=True)
    ex5.write_bytes(b"a different binary")
    pkg = tmp_path / "pkg2"
    rec = s8p.build_package(repo=REPO, package=pkg, gate_evidence=ev,
                            data_folder=data, golds=["gold2"],
                            symbolspec_export=None)
    assert not (pkg / "compile/Mql5Bot.ex5").exists()
    assert "not the binary stage 1 compiled" in rec["not_built"]["compile/Mql5Bot.ex5"]


# ---------------------------------------------------------------------------
# the verifier on the built package
# ---------------------------------------------------------------------------

def test_not_applicable_is_never_missing_and_never_present(run26, tmp_path):
    _, pkg, _ = run26
    rep = _verify(pkg, tmp_path)
    for kind in ("raw", "parsed"):
        assert rep["artifacts"][f"{kind}_gold2_real_ticks"]["state"] == \
            og.NOT_APPLICABLE
        assert f"{kind}_gold2_real_ticks" not in rep["missing"]
    assert rep["not_applicable_legs"] == ["gold2:real_ticks"]
    assert rep["gold"]["gold2"]["trade_sources"]["real_ticks"] == \
        og.TRADE_SOURCE_NOT_APPLICABLE
    assert rep["real_tick_coverage"]["state"] == og.VALID
    assert rep["real_tick_coverage"]["coverage"] == og.REAL_TICK_COVERAGE_NONE


def test_verdict_is_never_positive_and_safety_stays_missing(run26, tmp_path):
    _, pkg, _ = run26
    rep = _verify(pkg, tmp_path)
    assert rep["verdict"] not in og.POSITIVE_VERDICTS
    assert rep["verdict"] != og.MT5_VALIDATED_PARTIAL_SCOPE
    assert {n: rep["safety"][n]["state"] for n in rep["safety"]} == {
        n: og.MISSING for n in og.SAFETY_TESTS + ("netting", "hedging")}


def test_first_divergence_is_surfaced_on_a_fail(run26, tmp_path):
    _, pkg, _ = run26
    rep = _verify(pkg, tmp_path)
    div = rep["first_divergence"]["gold2"]
    assert div is not None
    trade = rep["first_trade_divergence"]["gold2"]
    # S8-WEIGHT-1: trade 0 (08:01) matches on every field, and the 08:08
    # scheduled-weight row is FROZEN_ONLY (informational), so the first
    # divergence is the 08:46 entry_price: the synthetic MT5 line bought
    # at 1.09700 while the named buy fill model gives 1.09726
    assert trade["first_divergent_field"] == "entry_price"
    assert trade["python_value"] == 1.09726
    assert trade["mt5_value"] == 1.097
    assert trade["trade_index"] == 1
    assert trade["classification"] == og.EXECUTION_MISMATCH
    # the package's source_commit is the gate HEAD; the verifier binds it
    # only when it EQUALS the frozen anchor. Any other HEAD (every commit
    # after the anchor, incl. the re-anchor commit itself) leaves the
    # divergence OBSERVED, never binding-verified; at the anchor commit the
    # chain verifies. Both branches are pinned exactly.
    frozen = json.loads((REPO / "artifacts" / "owner_mt5_gate"
                         / "frozen_inputs.json").read_text(encoding="utf-8"))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          capture_output=True, text=True,
                          check=True).stdout.strip()
    at_anchor = head == frozen["source"]["commit"]
    assert trade["binding_verified"] is at_anchor
    note = s8p.divergence_note(rep, ["gold2"])
    assert "first per-trade divergence: field 'entry_price'" in note
    assert ("[observed; binding chain NOT verified]" in note) is \
        (not at_anchor)


def test_cli_divergence_note_quotes_the_report(run26, tmp_path):
    _, pkg, _ = run26
    _verify(pkg, tmp_path)
    cp = subprocess.run([sys.executable, str(DECIDE), "--repo", str(REPO),
                         "stage8-divergence-note", "--verify",
                         str(tmp_path / "reconciliation_verify.json"),
                         "--golds", "gold2"],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 0, cp.stderr
    assert ("field 'entry_price' python=1.09726 mt5=1.097"
            in json.loads(cp.stdout)["note"])


def test_full_coverage_beside_a_not_applicable_leg_is_a_mismatch(run26, tmp_path):
    _, pkg, _ = run26
    cov = pkg / "real_tick_coverage.json"
    cov.write_text(json.dumps({"coverage": "REAL_TICK_COVERAGE_UNKNOWN",
                               "requested_model": "x", "actual_model_from_report": "x",
                               "requested_interval": "a", "actual_interval": "a",
                               "broker": "b", "symbol": "EURUSD"}))
    rep = og.run_gate(pkg, {"source": {"commit": "x"}}, ["gold2"])
    assert rep["real_tick_coverage"]["state"] == og.MISMATCHED
    assert rep["verdict"] == og.NOT_VERIFIED_ARTIFACT_MISMATCH


def test_none_coverage_claiming_an_actual_model_is_invalid(run26):
    _, pkg, _ = run26
    cov_path = pkg / "real_tick_coverage.json"
    cov = json.loads(cov_path.read_text())
    cov["actual_model_from_report"] = "Every tick based on real ticks"
    cov_path.write_text(json.dumps(cov))
    assert og.verify_real_tick_coverage(pkg)["state"] == og.INVALID


def test_none_coverage_without_the_stage5_record_is_a_mismatch(run26):
    _, pkg, _ = run26
    (pkg / og.GATE_STAGE5_REL).unlink()
    assert og.verify_real_tick_coverage(pkg)["state"] == og.MISMATCHED
    rep = og.run_gate(pkg, {"source": {"commit": "x"}}, ["gold2"])
    # without the record the NA slots are plain MISSING again
    assert rep["artifacts"]["raw_gold2_real_ticks"]["state"] == og.MISSING


def test_a_report_for_a_not_applicable_leg_is_invalid(run26):
    _, pkg, _ = run26
    (pkg / "gold2").mkdir()
    (pkg / "gold2" / "real_ticks.htm").write_text("<html/>")
    scan = og.scan_package(pkg)
    assert scan["raw_gold2_real_ticks"]["state"] == og.INVALID


def test_tester_models_cannot_claim_not_applicable_without_the_record(run26):
    _, pkg, _ = run26
    recon_path = pkg / "reconciliation/gold2.json"
    recon = json.loads(recon_path.read_text())
    recon["bindings"]["tester_models"]["every_tick"] = {
        "not_applicable": True, "outcome": og.STAGE5_NOT_APPLICABLE}
    recon_path.write_text(json.dumps(recon))
    frozen = {"source_commit": recon["bindings"]["source_commit"],
              "gold2": {}}
    rep = og.verify_reconciliation(pkg, "gold2", frozen, {})
    assert rep["state"] == og.MISMATCHED
    assert any("does not mark it NOT_APPLICABLE" in r for r in rep["reasons"])


# ---------------------------------------------------------------------------
# owner_gate.ps1 wiring (source)
# ---------------------------------------------------------------------------

def _s8() -> str:
    s = PS1.index('Enter-Stage 8 "reconciliation"')
    return PS1[s:PS1.index("STAGE 9", s)]


def test_ps1_builds_the_package_before_stage8_verifies():
    s8 = _s8()
    assert s8.index('Invoke-Decide @("place-log-trades"') \
        < s8.index('Invoke-Decide @("build-stage8-package"') \
        < s8.index("verify_owner_mt5_gate.py")
    assert '"--gate-evidence", $Evidence' in s8
    assert '"--symbolspec", $SymbolSpecExport' in s8


def test_ps1_quotes_the_divergence_and_classifies_only_verified_ones():
    s8 = _s8()
    assert 'Invoke-Decide @("stage8-divergence-note"' in s8
    note = s8.index("stage8-divergence-note")
    assert note < s8.index('Record-Stage 8 "reconciliation" "PASS"')
    assert '(Get-DataProp $fd "binding_verified") -eq $true' in s8
