"""Telemetry collector HTTP hardening.

Pins the Wave-2 request-body cap: the unauthenticated collector must not
read an unbounded POST body into memory (local DoS), while still accepting
normal small telemetry events. Runs a real server on an ephemeral loopback
port.
"""

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

import pytest
from mql5bot.telemetry_bridge import MAX_BODY_BYTES, Collector, _Handler


@pytest.fixture
def collector_url(tmp_path):
    collector = Collector(str(tmp_path / "telemetry.jsonl"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.collector = collector  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _, port = server.server_address
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def _post(url: str, body: bytes):
    req = urllib.request.Request(
        url + "/telemetry", data=body, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_small_telemetry_body_accepted(collector_url):
    status, body = _post(collector_url,
                         json.dumps({"event": "heartbeat",
                                     "symbol": "EURUSD"}).encode())
    assert status == 200
    assert b"ok" in body


def test_oversized_body_rejected_with_413(collector_url):
    # Advertise an oversized Content-Length but send NO body: the handler
    # must reject on the header alone, BEFORE reading anything into memory
    # (that is the whole point of the cap). A raw socket lets us assert the
    # 413 without streaming a megabyte the server never reads.
    parsed = urlparse(collector_url)
    conn = socket.create_connection((parsed.hostname, parsed.port), timeout=5)
    try:
        request = (
            f"POST /telemetry HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {MAX_BODY_BYTES + 1}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode()
        conn.sendall(request)
        status_line = conn.recv(256).split(b"\r\n", 1)[0].decode("latin-1")
    finally:
        conn.close()
    assert "413" in status_line
