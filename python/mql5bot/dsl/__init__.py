"""mql5bot.dsl — the canonical Strategy DSL (Release B).

Strategies are DATA: a versioned, validated, normalized JSON document
interpreted deterministically into signal series.  The DSL never
trades, never authorizes risk, never executes arbitrary code.

Public API:

- :func:`parse_spec` / :func:`parse_file` — document → StrategySpec
- :class:`StrategySpec` — frozen parsed artifact (spec_hash,
  semantic_hash, ambiguities, ``executable``)
- :func:`desired_positions` — spec + OHLC frame → {−1, 0, +1} series
- :func:`exit_params` — SL/TP/trailing geometry for the engine seam
- :func:`validate_document_size` / schema limits — resource bounds
"""

from __future__ import annotations

from .errors import (
                     AmbiguousParameter,
                     DslError,
                     LimitExceeded,
                     NotExecutable,
                     SchemaInvalid,
                     UnknownReference,
                     UnsupportedConstruct,
)
from .model import (
                     EntrySpec,
                     ExitSpec,
                     Filters,
                     IndicatorDef,
                     MarketSpec,
                     StopModel,
                     StrategySpec,
)
from .normalize import canon_json, normalize_spec, semantic_hash, spec_hash
from .parse import lint_spec, load_document, parse_file, parse_spec
from .runtime import (
                     compute_indicators,
                     desired_positions,
                     eval_condition,
                     eval_operand,
                     exit_params,
)
from .schema import (
                     MAX_CONDITION_NODES,
                     MAX_DEPTH,
                     MAX_DOC_BYTES,
                     MAX_INDICATORS,
                     SCHEMA_VERSION,
                     validate_document_size,
                     validate_spec,
)

__all__ = [
                     "MAX_CONDITION_NODES",
                     "MAX_DEPTH",
                     "MAX_DOC_BYTES",
                     "MAX_INDICATORS",
                     "SCHEMA_VERSION",
                     "AmbiguousParameter",
                     "DslError",
                     "EntrySpec",
                     "ExitSpec",
                     "Filters",
                     "IndicatorDef",
                     "LimitExceeded",
                     "MarketSpec",
                     "NotExecutable",
                     "SchemaInvalid",
                     "StopModel",
                     "StrategySpec",
                     "UnknownReference",
                     "UnsupportedConstruct",
                     "canon_json",
                     "compute_indicators",
                     "compute_spec_hash",
                     "desired_positions",
                     "eval_condition",
                     "eval_operand",
                     "exit_params",
                     "lint_spec",
                     "load_document",
                     "normalize_spec",
                     "parse_file",
                     "parse_spec",
                     "semantic_hash",
                     "spec_hash",
                     "validate_document_size",
                     "validate_spec",
]
