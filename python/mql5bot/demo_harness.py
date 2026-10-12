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
* ALWAYS ends by logging the terminal back in to the "hedging" account
  (SAFETY-DEMO-RESTORE-1): one more start with the cleanup probe, whose
  START line must report the hedging margin mode. If that restore fails,
  the run is FAILED (``status``), whatever the test itself showed;
* then (DEMO-LOGIN-PERSIST-1) logs in to the hedging account once more with
  ``KeepPrivate=1`` and a script that shuts the terminal down by itself, so
  the terminal keeps the password in ITS OWN encrypted store and writes its
  state on a clean exit; and VERIFIES it with a credential-less launch
  shaped exactly like the gate's stage-3 export (no ``[Common]``): the run
  FAILs unless that launch reports a connected terminal on the hedging
  account;
* writes ``<out>\\<test>\\ealog.txt`` (the EA lines of the test),
  ``restore_ealog.txt`` (the EA lines of the restore) and ``run.json``
  (status, steps, UTC times, the EX5 sha256, the restore record with the
  HASHED login and the margin mode; never the login, password or server).

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
from mql5bot import safety_legs as sl
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
RESTORE_ROLE = "hedging"     # the terminal's account after every run
# the EA's own refusal when it initialised before the terminal finished
# logging in (gate_run40 netting: stale server time, probe acted as 0,
# then "symbol spec build failed" and the EA shut down)
EA_NOT_LOGGED_IN = "REFUSED: honoured only on a logged-in DEMO account"
START_LAUNCHES = 2           # one relaunch for a start before the login
# DEMO-LOGIN-PERSIST-1: the credential-less connection check after the
# restore runs the gate's own exporter (stage 3, owner_gate.ps1
# Invoke-SymbolSpecExport) into a separate folder, never the gate's
EXPORT_SCRIPT = r"Mql5Bot\Mql5BotExportSymbolSpec"
CHECK_DIR_REL = Path("MQL5") / "Files" / "Mql5Bot" / "demo_connect_check"
CHECK_PRESET = "mql5bot_demo_connect_check.set"
NOT_CONNECTED = "terminal not connected"   # the exporter's sync_unmet text
LOGIN_HASH_PREFIX = "mql5bot-demo-login:"


def login_sha256(login: str) -> str:
    """The recorded form of a demo login: sha256 over a fixed prefix + the
    login. It identifies which configured account was restored without
    writing the login itself. NOT secret-grade: an MT5 login is a short
    number, so the hash can be brute-forced; it is never a credential."""
    return hashlib.sha256(
        (LOGIN_HASH_PREFIX + str(login).strip()).encode("utf-8")).hexdigest()


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


def common_login(account: dict) -> list[str]:
    """The [Common] login lines. KeepPrivate=1 makes the terminal keep the
    password in its own encrypted account store, so a later launch WITHOUT
    credentials (every gate launch) still connects (DEMO-LOGIN-PERSIST-1:
    gate_run40/44/46 stage 3 "terminal not connected" after the harness)."""
    return ["[Common]",
            f"Login={account['login']}",
            f"Password={account['password']}",
            f"Server={account['server']}",
            "KeepPrivate=1"]


