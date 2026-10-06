"""S8-COUNT-1 / S8-TS-1 / S8-TICKPATH-1 / S8-SLTP-1 (owner decisions,
2026-10-06, docs/DECISIONS.md).

Verifier/builder self-tests: a green test here is NOT MT5 evidence.

* unit tests quote gate_run35 lines verbatim (tester_gold2_*_window.txt and
  the log trade lists of that run, 2026-10-06; tab-separated log prefix
  kept) -- the deal-33 tick-path divergence, the 08:32:01 fill on the flat
  08:32 bar, and the entry request lines' sl/tp;
* package tests build a gate package from SYNTHETIC deals in the measured
  formats (see tests/data/owner_gate/tester_window_gate_run27_lines.txt):
  the every_tick leg's first exit leaves the m1_ohlc path, so its later
  entry is sized on MT5's own equity, while m1_ohlc stays fully strict.
"""

from __future__ import annotations

import copy
import json

import pytest
from mql5bot import owner_gate as og
from mql5bot import stage8_package as s8p
from mql5bot import tester_log_grader as tlg
from test_stage8_package_from_gate import (
    CAPTURE,
    OWNER_COMPILE_LOG,
    REAL_EA_HASH,
    REPO,
    RUN27_LINES,
    _stage5_record,
)

# --- gate_run35 lines, verbatim ---------------------------------------------
R35_M1_DEAL35 = {
    "entry": None, "pnl": 137.28, "price": 1.10007, "side": "sell",
    "symbol": "EURUSD.G2", "ticket": 35, "time": "2024.01.03 08:30:40",
    "volume": 3.52,
    "lines": [("HR\t0\t00:57:44.780\tCore 1\t2024.01.03 08:30:40   "
               "[2024.01.03 08:30:40] [INFO] DEAL #35 EURUSD.G2 vol=3.52 "
               "price=1.10007 pnl=137.28"),
              ("PQ\t0\t00:57:44.780\tCore 1\t2024.01.03 08:30:40   deal "
               "#35 sell 3.52 EURUSD.G2 at 1.10007 done (based on order "
               "#35)")]}
R35_ET_DEAL35 = {
    "entry": None, "pnl": 151.36, "price": 1.10011, "side": "sell",
    "symbol": "EURUSD.G2", "ticket": 35, "time": "2024.01.03 08:30:05",
    "volume": 3.52,
    "lines": [("MK\t0\t00:58:18.936\tCore 1\t2024.01.03 08:30:05   "
               "[2024.01.03 08:30:05] [INFO] DEAL #35 EURUSD.G2 vol=3.52 "
               "price=1.10011 pnl=151.36"),
              ("OH\t0\t00:58:18.936\tCore 1\t2024.01.03 08:30:05   deal "
               "#35 sell 3.52 EURUSD.G2 at 1.10011 done (based on order "
               "#35)")]}
R35_DEAL34 = {"entry": "open", "pnl": 0.0, "price": 1.09968, "side": "buy",
              "symbol": "EURUSD.G2", "ticket": 34,
              "time": "2024.01.03 08:01:00", "volume": 3.52, "lines": []}
_P = "\t0\t00:57:44.780\tCore 1\t"
R35_WINDOW = (
    f"ID{_P}2024.01.03 08:01:00   instant buy 3.52 EURUSD.G2 at 1.09968 "
    "sl: 1.09942 tp: 1.10007 (1.09967 / 1.09968 / 1.09967)\n"
    f"PJ{_P}2024.01.03 08:01:00   deal #34 buy 3.52 EURUSD.G2 at 1.09968 "
    "done (based on order #34)\n"
    f"PQ{_P}2024.01.03 08:30:40   deal #35 sell 3.52 EURUSD.G2 at 1.10007 "
    "done (based on order #35)\n"
    f"LH{_P}2024.01.03 08:32:01   instant sell 0.84 EURUSD.G2 at 1.09636 "
    "sl: 1.09745 tp: 1.09472 (1.09636 / 1.09637 / 1.09636)\n"
    f"IE{_P}2024.01.03 08:32:01   deal #38 sell 0.84 EURUSD.G2 at 1.09636 "
    "done (based on order #38)\n"
    f"QR{_P}2024.01.03 09:07:00   instant buy 0.84 EURUSD.G2 at 1.09675, "
    "close #38 (1.09674 / 1.09675 / 1.09674)\n"
    f"DS{_P}2024.01.03 09:07:00   deal #39 buy 0.84 EURUSD.G2 at 1.09675 "
    "done (based on order #39)\n")


