#!/usr/bin/env python3
"""tools/encrypt_outputs.py - REPO-SECURITY-1: encrypt a directory of
research outputs to the owner's age public key(s) BEFORE it leaves a runner
(e.g. before an ``actions/upload-artifact`` step).

    python tools/encrypt_outputs.py results/ --out results.tar.age
    python tools/encrypt_outputs.py results/ --out r.tar.age --recipient age1...

The directory is packed into a deterministic tar IN MEMORY (sorted names,
mtime 0, uid/gid 0, no user names) - no plaintext archive is written to
disk - and encrypted in the age v1 format (https://age-encryption.org/v1)
to every recipient in ``security/age_recipients.txt`` (public keys only;
the private key never enters the repository) plus any ``--recipient``.
The owner decrypts with the standard tool:

    age -d -i <owner identity file> results.tar.age | tar -x

Engines (``--engine auto`` picks the first available):
* ``age``    - the ``age`` binary, if it is on PATH;
* ``python`` - a built-in age-v1 X25519 encryptor using the optional
  ``cryptography`` package (not a declared dependency of this project; it is
  only imported here). Its output is a standard age file: the tests decrypt
  it with the ``age`` binary when one is installed.

Exit code: 0 = written (prints the output's sha256), 2 = usage error (no
recipient, missing input, no engine available).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RECIPIENTS_FILE = REPO / "security" / "age_recipients.txt"
AGE_V1 = b"age-encryption.org/v1"
X25519_INFO = b"age-encryption.org/v1/X25519"
CHUNK = 64 * 1024

# --------------------------------------------------------------------------
# bech32 (BIP-173) - age recipients "age1..." / identities "AGE-SECRET-KEY-1..."
# --------------------------------------------------------------------------
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values: list[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data, frombits: int, tobits: int, pad: bool) -> list[int]:
    acc = bits = 0
    out: list[int] = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if pad and bits:
        out.append((acc << (tobits - bits)) & maxv)
    elif not pad and (bits >= frombits or ((acc << (tobits - bits)) & maxv)):
        raise ValueError("bech32: invalid padding")
    return out


def bech32_encode(hrp: str, data: bytes) -> str:
    five = _convertbits(data, 8, 5, True)
    pm = _polymod(_hrp_expand(hrp) + five + [0] * 6) ^ 1
    check = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[d] for d in five + check)


def bech32_decode(text: str) -> tuple[str, bytes]:
    if text.lower() != text and text.upper() != text:
        raise ValueError("bech32: mixed case")
    text = text.lower()
    pos = text.rfind("1")
    if pos < 1 or pos + 7 > len(text):
        raise ValueError("bech32: bad separator")
    hrp, rest = text[:pos], text[pos + 1:]
    try:
        values = [_CHARSET.index(c) for c in rest]
    except ValueError as exc:
        raise ValueError("bech32: bad character") from exc
    if _polymod(_hrp_expand(hrp) + values) != 1:
        raise ValueError("bech32: bad checksum")
    return hrp, bytes(_convertbits(values[:-6], 5, 8, False))


def parse_recipient(text: str) -> bytes:
    hrp, key = bech32_decode(text.strip())
    if hrp != "age" or len(key) != 32:
        raise ValueError(f"not an age X25519 recipient: {text.strip()[:12]}...")
    return key


def parse_identity(text: str) -> bytes:
    hrp, key = bech32_decode(text.strip())
    if hrp != "age-secret-key-" or len(key) != 32:
        raise ValueError("not an age X25519 identity")
    return key


# --------------------------------------------------------------------------
# deterministic tar
# --------------------------------------------------------------------------
def tar_directory(src: Path) -> bytes:
    """A byte-reproducible tar of ``src`` (paths relative to its parent)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        entries = [src] + sorted(src.rglob("*"))
        for p in entries:
            if p.is_symlink():
                continue
            info = tarfile.TarInfo(p.relative_to(src.parent).as_posix())
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if p.is_dir():
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                tf.addfile(info)
            elif p.is_file():
                data = p.read_bytes()
                info.size, info.mode = len(data), 0o644
                tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# --------------------------------------------------------------------------
# age v1, X25519 recipients (python engine; needs `cryptography`)
# --------------------------------------------------------------------------
def _crypto():
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey,
            X25519PublicKey,
        )
        from cryptography.hazmat.primitives.ciphers.aead import (
            ChaCha20Poly1305,
        )
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except ImportError:
        return None
    return {"hashes": hashes, "ser": serialization, "priv": X25519PrivateKey,
            "pub": X25519PublicKey, "aead": ChaCha20Poly1305, "hkdf": HKDF}


def python_engine_available() -> bool:
    return _crypto() is not None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text + "=" * (-len(text) % 4))


def _hkdf(c, ikm: bytes, salt: bytes, info: bytes) -> bytes:
    return c["hkdf"](algorithm=c["hashes"].SHA256(), length=32, salt=salt,
                     info=info).derive(ikm)


def _raw(c, key) -> bytes:
    return key.public_bytes(c["ser"].Encoding.Raw, c["ser"].PublicFormat.Raw)


def _stream(c, key: bytes, data: bytes, decrypt: bool) -> bytes:
    aead = c["aead"](key)
    size = CHUNK + 16 if decrypt else CHUNK
    chunks = [data[i:i + size] for i in range(0, len(data), size)] or [b""]
    out = []
    for n, chunk in enumerate(chunks):
        last = n == len(chunks) - 1
        nonce = n.to_bytes(11, "big") + (b"\x01" if last else b"\x00")
        fn = aead.decrypt if decrypt else aead.encrypt
        out.append(fn(nonce, chunk, None))
    return b"".join(out)


