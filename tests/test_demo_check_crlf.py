"""DEMO-CHECK-CRLF-1 (gate_run52, c8bc022, -Golds gold2 -DemoSafety).

Stage 7 FAILED on the connection check of a terminal that WAS connected
("authorized on MetaQuotes-Demo ... terminal synchronized ... demo account -
hedging mode"). The exporter logged

    [mql5bot] export FAILED: cannot open Mql5Bot\\demo_connect_check\\ EURUSD.json err=5004

The "space" is a carriage return. check_preset_text() already ends its
lines with "\\r\\n"; Path.write_text in Windows text mode turns each "\\n"
into "\\r\\n", so the .set held "...demo_connect_check\\\\\\r\\r\\n". MT5 splits
the line on "\\n" and kept "\\r" in InpExportDir; the exporter's
InpExportDir + sym then named "...\\\\<CR>EURUSD.json".

These tests write the harness's MT5 config files under the Windows text-
mode emulation (tests/windows_newlines.py) and parse them the way MT5 did.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import windows_newlines
from mql5bot import demo_harness as dh

ACC = {"login": "1", "password": "p", "server": "MetaQuotes-Demo"}
SRC = (Path(__file__).resolve().parents[1]
       / "python/mql5bot/demo_harness.py").read_text(encoding="utf-8")


@pytest.fixture
def windows_text_mode(monkeypatch):
    for target, name, value in windows_newlines.patches():
        monkeypatch.setattr(target, name, value)


def _mt5_values(raw: bytes, encoding: str) -> dict[str, str]:
    """key -> value as MT5 read gate_run52's preset: split on "\\n" only,
    the value is everything after the first "=" (no trimming)."""
    text = raw.decode(encoding).lstrip("﻿")
    out = {}
    for line in text.split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def test_the_old_write_reproduces_the_gate_run52_value(tmp_path,
                                                      windows_text_mode):
    p = tmp_path / "old.set"
    p.write_text(dh.check_preset_text(), encoding="utf-16")
    raw = p.read_bytes().decode("utf-16")
    assert "\r\r\n" in raw                                   # CR CR LF
    v = _mt5_values(p.read_bytes(), "utf-16")["InpExportDir"]
    # a CR survives even after MT5 drops the line's own CR
    assert v[:-1].endswith("\r") and v.rstrip("\r") == \
        "Mql5Bot\\demo_connect_check\\"


@pytest.mark.parametrize("make,encoding,key,want", [
    (dh.check_preset_text, "utf-16", "InpExportDir",
     "Mql5Bot\\demo_connect_check\\"),
    (dh.check_preset_text, "utf-16", "InpDenomProbeTicks", "100"),
    (lambda: dh.export_ini(None), "ascii", "Script", dh.EXPORT_SCRIPT),
    (lambda: dh.export_ini(None), "ascii", "ScriptParameters",
     dh.CHECK_PRESET),
    (lambda: dh.export_ini(ACC), "utf-16", "Symbol", dh.SYMBOL),
    (lambda: dh.export_ini(ACC), "utf-16", "Server", "MetaQuotes-Demo"),
    (lambda: dh.startup_ini(ACC, "p.set"), "utf-16", "ExpertParameters",
     "p.set"),
])
def test_written_values_carry_no_whitespace(tmp_path, windows_text_mode,
                                            make, encoding, key, want):
    p = tmp_path / "f"
    dh.write_crlf_text(p, make(), encoding)
    raw = p.read_bytes().decode(encoding)
    assert "\r\r" not in raw
    assert raw.count("\r\n") == raw.count("\n")              # CRLF exactly
    # split on "\n", each value ends with exactly its line's own CR
    v = _mt5_values(p.read_bytes(), encoding)[key]
    assert v == want + "\r", repr(v)
    assert want == want.strip()


def test_the_export_path_has_no_whitespace_around_the_file_name(
        tmp_path, windows_text_mode):
    p = tmp_path / dh.CHECK_PRESET
    dh.write_crlf_text(p, dh.check_preset_text(), "utf-16")
    text = p.read_bytes().decode("utf-16").lstrip("﻿")
    d = next(ln for ln in text.split("\r\n")
             if ln.startswith("InpExportDir=")).split("=", 1)[1]
    fname = d + "EURUSD.json"
    assert fname == "Mql5Bot\\demo_connect_check\\EURUSD.json"
    assert not re.search(r"\s", fname)


def test_every_mt5_config_write_is_byte_exact():
    # no MT5 config text goes through a translating text-mode write
    for fn in ("startup_ini(", "export_ini(", "check_preset_text("):
        for m in re.finditer(r"\.write_text\(([^)]*)", SRC):
            assert fn not in m.group(1), m.group(0)
    assert SRC.count("write_crlf_text(") >= 5      # def + 4 call sites
    assert 'newline=""' in SRC