# ---------------------------------------------------------------------------
# unit: tick-path divergence, entry deals, request levels (gate_run35 lines)
# ---------------------------------------------------------------------------

def test_tick_path_divergence_is_the_gate_run35_ticket_35():
    # gate_run35: deal index 33 of 74 (ticket #35); here the two deals
    # before it are cut to the one entry they share
    ref = [R35_DEAL34, R35_M1_DEAL35]
    tick = [R35_DEAL34, R35_ET_DEAL35]
    rec, _ = og.tick_path_divergence(ref, tick)
    assert rec["classification"] == og.TICK_PATH_DIVERGENCE
    assert rec["observed"] is True
    assert (rec["deal_index"], rec["ticket"]) == (1, 35)
    assert (rec["tick_deal"]["time"], rec["tick_deal"]["price"],
            rec["tick_deal"]["pnl"]) == ("2024.01.03 08:30:05", 1.10011,
                                         151.36)
    assert (rec["reference_deal"]["time"], rec["reference_deal"]["price"],
            rec["reference_deal"]["pnl"]) == ("2024.01.03 08:30:40", 1.10007,
                                              137.28)
    # both deal lines are recorded
    assert "deal #35 sell 3.52 EURUSD.G2 at 1.10011" in \
        rec["tick_deal"]["lines"][1]
    assert "deal #35 sell 3.52 EURUSD.G2 at 1.10007" in \
        rec["reference_deal"]["lines"][1]


def test_identical_lists_have_no_tick_path_divergence():
    deals = [R35_DEAL34, R35_M1_DEAL35]
    assert og.tick_path_divergence(deals, copy.deepcopy(deals))[0] is None


def test_an_entry_difference_first_is_not_a_tick_path_divergence():
    other = dict(R35_DEAL34, volume=3.51)
    rec, note = og.tick_path_divergence([R35_DEAL34, R35_M1_DEAL35],
                                        [other, R35_ET_DEAL35])
    assert rec is None
    assert "not an exit time/price difference" in note


def test_log_entry_deals_are_the_open_deals_only():
    # an SL/TP exit has no request line (entry None): never an entry
    assert og.log_entry_deals([R35_DEAL34, R35_ET_DEAL35]) == [R35_DEAL34]


def test_entry_request_levels_read_mt5s_own_request_line():
    lv = og.entry_request_levels(R35_WINDOW, "EURUSD.G2")
    assert set(lv) == {34, 38}  # #35 (TP) and #39 (close) carry none
    assert (lv[34]["sl"], lv[34]["tp"]) == (1.09942, 1.10007)
    assert (lv[38]["sl"], lv[38]["tp"]) == (1.09745, 1.09472)
    assert "instant sell 0.84 EURUSD.G2 at 1.09636" in lv[38]["request_line"]
    assert "deal #38 sell 0.84" in lv[38]["deal_line"]
    # another symbol's lines are never read
    assert og.entry_request_levels(R35_WINDOW, "EURUSD.G1") == {}


def test_python_sl_tp_reproduce_the_gate_run35_request_lines():
    # 08:01 buy 3.52 at 1.09968 and 08:32 sell 0.84 at 1.09636 (the open of
    # the flat 08:32 bar, O=H=L=C 1.09636 in the frozen fixture)
    ctx, note = s8p.python_risk_context(REPO, "gold2")
    assert ctx is not None, note
    a = s8p.python_stop_levels(ctx, "2024-01-03T08:01", "buy", 1.09968)
    assert (a["sl"], a["tp"]) == (1.09942, 1.10007)
    b = s8p.python_stop_levels(ctx, "2024-01-03T08:32", "sell", 1.09636)
    assert (b["sl"], b["tp"]) == (1.09745, 1.09472)


