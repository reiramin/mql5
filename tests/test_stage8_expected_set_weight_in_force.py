"""S8-WEIGHT-1 (owner decision, 2026-10-04): the tester leg's EXPECTED
ENTRY SET is the weight-in-force run (InpBaseGateWeight=1.0, no allocation
file), not the scheduled-weight frozen trace.

gate_run29 (HEAD 5392cc4, -Golds gold2) measured 1 MISSING_IN_MT5: python
short 0.02 at 2024-01-02T08:08 (signal 08:07), a persistence re-entry that
exists only because the generator's day-2 weight 0.5 dropped the 08:01
approval for seven bars (docs/analysis/gate_run29_missing_0808.md). The EA
leg runs at weight 1.0 and held its 08:01 short; the python engine at
weight 1.0 does not enter at 08:08 either.

The MT5 side here is REAL gate_run29 data: byte copies of BOTH legs' log
trade lists (owner_mt5_package/log_trades/gold2_{m1_ohlc,every_tick}.json).

MEASURED expectations (pinned below; the owner's predicted numbers that
did NOT hold are stated in the PR, never asserted):

  * 74 PAIRED (37 per leg), 0 MISSING_IN_MT5, 0 EXTRA_IN_MT5;
  * entry_side 37/37 equal per leg;
  * timestamp 36/37 equal per leg (MT5's 2024-01-03 entry deal is at
    08:32:01, one second after the 08:32:00 bar -- already so in the
    gate_run29 reconciliation itself, whatever the brief said);
  * entry_price 18/37 equal per leg (every sell; all 19 buys stay +1
    point: MT5 filled at bid + 2 points, the manifest spread is 1 --
    the S8-FILL-1 residual, unchanged by the expected-set switch);
  * volume 14/37 exactly equal, 20/37 within one volume_step (0.01).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from mql5bot import owner_gate as og
from mql5bot import stage8_package as s8p

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "tests" / "data" / "owner_gate"
MANIFEST = json.loads((REPO / "artifacts/gold_2/manifest.json").read_text())
EXPECTED = json.loads(
    (REPO / "artifacts/gold_2/expected_execution.json").read_text())
FIXTURE = REPO / "artifacts/gold_2/gold2_fixture.csv"
START = "2024-01-02T00:00:00"
LINES = {
    "m1_ohlc": ("LH\t3\t01:56:38.082\tCore 1\tEURUSD.G2: start time "
                "changed to 2024.01.02 00:00 to provide data at beginning"),
    "every_tick": ("MS\t3\t01:57:14.149\tCore 1\tEURUSD.G2: start time "
                   "changed to 2024.01.02 00:00 to provide data at "
                   "beginning"),
}
END = "2024-01-04T00:00:00"
MODELS = ("every_tick", "m1_ohlc")


@pytest.fixture(scope="module")
def run29_both():
    sd, note = s8p.expected_set_window_run(REPO, "gold2", START, END)
    assert sd is not None, note
    py, _ = s8p.python_entries(EXPECTED, MANIFEST["timeframe"])
    mt5_by_model = {}
    for model in MODELS:
        doc = json.loads(
            (DATA / f"gate_run29_gold2_{model}_log_trades.json").read_text())
        entries, why = s8p.mt5_entries(doc["deals"])
        assert entries is not None, why
        mt5_by_model[model] = entries
    events, summary = s8p.reconciliation_events(
        py, mt5_by_model, "EURUSD.G2",
        window_starts={m: (START, LINES[m]) for m in MODELS},
        window_end=END,
        fixture_opens=s8p.fixture_minute_opens(FIXTURE),
        fill=s8p.fill_spec_of(MANIFEST)[0],
        expected_sets={m: (sd, note) for m in MODELS})
    return events, summary


def _paired(events, model):
    return [e for e in events if e.get("model") == model
            and e.get("pairing") == s8p.PAIRED_BY_TIME]


def test_74_paired_0_missing_0_extra(run29_both):
    events, summary = run29_both
    for model in MODELS:
        s = summary[model]
        assert (s["paired"], s["missing_in_mt5"], s["extra_in_mt5"]) == \
            (37, 0, 0)
        assert s["frozen_only_scheduled_weight"] == 21
        assert s["out_of_tested_window"] == 30
        assert s["expected_set"] == s8p.EXPECTED_SET_WINDOW_RUN
    assert len([e for e in events
                if e.get("pairing") == s8p.PAIRED_BY_TIME]) == 74
    assert not any(e.get("pairing") == s8p.MISSING_IN_MT5 for e in events)
    assert not any(e.get("pairing") == s8p.EXTRA_IN_MT5 for e in events)


def test_measured_field_equality_counts(run29_both):
    events, _ = run29_both
    step = MANIFEST["broker_spec"]["volume_step"]
    for model in MODELS:
        paired = _paired(events, model)
        ts = sum(1 for e in paired
                 if e["fields"]["timestamp"]["python"]
                 == e["fields"]["timestamp"]["mt5"])
        side = sum(1 for e in paired
                   if e["fields"]["entry_side"]["python"]
                   == e["fields"]["entry_side"]["mt5"])
        price = sum(1 for e in paired
                    if e["fields"]["entry_price"].get("python")
                    == e["fields"]["entry_price"]["mt5"])
        vol_eq = sum(1 for e in paired
                     if e["fields"]["volume"]["python"]
                     == e["fields"]["volume"]["mt5"])
        vol_step = sum(1 for e in paired
                       if abs(round(e["fields"]["volume"]["mt5"]
                                    - e["fields"]["volume"]["python"], 6))
                       <= step + 1e-9)
        print(f"\ngate_run29 {model}: timestamp {ts}/37, side {side}/37, "
              f"entry_price {price}/37, volume equal {vol_eq}/37, "
              f"volume within one step {vol_step}/37")
        # MEASURED, never predicted: these are the gate_run29 numbers
        assert (ts, side, price, vol_eq, vol_step) == (36, 37, 18, 14, 20)
        # the one timestamp gap is MT5's 08:32:01 entry deal, one second
        # after the bar -- present in gate_run29's own reconciliation too
        (off,) = [e for e in paired
                  if e["fields"]["timestamp"]["python"]
                  != e["fields"]["timestamp"]["mt5"]]
        assert off["fields"]["timestamp"] == {
            "python": "2024-01-03T08:32:00", "mt5": "2024-01-03T08:32:01"}
        # paired residuals stay divergences under the zero-tolerance rule
        assert og._field_divergent(off["fields"]["timestamp"])


def test_every_event_records_the_expected_set_and_cross_reference(
        run29_both):
    events, _ = run29_both
    for e in events:
        if "pairing" not in e:
            continue  # the final count event
        assert e["expected_set"] == s8p.EXPECTED_SET_WINDOW_RUN
    e0 = _paired(events, "m1_ohlc")[0]
    # 08:01 fill <- frozen expected_execution entries[19] (08:00 signal)
    assert e0["frozen_row_index"] == 19
    assert e0["python_volume_frozen_basis"] == 0.01
    e46 = next(e for e in _paired(events, "m1_ohlc")
               if e["time"] == "2024-01-02T08:46:00")
    assert e46["frozen_row_index"] == 21
    assert (e46["python_volume_frozen_basis"],
            e46["python_volume_window_basis"]) == (0.25, 0.28)
    # the engine run's own fill is recorded, labelled, never compared
    assert e46["python_window_run_fill"] == pytest.approx(1.09726, abs=5e-6)
    assert "window_run_fill" not in e46["fields"]


def test_frozen_only_rows_are_informational_never_divergences(run29_both):
    events, _ = run29_both
    fo = [e for e in events
          if e.get("pairing") == s8p.FROZEN_ONLY_SCHEDULED_WEIGHT
          and e["model"] == "m1_ohlc"]
    assert len(fo) == 21
    assert Counter(e["reason"] for e in fo) == {
        "before_window_start": 19, "scheduled_weight_only": 1,
        "at_or_after_window_end": 1}
    sw = next(e for e in fo if e["reason"] == "scheduled_weight_only")
    # THE gate_run29 MISSING_IN_MT5: now recorded for what it is -- the
    # scheduled-weight persistence re-entry the weight-1.0 run never makes
    assert sw["python_signal_time"] == "2024-01-02T08:07:00"
    assert sw["python_fill_time"] == "2024-01-02T08:08:00"
    assert sw["entry_kind"] == "persistence_reentry"
    assert sw["frozen_row_index"] == 20
    assert sw["python_volume_frozen_basis"] == 0.02
    for e in fo:
        assert e["fields"] == {}
        assert "trade_index" not in e
    # never a divergence: nothing in these events is comparable
    assert og.first_divergence(fo) is None


def test_out_of_window_rows_come_from_the_expected_set(run29_both):
    events, _ = run29_both
    out = [e for e in events
           if e.get("pairing") == s8p.OUT_OF_TESTED_WINDOW
           and e["model"] == "m1_ohlc"]
    # the weight-1.0 run trades 2024-01-04 (the frozen schedule's day
    # weight was 0.0 there); all 30 fills are at/after the exclusive
    # ToDate end -- recorded uncompared
    assert len(out) == 30
    for e in out:
        assert e["python_fill_time"] >= END
        assert e["expected_set"] == s8p.EXPECTED_SET_WINDOW_RUN
        assert e["fields"] == {}


def test_frozen_cross_reference_covers_every_in_window_entry(run29_both):
    events, _ = run29_both
    paired = _paired(events, "m1_ohlc")
    # every in-window weight-1.0 entry has a frozen counterpart at the
    # same fill minute (the sets differ only at 08:08 and on 2024-01-04)
    assert all(e["frozen_row_index"] is not None for e in paired)
    assert len({e["frozen_row_index"] for e in paired}) == 37
