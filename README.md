# Anki Phone Remote

Use your phone as an Anki remote: Show Answer, Again / Hard / Good / Easy, and Undo, with big thumb-sized buttons. Optional on-phone card text.

Guide page: https://arafatrais.github.io/anki-phone-remote/

## Setup

1. In Anki: Tools → Add-ons → Get Add-ons → code `2055492159` (AnkiConnect). Restart Anki.
2. On your laptop, paste into Terminal (Python 3 only, no packages):
   ```bash
   curl -sL https://raw.githubusercontent.com/ArafatRais/anki-phone-remote/main/server.py | python3 -
   ```
   (Or download the repo and double-click `Start Anki Remote.command`. Options: `-- --pin 1234`, `-- --port 9000` when piping.)
3. A page opens on the laptop with a QR code. Scan it with your phone camera (same Wi-Fi). Add it to your home screen for a full-screen app.
4. Start reviewing a deck in Anki.

## How it works

`server.py` serves `remote.html` and forwards a small allow-list of requests (`guiCurrentCard`, `guiShowAnswer`, `guiAnswerCard`, `guiUndo`, ...) to AnkiConnect at `127.0.0.1:8765`. Because the browser only talks to the script, no AnkiConnect CORS config is needed and it works whether or not Anki is focused.

The page can't live on GitHub Pages itself: an HTTPS page can't call a plain-HTTP device on your LAN (mixed content). `docs/` is the Pages guide.

## Security

The server listens on your LAN with no login unless you pass `--pin`. Use `--pin` on shared networks.
