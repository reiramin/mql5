"""Console v2 foundation tests: auth, hygiene, shell, live-update fallbacks.

No test starts a server or touches the network.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

from fastapi.testclient import TestClient
from mql5bot.api import auth as auth_mod
from mql5bot.api.main import create_app
from mql5bot.factory.store import FactoryStore

TOKEN = "test-owner-token-not-a-secret"


def _client(tmp_path, **kw):
    store = FactoryStore(tmp_path / "api.db")
    return store, TestClient(create_app(store, **kw))


def _get_paths(app):
    """Every concrete GET-able route path (path params filled with 'x')."""
    paths = []
    for r in app.routes:
        path = getattr(r, "path", "")
        methods = getattr(r, "methods", set()) or set()
        if not path or "GET" not in methods:
            continue
        if path in ("/openapi.json", "/docs", "/docs/oauth2-redirect",
                    "/redoc"):
            continue
        paths.append(path.replace("{sid}", "x")
                         .replace("{campaign_id}", "x"))
    return paths


# ---- hygiene: a fresh start writes nothing into the repo -------------------

def test_gitignore_excludes_local_databases():
    gi = Path(".gitignore").read_text(encoding="utf-8")
    assert "*.db" in gi
    assert "factory.db" in gi


def test_default_db_path_is_outside_the_repository():
    api_main = importlib.import_module("mql5bot.api.__main__")
    db = api_main.default_db_path().resolve()
    repo = Path.cwd().resolve()
    assert repo not in db.parents
    assert db != repo
    # and the parser default is None (resolved to the per-user dir at runtime)
    assert api_main.build_parser().parse_args([]).db is None


# ---- authentication ---------------------------------------------------------

def test_unauthenticated_request_to_every_route_redirects_to_login(tmp_path):
    _, c = _client(tmp_path, console_token=TOKEN)
    app = c.app
    for path in _get_paths(app):
        if path in ("/login", "/logout"):
            continue
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303, f"{path}: {r.status_code}"
        assert r.headers["location"] == "/login", path


def test_wrong_token_fails_and_sets_no_cookie(tmp_path):
    _, c = _client(tmp_path, console_token=TOKEN)
    r = c.post("/login", data={"token": "wrong"}, follow_redirects=False)
    assert r.status_code == 403
    assert auth_mod.SESSION_COOKIE not in r.cookies
    # and the wrong guess still cannot reach a page
    r2 = c.get("/", follow_redirects=False)
    assert r2.status_code == 303


def test_token_comparison_is_constant_time_by_construction():
    # the comparison hashes BOTH sides and uses hmac.compare_digest — neither
    # the content nor the length of a wrong guess shortens the comparison
    src = inspect.getsource(auth_mod)
    assert "compare_digest" in src
    assert src.count("sha256") >= 2
    assert auth_mod.token_matches("a", "a") is True
    assert auth_mod.token_matches("a", "b") is False
    assert auth_mod.token_matches("", "b") is False


def test_correct_token_logs_in_and_logout_clears(tmp_path):
    _, c = _client(tmp_path, console_token=TOKEN)
    r = c.post("/login", data={"token": TOKEN}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert c.get("/", follow_redirects=False).status_code == 200
    # the cookie never contains the token itself
    assert TOKEN not in c.cookies.get(auth_mod.SESSION_COOKIE, "")
    c.get("/logout", follow_redirects=False)
    assert c.get("/", follow_redirects=False).status_code == 303


def test_token_never_rendered_on_any_page(tmp_path):
    _, c = _client(tmp_path, console_token=TOKEN)
    c.post("/login", data={"token": TOKEN})
    for path in ("/", "/strategies", "/new", "/trades", "/certification",
                 "/settings", "/login"):
        assert TOKEN not in c.get(path).text, path


def test_runner_refuses_non_loopback_host_without_token(capsys):
    api_main = importlib.import_module("mql5bot.api.__main__")
    rc = api_main.main(["--host", "0.0.0.0"], env={})
    assert rc == 2
    err = capsys.readouterr().err
    assert auth_mod.ENV_CONSOLE_TOKEN in err
    assert "loopback" in err


def test_no_auth_mode_keeps_existing_routes_open(tmp_path):
    # with no token configured the app runs in trusted loopback mode — the
    # legacy routes stay open and render on the shared offline shell
    _, c = _client(tmp_path)
    assert c.get("/").status_code == 200


# ---- shell, sections, empty states ------------------------------------------

def test_new_sections_render_in_both_languages_with_banner(tmp_path):
    _, c = _client(tmp_path)
    for path in ("/strategies", "/new", "/trades", "/certification",
                 "/settings"):
        en = c.get(path)
        assert en.status_code == 200, path
        assert "Not yet proven:" in en.text, path
        fa = c.get(path + "?lang=fa")
        assert fa.status_code == 200, path
        assert 'dir="rtl"' in fa.text, path
        assert "هنوز اثبات‌نشده" in fa.text, path


def test_trades_page_shows_not_connected_never_zero(tmp_path):
    _, c = _client(tmp_path)
    en = c.get("/trades")
    assert "not connected" in en.text
    fa = c.get("/trades?lang=fa")
    assert "وصل نیست" in fa.text


def test_certification_page_says_not_configured_without_evidence(tmp_path):
    _, c = _client(tmp_path, console_env={})
    r = c.get("/certification")
    assert "not configured" in r.text
    assert "MQL5BOT_EVIDENCE_DIR" in r.text


def test_telemetry_proxy_is_503_when_not_configured(tmp_path):
    _, c = _client(tmp_path, console_env={})
    assert c.get("/telemetry/latest").status_code == 503
    assert c.get("/telemetry/stream").status_code == 503


def test_no_route_can_promote_toward_execution(tmp_path):
    # No route path or method suggests SHADOW/DEMO/LIVE promotion; the only
    # lifecycle actions the UI owns are pause/retire/resume + approvals that
    # the store re-validates. Walk every route and check its path.
    _, c = _client(tmp_path)
    for r in c.app.routes:
        path = getattr(r, "path", "").lower()
        for forbidden in ("promote", "golive", "go-live", "shadow", "demo",
                          "live_small"):
            assert forbidden not in path, path