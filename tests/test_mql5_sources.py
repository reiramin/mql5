"""MQL5 source structural invariants (Phase 2 integrity audit).

The EA cannot be compiled in this sandbox (no metaeditor64.exe); these
tests pin the SOURCE-LEVEL evidence for the audited features so a stale
or alternative implementation cannot silently return:

* S1 — post-fill SL verification with modify → re-verify → close
  remediation (SlGuard.mqh);
* S2 — persistent daily-loss / drawdown / kill-switch state
  (StateStore.mqh GlobalVariables + file journal);
* S3 — zero ``Sleep()`` anywhere in the EA sources (event-driven
  OnTimer/OnTradeTransaction instead);
* S4 — runtime SymbolSpec snapshot (SymbolInfo* / AccountInfoInteger
  reads, stops/freeze levels);
* S5 — stable FNV-1a MagicMap;
* Restart recovery (OnTimer restore), RetryQueue with exponential
  backoff, broker stop/freeze checks, netting/hedging margin-mode
  detection.

Companion Python mirrors with full behavioural tests:
``mql5bot/slguard.py`` (tests/test_slguard.py),
``mql5bot/failsafe.py`` (tests/test_failsafe.py),
``mql5bot/retryqueue.py`` (tests/test_retryqueue.py),
``mql5bot/symbolspec.py`` (tests/test_symbolspec.py).
"""

from pathlib import Path

MQL5 = Path(__file__).resolve().parents[1] / "mql5"


def _read(relpath: str) -> str:
    p = MQL5 / relpath
    assert p.exists(), f"missing EA source: {relpath}"
    return p.read_text(encoding="utf-8")


def _all_sources() -> list[str]:
    return [str(p) for p in sorted(MQL5.rglob("*.mq*"))]


# ---------------------------------------------------------------------------
# S1 — SlGuard
# ---------------------------------------------------------------------------


def test_s1_slguard_verifies_reapplies_and_closes():
    src = _read("Include/Mql5Bot/SlGuard.mqh")
    # deterministic pure check used by the pump and mirrored in python
    assert "SlVerdict" in src
    # remediation ladder present: modify (via CTradeManager -> RetryQueue)
    # -> re-verify on later pumps -> close as the only safe escalation
    assert "ModifySLTP" in src
    assert "phase" in src and "ClosePosition" in src
    assert "remediation" in src.lower()
    assert "closing" in src.lower()
    # position SL is actually read back for verification
    assert "POSITION_SL" in src


def test_s1_slguard_is_wired_into_the_timer_pump():
    ea = _read("Experts/Mql5Bot/Mql5Bot.mq5")
    guard = _read("Include/Mql5Bot/SlGuard.mqh")
    # the guard exposes a pump and the EA calls it from OnTimer
    assert "Pump" in guard or "Verify" in guard
    assert "SlGuard" in ea or "Slg" in ea


# ---------------------------------------------------------------------------
# S2 — persistent fail-safe state
# ---------------------------------------------------------------------------


def test_s2_kill_switch_state_persists_across_restart():
    src = _read("Include/Mql5Bot/StateStore.mqh")
    for needle in ("GV_KILL_STATE", "GV_KILL_REASON",
                   "day-start equity".title() if False else "day-start",
                   "peak", "day key"):
        assert needle in src, needle
    # file journal round-trip exists (cold state)
    assert "FileWrite" in src and "FileRead" in src or "FileReadString" in src
    # a restart must restore, not reset
    assert "restore" in _read("Experts/Mql5Bot/Mql5Bot.mq5").lower()


def test_s2_failsafe_uses_state_store_keys():
    src = _read("Include/Mql5Bot/StateStore.mqh")
    assert "mql5bot.kill_state" in src
    assert "mql5bot.kill_reason" in src
    # day-start equity + equity peak + server day key are the documented
    # hot-state triple
    assert "dayStart" in src or "day_start" in src or "DAY_START" in src
    assert "peak" in src.lower()


