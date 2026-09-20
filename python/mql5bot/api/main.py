"""Operator UI/API (mission §57-§59/§78/§80): FastAPI + Jinja2 +
HTMX.  NO React.  Every promotion goes through an EXPLICIT approval
button carrying actor + reason; the UI can never mark a strategy LIVE
(§73: enforced by source-scan test) and can never skip lifecycle
stages — it may only request the NEXT legal transition, which the
factory store re-validates server-side (state machine + evidence
gates + human approval).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import urllib.request
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from ..backtest import run_backtest
from ..data import load_csv
from ..discovery.safety import AllocationCircuitBreaker, KillSwitch
from ..dsl import desired_positions, parse_spec
from ..factory import lifecycle as lc
from ..factory.conversation import GuidedConversation
from ..factory.interpreter import restate_from_draft
from ..factory.models import StrategyVersion, ValidationRun
from ..factory.store import FactoryStore, StoreError
from ..i18n import explain_status, isolate_ltr
from ..status import EMPIRICAL_VALIDATION_PENDING, certify_status_model
from .auth import (
    ENV_CONSOLE_TOKEN,
    SESSION_COOKIE,
    session_valid,
    session_value,
    token_matches,
)

# Console data-source configuration — environment variable NAMES (the console
# never renders a value, only whether the name is set).
ENV_TELEMETRY_URL = "MQL5BOT_TELEMETRY_URL"      # the telemetry bridge base URL
ENV_TELEMETRY_LOG = "MQL5BOT_TELEMETRY_LOG"      # the bridge's JSONL file
ENV_EVIDENCE_DIR = "MQL5BOT_EVIDENCE_DIR"        # an owner gate evidence dir
ENV_CONSOLE_DATASET = "MQL5BOT_CONSOLE_DATASET"  # CSV for Python validation

# The six console sections. English default of the EXISTING routes is
# untouched; these drive the shared shell of the NEW pages.
_NAV = (
    ("home", "/", "Home", "خانه / home"),
    ("strategies", "/strategies", "Strategies", "استراتژی‌ها"),
    ("new", "/new", "New strategy", "استراتژی جدید"),
    ("trades", "/trades", "Trades", "معاملات"),
    ("certification", "/certification", "Certification", "گواهی"),
    ("settings", "/settings", "Settings", "تنظیمات"),
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

KANBAN_COLUMNS = ("Inbox", "PARSED", "VALIDATED", "BACKTESTED",
                  "ROBUSTNESS_PASS", "OOS_SURVIVOR", "SHADOW", "DEMO",
                  "LIVE_SMALL", "LIVE", "DEGRADED", "PAUSED", "RETIRED",
                  "REJECTED")

# §73/§59: the UI may request at most the NEXT transition, and only
# the human-approval-gated ones are surfaced as buttons.  LIVE is
# deliberately absent — live activation is owner-only (MT5 phase).
UI_PROPOSABLE = {"SHADOW": "DEMO", "DEMO": "LIVE_SMALL"}


class SafetyHub:
    """Process-wide safety singletons exposed to routes (the kill
    switch itself stays independent — the UI only views/resets it)."""

    def __init__(self, kill_switch: KillSwitch,
                 breaker: AllocationCircuitBreaker):
        self.kill_switch = kill_switch
        self.breaker = breaker
        self.watchdog_alerts: list[dict] = []



# §52 one-click research: the console creates the campaign; actual
# research execution is injected (deterministic pipeline runner) — with
# no runner the campaign is stored PAUSED and the UI says so plainly
# (never a silent fake "research done").


def _persian_board_context(ks: KillSwitch,
                           live_state: Callable[[], object] | None) -> dict:
    """Build the Persian RTL status page context. The traffic light and the
    'not yet proven' line are sourced from the real kill-switch and status
    model — never hardcoded. Latin identifiers are bidi-isolated so they stay
    readable and copyable inside the Persian text."""
    state = ks.state.value
    if state == "EMERGENCY_HALT":
        light_class, headline = "red", "سیستم متوقف است."
    elif state == "NO_NEW_TRADES":
        light_class, headline = "amber", "معامله‌ی جدید متوقف است؛ سیستم در حال پایش است."
    else:
        light_class, headline = "green", "سیستم فعال است و در محدوده‌ی ریسک کار می‌کند."
    # nothing here is VERIFIED — the real status model says so, in its words
    cs = certify_status_model(EMPIRICAL_VALIDATION_PENDING, 0, 0)
    if live_state is not None:
        s = live_state()
        if not getattr(s, "alive", True):
            light_class, headline = "red", "سیستم پاسخ نمی‌دهد."
        alive_fa = "بله" if getattr(s, "alive", False) else "خیر"
        activity_fa = (f"{s.trades_today} معامله / trades، "
                       f"P&L {s.realised_pnl_today}")
        distance_fa = f"{s.drawdown_distance_pct} pct"
    else:
        alive_fa = activity_fa = distance_fa = "بی‌اتصال / not connected"
    return {
        "light_class": light_class,
        "headline_fa": headline,
        "alive_fa": alive_fa,
        "activity_fa": activity_fa,
        "distance_fa": distance_fa,
        "unproven_reason": cs["reason"],
        "status_explained": explain_status(cs["status"], "fa"),
        "mt5_explained": explain_status(cs["mt5_status"], "fa"),
        "kill_switch": isolate_ltr(state),
        "kill_reason": isolate_ltr(ks.reason) if ks.reason else "",
    }


def create_app(store: FactoryStore, safety: SafetyHub | None = None,
               *, score_fn: Callable[[str], dict] | None = None,
               research_runner: Callable[[dict], dict] | None = None,
               campaign_query: Callable[[], list[dict]] | None = None,
               live_state: Callable[[], object] | None = None,
               console_token: str | None = None,
               console_env: dict | None = None
               ) -> FastAPI:
    app = FastAPI(title="AEGIS Governance Console", version="1.0")
    env = Environment(autoescape=True,
                      loader=FileSystemLoader(str(TEMPLATES_DIR)))
    templates = Jinja2Templates(env=env)
    safety = safety or SafetyHub(KillSwitch(), AllocationCircuitBreaker())
    cenv = os.environ if console_env is None else console_env

    # ---- authentication (opt-in via MQL5BOT_CONSOLE_TOKEN) ------------------
    # With no token configured the console runs in trusted loopback-only mode
    # (the runner refuses any non-loopback bind in that mode). With a token,
    # EVERY route except /login requires the signed session cookie. The token
    # is never logged and never rendered.
    _token = (console_token if console_token is not None
              else cenv.get(ENV_CONSOLE_TOKEN, ""))
    auth_enabled = bool(_token)

    @app.middleware("http")
    async def _require_session(request: Request, call_next):
        if (auth_enabled and request.url.path not in ("/login", "/logout")
                and not session_valid(
                    request.cookies.get(SESSION_COOKIE), _token)):
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        lang = "fa" if request.query_params.get("lang") == "fa" else "en"
        return templates.TemplateResponse(request, "login.html",
                                          {"lang": lang, "error": ""})

    @app.post("/login")
    def login_submit(request: Request, token: str = Form("")):
        # constant-time check (both sides hashed — length does not leak)
        if auth_enabled and token_matches(token, _token):
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(SESSION_COOKIE, session_value(_token),
                            httponly=True, samesite="lax")
            return resp
        lang = "fa" if request.query_params.get("lang") == "fa" else "en"
        return templates.TemplateResponse(
            request, "login.html",
            {"lang": lang,
             "error": "توکن نادرست است / wrong token"},
            status_code=403)

    @app.get("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # ---- shared shell context for the NEW console pages --------------------
    def _shell_ctx(request: Request, section: str) -> dict:
        lang = "fa" if request.query_params.get("lang") == "fa" else "en"
        cs = certify_status_model(EMPIRICAL_VALIDATION_PENDING, 0, 0)
        nav = [{"href": href,
                "label": label_fa if lang == "fa" else label_en,
                "current": key == section}
               for key, href, label_en, label_fa in _NAV]
        return {"lang": lang, "nav_items": nav, "auth_enabled": auth_enabled,
                "unproven_reason": cs["reason"],
                "unproven_status": explain_status(cs["status"], lang)}

    def _strategy_rows() -> list[dict]:
        rows = []
        for s in store.list_strategies():
            rows.append({
                "strategy_id": s["strategy_id"], "state": s["state"],
                "version": s.get("version"),
                "score": score_fn(s["strategy_id"]) if score_fn
                else None})
        return rows

    @app.get("/", response_class=HTMLResponse)
    def board(request: Request):
        rows = _strategy_rows()
        columns = []
        for col in KANBAN_COLUMNS:
            cards = [r for r in rows
                     if (col == "Inbox" and r["state"] == "DRAFT")
                     or r["state"] == col]
            columns.append({"name": col, "cards": cards})
        ks = safety.kill_switch
        ctx = {
            "columns": columns,
            "kill_switch": ks.state.value,
            "kill_reason": ks.reason,
            "breaker_frozen": safety.breaker.st.frozen,
            "alerts": safety.watchdog_alerts[-10:],
        }
        # Persian RTL phone-first status page is OPT-IN (?lang=fa); the English
        # default (board.html) is byte-identical and unchanged.
        if request.query_params.get("lang") == "fa":
            ctx.update(_persian_board_context(ks, live_state))
            return templates.TemplateResponse(request, "board_fa.html", ctx)
        return templates.TemplateResponse(request, "board.html", ctx)

    @app.get("/strategies/{sid}", response_class=HTMLResponse)
    def strategy_detail(request: Request, sid: str):
        try:
            state = store.current_state(sid)
        except StoreError:
            raise HTTPException(404, "unknown strategy") from None
        history = [{"from": e.from_state, "to": e.to_state,
                    "kind": e.kind, "actor": e.actor,
                    "reason": e.reason, "ts": str(e.created_at)}
                   for e in store.history(sid)]
        proposable = UI_PROPOSABLE.get(state)
        return templates.TemplateResponse(request, "strategy.html", {
            "sid": sid, "state": state, "history": history,
            "proposable": proposable,
            "score": score_fn(sid) if score_fn else None,
            "error": None})

    @app.post("/approvals")
    def approve(sid: str = Form(...), decision: str = Form(...),
                actor: str = Form(...), reason: str = Form(...),
                evidence: str = Form(""), version: int = Form(0)):
        """§32 structured approval.  The UI NEVER targets LIVE (§73)
        and never skips stages: the target must be the UI-proposable
        next state, and store.transition re-validates the state
        machine, the evidence binding and the human-approval flag."""
        try:
            state = store.current_state(sid)
        except StoreError:
            raise HTTPException(404, "unknown strategy") from None
        target = UI_PROPOSABLE.get(state or "")
        if target is None:
            raise HTTPException(409, f"no UI-proposable transition from "
                                     f"{state!r}")
        if target == "LIVE" or decision not in ("APPROVED", "DENIED"):
            raise HTTPException(422, "invalid decision target")
        if not reason.strip() or not actor.strip():
            raise HTTPException(422, "approval requires actor + reason")
        version_no = version or _current_version(store, sid)
        refs = tuple(r.strip() for r in evidence.split(",") if r.strip())
        if decision == "DENIED":
            # a denial is recorded as an oversight event, never a state
            # change: refusals must be visible without mutating status
            store.alert("APPROVAL_DENIED", severity="INFO",
                        strategy_id=sid, message=f"{actor}: {reason}")
            return RedirectResponse(f"/strategies/{sid}", status_code=303)
        try:
            store.transition(sid, version_no, target, evidence_refs=refs,
                             actor=f"ui:{actor}", reason=reason,
                             human_approval=True)
        except StoreError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/strategies/{sid}", status_code=303)

    # ---------------------------------------- §52 one-click research
    MAX_RUNNING_CAMPAIGNS = 3   # §82: global research concurrency cap

    @app.post("/interpret")
    def interpret_idea(idea: str = Form(...), source: str = Form(""),
                       symbol: str = Form(""), timeframe: str = Form(""),
                       interpreter: str = Form("auto"),
                       provider: str = Form(""), model: str = Form(""),
                       autonomous: bool = Form(False)):
        """NL idea → draft interpretation (§9/§10). The operator picks the
        interpreter; with NO API key configured this defaults to the
        deterministic template and says so in ``interpreter_note``. The
        draft is version 0 — no execution authority, no allocation, no
        live state — and the market is only ever the explicit selection
        passed here (§6: never guessed)."""
        from ..factory.interpreter import select_interpreter
        from ..factory.providers import ResearchMaterial
        if not idea.strip():
            raise HTTPException(422, "idea is required")
        if interpreter not in ("auto", "template", "llm"):
            raise HTTPException(422, "interpreter must be auto|template|llm")
        text = source.strip() or idea.strip()
        mat = ResearchMaterial("USER_TEXT", idea.strip().splitlines()[0][:80],
                               text)
        market = ({"symbol": symbol.strip(), "timeframe": timeframe.strip()}
                  if symbol.strip() and timeframe.strip() else None)
        choice = select_interpreter(prefer=interpreter,
                                    provider=provider or None,
                                    model=model or None)
        try:
            r = choice.interpreter.interpret(
                mat, autonomous_research=autonomous, market=market)
        except Exception as e:  # noqa: BLE001 — HTTP boundary: a bad idea
            # text is a 422, never an unhandled 500
            raise HTTPException(422, f"unprocessable idea text: {e}") from None
        return JSONResponse({
            "interpreter": r.interpreter or choice.name,
            "interpreter_note": choice.note,
            "is_llm": choice.is_llm,
            "notes": r.notes,
            "restatement": r.restatement,
            "draft": r.draft,
            "ambiguities": r.ambiguities,
            "unsupported": r.unsupported,
            "assumptions": r.assumptions,
            "injection_warnings": r.injection_warnings,
            "confidence": r.confidence,
            "needs_review": r.needs_review})

    @app.post("/campaigns")
    def create_campaign(request: Request, idea: str = Form(...),
                        source: str = Form(""),
                        dataset: str = Form("synthetic-default"),
                        symbol: str = Form(""),
                        timeframe: str = Form(""),
                        actor: str = Form(...)):
        """One-click research intake (§52/§54): idea + optional source +
        dataset → interpreted draft (deterministic template; LLM
        optional) → registered campaign with declared budgets.  The
        campaign NEVER trades; live promotion stays OFF by default."""
        from ..discovery.candidates import doc_hash
        from ..factory.models import DiscoveryCampaign
        if not idea.strip() or not actor.strip():
            raise HTTPException(422, "idea and actor are required")
        # §6: the market is NEVER guessed. When a research runner is
        # attached this campaign will build an EXECUTABLE research spec,
        # so an explicit symbol + timeframe are required up front (fail
        # closed). With no runner the campaign is only staged (PAUSED) and
        # the market may be supplied later at execution wiring.
        market = ({"symbol": symbol.strip(), "timeframe": timeframe.strip()}
                  if symbol.strip() and timeframe.strip() else None)
        if research_runner is not None and market is None:
            raise HTTPException(
                422, "symbol and timeframe are required to run research "
                "(the market is never guessed from the idea — §6)")
        campaign_id = f"camp_{doc_hash({'idea': idea, 'ts_actor': actor})[:12]}"
        manifest = {"hypothesis": idea.strip()[:200],
                    "source_text_hash": doc_hash({"text": source})
                    if source.strip() else "",
                    "dataset": dataset,
                    "market": market,
                    "budgets": {"stage1_single_indicator": 12,
                                "stage2_two_factor": 24,
                                "stage3_multi_factor": 12,
                                "stage5_mutations": 10},
                    "autonomy": "RESEARCH_AUTOMATION"}
        with store.session() as sess:
            exists = sess.query(DiscoveryCampaign).filter_by(
                campaign_id=campaign_id).one_or_none()
            if exists is None:
                running = sess.query(DiscoveryCampaign).filter_by(
                    status="RUNNING").count()
                if running >= MAX_RUNNING_CAMPAIGNS:
                    raise HTTPException(
                        429, f"{running} campaigns already RUNNING "
                        f"(cap {MAX_RUNNING_CAMPAIGNS}); pause or "
                        f"complete one first")
                sess.add(DiscoveryCampaign(
                    campaign_id=campaign_id, name=idea.strip()[:120],
                    stage="stage1_single_indicator",
                    status="RUNNING" if research_runner else "PAUSED",
                    budget=manifest["budgets"], progress={},
                    manifest=manifest,
                    manifest_hash=doc_hash(manifest),
                    dataset_hash=doc_hash({"dataset": dataset})))
                sess.commit()
        if research_runner is not None:
            research_runner({"campaign_id": campaign_id,
                             "manifest": manifest})
        return RedirectResponse("/research", status_code=303)

    @app.get("/research", response_class=HTMLResponse)
    def research_page(request: Request):
        if campaign_query is not None:
            campaigns = campaign_query()
        else:
            from ..factory.models import DiscoveryCampaign
            with store.session() as sess:
                campaigns = [{"campaign_id": c.campaign_id,
                              "name": c.name, "stage": c.stage,
                              "status": c.status,
                              "dataset_hash": c.dataset_hash}
                             for c in sess.query(
                                 DiscoveryCampaign)
                             .order_by(DiscoveryCampaign.id.desc())
                             .limit(50)]
        return templates.TemplateResponse(request, "research.html", {
            "campaigns": campaigns,
            "runner_configured": research_runner is not None})

    # --------------------------------------- §55 lifecycle operations
    # The console may request only lifecycle-legal, NON-execution
    # operations.  PAUSE/RESUME/RETIRE route through the SAME store
    # boundary (state machine + reason); there is still NO order
    # endpoint anywhere in the Factory.
    @app.post("/strategies/{sid}/pause")
    def pause_strategy(sid: str, actor: str = Form(...),
                       reason: str = Form(...)):
        _require(sid)
        store.transition(sid, _current_version(store, sid), "PAUSED",
                         actor=f"ui:{actor}", reason=reason,
                         human_approval=True)
        return RedirectResponse(f"/strategies/{sid}", status_code=303)

    @app.post("/strategies/{sid}/retire")
    def retire_strategy(sid: str, actor: str = Form(...),
                        reason: str = Form(...)):
        _require(sid)
        store.transition(sid, _current_version(store, sid), "RETIRED",
                         actor=f"ui:{actor}", reason=reason,
                         human_approval=True)
        return RedirectResponse(f"/strategies/{sid}", status_code=303)

    @app.post("/strategies/{sid}/resume")
    def resume_strategy(sid: str, actor: str = Form(...),
                        reason: str = Form(...)):
        """Resume is RECOVERY: only legal where the state machine allows
        it (PAUSED → prior observed state); requalification rules still
        apply upstream — the UI cannot shortcut decay governance."""
        _require(sid)
        cur = store.current_state(sid)
        target = {"PAUSED": "SHADOW"}.get(cur)
        if target is None:
            raise HTTPException(409, f"no resume path from {cur!r}")
        store.transition(sid, _current_version(store, sid), target,
                         actor=f"ui:{actor}", reason=reason,
                         human_approval=True)
        return RedirectResponse(f"/strategies/{sid}", status_code=303)

    @app.get("/strategies/{sid}/trail")
    def strategy_trail(sid: str):
        """§73: the complete audit trail (source, claims, versions,
        evidence runs, lifecycle events, promotion decisions) — read
        only, straight from the store reconstruction."""
        _require(sid)
        return store.reconstruct(sid)

    @app.get("/campaigns/{campaign_id}")
    def campaign_detail(campaign_id: str):
        from ..factory.models import DiscoveryCampaign
        with store.session() as sess:
            row = sess.query(DiscoveryCampaign).filter_by(
                campaign_id=campaign_id).one_or_none()
        if row is None:
            raise HTTPException(404, "unknown campaign")
        return {"campaign_id": row.campaign_id, "name": row.name,
                "stage": row.stage, "status": row.status,
                "budget": row.budget, "progress": row.progress,
                "manifest": row.manifest,
                "manifest_hash": row.manifest_hash,
                "dataset_hash": row.dataset_hash,
                "policy_hash": row.policy_hash}

    @app.get("/allocation")
    def allocation_view():
        """§55: the current allocation view is READ-ONLY — the console
        displays what the governor decided; it never sets risk."""
        return {"kill_switch": safety.kill_switch.state.value,
                "breaker_frozen": safety.breaker.st.frozen,
                "last_safe_allocation": safety.breaker.st.last_safe,
                "note": ("allocation authority: governor→Meta→Risk; "
                         "the console can only look; it never sets "
                         "risk")}

    def _require(sid: str) -> None:
        try:
            store.current_state(sid)
        except StoreError:
            raise HTTPException(404, "unknown strategy") from None

    @app.get("/safety", response_class=HTMLResponse)
    def safety_page(request: Request):
        ks = safety.kill_switch
        return templates.TemplateResponse(request, "safety.html", {
            "kill_switch": ks.state.value, "kill_reason": ks.reason,
            "kill_history": ks.history[-20:],
            "breaker_frozen": safety.breaker.st.frozen,
            "breaker_reason": safety.breaker.st.last_reason,
            "alerts": safety.watchdog_alerts[-20:]})

    @app.post("/safety/killswitch/reset")
    def killswitch_reset(actor: str = Form(...),
                         reason: str = Form(...)):
        """§42: explicit, audited reset — the ONLY path out of
        EMERGENCY_HALT; requires actor + reason."""
        if not actor.strip() or not reason.strip():
            raise HTTPException(422, "reset requires actor + reason")
        safety.kill_switch.explicit_reset(actor, reason)
        return RedirectResponse("/safety", status_code=303)

    # -- guided strategy conversation (Phase 4 of docs/ROADMAP_UX.md) --------
    # A step-by-step dialogue over the interpreter + DSL parser. The flow ENDS
    # at SCHEMA VALIDATION (a well-formedness check, NOT a test of the
    # strategy): neither endpoint promotes a strategy toward MT5 or a live
    # account, and the two not-yet-done steps — the Python research validation
    # and the owner-run 11-stage MT5 gate — are surfaced explicitly.
    @app.post("/guided/start")
    def guided_start(idea: str = Form(...), symbol: str = Form(""),
                     timeframe: str = Form(""),
                     interpreter: str = Form("auto")):
        if not idea.strip():
            raise HTTPException(422, "idea is required")
        if interpreter not in {"auto", "template", "llm"}:
            raise HTTPException(422, "interpreter must be auto|template|llm")
        conv = GuidedConversation(interpreter=interpreter)
        step = conv.start(idea, symbol=symbol.strip(),
                          timeframe=timeframe.strip())
        return JSONResponse({
            "restatement": step.restatement,
            "questions": step.questions,
            "draft": step.draft,
            "ambiguities": step.ambiguities,
            "needs_answers": step.needs_answers,
            # the owner echoes this back as `accepted_token` to /guided/validate
            "acceptance_token": step.acceptance_token,
            "remaining_after_schema": list(step.remaining_after_schema),
        })

    @app.post("/guided/validate")
    def guided_validate(draft: str = Form(...),
                        accepted_token: str = Form("")):
        try:
            doc = json.loads(draft)
        except (ValueError, TypeError):
            raise HTTPException(422, "draft must be a JSON object") from None
        if not isinstance(doc, dict):
            raise HTTPException(422, "draft must be a JSON object")
        # Acceptance is REQUIRED and bound to the draft content: an unaccepted
        # (or mismatched) draft is REFUSED by validate(), never validated.
        verdict = GuidedConversation().validate(
            doc, accepted_token=accepted_token or None)
        return JSONResponse({
            "passed": verdict.passed,
            "verdict_fa": verdict.verdict_fa,
            "reason": verdict.reason,
            "remaining_after_schema": list(verdict.remaining_after_schema),
        })

    # ---- console v2 sections (new pages; the legacy routes are untouched) --
    LADDER = ("DRAFT", "PARSED", "VALIDATED", "BACKTESTED",
              "ROBUSTNESS_PASS", "OOS_SURVIVOR", "SHADOW", "DEMO",
              "LIVE_SMALL", "LIVE")

    def _why_here(sid: str) -> str:
        """WHY a strategy is in its current state: the last lifecycle event's
        evidence or refusal, from the store — never invented."""
        events = store.history(sid)
        if not events:
            return "registered as a draft; no lifecycle events yet"
        ev = events[-1]
        parts = [f"{ev.kind}: {ev.from_state} → {ev.to_state} by {ev.actor}"]
        if ev.evidence_refs:
            parts.append(f"evidence {list(ev.evidence_refs)}")
        if ev.reason:
            parts.append(str(ev.reason))
        return " — ".join(parts)

    @app.get("/strategies", response_class=HTMLResponse)
    def strategies_page(request: Request):
        rows = []
        for s in store.list_strategies():
            state = s["state"]
            rows.append({
                "strategy_id": s["strategy_id"],
                "version": s.get("version"),
                "state": state,
                "state_index": LADDER.index(state) if state in LADDER else -1,
                "why": _why_here(s["strategy_id"]),
            })
        ctx = _shell_ctx(request, "strategies")
        ctx.update({"strategies": rows, "ladder": LADDER})
        return templates.TemplateResponse(request, "strategies_list.html", ctx)

    def _latest_version_row(sid: str):
        with store.session() as sess:
            return (sess.query(StrategyVersion)
                    .filter_by(strategy_id=sid)
                    .order_by(StrategyVersion.version.desc()).first())

    @app.get("/strategy/{sid}", response_class=HTMLResponse)
    def strategy_console_detail(request: Request, sid: str):
        try:
            state = store.current_state(sid)
        except StoreError:
            raise HTTPException(404, "unknown strategy") from None
        row = _latest_version_row(sid)
        doc = json.loads(row.spec_json) if row else None
        restatement = restate_from_draft(doc) if doc else ""
        timeline = [{
            "from_state": ev.from_state, "to_state": ev.to_state,
            "kind": ev.kind, "actor": ev.actor, "reason": ev.reason,
            "evidence_refs": list(ev.evidence_refs or []),
            "created_at": str(ev.created_at),
        } for ev in store.history(sid)]
        with store.session() as sess:
            runs = [{"id": r.id, "run_type": r.run_type, "status": r.status,
                     "finished_at": str(r.finished_at or "")}
                    for r in sess.query(ValidationRun)
                    .filter_by(strategy_id=sid)
                    .order_by(ValidationRun.id.desc()).limit(20)]
        # Only the actions the lifecycle actually permits from this state —
        # pause / retire / resume; never anything toward execution.
        allowed = []
        if lc.PAUSED in lc.FAILURES.get(state, ()):
            allowed.append("pause")
        if state in lc.RECOVERIES:
            allowed.append("resume")
        if state in lc.OBSERVATION_STATES:
            allowed.append("retire")
        ctx = _shell_ctx(request, "strategies")
        ctx.update({
            "sid": sid, "state": state,
            "version": row.version if row else 0,
            "state_index": LADDER.index(state) if state in LADDER else -1,
            "ladder": LADDER,
            "original_text": store.original_text(sid) or "",
            "restatement": restatement,
            "timeline": timeline, "runs": runs,
            "allowed_actions": allowed,
            "refusal": request.query_params.get("refused", ""),
            "dataset_configured": bool(cenv.get(ENV_CONSOLE_DATASET, "")),
        })
        return templates.TemplateResponse(request, "strategy_detail.html", ctx)

    @app.post("/guided/register")
    def guided_register(draft: str = Form(...),
                        accepted_token: str = Form(""),
                        original_text: str = Form("")):
        """Register an ACCEPTED, schema-valid draft as version 0 → DRAFT.
        Nothing beyond DRAFT is reachable from this endpoint."""
        try:
            doc = json.loads(draft)
        except (ValueError, TypeError):
            raise HTTPException(422, "draft must be a JSON object") from None
        if not isinstance(doc, dict):
            raise HTTPException(422, "draft must be a JSON object")
        verdict = GuidedConversation().validate(
            doc, accepted_token=accepted_token or None)
        if not verdict.passed:
            return JSONResponse({"registered": False,
                                 "verdict_fa": verdict.verdict_fa,
                                 "reason": verdict.reason}, status_code=422)
        spec = parse_spec(dict(doc, version=0))
        _vid, created = store.register_strategy(
            spec, created_by="ui:console-conversation",
            source={"type": "USER_TEXT"},
            original_text=original_text or None)
        return JSONResponse({
            "registered": True, "created": created,
            "strategy_id": spec.strategy_id,
            "state": store.current_state(spec.strategy_id),
        })

    @app.post("/strategy/{sid}/validate-python")
    def validate_python(sid: str):
        """Run the existing backtest on the configured dataset and RECORD the
        result via store.record_run — honestly, never advancing the lifecycle
        state. With no dataset configured, nothing runs and the reply says
        exactly what is missing."""
        ds = cenv.get(ENV_CONSOLE_DATASET, "")
        if not ds:
            return JSONResponse({
                "ran": False,
                "detail": ("no dataset configured — set "
                           f"{ENV_CONSOLE_DATASET} to a CSV of OHLC bars "
                           "to enable the backtest; nothing was run")})
        try:
            state_before = store.current_state(sid)
        except StoreError:
            raise HTTPException(404, "unknown strategy") from None
        row = _latest_version_row(sid)
        if row is None:
            raise HTTPException(404, "no stored spec")
        doc = json.loads(row.spec_json)
        try:
            spec = parse_spec(doc)
            df = load_csv(ds)
            res = run_backtest(df, "dsl:" + sid, {"sl_atr": 1.5, "tp_atr": 3.0},
                               signal=desired_positions(spec, df),
                               risk_percent=0.1)
            metrics = dict(getattr(res, "metrics", {}) or {})
            status, detail = "PASS", {"note": "backtest completed"}
        except Exception as exc:  # noqa: BLE001 — a failed run is recorded, not hidden
            metrics = {}
            status = "ERROR"
            detail = {"error": f"{type(exc).__name__}: {exc}"}
        run_id = store.record_run(
            sid, row.version, run_type="backtest", status=status,
            spec_hash=row.spec_hash, detail=detail,
            metrics={k: v for k, v in metrics.items()
                     if isinstance(v, (int, float))})
        state_after = store.current_state(sid)
        return JSONResponse({
            "ran": True, "run_id": run_id, "status": status,
            "detail": (f"recorded run {run_id} status {status}; lifecycle "
                       f"state unchanged ({state_before} → {state_after})"),
        })

    @app.get("/new", response_class=HTMLResponse)
    def new_strategy_page(request: Request):
        return templates.TemplateResponse(request, "new_strategy.html",
                                          _shell_ctx(request, "new"))

    _PAGE_SIZE = 50

    def _telemetry_rows() -> list[dict]:
        """Trade events from the telemetry JSONL, newest first. A missing or
        unconfigured log yields an empty list (the page renders its honest
        empty state); malformed lines are skipped, never repaired."""
        log = cenv.get(ENV_TELEMETRY_LOG, "")
        if not log or not Path(log).exists():
            return []
        rows = []
        for line in Path(log).read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("event") == "trade":
                rows.append(e)
        rows.reverse()
        return rows

    def _trade_view(e: dict) -> dict:
        ts = e.get("received_at")
        try:
            when = _dt.datetime.fromtimestamp(
                float(ts), tz=_dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OSError):
            when = str(ts or "")
        return {"time": when, "symbol": e.get("symbol", ""),
                "action": e.get("action", ""), "lots": e.get("lots", ""),
                "pnl": e.get("pnl", "")}

    @app.get("/trades", response_class=HTMLResponse)
    def trades_page(request: Request, page: int = 0):
        # Honest sources only: a source that is not connected renders
        # "not connected", never 0. P&L never appears without the distance
        # to the loss limit beside it.
        ctx = _shell_ctx(request, "trades")
        distance = "وصل نیست / not connected"
        open_positions: list = []
        if live_state is not None:
            s = live_state()
            distance = f"{s.drawdown_distance_pct} pct"
            open_positions = [
                {"symbol": p.symbol, "side": p.side, "lots": p.lots,
                 "pnl": ""} for p in s.open_positions]
        rows = _telemetry_rows()
        today = _dt.datetime.now(tz=_dt.timezone.utc).date()

        def _is_today(e: dict) -> bool:
            try:
                return _dt.datetime.fromtimestamp(
                    float(e.get("received_at")),
                    tz=_dt.timezone.utc).date() == today
            except (TypeError, ValueError, OSError):
                return False

        today_trades = [_trade_view(e) for e in rows if _is_today(e)][:100]
        page = max(0, int(page))
        window = rows[page * _PAGE_SIZE:(page + 1) * _PAGE_SIZE]
        ctx.update({
            "open_positions": open_positions,
            "today_trades": today_trades,
            "history_rows": [_trade_view(e) for e in window],
            "page": page,
            "has_more": len(rows) > (page + 1) * _PAGE_SIZE,
            "distance_pct": distance,
        })
        return templates.TemplateResponse(request, "trades.html", ctx)

    # The gate's canonical rail. Stages 6-7 are the extra tester models —
    # they run INSIDE stage 5 as six legs (the gate's own numbering).
    _GATE_RAIL = (
        (0, "self_protection"), (1, "strict_compile"), (2, "dsl_parity"),
        (3, "broker_parity"), (4, "fixture_import"),
        (5, "tester_legs (stages 5–7: the six tester legs)"),
        (8, "reconciliation (incl. 8a–8d)"), (9, "archive_manifest"),
        (10, "certify"))

    def _leg_outcomes(ev_dir: Path) -> list[dict]:
        """Per-leg outcome records written by the gate's classifier — found by
        their content (outcome+leg+reason keys), never guessed by filename."""
        legs = []
        for p in sorted(ev_dir.glob("*.json")):
            if p.name == "gate_summary.json" or p.name.startswith("stage_"):
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if (isinstance(doc, dict)
                    and {"outcome", "leg", "reason"} <= set(doc)):
                legs.append(doc)
        legs.sort(key=lambda d: str(d.get("leg", "")))
        return legs

    @app.get("/certification", response_class=HTMLResponse)
    def certification_page(request: Request):
        ctx = _shell_ctx(request, "certification")
        ev = cenv.get(ENV_EVIDENCE_DIR, "")
        ctx.update({"evidence_configured": bool(ev), "evidence_dir": ev,
                    "gate_result": "", "stages": [], "error": ""})
        if not ev:
            return templates.TemplateResponse(request,
                                              "certification.html", ctx)
        ev_dir = Path(ev)
        summary = ev_dir / "gate_summary.json"
        if not summary.exists():
            ctx["error"] = f"gate_summary.json not found under {ev}"
            return templates.TemplateResponse(request,
                                              "certification.html", ctx)
        lang = ctx["lang"]
        try:
            doc = json.loads(summary.read_text(encoding="utf-8"))
            ctx["gate_result"] = str(doc.get("gate_result", ""))
            recorded = {int(st.get("stage", -1)): st
                        for st in doc.get("stages", [])
                        if isinstance(st, dict)}
            legs = [{
                "name": str(leg.get("leg", "")),
                "verdict": str(leg.get("outcome", "")),
                "verdict_explained":
                    explain_status(str(leg.get("outcome", "")), lang)
                    if lang == "fa" else "",
                "reason": str(leg.get("reason", "") or ""),
                "log_lines": [str(x) for x in
                              (leg.get("evidence_lines") or [])],
            } for leg in _leg_outcomes(ev_dir)]
            stages = []
            for num, rail_name in _GATE_RAIL:
                st = recorded.get(num)
                if st is None:
                    stages.append({
                        "stage": num, "name": rail_name,
                        "status": "NOT RUN",
                        "status_explained":
                            explain_status("NOT RUN", lang)
                            if lang == "fa" else "",
                        "reason": ("the gate stopped before this stage"
                                   if ctx["gate_result"] else ""),
                        "artifacts": [], "legs": []})
                    continue
                stages.append({
                    "stage": num,
                    "name": str(st.get("name", rail_name)),
                    "status": str(st.get("status", "NOT RUN")),
                    "status_explained":
                        explain_status(str(st.get("status", "")), lang)
                        if lang == "fa" else "",
                    "reason": str(st.get("reason", "") or ""),
                    "artifacts": [a for a in (st.get("artifacts") or [])
                                  if isinstance(a, dict)],
                    "legs": legs if num == 5 else [],
                })
            ctx["stages"] = stages
        except (ValueError, OSError) as exc:
            ctx["error"] = f"{type(exc).__name__}: {exc}"
        return templates.TemplateResponse(request, "certification.html", ctx)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        ctx = _shell_ctx(request, "settings")
        ctx.update({"checks": []})
        return templates.TemplateResponse(request, "settings.html", ctx)

    # ---- telemetry proxy (same-origin SSE for the pages' live updates) -----
    @app.get("/telemetry/latest")
    def telemetry_latest():
        url = cenv.get(ENV_TELEMETRY_URL, "")
        if not url:
            raise HTTPException(503, "telemetry not configured "
                                     f"(set {ENV_TELEMETRY_URL})")
        try:
            with urllib.request.urlopen(
                    url.rstrip("/") + "/telemetry/latest", timeout=5) as r:
                return JSONResponse(json.loads(r.read() or b"{}"))
        except Exception:  # noqa: BLE001 — unreachable is an honest 503
            raise HTTPException(503, "telemetry bridge unreachable") from None

    @app.get("/telemetry/stream")
    def telemetry_stream():
        url = cenv.get(ENV_TELEMETRY_URL, "")
        if not url:
            raise HTTPException(503, "telemetry not configured "
                                     f"(set {ENV_TELEMETRY_URL})")
        try:
            upstream = urllib.request.urlopen(
                url.rstrip("/") + "/telemetry/stream", timeout=10)
        except Exception:  # noqa: BLE001 — unreachable is an honest 503
            raise HTTPException(503, "telemetry bridge unreachable") from None

        def gen():
            try:
                with upstream:
                    yield from upstream
            except Exception:  # noqa: BLE001 — the browser reconnects
                return
        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def _current_version(store: FactoryStore, sid: str) -> int:
    with store.session() as sess:
        from ..factory.models import StrategyVersion
        row = (sess.query(StrategyVersion)
               .filter_by(strategy_id=sid)
               .order_by(StrategyVersion.version.desc()).first())
        return row.version if row else 0


__all__ = ["KANBAN_COLUMNS", "SafetyHub", "create_app"]
