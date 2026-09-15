"""discovery/entry_chain.py — the ONE deterministic entry decision
chain (convergence §36/§39/§57).

Event order (normative, pinned by tests — any change must be
deliberate and documented):

    market data
      → strategy state / eligibility
      → regime compatibility
      → score present (ranks only, never authorizes)
      → Meta proposal (weights)
      → portfolio constraints (concentration/heat)
      → risk approval (exposure ≤ Meta×risk budget)
      → circuit breaker
      → kill switch
      → execution boundary

Hard rules proven here:
- NOTHING above Risk may bypass Risk; NOTHING above the Kill Switch
  may override the Kill Switch (§0/§36).
- An order request whose ORIGIN is not a strategy signal (LLM, ML,
  community, factory) is refused before any gate runs — those origins
  can never trade (§0 absolutes 1–4).
- Risk-approved exposure ≤ Meta allocation × risk budget, always
  (§39).  Broker normalization can round DOWN, never up into a trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ALLOWED_ORIGINS = ("strategy",)
BLOCKED_ORIGINS = ("llm", "ml", "community", "factory", "interpreter",
                   "optimizer")


@dataclass(frozen=True)
class EntryRequest:
    origin: str                 # who ASKED: only "strategy" is legal
    strategy_id: str
    symbol: str
    side: str                   # long|short
    requested_risk: float       # fraction of equity requested


@dataclass
class ChainContext:
    market_data_ok: bool = True
    lifecycle_state: str = "LIVE_SMALL"
    human_approved: bool = True
    gates_pass: bool = True
    evidence_ok: bool = True
    regime_allowed: bool = True
    score: float | None = 0.6           # present but never authorizing
    meta_weight: float = 0.10           # Meta's allocated weight share
    portfolio_ok: bool = True           # concentration/heat constraints
    risk_approved_risk: float = 0.005   # Risk's approved fraction
    risk_budget: float = 0.01           # Risk's max fraction for the book
    breaker_frozen: bool = False
    kill_switch_state: str = "NORMAL"   # NORMAL|NO_NEW_TRADES|EMERGENCY_HALT


@dataclass
class EntryDecision:
    allowed: bool
    veto_owner: str = ""                # "" or the refusing layer
    reason: str = ""
    trace: list[dict] = field(default_factory=list)
    approved_risk: float = 0.0          # what Risk would actually allow

    def _step(self, layer: str, ok: bool, detail: str = "") -> bool:
        self.trace.append({"layer": layer, "ok": ok, "detail": detail})
        return ok


def govern_entry(req: EntryRequest, ctx: ChainContext) -> EntryDecision:
    """Run the canonical chain IN ORDER; first veto stops the chain and
    names its owner.  Deterministic; no I/O."""
    d = EntryDecision(allowed=False)

    # origin authority: before ANY gate — a non-strategy origin never
    # even reaches the risk path (§0: LLM/ML/community/factory never
    # trade; no gate may "approve" them past this)
    if req.origin not in ALLOWED_ORIGINS:
        d._step("origin", False,
                f"origin {req.origin!r} may never place orders")
        d.veto_owner = "origin-authority"
        d.reason = (f"requests originating from {req.origin!r} are "
                    "refused unconditionally (Factory/LLM/ML/community "
                    "never trade)")
        return d
    d._step("origin", True, "strategy signal")

    if not d._step("market_data", ctx.market_data_ok):
        d.veto_owner, d.reason = "market-data", "market data unavailable"
        return d
    if ctx.lifecycle_state not in ("SHADOW", "DEMO", "LIVE_SMALL", "LIVE") \
            or not d._step("eligibility",
                           ctx.human_approved and ctx.gates_pass
                           and ctx.evidence_ok):
        d.veto_owner, d.reason = "lifecycle", \
            "state/eligibility gates not satisfied"
        return d
    if not d._step("regime", ctx.regime_allowed):
        d.veto_owner, d.reason = "regime", "regime forbids this book"
        return d
    # score is recorded but NEVER authorizes (§22)
    d._step("score", True,
            f"score={ctx.score!r} (ranks only; not an authorization)")

    meta_risk = ctx.meta_weight * ctx.risk_budget
    if not d._step("meta", ctx.meta_weight > 0,
                   f"meta_weight={ctx.meta_weight}"):
        d.veto_owner, d.reason = "meta", "no Meta allocation"
        return d
    if not d._step("portfolio_constraints", ctx.portfolio_ok):
        d.veto_owner, d.reason = "portfolio", \
            "concentration/heat constraint breach"
        return d
    # §39: approved risk ≤ Meta allocation × risk budget — Risk may
    # only DECREASE what Meta+policy allow
    approved = min(ctx.risk_approved_risk, meta_risk)
    if not d._step("risk", ctx.risk_approved_risk > 0
                   and approved <= meta_risk + 1e-12,
                   f"approved={approved} ≤ meta×budget={meta_risk}"):
        d.veto_owner, d.reason = "risk", "risk approval missing/over Meta"
        return d
    d.approved_risk = approved
    if not d._step("circuit_breaker", not ctx.breaker_frozen):
        d.veto_owner, d.reason = "circuit-breaker", \
            "allocation breaker frozen: keep last safe allocation"
        return d
    if not d._step("kill_switch", ctx.kill_switch_state == "NORMAL",
                   f"state={ctx.kill_switch_state}"):
        d.veto_owner, d.reason = "kill-switch", \
            f"kill switch {ctx.kill_switch_state}: no new risk"
        return d

    d.allowed = True
    return d
