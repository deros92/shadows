"""Verifica end-to-end del native messaging in un browser vero.

Controlla che: la porta 8765 sia chiusa; l'ID assegnato da Chrome all'estensione
coincida con quello calcolato; il browser avvii Shadows da solo e lo usi su
Perplexity; chiuso il browser, Shadows termini.

    python tools/check_native.py

Registra temporaneamente Shadows per "Chromium" (il browser di Playwright) e alla
fine rimuove quella registrazione; Chrome ed Edge non vengono toccati.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shadows import native_install  # noqa: E402

EXTENSION = ROOT / "extension"
MESSAGE = ("Mario Rossi p.iva IT3823782372743 chiede pagamento fattura 23255 di importo 1456,78 "
           "non pagata da Luigi Verdi")
ORIGINALS = ["Mario Rossi", "Luigi Verdi", "IT3823782372743"]


def port_open(port: int = 8765) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def native_processes() -> list[str]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*shadows native*' } | ForEach-Object { $_.ProcessId }"],
        capture_output=True, text=True)
    return out.stdout.split()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= passed
        print(f"{'OK ' if passed else 'NO '} {label}{(': ' + detail) if detail else ''}", flush=True)

    check("porta 8765 chiusa prima del test", not port_open())
    native_install.install(["chromium"], sys.executable)
    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                tempfile.mkdtemp(), channel="chromium", headless=True, locale="it-IT",
                viewport={"width": 1280, "height": 900},
                args=[f"--disable-extensions-except={EXTENSION}", f"--load-extension={EXTENSION}"])
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
            chrome_id = sw.url.split("/")[2]
            check("ID assegnato dal browser = ID calcolato", chrome_id == native_install.extension_id(),
                  chrome_id)

            t0 = time.monotonic()
            health = {}
            while time.monotonic() - t0 < 120:
                health = sw.evaluate("handle({type: 'health'}).catch(e => ({error: String(e)}))")
                if health.get("status") == "ok" or health.get("error"):
                    break
                time.sleep(1)
            check("Shadows avviato dal browser via native messaging",
                  health.get("transport") == "native",
                  f"pronto in {time.monotonic() - t0:.0f}s, {health.get('detectors') or health}")
            check("processo Shadows avviato dal browser", bool(native_processes()))

            page = ctx.new_page()
            leaks, clean = [], []

            def on_request(req):
                if req.method != "POST":
                    return
                try:
                    body = req.post_data or ""
                except Exception:  # noqa: BLE001
                    body = ""
                if any(o in body for o in ORIGINALS):
                    leaks.append(req.url[:80])
                elif "FULLNAME_1" in body:
                    clean.append(req.url[:80])

            page.on("request", on_request)
            page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded")
            composer = page.locator('[contenteditable="true"]').filter(visible=True).first
            composer.wait_for(timeout=30000)
            composer.click()
            page.keyboard.type(MESSAGE, delay=2)
            page.keyboard.press("Enter")
            page.locator("#shadows-host").wait_for(state="attached", timeout=20000)
            page.keyboard.press("Enter")
            page.wait_for_timeout(10000)
            check("Perplexity: in uscita solo segnaposto", bool(clean) and not leaks,
                  f"pulite={len(clean)} con_originali={len(leaks)}")
            check("porta 8765 ancora chiusa durante l'uso", not port_open())
            ctx.close()

        time.sleep(3)
        check("chiuso il browser, Shadows è terminato", not native_processes())
    finally:
        native_install.uninstall(["chromium"])  # Chrome ed Edge restano registrati
    print("TUTTO OK" if ok else "CI SONO PROBLEMI")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
