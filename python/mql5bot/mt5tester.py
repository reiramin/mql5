"""mql5bot.mt5tester — headless MetaTrader 5 Strategy Tester automation.

Phase-2 tool of the AEGIS research mission (docs/SPEC.md §14 tester
procedures, DoD item 37 "backtest automation documented and run on a
sample").  Scope of THIS module:

  * .set (preset) parse / render — including optimization-range lines
    ``Key=value||start||step||stop||Y/N`` preserved verbatim on round-trip;
  * tester .ini generation — the ``[Tester]`` + ``[TesterInputs]`` contract
    consumed by ``terminal64.exe /config:<file>``;
  * deterministic run configuration (symbol, timeframe, dates, model,
    deposit, currency, leverage) — determinism rules are explicit so a run
    is reproducible; MT5 applies broker symbol conditions (spread, ticks),
    which is *documented*, not hidden (cost scenarios live in the Python
    execution model, Phase 4);
  * MT5 HTML tester-report parsing — tables are locale-labelled but
    structurally stable; we parse generically, match labels through a
    synonym table, preserve every raw label/value pair, and expose typed
    canonical metrics.  Nothing is presented that was not read from a cell;
  * batch matrix runs (strategy x symbol x timeframe x period).

The launch boundary is Windows-only (``terminal64.exe``); generation and
parsing are pure Python + stdlib so they are fully unit-tested here without
a terminal.  Raw reports are always preserved before parsing.

Never claim a backtest result from this sandbox: the owner (or a Windows
runner) executes ``tools/run_mt5_backtest.py run`` and pastes the outcome
back.  This module is the deterministic, testable core underneath.
"""

from __future__ import annotations

import dataclasses
import html
import html.parser
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# MT5 constants (values documented by MetaTrader 5)
# ---------------------------------------------------------------------------

MT5_TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1")

# tester model: 0 every tick, 1 one-minute OHLC, 2 open prices only,
# 3 every tick based on real ticks, 4 real ticks.
MT5_MODEL_LABELS = {0: "Every tick", 1: "1 minute OHLC", 2: "Open prices only",
                    3: "Every tick based on real ticks", 4: "Real ticks"}

# Default EA inputs — mirrored from mql5/Experts/Mql5Bot/Mql5Bot.mq5
# (enums as their integer values from the .mqh headers; keep in sync when
# the EA changes).  Values render in MT5 .set style.
EA_INPUT_DEFAULTS: dict[str, object] = {
    # --- Strategy ---
    "InpStrategy": 0,              # STRAT_EMA_CROSSOVER
    "InpFastEma": 10,
    "InpSlowEma": 30,
    "InpRsiPeriod": 14,
    "InpRsiOversold": 30.0,
    "InpRsiOverbought": 70.0,
    "InpDonchianPeriod": 20,
    "InpBollingerPeriod": 20,
    "InpBollingerDev": 2.0,
    "InpMacdFast": 12,
    "InpMacdSlow": 26,
    "InpMacdSignal": 9,
    "InpSlAtr": 2.5,
    "InpTpAtr": 4.0,
    # --- Risk & money management ---
    "InpSizingMode": 1,            # SIZING_RISK_PERCENT_EQ
    "InpRiskPercent": 1.0,
    "InpFixedLots": 0.01,
    "InpFixedMoney": 100.0,
    "InpKellyWinRate": 0.55,
    "InpKellyPayoff": 1.5,
    "InpMaxLots": 10.0,
    "InpDailyLossPct": 0.0,
    "InpMaxDrawdownPct": 0.0,
    "InpMaxSpreadPoints": 0.0,
    "InpMaxBars": 0,
    # --- Exits ---
    "InpTrailAtr": 0.0,
    "InpBreakevenAtr": 0.0,
    "InpBreakevenOffset": 0.0,
    "InpPartialAtr": 0.0,
    "InpPartialFraction": 0.5,
    # --- Execution ---
    "InpEntryMode": 0,             # ENTRY_MARKET
    "InpPendingOffsetPoints": 10,
    "InpPendingExpireBars": 6,
    "InpDeviation": 30,
    "InpMaxRetries": 3,
    "InpAllowShort": True,
    "InpMagic": 20240904,
    # --- Identity & state ---
    "InpUseMagicRegistry": True,
    "InpResetKillSwitch": False,
    # --- Session filter ---
    "InpUseSession": False,
    "InpSessionStartHour": 8,
    "InpSessionStartMin": 0,
    "InpSessionEndHour": 17,
    "InpSessionEndMin": 0,
    "InpSessionDays": 0x3E,        # SESSION_WEEKDAYS = Mon..Fri
    # --- Logging & telemetry ---
    "InpLogLevel": 2,
    "InpTelemetry": False,
    "InpWebhookUrl": "https://httpbin.org/post",
}

