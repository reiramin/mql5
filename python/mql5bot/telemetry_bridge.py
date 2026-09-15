"""mql5bot.telemetry_bridge — HTTP collector for the MQL5 EA's telemetry.

The Expert Advisor POSTs JSON (heartbeat / trade / alert events) to any
endpoint via WebRequest. Run this collector on a machine reachable from
your MT5 terminal (or expose it with a tunnel):

    python -m mql5bot.telemetry_bridge --port 8080

Then set the EA inputs:

    InpTelemetry = true
    InpWebhookUrl = http://<this-host>:8080/telemetry

and add that URL to the terminal's allowed WebRequest list
(Tools -> Options -> Expert Advisors).

The collector writes every event to a JSONL log, prints a live summary, and
can re-emit events as an SSE stream for frontends:

    GET /telemetry/stream   (Server-Sent Events)
    GET /telemetry/latest   (last snapshot as JSON)
"""

from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

_DEFAULT_LOG = "results/telemetry.jsonl"


class Collector:
    def __init__(self, log_path: str):
        self.log_path = log_path
        self.clients: list = []
        self.last: dict = {}
        self.count = 0

    def handle(self, payload: dict) -> None:
        payload["received_at"] = time.time()
        self.last = payload
        self.count += 1
        os.makedirs(os.path.dirname(os.path.abspath(self.log_path)) or ".", exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
        line = (
            f"[{payload.get('event', '?')}] {payload.get('symbol', '-')} "
            f"{payload.get('action', payload.get('level', ''))} "
            f"{payload.get('lots', '')} {payload.get('pnl', '')}"
        ).strip()
        print(line)
        self.broadcast(payload)

    def subscribe(self, queue: list):
        self.clients.append(queue)

    def unsubscribe(self, queue: list):
        if queue in self.clients:
            self.clients.remove(queue)

    def broadcast(self, payload: dict):
        for queue in list(self.clients):
            queue.append(payload)


class _Handler(BaseHTTPRequestHandler):
    server_version = "mql5bot-telemetry/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(b'{"error":"invalid json"}', "application/json", 400)
            return
        self.server.collector.handle(payload)  # type: ignore[attr-defined]
        self._send(b'{"ok":true}', "application/json")

    def do_GET(self):
        parsed = urlparse(self.path)
        collector: Collector = self.server.collector  # type: ignore[attr-defined]
        if parsed.path == "/":
            self._send(
                (
                    "<html><body style='font-family:monospace;background:#0d1117;color:#e6edf3;padding:24px'>"
                    "<h3>mql5bot telemetry collector</h3>"
                    "<p>POST JSON events to /telemetry<br>"
                    "<a href='/telemetry/latest'>latest snapshot</a> · "
                    "<a href='/telemetry/stream'>SSE stream</a></p>"
                    "</body></html>"
                ).encode(),
                "text/html; charset=utf-8",
            )
        elif parsed.path == "/telemetry/latest":
            self._send(json.dumps(collector.last).encode(), "application/json")
        elif parsed.path == "/telemetry/stream":
            queue: list = []
            collector.subscribe(queue)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    while queue:
                        item = queue.pop(0)
                        self.wfile.write(
                            f"data: {json.dumps(item)}\n\n".encode()
                        )
                    self.wfile.flush()
                    time.sleep(0.2)
            except (BrokenPipeError, ConnectionResetError):
                collector.unsubscribe(queue)
        else:
            self._send(b'{"error":"not found"}', "application/json", 404)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mql5bot telemetry collector")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--log", default=_DEFAULT_LOG)
    args = parser.parse_args(argv)

    collector = Collector(args.log)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), _Handler)
    server.collector = collector  # type: ignore[attr-defined]
    print(f"mql5bot telemetry collector on http://0.0.0.0:{args.port} "
          f"(log: {args.log})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
