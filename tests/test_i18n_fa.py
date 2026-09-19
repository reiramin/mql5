"""Tests for mql5bot.i18n — the Persian/RTL console PRESENTATION layer.

Feature Wave 2, commit 2. These pin the hard rules:

* default output is byte-identical to the pre-i18n CLI (golden strings);
* fa is opt-in (``--lang fa`` / ``MQL5BOT_LANG=fa``) and renders Persian;
* no fa translation key is missing; a missing key falls back to English;
* the protected certification vocabulary appears VERBATIM in fa mode,
  explained alongside — never replaced;
* Latin identifiers/hashes/paths are never reordered or digit-substituted;
* an unknown ``--lang`` value fails cleanly;
* machine-readable artifacts are unaffected by the language.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mql5bot import i18n
from mql5bot.cli import _print_metrics

REPO = Path(__file__).resolve().parents[1]

_METRICS = {"total_return_pct": 12.3456, "cagr_pct": 5.0, "sharpe": 1.234,
            "sortino": 2.0, "max_drawdown_pct": -8.1, "win_rate_pct": 55.5,
            "profit_factor": 1.5, "trades": 42, "net_profit": 1234.5,
            "expectancy": 29.393}

# The EXACT bytes the pre-i18n CLI printed for _METRICS (captured from the
# committed implementation). The default language must reproduce them
# byte for byte — this test fails on ANY change to the English output.
_GOLDEN_EN = (
    "total return  12.35 %\n"
    "CAGR          5.00 %\n"
    "Sharpe        1.23\n"
    "Sortino       2.00\n"
    "max drawdown  -8.10 %\n"
    "win rate      55.50 %\n"
    "profit factor 1.50\n"
    "trades        42.00\n"
    "net profit    1,234.50\n"
    "expectancy    29.39\n"
)


def _capture(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


def _run_cli(*args: str, env_extra: dict | None = None
             ) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop(i18n.ENV_LANG, None)  # a stray operator export must not leak in
    # pin the REPO's package for the subprocess (never an installed copy)
    env["PYTHONPATH"] = str(REPO / "python")
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, "-m", "mql5bot.cli", *args],
                          capture_output=True, text=True, env=env,
                          check=False)


# ---------------------------------------------------------------------------
# default English output — byte-identical to the pre-i18n CLI
# ---------------------------------------------------------------------------

def test_default_metrics_output_is_byte_identical_golden():
    assert _capture(_print_metrics, _METRICS) == _GOLDEN_EN


def test_explicit_lang_en_equals_default():
    assert _capture(_print_metrics, _METRICS, lang="en") == _GOLDEN_EN


def test_default_cli_run_is_english(tmp_path: Path):
    out = tmp_path / "d.csv"
    cp = _run_cli("data", "--days", "2", "--seed", "7", "--out", str(out))
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.startswith("wrote ")
    assert "bars to" in cp.stdout


def test_unknown_env_lang_falls_back_to_english(tmp_path: Path):
    out = tmp_path / "d.csv"
    cp = _run_cli("data", "--days", "2", "--seed", "7", "--out", str(out),
                  env_extra={i18n.ENV_LANG: "de"})
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.startswith("wrote ")


# ---------------------------------------------------------------------------
# fa opt-in — flag and environment variable
# ---------------------------------------------------------------------------

def test_lang_flag_fa_renders_persian_and_keeps_path_verbatim(tmp_path: Path):
    out = tmp_path / "d.csv"
    cp = _run_cli("--lang", "fa", "data", "--days", "2", "--seed", "7",
                  "--out", str(out))
    assert cp.returncode == 0, cp.stderr
    assert "کندل" in cp.stdout                 # Persian rendered
    assert str(out) in cp.stdout               # path verbatim, copyable
    assert "wrote" not in cp.stdout


def test_lang_flag_accepted_after_the_subcommand(tmp_path: Path):
    out = tmp_path / "d.csv"
    cp = _run_cli("data", "--days", "2", "--seed", "7", "--out", str(out),
                  "--lang", "fa")
    assert cp.returncode == 0, cp.stderr
    assert "کندل" in cp.stdout


def test_env_var_fa_opts_in(tmp_path: Path):
    out = tmp_path / "d.csv"
    cp = _run_cli("data", "--days", "2", "--seed", "7", "--out", str(out),
                  env_extra={i18n.ENV_LANG: "fa"})
    assert cp.returncode == 0, cp.stderr
    assert "کندل" in cp.stdout


def test_cli_flag_wins_over_env_var(tmp_path: Path):
    out = tmp_path / "d.csv"
    cp = _run_cli("--lang", "en", "data", "--days", "2", "--seed", "7",
                  "--out", str(out), env_extra={i18n.ENV_LANG: "fa"})
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.startswith("wrote ")


def test_unknown_lang_flag_fails_cleanly(tmp_path: Path):
    cp = _run_cli("--lang", "de", "data", "--days", "2",
                  "--out", str(tmp_path / "d.csv"))
    assert cp.returncode == 2                  # argparse usage error
    assert "invalid choice" in cp.stderr


def test_fa_metrics_render_with_persian_digits():
    text = _capture(_print_metrics, _METRICS, lang="fa")
    assert "بازده کل" in text
    assert "۱۲.۳۵" in text                     # value digits are Persian
    assert "total return" not in text


# ---------------------------------------------------------------------------
# artifacts are unaffected by the language (presentation only)
# ---------------------------------------------------------------------------

def test_csv_artifact_is_byte_identical_across_languages(tmp_path: Path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    cp1 = _run_cli("data", "--days", "2", "--seed", "7", "--out", str(a))
    cp2 = _run_cli("--lang", "fa", "data", "--days", "2", "--seed", "7",
                   "--out", str(b))
    assert cp1.returncode == 0 and cp2.returncode == 0
    assert a.read_bytes() == b.read_bytes()


# ---------------------------------------------------------------------------
# the ONE translation table — no key missing, missing key falls back
# ---------------------------------------------------------------------------

def test_no_required_translation_key_is_missing():
    for key in i18n.REQUIRED_KEYS:
        assert key in i18n.MESSAGES_FA
        assert i18n.MESSAGES_FA[key].strip(), f"{key} has an empty fa value"


def test_missing_key_falls_back_to_english_never_raises():
    assert i18n.tr("no.such.key", "fallback text", "fa") == "fallback text"
    assert i18n.tr("no.such.key", "fallback text", "en") == "fallback text"


# ---------------------------------------------------------------------------
# protected certification vocabulary — verbatim, explained alongside
# ---------------------------------------------------------------------------

def test_protected_terms_appear_verbatim_in_fa_mode():
    for term in i18n.PROTECTED_TERMS:
        rendered = i18n.explain_status(term, lang="fa")
        assert term in rendered, f"{term} must appear VERBATIM"
        # a Persian explanation sits alongside (Arabic-script codepoints)
        assert any("؀" <= ch <= "ۿ" for ch in rendered), \
            f"{term} carries no Persian explanation"


def test_protected_terms_untouched_in_english():
    for term in i18n.PROTECTED_TERMS:
        assert i18n.explain_status(term, lang="en") == term


def test_unknown_status_term_stays_verbatim_in_fa():
    assert i18n.explain_status("SOME_NEW_STATE", lang="fa") == "SOME_NEW_STATE"


# ---------------------------------------------------------------------------
# RTL correctness — identifiers stay verbatim; alignment survives bidi
# ---------------------------------------------------------------------------

def test_latin_identifiers_never_reordered_or_digit_substituted():
    row = i18n.render_compare_row_fa("strat123", "12.35", "1.23",
                                     "-8.10", "42")
    # the identifier is byte-contiguous, verbatim, ASCII digits intact
    assert "strat123" in row
    # metric values ARE Persian-digit
    assert "۱۲.۳۵" in row and "۴۲" in row
    # the identifier is wrapped in directional isolates (LRI ... PDI)
    assert i18n.LRI + "strat123" + i18n.PDI in row


def test_isolate_keeps_content_byte_contiguous():
    h = "a85cba3f" * 8  # a hash-like Latin run
    wrapped = i18n.isolate_ltr(h)
    assert wrapped == i18n.LRI + h + i18n.PDI
    assert h in wrapped


def test_display_width_ignores_bidi_controls_and_pads_align():
    plain = "abcdef"
    wrapped = i18n.isolate_ltr(plain)
    assert i18n.display_width(wrapped) == len(plain)
    assert i18n.display_width(i18n.RLM + "سود") == 3
    # padding to the same width yields the same display width for both
    a = i18n.pad_end(wrapped, 10)
    b = i18n.pad_end(plain, 10)
    assert i18n.display_width(a) == i18n.display_width(b) == 10


def test_fa_digits_converts_only_digits():
    assert i18n.fa_digits("1,234.56") == "۱,۲۳۴.۵۶"
    assert i18n.fa_digits("abc") == "abc"


# ---------------------------------------------------------------------------
# resolve_lang — precedence and validation
# ---------------------------------------------------------------------------

def test_resolve_lang_precedence():
    assert i18n.resolve_lang(None, env={}) == "en"
    assert i18n.resolve_lang(None, env={i18n.ENV_LANG: "fa"}) == "fa"
    assert i18n.resolve_lang("en", env={i18n.ENV_LANG: "fa"}) == "en"
    assert i18n.resolve_lang(None, env={i18n.ENV_LANG: "xx"}) == "en"
    with pytest.raises(ValueError, match="unknown language"):
        i18n.resolve_lang("xx", env={})
