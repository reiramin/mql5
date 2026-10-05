"""Scoped mql5/ exception (owner authorization, Sal, 2026-10-04): static
source pins for the TWO authorized EA-source edits, plus the measured
reconciliation counts the python side produces once the export carries the
measured spread.

Item 1 — mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5 emits every
owner_gate.SYMBOLSPEC_REQUIRED field FLAT at the top level (S8-SPEC-1),
each from the MQL5 source that decision names, plus the measured spread
(SYMBOL_SPREAD / SYMBOL_SPREAD_FLOAT / custom fixed spread). The nested
"symbol" object is byte-retained for tools/broker_symbol_parity.py.

Item 2 — mql5/Experts/Mql5Bot/Mql5Bot.mq5 records its OWN new position in
the ticket registry immediately after a successful entry (and from the
entry deal in OnTradeTransaction for pending/retry fills), with the SAME
record SyncRecords builds, so the next sync does not warn-adopt it as
restart recovery. The restart-recovery WARN path itself is unchanged.

The MQL5 sources cannot be compiled here (no metaeditor64.exe on this
host); these are source-level pins only — the strict-compile 0/0 proof is
the owner's stage-1 gate.

MT5 data: the log trade lists are byte copies from gate_run29
(tests/data/owner_gate/gate_run29_gold2_*_log_trades.json). gate_run30
(HEAD 887ffa8) measured the same counts on them — 74 PAIRED / 0 MISSING /
0 EXTRA, side 37/37, timestamp 36/37, entry_price 18/37 (all 19 buys +1
point), volume 14/37 — so these lists carry the gate_run30 numbers. The
counts asserted below are MEASURED on this code; the owner's predictions
are quoted in the docstrings and never forced.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from mql5bot import owner_gate as og
from mql5bot import stage8_package as s8p

REPO = Path(__file__).resolve().parents[1]
EXPORT_SRC = (REPO / "mql5/Scripts/Mql5Bot/Mql5BotExportSymbolSpec.mq5"
              ).read_text(encoding="utf-8")
EA_SRC = (REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5"
          ).read_text(encoding="utf-8")
DATA = REPO / "tests" / "data" / "owner_gate"
MANIFEST = json.loads((REPO / "artifacts/gold_2/manifest.json").read_text())
EXPECTED = json.loads(
    (REPO / "artifacts/gold_2/expected_execution.json").read_text())
FIXTURE = REPO / "artifacts/gold_2/gold2_fixture.csv"
START = "2024-01-02T00:00:00"
END = "2024-01-04T00:00:00"
MODELS = ("every_tick", "m1_ohlc")
MEASURED_SPREAD = {"spread_points": 2}

# a FLAT top-level emission in the export script is exactly two-space
# indented (`j += "  " + JsonQuote("<field>")`); nested symbol fields are
# four-space indented and do not match
_FLAT_EMIT_RE = re.compile(r'j \+= "  " \+ JsonQuote\("([a-z_0-9]+)"\)')


# ------------------------------------------------- Item 1: export script

def test_every_required_symbolspec_field_is_emitted_flat():
    flat = set(_FLAT_EMIT_RE.findall(EXPORT_SRC))
    need = set(og.SYMBOLSPEC_REQUIRED) - {"symbol"}
    assert need <= flat, sorted(need - flat)
    # `symbol` stays the nested object (it satisfies the required key and
    # keeps tools/broker_symbol_parity.py reading the same document)
    assert 'JsonQuote("symbol") + ":\\n  {\\n"' in EXPORT_SRC
    # measured spread beside them
    assert {"spread_points", "spread_float", "custom_symbol",
            "custom_fixed_spread_points"} <= flat


def test_flat_fields_come_from_the_s8_spec_1_named_sources():
    assert "AccountInfoString(ACCOUNT_COMPANY)" in EXPORT_SRC   # broker
    assert "TerminalInfoInteger(TERMINAL_BUILD)" in EXPORT_SRC
    assert "TimeGMT()" in EXPORT_SRC and "TimeCurrent()" in EXPORT_SRC
    assert "SYMBOL_SPREAD_FLOAT" in EXPORT_SRC
    assert "SYMBOL_CUSTOM" in EXPORT_SRC
    # ISO timestamp (owner_gate._iso parses ISO, not TimeToString's shape)
    assert "JsonIso8601" in EXPORT_SRC
    # the script stays an exporter: no trading call was added
    for call in ("OrderSend", "PositionOpen", "OpenMarket", "OpenPending",
                 "ClosePosition"):
        assert call not in EXPORT_SRC, call


def test_the_emitted_flat_shape_satisfies_the_unchanged_verifier(tmp_path):
    """Build the document shape the script now writes (flat field names
    parsed from the SOURCE, nested symbol object) and run the UNCHANGED
    verifier on it: no missing fields. Values here are placeholders —
    value parity is runtime, owner-side."""
    doc = {f: "x" for f in _FLAT_EMIT_RE.findall(EXPORT_SRC)}
    doc["symbol"] = {"name": "EURUSD"}
    pkg = tmp_path / "pkg"
    (pkg / "symbolspec").mkdir(parents=True)
    (pkg / "symbolspec/symbolspec.json").write_text(json.dumps(doc),
                                                    encoding="utf-8")
    rep = og.verify_symbolspec(pkg, None)
    assert rep["state"] == og.PRESENT_UNVERIFIED, rep
    assert not any("missing fields" in r for r in rep["reasons"])


# ----------------------------------------------- Item 2: entry recording

def _helpers_segment() -> str:
    """The two new helpers, between SyncRecords and ProtectManagedPositions."""
    start = EA_SRC.index("bool RegisterOwnPosition")
    end = EA_SRC.index("// Enqueue SL verification")
    return EA_SRC[start:end]


def test_register_own_position_builds_the_same_record_as_sync():
    seg = _helpers_segment()
    # the exact record SyncRecords builds, field for field
    for field in ("ticket", "strategyId", "symbol", "type", "entry",
                  "openTime", "lots", "partialDone", "beDone"):
        assert f"rec.{field}" in seg, field
        assert EA_SRC.count(f"rec.{field}") >= 2, field  # sync + register
    assert "g_store.Upsert(rec)" in seg
    assert "g_store.HasTicket(ticket)" in seg
    # it registers OUR positions only, and logs Info, never the WARN
    assert "POSITION_MAGIC) != g_magic" in seg
    assert "registered own entry position" in seg
    assert "g_log.Warn" not in seg


def test_entry_path_registers_immediately_and_transaction_covers_fills():
    # immediate sweep right after a successful entry, before the ENTRY log
    ok_block = EA_SRC[EA_SRC.index("if(ok)"):EA_SRC.index('"ENTRY %s')]
    assert "RegisterOwnEntryPositions();" in ok_block
    # OnTradeTransaction registers the position an entry deal of ours
    # opened (pending/retry fills, where no position existed at ok-time)
    ott = EA_SRC[EA_SRC.index("void OnTradeTransaction"):]
    assert "DEAL_ENTRY_IN" in ott
    assert "DEAL_POSITION_ID" in ott
    assert "RegisterOwnPosition" in ott


def test_restart_recovery_warn_path_is_unchanged():
    sync = EA_SRC[EA_SRC.index("void SyncRecords"):
                  EA_SRC.index("bool RegisterOwnPosition")]
    assert 'g_log.Warn("adopted unknown position #"' in sync
    assert "(restart recovery)" in sync


def test_the_new_helpers_touch_no_trading_path():
    seg = _helpers_segment()
    for call in ("OrderSend", "OpenMarket", "OpenPending", "ClosePosition",
                 "ModifySLTP", "QueueCancel", "Enqueue"):
        assert call not in seg, call


# ------------------- python side: measured counts with the measured spread

@pytest.fixture(scope="module")
def measured_events():
    fill, _ = s8p.fill_spec_of(MANIFEST, MEASURED_SPREAD)
    assert fill["spread_points"] == 2.0
    # price_basis "mid": the S8-SPEC-2 measurement below was taken on the
    # mid-convention window run; the S8-COST-1 "bid" run is measured in
    # tests/test_s8_cost_bid_basis.py
    sd, note = s8p.expected_set_window_run(
        REPO, "gold2", START, END, spread_points=2.0,
        spread_source=fill["spread_source"], price_basis="mid")
    assert sd is not None, note
    py, _ = s8p.python_entries(EXPECTED, MANIFEST["timeframe"])
    mt5 = {}
    for m in MODELS:
        deals = json.loads((DATA / f"gate_run29_gold2_{m}_log_trades.json"
                            ).read_text())["deals"]
        mt5[m], _ = s8p.mt5_entries(deals)
    events, summary = s8p.reconciliation_events(
        py, mt5, "EURUSD.G2",
        window_starts={m: (START, "line") for m in MODELS},
        window_end=END, fixture_opens=s8p.fixture_minute_opens(FIXTURE),
        fill=fill, expected_sets={m: (sd, note) for m in MODELS})
    return events, summary


def _paired(events, model):
    return [e for e in events
            if e.get("pairing") == s8p.PAIRED_BY_TIME
            and e["model"] == model]


def test_measured_spread_names_itself_in_the_fill_model():
    fill, note = s8p.fill_spec_of(MANIFEST, MEASURED_SPREAD)
    assert fill["spread_source"] == \
        "measured_spread(2 points, symbolspec export)"
    assert "measured_spread(2 points, symbolspec export)" in note
    # the gate_run30 first divergence: 08:46 buy, python 1.09726 (manifest
    # spread 1) vs mt5 1.09727 — with the measured spread the expected
    # fill IS 1.09727 and the model names its source
    price, model = s8p.expected_fill(1.09725, "buy", fill)
    assert (price, model) == (
        1.09727, "ask_open=bid+measured_spread(2 points, symbolspec export)")
    # sells stay the bid open
    assert s8p.expected_fill(1.09725, "sell", fill) == (1.09725,
                                                        s8p.FILL_MODEL_SELL)


def test_manifest_fallback_is_stated_and_keeps_the_generic_name():
    fill, note = s8p.fill_spec_of(MANIFEST, {"symbol": "EURUSD"})
    assert fill["spread_points"] == 1.0
    assert "spread_source" not in fill
    assert "fallback" in note and "no numeric flat spread_points" in note
    assert s8p.expected_fill(1.09725, "buy", fill)[1] == s8p.FILL_MODEL_BUY
    # the one-argument call (no export at all) is unchanged
    fill1, note1 = s8p.fill_spec_of(MANIFEST)
    assert fill1["spread_points"] == 1.0 and "spread_source" not in fill1
    assert "fallback" not in note1


def test_entry_price_37_of_37_equal_with_the_measured_spread(
        measured_events):
    """Owner prediction: entry_price 37/37 equal once measured spread = 2
    points. MEASURED here: holds, both legs (every buy python == bid + 2
    points == the MT5 journal price; every sell already equal)."""
    events, summary = measured_events
    for m in MODELS:
        paired = _paired(events, m)
        assert (summary[m]["paired"], summary[m]["missing_in_mt5"],
                summary[m]["extra_in_mt5"]) == (37, 0, 0)
        price_eq = sum(1 for e in paired
                       if e["fields"]["entry_price"]["python"]
                       == e["fields"]["entry_price"]["mt5"])
        side_eq = sum(1 for e in paired
                      if e["fields"]["entry_side"]["python"]
                      == e["fields"]["entry_side"]["mt5"])
        ts_eq = sum(1 for e in paired
                    if e["fields"]["timestamp"]["python"]
                    == e["fields"]["timestamp"]["mt5"])
        assert (price_eq, side_eq, ts_eq) == (37, 37, 36), m
        buys = [e for e in paired if e["python_side_declared"] == "long"]
        assert len(buys) == 19
        for e in buys:
            assert e["fill_model"] == \
                "ask_open=bid+measured_spread(2 points, symbolspec export)"
            assert not og._field_divergent(e["fields"]["entry_price"])


def test_volume_equality_measured_and_the_prediction_quoted(
        measured_events):
    """Owner prediction: 'expect volume equality to rise'. MEASURED here:
    it does NOT hold — 11/37 equal per leg with the measured spread in the
    window-run cost, DOWN from 14/37 at the manifest spread. Cause (code,
    not conjecture): costs.py treats the bar open as MID, so a round trip
    charges spread + 2x slippage = 2 + 2x1 = 4 points against MT5's 2
    (bid bars, fixed spread, no slippage); the equity paths diverge more,
    not less. Recorded as measured; nothing is bent to the prediction.

    PREDICTED gate_run31 counts per leg, from these lists (printed below):
    74 PAIRED / 0 MISSING / 0 EXTRA overall; side 37/37; timestamp 36/37;
    entry_price 37/37; volume 11/37 equal."""
    events, _ = measured_events
    print("\npredicted gate_run31 per-leg counts "
          "(measured on the gate_run29/30 log trade lists):")
    for m in MODELS:
        paired = _paired(events, m)
        vol_eq = sum(1 for e in paired
                     if e["fields"]["volume"]["python"]
                     == e["fields"]["volume"]["mt5"])
        off = [round(abs(e["fields"]["volume"]["python"]
                         - e["fields"]["volume"]["mt5"]) / 0.01)
               for e in paired]
        print(f"  {m}: paired 37/37, side 37/37, timestamp 36/37, "
              f"entry_price 37/37, volume {vol_eq}/37 equal "
              f"(max off {max(off)} steps)")
        assert vol_eq == 11, (m, vol_eq)
    # the window run itself states the measured cost it sized on
    note = next(e for e in events
                if e.get("pairing") == s8p.PAIRED_BY_TIME
                )["python_volume_basis"]
    assert "window-run entry cost spread_points 2" in note
    assert "measured_spread(2 points, symbolspec export)" in note
