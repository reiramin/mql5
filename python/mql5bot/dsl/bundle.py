"""mql5bot.dsl.bundle — the immutable EXECUTABLE BUNDLE contract (§10).

A certified, executable :class:`StrategySpec` is serialized into a single
hash-bound envelope — the *executable bundle* — that BOTH runtimes read:

    certified StrategySpec
            │  build_bundle()
            ▼
    executable bundle  (JSON: identity + market + spec + contracts + hash)
            │
     ┌──────┴───────┐
     ▼              ▼
 Python loader   MQL5 generic runtime (mql5_dsl_runtime/, owner-compiled)
 load_bundle()   DslBundle loader — enforces the SAME fail-closed checks

The envelope binds decision-changing identity so a runtime can refuse to
load anything it cannot faithfully execute (mission §10):

    bundle_format_version   envelope schema
    runtime_contract_version execution-semantics version both runtimes speak
    schema_version          DSL document schema
    strategy_id / version   immutable identity
    spec_hash / semantic_hash  content identity (re-derived and checked)
    market (symbol/timeframe)  never guessed (§6)
    indicator_contracts     {kind, version, mql5_status} per used kind
    spec                    the FULL normalized executable document
    bundle_hash             sha256 over everything above (tamper-evident)

The loader FAILS CLOSED on: malformed envelope, unsupported bundle or
runtime version, missing identity, hash mismatch, unresolved ambiguity
(drafts never run), spec-hash/identity mismatch, and indicator-contract
drift vs the current registry.  It never repairs, never guesses, never
executes code — the bundle is DATA.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import BundleError, DslError
from .model import StrategySpec
from .normalize import canon_json
from .parse import parse_spec
from .schema import SCHEMA_VERSION, validate_document_size

# The envelope format and the execution-semantics contract. Bump
# RUNTIME_CONTRACT_VERSION only when the interpreted semantics change in a
# way both the Python runtime AND the MQL5 runtime must re-agree on.
BUNDLE_FORMAT_VERSION = "1.0"
RUNTIME_CONTRACT_VERSION = "1.0"

_HASH_FIELD = "bundle_hash"


def _binding_hash(envelope: dict) -> str:
    """sha256 over the canonical envelope EXCLUDING the hash field itself
    (same canon_json convention as spec_hash)."""
    import hashlib
    core = {k: v for k, v in envelope.items() if k != _HASH_FIELD}
    return hashlib.sha256(canon_json(core).encode()).hexdigest()


def _indicator_contracts(spec: StrategySpec) -> list[dict]:
    """{kind, version, mql5_status} for every indicator kind the spec
    uses — bound into the bundle so a runtime can detect contract drift
    and refuse a kind whose definition changed under it (§7/§10)."""
    from ..indicator_universe import contract as _contract
    kinds = sorted({ind.kind for ind in spec.indicators})
    out: list[dict] = []
    for kind in kinds:
        try:
            ct = _contract(kind)
        except Exception as exc:                      # unknown kind
            raise BundleError(
                f"indicator kind {kind!r} has no registry contract",
                path="indicator_contracts") from exc
        out.append({"kind": kind, "version": int(ct.version),
                    "mql5_status": ct.mql5_status})
    return out


def build_bundle(spec: StrategySpec, *,
                 runtime_contract_version: str = RUNTIME_CONTRACT_VERSION
                 ) -> dict:
    """Serialize a CERTIFIED, EXECUTABLE spec into a hash-bound bundle.

    Refuses a non-executable spec (draft v0 or unresolved ambiguities) —
    a bundle is by definition runnable; drafts never become bundles."""
    if not spec.executable:
        reason = ("version 0 (draft)" if spec.version == 0
                  else f"unresolved ambiguities "
                       f"{[a['name'] for a in spec.ambiguities]}")
        raise BundleError(
            f"cannot bundle a non-executable spec ({reason}); resolve and "
            "certify an executable version first")
    envelope = {
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "runtime_contract_version": str(runtime_contract_version),
        "schema_version": spec.document.get("schema_version",
                                            SCHEMA_VERSION),
        "identity": {
            "strategy_id": spec.strategy_id,
            "strategy_version": int(spec.version),
            "spec_hash": spec.spec_hash,
            "semantic_hash": spec.semantic_hash,
        },
        "market": {"symbol": spec.market.symbol,
                   "timeframe": spec.market.timeframe},
        "indicator_contracts": _indicator_contracts(spec),
        # the FULL normalized executable document (indicators/entry/exit/
        # filters/params) — the runtime interprets THIS, verbatim
        "spec": spec.document,
    }
    envelope[_HASH_FIELD] = _binding_hash(envelope)
    return envelope


@dataclass(frozen=True)
class ExecutableBundle:
    """A loaded, verified bundle. ``spec`` is the re-parsed, executable
    :class:`StrategySpec` the runtime evaluates."""

    envelope: dict
    spec: StrategySpec

    @property
    def strategy_id(self) -> str:
        return self.envelope["identity"]["strategy_id"]

    @property
    def strategy_version(self) -> int:
        return int(self.envelope["identity"]["strategy_version"])

    @property
    def spec_hash(self) -> str:
        return self.envelope["identity"]["spec_hash"]

    @property
    def bundle_hash(self) -> str:
        return self.envelope[_HASH_FIELD]

    @property
    def market(self) -> dict:
        return dict(self.envelope["market"])


def _require(cond: bool, msg: str, path: str = "") -> None:
    if not cond:
        raise BundleError(msg, path=path)


def load_bundle(envelope: dict, *,
                accepted_runtime_versions: tuple[str, ...] =
                (RUNTIME_CONTRACT_VERSION,)) -> ExecutableBundle:
    """Fail-closed load. Mirrors the MQL5 loader's refusals (§10)."""
    _require(isinstance(envelope, dict), "bundle must be a JSON object")
    # total-size guard on the in-memory path too (an already-parsed dict
    # never went through load_document's byte check): a bundle is untrusted
    # data and must fail closed on oversize before any structural work.
    try:
        validate_document_size(canon_json(envelope))
    except DslError as exc:
        raise BundleError(f"bundle exceeds size limit: {exc}") from exc
    _require(envelope.get("bundle_format_version") == BUNDLE_FORMAT_VERSION,
             f"unsupported bundle_format_version "
             f"{envelope.get('bundle_format_version')!r}; this loader "
             f"speaks {BUNDLE_FORMAT_VERSION!r}",
             path="bundle_format_version")
    rcv = envelope.get("runtime_contract_version")
    _require(rcv in accepted_runtime_versions,
             f"unsupported runtime_contract_version {rcv!r}; accepted: "
             f"{list(accepted_runtime_versions)}",
             path="runtime_contract_version")

    ident = envelope.get("identity")
    _require(isinstance(ident, dict), "missing identity block",
             path="identity")
    for key in ("strategy_id", "strategy_version", "spec_hash",
                "semantic_hash"):
        _require(key in ident and ident[key] not in (None, ""),
                 f"identity.{key} is required", path=f"identity.{key}")

    market = envelope.get("market")
    _require(isinstance(market, dict) and market.get("symbol")
             and market.get("timeframe"),
             "bundle market must specify symbol and timeframe (§6)",
             path="market")

    # tamper check: recompute the binding hash over the canonical core
    _require(_HASH_FIELD in envelope, "missing bundle_hash",
             path=_HASH_FIELD)
    expected = _binding_hash(envelope)
    _require(envelope[_HASH_FIELD] == expected,
             f"bundle_hash mismatch (tampered or mis-encoded): stored "
             f"{envelope[_HASH_FIELD]!r} != computed {expected!r}",
             path=_HASH_FIELD)

    spec_doc = envelope.get("spec")
    _require(isinstance(spec_doc, dict), "missing spec document",
             path="spec")
    # re-parse through the SAME validator: unsupported indicator /
    # condition / exit / limits all fail closed here
    try:
        spec = parse_spec(spec_doc)
    except DslError as exc:
        raise BundleError(f"spec failed validation: {exc}",
                          path="spec") from exc

    # a bundle must be executable — never a draft or ambiguous spec
    _require(spec.executable,
             "bundled spec is not executable (draft or unresolved "
             f"ambiguities: {[a['name'] for a in spec.ambiguities]})",
             path="spec")

    # identity must bind to the CONTENT: the re-derived hashes must match
    _require(spec.spec_hash == ident["spec_hash"],
             f"identity.spec_hash {ident['spec_hash']!r} != re-derived "
             f"{spec.spec_hash!r} (identity does not bind the spec)",
             path="identity.spec_hash")
    _require(spec.semantic_hash == ident["semantic_hash"],
             "identity.semantic_hash does not bind the spec",
             path="identity.semantic_hash")
    _require(spec.strategy_id == ident["strategy_id"]
             and int(spec.version) == int(ident["strategy_version"]),
             "identity id/version does not match the spec",
             path="identity")

    # market in the envelope must match the spec's market
    _require(spec.market.symbol == market["symbol"]
             and spec.market.timeframe == market["timeframe"],
             "bundle market does not match the spec market",
             path="market")

    # indicator-contract drift: every bound contract must match the
    # CURRENT registry version — a kind redefined under the bundle is
    # refused (never silently run with new semantics, §7/§10)
    from ..indicator_universe import contract as _contract
    for entry in envelope.get("indicator_contracts", []):
        kind = entry.get("kind")
        try:
            ct = _contract(kind)
        except Exception as exc:
            raise BundleError(f"unknown indicator contract {kind!r}",
                              path="indicator_contracts") from exc
        _require(int(entry.get("version", -1)) == int(ct.version),
                 f"indicator {kind!r} contract drift: bundle pinned "
                 f"v{entry.get('version')} but registry is v{ct.version}",
                 path="indicator_contracts")

    return ExecutableBundle(envelope=envelope, spec=spec)
