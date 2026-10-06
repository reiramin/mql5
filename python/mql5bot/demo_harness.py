"""mql5bot.demo_harness - the no-click demo harness for the safety tests the
Strategy Tester cannot run: restart, netting, hedging
(docs/SAFETY_DEMO_PLAN.md).

The Windows agent runs ``tools/demo_safety_harness.py run --test <t> ...``.
For each run the harness:

* writes an EA preset (``MQL5\\Presets\\mql5bot_demo_<test>.set``,
  ``InpTestDemoProbe`` set, no secrets) into the terminal data folder;
* writes a ``[StartUp]`` config ini to a fresh TEMP directory OUTSIDE the
  repository (it holds the demo Login / Password / Server, read from a LOCAL
  accounts file outside the repository, never committed); the ini is deleted
  as soon as the EA reports START, and always on exit;
* starts ``terminal64.exe /config:<ini>``, follows the EA's own log file
  (``MQL5\\Files\\Mql5Bot\\Logs\\mql5bot_<SYMBOL>_M1_<date>.log``; the EA
  re-creates it on every start, so lines are buffered as they appear), and
  for ``restart`` KILLS the terminal process while the probe position is
  open, then relaunches it;
* writes ``<out>\\<test>\\ealog.txt`` (the EA lines of this run) and
  ``run.json`` (steps, UTC times, the EX5 sha256; never the login, password
  or server).

The stage-8 builder grades ealog.txt with mql5bot.safety_legs and the
verifier re-grades it. Nothing here asserts a result.

Built, unit-tested with a fake terminal; never run against MT5.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from mql5bot import gate_selfcheck as gs
from mql5bot import mt5tester as mt
from mql5bot.owner_gate import path_within

SYMBOL = "EURUSD"
PERIOD = "M1"
EA_REL = Path("MQL5") / "Experts" / "Mql5Bot" / "Mql5Bot.ex5"
LOG_DIR_REL = Path("MQL5") / "Files" / "Mql5Bot" / "Logs"
PRESET_DIR_REL = Path("MQL5") / "Presets"
PROBE = {"restart": 1, "account": 2, "cleanup": 3}
ACCOUNT_ROLE = {"restart": "hedging", "netting": "netting",
                "hedging": "hedging"}
ACCOUNTS_ENV = "MQL5BOT_DEMO_ACCOUNTS"
TESTS = ("restart", "netting", "hedging")


class HarnessError(RuntimeError):
    """A refused or failed harness step (the message names it)."""


def default_accounts_path() -> Path:
    env = os.environ.get(ACCOUNTS_ENV)
    if env:
        return Path(env)
    return Path.home() / ".mql5bot" / "demo_accounts.json"


def load_account(path: Path | str, role: str, repo: Path | str) -> dict:
    """The demo account for ``role`` (hedging / netting) from the LOCAL
    accounts file: {"hedging": {"login", "password", "server"}, "netting":
    {...}}. Refused when the file lies inside the repository."""
    path = Path(path)
    if path_within(path.resolve(), Path(repo).resolve()):
        raise HarnessError(f"accounts file {path} is inside the repository: "
                           "credentials never live in the repo")
    if not path.is_file():
        raise HarnessError(f"no accounts file at {path} (set {ACCOUNTS_ENV} "
                           "or create it; docs/SAFETY_DEMO_PLAN.md)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    acc = doc.get(role) if isinstance(doc, dict) else None
    if not isinstance(acc, dict) or not all(
            str(acc.get(k) or "").strip() for k in ("login", "password",
                                                    "server")):
        raise HarnessError(f"accounts file has no complete {role!r} entry "
                           "(login, password, server)")
    return {"login": str(acc["login"]).strip(),
            "password": str(acc["password"]),
            "server": str(acc["server"]).strip()}


def preset_text(probe: int) -> str:
    """The EA .set for a demo run: the EA defaults (the compiled strategy;
    strategy entries are skipped while the probe runs) + InpTestDemoProbe."""
    inputs = dict(mt.EA_INPUT_DEFAULTS)
    inputs["InpTestDemoProbe"] = int(probe)
    return mt.render_set(mt.inputs_to_lines(inputs),
                         header="mql5bot demo harness preset (no secrets)")


def startup_ini(account: dict, preset_name: str, symbol: str = SYMBOL,
                period: str = PERIOD) -> str:
    """The terminal's [StartUp] config: log in to the demo account, allow
    algo trading, attach the EA with the preset to one chart."""
    return "\r\n".join([
        "[Common]",
        f"Login={account['login']}",
        f"Password={account['password']}",
        f"Server={account['server']}",
        "[Experts]",
        "AllowLiveTrading=1",
        "AllowDllImport=0",
        "Enabled=1",
        "Account=0",
        "Profile=0",
        "[StartUp]",
        r"Expert=Mql5Bot\Mql5Bot",
        f"ExpertParameters={preset_name}",
        f"Symbol={symbol}",
        f"Period={period}",
        "",
    ])


class EaLogFollower:
    """Buffers the EA log lines as they appear. The EA re-creates its log
    file on every start (FileOpen FILE_WRITE truncates), so a shrink resets
    the read position; the buffer keeps every line already seen."""

    def __init__(self, data_folder: Path | str, symbol: str = SYMBOL,
                 period: str = PERIOD):
        self.dir = Path(data_folder) / LOG_DIR_REL
        self.pattern = f"mql5bot_{symbol}_{period}_*.log"
        self.lines: list[str] = []
        # per file: the lines already consumed (content, not a count: a
        # re-created file with as many lines is still a new file)
        self._seen: dict[str, list[str]] = {
            p.name: self._read(p) for p in self._files()}

    def _files(self) -> list[Path]:
        return sorted(self.dir.glob(self.pattern),
                      key=lambda p: p.stat().st_mtime) \
            if self.dir.is_dir() else []

    @staticmethod
    def _read(path: Path) -> list[str]:
        try:
            raw = path.read_bytes()
        except OSError:
            return []
        return [ln for ln in gs.decode_bom_aware(raw).splitlines()
                if ln.strip()]

    def poll(self) -> list[str]:
        new: list[str] = []
        for path in self._files():
            lines = self._read(path)
            seen = self._seen.get(path.name, [])
            # appended to: skip what was seen; else re-created by an EA
            # start (FileOpen FILE_WRITE truncates): all of it is new
            start = len(seen) if lines[:len(seen)] == seen else 0
            new += lines[start:]
            self._seen[path.name] = lines
        self.lines += new
        return new

    def has(self, needle: str, after: int = 0) -> bool:
        return any(needle in ln for ln in self.lines[after:])


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() \
        if path.is_file() else None


class Harness:
    """One demo run. ``launch(argv) -> process`` and ``sleep(s)`` are
    injectable (tests use a fake terminal); defaults are subprocess.Popen
    and time.sleep."""

    def __init__(self, *, test: str, terminal: Path | str,
                 data_folder: Path | str, accounts: Path | str,
                 repo: Path | str, out_dir: Path | str,
                 launch=None, sleep=None, timeout_s: int = 900,
                 hold_s: int = 30, observe_s: int = 90):
        if test not in TESTS:
            raise HarnessError(f"unknown test {test!r}; one of {TESTS}")
        self.test, self.repo = test, Path(repo)
        self.terminal, self.data = Path(terminal), Path(data_folder)
        self.accounts = Path(accounts)
        self.out = Path(out_dir) / test
        self.launch = launch or (lambda argv: subprocess.Popen(argv))
        self.sleep = sleep or time.sleep
        self.timeout_s, self.hold_s, self.observe_s = (timeout_s, hold_s,
                                                       observe_s)
        self.steps: list[dict] = []
        self.log = EaLogFollower(self.data)
        self.proc = None
        self._tmp: Path | None = None

    # -- steps ---------------------------------------------------------
    def _step(self, what: str, **extra) -> None:
        self.steps.append({"utc": _utc(), "step": what, **extra})

    def _write_ini(self, account: dict, probe: int) -> Path:
        preset = f"mql5bot_demo_{self.test}_{probe}.set"
        pdir = self.data / PRESET_DIR_REL
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / preset).write_text(preset_text(probe), encoding="utf-8")
        self._tmp = Path(tempfile.mkdtemp(prefix="mql5bot_demo_"))
        if path_within(self._tmp.resolve(), self.repo.resolve()):
            raise HarnessError("temp dir is inside the repository")
        ini = self._tmp / "startup.ini"
        ini.write_text(startup_ini(account, preset), encoding="utf-16")
        return ini

    def _drop_ini(self) -> None:
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None

    def _start(self, account: dict, probe: int) -> int:
        ini = self._write_ini(account, probe)
        mark = len(self.log.lines)
        self.proc = self.launch([str(self.terminal), f"/config:{ini}"])
        self._step("terminal_started", probe=probe)
        try:
            self._wait("TEST demo: START", mark, "EA START")
        finally:
            self._drop_ini()                    # credentials off the disk
        return mark

    def _wait(self, needle: str, after: int, what: str) -> None:
        waited = 0
        while True:
            self.log.poll()
            if self.log.has(needle, after):
                self._step(f"seen: {what}")
                return
            if waited >= self.timeout_s:
                raise HarnessError(f"timeout after {waited}s waiting for "
                                   f"{what!r} in the EA log")
            self.sleep(1)
            waited += 1

    def _observe(self, seconds: int) -> None:
        for _ in range(seconds):
            self.log.poll()
            self.sleep(1)

    def _kill(self, what: str) -> None:
        if self.proc is not None:
            self.proc.kill()                    # hard kill: no OnDeinit
            try:
                self.proc.wait(timeout=60)
            except Exception as exc:  # noqa: BLE001 -- recorded, not raised
                self._step("wait after kill failed", reason=repr(exc))
            self._step(what)
            self.proc = None

    # -- the tests ---------------------------------------------------------
    def run(self) -> dict:
        account = load_account(self.accounts, ACCOUNT_ROLE[self.test],
                               self.repo)
        self._step("start", test=self.test,
                   account_role=ACCOUNT_ROLE[self.test])
        error = None
        try:
            if self.test == "restart":
                mark = self._start(account, PROBE["restart"])
                self._wait("TEST demo: PROBE position opened", mark,
                           "probe position opened")
                self._observe(self.hold_s)
                self._kill("terminal KILLED with the probe position open")
                self.sleep(10)
                mark = self._start(account, PROBE["restart"])
                self._observe(self.observe_s)
                self._kill("terminal stopped after observation")
                mark = self._start(account, PROBE["cleanup"])
                self._wait("TEST demo: CLEANUP closed", mark, "cleanup")
            else:
                mark = self._start(account, PROBE["account"])
                self._wait("TEST demo: CLEANUP closed", mark,
                           "account probe + cleanup")
        except HarnessError as exc:
            error = str(exc)
            self._step("error", reason=error)
        finally:
            self.log.poll()
            self._kill("terminal stopped")
            self._drop_ini()
        return self._write(error)

    def _write(self, error: str | None) -> dict:
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "ealog.txt").write_text(
            "\n".join(self.log.lines) + "\n", encoding="utf-8")
        rec = {"schema": "mql5bot.demo_safety_run/1", "test": self.test,
               "account_role": ACCOUNT_ROLE[self.test],
               "symbol": SYMBOL, "period": PERIOD,
               "ex5_sha256": sha256_file(self.data / EA_REL),
               "steps": self.steps, "error": error,
               "ea_log_lines": len(self.log.lines),
               "note": ("no login, password or server is recorded; the EA "
                        "log lines are the evidence, graded at stage 8")}
        (self.out / "run.json").write_text(json.dumps(rec, indent=2),
                                           encoding="utf-8")
        return rec
