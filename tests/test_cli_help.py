"""CLI help regression (FINAL CONVERGENCE): literal '%' in argparse help
strings broke `--help` for every subcommand using the cost arguments
(TypeError: %o format). Help must render for ALL subcommands."""

import subprocess
import sys

import pytest

SUBCOMMANDS = ("data", "backtest", "compare", "optimize", "walkforward",
               "dashboard")


@pytest.mark.parametrize("cmd", SUBCOMMANDS)
def test_help_renders_for_every_subcommand(cmd):
    r = subprocess.run([sys.executable, "-m", "mql5bot.cli", cmd, "--help"],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, f"{cmd} --help failed: {r.stderr[-300:]}"
    assert "--help" in r.stdout