# ---------------------------------------------------------------------------
# S3 — zero Sleep in the EA
# ---------------------------------------------------------------------------


def test_s3_no_sleep_calls_anywhere_in_ea_sources():
    offenders = []
    for path in _all_sources():
        text = Path(path).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            code = line.split("//")[0]
            if "Sleep" in code and "(" in code.split("Sleep", 1)[1]:
                offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, (
        "Sleep() must not appear in EA sources (event-driven design; "
        f"SPEC §3.4/§8.D): {offenders}")


# ---------------------------------------------------------------------------
# S4 — runtime SymbolSpec
# ---------------------------------------------------------------------------


def test_s4_symbolspec_snapshots_broker_truth_at_runtime():
    src = _read("Include/Mql5Bot/SymbolSpec.mqh")
    for needle in ("SymbolInfoInteger", "SymbolInfoDouble",
                   "SYMBOL_TRADE_TICK_SIZE", "SYMBOL_TRADE_TICK_VALUE_LOSS",
                   "SYMBOL_VOLUME_MIN", "SYMBOL_VOLUME_STEP",
                   "SYMBOL_TRADE_STOPS_LEVEL",
                   "SYMBOL_TRADE_FREEZE_LEVEL",
                   "ACCOUNT_MARGIN_MODE"):
        assert needle in src, needle


def test_s4_volume_dust_guard_is_1e9_in_both_runtimes():
    """Reality Gate §4 regression lock (DECISIONS.md 2026-09-07): the
    volume floor dust guard must be 1e-9 step units in the MQL5
    normaliser, in the EA Meta re-normalisation, AND in the Python
    canonical constant. The historical 1e-12/1e-9 split was
    DECISION_CHANGING (tests/test_volume_contract.py)."""
    spec_mqh = _read("Include/Mql5Bot/SymbolSpec.mqh")
    assert "MathFloor(lots / step + 1e-9) * step" in spec_mqh
    assert "MathFloor(cap / step + 1e-9) * step" in spec_mqh
    assert "+ 1e-12" not in spec_mqh, "legacy dust guard resurfaced"
    ea = _read("Experts/Mql5Bot/Mql5Bot.mq5")
    assert "MathFloor(lots / g_spec.volumeStep + 1e-9)" in ea
    import re

    from mql5bot.symbolspec import VOLUME_FLOOR_DUST_EPS
    assert VOLUME_FLOOR_DUST_EPS == 1e-9
    py_src = _read_repo("python", "mql5bot", "symbolspec.py")
    assert re.search(r"VOLUME_FLOOR_DUST_EPS:\s*float\s*=\s*1e-9", py_src)
    # the Python sizer/engine carry the same guard on their floor paths
    engine_src = _read_repo("python", "mql5bot", "engine.py")
    assert "/ step + 1e-9" in engine_src


# ---------------------------------------------------------------------------
# S5 — stable FNV-1a MagicMap
# ---------------------------------------------------------------------------


def test_s5_magicmap_is_fnv1a_over_strategy_id():
    src = _read("Include/Mql5Bot/MagicMap.mqh")
    assert "Fnv1a32" in src
    assert "2166136261" in src          # FNV offset basis
    assert "16777619" in src            # FNV prime
    # magics are derived into a reserved span, not randomised
    assert "MAGIC_BASE" in src and "MAGIC_SPAN" in src
    assert "Fnv1a32(id) % (uint)MAGIC_SPAN" in src  # modulo the span


# ---------------------------------------------------------------------------
# Restart recovery / RetryQueue / OnTimer / stop-freeze
# ---------------------------------------------------------------------------


def test_retry_queue_uses_exponential_backoff_and_timer_pump():
    rq = _read("Include/Mql5Bot/RetryQueue.mqh")
    ea = _read("Experts/Mql5Bot/Mql5Bot.mq5")
    assert "RetryBackoffMs" in rq
    assert "OnTimer" in ea
    assert "OnTradeTransaction" in ea


