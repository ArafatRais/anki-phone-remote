#!/usr/bin/env python3
"""Anki phone remote: serves a mobile page on your LAN and relays button
presses to the AnkiConnect add-on running inside Anki on this computer.

Usage:  python3 server.py [--port 8080] [--pin 1234]
No third-party packages needed.
"""
import argparse
import json
import socket
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ANKI_CONNECT = "http://127.0.0.1:8765"
ALLOWED = {"guiCurrentCard", "guiShowAnswer", "guiAnswerCard", "guiUndo", "guiDeckReview", "deckNames"}
PAGE = Path(__file__).with_name("remote.html")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def make_handler(pin):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive: no new connection per tap

        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.split("?")[0] in ("/", "/index.html"):
                html = PAGE.read_text().replace("__PIN_REQUIRED__", "true" if pin else "false")
                self._send(200, html, "text/html; charset=utf-8")
            else:
                self._send(404, "{}")

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)  # always drain the body so keep-alive stays in sync
            if self.path != "/api":
                return self._send(404, "{}")
            if pin and self.headers.get("X-Pin") != pin:
                return self._send(401, json.dumps({"error": "bad pin"}))
            try:
                req = json.loads(body)
                if req.get("action") not in ALLOWED:
                    return self._send(403, json.dumps({"error": "action not allowed"}))
                req["version"] = 6
                r = urllib.request.Request(
                    ANKI_CONNECT, json.dumps(req).encode(), {"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(r, timeout=5) as resp:
                    self._send(200, resp.read())
            except Exception as e:  # Anki closed, AnkiConnect missing, bad JSON...
                self._send(502, json.dumps({"error": f"cannot reach AnkiConnect: {e}"}))

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--pin", default="", help="optional PIN the phone must enter")
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(args.pin))
    print(f"\nAnki remote running. On your phone (same Wi-Fi) open:\n\n  http://{lan_ip()}:{args.port}\n")
    print("Keep Anki open, with AnkiConnect installed. Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
