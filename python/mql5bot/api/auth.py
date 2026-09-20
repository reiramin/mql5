"""Console authentication — one owner token, one signed session cookie.

The console previously had NO authentication: anyone who reached the port
could stop the bot or reset the kill switch. This module adds the minimal
honest fix, stdlib-only:

  * ONE owner token from the environment (``MQL5BOT_CONSOLE_TOKEN``). Never a
    default, never a literal, never logged or rendered.
  * A login page exchanges the token for a SIGNED session cookie. The cookie
    value is an HMAC of a fixed payload keyed by the token, so it cannot be
    forged without the token and holds no secret material itself.
  * Every comparison is constant-time (``hmac.compare_digest``), and the
    submitted token is hashed before comparison so even its LENGTH does not
    leak through timing.

Auth is enforced when the token is configured. With no token configured the
app runs in trusted loopback-only mode — and the runner (``api/__main__.py``)
REFUSES to bind any non-loopback host in that mode.
"""

from __future__ import annotations

import hashlib
import hmac

ENV_CONSOLE_TOKEN = "MQL5BOT_CONSOLE_TOKEN"
SESSION_COOKIE = "mql5bot_console_session"
_SESSION_PAYLOAD = b"mql5bot-console-session-v1"


def session_value(token: str) -> str:
    """The signed cookie value for a valid session: HMAC-SHA256 of a fixed
    payload keyed by the owner token. Deriving it requires the token; the
    cookie itself never contains the token."""
    return hmac.new(token.encode("utf-8"), _SESSION_PAYLOAD,
                    hashlib.sha256).hexdigest()


def token_matches(submitted: str, token: str) -> bool:
    """Constant-time token check. Both sides are hashed first so neither the
    content nor the LENGTH of the wrong guess shortens the comparison."""
    a = hashlib.sha256(submitted.encode("utf-8")).digest()
    b = hashlib.sha256(token.encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


def session_valid(cookie_value: str | None, token: str) -> bool:
    """Constant-time session-cookie check against the expected signature."""
    if not cookie_value:
        return False
    return hmac.compare_digest(cookie_value.encode("utf-8"),
                               session_value(token).encode("utf-8"))


__all__ = [
    "ENV_CONSOLE_TOKEN",
    "SESSION_COOKIE",
    "session_valid",
    "session_value",
    "token_matches",
]
