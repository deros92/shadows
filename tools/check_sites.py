"""Verifica end-to-end dell'estensione sui siti di chat reali.

Apre un Chromium con l'estensione caricata, scrive un messaggio con dati sensibili,
preme Invio, conferma "Invia anonimizzato" e controlla le richieste di rete in
uscita: devono contenere i placeholder e non i valori reali.

    python tools/check_sites.py                 # demo, chatgpt, perplexity
    python tools/check_sites.py chatgpt --headed

Richiede `shadows serve` attivo e Playwright (`pip install playwright` e
`python -m playwright install chromium`). Senza login, i siti possono cambiare
comportamento o mostrare verifiche anti-bot: il report lo dice.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PwTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
EXTENSION = ROOT / "extension"
SITES = {
    "demo": "http://127.0.0.1:8765/demo",
    "chatgpt": "https://chatgpt.com/",
    "perplexity": "https://www.perplexity.ai/",
    "claude": "https://claude.ai/new",
    "gemini": "https://gemini.google.com/app",
}
SECRET_VALUES = ["Mario Rossi", "mario.rossi@megastore.it", "SuperMercati Bianchi"]
MESSAGE = ("Ciao, sono Mario Rossi: scrivi una riga di saluto per il cliente SuperMercati "
           "Bianchi, referente mario.rossi@megastore.it")
COMPOSER = 'textarea, [contenteditable="true"], [contenteditable=""]'


def check(page, name: str, url: str, shots: Path) -> str:
    bodies: list[str] = []

    def on_request(req):
        if req.method == "POST" and "127.0.0.1:8765" not in req.url:
            try:
                data = req.post_data or ""
            except Exception:  # noqa: BLE001 - corpi binari
                data = ""
            if data:
                bodies.append(data)

    page.on("request", on_request)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        composer = page.locator(COMPOSER).filter(visible=True).first
        composer.wait_for(state="visible", timeout=30000)
    except PwTimeout:
        page.screenshot(path=shots / f"{name}-no-composer.png")
        return "campo di testo non trovato (login richiesto o verifica anti-bot?)"

    composer.click()
    page.keyboard.type(MESSAGE, delay=5)
    page.keyboard.press("Enter")
    try:
        page.locator("#shadows-host").wait_for(state="attached", timeout=15000)
    except PwTimeout:
        page.screenshot(path=shots / f"{name}-no-dialog.png")
        sent_clear = any(v in b for b in bodies for v in SECRET_VALUES)
        return ("INVIO NON INTERCETTATO: il messaggio è partito in chiaro" if sent_clear
                else "dialogo non comparso (invio non intercettato o servizio spento)")

    page.screenshot(path=shots / f"{name}-dialog.png")
    page.keyboard.press("Enter")  # il focus è su "Invia anonimizzato"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        wire = page.locator("#wire")  # solo nella pagina demo: ciò che ha ricevuto l'"AI"
        if wire.count():
            bodies.append(wire.inner_text())
        if any("[FULLNAME_1]" in b or "FULLNAME_1" in b for b in bodies):
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(8000)  # lascia arrivare la risposta
    page.screenshot(path=shots / f"{name}-after.png")
    # Modalità "safe" (default): la pagina non deve contenere i valori reali, perché
    # gli script del sito (telemetria, registrazione di sessione) li leggerebbero.
    in_page = page.evaluate("""(values) => {
        const clone = document.body.cloneNode(true);
        clone.querySelectorAll('textarea, [contenteditable], [data-shadows-ignore]').forEach(n => n.remove());
        return values.filter(v => clone.textContent.includes(v));
    }""", SECRET_VALUES)

    leaked = [v for v in SECRET_VALUES if any(v in b for b in bodies)]
    with_placeholder = any("FULLNAME_1" in b for b in bodies)
    if leaked:
        return f"PERDITA: valori reali nelle richieste in uscita: {leaked}"
    if with_placeholder:
        page_state = ("pagina senza valori reali" if not in_page
                      else f"valori reali nella pagina: {in_page}")
        return f"OK: in uscita solo placeholder; {page_state}"
    composer_text = composer.inner_text() if composer.count() else ""
    return f"nessuna richiesta col messaggio rilevata (composer ora: {composer_text[:80]!r})"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sites", nargs="*", default=["demo", "chatgpt", "perplexity"])
    parser.add_argument("--headed", action="store_true", help="mostra la finestra del browser")
    parser.add_argument("--shots", type=Path, default=ROOT / "logs" / "check_sites")
    args = parser.parse_args()
    args.shots.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8")

    with sync_playwright() as pw, tempfile.TemporaryDirectory() as profile:
        ctx = pw.chromium.launch_persistent_context(
            profile, channel="chromium", headless=not args.headed, locale="it-IT",
            viewport={"width": 1280, "height": 900},
            args=[f"--disable-extensions-except={EXTENSION}", f"--load-extension={EXTENSION}"],
        )
        try:
            for name in args.sites:
                page = ctx.new_page()
                try:
                    result = check(page, name, SITES[name], args.shots)
                except Exception as exc:  # noqa: BLE001
                    result = f"errore: {exc.__class__.__name__}: {str(exc)[:200]}"
                print(f"{name:11} {result}", flush=True)
                page.close()
        finally:
            ctx.close()
    print(f"Screenshot in {args.shots}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