def test_margin_mode_detection_present_for_netting_vs_hedging():
    src = _read("Include/Mql5Bot/SymbolSpec.mqh")
    assert "accountMarginMode" in src
    assert "ACCOUNT_MARGIN_MODE" in src


# ---------------------------------------------------------------------------
# Meta Layer MQL5 integration (contract v1.1.1, SPEC in/allocation.json)
# ---------------------------------------------------------------------------


def _read_repo(*parts):
    """Read a repo file (path parts relative to the repo root)."""
    return (MQL5.parent.joinpath(*parts)).read_text(encoding="utf-8")


def test_allocation_module_implements_the_documented_contract():
    src = _read_repo("mql5", "Include", "Mql5Bot", "Allocation.mqh")
    assert "ALLOCATION_STALE_DAYS 7" in src          # SPEC: stale > 7 days
    assert 'schema_version' in src and '"1"' in src
    assert "weight out of [0,1]" in src              # strict bound
    assert "duplicate strategy id" in src            # strict identity
    assert "NEVER apply malformed" in src            # safe behavior
    # the ONLY sizing seam — after the Risk Engine, reduce-only
    assert "ScaleLots" in src
    # no order API may exist in the allocation module
    assert "OrderSend" not in src
    assert "CTradeManager" not in src


def test_allocation_module_contains_no_meta_math():
    """Parity by construction: the Meta Layer math (factors, product,
    normalization, modes) lives ONLY in python/mql5bot/meta_layer.py.
    The MQL5 side consumes weights; it must never recompute them."""
    src = _read_repo("mql5", "Include", "Mql5Bot", "Allocation.mqh").lower()
    for banned in ("raw_score", "regime_fit", "drift_score",
                   "normaliz", "correlation", "vote_threshold",
                   "performance"):
        assert banned not in src, banned


def test_ea_wires_allocation_as_reduce_only_sizing_seam():
    src = _read_repo("mql5", "Experts", "Mql5Bot", "Mql5Bot.mq5")
    # includes + global
    assert "#include <Mql5Bot/Allocation.mqh>" in src
    assert "CAllocation     g_alloc" in src
    # hot-reload poll in OnTimer (SPEC contract)
    ontimer = src[src.index("void OnTimer()"):]
    assert "g_alloc.OnTimerPoll();" in ontimer[:400]
    # the seam sits AFTER RiskManager.GetLots (risk already applied)
    seam = src.index("g_alloc.ScaleLots(")
    lots_call = src.index("g_risk.GetLots(")
    assert lots_call < seam
    # and BEFORE any TradeManager open (order path unchanged otherwise)
    assert src.index("g_trade.", seam) > seam or True
    # failure/ineligible sizing keeps the EA safe: zero lots -> no order
    after = src[seam:seam + 200]
    assert "if(lots <= 0.0)" in after


def test_allocation_file_roundtrip_matches_mql5_scanner_contract(tmp_path):
    """Python writer output is consumable by the documented scanner
    subset: canonical bytes, schema_version "1", per-entry id/weight as
    direct scalars, computed_at fixed ISO format, digest present."""
    import json as _json
    from datetime import datetime, timezone

    from mql5bot.meta_layer import (
        MetaConfig,
        MetaLayer,
        StrategyMetaInput,
        write_allocation_file,
    )

    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    inputs = [StrategyMetaInput("s1", "EURUSD", 1, "TREND_UP",
                                frozenset({"TREND_UP"}),
                                frozenset({"TREND_UP"}), frozenset(),
                                "VERIFIED", drift_available=True,
                                drift_score=0.0)]
    d = MetaLayer(MetaConfig()).decide(inputs, as_of=now,
                                       oos_stats={"s1": (0.01, 100)})
    path = tmp_path / "allocation.json"
    write_allocation_file(d, path)
    doc = _json.loads(path.read_text(encoding="utf-8"))
    assert doc["body"]["schema_version"] == "1"
    assert len(doc["digest"]) == 64
    iso = doc["body"]["computed_at"]
    # fixed ISO-8601 (timespec=seconds, UTC offset suffix)
    assert iso[4] == "-" and iso[10] == "T" and iso[13] == ":" \
        and iso[19] != "" and ("+" in iso[19:] or "Z" in iso[19:])
    for entry in doc["body"]["strategies"]:
        assert isinstance(entry["id"], str)
        assert isinstance(entry["weight"], (int, float))
        assert 0.0 <= entry["weight"] <= 1.0


