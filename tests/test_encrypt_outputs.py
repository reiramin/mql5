"""REPO-SECURITY-1: tools/encrypt_outputs.py encrypts a directory of
research outputs to age recipients before upload.

Every test uses a throwaway keypair generated at run time; no key is
committed. The python engine needs the optional ``cryptography`` package and
the interop tests need the ``age`` binary: each skips, named, when its tool
is missing (CI installs ``age`` when it can).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "encrypt_outputs.py"
_spec = importlib.util.spec_from_file_location("encrypt_outputs", TOOL)
eo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eo)

needs_crypto = pytest.mark.skipif(
    not eo.python_engine_available(),
    reason="the python engine needs the optional `cryptography` package")
needs_age = pytest.mark.skipif(shutil.which("age") is None,
                               reason="the `age` binary is not installed")


def _outputs(tmp_path: Path, size: int = 1000) -> Path:
    d = tmp_path / "results"
    (d / "sub").mkdir(parents=True)
    (d / "summary.json").write_text('{"trades": 3}', encoding="utf-8")
    (d / "sub" / "equity.csv").write_bytes(bytes(range(256)) * (size // 256))
    return d


def test_bech32_roundtrip_and_validation():
    key = bytes(range(32))
    r = eo.bech32_encode("age", key)
    assert r.startswith("age1") and eo.parse_recipient(r) == key
    with pytest.raises(ValueError):
        eo.parse_recipient(r[:-1] + ("q" if r[-1] != "q" else "p"))
    with pytest.raises(ValueError):
        eo.parse_recipient(eo.bech32_encode("age-secret-key-", key))


def test_the_tar_is_deterministic(tmp_path):
    d = _outputs(tmp_path)
    assert eo.tar_directory(d) == eo.tar_directory(d)


@needs_crypto
@pytest.mark.parametrize("size", [0, 1000, 65536, 65536 * 2 + 7])
def test_python_engine_roundtrip(size):
    ident, rcpt = eo.generate_identity()
    data = b"\x07" * size
    blob = eo.age_encrypt(data, [rcpt])
    assert blob.startswith(b"age-encryption.org/v1\n-> X25519 ")
    assert eo.age_decrypt(blob, ident) == data


@needs_crypto
def test_tampering_and_a_wrong_key_are_refused():
    ident, rcpt = eo.generate_identity()
    other, _ = eo.generate_identity()
    blob = bytearray(eo.age_encrypt(b"payload" * 100, [rcpt]))
    with pytest.raises(ValueError):
        eo.age_decrypt(bytes(blob), other)
    blob[-5] ^= 0x01
    with pytest.raises(Exception):  # noqa: B017 -- AEAD InvalidTag
        eo.age_decrypt(bytes(blob), ident)


@needs_crypto
def test_two_recipients_each_decrypt():
    (i1, r1), (i2, r2) = eo.generate_identity(), eo.generate_identity()
    blob = eo.age_encrypt(b"x" * 300, [r1, r2])
    assert eo.age_decrypt(blob, i1) == eo.age_decrypt(blob, i2) == b"x" * 300


@needs_crypto
@needs_age
def test_python_output_decrypts_with_the_age_binary(tmp_path):
    ident, rcpt = eo.generate_identity()
    key = tmp_path / "id.txt"
    key.write_text(ident + "\n", encoding="utf-8")
    d = _outputs(tmp_path, 70000)
    out = tmp_path / "r.tar.age"
    assert eo.encrypt_directory(d, out, [rcpt], "python") == "python"
    plain = subprocess.run(["age", "-d", "-i", str(key), str(out)],
                           capture_output=True, check=True).stdout
    assert plain == eo.tar_directory(d)


@needs_crypto
@needs_age
def test_age_binary_output_decrypts_with_python(tmp_path):
    ident, rcpt = eo.generate_identity()
    d = _outputs(tmp_path)
    out = tmp_path / "r.tar.age"
    assert eo.encrypt_directory(d, out, [rcpt], "age") == "age"
    assert eo.age_decrypt(out.read_bytes(), ident) == eo.tar_directory(d)


@needs_crypto
def test_cli_writes_only_ciphertext(tmp_path):
    _ident, rcpt = eo.generate_identity()
    d = _outputs(tmp_path)
    out = tmp_path / "r.tar.age"
    cp = subprocess.run([sys.executable, str(TOOL), str(d), "--out", str(out),
                         "--recipient", rcpt, "--recipients-file",
                         str(tmp_path / "none.txt"), "--engine", "python"],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 0, cp.stderr
    assert "sha256" in cp.stdout
    assert b'"trades"' not in out.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r.tar.age",
                                                          "results"]


def test_cli_refuses_without_a_recipient(tmp_path):
    d = _outputs(tmp_path)
    cp = subprocess.run([sys.executable, str(TOOL), str(d), "--out",
                         str(tmp_path / "x.age")],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 2
    assert "no recipient" in cp.stderr
    assert not (tmp_path / "x.age").exists()


def test_the_committed_recipients_file_holds_no_private_key():
    text = (REPO / "security" / "age_recipients.txt").read_text(
        encoding="utf-8")
    assert "AGE-SECRET-KEY" not in text.replace("AGE-SECRET-KEY-1...", "")
    # every non-comment line, if any, is a valid public key
    assert all(eo.parse_recipient(r)
               for r in eo.load_recipients(REPO / "security" /
                                           "age_recipients.txt"))


@needs_age
def test_age_engine_end_to_end_without_the_python_crypto(tmp_path):
    """Runs wherever the `age` binary exists (CI installs it), even without
    `cryptography`: a throwaway age-keygen key, the CLI with the age
    engine, and `age -d` give back the exact deterministic tar."""
    key = tmp_path / "id.txt"
    gen = subprocess.run(["age-keygen", "-o", str(key)], capture_output=True,
                         text=True, check=True)
    rcpt = next(w for w in (gen.stderr + gen.stdout).split()
                if w.startswith("age1"))
    assert len(eo.parse_recipient(rcpt)) == 32     # our bech32 reads it
    d = _outputs(tmp_path, 70000)
    out = tmp_path / "r.tar.age"
    cp = subprocess.run([sys.executable, str(TOOL), str(d), "--out", str(out),
                         "--recipient", rcpt, "--recipients-file",
                         str(tmp_path / "none.txt"), "--engine", "age"],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 0, cp.stderr
    plain = subprocess.run(["age", "-d", "-i", str(key), str(out)],
                           capture_output=True, check=True).stdout
    assert plain == eo.tar_directory(d)