def _header_mac(c, file_key: bytes, header: bytes) -> bytes:
    return hmac.new(_hkdf(c, file_key, b"", b"header"), header,
                    hashlib.sha256).digest()


def age_encrypt(data: bytes, recipients: list[str]) -> bytes:
    c = _crypto()
    if c is None:
        raise RuntimeError("the python engine needs the `cryptography` package")
    file_key = os.urandom(16)
    lines = [AGE_V1]
    for r in recipients:
        rkey = parse_recipient(r)
        eph = c["priv"].generate()
        share = _raw(c, eph.public_key())
        shared = eph.exchange(c["pub"].from_public_bytes(rkey))
        wrap = _hkdf(c, shared, share + rkey, X25519_INFO)
        body = c["aead"](wrap).encrypt(b"\x00" * 12, file_key, None)
        lines.append(b"-> X25519 " + _b64(share).encode())
        lines.append(_b64(body).encode())      # 43 chars: one short line
    header = b"\n".join(lines) + b"\n---"
    header += b" " + _b64(_header_mac(c, file_key, header)).encode() + b"\n"
    nonce = os.urandom(16)
    payload = _stream(c, _hkdf(c, file_key, nonce, b"payload"), data, False)
    return header + nonce + payload


def age_decrypt(blob: bytes, identity: str) -> bytes:
    """Decrypt with one X25519 identity (used by the tests; the owner uses
    the ``age`` binary)."""
    c = _crypto()
    if c is None:
        raise RuntimeError("the python engine needs the `cryptography` package")
    secret = c["priv"].from_private_bytes(parse_identity(identity))
    me = _raw(c, secret.public_key())
    end = blob.index(b"\n---") + len(b"\n---")
    header = blob[:end]
    mac_line, rest = blob[end:].split(b"\n", 1)
    lines = header.split(b"\n")
    if lines[0] != AGE_V1:
        raise ValueError("not an age v1 file")
    file_key = None
    for i, line in enumerate(lines):
        if not line.startswith(b"-> X25519 "):
            continue
        share = _unb64(line[len(b"-> X25519 "):].decode())
        shared = secret.exchange(c["pub"].from_public_bytes(share))
        wrap = _hkdf(c, shared, share + me, X25519_INFO)
        try:
            file_key = c["aead"](wrap).decrypt(
                b"\x00" * 12, _unb64(lines[i + 1].decode()), None)
        except Exception:  # noqa: BLE001, S112 -- another recipient's stanza
            continue
        break
    if file_key is None:
        raise ValueError("no stanza for this identity")
    if not hmac.compare_digest(_header_mac(c, file_key, header),
                               _unb64(mac_line.strip().decode())):
        raise ValueError("header MAC mismatch")
    nonce, payload = rest[:16], rest[16:]
    return _stream(c, _hkdf(c, file_key, nonce, b"payload"), payload, True)


def generate_identity() -> tuple[str, str]:
    """(identity, recipient) - a throwaway keypair for tests."""
    c = _crypto()
    if c is None:
        raise RuntimeError("needs the `cryptography` package")
    k = c["priv"].generate()
    raw = k.private_bytes(c["ser"].Encoding.Raw, c["ser"].PrivateFormat.Raw,
                          c["ser"].NoEncryption())
    return (bech32_encode("age-secret-key-", raw).upper(),
            bech32_encode("age", _raw(c, k.public_key())))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def load_recipients(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            parse_recipient(line)                  # refuse a malformed key
            out.append(line)
    return out


def encrypt_directory(src: Path, out: Path, recipients: list[str],
                      engine: str = "auto") -> str:
    if engine == "auto":
        engine = "age" if shutil.which("age") else "python"
    data = tar_directory(src)
    if engine == "age":
        argv = ["age"]
        for r in recipients:
            argv += ["-r", r]
        argv += ["-o", str(out)]
        subprocess.run(argv, input=data, check=True)
    elif engine == "python":
        out.write_bytes(age_encrypt(data, recipients))
    else:
        raise ValueError(f"unknown engine {engine!r}")
    return engine


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", help="directory of outputs to encrypt")
    ap.add_argument("--out", required=True, help="output file (.tar.age)")
    ap.add_argument("--recipient", action="append", default=[],
                    help="extra age recipient (age1...)")
    ap.add_argument("--recipients-file", default=str(RECIPIENTS_FILE))
    ap.add_argument("--engine", choices=("auto", "age", "python"),
                    default="auto")
    args = ap.parse_args(argv)
    src = Path(args.src)
    if not src.is_dir():
        print(f"encrypt_outputs: {src} is not a directory", file=sys.stderr)
        return 2
    try:
        recipients = load_recipients(Path(args.recipients_file))
        recipients += [r for r in args.recipient if parse_recipient(r)]
    except ValueError as exc:
        print(f"encrypt_outputs: {exc}", file=sys.stderr)
        return 2
    if not recipients:
        print("encrypt_outputs: no recipient. The owner adds their age public "
              f"key to {args.recipients_file} (docs/SECURITY.md); nothing "
              "was written", file=sys.stderr)
        return 2
    wants_python = args.engine == "python" or (
        args.engine == "auto" and not shutil.which("age"))
    if wants_python and not python_engine_available():
        print("encrypt_outputs: no engine: install `age`, or the "
              "`cryptography` package for the python engine",
              file=sys.stderr)
        return 2
    out = Path(args.out)
    used = encrypt_directory(src, out, recipients, args.engine)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"encrypt_outputs: {src} -> {out} ({used} engine, "
          f"{len(recipients)} recipient(s)) sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