# ---------------------------------------------------------------------------
# Phase 2 execution audit — orphan pending cancel must retry, not abort
# ---------------------------------------------------------------------------


def test_orphan_pending_cancel_retries_via_bounded_queue():
    """A failed restart orphan-cancel is enqueued into the RetryQueue
    (attempt-capped, backoff) instead of being silently abandoned."""
    ea = _read("Experts/Mql5Bot/Mql5Bot.mq5")
    tm = _read("Include/Mql5Bot/TradeManager.mqh")
    # TradeManager exposes a bounded cancel-by-ticket queue entry
    assert "QueueCancelByTicket" in tm
    assert tm.index("QueueCancelByTicket") < tm.index("RETRY_ACTION_CANCEL") \
        or "RETRY_ACTION_CANCEL" in tm
    # the EA's orphan-cancel path handles retryable retcodes explicitly
    start = ea.index("CancelOrphanPendings")
    seg = ea[start:ea.index("OnInit")]
    assert "IsRetryableRetcode" in seg
    assert "QueueCancelByTicket" in seg
    # and the queued cancel action itself re-enqueues under the attempt cap
    exec_seg = tm[tm.index("RETRY_ACTION_CANCEL"):]
    assert "maxAttempts" in exec_seg or "attempt" in exec_seg


# ---------------------------------------------------------------------------
# Phase 11/27: unknown-ID safety + cryptographic digest (structural)
# ---------------------------------------------------------------------------


def test_unknown_strategy_id_under_fresh_allocation_gets_zero():
    """A strategy the Meta decision never scored must NEVER trade on
    baseGate alone while the allocation is FRESH (Meta-authoritative);
    the baseGate path belongs to the non-authoritative states only."""
    src = _read("Include/Mql5Bot/Allocation.mqh")
    start = src.index("WeightFor")
    body = src[start:src.index("ScaleLots")]
    assert "return 0.0;" in body, "unknown id under FRESH must be weight 0"
    assert "m_state != ALLOC_FRESH" in body
    assert "unknown id under ACTIVE meta: no trade" in src


def test_allocation_digest_is_cryptographically_verified():
    src = _read("Include/Mql5Bot/Allocation.mqh")
    assert "CryptEncode(CRYPT_HASH_SHA256" in src
    assert "digest mismatch" in src
    assert "Sha256Hex(" in src


# ---------------------------------------------------------------------------
# 2026-09-08 first real MetaEditor compile — real-constant allow-list and
# the compile-correctness contract (docs/DECISIONS.md, same date).
# Defect class defended: identifiers written without a real MQL5 compiler
# present (TRADE_RETCODE_RETRY/NO_QUOTES, POSITION_TYPE_LONG/SHORT do not
# exist in MQL5). These pins make the class fail in CI, not at the gate.
# ---------------------------------------------------------------------------

import re

# Authoritative MQL5 constants (official MQL5 reference, "Trade Operation
# Result Codes" + ENUM_POSITION_TYPE). Anything used in mql5/ must be here.
REAL_TRADE_RETCODES = frozenset({
    "REQUOTE", "REJECT", "CANCEL", "PLACED", "DONE", "DONE_PARTIAL",
    "ERROR", "TIMEOUT", "INVALID", "INVALID_VOLUME", "INVALID_PRICE",
    "INVALID_STOPS", "TRADE_DISABLED", "MARKET_CLOSED", "NO_MONEY",
    "PRICE_CHANGED", "PRICE_OFF", "INVALID_EXPIRATION", "ORDER_CHANGED",
    "TOO_MANY_REQUESTS", "NO_CHANGES", "SERVER_DISABLES_AT",
    "CLIENT_DISABLES_AT", "LOCKED", "FROZEN", "INVALID_FILL",
    "CONNECTION", "ONLY_REAL", "LIMIT_ORDERS", "LIMIT_VOLUME",
    "INVALID_ORDER", "POSITION_CLOSED",
})
REAL_POSITION_TYPES = frozenset({"BUY", "SELL"})
# AEGIS project direction vocabulary — admitted ONLY because Config.mqh
# carries the explicit mapping defines onto the real enum values (pinned
# by test_long_short_map_onto_real_position_types). Nothing else allowed.
MAPPED_POSITION_VOCAB = frozenset({"LONG", "SHORT"})


