"""Operator UI/API (mission §57-§59/§78/§80): FastAPI + Jinja2 +
HTMX.  NO React.  Every promotion goes through an EXPLICIT approval
button carrying actor + reason; the UI can never mark a strategy LIVE
(§73: enforced by source-scan test) and can never skip lifecycle
stages — it may only request the NEXT legal transition, which the
factory store re-validates server-side (state machine + evidence
gates + human approval).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

from ..discovery.safety import AllocationCircuitBreaker, KillSwitch
from ..factory.store import FactoryStore, StoreError

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


def create_app(store: FactoryStore, safety: SafetyHub | None = None,
               *, score_fn: Callable[[str], dict] | None = None,
               research_runner: Callable[[dict], dict] | None = None,
               campaign_query: Callable[[], list[dict]] | None = None
               ) -> FastAPI:
    app = FastAPI(title="AEGIS Governance Console", version="1.0")
    env = Environment(autoescape=True,
                      loader=FileSystemLoader(str(TEMPLATES_DIR)))
    templates = Jinja2Templates(env=env)
    safety = safety or SafetyHub(KillSwitch(), AllocationCircuitBreaker())

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
        return templates.TemplateResponse(request, "board.html", {
            "columns": columns,
            "kill_switch": ks.state.value,
            "kill_reason": ks.reason,
            "breaker_frozen": safety.breaker.st.frozen,
            "alerts": safety.watchdog_alerts[-10:],
        })

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

    @app.post("/campaigns")
    def create_campaign(request: Request, idea: str = Form(...),
                        source: str = Form(""),
                        dataset: str = Form("synthetic-default"),
                        actor: str = Form(...)):
        """One-click research intake (§52/§54): idea + optional source +
        dataset → interpreted draft (deterministic template; LLM
        optional) → registered campaign with declared budgets.  The
        campaign NEVER trades; live promotion stays OFF by default."""
        from ..discovery.candidates import doc_hash
        from ..factory.models import DiscoveryCampaign
        if not idea.strip() or not actor.strip():
            raise HTTPException(422, "idea and actor are required")
        campaign_id = f"camp_{doc_hash({'idea': idea, 'ts_actor': actor})[:12]}"
        manifest = {"hypothesis": idea.strip()[:200],
                    "source_text_hash": doc_hash({"text": source})
                    if source.strip() else "",
                    "dataset": dataset,
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

    return app


def _current_version(store: FactoryStore, sid: str) -> int:
    with store.session() as sess:
        from ..factory.models import StrategyVersion
        row = (sess.query(StrategyVersion)
               .filter_by(strategy_id=sid)
               .order_by(StrategyVersion.version.desc()).first())
        return row.version if row else 0


__all__ = ["KANBAN_COLUMNS", "SafetyHub", "create_app"]
