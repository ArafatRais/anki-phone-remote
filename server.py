#!/usr/bin/env python3
"""Anki phone remote: serves a mobile page on your LAN and relays button
presses to the AnkiConnect add-on running inside Anki on this computer.

Usage:  python3 server.py [--port 8080] [--pin 1234]
No third-party packages needed.
"""
import argparse
import json
import os
import re
import subprocess
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ANKI_CONNECT = os.environ.get("ANKI_CONNECT_URL", "http://127.0.0.1:8765")
ALLOWED = {"guiCurrentCard", "guiShowAnswer", "guiAnswerCard", "guiUndo", "guiDeckReview", "deckNames"}
RAW = "https://raw.githubusercontent.com/ArafatRais/anki-phone-remote/main/remote.html"
HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()


def load_page():
    """remote.html next to this file, else download it (lets server.py run on its own / piped)."""
    f = HERE / "remote.html"
    if f.exists():
        return f.read_text()
    try:
        with urllib.request.urlopen(f"{RAW}?t={int(time.time())}", timeout=10) as r:  # ?t= dodges the raw cache
            return r.read().decode()
    except Exception:  # python.org builds on macOS often lack SSL certs; curl ships with macOS
        return subprocess.run(["curl", "-fsSL", f"{RAW}?t={int(time.time())}"], capture_output=True, text=True, check=True).stdout


QR_PAGE = """<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Anki Remote</title>
<body style="font:18px -apple-system,system-ui,sans-serif;text-align:center;padding:40px;background:#f4f5f7;color:#15181d">
<h2>Scan with your phone camera</h2><div id="q" style="display:inline-block;padding:16px;background:#fff;border-radius:16px"></div>
<p>or type <b id="u"></b> (same Wi-Fi)</p><p style="color:#5d6672">Keep Anki open on a deck. You can close this tab.</p>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<script>const u=location.search.slice(1);document.getElementById("u").textContent=u;
try{new QRCode(document.getElementById("q"),{text:u,width:240,height:240})}catch(e){document.getElementById("q").remove()}</script>"""


STYLE_RE = re.compile(r"<(style|script)\b.*?</\1>", re.S | re.I)


def slim_card(card):
    """Cards can carry 100KB+ of CSS/field data; the phone only needs a little."""
    if not isinstance(card, dict):
        return card
    keep = {k: card.get(k) for k in ("cardId", "deckName", "buttons", "nextReviews")}
    for k in ("question", "answer"):
        keep[k] = STYLE_RE.sub("", card.get(k) or "")[:6000]
    return keep


def candidate_ips():
    """Real addresses this machine can be reached on, best first.
    Tailscale (100.64/10) wins: it works on any Wi-Fi. Then ordinary private LAN ranges.
    Skips loopback, link-local and 192.0.0.x (a virtual interface, not Wi-Fi)."""
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
    except OSError:
        out = ""
    found = []
    for ip in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out):
        a, b = map(int, ip.split(".")[:2])
        if a == 127 or (a, b) == (169, 254) or ip.startswith("192.0.0."):
            continue
        if a == 100 and 64 <= b <= 127:
            rank = 0
        elif a == 10 or (a, b) == (192, 168) or (a == 172 and 16 <= b <= 31):
            rank = 1
        else:
            continue
        found.append((rank, ip))
    return [ip for _, ip in sorted(found)] or ["127.0.0.1"]


def make_handler(pin, page):
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
                html = page.replace("__PIN_REQUIRED__", "true" if pin else "false")
                self._send(200, html, "text/html; charset=utf-8")
            elif self.path.split("?")[0] == "/qr":
                self._send(200, QR_PAGE, "text/html; charset=utf-8")
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
                t0 = time.perf_counter()
                with urllib.request.urlopen(r, timeout=30) as resp:
                    out = json.loads(resp.read())
                if req.get("action") == "guiCurrentCard":
                    out["result"] = slim_card(out.get("result"))
                out["anki_ms"] = round((time.perf_counter() - t0) * 1000)  # time Anki itself took
                self._send(200, json.dumps(out))
            except Exception as e:  # Anki closed, AnkiConnect missing, bad JSON...
                self._send(502, json.dumps({"error": f"cannot reach AnkiConnect: {e}"}))

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--pin", default="", help="optional PIN the phone must enter")
    args = ap.parse_args()
    page = load_page()
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(args.pin, page))
    except OSError:
        raise SystemExit(f"Port {args.port} is busy (is the remote already running?). Try --port {args.port + 1}.")
    ips = candidate_ips()
    url = f"http://{ips[0]}:{args.port}"
    if len(ips) > 1:
        print("Other addresses to try: " + ", ".join(f"http://{i}:{args.port}" for i in ips[1:]))
    print(f"\nAnki remote running. On your phone open (Tailscale address if listed, otherwise same Wi-Fi):\n\n  {url}\n")
    webbrowser.open(f"http://127.0.0.1:{args.port}/qr?{url}")
    print("Keep Anki open, with AnkiConnect installed. Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