def startup_ini(account: dict, preset_name: str, symbol: str = SYMBOL,
                period: str = PERIOD) -> str:
    """The terminal's [StartUp] config: log in to the demo account, allow
    algo trading, attach the EA with the preset to one chart."""
    return "\r\n".join([
        *common_login(account),
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


def export_ini(account: dict | None, symbol: str = SYMBOL) -> str:
    """Run the gate's exporter script on ``symbol`` and shut the terminal
    down when it ends (a clean exit). With ``account`` it logs in first
    (the persist step); without, it is the gate's own credential-less
    stage-3 launch shape (owner_gate.ps1 Invoke-TerminalScript)."""
    lines = common_login(account) if account is not None else []
    return "\r\n".join([
        *lines,
        "[StartUp]",
        f"Script={EXPORT_SCRIPT}",
        f"Symbol={symbol}",
        f"ScriptParameters={CHECK_PRESET}",
        "ShutdownTerminal=1",
        "",
    ])


def check_preset_text() -> str:
    return "\r\n".join([r"InpExportDir=Mql5Bot\demo_connect_check" + "\\",
                         "InpDenomProbeTicks=100", ""])


def write_crlf_text(path: Path, text: str, encoding: str) -> None:
    r"""Write MT5 config text that already carries its CRLF line ends,
    byte-exact (DEMO-CHECK-CRLF-1). Text mode on Windows turns every LF
    into CRLF, so the CRLF-joined text became CR CR LF. MT5 kept the stray
    CR in the preset value: gate_run52's connection check opened
    `Mql5Bot\demo_connect_check\<CR>EURUSD.json` -> err=5004, no export,
    stage 7 FAIL on a terminal that HAD connected."""
    path.write_text(text, encoding=encoding, newline="")


# --- DEMO-IN-GATE-1: owner_gate.ps1 -DemoSafety ----------------------------
# The gate runs the harness itself, with THIS run's stage-1 EX5 (a demo run
# bound to another compile's EX5 is rejected at stage 8, gate_run47). These
# are the gate's decisions about it (tools/owner_gate_decide.py).

def fx_market_closed(now: datetime) -> str | None:
    """None while the FX market is open, else the reason it is closed.
    The weekly close (Friday ~21:00/22:00 UTC) and re-open (Sunday
    ~21:00/22:00 UTC) and the daily rollover (~23:55-00:05 server time,
    UTC+2/+3) move with daylight saving, so every edge is widened: closed
    Friday 20:00 - Sunday 22:15 UTC, and 20:45 - 22:15 UTC every day, so a
    demo session never straddles one (docs/SAFETY_DEMO_PLAN.md "Market
    hours")."""
    now = now.astimezone(timezone.utc)
    wd, hm = now.weekday(), now.hour * 60 + now.minute   # Monday 0 .. Sunday 6
    stamp = f"{now:%a %Y-%m-%d %H:%M} UTC"
    if wd == 5 or (wd == 4 and hm >= 20 * 60) or (wd == 6 and hm < 22 * 60 + 15):
        return (f"FX market closed at {stamp} (weekly close: Fri 20:00 - "
                "Sun 22:15 UTC)")
    if 20 * 60 + 45 <= hm < 22 * 60 + 15:
        return (f"FX daily rollover at {stamp} (orders refused around "
                "server midnight: 20:45 - 22:15 UTC)")
    return None


def demo_preflight(accounts: Path | str, repo: Path | str,
                   now: datetime) -> dict:
    """May the gate run the demo harness now? Refuses (named, never a
    pass) when the accounts file lacks a complete hedging or netting entry,
    or the market is closed. Never reads out a credential."""
    reasons: list[str] = []
    for role in ("hedging", "netting"):
        try:
            load_account(accounts, role, repo)
        except HarnessError as exc:
            why = f"[demo_accounts_missing] {exc}"
            if why not in reasons:
                reasons.append(why)
        except (OSError, ValueError) as exc:
            reasons.append(f"[demo_accounts_missing] accounts file "
                           f"unreadable: {type(exc).__name__}")
            break
    closed = fx_market_closed(now)
    if closed:
        reasons.append(f"[market_closed] {closed}")
    return {"ok": not reasons, "reasons": reasons,
            "accounts": str(accounts), "now": now.isoformat()}


def demo_in_gate_outcome(out_dir: Path | str) -> dict:
    """After the gate's harness runs: is the terminal left logged in to the
    hedging account, its password kept, a credential-less launch connected?
    Every run's restore (with its connection check, DEMO-LOGIN-PERSIST-1)
    must hold; otherwise the gate FAILs loudly. The tests themselves are
    graded at stage 8, never here."""
    tests: dict = {}
    reasons: list[str] = []
    for t in TESTS:
        run = Path(out_dir) / t / "run.json"
        if not run.is_file():
            reasons.append(f"[demo_run_missing] {t}: no {run}")
            continue
        try:
            rec = json.loads(run.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            reasons.append(f"[demo_run_missing] {t}: {run} unreadable: "
                           f"{type(exc).__name__}")
            continue
        restore = rec.get("restore") if isinstance(rec, dict) else None
        restore = restore if isinstance(restore, dict) else {}
        cc = restore.get("connect_check")
        tests[t] = {"status": rec.get("status"),
                    "error": rec.get("error"),
                    "restore_ok": restore.get("ok"),
                    "connect_check": cc}
        if restore.get("ok") is not True or not isinstance(cc, dict) \
                or cc.get("sync_unmet") == NOT_CONNECTED:
            reasons.append(
                f"[demo_restore_not_connected] {t}: "
                f"{restore.get('reason') or 'no connection check recorded'}")
    return {"ok": not reasons, "reasons": reasons, "tests": tests,
            "out_dir": str(out_dir)}


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
        self.restore_lines: list[str] = []

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
        write_crlf_text(ini, startup_ini(account, preset), "utf-16")
        return ini

    def _drop_ini(self) -> None:
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None

    def _start(self, account: dict, probe: int) -> int:
        """Launch the terminal and wait for the EA's START line. When the
        EA initialised before the login completed (EA_NOT_LOGGED_IN: it
        refused the probe and shut down, so nothing was traded) the
        terminal is stopped and launched once more."""
        for launch_no in range(1, START_LAUNCHES + 1):
            ini = self._write_ini(account, probe)
            mark = len(self.log.lines)
            self.proc = self.launch([str(self.terminal), f"/config:{ini}"])
            self._step("terminal_started", probe=probe)
            try:
                started = self._wait_start(mark)
            finally:
                self._drop_ini()                # credentials off the disk
            if started:
                break
            self._kill("terminal stopped: the EA started before the login "
                       "completed")
            if launch_no == START_LAUNCHES:
                raise HarnessError(
                    f"the EA refused the demo probe on {START_LAUNCHES} "
                    "launches: not a logged-in DEMO account when it "
                    f"initialised ({EA_NOT_LOGGED_IN!r})")
            self.sleep(10)
        return mark

    def _wait_start(self, after: int) -> bool:
        """True on the START line; False on the EA's not-logged-in
        refusal; HarnessError on timeout."""
        waited = 0
        while True:
            self.log.poll()
            if self.log.has("TEST demo: START", after):
                self._step("seen: EA START")
                return True
            if self.log.has(EA_NOT_LOGGED_IN, after):
                self._step("seen: EA refused the probe before the login "
                           "completed")
                return False
            if waited >= self.timeout_s:
                raise HarnessError(f"timeout after {waited}s waiting for "
                                   "'EA START' in the EA log")
            self.sleep(1)
            waited += 1

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
        self._step("start", test=self.test,
                   account_role=ACCOUNT_ROLE[self.test])
        error = None
        try:
            account = load_account(self.accounts, ACCOUNT_ROLE[self.test],
                                   self.repo)
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
        except (HarnessError, OSError) as exc:
            error = str(exc)
            self._step("error", reason=error)
        finally:
            self.log.poll()
            self._kill("terminal stopped")
            self._drop_ini()
        test_lines = list(self.log.lines)
        restore = self._restore()
        if not restore["ok"]:
            error = f"{error}; {restore['reason']}" if error \
                else restore["reason"]
        return self._write(error, test_lines, restore)

    def _restore(self) -> dict:
        """Log the terminal back in to the "hedging" account, ALWAYS (also
        after a failed test). Started with the cleanup probe, so the EA's
        START line reports the account's margin mode; the restore holds
        only when mql5bot.safety_legs.check_restore accepts those lines."""
        rec = {"account_role": RESTORE_ROLE, "login_sha256": None,
               "margin_mode": None, "ok": False, "reason": ""}
        mark = len(self.log.lines)
        try:
            account = load_account(self.accounts, RESTORE_ROLE, self.repo)
            rec["login_sha256"] = login_sha256(account["login"])
            self._step("restore: log back in to the hedging account")
            self._start(account, PROBE["cleanup"])
            self._wait("TEST demo: CLEANUP closed", mark, "restore cleanup")
        except (HarnessError, OSError) as exc:
            rec["reason"] = f"restore failed: {exc}"
        finally:
            self.log.poll()
            self._kill("terminal stopped after restore")
            self._drop_ini()
        self.restore_lines = self.log.lines[mark:]
        chk = sl.check_restore("\n".join(self.restore_lines))
        rec["margin_mode"] = chk["margin_mode"]
        if not rec["reason"] and not chk["ok"]:
            rec["reason"] = f"restore failed: {chk['reason']}"
        if not rec["reason"]:
            # DEMO-LOGIN-PERSIST-1: the restore above ends in a hard kill;
            # log in once more with KeepPrivate=1 and let the terminal exit
            # by itself, then prove a credential-less launch connects
            try:
                self._step("restore: persist the hedging login "
                           "(KeepPrivate=1, terminal exits by itself)")
                self._script_run(account, "persist hedging login")
                rec["connect_check"] = self._verify_connection()
            except (HarnessError, OSError) as exc:
                rec["reason"] = f"restore failed: {exc}"
            finally:
                self._drop_check_export()
        rec["ok"] = not rec["reason"]
        self._step("restore", ok=rec["ok"])
        return rec

    # -- DEMO-LOGIN-PERSIST-1 ------------------------------------------------
    def _check_export(self) -> Path:
        return self.data / CHECK_DIR_REL / f"{SYMBOL}.json"

    def _drop_check_export(self) -> None:
        """The export carries the account login: never left behind."""
        try:
            self._check_export().unlink()
        except FileNotFoundError:
            pass

    def _script_run(self, account: dict | None, what: str) -> None:
        """Launch the gate's exporter script (logging in first when
        ``account`` is given) and wait for the terminal to EXIT BY ITSELF
        (ShutdownTerminal=1) -- never a kill."""
        pdir = self.data / PRESET_DIR_REL
        pdir.mkdir(parents=True, exist_ok=True)
        write_crlf_text(pdir / CHECK_PRESET, check_preset_text(), "utf-16")
        self._tmp = Path(tempfile.mkdtemp(prefix="mql5bot_demo_"))
        if path_within(self._tmp.resolve(), self.repo.resolve()):
            raise HarnessError("temp dir is inside the repository")
        ini = self._tmp / "startup.ini"
        if account is None:
            # byte-for-byte the gate's own launch shape (ASCII ini)
            write_crlf_text(ini, export_ini(None), "ascii")
        else:
            write_crlf_text(ini, export_ini(account), "utf-16")
        self.proc = self.launch([str(self.terminal), f"/config:{ini}"])
        self._step("terminal_started", script=what)
        try:
            self.proc.wait(timeout=self.timeout_s)
        except subprocess.TimeoutExpired as exc:
            self._kill(f"terminal KILLED: {what} did not exit")
            raise HarnessError(
                f"{what}: the terminal did not exit by itself within "
                f"{self.timeout_s}s (ShutdownTerminal=1)") from exc
        finally:
            self._drop_ini()                    # credentials off the disk
        self.proc = None
        self._step(f"terminal exited by itself: {what}")

    def _verify_connection(self) -> dict:
        """A launch WITHOUT credentials -- the way every gate launch starts
        the terminal -- must connect, on the hedging account. Read from the
        exporter's own fields; the export (it holds the login) is deleted."""
        out = self._check_export()
        self._drop_check_export()
        self._script_run(None, "credential-less connection check")
        if not out.is_file():
            raise HarnessError(
                "connection check: the credential-less launch wrote no "
                f"export ({CHECK_DIR_REL.as_posix()}/{SYMBOL}.json)")
        doc = json.loads(out.read_text(encoding="utf-8"))
        self._drop_check_export()
        sym = doc.get("symbol") if isinstance(doc.get("symbol"), dict) else {}
        probe = sym.get("denomination_probe")
        probe = probe if isinstance(probe, dict) else {}
        chk = {"sync_unmet": probe.get("sync_unmet"),
               "synced": probe.get("synced"),
               "margin_mode": doc.get("account_margin_mode")}
        if "sync_unmet" not in probe:
            raise HarnessError("connection check: the export has no "
                               "denomination_probe.sync_unmet")
        if chk["sync_unmet"] == NOT_CONNECTED:
            raise HarnessError(
                "connection check: a credential-less launch is NOT "
                f"connected (sync_unmet={NOT_CONNECTED!r}); the gate's "
                "launches would fail stage 3 the same way")
        if chk["margin_mode"] != sl.MARGIN_HEDGING:
            raise HarnessError(
                "connection check: the credential-less launch is on "
                f"margin_mode {chk['margin_mode']} (required hedging "
                f"{sl.MARGIN_HEDGING})")
        self._step("connection check: credential-less launch connected",
                   margin_mode=chk["margin_mode"])
        return chk

    def _write(self, error: str | None, test_lines: list[str],
               restore: dict) -> dict:
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "ealog.txt").write_text(
            "\n".join(test_lines) + "\n", encoding="utf-8")
        (self.out / "restore_ealog.txt").write_text(
            "\n".join(self.restore_lines) + "\n", encoding="utf-8")
        rec = {"schema": "mql5bot.demo_safety_run/2", "test": self.test,
               "status": "FAILED" if error else "COMPLETED",
               "account_role": ACCOUNT_ROLE[self.test],
               "symbol": SYMBOL, "period": PERIOD,
               "ex5_sha256": sha256_file(self.data / EA_REL),
               "steps": self.steps, "error": error,
               "ea_log_lines": len(test_lines),
               "restore": restore,
               "note": ("no login, password or server is recorded (the "
                        "restore login is a prefixed sha256); the EA log "
                        "lines are the evidence, graded at stage 8")}
        (self.out / "run.json").write_text(json.dumps(rec, indent=2),
                                           encoding="utf-8")
        return rec
