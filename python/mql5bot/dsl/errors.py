"""mql5bot.dsl.errors — typed DSL failures.

Every failure carries a stable machine code + a human explanation.
Invalid specs are REJECTED WHOLE: nothing is silently repaired into
executable behavior (SPEC §9, mission §7/§41).
"""

from __future__ import annotations


class DslError(Exception):
    """Base class: ``code`` is stable, ``message`` is human-oriented."""

    code = "DSL_ERROR"

    def __init__(self, message: str, *, path: str = ""):
        self.message = message
        self.path = path
        loc = f" at `{path}`" if path else ""
        super().__init__(f"{self.code}{loc}: {message}")

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message,
                "path": self.path}


class SchemaInvalid(DslError):
    code = "SCHEMA_INVALID"


class UnsupportedConstruct(DslError):
    code = "UNSUPPORTED_CONSTRUCT"


class AmbiguousParameter(DslError):
    """An unresolved ``{"ambiguous": ...}`` value or a ``{"param": ...}``
    reference without a default.  Drafts MAY carry these; the runtime
    refuses to execute a spec that has any."""

    code = "AMBIGUOUS_PARAMETER"


class UnknownReference(DslError):
    code = "UNKNOWN_REFERENCE"


class LimitExceeded(DslError):
    """Resource limits (doc size, node count, depth, indicator count)."""

    code = "LIMIT_EXCEEDED"


class NotExecutable(DslError):
    """Spec is valid but cannot run in the requested mode (e.g. a
    filter needs a data series the caller did not provide)."""

    code = "NOT_EXECUTABLE"
