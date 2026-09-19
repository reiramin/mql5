"""mql5bot.i18n — Persian (fa) / RTL console PRESENTATION layer.

PRESENTATION ONLY (Feature Wave 2, commit 2). This module translates and lays
out text that is already printed for a human on the console. It never touches
a computed value, a status string stored in a structure, a JSON field, an
artifact (HTML reports, manifests, parity/evidence files), or an exit code.

Opt-in and explicit: the CLI's ``--lang fa`` flag or ``MQL5BOT_LANG=fa``.
The default stays English, byte-identical to before this module existed —
English output NEVER routes through the renderers here.

RTL correctness rules implemented here:

* Persian digits (U+06F0..U+06F9) are applied ONLY to values presented for a
  human (metric numbers, counts) — NEVER to Latin identifiers, symbol names,
  hashes, JSON, URLs or file paths, which stay verbatim, readable and
  copyable.
* Latin runs inside Persian sentences are wrapped in Unicode ISOLATES
  (LRI U+2066 … PDI U+2069) so bidirectional reordering cannot scramble them;
  the wrapped text itself is byte-contiguous and unmodified.
* Column alignment uses a display width that ignores the zero-width bidi
  control characters, so mixed-direction tables stay aligned.

The certification vocabulary that carries evidential meaning is PROTECTED:
``SOFTWARE_PASS``, ``EMPIRICAL_VALIDATION_PENDING``, ``VERIFIED``,
``NOT VERIFIED``, ``GOLD_SEMANTIC_PASS``, ``MT5-VALIDATED``,
``BLOCKED_OWNER_ENVIRONMENT`` are never translated: ``explain_status`` shows
the Persian explanation ALONGSIDE the original term, never instead of it —
a translated synonym would misrepresent what was proven.

All translations live in the ONE table ``MESSAGES_FA`` below (no scattered
string literals), so a missing key is detectable; a missing key falls back to
English rather than raising.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

ENV_LANG = "MQL5BOT_LANG"
LANGS = ("en", "fa")

# ---------------------------------------------------------------------------
# bidi / digit helpers
# ---------------------------------------------------------------------------

LRI = "\u2066"   # LEFT-TO-RIGHT ISOLATE
PDI = "\u2069"   # POP DIRECTIONAL ISOLATE
RLM = "\u200f"   # RIGHT-TO-LEFT MARK (hints an RTL line to the terminal)
LRM = "\u200e"   # LEFT-TO-RIGHT MARK

# zero-width controls excluded from display width (incl. RLI/FSI for safety)
_BIDI_CONTROLS = frozenset({LRI, PDI, RLM, LRM, "\u2067", "\u2068"})

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(text: str) -> str:
    """ASCII digits → Persian digits. For presented VALUES only — callers must
    never pass identifiers, hashes, paths or URLs through this."""
    return str(text).translate(_FA_DIGITS)


def isolate_ltr(text: str) -> str:
    """Wrap a Latin run (identifier, hash, path, URL, JSON) in LRI…PDI so it
    renders in its own order inside an RTL sentence. The wrapped text itself is
    unmodified and byte-contiguous — readable and copyable."""
    return f"{LRI}{text}{PDI}"


def display_width(text: str) -> int:
    """Column width of ``text`` ignoring zero-width bidi controls, so padding
    survives mixed-direction content."""
    return sum(1 for ch in text if ch not in _BIDI_CONTROLS)


def pad_end(text: str, width: int) -> str:
    """Pad with trailing spaces to ``width`` display columns."""
    return text + " " * max(0, width - display_width(text))


# ---------------------------------------------------------------------------
# language resolution — opt-in, default English
# ---------------------------------------------------------------------------

def resolve_lang(cli_value: str | None = None,
                 env: Mapping[str, str] | None = None) -> str:
    """CLI flag wins; then ``MQL5BOT_LANG``; default ``en``.

    An unknown CLI value raises (argparse ``choices`` already rejects it at
    the parser, cleanly); an unknown environment value falls back to English
    so an exported typo can never change behaviour silently mid-script.
    """
    if cli_value:
        if cli_value not in LANGS:
            raise ValueError(f"unknown language {cli_value!r}; "
                             f"choose one of {LANGS}")
        return cli_value
    source = os.environ if env is None else env
    env_value = source.get(ENV_LANG, "")
    return env_value if env_value in LANGS else "en"


# ---------------------------------------------------------------------------
# THE translation table — every fa string lives here and only here
# ---------------------------------------------------------------------------

MESSAGES_FA: dict[str, str] = {
    # metric labels (cli._print_metrics)
    "metric.total_return": "بازده کل",
    "metric.cagr": "نرخ رشد مرکب سالانه",
    "metric.sharpe": "نسبت شارپ",
    "metric.sortino": "نسبت سورتینو",
    "metric.max_drawdown": "حداکثر افت سرمایه",
    "metric.win_rate": "نرخ برد",
    "metric.profit_factor": "ضریب سود",
    "metric.trades": "تعداد معاملات",
    "metric.net_profit": "سود خالص",
    "metric.expectancy": "امید ریاضی",
    # compare row labels
    "compare.ret": "بازده",
    "compare.sharpe": "شارپ",
    "compare.maxdd": "حداکثر افت",
    "compare.trades": "معاملات",
    # optimize / walkforward headers
    "optimize.params": "پارامترها",
    "optimize.metric": "معیار",
    "walkforward.window": "پنجره",
    "walkforward.train_metric": "معیار آموزش",
    "walkforward.best_params": "بهترین پارامترها",
    "walkforward.oos": "جمع‌بندی برون‌نمونه",
    # one-line messages
    "msg.wrote_bars": "کندل نوشته شد در",
    "msg.report": "گزارش",
    "msg.json": "خروجی JSON",
    "msg.error": "خطا",
    "msg.dashboard": "داشبورد",
    "msg.dashboard_listening": "داشبورد در حال اجراست روی",
}

# keys the fa renderers below depend on — pinned by a test so a renderer can
# never reference a translation that does not exist
REQUIRED_KEYS: tuple[str, ...] = tuple(sorted(MESSAGES_FA))


def tr(key: str, en_text: str, lang: str) -> str:
    """The fa translation for ``key``, or ``en_text`` unchanged. A missing key
    falls back to English — it never raises."""
    if lang != "fa":
        return en_text
    return MESSAGES_FA.get(key, en_text)


# ---------------------------------------------------------------------------
# protected certification vocabulary — NEVER translated, only explained
# ---------------------------------------------------------------------------

PROTECTED_TERMS: tuple[str, ...] = (
    "SOFTWARE_PASS",
    "EMPIRICAL_VALIDATION_PENDING",
    "VERIFIED",
    "NOT VERIFIED",
    "GOLD_SEMANTIC_PASS",
    "MT5-VALIDATED",
    "BLOCKED_OWNER_ENVIRONMENT",
)

_PROTECTED_EXPLANATIONS_FA: dict[str, str] = {
    "SOFTWARE_PASS":
        "همهٔ مراحل نرم‌افزاری دقیقاً طبق مشخصات اجرا شد؛ "
        "هیچ ادعایی دربارهٔ عملکرد هیچ استراتژی‌ای ندارد",
    "EMPIRICAL_VALIDATION_PENDING":
        "گیت‌های تجربی گذرانده شده‌اند اما نردبان تأیید MT5 هنوز اجرا "
        "نشده است",
    "VERIFIED":
        "کل نردبان تأیید — شامل اجرای واقعی تستر MT5 با موفقیت همهٔ "
        "لگ‌های الزامی — گذرانده شد",
    "NOT VERIFIED":
        "تستر MT5 اجرا نشده یا نگذشته است؛ اجرانشدن هرگز قبولی نیست",
    "GOLD_SEMANTIC_PASS":
        "توافق روی فیکسچرهای طلایی منجمد؛ هرگز به‌معنای تأیید MT5 یا "
        "VERIFIED نیست",
    "MT5-VALIDATED":
        "شواهد مالک روی ترمینال MT5 در برابر رکورد منجمد تأیید شد",
    "BLOCKED_OWNER_ENVIRONMENT":
        "اجرای تمیز از روی لاگ تستر اثبات شده اما محیط مالک فایل گزارش "
        "را ننوشت؛ این وضعیت قبولی نیست و گیت همان‌جا می‌ایستد",
}


def explain_status(term: str, lang: str = "en") -> str:
    """Present a certification status term.

    In English: the term, verbatim. In Persian: the term VERBATIM (isolated so
    RTL layout cannot reorder it) followed by the Persian explanation — the
    explanation sits ALONGSIDE the original term, never instead of it. A term
    with no recorded explanation is shown verbatim in both modes.
    """
    if lang != "fa":
        return term
    explanation = _PROTECTED_EXPLANATIONS_FA.get(term)
    if not explanation:
        return term
    return f"{isolate_ltr(term)} — {explanation}"


# ---------------------------------------------------------------------------
# fa renderers for the CLI's human-facing lines. English output NEVER routes
# through these — the en branches in cli.py keep their original f-strings, so
# the default is byte-identical by construction.
# ---------------------------------------------------------------------------

def render_metric_rows_fa(rows: list[tuple[str, str, str, str]]) -> str:
    """``rows`` — (key, en_label, formatted_value, unit); the values arrive
    already formatted by the caller (single source of number formatting).
    Labels come from MESSAGES_FA; values get Persian digits; columns align on
    display width."""
    labels = [tr(key, en_label, "fa") for key, en_label, _, _ in rows]
    width = max(display_width(lbl) for lbl in labels)
    lines = []
    for (key, en_label, value, unit), label in zip(rows, labels):
        line = f"{RLM}{pad_end(label, width)} {fa_digits(value)} {unit}"
        lines.append(line.rstrip())
    return "\n".join(lines)


def render_compare_row_fa(name: str, ret: str, sharpe: str, maxdd: str,
                          trades: str) -> str:
    """One strategy-comparison row. ``name`` is a Latin identifier: isolated,
    verbatim, NEVER digit-substituted. Metric values get Persian digits."""
    return (f"{RLM}{pad_end(isolate_ltr(name), 20)} "
            f"{tr('compare.ret', 'ret', 'fa')} {fa_digits(ret)}٪  "
            f"{tr('compare.sharpe', 'sharpe', 'fa')} {fa_digits(sharpe)}  "
            f"{tr('compare.maxdd', 'maxDD', 'fa')} {fa_digits(maxdd)}٪  "
            f"{tr('compare.trades', 'trades', 'fa')} {fa_digits(trades)}")


def render_wrote_bars_fa(n_bars: int, path: str) -> str:
    """'wrote N bars to PATH' — the count in Persian digits, the path isolated
    and verbatim."""
    return (f"{RLM}{fa_digits(str(n_bars))} "
            f"{tr('msg.wrote_bars', 'bars written to', 'fa')} "
            f"{isolate_ltr(path)}")


def render_artifact_fa(kind_key: str, kind_en: str, path: str) -> str:
    """'report -> PATH' / 'json -> PATH' — label translated, path isolated."""
    return f"{RLM}{tr(kind_key, kind_en, 'fa')} ← {isolate_ltr(path)}"


def render_error_fa(exc: object) -> str:
    """'error: …' — the label translated; the exception text stays verbatim
    (isolated), because it may carry identifiers the operator must copy."""
    return f"{RLM}{tr('msg.error', 'error', 'fa')}: {isolate_ltr(str(exc))}"


def render_dashboard_url_fa(url: str) -> str:
    return f"{RLM}{tr('msg.dashboard', 'dashboard', 'fa')}: {isolate_ltr(url)}"


def render_dashboard_listening_fa(url: str) -> str:
    return (f"{RLM}{tr('msg.dashboard_listening', 'dashboard listening on', 'fa')} "
            f"{isolate_ltr(url)}")


def render_oos_aggregate_fa(ret: str, sharpe: str, maxdd: str) -> str:
    """Walk-forward OOS aggregate line."""
    return (f"{RLM}{tr('walkforward.oos', 'OOS aggregate', 'fa')} (OOS): "
            f"{tr('compare.ret', 'ret', 'fa')} {fa_digits(ret)}٪  "
            f"{tr('compare.sharpe', 'sharpe', 'fa')} {fa_digits(sharpe)}  "
            f"{tr('compare.maxdd', 'maxDD', 'fa')} {fa_digits(maxdd)}٪")


def render_table_header_fa(cols: list[tuple[str, str, int]]) -> str:
    """A header row: (key, en_label, width) triples, aligned on display
    width."""
    return RLM + " ".join(
        pad_end(tr(key, en, "fa"), width) for key, en, width in cols).rstrip()


__all__ = [
    "ENV_LANG",
    "LANGS",
    "LRI",
    "LRM",
    "MESSAGES_FA",
    "PDI",
    "PROTECTED_TERMS",
    "REQUIRED_KEYS",
    "RLM",
    "display_width",
    "explain_status",
    "fa_digits",
    "isolate_ltr",
    "pad_end",
    "render_artifact_fa",
    "render_compare_row_fa",
    "render_dashboard_listening_fa",
    "render_dashboard_url_fa",
    "render_error_fa",
    "render_metric_rows_fa",
    "render_oos_aggregate_fa",
    "render_table_header_fa",
    "render_wrote_bars_fa",
    "resolve_lang",
    "tr",
]