# ---------------------------------------------------------------------------
# .set helpers
# ---------------------------------------------------------------------------


def mt5_value_str(value: object) -> str:
    """Render a Python value the way MT5 .set files store it.

    Booleans become ``true``/``false``; floats keep a trailing ``.0`` when
    integral (MT5 GUI style); ints stay plain.  Strings pass through.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return f"{value:.1f}"
        return f"{value:.10g}"
    return str(value)


@dataclasses.dataclass(frozen=True)
class PresetLine:
    """One parsed line of a .set preset.

    ``value`` is the plain value used for a normal (non-optimization) run;
    ``opt_range`` is the verbatim ``||start||step||stop||flag`` suffix when
    the line carries an optimization range, else None.  ``raw`` keeps the
    original text for lossless re-rendering of unknown/comment lines.
    """

    key: str
    value: str
    opt_range: str | None = None
    raw: str | None = None


def parse_set(text: str) -> list[PresetLine]:
    """Parse MT5 .set text into ordered lines (comments dropped).

    Grammar per line: ``;`` comment, blank, or ``Key=Value`` optionally
    followed by ``||start||step||stop||Y/N``.  Optimization pipes are
    preserved verbatim so GUI-saved presets round-trip losslessly.
    """
    lines: list[PresetLine] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if "=" not in line:
            # Not a key/value line (e.g. stray text) — keep raw only.
            lines.append(PresetLine(key="", value="", raw=raw))
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if "||" in rest:
            value, _, opt_range = rest.partition("||")
            lines.append(PresetLine(key=key, value=value.strip(),
                                    opt_range="||" + opt_range))
        else:
            lines.append(PresetLine(key=key, value=rest.strip()))
    return lines


def render_set(lines: list[PresetLine], header: str | None = None) -> str:
    """Render preset lines back to .set text (round-trip of parse_set)."""
    out: list[str] = []
    if header:
        out.append(f"; {header}")
    for ln in lines:
        if ln.raw is not None:
            out.append(ln.raw)
        elif ln.key:
            suffix = ln.opt_range or ""
            out.append(f"{ln.key}={ln.value}{suffix}")
    return "\n".join(out) + ("\n" if out else "")


def inputs_to_lines(inputs: dict[str, object]) -> list[PresetLine]:
    """Convert an ordered {input: value} map to plain preset lines."""
    return [PresetLine(key=k, value=mt5_value_str(v)) for k, v in inputs.items()]


def validate_inputs(inputs: dict[str, object],
                    known: set[str] | None = None) -> None:
    """Reject unknown EA inputs (typo guard) with a precise message.

    ``known=None`` skips validation (arbitrary third-party EAs).
    """
    if known is None:
        return
    unknown = sorted(set(inputs) - known)
    if unknown:
        raise ValueError(
            "unknown EA input(s): " + ", ".join(unknown)
            + " — not in " + ", ".join(sorted(known))
        )


# ---------------------------------------------------------------------------
# Tester configuration and .ini generation
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
_REPORT_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclasses.dataclass
class TesterConfig:
    """Deterministic single-run tester configuration.

    ``ea`` is the .ex5 path relative to the data folder's MQL5 directory
    (e.g. ``Experts\\Mql5Bot\\Mql5Bot.ex5``).  ``inputs`` maps EA input
    names to Python values; rendered in .set style into [TesterInputs].
    """

    ea: str = "Experts\\Mql5Bot\\Mql5Bot.ex5"
    symbol: str = "EURUSD"
    timeframe: str = "H1"
    model: int = 1
    date_from: str = "2020.01.01"
    date_to: str = "2024.01.01"
    deposit: float = 10000.0
    currency: str = "USD"
    leverage: int = 100
    inputs: dict[str, object] = dataclasses.field(default_factory=dict)
    report_name: str = ""
    optimization: int = 0            # 0 = single run
    shutdown_terminal: bool = True   # terminal exits when the test finishes
    replace_report: bool = True

    def validate(self) -> None:
        if not self.ea.lower().endswith(".ex5"):
            raise ValueError(f"ea must be a .ex5 path under MQL5, got {self.ea!r}")
        if not self.symbol or any(ch.isspace() for ch in self.symbol):
            raise ValueError(f"symbol must be a non-blank MT5 symbol, got {self.symbol!r}")
        if self.timeframe not in MT5_TIMEFRAMES:
            raise ValueError(
                f"timeframe must be one of {MT5_TIMEFRAMES}, got {self.timeframe!r}")
        if self.model not in MT5_MODEL_LABELS:
            raise ValueError(f"model must be 0..4, got {self.model}")
        for name, date in (("date_from", self.date_from), ("date_to", self.date_to)):
            if not _DATE_RE.match(date or ""):
                raise ValueError(f"{name} must be YYYY.MM.DD, got {date!r}")
        if self.date_from > self.date_to:
            raise ValueError(
                f"date_from {self.date_from} is after date_to {self.date_to}")
        if self.deposit <= 0:
            raise ValueError(f"deposit must be > 0, got {self.deposit}")
        if not self.currency or len(self.currency) != 3:
            raise ValueError(f"currency must be a 3-letter code, got {self.currency!r}")
        if self.leverage <= 0:
            raise ValueError(f"leverage must be > 0, got {self.leverage}")
        if self.optimization not in (0, 1):
            raise ValueError(f"optimization must be 0 or 1, got {self.optimization}")

    @property
    def safe_report_name(self) -> str:
        """Report stem: explicit name or a deterministic auto id."""
        if self.report_name:
            stem = _REPORT_SAFE_RE.sub("_", self.report_name).strip("_")
            if not stem:
                raise ValueError(f"report_name {self.report_name!r} is not usable")
            return stem
        return (f"{self.symbol}_{self.timeframe}_"
                f"{self.date_from.replace('.', '')}_{self.date_to.replace('.', '')}")

    def render_ini(self, extra_inputs: dict[str, object] | None = None) -> str:
        """Render the terminal64.exe /config: ini for this run.

        Keys follow the documented [Tester] contract; [TesterInputs] gets
        the merged EA inputs (extra_inputs win).  Dates appear only when
        set; deposit renders with two decimals as MT5 expects.
        """
        self.validate()
        inputs = dict(self.inputs)
        if extra_inputs:
            inputs.update(extra_inputs)
        out = ["; generated by mql5bot.mt5tester — deterministic tester config",
               "[Tester]",
               f"Expert={self.ea}",
               f"Symbol={self.symbol}",
               f"Period={self.timeframe}",
               f"Model={self.model}",
               f"Optimization={self.optimization}",
               f"FromDate={self.date_from}",
               f"ToDate={self.date_to}",
               f"Deposit={self.deposit:.2f}",
               f"Currency={self.currency}",
               f"Leverage={self.leverage}",
               "ShutdownTerminal=1" if self.shutdown_terminal else "ShutdownTerminal=0",
               f"Report={self.safe_report_name}",
               "ReplaceReport=1" if self.replace_report else "ReplaceReport=0",
               "",
               "[TesterInputs]"]
        for key, value in inputs.items():
            out.append(f"{key}={mt5_value_str(value)}")
        return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# MT5 HTML tester-report parsing
# ---------------------------------------------------------------------------

# kind -> how to type the metric value from the raw cell text
#   money      plain number in deposit currency (thousands separators ok)
#   number     plain ratio/score number
#   pct        plain percentage value
#   int        whole count
#   money_pct  money primary, percent in parentheses (maximal drawdown)
#   pct_money  percent primary, money in parentheses (relative drawdown)
#   count_pct  count primary, percent in parentheses (won % rows)
#   count_money count primary, money in parentheses (consecutive rows)
#   text       kept verbatim (OnTester result and friends)

@dataclasses.dataclass(frozen=True)
class MetricDef:
    key: str
    kind: str
    labels: tuple[str, ...]


METRIC_DEFS: tuple[MetricDef, ...] = (
    MetricDef("total_net_profit", "money", ("total net profit",)),
    MetricDef("gross_profit", "money", ("gross profit",)),
    MetricDef("gross_loss", "money", ("gross loss",)),
    MetricDef("profit_factor", "number", ("profit factor",)),
    MetricDef("expected_payoff", "money", ("expected payoff",)),
    MetricDef("recovery_factor", "number", ("recovery factor",)),
    MetricDef("sharpe_ratio", "number", ("sharpe ratio",)),
    MetricDef("zscore", "number", ("z-score", "z score", "zscore")),
    MetricDef("lr_correlation", "number", ("lr correlation",)),
    MetricDef("margin_level", "pct", ("margin level",)),
    MetricDef("on_tester_result", "text", ("on tester result", "on_tester result",
                                           "custom criterion", "custom max")),
    MetricDef("balance_drawdown_absolute", "money",
              ("balance drawdown absolute", "absolute drawdown")),
    MetricDef("equity_drawdown_absolute", "money",
              ("equity drawdown absolute",)),
    MetricDef("balance_drawdown_maximal", "money_pct",
              ("balance drawdown maximal", "maximal drawdown")),
    MetricDef("equity_drawdown_maximal", "money_pct",
              ("equity drawdown maximal",)),
    MetricDef("balance_drawdown_relative", "pct_money",
              ("balance drawdown relative", "relative drawdown")),
    MetricDef("equity_drawdown_relative", "pct_money",
              ("equity drawdown relative",)),
    MetricDef("total_trades", "int", ("total trades",)),
    MetricDef("total_deals", "int", ("total deals",)),
    MetricDef("short_trades_won_pct", "count_pct",
              ("short trades (won %)", "short trades (won%)")),
    MetricDef("long_trades_won_pct", "count_pct",
              ("long trades (won %)", "long trades (won%)")),
    MetricDef("profit_trades_pct", "count_pct",
              ("profit trades (% of total)", "profit trades (% of total)",)),
    MetricDef("loss_trades_pct", "count_pct",
              ("loss trades (% of total)",)),
    MetricDef("largest_profit_trade", "money", ("largest profit trade",)),
    MetricDef("largest_loss_trade", "money", ("largest loss trade",)),
    MetricDef("average_profit_trade", "money", ("average profit trade",)),
    MetricDef("average_loss_trade", "money", ("average loss trade",)),
    MetricDef("max_consecutive_wins", "count_money",
              ("maximum consecutive wins",)),
    MetricDef("max_consecutive_losses", "count_money",
              ("maximum consecutive losses",)),
    MetricDef("avg_consecutive_wins", "count", ("average consecutive wins",)),
    MetricDef("avg_consecutive_losses", "count", ("average consecutive losses",)),
    MetricDef("commission", "money", ("commission",)),
    MetricDef("swap", "money", ("swap",)),
)

_SETTING_KEYS = ("expert", "symbol", "period", "broker", "currency",
                 "deposit", "leverage", "history quality")
_SETTING_LABELS = {
    "expert advisor": "expert",
    "expert": "expert",
    "symbol": "symbol",
    "period": "period",
    "broker": "broker",
    "currency": "currency",
    "initial deposit": "deposit",
    "deposit": "deposit",
    "leverage": "leverage",
    "history quality": "history quality",
    "bars": "bars",
    "ticks": "ticks",
    # the modelling mode the terminal ACTUALLY used — required evidence
    # for the real-tick coverage rule (docs/MT5_ROUNDTRIP.md step 7):
    # selecting a real-tick mode does NOT guarantee every tick was real.
    "model": "model",
}


class _TableExtractor(html.parser.HTMLParser):
    """Collect every <table> as rows of plain cell texts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._skip_depth = 0  # >0 while inside <style>/<script>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in ("style", "script"):
            self._skip_depth += 1
        elif self._skip_depth == 0 and tag == "table":
            self._table = []
        elif self._skip_depth == 0 and tag == "tr" and self._table is not None:
            self._row = []
            self._table.append(self._row)
        elif self._skip_depth == 0 and tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("style", "script") and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and tag in ("td", "th") and self._cell is not None:
            self._row.append("".join(self._cell).strip())  # type: ignore[union-attr]
            self._cell = None
        elif self._skip_depth == 0 and tag == "tr" and self._row is not None:
            self._row = None
        elif self._skip_depth == 0 and tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and self._cell is not None:
            self._cell.append(data)