def test_python_sl_refused_when_atr_disagrees_with_the_frozen_stop():
    ctx, _ = s8p.python_risk_context(REPO, "gold2")
    bad = dict(ctx, frozen_stop={k: v * 2 for k, v in
                                 ctx["frozen_stop"].items()})
    out = s8p.python_stop_levels(bad, "2024-01-02T08:01", "sell", 1.09589)
    assert "frozen stop_distance" in out["refused"]


def test_mt5_equity_sizing_needs_a_flat_book_and_a_deposit():
    deals = [R35_DEAL34, R35_ET_DEAL35, dict(R35_DEAL34, ticket=36)]
    stops = {"stop_distance": 0.0004}

    def rule(eq, sd):
        return 1.0

    facts, why = s8p._mt5_equity_sizing(deals, 2, (10000.0, "ini"), stops,
                                        rule)
    assert why is None
    assert facts["mt5_pre_entry_equity"] == 10151.36
    assert facts["book_flat_at_entry"] is True
    _, why = s8p._mt5_equity_sizing(deals, 1, (10000.0, "ini"), stops, rule)
    assert "not flat" in why
    _, why = s8p._mt5_equity_sizing(deals, 2, (None, "no Deposit"), stops,
                                    rule)
    assert "no deposit" in why


# ---------------------------------------------------------------------------
# package: every_tick leaves the m1_ohlc path at its first exit
# ---------------------------------------------------------------------------

# EA DEAL lines (measured format). m1_ohlc: the run27 synthetic deals.
M1_DEALS = [
    "[2024.01.02 08:01:00] [INFO] DEAL #2 EURUSD.G2 vol=0.01 price=1.09589 pnl=0.00",
    "[2024.01.02 08:07:00] [INFO] DEAL #3 EURUSD.G2 vol=0.01 price=1.09659 pnl=-0.70",
    "[2024.01.02 08:46:00] [INFO] DEAL #4 EURUSD.G2 vol=0.28 price=1.09700 pnl=0.00",
    "[2024.01.02 09:12:00] [INFO] DEAL #5 EURUSD.G2 vol=0.28 price=1.09650 pnl=-14.00",
]
# every_tick: the first exit (#3) fills earlier at another price -- the
# tick-path divergence -- and books a (synthetic) +800.00, so MT5's own
# equity, and the frozen sizing rule on it, part from the python path:
# the 08:46 entry is 0.30 on 10800.00 where the python path sizes 0.28
ET_DEALS = [
    M1_DEALS[0],
    ("[2024.01.02 08:06:30] [INFO] DEAL #3 EURUSD.G2 vol=0.01 "
     "price=1.09660 pnl=800.00"),
    "[2024.01.02 08:46:00] [INFO] DEAL #4 EURUSD.G2 vol=0.30 price=1.09700 pnl=0.00",
    "[2024.01.02 09:12:00] [INFO] DEAL #5 EURUSD.G2 vol=0.30 price=1.09650 pnl=-15.00",
]


def _window(model_line: str, deals: list[str]) -> str:
    lines = [ln for ln in CAPTURE.read_text(encoding="utf-8").splitlines()
             if ln and not ln.startswith("#") and "EURUSD.G1" not in ln
             and "generating" not in ln]
    return "\n".join([model_line, *lines, *RUN27_LINES,
                      ("[2024.01.02 00:00:00] [INFO] generic DSL execution "
                       "enabled: gold2_multifactor"), *deals]) + "\n"


