"""mql5bot.factory.conversation — the guided (Persian) strategy dialogue.

Phase 4 of ``docs/ROADMAP_UX.md``, built OVER the existing interpreter and the
existing DSL schema parser. It turns a one-shot ``/interpret`` into a
step-by-step conversation:

    Persian text
      -> a Persian restatement (derived from the SCRUBBED draft, never echoed
         from the owner's words)
      -> a Persian QUESTION for every parameter the owner did not specify
         (naming exactly what is missing; a value is NEVER invented)
      -> the DSL schema/parse check (structure only)
      -> a plain-Persian verdict naming the reason it passed or failed.

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

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..dsl import parse_spec
from ..dsl.errors import DslError
from .interpreter import select_interpreter
from .providers import ResearchMaterial

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
        return ConversationStep(
            restatement=interp.restatement,
            questions=questions,
            draft=dict(interp.draft),
            ambiguities=[dict(a) for a in interp.ambiguities],
            needs_answers=bool(interp.ambiguities),
        )

    def validate(self, draft: Mapping[str, object]) -> ConversationVerdict:
        """Run the DSL schema/parse check on a confirmed draft — the SAME check
        ``gate0_schema`` consumes. This proves the draft is well-formed; it is
        NOT a test of the strategy (no backtest, robustness or out-of-sample,
        no market data). A pass or a fail — with the reason — is the answer;
        nothing is promoted."""
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
]