def _clean(text: str) -> str:
    """Collapse whitespace (incl. nbsp) and strip HTML entities leftovers."""
    text = text.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _strip_thousands(text: str) -> str:
    """Remove thousands separators ('1 234.56', '1,234.56') -> '1234.56'."""
    text = re.sub(r"[ ,](?=\d{3}(?:[.,]|$))", "", text)
    return text


def _first_number(text: str) -> float | None:
    m = re.search(r"-?\d+(?:[.,]\d+)?", _strip_thousands(text))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _int_in(text: str) -> int | None:
    m = re.search(r"-?\d+", _strip_thousands(text))
    return int(m.group(0)) if m else None


def _pct_in(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _in_parentheses(text: str) -> float | None:
    m = re.search(r"\(([^)]*)\)", text)
    if not m:
        return None
    return _first_number(m.group(1))


def _typed(kind: str, raw: str) -> object:
    """Extract the typed metric value for a metric kind (None when absent)."""
    if kind == "money":
        return _first_number(raw)
    if kind == "number":
        return _first_number(raw)
    if kind == "pct":
        return _pct_in(raw) or _first_number(raw)
    if kind == "int":
        return _int_in(raw)
    if kind == "money_pct":
        # maximal drawdown rows: money first, optional pct in parentheses
        money, pct = _first_number(raw), _pct_in(raw)
        if pct is None:
            pct = _in_parentheses(raw)
        return {"money": money, "pct": pct} if money is not None or pct is not None else None
    if kind == "pct_money":
        # relative drawdown rows: pct first, optional money in parentheses
        pct, money = _pct_in(raw), _in_parentheses(raw)
        return {"pct": pct, "money": money} if pct is not None or money is not None else None
    if kind == "count_pct":
        count, pct = _int_in(raw), _pct_in(raw)
        return {"count": count, "pct": pct} if count is not None or pct is not None else None
    if kind == "count_money":
        # consecutive-win rows: count first, optional money in parentheses
        count, money = _int_in(raw), _in_parentheses(raw)
        return {"count": count, "money": money} if count is not None or money is not None else None
    if kind == "count":
        return _int_in(raw)
    return raw  # text


def _label_key(text: str) -> str:
    return re.sub(r"[^a-z0-9%() ]+", "", _clean(text).lower())


def extract_tables(html_text: str) -> list[list[list[str]]]:
    parser = _TableExtractor()
    parser.feed(html_text)  # tolerant: malformed markup is skipped, not fatal
    parser.close()
    return parser.tables


# Real-tick coverage record (FINAL REALITY-GATE §4, 2026-09-08).
# Official MetaTrader 5 semantics ("Real and Generated Ticks",
# metatrader5.com/en/terminal/help/algotrading/tick_generation): "If a
# symbol history has a minute bar with no tick data for it, the tester
# generates ticks in the Every tick mode." Therefore selecting the
# real-tick modelling mode never implies every tick was real — every
# real-tick leg must record which coverage class applies; PARTIAL or
# UNKNOWN keeps the certification appropriately constrained.
REAL_TICK_COVERAGE_FULL = "REAL_TICK_COVERAGE_FULL"
REAL_TICK_COVERAGE_PARTIAL = "REAL_TICK_COVERAGE_PARTIAL"
REAL_TICK_COVERAGE_UNKNOWN = "REAL_TICK_COVERAGE_UNKNOWN"
REAL_TICK_COVERAGES = (REAL_TICK_COVERAGE_FULL,
                       REAL_TICK_COVERAGE_PARTIAL,
                       REAL_TICK_COVERAGE_UNKNOWN)


@dataclasses.dataclass
class ReportData:
    """Parsed MT5 tester report.

    ``settings``/``fields`` preserve the raw label/value pairs (never lose
    information); ``metrics`` holds typed canonical values (None when the
    report did not contain the row).  ``tables`` carries the raw table
    count for diagnostics.  Report rows are matched case-insensitively via
    synonym labels — locale-labelled values are kept raw for review.
    """

    tables: int
    settings: dict[str, str]
    fields: dict[str, str]
    metrics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"tables": self.tables,
                "settings": self.settings,
                "fields": self.fields,
                "metrics": self.metrics}

    def as_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def parse_report_html(html_text: str) -> ReportData:
    """Parse an MT5 Strategy Tester HTML report into canonical metrics.

    Every row of every table with >= 2 cells is kept in ``fields`` under
    its (cleaned) label.  Setting rows are additionally classified into
    ``settings``; metric rows matching the synonym table are typed into
    ``metrics``.  Unknown rows are simply preserved — the parser never
    guesses.
    """
    tables = extract_tables(html_text)
    settings: dict[str, str] = {}
    fields: dict[str, str] = {}
    raw_metrics: dict[str, str] = {}
    metric_by_label: dict[str, MetricDef] = {}
    for mdef in METRIC_DEFS:
        for label in mdef.labels:
            metric_by_label.setdefault(_label_key(label), mdef)
    setting_by_label = {_label_key(k): v for k, v in _SETTING_LABELS.items()}

    for table in tables:
        for row in table:
            cells = [_clean(c) for c in row if _clean(c)]
            if len(cells) < 2:
                continue
            label, value = cells[0], cells[1]
            key = _label_key(label)
            fields[label] = value
            if key in setting_by_label:
                settings.setdefault(setting_by_label[key], value)
            mdef = metric_by_label.get(key)
            if mdef is not None and mdef.key not in raw_metrics:
                raw_metrics[mdef.key] = value
    metrics: dict[str, object] = {
        mdef.key: (_typed(mdef.kind, raw_metrics[mdef.key])
                   if mdef.key in raw_metrics else None)
        for mdef in METRIC_DEFS
    }
    return ReportData(tables=len(tables), settings=settings,
                      fields=fields, metrics=metrics)