@pytest.fixture()
def tick(tmp_path):
    ev, data, pkg = tmp_path / "gate_ev", tmp_path / "data", tmp_path / "pkg"
    ev.mkdir()
    ex5 = data / "MQL5" / "Experts" / "Mql5Bot" / "Mql5Bot.ex5"
    ex5.parent.mkdir(parents=True)
    ex5.write_bytes(b"synthetic ex5 bytes for the tick-path test")
    log = OWNER_COMPILE_LOG.read_text(encoding="utf-8-sig").replace(
        REAL_EA_HASH, s8p._sha(ex5).upper())
    (ev / "compile-20260917-201954.log").write_text(log, encoding="utf-8")
    (ev / "stage_5.json").write_text(json.dumps(_stage5_record()),
                                     encoding="ascii")
    spec = tmp_path / "EURUSD.json"
    spec.write_text(json.dumps({"symbol": "EURUSD", "point": 1e-05,
                                "server": "MetaQuotes-Demo"}),
                    encoding="utf-8")
    for model, req, line, deals in (
            ("m1_ohlc", 1, ("EURUSD.G2,M1 (MetaQuotes-Demo): 1 minutes "
                            "OHLC ticks generating"), M1_DEALS),
            ("every_tick", 0, ("EURUSD.G2,M1 (MetaQuotes-Demo): every "
                               "tick generating"), ET_DEALS)):
        win = _window(line, deals)
        (ev / f"tester_gold2_{model}_window.txt").write_text(win,
                                                             encoding="utf-8")
        # the intended tester config (Deposit) the gate copies, from the
        # same derivation the gate uses
        (ev / f"tester_gold2_{model}.ini").write_text(
            "[Tester]\nSymbol=EURUSD.G2\nDeposit=10000.00\nCurrency=USD\n",
            encoding="utf-8")
        grade = tlg.grade_leg_from_log(window_text=win, symbol="EURUSD.G2",
                                       requested_model=req,
                                       leg=f"gold2_{model}",
                                       expected_strategy="gold2_multifactor")
        assert grade["outcome"] == "PASS_FROM_LOG", grade["reason"]
        trades = ev / f"tester_gold2_{model}_log_trades.json"
        trades.write_text(json.dumps(tlg.log_trade_list(grade, win.encode())),
                          encoding="utf-8")
        assert tlg.place_log_trades(trades, pkg, "gold2", model, REPO)["ok"]
    rec = s8p.build_package(repo=REPO, package=pkg, gate_evidence=ev,
                            data_folder=data, golds=["gold2"],
                            symbolspec_export=spec,
                            host={"os": "Windows (test)", "timezone": "UTC"})
    assert rec["ok"], rec
    return pkg


def _recon(pkg):
    return json.loads((pkg / "reconciliation/gold2.json").read_text())


def _paired(doc, model, ticket):
    (e,) = [e for e in doc["events"] if e.get("model") == model
            and e.get("pairing") == og.PAIRED_BY_TIME
            and e.get("mt5_ticket") == ticket]
    return e


FROZEN_INPUTS = json.loads((REPO / "artifacts/owner_mt5_gate/"
                            "frozen_inputs.json").read_text())


def _ref() -> dict:
    ref = og.sizing_reference(REPO, FROZEN_INPUTS["gold_2"])
    assert ref is not None  # the repo files equal the frozen pins
    return ref


def _verify(pkg, doc=None, ref="pinned") -> dict:
    if doc is not None:
        (pkg / "reconciliation/gold2.json").write_text(json.dumps(doc))
    fman = {"python_trade_count": 56}
    if ref is not None:
        fman["sizing_reference"] = _ref() if ref == "pinned" else ref
    return og.verify_reconciliation(pkg, "gold2", {"gold2": fman}, {})


def test_window_copies_are_packaged_and_bound(tick):
    man = json.loads((tick / "archive_manifest.json").read_text())
    for model in ("m1_ohlc", "every_tick"):
        rel = og.log_window_rel("gold2", model)
        lst = json.loads((tick / og.log_trades_rel("gold2", model))
                         .read_text())
        assert s8p._sha(tick / rel) == lst["window_sha256"] == \
            man["artifacts"][rel]