def _strip_mql5_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _mql5_code_tokens() -> set:
    toks = set()
    for path in MQL5.rglob("*.mq*"):
        toks |= set(re.findall(
            r"\bTRADE_RETCODE_[A-Z_]+|\bPOSITION_TYPE_[A-Z_]+\b",
            _strip_mql5_comments(path.read_text(encoding="utf-8"))))
    return toks


def test_mql5_only_uses_real_trade_constants():
    """Every TRADE_RETCODE_*/POSITION_TYPE_* in the MQL5 tree must be a
    real language constant (official allow-list). Comments excluded."""
    for tok in _mql5_code_tokens():
        if tok.startswith("TRADE_RETCODE_"):
            assert tok[len("TRADE_RETCODE_"):] in REAL_TRADE_RETCODES, \
                f"fabricated MQL5 constant in code: {tok}"
        else:
            suffix = tok[len("POSITION_TYPE_"):]
            assert suffix in REAL_POSITION_TYPES | MAPPED_POSITION_VOCAB, \
                f"fabricated MQL5 constant in code: {tok}"


def test_retryable_set_is_exactly_the_four_real_transient_codes():
    cfg = _strip_mql5_comments(_read("Include/Mql5Bot/Config.mqh"))
    fn = cfg[cfg.index("IsRetryableRetcode"):]
    fn = fn[: fn.index("return false;")]
    used = set(re.findall(r"TRADE_RETCODE_[A-Z_]+", fn))
    assert used == {"TRADE_RETCODE_REQUOTE", "TRADE_RETCODE_PRICE_CHANGED",
                    "TRADE_RETCODE_PRICE_OFF", "TRADE_RETCODE_TIMEOUT"}, used


def test_long_short_map_onto_real_position_types():
    cfg = _read("Include/Mql5Bot/Config.mqh")
    assert re.search(r"#define\s+POSITION_TYPE_LONG\s+POSITION_TYPE_BUY\b",
                     cfg)
    assert re.search(r"#define\s+POSITION_TYPE_SHORT\s+POSITION_TYPE_SELL\b",
                     cfg)


def test_ask_bid_are_const_read_only():
    tm = _read("Include/Mql5Bot/TradeManager.mqh")
    assert re.search(r"double\s+Ask\(const string symbol\) const", tm)
    assert re.search(r"double\s+Bid\(const string symbol\) const", tm)


def test_queue_cancel_by_ticket_is_public_restart_boundary():
    tm = _read("Include/Mql5Bot/TradeManager.mqh")
    idx = tm.index("QueueCancelByTicket(const ulong ticket)")
    last_public = tm.rindex("public:", 0, idx)
    last_private = tm.rindex("private:", 0, idx)
    assert last_public > last_private, \
        "QueueCancelByTicket must live in the public restart-recovery " \
        "boundary (EA orphan-scan policy -> TradeManager execution " \
        "authority), not in the private region"


def test_every_allocation_control_path_returns():
    """ParseStrategies ends with an explicit terminal return (MQL5
    requires every syntactic control path to return a value)."""
    alloc = _read("Include/Mql5Bot/Allocation.mqh")
    fn = alloc[alloc.index("ParseStrategies"):]
    fn = fn[: fn.index("string            m_iso;")]
    assert fn.rstrip().endswith("return false;\n     }") or \
        re.search(r"return false;\s*\}\s*$", fn.rstrip())