def report_gate(parsed: ReportData | None) -> tuple[bool, str]:
    """Fail-closed completeness gate for a parsed tester report.

    A leg's evidence must at least BE a report: the parsed artifact must
    contain one or more tables and at least one label/value row.  An
    empty, truncated or non-report file therefore can never become an
    ``ok`` leg (red-team: empty/edited/fake report attacks).  The gate
    deliberately does NOT judge metric values — extraction stays
    locale-tolerant and the trade-count/spread gates live in certify.py.
    """
    if parsed is None:
        return False, "report did not parse (missing or malformed)"
    if parsed.tables < 1:
        return False, ("report parsed but contains no tables "
                       "(empty or not a tester report)")
    if not parsed.fields:
        return False, ("report parsed but contains no label/value rows "
                       "(truncated or empty report)")
    return True, ""


# ---------------------------------------------------------------------------
# Runner (Windows-only boundary)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RunSettings:
    """Paths and lifecycle settings for a headless tester run."""

    terminal_dir: Path | str      # folder containing terminal64.exe
    data_folder: Path | str       # MT5 data folder (contains MQL5\)
    out_dir: Path | str = "results"   # artifacts root (raw report kept here)
    timeout_s: float = 3600.0
    poll_s: float = 5.0


@dataclasses.dataclass
class RunOutcome:
    """Result of one headless tester run.

    ``ok`` is True only when the terminal exited and the report file was
    found and parsed.  ``timed_out``/``error`` explain failures.  The raw
    report is always preserved at ``report_raw`` when found, even when
    parsing failed (parser errors are non-fatal — the raw file is the
    source of truth for the owner round-trip).
    """

    run_id: str
    ok: bool
    timed_out: bool
    error: str
    config: dict[str, object]
    report_raw: str | None
    report_json: str | None
    report: ReportData | None

    def to_dict(self) -> dict[str, object]:
        return {"run_id": self.run_id,
                "ok": self.ok,
                "timed_out": self.timed_out,
                "error": self.error,
                "config": self.config,
                "report_raw": self.report_raw,
                "report_json": self.report_json,
                "metrics": self.report.to_dict() if self.report else None}


