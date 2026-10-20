"""Il sito invia la bozza mentre si scrive, prima che si prema Invio?

Scrive un messaggio a velocità umana SENZA inviarlo e conta le richieste HTTP e i
frame WebSocket che contengono il testo. Un controllo "all'invio" come quello di
Shadows non può fermare questi flussi: vanno bloccati a livello di rete
(extension/rules.json).

    python tools/check_drafts.py perplexity          # comportamento nativo del sito
    python tools/check_drafts.py perplexity --ext    # con l'estensione Shadows

Risultato del 2026-10-18: Perplexity invia la bozza lettera per lettera a
wss://suggest.perplexity.ai (55 frame per una frase); con le regole di Shadows, 0.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SITES = {
    "perplexity": "https://www.perplexity.ai/",
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/new",
    "gemini": "https://gemini.google.com/app",
}
MARKER = "Mario Rossi"
MESSAGE = f"{MARKER} chiede il pagamento della fattura a Luigi Verdi"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("site", choices=SITES)
    parser.add_argument("--ext", action="store_true", help="carica l'estensione Shadows")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    extension = str(ROOT / "extension")
    launch_args = [f"--disable-extensions-except={extension}", f"--load-extension={extension}"] if args.ext else []
    http_hits: Counter[str] = Counter()
    ws_hits: Counter[str] = Counter()
    marker = MARKER.encode()

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            tempfile.mkdtemp(), channel="chromium", headless=not args.headed, locale="it-IT",
            viewport={"width": 1280, "height": 900}, args=launch_args)
        page = ctx.new_page()

        def on_request(req):
            try:
                body = req.post_data_buffer or b""
            except Exception:  # noqa: BLE001
                body = b""
            if marker in body or MARKER in req.url or MARKER.replace(" ", "%20") in req.url:
                http_hits[f"{req.method} {req.url.split('?')[0][:90]}"] += 1

        def on_websocket(ws):
            def sent(payload):
                data = payload.encode() if isinstance(payload, str) else payload
                if marker in data:
                    ws_hits[ws.url.split("?")[0][:90]] += 1
            ws.on("framesent", sent)

        page.on("request", on_request)
        page.on("websocket", on_websocket)
        page.goto(SITES[args.site], wait_until="domcontentloaded", timeout=60000)
        composer = page.locator('textarea, [contenteditable="true"]').filter(visible=True).first
        composer.wait_for(timeout=30000)
        composer.click()
        page.keyboard.type(MESSAGE, delay=60)
        page.wait_for_timeout(4000)  # nessun invio
        ctx.close()

    print(f"{args.site} {'con' if args.ext else 'senza'} Shadows: bozza in uscita prima dell'invio")
    for name, hits in (("HTTP", http_hits), ("WebSocket", ws_hits)):
        for url, n in hits.most_common():
            print(f"  {name:9} {n:3}x {url}")
    if not http_hits and not ws_hits:
        print("  nessuna")
    return 0


if __name__ == "__main__":
    sys.exit(main())
