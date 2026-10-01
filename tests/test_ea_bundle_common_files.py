"""gate_run24: the EA reads the DSL bundle from the common folder too.

MEASURED (gate_run24, HEAD 150303a): a bundle staged into the tester agent's
MQL5\\Files before launch was NOT readable at OnInit ("DSL bundle refused:  ",
both error strings empty). The fix, under the owner's scoped authorization
(docs/DECISIONS.md):

  * Mql5Bot.mq5 ReadDslBundleText falls back to FILE_COMMON and reports both
    GetLastError codes; OnInit prints them, or which location loaded;
  * stage_bundle REQUIRES a sha256-verified copy in Terminal\\Common\\Files;
  * the graders read the new refusal and "loaded from" lines.

The MQL5 side cannot be compiled on the Mac: the checks here are static
source checks. Stage 1 on Windows is the compile proof.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from mql5bot import gate_selfcheck as gs
from mql5bot import gold_leg_inputs as gli
from mql5bot import tester_log_grader as tlg

REPO = Path(__file__).resolve().parents[1]
EA = REPO / "mql5" / "Experts" / "Mql5Bot" / "Mql5Bot.mq5"
DECIDE = REPO / "tools" / "owner_gate_decide.py"
GOLD2_MANIFEST = REPO / "artifacts" / "gold_2" / "manifest.json"
GOLD2_BUNDLE_REL = ("Mql5Bot\\gold_bundles\\"
                    "gold2_multifactor_v1_EURUSD.G2.bundle.json")
CAPTURE = REPO / "tests" / "data" / "owner_gate" / "tester_log_gate_runs_16_17.txt"
TERMINAL_ID = "D0E8209F77C8CF37AD8BF550E51FF075"
SYMBOL = "EURUSD.G2"

# the lines the EA source prints (rendered with gate_run24's path and a
# plausible error code -- UNCONFIRMED in a captured window)
REFUSED_OPEN = ("[mql5bot] DSL bundle refused: cannot open '"
                + GOLD2_BUNDLE_REL + "' (local err=5004, common err=5002)")
LOADED_FROM = "[mql5bot] DSL bundle loaded from common: " + GOLD2_BUNDLE_REL
ENABLED = ("[2024.01.01 00:00:00] [INFO] generic DSL execution enabled: "
           "gold2_multifactor")


def _src() -> str:
    return EA.read_text(encoding="utf-8")


def _function(name: str) -> str:
    """The source of one top-level MQL5 function, signature to closing
    brace (functions in Mql5Bot.mq5 close with a "  }" line)."""
    src = _src()
    start = src.index(f"bool {name}(")
    end = src.index("\n  }\n", start)
    return src[start:end + 4]


def _oninit_dsl_block() -> str:
    src = _src()
    start = src.index('if(InpDslBundleFile != "")')
    end = src.index('g_log.Info("generic DSL execution enabled: "', start)
    return src[start:end + 60]


# ---------------------------------------------------------------------------
# EA source (static: no MQL5 compiler on the Mac)
# ---------------------------------------------------------------------------

def test_read_dsl_bundle_text_falls_back_to_file_common():
    fn = _function("ReadDslBundleText")
    local = fn.index("FileOpen(path,FILE_READ|FILE_BIN)")
    common = fn.index("FileOpen(path,FILE_READ|FILE_BIN|FILE_COMMON)")
    assert local < common, "local MQL5\\Files must be tried first"
    # each attempt starts from a clean error state and keeps its own code
    assert fn.count("ResetLastError();") == 2
    assert fn.index("ResetLastError();") < local
    assert "errLocal=GetLastError();" in fn[local:common]
    assert "errCommon=GetLastError();" in fn[common:]
    assert 'source="local";' in fn and 'source="common";' in fn


def test_read_dsl_bundle_text_still_fails_closed():
    fn = _function("ReadDslBundleText")
    assert "if(sz<=0){ FileClose(h); return false; }" in fn
    assert "if(rd!=sz) return false;" in fn
    assert "return StringLen(out)>0;" in fn
    # still a byte-faithful read, never text mode
    assert "FILE_TXT" not in fn and "FILE_ANSI" not in fn
    # strict-compile hygiene the Mac can check: explicit narrowing casts
    assert "int sz=(int)FileSize(h);" in fn
    assert "int rd=(int)FileReadArray(h,bytes,0,sz);" in fn


def test_oninit_refusal_prints_path_locations_and_both_error_codes():
    block = _oninit_dsl_block()
    assert ('Print("[mql5bot] DSL bundle refused: cannot open \'",'
            'InpDslBundleFile,') in block
    assert '"\' (local err=",bundleErrLocal,", common err=",bundleErrCommon,")");' \
        in block
    for var in ("string bundleSource", "int    bundleErrLocal",
                "int    bundleErrCommon", "bool   bundleRead"):
        assert var in block
    # one refusal exit for read/parse/load (no new INIT_FAILED site); the
    # parse/load refusal text is unchanged
    refuse = block[block.index("if(!bundleRead || !g_dslJson.Parse"):]
    refuse = refuse[:refuse.index("return INIT_FAILED;")]
    assert ('Print("[mql5bot] DSL bundle refused: ",g_dslJson.Error()," ",'
            'g_dslLoader.Error());') in refuse
    assert "cannot open" in refuse and "empty or short read" in refuse


def test_oninit_prints_the_load_source_before_dsl_enabled():
    block = _oninit_dsl_block()
    loaded = block.index('Print("[mql5bot] DSL bundle loaded from ",'
                         'bundleSource,": ",InpDslBundleFile);')
    enabled = block.index('g_log.Info("generic DSL execution enabled: "')
    assert loaded < enabled


def test_the_grader_regexes_match_the_lines_the_ea_source_prints():
    m = gs._DSL_REFUSED_OPEN_RE.search(REFUSED_OPEN)
    assert m and m.groups() == (GOLD2_BUNDLE_REL, "5004", "5002")
    m = tlg._DSL_LOADED_FROM_RE.search(LOADED_FROM)
    assert m and m.groups() == ("common", GOLD2_BUNDLE_REL)
    assert tlg._DSL_LOADED_FROM_RE.search(
        LOADED_FROM.replace("from common", "from local")).group(1) == "local"


# ---------------------------------------------------------------------------
# staging into Terminal\Common\Files
# ---------------------------------------------------------------------------

def _gold2() -> dict:
    return gli.derive_gold_leg_inputs(REPO, GOLD2_MANIFEST, SYMBOL)


def _windows_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """gate_run23/24's layout under %APPDATA%: data folder
    MetaQuotes\\Terminal\\<id>, agent MetaQuotes\\Tester\\<id>\\Agent-*, and
    the common folder MetaQuotes\\Terminal\\Common\\Files."""
    mq = tmp_path / "AppData" / "Roaming" / "MetaQuotes"
    df = mq / "Terminal" / TERMINAL_ID
    (df / "Tester" / "logs").mkdir(parents=True)
    (df / "MQL5" / "Files").mkdir(parents=True)
    agent = mq / "Tester" / TERMINAL_ID / "Agent-127.0.0.1-3000"
    (agent / "logs").mkdir(parents=True)
    return df, agent, mq / "Terminal" / "Common" / "Files"


def _rel() -> Path:
    return Path(*GOLD2_BUNDLE_REL.split("\\"))


def test_common_files_dir_is_the_data_folders_sibling_common(tmp_path):
    df, _, common = _windows_layout(tmp_path)
    assert gli.common_files_dir(df) == common


def test_bundle_is_staged_into_common_files_sha256_verified(tmp_path):
    df, agent, common = _windows_layout(tmp_path)
    d = _gold2()
    st = gli.stage_bundle(gli.bundle_bytes(d["bundle"]), d["bundle_rel"], df)
    assert st["ok"] is True, st
    want = common / _rel()
    assert st["common"] == str(want)
    assert hashlib.sha256(want.read_bytes()).hexdigest() == d["bundle_sha256"]
    # the agent/terminal copies are still written, as before
    assert str(agent / "MQL5" / "Files" / _rel()) in st["staged"]
    assert str(df / "MQL5" / "Files" / _rel()) in st["staged"]
    assert st["optional_bad"] == []


def test_unwritable_common_folder_fails_closed(tmp_path):
    df, agent, common = _windows_layout(tmp_path)
    common.parent.write_text("not a directory", encoding="utf-8")
    d = _gold2()
    st = gli.stage_bundle(gli.bundle_bytes(d["bundle"]), d["bundle_rel"], df)
    assert st["ok"] is False
    assert st["missing"] == "common files folder"
    assert st["common"] is None
    assert st["common_path"] == str(common / _rel())
    assert "cannot write" in st["reasons"][0]
    # the agent copy alone is NOT a staged bundle (gate_run24)
    assert str(agent / "MQL5" / "Files" / _rel()) in st["staged"]


def test_common_copy_sha256_mismatch_fails_closed(tmp_path, monkeypatch):
    df, _, common = _windows_layout(tmp_path)
    d = _gold2()
    raw = gli.bundle_bytes(d["bundle"])
    real_read = Path.read_bytes

    def corrupt_common(self):
        data = real_read(self)
        return data + b" " if self == common / _rel() else data

    monkeypatch.setattr(Path, "read_bytes", corrupt_common)
    st = gli.stage_bundle(raw, d["bundle_rel"], df)
    assert st["ok"] is False
    assert st["missing"] == "common files folder"
    assert "sha256 mismatch" in st["reasons"][0]


def test_failed_agent_copy_is_reported_but_not_required(tmp_path):
    df, agent, common = _windows_layout(tmp_path)
    (agent / "MQL5").write_text("not a directory", encoding="utf-8")
    d = _gold2()
    st = gli.stage_bundle(gli.bundle_bytes(d["bundle"]), d["bundle_rel"], df)
    assert st["ok"] is True
    assert st["common"] == str(common / _rel())
    assert len(st["optional_bad"]) == 1
    assert str(agent / "MQL5") in st["optional_bad"][0]


def test_cli_refuses_the_leg_when_common_cannot_be_written(tmp_path):
    df, _, common = _windows_layout(tmp_path)
    common.parent.write_text("not a directory", encoding="utf-8")
    out_dir = tmp_path / "ev"
    out_dir.mkdir()
    cp = subprocess.run(
        [sys.executable, str(DECIDE), "--repo", str(REPO),
         "stage5-leg-inputs", "--manifest", str(GOLD2_MANIFEST),
         "--symbol", SYMBOL, "--leg", "gold2_m1_ohlc",
         "--out-dir", str(out_dir), "--data-folder", str(df)],
        capture_output=True, text=True, check=False)
    assert cp.returncode == 1, cp.stdout
    out = json.loads(cp.stdout)
    assert out["ok"] is False
    assert out["missing"] == "common files folder"
    assert out["staging"]["common"] is None


# ---------------------------------------------------------------------------
# graders
# ---------------------------------------------------------------------------

def _real_gold2_window() -> str:
    lines = [ln for ln in CAPTURE.read_text(encoding="utf-8").splitlines()
             if ln and not ln.startswith("#") and "EURUSD.G1" not in ln]
    return "\n".join(lines) + "\n"


def test_classifier_names_both_error_codes_of_the_new_refusal():
    window = REFUSED_OPEN + "\ntester stopped because OnInit returns " \
        "non-zero code 1\n"
    v = gs.classify_tester_leg_outcome(report_present=False,
                                       window_text=window, symbol=SYMBOL,
                                       leg="gold2_m1_ohlc")
    assert v["outcome"] == gs.STAGE5_OUTCOME_FAIL and v["ok"] is False
    assert "EA refused the DSL bundle at OnInit" in v["reason"]
    assert f"could not open '{GOLD2_BUNDLE_REL}'" in v["reason"]
    assert "local GetLastError=5004" in v["reason"]
    assert "common GetLastError=5002" in v["reason"]
    assert "both error strings empty" not in v["reason"]
    assert REFUSED_OPEN in v["evidence_lines"]


def test_loaded_from_line_is_parsed_and_quoted_as_evidence():
    window = _real_gold2_window() + LOADED_FROM + "\n" + ENABLED
    r = tlg.grade_leg_from_log(window_text=window, symbol=SYMBOL,
                               requested_model=1,
                               expected_strategy="gold2_multifactor")
    assert r["outcome"] == "PASS_FROM_LOG", r["reason"]
    assert r["parsed"]["bundle_source"] == "common"
    assert LOADED_FROM in r["evidence_lines"]
    assert ENABLED in r["evidence_lines"]


def test_loaded_from_alone_does_not_prove_the_strategy_loaded():
    r = tlg.grade_leg_from_log(window_text=_real_gold2_window() + LOADED_FROM,
                               symbol=SYMBOL, requested_model=1,
                               expected_strategy="gold2_multifactor")
    assert r["ok"] is False
    assert "strategy_loaded" in r["failed_checks"]


def test_two_different_bundle_sources_are_never_loaded():
    window = (_real_gold2_window() + LOADED_FROM + "\n"
              + LOADED_FROM.replace("from common", "from local") + "\n"
              + ENABLED)
    r = tlg.grade_leg_from_log(window_text=window, symbol=SYMBOL,
                               requested_model=1,
                               expected_strategy="gold2_multifactor")
    assert r["ok"] is False
    assert r["parsed"]["bundle_source"] is None
    assert "two different bundle sources" in r["reason"]


def test_refused_open_line_is_not_misread_as_loaded():
    assert not re.search(tlg._DSL_LOADED_FROM_RE, REFUSED_OPEN)