def _config_snapshot(cfg: TesterConfig) -> dict[str, object]:
    return {"ea": cfg.ea, "symbol": cfg.symbol, "timeframe": cfg.timeframe,
            "model": cfg.model, "date_from": cfg.date_from, "date_to": cfg.date_to,
            "deposit": cfg.deposit, "currency": cfg.currency,
            "leverage": cfg.leverage, "inputs": dict(cfg.inputs),
            "report_name": cfg.safe_report_name}


def run_backtest(cfg: TesterConfig, settings: RunSettings) -> RunOutcome:
    """Run one backtest headlessly and parse its report.

    Windows-only: raises RuntimeError elsewhere.  Writes ``tester.ini`` and
    keeps artifacts under ``<out_dir>/runs/<run_id>/``; waits for the
    terminal (ShutdownTerminal=1) with a timeout; preserves the raw HTML
    report before parsing.
    """
    if sys.platform != "win32":
        raise RuntimeError(
            "headless MT5 runs are Windows-only (terminal64.exe); "
            "on this platform use the generators/parser (unit-tested)")
    cfg.validate()
    terminal_dir = Path(settings.terminal_dir)
    data_folder = Path(settings.data_folder)
    terminal_exe = terminal_dir / "terminal64.exe"
    if not terminal_exe.exists():
        raise FileNotFoundError(f"terminal64.exe not found in {terminal_dir}")
    if not (data_folder / "MQL5").is_dir():
        raise FileNotFoundError(f"{data_folder} is not an MT5 data folder (no MQL5)")
    out_root = Path(settings.out_dir)
    run_id = f"{cfg.safe_report_name}_m{cfg.model}_{int(time.time())}"
    run_dir = out_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    ini_path = run_dir / "tester.ini"
    ini_path.write_text(cfg.render_ini(), encoding="utf-8")

    report_html = (data_folder / "tester" / f"{cfg.safe_report_name}.htm")
    # Start fresh so a previous run's stale report can never be mistaken
    # for this run's output.
    if report_html.exists():
        report_html.unlink()

    started = time.monotonic()
    proc = subprocess.Popen(
        [str(terminal_exe), f"/config:{ini_path}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    timed_out = False
    while proc.poll() is None:
        if time.monotonic() - started > settings.timeout_s:
            timed_out = True
            proc.kill()
            break
        time.sleep(min(settings.poll_s, max(0.5, settings.timeout_s / 20)))
    proc.wait(timeout=10)

    report_raw: str | None = None
    parsed: ReportData | None = None
    error = ""
    if timed_out:
        error = f"timed out after {settings.timeout_s:.0f}s (process killed)"
    else:
        # Report may land a moment after the process exits.
        deadline = time.monotonic() + 10.0
        while not report_html.exists() and time.monotonic() < deadline:
            time.sleep(0.5)
        if not report_html.exists():
            error = ("report not found: " + str(report_html)
                     + " — check the terminal log (tester did not produce a report)")
        else:
            report_raw = str(run_dir / f"{cfg.safe_report_name}.htm")
            import shutil
            shutil.copyfile(report_html, report_raw)
            try:
                parsed = parse_report_html(report_html.read_text(
                    encoding="utf-8", errors="replace"))
            except (ValueError, TypeError, UnicodeError) as exc:
                # never lose the raw artifact on a parse failure
                error = f"report parse failed (raw preserved): {exc}"
            else:
                gate_ok, gate_reason = report_gate(parsed)
                if not gate_ok:
                    # fail closed: an empty/truncated report is NOT a leg
                    error = f"{gate_reason} (raw preserved)"
    report_json: str | None = None
    if parsed is not None:
        report_json = str(run_dir / "report.json")
        Path(report_json).write_text(parsed.as_json(), encoding="utf-8")
    outcome = RunOutcome(
        run_id=run_id,
        ok=parsed is not None and not timed_out and not error,
        timed_out=timed_out,
        error=error,
        config=_config_snapshot(cfg),
        report_raw=report_raw,
        report_json=report_json,
        report=parsed)
    return outcome


def run_batch(configs: list[TesterConfig], settings: RunSettings) -> list[RunOutcome]:
    """Run configs sequentially (one tester terminal at a time)."""
    return [run_backtest(cfg, settings) for cfg in configs]


__all__ = [
    "EA_INPUT_DEFAULTS",
    "METRIC_DEFS",
    "MT5_MODEL_LABELS",
    "MT5_TIMEFRAMES",
    "REAL_TICK_COVERAGES",
    "REAL_TICK_COVERAGE_FULL",
    "REAL_TICK_COVERAGE_PARTIAL",
    "REAL_TICK_COVERAGE_UNKNOWN",
    "MetricDef",
    "PresetLine",
    "ReportData",
    "RunOutcome",
    "RunSettings",
    "TesterConfig",
    "extract_tables",
    "inputs_to_lines",
    "mt5_value_str",
    "parse_report_html",
    "parse_set",
    "render_set",
    "report_gate",
    "run_backtest",
    "run_batch",
    "validate_inputs",
]