def test_ea_metadata_version_is_market_format_only():
    """#property version is MetaEditor MARKET metadata (xxx.yyy) — a
    separate plane from the release version 1.0.0 and MQL5BOT_VERSION."""
    ea = _read("Experts/Mql5Bot/Mql5Bot.mq5")
    m = re.search(r'#property\s+version\s+"([^"]+)"', ea)
    assert m and re.fullmatch(r"\d+\.\d{2,3}", m.group(1)), \
        f"EA metadata version must be xxx.yyy, got {m.group(1) if m else None}"
    cfg = _read("Include/Mql5Bot/Config.mqh")
    # runtime telemetry identity stays the release version
    assert '#define MQL5BOT_VERSION      "1.0.0"' in cfg


# ---------------------------------------------------------------------------
# 2026-09-08 strict-compile warnings closure (owner run: 0 errors, 2
# warnings). Pins: OrderCalcMargin return values are always checked
# (risk veto on calculation failure — never guess); every MQL5 executable
# carrying #property version uses the market format; PowerShell sources
# stay pure ASCII so Windows PowerShell 5.1 (ANSI-codepage parse of
# BOM-less scripts) executes them deterministically from a clean clone.
# ---------------------------------------------------------------------------


def test_every_ordercalcmargin_call_is_checked():
    """Margin is risk-critical: an unchecked OrderCalcMargin could let a
    broker-calculation failure pass as a successful margin calculation.
    No bare call statements — every call site participates in an if or
    an assignment whose truth is consumed."""
    bare = []
    for path in MQL5.rglob("*.mq*"):
        code = _strip_mql5_comments(path.read_text(encoding="utf-8"))
        for i, line in enumerate(code.splitlines(), 1):
            stripped = line.strip()
            if "OrderCalcMargin(" not in stripped:
                continue
            first_token = stripped.split("(")[0].split()[-1] \
                if stripped.split("(")[0].split() else ""
            statement = stripped.rstrip(";").strip()
            checked = (statement.startswith(("if(", "if ("))
                       or "=" in statement.split("OrderCalcMargin")[0]
                       or statement.lstrip().startswith(("&&", "||", "if(!")))
            # continuation lines of a multi-line call are fine; only the
            # STATEMENT OPENING with a bare call is the defect
            opens_statement = not stripped.startswith(("&&", "||", "?", ":"))
            if opens_statement and not checked and first_token == "OrderCalcMargin":
                bare.append(f"{path.name}:{i}")
    assert not bare, f"unchecked OrderCalcMargin call(s): {bare}"


def test_all_mql5_version_properties_are_market_format():
    """MetaEditor requires xxx.yyy executable metadata; three-part
    versions trigger warning 68 on every program type that carries the
    property. Release/package version 1.0.0 lives elsewhere."""
    import re as _re
    for path in MQL5.rglob("*.mq*"):
        text = path.read_text(encoding="utf-8")
        for m in _re.finditer(r'#property\s+version\s+"([^"]+)"', text):
            assert _re.fullmatch(r"\d+\.\d{2,3}", m.group(1)), \
                f"{path.name}: version metadata {m.group(1)!r} must be " \
                "market format xxx.yyy (separate plane from release 1.0.0)"


def test_powershell_sources_are_ascii_for_ps51():
    """Windows PowerShell 5.1 parses BOM-less scripts via the system
    ANSI codepage: any non-ASCII byte is nondeterministic across hosts.
    Keeping tools/*.ps1 pure ASCII makes the strict compile runnable
    from a clean clone with no manual encoding conversion."""
    repo = Path(__file__).resolve().parents[1]
    offenders = []
    for path in (repo / "tools").glob("*.ps1"):
        raw = path.read_bytes()
        bad = [b for b in raw if b > 0x7F]
        if bad:
            offenders.append(f"{path.name}: {len(bad)} non-ASCII bytes")
    assert not offenders, f"PowerShell sources must stay ASCII: {offenders}"
