"""mql5bot.factory.conversation — the guided (Persian) strategy dialogue.

Phase 4 of ``docs/ROADMAP_UX.md``, built OVER the existing interpreter and the
existing DSL schema parser. It turns a one-shot ``/interpret`` into a
step-by-step conversation:

    Persian text
      -> a Persian restatement (derived from the SCRUBBED draft, never echoed
         from the owner's words)
      -> a Persian QUESTION for every parameter the owner did not specify
         (naming exactly what is missing; a value is NEVER invented)
      -> the OWNER ACCEPTS THE RESTATEMENT (required — see below)
      -> the DSL schema/parse check (structure only)
      -> a plain-Persian verdict naming the reason it passed or failed.

ACCEPTANCE IS REQUIRED. The restatement exists to catch a misinterpretation
BEFORE anything proceeds; one that nobody has to agree with is decoration.
``validate()`` therefore REFUSES any draft that has not been accepted, even a
draft with no ambiguities (no ambiguity is not the same as agreement). The
acceptance is bound to the draft's CONTENT via :func:`acceptance_token`, so
accepting one restatement never carries over to a draft that has since changed:
the owner echoes back the token they were shown in :class:`ConversationStep`,
and a token computed over any other draft is rejected.

HARD BOUNDARY — the flow ENDS at SCHEMA VALIDATION. The only Python check that
runs here is the DSL schema/parse gate: it proves the draft is well-formed. It
is NOT a test of the strategy — no backtest, no robustness check, no
out-of-sample test, no market data at all. Nothing in this module promotes a
strategy toward MetaTrader or a live account: it never calls a lifecycle
transition and never names an execution state (SHADOW/DEMO/LIVE_SMALL/LIVE).
Two things that have NOT happened yet are surfaced as EXPLICIT, not-yet-done
steps (:data:`REMAINING_AFTER_SCHEMA`): (a) the Python research validation —
backtest, robustness, out-of-sample — which needs market data and has not run;
(b) the owner-run 11-stage MT5 certification gate. A test pins that no
execution state is reachable from here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..dsl import parse_spec
from ..dsl.errors import DslError
from .interpreter import select_interpreter
from .providers import ResearchMaterial


def acceptance_token(draft: Mapping[str, object]) -> str:
    """A stable content fingerprint of the draft the owner is shown alongside
    the restatement. The owner accepts a restatement by echoing this token
    back to :meth:`GuidedConversation.validate`. Because it is computed over the
    draft's canonical content, acceptance of one restatement cannot validate a
    draft that has since changed — a different draft yields a different token."""
    canonical = json.dumps(draft, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

# The two things that remain AFTER the schema check — shown to the owner as
# explicit, not-yet-done steps. Neither is taken here.
REMAINING_AFTER_SCHEMA: tuple[str, ...] = (
    ("Python research validation — backtest, robustness, out-of-sample — "
     "needs market data, NOT run here"),
    "11-stage MT5 certification gate — owner-run, NOT yet passed",
)

# One Persian question per ambiguity kind. Each NAMES what was not specified
# and asks for it; none fills a value in.
_QUESTION_FA: dict[str, str] = {
    "AMBIGUOUS_PARAMETER": "مقدار «{name}» را مشخص نکردید — چه عددی می‌خواهید؟",
    "MISSING_SL": "حد ضرر (stop-loss) را مشخص نکردید — چه فاصله‌ای باشد؟",
    "MISSING_TP": "حد سود (take-profit) را مشخص نکردید — چه فاصله‌ای باشد؟",
    "UNRESOLVED_MARKET": "نماد و تایم‌فریم را مشخص کنید (symbol / timeframe).",
    "UNRECOGNIZED": "الگوی استراتژی را نشناختم — کمی واضح‌تر توصیف کنید.",
}


@dataclass
class ConversationStep:
    """The result of interpreting one message. When ``needs_answers`` is true
    the owner must answer ``questions`` (or refine the text) before the strategy
    can be validated — the conversation never proceeds on an invented value."""

    restatement: str
    questions: list[str]
    draft: dict
    ambiguities: list[dict]
    needs_answers: bool
    # the token the owner echoes back to accept THIS restatement; bound to the
    # draft's content so it cannot accept a draft that has since changed.
    acceptance_token: str = ""
    remaining_after_schema: tuple[str, ...] = REMAINING_AFTER_SCHEMA


@dataclass
class ConversationVerdict:
    """The result of the DSL schema/parse check — a pass or a fail WITH its
    reason, plus the explicit not-yet-done remainder. A pass means the draft is
    well-formed, NOT that the strategy was tested."""

    passed: bool
    verdict_fa: str
    reason: str
    remaining_after_schema: tuple[str, ...] = REMAINING_AFTER_SCHEMA
    ambiguities: list[dict] = field(default_factory=list)


def _question_for(amb: Mapping[str, object]) -> str:
    kind = str(amb.get("kind", "UNRECOGNIZED"))
    name = str(amb.get("name", "") or "?")
    template = _QUESTION_FA.get(kind, _QUESTION_FA["UNRECOGNIZED"])
    try:
        return template.format(name=name)
    except (KeyError, IndexError):
        return template


class GuidedConversation:
    """Drive the guided dialogue over the existing interpreter + DSL parser.

    ``interpreter`` selects the intake (``"auto"``/``"template"``/``"llm"``,
    exactly like ``POST /interpret``); the default deterministic template needs
    no provider and no network.
    """

    def __init__(self, *, interpreter: str = "auto",
                 provider: str = "", model: str = "") -> None:
        self._prefer = interpreter
        self._provider = provider
        self._model = model

    def start(self, text: str, *, symbol: str = "",
              timeframe: str = "") -> ConversationStep:
        text = text or ""
        title = text.splitlines()[0][:80] if text.strip() else ""
        material = ResearchMaterial("USER_TEXT", title, text)
        # §6: the market is NEVER guessed — only used when BOTH are supplied.
        market = ({"symbol": symbol, "timeframe": timeframe}
                  if symbol and timeframe else None)
        choice = select_interpreter(prefer=self._prefer,
                                    provider=self._provider or None,
                                    model=self._model or None)
        interp = choice.interpreter.interpret(material, market=market)
        questions = [_question_for(a) for a in interp.ambiguities]
        draft = dict(interp.draft)
        return ConversationStep(
            restatement=interp.restatement,
            questions=questions,
            draft=draft,
            ambiguities=[dict(a) for a in interp.ambiguities],
            needs_answers=bool(interp.ambiguities),
            acceptance_token=acceptance_token(draft),
        )

    def validate(self, draft: Mapping[str, object], *,
                 accepted_token: str | None = None) -> ConversationVerdict:
        """Run the DSL schema/parse check on an ACCEPTED draft — the SAME check
        ``gate0_schema`` consumes. This proves the draft is well-formed; it is
        NOT a test of the strategy (no backtest, robustness or out-of-sample,
        no market data). A pass or a fail — with the reason — is the answer;
        nothing is promoted.

        Acceptance is REQUIRED: ``accepted_token`` must equal
        :func:`acceptance_token` for THIS draft (the token the owner was shown
        with the restatement). A missing or mismatched token — including a
        token accepted for a now-changed draft — is REFUSED, not warned. A draft
        with no ambiguities is refused too: no ambiguity is not agreement."""
        expected = acceptance_token(draft)
        if accepted_token != expected:
            return ConversationVerdict(
                passed=False,
                verdict_fa=(
                    "بازنویسی تأیید نشده است — پیش از اعتبارسنجی، بازنویسی را "
                    "تأیید کنید / RESTATEMENT NOT CONFIRMED — accept the "
                    "restatement before validation"),
                reason=(
                    "the restatement was not accepted for this draft; "
                    "acceptance is required and is bound to the draft content "
                    "the owner saw (a token accepted for a different or changed "
                    "draft does not carry over)"))
        # The headline names EXACTLY what ran and what did not, in both
        # languages — never rely on the reason field to carry the qualifier.
        fail_headline = (
            "بررسی شِمای طرح رد شد — ساختار طرح نامعتبر است / "
            "SCHEMA CHECK FAILED — the draft's structure is invalid")
        try:
            parse_spec(dict(draft, version=0))
        except DslError as exc:
            return ConversationVerdict(
                passed=False, verdict_fa=fail_headline,
                reason=f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 — any parse failure is a FAIL
            return ConversationVerdict(
                passed=False, verdict_fa=fail_headline,
                reason=f"{type(exc).__name__}: {exc}")
        return ConversationVerdict(
            passed=True,
            verdict_fa=(
                "شِمای طرح معتبر است — فقط بررسی ساختار؛ "
                "استراتژی هنوز آزمایش نشده / "
                "SCHEMA-VALIDATED — structure only; "
                "the strategy has NOT been tested"),
            reason=(
                "draft parses and satisfies the DSL schema at version 0; "
                "no backtest, robustness or out-of-sample validation has run "
                "(those need market data)"))


__all__ = [
    "REMAINING_AFTER_SCHEMA",
    "ConversationStep",
    "ConversationVerdict",
    "GuidedConversation",
    "acceptance_token",
]
