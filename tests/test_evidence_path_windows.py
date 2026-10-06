"""_resolve_evidence containment is separator-independent (gate_run37).

gate_run37: all four tester safety legs passed in MT5, but the verifier
marked them INVALID ("evidence path escapes the evidence root"). The check
was ``str(path).startswith(str(root) + "/")``, and resolved Windows paths
use ``\\``. owner_gate.path_within now uses PurePath.is_relative_to.
"""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest
from mql5bot import owner_gate as og

W_ROOT = PureWindowsPath(r"C:\Users\ramin\Desktop\mql5\evidence\owner_mt5_package")


@pytest.mark.parametrize("rel", [r"safety\raw\kill_switch_window.txt",
                                 r"safety\kill_switch.json", r"a\b\c.txt"])
def test_windows_path_inside_the_root_is_accepted(rel):
    assert og.path_within(W_ROOT / rel, W_ROOT)


def test_windows_root_itself_is_accepted():
    assert og.path_within(W_ROOT, W_ROOT)


@pytest.mark.parametrize("path", [
    W_ROOT / r"..\escape.log",
    W_ROOT / r"safety\..\..\escape.log",
    PureWindowsPath(r"C:\Users\ramin\Desktop\mql5\evidence\escape.log"),
    PureWindowsPath(r"D:\owner_mt5_package\safety\x.json"),
])
def test_windows_escape_is_refused(path):
    assert not og.path_within(path, W_ROOT)


def test_windows_sibling_name_prefix_is_refused():
    sibling = PureWindowsPath(str(W_ROOT) + "2") / "x"   # ...owner_mt5_package2\x
    assert not og.path_within(sibling, W_ROOT)


def test_posix_paths_unchanged():
    root = PurePosixPath("/ev/pkg")
    assert og.path_within(root / "safety/x.json", root)
    assert og.path_within(root, root)
    assert not og.path_within(PurePosixPath("/ev/pkg/../x.log"), root)
    assert not og.path_within(PurePosixPath("/ev/pkg2/x"), root)
    assert not og.path_within(PurePosixPath("/ev/x"), root)


def test_resolve_evidence_accepts_a_bound_file_inside_the_root(tmp_path):
    import hashlib
    (tmp_path / "safety").mkdir()
    (tmp_path / "safety" / "w.txt").write_bytes(b"x\n")
    state, reason, _ = og._resolve_evidence(
        tmp_path, {"path": "safety/w.txt",
                   "sha256": hashlib.sha256(b"x\n").hexdigest()}, "t")
    assert (state, reason) == ("VALID", "")


def test_the_separator_bound_check_is_gone():
    from pathlib import Path
    src = Path(og.__file__).read_text(encoding="utf-8")
    assert 'startswith(str(root_res) + "/")' not in src
    assert "if not path_within(path, root_res):" in src