def test_builder_records_the_tick_path_divergence(tick):
    doc = _recon(tick)
    rec = doc["tick_path_divergence"]["every_tick"]["record"]
    assert (rec["deal_index"], rec["ticket"]) == (1, 3)
    assert rec["tick_deal"]["time"] == "2024.01.02 08:06:30"
    assert rec["reference_deal"]["time"] == "2024.01.02 08:07:00"
    assert any(og.TICK_PATH_DIVERGENCE in x for x in doc["limitations"])


def test_after_the_tick_path_volume_is_sized_on_mt5_equity(tick):
    doc = _recon(tick)
    before = _paired(doc, "every_tick", 2)
    assert "basis" not in before["fields"]["volume"]  # python path
    after = _paired(doc, "every_tick", 4)
    vol = after["fields"]["volume"]
    assert vol["basis"] == og.VOLUME_BASIS_MT5_EQUITY
    # equity = Deposit 10000 + pnl of #2 (0) and #3 (+800), book flat
    assert after["mt5_pre_entry_equity"] == 10800.0
    assert after["book_flat_at_entry"] is True
    assert after["mt5_deposit"] == 10000.0
    ctx, _ = s8p.python_risk_context(REPO, "gold2")
    assert vol["python"] == s8p.frozen_rule_lots(
        ctx["spec"], ctx["risk"], 10800.0, after["python_stop_distance"])
    assert vol == {"python": 0.3, "mt5": 0.3,
                   "basis": og.VOLUME_BASIS_MT5_EQUITY}
    # the python-path volume stays beside it, recorded, uncompared
    assert after["python_volume_path"] == 0.28


def test_m1_ohlc_stays_fully_strict(tick):
    doc = _recon(tick)
    e = _paired(doc, "m1_ohlc", 4)
    assert e["fields"]["volume"] == {"python": 0.28, "mt5": 0.28}
    assert "tick_path" not in e
    assert doc["tick_path_divergence"] == {
        "every_tick": doc["tick_path_divergence"]["every_tick"]}


def test_verifier_accepts_the_rules_and_still_diverges_on_m1(tick):
    rep = _verify(tick)
    assert rep["state"] == og.MISMATCHED, rep["reasons"]
    assert rep["entry_counts"]["every_tick"] == {
        "paired": 2, "missing_in_mt5": 35, "extra_in_mt5": 0,
        "mt5_entry_deals": 2, "mt5_deals": 4}
    assert rep["tick_path_divergence"]["every_tick"]["record"]["ticket"] == 3
    # entry_count python 37 (2 paired + 35 missing) vs 2 entry deals
    assert rep["first_divergence"]["first_divergent_field"] == \
        "entry_count:every_tick"


def test_tampered_tick_path_record_is_invalid(tick):
    doc = _recon(tick)
    doc["tick_path_divergence"]["every_tick"]["record"]["deal_index"] = 3
    rep = _verify(tick, doc)
    assert rep["state"] == og.INVALID
    assert "recorded tick-path divergence" in " ".join(rep["reasons"])


def test_tampered_pre_entry_equity_is_invalid(tick):
    doc = _recon(tick)
    _paired(doc, "every_tick", 4)["mt5_pre_entry_equity"] = 10800.01
    rep = _verify(tick, doc)
    assert rep["state"] == og.INVALID
    assert "the bound deals give 10800.0" in " ".join(rep["reasons"])


def test_m1_ohlc_may_never_use_the_mt5_equity_basis(tick):
    doc = _recon(tick)
    _paired(doc, "m1_ohlc", 4)["fields"]["volume"]["basis"] = \
        og.VOLUME_BASIS_MT5_EQUITY
    rep = _verify(tick, doc)
    assert rep["state"] == og.INVALID
    assert "m1_ohlc: ticket 4 volume basis" in " ".join(rep["reasons"])


