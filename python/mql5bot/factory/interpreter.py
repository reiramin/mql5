"""mql5bot.factory.interpreter — NL → draft DSL spec (mission §9/§10/§11).

Two-stage interpretation is MANDATORY::

    text → draft spec → validation → user review → canonical spec

This module provides:

- :class:`IStrategyInterpreter` — the provider-neutral contract (an
  LLM provider plugs in HERE; it never gains execution authority);
- :class:`TemplateInterpreter` — a fully DETERMINISTIC pattern
  interpreter (EN + FA) with zero ML.  It recognizes a small, explicit
  pattern set and reports everything else as AMBIGUOUS_PARAMETER — it
  never invents thresholds (the canonical example: "RSI is low" must
  NOT become RSI < 30).

The output is a DRAFT document (version 0): the Factory stores it,
shows the restatement + ambiguities, and the canonical version is
created only after the ambiguities are resolved and reviewed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .claims import extract_claims
from .providers import ResearchMaterial
from .security import sanitize_external_text

# Persian/Arabic-Indic digits → ASCII
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# Deterministic sentence templates (each is a documented contract in
# docs/DSL_REFERENCE.md); recognizing a shape never invents numbers.

# "EMA20 crosses above EMA50" / "EMA20 از EMA50 به (سمت) بالا کراس کرد"
_RE_EMA_CROSS = re.compile(
    r"EMA\s*(\d+)\s*(?:cross(?:es)?\s*(?:above\s*|up(?:ward)?\s*)?"
    r"|از|بالای)\s*"
    r"EMA\s*(\d+)(?:\s*(?:به\s*(?:سمت\s*)?)?"
    r"(?:بالا|upward|up|بالاتر|above))?", re.IGNORECASE)
_RE_RSI_ABOVE = re.compile(
    r"RSI\s*(?:\((\d+)\))?\s*(?:is\s+)?(?:above|over|بالای)\s*"
    r"(\d+(?:\.\d+)?)", re.IGNORECASE)
_RE_RSI_LOW = re.compile(
    r"RSI\s*(?:\((\d+)\))?\s*(?:is\s+)?low|RSI\s*(?:کم|پایین)",
    re.IGNORECASE)
_RE_SL_TP = re.compile(
    r"(?:SL|stop|حد\s*ضرر)\D{0,14}?(?P<sl>\d+(?:\.\d+)?)\s*ATR"
    r".*?(?:"
    r"(?:TP|take\s*profit|حد\s*سود|تارگت|target)\D{0,14}?"
    r"(?P<tp_a>\d+(?:\.\d+)?)\s*ATR"
    r"|(?P<tp_b>\d+(?:\.\d+)?)\s*ATR\s*(?:target|تارگت))",
    re.IGNORECASE)


@dataclass
class Interpretation:
    draft: dict                       # draft spec document (version 0)
    restatement: str
    claims: list[dict] = field(default_factory=list)
    ambiguities: list[dict] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    injection_warnings: list[dict] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def needs_review(self) -> bool:
        # an injection ATTEMPT in source text never changes the draft,
        # but it MUST be seen by the human reviewer (red-team §2/§28)
        return bool(self.ambiguities or self.unsupported
                    or self.injection_warnings)


class IStrategyInterpreter:
    """Provider-neutral interpretation contract (mission §9).  An LLM
    provider implements THIS and stays a research assistant: its output
    is a DRAFT consumed by validation + human review — it can never
    trade, never touch allocation, never modify live state."""

    name = "base"

    def interpret(self, material: ResearchMaterial,
                  *, autonomous_research: bool = False) -> Interpretation:
        raise NotImplementedError


class TemplateInterpreter(IStrategyInterpreter):
    """Deterministic EN/FA pattern interpreter (no ML, no network)."""

    name = "template-1.0"

    def interpret(self, material: ResearchMaterial, *,
                  autonomous_research: bool = False) -> Interpretation:
        # defense in depth: external text is DATA (mission §42/§67) —
        # size/binary refusals + injection attempts surfaced as data;
        # the sanitized text stays VERBATIM (provenance §13)
        sec = sanitize_external_text(material.text or "")
        text = sec["text"].translate(_DIGIT_MAP)
        ambiguities: list[dict] = []
        unsupported: list[str] = []
        assumptions: list[str] = []

        cross = _RE_EMA_CROSS.search(text)
        rsi_above = _RE_RSI_ABOVE.search(text)
        sl_tp = _RE_SL_TP.search(text)

        indicators: list[dict] = []
        long_parts: list[dict] = []
        recognized = False

        if cross:
            recognized = True
            indicators.append({"id": "ema_f", "kind": "EMA",
                               "period": int(cross.group(1)),
                               "applied": "close"})
            indicators.append({"id": "ema_s", "kind": "EMA",
                               "period": int(cross.group(2)),
                               "applied": "close"})
            long_parts.append({"cross": "ABOVE", "a": {"ind": "ema_f"},
                               "b": {"ind": "ema_s"}})
        else:
            unsupported.append(
                "EMA-cross sentence not recognized (supported: 'Buy "
                "when EMA20 crosses EMA50 upward …' / 'وقتی EMA20 از "
                "EMA50 به سمت بالا کراس کرد …')")

        restatement = ""
        if rsi_above:
            recognized = True
            period = int(rsi_above.group(1) or 14)
            thr = float(rsi_above.group(2))
            indicators.append({"id": "rsi_m", "kind": "RSI",
                               "period": period, "applied": "close"})
            long_parts.append({"left": {"ind": "rsi_m"}, "cmp": "GT",
                               "right": {"const": thr}})
            restatement += (f" Long requires RSI({period}) above "
                            f"{thr:g}.")
        elif _RE_RSI_LOW.search(text):
            # THE canonical ambiguity: a threshold is NOT invented
            recognized = True
            indicators.append({"id": "rsi_m", "kind": "RSI",
                               "period": 14, "applied": "close"})
            sym = ({"ambiguous": "rsi_threshold",
                    "range": [10.0, 40.0]}
                   if autonomous_research else
                   {"ambiguous": "rsi_threshold"})
            long_parts.append({"left": {"ind": "rsi_m"}, "cmp": "LT",
                               "right": sym})
            ambiguities.append({
                "name": "rsi_threshold", "kind": "AMBIGUOUS_PARAMETER",
                "why": "'RSI is low' has no deterministic threshold — "
                       "supply a value (or an explicit research range)",
                "range": [10.0, 40.0] if autonomous_research else None})
            restatement += (" Long requires an RSI threshold that is "
                            "AMBIGUOUS and must be supplied.")

        exit_doc: dict = {}
        if sl_tp:
            tp = sl_tp.group("tp_a") or sl_tp.group("tp_b")
            exit_doc = {"sl": {"model": "atr",
                               "mult": float(sl_tp.group("sl"))},
                        "tp": {"model": "atr", "mult": float(tp)}}
        elif recognized:
            ambiguities.append({
                "name": "stop_loss", "kind": "MISSING_SL",
                "why": "no stop-loss specified — every strategy needs "
                       "an SL (DECISIONS §4.2); supply an ATR multiple",
                "range": [1.0, 4.0] if autonomous_research else None})

        assumptions.append(
            "state entry mode with EMA-cross flip semantics unless "
            "review changes it")
        assumptions.append("market.symbol/timeframe must be chosen by "
                           "the owner (never guessed from text)")

        if recognized:
            short_cond = ({"cross": "BELOW", "a": {"ind": "ema_f"},
                           "b": {"ind": "ema_s"}} if cross else {})
            entry = {"mode": "state",
                     "long": (long_parts[0] if len(long_parts) == 1
                              else {"and": long_parts}),
                     "short": short_cond}
            restatement = ("Buy when the fast EMA crosses the slow EMA "
                           "upward." + restatement)
        else:
            # nothing recognized → NOTHING is invented: the entry is
            # empty and the draft stays non-executable (mission §10)
            entry = {"mode": "state", "long": {}, "short": {}}
            restatement = ("Could not recognize a strategy pattern in "
                           "the source text; the draft is a placeholder "
                           "and must be specified manually.")
            ambiguities.append({
                "name": "whole_rule", "kind": "UNRECOGNIZED",
                "why": "no supported sentence shape matched",
                "range": None})

        slug = re.sub(r"[^a-z0-9]+", "_", material.title.lower())[:40]
        draft = {
            "schema_version": "1.0",
            "strategy_id": f"draft_{slug.strip('_') or 'strategy'}",
            "version": 0,
            "name": material.title[:80],
            "description": (material.text or "")[:500],
            "source": material.provenance(),
            "market": {"symbol": "EURUSD", "timeframe": "H1"},
            "indicators": indicators,
            "entry": entry,
            "exit": exit_doc,
            "metadata": {"confidence": None,
                         "requires_codegen": False,
                         "missing_features": []},
        }
        return Interpretation(
            draft=draft, restatement=restatement,
            claims=extract_claims(text), ambiguities=ambiguities,
            unsupported=unsupported, assumptions=assumptions,
            injection_warnings=sec["injection_warnings"],
            confidence=0.0 if not recognized else
            (0.4 if (ambiguities or unsupported) else 0.8))
