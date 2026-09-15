"""MQL5 allocation-digest integrity (meta-production mission, Phase 27).

The EA consumer verifies the allocation digest CRYPTOGRAPHICALLY with
native ``CryptEncode(CRYPT_HASH_SHA256)`` over the exact body substring.
Python cannot execute MQL5 in this sandbox — these tests pin the parts
that make the EA's algorithm reconcile with the writer:

1. the body substring the EA extracts (byte-for-byte between ``"body":``
   and its matching brace) is EXACTLY the payload Python hashed;
2. the EA source implements the mandated behavior structurally (native
   CryptEncode, substring capture, mismatch/malformed/missing rejection);
3. the adversarial cases reject at the Python reader (same file contract).
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

from mql5bot.meta_layer import (
    MetaConfig,
    MetaDecision,
    MetaFileError,
    MetaLayer,
    StrategyMetaInput,
    read_allocation_file,
    write_allocation_file,
)

MQH = (REPO / "mql5/Include/Mql5Bot/Allocation.mqh").read_text(encoding="utf-8")


def _decision() -> MetaDecision:
    now = "2026-09-05T12:00:00+00:00"
    inputs = [
        StrategyMetaInput("alpha", "SYNTH", 0, "TREND_UP",
                          frozenset({"TREND_UP"}), frozenset({"TREND_UP"}),
                          frozenset(), "VERIFIED", drift_available=True,
                          drift_score=0.0),
        StrategyMetaInput("beta", "SYNTH", 0, "TREND_UP",
                          frozenset({"TREND_UP"}), frozenset({"TREND_UP"}),
                          frozenset(), "VERIFIED", drift_available=True,
                          drift_score=0.0),
    ]
    return MetaLayer(MetaConfig()).decide(inputs, as_of=_dt(now),
                                          returns=None,
                                          oos_stats={"alpha": (0.01, 50),
                                                     "beta": (0.01, 50)})


def _dt(iso):
    from datetime import datetime, timezone
    return datetime.fromisoformat(iso).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# 1. byte-layout reconciliation (EA algorithm == writer payload)
# ---------------------------------------------------------------------------


def _ea_body_substring(doc: str) -> str:
    """Exactly what Allocation.mqh extracts: SkipWs after the ``"body":``
    member colon, then the substring to the matching close brace (string-
    and escape-aware depth counting)."""
    i = doc.index('"body":') + len('"body":')
    while doc[i] in " \t\r\n":
        i += 1
    assert doc[i] == "{"
    depth, j, in_str, esc = 0, i, False, False
    while j < len(doc):
        c = doc[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return doc[i:j + 1]
        j += 1
    raise AssertionError("unterminated body")


def test_ea_body_substring_is_exactly_the_hashed_payload(tmp_path):
    p = tmp_path / "allocation.json"
    write_allocation_file(_decision(), p)
    doc = p.read_text(encoding="utf-8")
    digest = json.loads(doc)["digest"]
    body_sub = _ea_body_substring(doc)
    # the EA hashes THESE bytes; they must equal the writer's payload
    assert hashlib.sha256(body_sub.encode("utf-8")).hexdigest() == digest
    # and round-trips through canonical serialization unchanged
    assert body_sub == json.dumps(json.loads(body_sub), sort_keys=True,
                                  separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------
# 2. EA source structure (native crypto, all rejection branches)
# ---------------------------------------------------------------------------


def test_ea_uses_native_cryptencode_sha256_over_body_substring():
    assert "CryptEncode(CRYPT_HASH_SHA256" in MQH
    assert "StringToCharArray" in MQH and "CP_UTF8" in MQH
    assert "m_bodySub" in MQH and "StringSubstr" in MQH
    assert "digest mismatch" in MQH
    assert "digest malformed" in MQH
    # the old "cannot recompute sha256 cheaply" excuse is gone
    assert "cannot recompute sha256" not in MQH


def test_ea_rejects_non_ascii_body_rather_than_guessing():
    assert "non-ASCII body: refuse" in MQH or "non-ascii body" in MQH


# ---------------------------------------------------------------------------
# 3. adversarial file cases at the reader (same contract, executable)
# ---------------------------------------------------------------------------


def _write_raw(tmp_path, body_obj, digest):
    p = tmp_path / "alloc.json"
    p.write_text(json.dumps({"body": body_obj, "digest": digest},
                            sort_keys=True, separators=(",", ":")),
                 encoding="utf-8")
    return p


def test_correct_body_correct_digest_accepts(tmp_path):
    p = tmp_path / "a.json"
    write_allocation_file(_decision(), p)
    body = read_allocation_file(p)
    assert 0.0 <= body["strategies"][0]["weight"] <= 1.0


def test_modified_body_old_digest_rejected(tmp_path):
    p = tmp_path / "a.json"
    write_allocation_file(_decision(), p)
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["body"]["strategies"][0]["weight"] = 0.99   # tamper
    bad = _write_raw(tmp_path, doc["body"], doc["digest"])
    with pytest.raises(MetaFileError, match="digest mismatch"):
        read_allocation_file(bad)


def test_old_body_new_digest_rejected(tmp_path):
    """body A + digest(A') with A' ≠ A must be refused by the integrity
    check — the digest binds the exact body bytes."""
    p = tmp_path / "a.json"
    write_allocation_file(_decision(), p)
    doc = json.loads(p.read_text(encoding="utf-8"))
    other = json.loads(json.dumps(doc["body"]))   # deep copy
    other["strategies"][0]["weight"] = 0.99       # A' ≠ A
    forged_digest = hashlib.sha256(json.dumps(
        other, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode()).hexdigest()
    bad = _write_raw(tmp_path, doc["body"], forged_digest)   # body A kept
    with pytest.raises(MetaFileError, match="digest mismatch"):
        read_allocation_file(bad)


def test_reader_contract_is_integrity_not_provenance(tmp_path):
    """Documented trust boundary: a CONSISTENT digest over foreign ids
    passes the file contract (integrity), because provenance is enforced
    downstream — the EA seam trades UNKNOWN ids at ZERO under a FRESH
    (Meta-authoritative) allocation, never at baseGate."""
    p = tmp_path / "a.json"
    write_allocation_file(_decision(), p)
    doc = json.loads(p.read_text(encoding="utf-8"))
    foreign = json.loads(json.dumps(doc["body"]))
    foreign["strategies"][0]["id"] = "rogue"
    payload = json.dumps(foreign, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True)
    ok = _write_raw(tmp_path, foreign,
                    hashlib.sha256(payload.encode()).hexdigest())
    body = read_allocation_file(ok)               # integrity holds
    assert {e["id"] for e in body["strategies"]} == {"rogue", "beta"}


def test_malformed_digest_rejected(tmp_path):
    p = tmp_path / "a.json"
    write_allocation_file(_decision(), p)
    doc = json.loads(p.read_text(encoding="utf-8"))
    bad = _write_raw(tmp_path, doc["body"], "z" * 64)
    with pytest.raises(MetaFileError):
        read_allocation_file(bad)


def test_missing_digest_rejected(tmp_path):
    p = tmp_path / "a.json"
    write_allocation_file(_decision(), p)
    doc = json.loads(p.read_text(encoding="utf-8"))
    q = tmp_path / "b.json"
    q.write_text(json.dumps({"body": doc["body"]}), encoding="utf-8")
    with pytest.raises(MetaFileError):
        read_allocation_file(q)


def test_truncated_file_rejected(tmp_path):
    p = tmp_path / "a.json"
    write_allocation_file(_decision(), p)
    doc = p.read_text(encoding="utf-8")
    q = tmp_path / "c.json"
    q.write_text(doc[: len(doc) // 2], encoding="utf-8")
    with pytest.raises(MetaFileError):
        read_allocation_file(q)