def test_python_path_after_the_tick_path_is_refused(tick):
    doc = _recon(tick)
    del _paired(doc, "every_tick", 4)["fields"]["volume"]["basis"]
    rep = _verify(tick, doc)
    assert rep["state"] == og.INVALID
    assert "but the deal is after the tick-path divergence" in \
        " ".join(rep["reasons"])


def test_wrong_python_volume_with_correct_equity_is_invalid(tick):
    # the package's python value is never trusted: the verifier recomputes
    # the lots from the equity it recomputed, the frozen stop_distance and
    # the pinned broker_spec (owner review of PR #30)
    doc = _recon(tick)
    e = _paired(doc, "every_tick", 4)
    assert e["mt5_pre_entry_equity"] == 10800.0  # correct equity
    e["fields"]["volume"]["python"] = 0.29
    rep = _verify(tick, doc)
    assert rep["state"] == og.INVALID
    assert ("every_tick: ticket 4 package states python volume 0.29; the "
            "verifier recomputes 0.3 (equity 10800.0") in \
        " ".join(rep["reasons"])


def test_recomputed_lots_unequal_to_mt5_diverge(tick):
    # a sizing reference whose rule gives other lots than MT5 traded: the
    # package agrees with the verifier, and the field diverges
    ref = copy.deepcopy(_ref())
    ref["risk_config"]["risk_percent"] = 0.5
    doc = _recon(tick)
    e = _paired(doc, "every_tick", 4)
    from mql5bot.symbolspec import SymbolSpec
    lots = og.frozen_rule_lots(
        SymbolSpec(**ref["broker_spec"]), ref["risk_config"], 10800.0,
        ref["stop_distance_by_row"][e["frozen_row_index"]])
    assert lots != 0.3
    e["fields"]["volume"]["python"] = lots
    rep = _verify(tick, doc, ref=ref)
    assert rep["state"] == og.MISMATCHED, rep["reasons"]
    div = rep["first_trade_divergence"]
    assert div is not None


def test_mt5_equity_volume_without_a_pinned_reference_is_invalid(tick):
    rep = _verify(tick, ref=None)
    assert rep["state"] == og.INVALID
    assert "MT5-equity volume not verifiable" in " ".join(rep["reasons"])


def test_sizing_reference_refuses_unpinned_bytes():
    bad = dict(FROZEN_INPUTS["gold_2"], manifest_sha256="0" * 64)
    assert og.sizing_reference(REPO, bad) is None


# --- S8-TS-1 ------------------------------------------------------------------

def test_bar_level_timestamp_needs_an_exact_entry_price(tick):
    doc = _recon(tick)
    e = _paired(doc, "every_tick", 2)
    assert e["fields"]["timestamp"]["python"] == \
        e["fields"]["timestamp"]["mt5"] == "2024-01-02T08:01"
    e["fields"]["entry_price"]["mt5"] = 1.09590
    events = [dict(x) for x in doc["events"]]
    _, out, problems, _ = og._log_leg_checks(
        tick, "gold2", _log_docs(tick), events,
        doc["tick_path_divergence"], 56, _ref())
    assert problems == []
    (ts,) = [x["fields"]["timestamp"] for x in out
             if x.get("model") == "every_tick" and x.get("mt5_ticket") == 2]
    assert ts["status"] == "DIVERGENT"
    assert "no exact entry_price match on this event" in ts["s8_ts1_refused"]
    assert og._field_divergent(ts)


def test_bar_level_timestamp_holds_beside_an_exact_price(tick):
    doc = _recon(tick)
    _, out, problems, _ = og._log_leg_checks(
        tick, "gold2", _log_docs(tick), doc["events"],
        doc["tick_path_divergence"], 56, _ref())
    assert problems == []
    (ts,) = [x["fields"]["timestamp"] for x in out
             if x.get("model") == "every_tick" and x.get("mt5_ticket") == 2]
    assert not og._field_divergent(ts)


