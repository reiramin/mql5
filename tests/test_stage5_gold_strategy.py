"""Stage 5 R9: each tester leg runs the strategy its gold manifest pins.

gate_run17 measured the EA starting with ``InpStrategy=0`` and an EMPTY
``InpDslBundleFile`` — its compiled-in default — so stage 8 compared two
different strategies. These tests pin the fix, all Mac-side (no MT5):

  * inputs are derived from the committed manifests (read-only); a field
    that cannot be derived fails the leg BEFORE launch, naming the field;
  * the rendered tester .ini for gold2 carries the gold2 strategy selector;
  * the bundle is the committed gold spec with only the market symbol
    retargeted to the custom symbol, proven and recorded;
  * the log trade list lands in the evidence package where stage 8 reads it;
  * a window showing the EA ran another strategy never grades PASS_FROM_LOG.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import gold_leg_inputs as gli
from mql5bot import mt5tester as mt
from mql5bot import owner_gate as og
from mql5bot import tester_log_grader as tlg
from mql5bot.dsl.bundle import load_bundle

REPO = Path(__file__).resolve().parents[1]
DECIDE = REPO / "tools" / "owner_gate_decide.py"
RUN_BACKTEST = REPO / "tools" / "run_mt5_backtest.py"
GOLD1_MANIFEST = REPO / "artifacts" / "gold" / "manifest.json"
GOLD2_MANIFEST = REPO / "artifacts" / "gold_2" / "manifest.json"
CAPTURE = REPO / "tests" / "data" / "owner_gate" / "tester_log_gate_runs_16_17.txt"
GOLD2_BUNDLE_REL = "Mql5Bot\\gold_bundles\\gold2_multifactor_v1_EURUSD.G2.bundle.json"


def _gold2() -> dict:
    return gli.derive_gold_leg_inputs(REPO, GOLD2_MANIFEST, "EURUSD.G2")


def _manifest_copy(tmp_path: Path, mutate) -> Path:
    doc = json.loads(GOLD2_MANIFEST.read_text(encoding="utf-8"))
    mutate(doc)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _decide(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(DECIDE), "--repo", str(REPO),
                           *args], capture_output=True, text=True,
                          check=False)


# ---------------------------------------------------------------------------
# derivation from the manifest
# ---------------------------------------------------------------------------

def test_gold2_inputs_come_from_its_manifest():
    d = _gold2()
    assert d["ok"], d["reasons"]
    man = json.loads(GOLD2_MANIFEST.read_text(encoding="utf-8"))
    assert d["strategy_id"] == man["strategy_id"] == "gold2_multifactor"
    assert d["manifest_spec_hash"] == man["spec_hash"]
    assert d["spec_file"] == "examples/strategies/gold2_multifactor.json"
    assert d["inputs"]["InpDslBundleFile"] == GOLD2_BUNDLE_REL
    assert d["inputs"]["InpSizingMode"] == 1          # SIZING_RISK_PERCENT_EQ
    assert d["inputs"]["InpRiskPercent"] == man["risk_config"]["risk_percent"]
    assert d["inputs"]["InpAllowShort"] is man["engine_config"]["allow_short"]
    assert d["deposit"] == man["risk_config"]["equity_start"]
    # every derived input names where it came from
    assert set(d["inputs"]) <= set(d["sources"])
    assert d["sources"]["InpRiskPercent"] == "manifest risk_config.risk_percent"


def test_gold2_bundle_is_the_committed_spec_retargeted_to_the_chart():
    d = _gold2()
    bundle = load_bundle(d["bundle"])            # the Python loader accepts it
    assert bundle.strategy_id == "gold2_multifactor"
    assert bundle.strategy_version == 1
    assert bundle.market == {"symbol": "EURUSD.G2", "timeframe": "M1"}
    assert d["retarget"]["from_symbol"] == "EURUSD"
    assert d["retarget"]["to_symbol"] == "EURUSD.G2"
    # the market is part of the hash, so the bundle's spec_hash differs
    # from the manifest's; both are recorded
    assert d["retarget"]["bundle_spec_hash"] != d["manifest_spec_hash"]
    assert bundle.spec_hash == d["retarget"]["bundle_spec_hash"]
    raw = gli.bundle_bytes(d["bundle"])
    assert hashlib.sha256(raw).hexdigest() == d["bundle_sha256"]


def test_real_gold1_manifest_fails_before_launch_naming_allow_short():
    # gold1's manifest pins no engine_config: its allow-short rule cannot
    # be derived, and no EA default is substituted
    d = gli.derive_gold_leg_inputs(REPO, GOLD1_MANIFEST, "EURUSD.G1")
    assert d["ok"] is False
    assert d["missing"] == "engine_config.allow_short"


@pytest.mark.parametrize("field,mutate", [
    ("strategy_id", lambda m: m.pop("strategy_id")),
    ("spec_hash", lambda m: m.pop("spec_hash")),
    ("risk_config.risk_percent", lambda m: m["risk_config"].pop("risk_percent")),
    ("risk_config.equity_start", lambda m: m["risk_config"].pop("equity_start")),
    ("risk_config.mode", lambda m: m["risk_config"].update(mode="kelly")),
    ("engine_config.allow_short",
     lambda m: m["engine_config"].update(allow_short="yes")),
    ("spec_hash", lambda m: m.update(spec_hash="0" * 64)),
    ("spec_hash", lambda m: m.update(strategy_version=2)),
])
def test_underivable_input_fails_naming_the_field(tmp_path, field, mutate):
    d = gli.derive_gold_leg_inputs(REPO, _manifest_copy(tmp_path, mutate),
                                   "EURUSD.G2")
    assert d["ok"] is False
    assert d["missing"] == field
    assert "inputs" not in d


def test_selector_check_refuses_an_empty_or_foreign_selector():
    d = _gold2()
    assert gli.selector_check(d["inputs"], d["bundle"],
                              "gold2_multifactor")["ok"]
    empty = {**d["inputs"], "InpDslBundleFile": ""}
    assert not gli.selector_check(empty, d["bundle"], "gold2_multifactor")["ok"]
    assert not gli.selector_check(d["inputs"], d["bundle"],
                                  "ema_crossover_ref")["ok"]


def test_ea_input_defaults_mirror_every_ea_input():
    # the gate can only send inputs the mirror knows (validate_inputs)
    src = (REPO / "mql5" / "Experts" / "Mql5Bot" / "Mql5Bot.mq5").read_text(
        encoding="utf-8", errors="replace")
    names = set(re.findall(r"^input\s+\S+\s+(Inp\w+)", src, re.MULTILINE))
    assert {"InpDslBundleFile", "InpDslBars"} <= names
    assert names == set(mt.EA_INPUT_DEFAULTS)
    assert mt.EA_INPUT_DEFAULTS["InpDslBundleFile"] == ""


# ---------------------------------------------------------------------------
# the CLI the .ps1 shells to, and the rendered .ini
# ---------------------------------------------------------------------------

def test_cli_leg_inputs_fail_before_launch_naming_the_field(tmp_path):
    cp = _decide("stage5-leg-inputs", "--manifest", str(GOLD1_MANIFEST),
                 "--symbol", "EURUSD.G1", "--leg", "gold1_m1_ohlc",
                 "--out-dir", str(tmp_path))
    assert cp.returncode == 1
    out = json.loads(cp.stdout)
    assert out["missing"] == "engine_config.allow_short"
    assert "input_args" not in out


def test_rendered_gold2_ini_carries_the_gold2_strategy_selector(tmp_path):
    cp = _decide("stage5-leg-inputs", "--manifest", str(GOLD2_MANIFEST),
                 "--symbol", "EURUSD.G2", "--leg", "gold2_m1_ohlc",
                 "--out-dir", str(tmp_path))
    assert cp.returncode == 0, cp.stdout
    li = json.loads(cp.stdout)
    args = []
    for kv in li["input_args"]:
        args += ["--input", kv]
    ini = tmp_path / "tester_gold2_m1_ohlc.ini"
    gen = subprocess.run(
        [sys.executable, str(RUN_BACKTEST), "generate-ini", "--symbol",
         "EURUSD.G2", "--timeframe", "M1", "--model", "1", "--from",
         "2024.01.01", "--to", "2024.01.03", "--report", "gold2_m1_ohlc",
         "--defaults", "--output", str(ini), *args,
         "--deposit", str(li["deposit"])],
        capture_output=True, text=True, check=False)
    assert gen.returncode == 0, gen.stderr
    text = ini.read_text(encoding="utf-8")
    inputs = text.split("[TesterInputs]", 1)[1]
    assert f"InpDslBundleFile={GOLD2_BUNDLE_REL}" in inputs
    assert "gold2_multifactor" in inputs
    assert re.search(r"^InpAllowShort=(true|1)", inputs, re.MULTILINE | re.IGNORECASE)
    assert re.search(r"^InpRiskPercent=1(\.0+)?\b", inputs, re.MULTILINE)
    assert re.search(r"^Deposit=10000", text, re.MULTILINE)
    # the evidence copy of the bundle is exactly what gets staged
    ev = Path(li["bundle_evidence"])
    assert hashlib.sha256(ev.read_bytes()).hexdigest() == li["bundle_sha256"]


def test_bundle_is_staged_into_terminal_and_every_agent_sandbox(tmp_path):
    df = tmp_path / "data"
    for agent in ("Agent-127.0.0.1-3000", "Agent-127.0.0.1-3001"):
        (df / "Tester" / "HASH" / agent / "logs").mkdir(parents=True)
    d = _gold2()
    st = gli.stage_bundle(gli.bundle_bytes(d["bundle"]), d["bundle_rel"], df)
    assert st["ok"] is True
    assert len(st["staged"]) == 4  # common + terminal + the two agents
    tail = Path(*GOLD2_BUNDLE_REL.split("\\"))
    for path in st["staged"]:
        assert Path(path).as_posix().endswith(tail.as_posix())
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == \
            d["bundle_sha256"]
    assert any("Agent-127.0.0.1-3001" in p for p in st["staged"])


TERMINAL_ID = "D0E8209F77C8CF37AD8BF550E51FF075"


def _windows_layout(tmp_path: Path) -> tuple[Path, Path]:
    """gate_run23's measured layout: data folder
    ``MetaQuotes\\Terminal\\<id>`` (its Tester dir holds logs only) and the
    agent at the sibling ``MetaQuotes\\Tester\\<id>\\Agent-127.0.0.1-3000``."""
    mq = tmp_path / "AppData" / "Roaming" / "MetaQuotes"
    df = mq / "Terminal" / TERMINAL_ID
    (df / "Tester" / "logs").mkdir(parents=True)
    (df / "MQL5" / "Files").mkdir(parents=True)
    agent = mq / "Tester" / TERMINAL_ID / "Agent-127.0.0.1-3000"
    (agent / "logs").mkdir(parents=True)
    return df, agent


def test_bundle_is_staged_into_the_sibling_tester_agent_sandbox(tmp_path):
    df, agent = _windows_layout(tmp_path)
    d = _gold2()
    st = gli.stage_bundle(gli.bundle_bytes(d["bundle"]), d["bundle_rel"], df)
    assert st["ok"] is True, st
    assert st["agent_sandboxes"] == [str(agent)]
    want = agent / "MQL5" / "Files" / Path(*GOLD2_BUNDLE_REL.split("\\"))
    assert str(want) in st["staged"]
    assert hashlib.sha256(want.read_bytes()).hexdigest() == d["bundle_sha256"]
    # common (required) + terminal MQL5\Files + the one agent
    assert len(st["staged"]) == 3


def test_old_and_sibling_agent_locations_are_both_staged(tmp_path):
    df, agent = _windows_layout(tmp_path)
    old_agent = df / "Tester" / "HASH" / "Agent-127.0.0.1-3001"
    (old_agent / "logs").mkdir(parents=True)
    d = _gold2()
    st = gli.stage_bundle(gli.bundle_bytes(d["bundle"]), d["bundle_rel"], df)
    assert st["ok"] is True
    assert set(st["agent_sandboxes"]) == {str(agent), str(old_agent)}
    assert len(st["staged"]) == 4


def test_zero_agent_sandboxes_no_longer_refuses_when_common_is_staged(
        tmp_path):
    # gate_run24: agent copies are no longer required -- the EA falls back
    # to FILE_COMMON, so the verified common copy alone decides ok
    mq = tmp_path / "MetaQuotes"
    df = mq / "Terminal" / TERMINAL_ID
    (df / "Tester" / "logs").mkdir(parents=True)  # logs only, as gate_run23
    d = _gold2()
    st = gli.stage_bundle(gli.bundle_bytes(d["bundle"]), d["bundle_rel"], df)
    assert st["ok"] is True, st
    assert st["agent_sandboxes"] == []
    common = (mq / "Terminal" / "Common" / "Files"
              / Path(*GOLD2_BUNDLE_REL.split("\\")))
    assert st["common"] == str(common)
    assert hashlib.sha256(common.read_bytes()).hexdigest() == \
        d["bundle_sha256"]
    # every agent location is still searched and reported
    assert str(df / "Tester") in st["searched"]
    assert str(mq / "Tester" / TERMINAL_ID) in st["searched"]


def test_cli_zero_agent_sandboxes_still_launches_with_common_copy(tmp_path):
    df = tmp_path / "MetaQuotes" / "Terminal" / TERMINAL_ID
    (df / "Tester" / "logs").mkdir(parents=True)
    out_dir = tmp_path / "ev"
    out_dir.mkdir()
    cp = _decide("stage5-leg-inputs", "--manifest", str(GOLD2_MANIFEST),
                 "--symbol", "EURUSD.G2", "--leg", "gold2_m1_ohlc",
                 "--out-dir", str(out_dir), "--data-folder", str(df))
    assert cp.returncode == 0, cp.stdout
    out = json.loads(cp.stdout)
    assert out["ok"] is True
    assert out["staging"]["agent_sandboxes"] == []
    assert out["staging"]["common"].endswith(
        Path(*GOLD2_BUNDLE_REL.split("\\")).name)


# ---------------------------------------------------------------------------
# post-run: the EA must have loaded THAT strategy
# ---------------------------------------------------------------------------

def _real_gold2_window() -> str:
    lines = [ln for ln in CAPTURE.read_text(encoding="utf-8").splitlines()
             if ln and not ln.startswith("#") and "EURUSD.G1" not in ln]
    return "\n".join(lines) + "\n"


# EA SOURCE format (Mql5Bot.mq5 OnInit via Logger.Write) — UNCONFIRMED in a
# captured window: runs 16/17 loaded no bundle.
_EA_LOADED = ("[2024.01.01 00:00:00] [INFO] generic DSL execution enabled: "
              "gold2_multifactor")


def test_ea_loaded_line_format_matches_the_ea_source():
    src = (REPO / "mql5" / "Experts" / "Mql5Bot" / "Mql5Bot.mq5").read_text(
        encoding="utf-8", errors="replace")
    assert 'g_log.Info("generic DSL execution enabled: "+g_strategyId)' in src


def test_real_runs_16_17_window_cannot_pass_once_the_strategy_is_expected():
    # the measured root cause, end to end: that run loaded no gold2 bundle
    r = tlg.grade_leg_from_log(window_text=_real_gold2_window(),
                               symbol="EURUSD.G2", requested_model=1,
                               expected_strategy="gold2_multifactor")
    assert r["ok"] is False
    assert r["failed_checks"] == ["strategy_loaded"]
    assert "expected DSL strategy 'gold2_multifactor'" in r["reason"]


def test_window_showing_the_gold2_strategy_loaded_passes():
    r = tlg.grade_leg_from_log(window_text=_real_gold2_window() + _EA_LOADED,
                               symbol="EURUSD.G2", requested_model=1,
                               expected_strategy="gold2_multifactor")
    assert r["outcome"] == "PASS_FROM_LOG"
    assert _EA_LOADED in r["evidence_lines"]


def test_window_showing_another_strategy_loaded_fails():
    other = _EA_LOADED.replace("gold2_multifactor", "ema_crossover_ref")
    r = tlg.grade_leg_from_log(window_text=_real_gold2_window() + other,
                               symbol="EURUSD.G2", requested_model=1,
                               expected_strategy="gold2_multifactor")
    assert r["ok"] is False
    assert r["parsed"]["loaded_strategy"] == "ema_crossover_ref"


# ---------------------------------------------------------------------------
# the log trade list lands in the evidence package
# ---------------------------------------------------------------------------

def _trade_list(tmp_path: Path) -> Path:
    window = _real_gold2_window() + _EA_LOADED
    grade = tlg.grade_leg_from_log(window_text=window, symbol="EURUSD.G2",
                                   requested_model=1, leg="gold2_m1_ohlc",
                                   expected_strategy="gold2_multifactor")
    doc = tlg.log_trade_list(grade, window.encode("utf-8"))
    path = tmp_path / "tester_gold2_m1_ohlc_log_trades.json"
    path.write_text(json.dumps(doc, indent=2, sort_keys=True),
                    encoding="utf-8")
    return path


def test_log_trade_list_lands_where_stage_8_reads_it(tmp_path):
    src = _trade_list(tmp_path)
    pkg = tmp_path / "package"
    cp = _decide("place-log-trades", "--trades", str(src), "--package",
                 str(pkg), "--gold", "gold2", "--model", "m1_ohlc")
    assert cp.returncode == 0, cp.stdout
    dest = pkg / og.log_trades_rel("gold2", "m1_ohlc")
    assert dest.read_bytes() == src.read_bytes()
    out = json.loads(cp.stdout)
    assert out["dest"] == str(dest.resolve())
    assert out["trade_source"] == "tester agent log"
    # stage 8 sees it as the leg's trade source (no raw report present)
    assert og.log_sourced_legs(pkg) == {("gold2", "m1_ohlc")}


def test_package_inside_the_repo_is_refused_outside_evidence(tmp_path):
    src = _trade_list(tmp_path)
    fake_repo = tmp_path / "repo"
    bad = fake_repo / "artifacts" / "owner_mt5_gate" / "evidence"
    r = tlg.place_log_trades(src, bad, "gold2", "m1_ohlc", fake_repo)
    assert r["ok"] is False and "MQL5BOT_EVIDENCE_DIR" in r["reasons"][0]
    assert not bad.exists()
    good = fake_repo / "evidence" / "owner_mt5_package"
    assert tlg.place_log_trades(src, good, "gold2", "m1_ohlc",
                                fake_repo)["ok"] is True


def test_a_list_that_is_not_pass_from_log_is_not_placed(tmp_path):
    src = _trade_list(tmp_path)
    doc = json.loads(src.read_text(encoding="utf-8"))
    doc["evidence_class"] = "BLOCKED_OWNER_ENVIRONMENT"
    src.write_text(json.dumps(doc), encoding="utf-8")
    r = tlg.place_log_trades(src, tmp_path / "pkg", "gold2", "m1_ohlc",
                             tmp_path / "repo")
    assert r["ok"] is False
    assert not (tmp_path / "pkg").exists()


# ---------------------------------------------------------------------------
# the .ps1 wiring
# ---------------------------------------------------------------------------

def _stage(src: str, start: str, end: str) -> str:
    s = src.index(start)
    return src[s:src.index(end, s)]


PS1 = (REPO / "tools" / "owner_gate.ps1").read_text(encoding="utf-8")
S5 = _stage(PS1, 'Enter-Stage 5 "tester_legs"', "STAGE 8")
S8 = _stage(PS1, 'Enter-Stage 8 "reconciliation"', "STAGE 9")


def test_ps1_derives_leg_inputs_before_anything_is_launched():
    derive = S5.index('Invoke-Decide @("stage5-leg-inputs"')
    assert derive < S5.index("$gp = Start-Process")     # generate-ini
    assert derive < S5.index("$p = Start-Process")      # the tester leg
    block = S5[derive:S5.index("$legInputArgs = @()")]
    assert "leg NOT launched" in block and "continue" in block
    assert "[input_underivable]" in block
    # the derived inputs + deposit reach BOTH the evidence .ini and the run
    assert '"--output", $iniEvidence) + $legInputArgs' in S5
    assert '"--out-dir", $testerOut) + $legInputArgs' in S5
    assert '"--data-folder", $DataFolder' in block


def test_ps1_captures_the_window_for_every_leg():
    save = S5.index("$windowArt = Save-TesterWindowLog")
    assert save < S5.index("if ($p.ExitCode -ne 0)")
    assert S5.count("Save-TesterWindowLog") == 1
    assert S5.count('"--expected-strategy", $legStrategy') == 2


def test_ps1_places_log_trade_lists_before_stage_8_verifies():
    place = S8.index('Invoke-Decide @("place-log-trades"')
    assert place < S8.index("verify_owner_mt5_gate.py")
    assert '"evidence\\owner_mt5_package"' in S8
    assert 'Join-Path $RepoRoot "artifacts\\owner_mt5_gate\\evidence"' \
        not in PS1
    assert S8.count("@($s8Art)") >= 4


def test_gold_manifests_are_untouched_by_derivation(tmp_path):
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (GOLD1_MANIFEST, GOLD2_MANIFEST)}
    gli.derive_gold_leg_inputs(REPO, GOLD1_MANIFEST, "EURUSD.G1")
    gli.derive_gold_leg_inputs(REPO, GOLD2_MANIFEST, "EURUSD.G2")
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
    assert before == after
