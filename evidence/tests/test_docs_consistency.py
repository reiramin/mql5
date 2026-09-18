"""Documentation consistency (meta-production mission, Phases 1-2).

Rejects: implementation-exists + contract claims "CONTRACT ONLY";
contract-version disagreement between the contract document, the Python
producer (`CONTRACT_VERSION`), the MQL5 consumer header, and the EA; and
a contract document without the lifecycle status line.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python"))

CONTRACT = REPO / "docs/META_LAYER_CONTRACT.md"
ALLOCATION_MQH = REPO / "mql5/Include/Mql5Bot/Allocation.mqh"
EA = REPO / "mql5/Experts/Mql5Bot/Mql5Bot.mq5"
META_PY = REPO / "python/mql5bot/meta_layer.py"


def _contract_version() -> str:
    m = re.search(r"Contract version:\s*([0-9.]+)",
                  CONTRACT.read_text(encoding="utf-8"))
    assert m, "contract header missing 'Contract version:'"
    return m.group(1)


def test_one_authoritative_contract_version_everywhere():
    v = _contract_version()
    from mql5bot.meta_layer import CONTRACT_VERSION
    assert CONTRACT_VERSION == v, (
        f"meta_layer.py declares {CONTRACT_VERSION}, contract doc says {v}")
    mqh = ALLOCATION_MQH.read_text(encoding="utf-8")
    assert f"contract {v}" in mqh, "Allocation.mqh header version stale"
    ea = EA.read_text(encoding="utf-8")
    assert f"contract {v}" in ea, "EA allocation reference version stale"
    # the producer actually EMITS the authoritative version in journals
    from mql5bot.meta_layer import MetaConfig, MetaLayer
    versions = MetaLayer(MetaConfig())._versions()
    assert versions["contract_version"] == v


def test_implementation_exists_contract_may_not_claim_contract_only():
    impl = META_PY.read_text(encoding="utf-8")
    assert "class MetaLayer" in impl, "precondition: implementation present"
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "CONTRACT ONLY" not in doc, (
        "contract claims CONTRACT ONLY while the implementation exists")
    assert "No Meta Layer code exists" not in doc


def test_contract_declares_lifecycle_status():
    doc = CONTRACT.read_text(encoding="utf-8")
    assert "IMPLEMENTED — SOFTWARE PASS" in doc
    assert "EMPIRICAL VALIDATION" in doc
    # activation requirements are explicit and current: DISABLED default,
    # SHADOW_ONLY as max state, EW standing policy documented
    from mql5bot.meta_layer import Activation, MetaConfig, MetaLayer
    assert MetaLayer(MetaConfig()).activation == Activation.DISABLED
    assert "SHADOW_ONLY" in doc or "SHADOW-READY" in doc
    assert "EQUAL_WEIGHT" in doc or "EQUAL" in doc.upper()


def test_journal_and_decision_versions_still_declared():
    """Contract-version fix must not have touched the wire versions."""
    from mql5bot.meta_layer import (
        ALLOCATION_SCHEMA_VERSION,
        DECISION_VERSION,
        META_LAYER_VERSION,
    )
    assert META_LAYER_VERSION == "1.0.0"
    assert DECISION_VERSION == "1.0.0"
    assert ALLOCATION_SCHEMA_VERSION == "1"


def test_version_consistency_doc_exists_and_matches():
    doc = (REPO / "docs/VERSION_CONSISTENCY.md").read_text(encoding="utf-8")
    v = _contract_version()
    assert f"**Meta contract** | **{v}**" in doc
    assert "CONTRACT_VERSION" in doc
