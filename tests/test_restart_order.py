"""RESTART-ORDER-1 (gate_run54, 422c174, gold2 -DemoSafety).

The restart demo run COMPLETED (probe opened, terminal killed, relaunched,
cleanup, restore connected), but the stage-8 builder graded it NO_RESTART.
The grader ordered events by the EA's own stamp, which is TimeCurrent():
stale at OnInit after a relaunch. restart.json quoted

    [2026.10.12 16:06:55] ... START probe=1 ... own_positions=0 registry=0
    [2026.10.12 16:06:55] ... START probe=1 ... own_positions=1 registry=1
    [2026.10.12 16:06:55] ... START probe=3 ... own_positions=1 registry=1
    [2026.10.12 16:07:21] ... PROBE position opened

while the harness's own UTC steps were: START 13:07:18, probe 13:07:20,
KILL 13:07:50, relaunch START 13:08:05. The ealog is the harness's tail of
the append-only Experts log, so the LINE POSITION is the true order.
"""

from __future__ import annotations

import pytest
from mql5bot import safety_legs as sl


def _l(t: str, msg: str) -> str:
    return f"[2026.10.12 {t}] [INFO] TEST demo: {msg}"


START = ("START probe={p} magic=17514383 own_positions={o} registry={r} "
         "engine=0 margin_mode=2")
HB = ("SNAPSHOT heartbeat margin_mode=2 own_positions={o} registry={r} "
      "positions=[{pos}]")
ONE = "5:buy:0.01:17514383"


def _run54(*, relaunch: bool = True, dup_between: bool = False,
           dup_after_cleanup: bool = False) -> str:
    """gate_run54's shape in log order, START stamps stale (16:06:55)."""
    lines = [_l("16:06:55", START.format(p=1, o=0, r=0)),
             _l("16:07:21", "PROBE position opened"),
             _l("16:07:40", HB.format(o=1, r=1, pos=ONE))]
    if relaunch:
        lines += [_l("16:06:55", START.format(p=1, o=1, r=1)),
                  _l("16:08:20", HB.format(o=2 if dup_between else 1, r=1,
                                           pos=ONE))]
    lines += [_l("16:06:55", START.format(p=3, o=1, r=1)),
              _l("16:09:45", "CLEANUP closed 1")]
    if dup_after_cleanup:
        lines.append(_l("16:09:50", HB.format(o=2, r=1, pos=ONE)))
    return "\n".join(lines) + "\n"


def test_gate_run54_shape_is_a_recovered_restart():
    d = sl.grade("restart", _run54(), "", "")
    assert d["observed_result"] == "RESTART_RECOVERED_NO_DUPLICATE"
    assert d["passed"] is True
    assert d["facts"]["own_at_restart"] == 1
    assert d["facts"]["heartbeats_after_restart"] == 1
    assert d["facts"]["order"] == "log position (RESTART-ORDER-1)"


def test_a_cleanup_start_alone_is_not_a_restart():
    # stricter than before: only a probe=1 START counts as the relaunch
    d = sl.grade("restart", _run54(relaunch=False), "", "")
    assert d["observed_result"] == "NO_RESTART"
    assert d["passed"] is False


def test_a_duplicate_after_the_relaunch_is_caught():
    d = sl.grade("restart", _run54(dup_between=True), "", "")
    assert d["observed_result"] == "DUPLICATE_EXPOSURE:1"


def test_heartbeats_before_the_relaunch_never_count_as_after_it():
    # the pre-kill heartbeat (16:07:40) is stamped AFTER the stale relaunch
    # START (16:06:55); by stamp it would count, by position it does not
    d = sl.grade("restart", _run54(), "", "")
    assert d["facts"]["heartbeats_after_restart"] == 1


@pytest.mark.parametrize("cleanup_dup", [True])
def test_heartbeats_after_the_next_start_belong_to_the_cleanup(cleanup_dup):
    d = sl.grade("restart", _run54(dup_after_cleanup=cleanup_dup), "", "")
    assert d["observed_result"] == "RESTART_RECOVERED_NO_DUPLICATE"


# gate_run54 restart.json quoted_lines, VERBATIM. The grader quotes every
# START first, then the probe line, so this list is NOT the log order.
RUN54_QUOTED = [
    ("[2026.10.12 16:06:55] [INFO] TEST demo: START probe=1 magic=17514383 "
     "own_positions=0 registry=0 engine=0 margin_mode=2"),
    ("[2026.10.12 16:06:55] [INFO] TEST demo: START probe=1 magic=17514383 "
     "own_positions=1 registry=1 engine=0 margin_mode=2"),
    ("[2026.10.12 16:06:55] [INFO] TEST demo: START probe=3 magic=17514383 "
     "own_positions=1 registry=1 engine=0 margin_mode=2"),
    "[2026.10.12 16:07:21] [INFO] TEST demo: PROBE position opened",
]
# The log order, from the harness's own UTC steps in the same run.json:
# START 13:07:18, probe opened 13:07:20, KILL 13:07:50, relaunch START
# 13:08:05, cleanup START (probe=3) 13:09:42.
RUN54_LOG_ORDER = [RUN54_QUOTED[0], RUN54_QUOTED[3], RUN54_QUOTED[1],
                   RUN54_QUOTED[2]]


def test_run54_quoted_lines_find_the_relaunch():
    d = sl.grade("restart", "\n".join(RUN54_LOG_ORDER) + "\n", "", "")
    # the restart IS found: same magic, own position 1 at relaunch
    assert d["observed_result"] != "NO_RESTART"
    assert d["facts"]["magic_before"] == d["facts"]["magic_after"] == \
        "17514383"
    assert d["facts"]["own_at_restart"] == 1
    assert d["facts"]["engine_at_restart"] == 0
    # the quote carries no heartbeat line, so "no duplicate" is NOT proven
    # from these four lines alone -- never a pass on them
    assert d["observed_result"] == "INCONCLUSIVE_NO_HEARTBEAT_AFTER_RESTART"
    assert d["passed"] is False


def test_run54_quoted_lines_plus_a_clean_heartbeat_pass():
    # a heartbeat line in the measured SNAPSHOT format, placed after the
    # relaunch START (test input, not gate_run54 evidence)
    hb = ("[2026.10.12 16:08:30] [INFO] TEST demo: SNAPSHOT heartbeat "
          "margin_mode=2 own_positions=1 registry=1 "
          "positions=[5:buy:0.01:17514383]")
    lines = RUN54_LOG_ORDER[:3] + [hb] + RUN54_LOG_ORDER[3:]
    d = sl.grade("restart", "\n".join(lines) + "\n", "", "")
    assert d["observed_result"] == d["expected_result"] == \
        "RESTART_RECOVERED_NO_DUPLICATE"
