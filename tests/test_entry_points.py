"""Entry-point tests: each runner imports and parses arguments WITHOUT starting
a server or touching the network, and a missing environment variable fails with
the variable NAMED and its value ABSENT.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest
from mql5bot.notify.telegram import ENV_BOT_TOKEN, ENV_CHAT_ID

# -- python -m mql5bot -------------------------------------------------------

def test_package_main_delegates_to_cli():
    mod = importlib.import_module("mql5bot.__main__")
    from mql5bot.cli import main as cli_main
    assert mod.main is cli_main


# -- python -m mql5bot.api ---------------------------------------------------

def test_api_runner_arg_parsing_without_serving():
    api_main = importlib.import_module("mql5bot.api.__main__")
    args = api_main.build_parser().parse_args(
        ["--host", "0.0.0.0", "--port", "9001", "--db", "x.db"])
    assert args.host == "0.0.0.0"
    assert args.port == 9001
    assert args.db == "x.db"
    # defaults are loopback + 8000
    d = api_main.build_parser().parse_args([])
    assert d.host == "127.0.0.1"
    assert d.port == 8000


def test_api_banner_states_it_is_not_certified():
    api_main = importlib.import_module("mql5bot.api.__main__")
    assert "not certified" in api_main.BANNER.lower() \
        or "nothing here is certified" in api_main.BANNER.lower()
    assert "never mark a strategy LIVE" in api_main.BANNER
    assert "never run live" in api_main.BANNER


def test_api_runner_reports_a_missing_server_dependency_clearly():
    api_main = importlib.import_module("mql5bot.api.__main__")
    if importlib.util.find_spec("uvicorn") is not None:
        pytest.skip("uvicorn is installed; the missing-dependency path "
                    "cannot be exercised here")
    with pytest.raises(api_main.ServerDependencyMissing) as e:
        api_main._load_server()
    assert "uvicorn" in str(e.value)          # names the dependency
    assert "pip install uvicorn" in str(e.value)


# -- python -m mql5bot.notify.telegram_ops -----------------------------------

def test_telegram_runner_arg_parsing_without_network():
    ops = importlib.import_module("mql5bot.notify.telegram_ops")
    args = ops.build_parser().parse_args(
        ["--poll-interval", "5", "--long-poll-timeout", "10"])
    assert args.poll_interval == 5.0
    assert args.long_poll_timeout == 10


def test_telegram_banner_states_stop_yes_resume_no():
    ops = importlib.import_module("mql5bot.notify.telegram_ops")
    banner = ops.BANNER
    assert "stop trading from Telegram" in banner
    assert "CANNOT" in banner and "resume" in banner
    assert "never run live" in banner


def test_telegram_runner_refuses_missing_env_naming_the_variable(capsys):
    ops = importlib.import_module("mql5bot.notify.telegram_ops")
    # empty environment -> refuse, name the missing var, never poll
    rc = ops.main([], env={})
    assert rc == 2
    err = capsys.readouterr().err
    assert ENV_BOT_TOKEN in err                    # the variable is named
    # a placeholder value must never be echoed
    assert "AAF" not in err and "token=" not in err.lower()


def test_telegram_runner_names_the_chat_id_variable_when_token_present(capsys):
    ops = importlib.import_module("mql5bot.notify.telegram_ops")
    # token present but chat id missing -> refuse naming the chat-id variable,
    # and never echo the token value
    fake_token = "123456789:AAF-FAKE-do-not-leak"
    rc = ops.main([], env={ENV_BOT_TOKEN: fake_token})
    assert rc == 2
    err = capsys.readouterr().err
    assert ENV_CHAT_ID in err
    assert fake_token not in err                   # value absent