def test_a_different_minute_still_diverges(tick):
    doc = _recon(tick)
    e = _paired(doc, "every_tick", 2)
    e["fields"]["timestamp"]["python"] = "2024-01-02T08:02"
    _, out, _, _ = og._log_leg_checks(
        tick, "gold2", _log_docs(tick), doc["events"],
        doc["tick_path_divergence"], 56, _ref())
    (ts,) = [x["fields"]["timestamp"] for x in out
             if x.get("model") == "every_tick" and x.get("mt5_ticket") == 2]
    assert og._field_divergent(ts)


def test_a_raw_time_that_is_not_the_deals_own_diverges(tick):
    doc = _recon(tick)
    _paired(doc, "every_tick", 2)["mt5_time_raw"] = "2024-01-02T08:01:59"
    _, out, _, _ = og._log_leg_checks(
        tick, "gold2", _log_docs(tick), doc["events"],
        doc["tick_path_divergence"], 56, _ref())
    (ts,) = [x["fields"]["timestamp"] for x in out
             if x.get("model") == "every_tick" and x.get("mt5_ticket") == 2]
    assert "raw MT5 time is not the bound deal's time" in ts["s8_ts1_refused"]


def _log_docs(pkg) -> dict:
    return {m: json.loads((pkg / og.log_trades_rel("gold2", m)).read_text())
            for m in ("m1_ohlc", "every_tick")}


# --- S8-SLTP-1 ----------------------------------------------------------------

def test_sl_tp_are_compared_on_every_paired_event(tick):
    doc = _recon(tick)
    for model in ("m1_ohlc", "every_tick"):
        e = _paired(doc, model, 2)
        assert e["fields"]["sl"] == {"python": 1.16598, "mt5": 1.16598}
        assert e["fields"]["tp"] == {"python": 0.99075, "mt5": 0.99075}


def test_sl_mt5_value_must_be_the_request_lines(tick):
    doc = _recon(tick)
    _paired(doc, "every_tick", 2)["fields"]["sl"]["mt5"] = 1.16597
    rep = _verify(tick, doc)
    assert rep["state"] == og.INVALID
    assert "every_tick: ticket 2 sl mt5=1.16597 is not the request line's " \
        "1.16598" in " ".join(rep["reasons"])


def test_a_paired_event_without_sl_tp_is_invalid(tick):
    doc = _recon(tick)
    del _paired(doc, "m1_ohlc", 2)["fields"]["tp"]
    rep = _verify(tick, doc)
    assert rep["state"] == og.INVALID
    assert "m1_ohlc: ticket 2 carries no tp field (S8-SLTP-1)" in \
        " ".join(rep["reasons"])


def test_a_python_tp_off_by_one_point_diverges(tick):
    doc = _recon(tick)
    _paired(doc, "m1_ohlc", 2)["fields"]["tp"]["python"] = 0.99076
    rep = _verify(tick, doc)
    assert rep["state"] == og.MISMATCHED
    div = rep["first_trade_divergence"]
    assert (div["first_divergent_field"], div["model"]) == ("tp", "m1_ohlc")
    assert div["classification"] == og.ROUNDING_MISMATCH


def test_a_window_copy_that_is_not_the_lists_window_is_invalid(tick):
    path = tick / og.log_window_rel("gold2", "every_tick")
    path.write_bytes(path.read_bytes() + b"\n")
    rep = _verify(tick)
    assert rep["state"] == og.INVALID
    assert "every_tick: S8-SLTP-1 needs the bound window copy" in \
        " ".join(rep["reasons"])


def test_archive_manifest_must_bind_the_window_copies(tick):
    man_path = tick / "archive_manifest.json"
    man = json.loads(man_path.read_text())
    del man["artifacts"][og.log_window_rel("gold2", "m1_ohlc")]
    man_path.write_text(json.dumps(man))
    rep = og.verify_archive_manifest(tick, {}, ("gold2",))
    assert rep["state"] == og.INVALID
    assert "log_windows/gold2_m1_ohlc.txt" in " ".join(rep["reasons"])
