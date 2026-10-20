"""Registra Shadows come "native messaging host" di Chrome, Edge e Chromium.

Native messaging: invece di aprire una porta di rete, è il browser ad avviare
Shadows e a parlarci attraverso stdin/stdout, e solo l'estensione con l'ID indicato
in "allowed_origins" può collegarsi. Il browser trova Shadows grazie a:
- un file manifest JSON (nome del host, percorso del programma, ID autorizzati);
- una voce di registro che punta a quel file.

Qui la registrazione è per l'utente corrente (HKCU): non servono permessi di
amministratore. Un'installazione aziendale userebbe HKLM, non modificabile dai
programmi che girano con i permessi dell'utente.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

HOST_NAME = "com.shadows.host"
PROJECT_DIR = Path(__file__).resolve().parent.parent
EXTENSION_MANIFEST = PROJECT_DIR / "extension" / "manifest.json"
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Shadows" / "native"

# Chiavi di registro per browser. "Chromium" serve ai test automatici (Playwright).
REGISTRY_PATHS = {
    "chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
    "chromium": r"Software\Chromium\NativeMessagingHosts",
}


def extension_id_from_key(key_b64: str) -> str:
    """ID di Chrome: primi 32 caratteri esadecimali dello SHA-256 della chiave, in a-p."""
    digest = hashlib.sha256(base64.b64decode(key_b64)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def extension_id() -> str:
    manifest = json.loads(EXTENSION_MANIFEST.read_text(encoding="utf-8"))
    if "key" not in manifest:
        raise RuntimeError("extension/manifest.json non ha 'key': eseguire tools/make_extension_key.py")
    return extension_id_from_key(manifest["key"])


def build_files(target: Path, python: str, ext_id: str) -> tuple[Path, Path]:
    """Scrive il lanciatore e il manifest del host. Ritorna (manifest, lanciatore)."""
    target.mkdir(parents=True, exist_ok=True)
    launcher = target / "shadows-host.bat"
    # Il browser avvia il host con stdin/stdout collegati a sé: niente echo, niente
    # output estraneo su stdout, o il protocollo si rompe.
    launcher.write_text(
        "@echo off\r\n"
        f'cd /d "{PROJECT_DIR}"\r\n'
        f'"{python}" -m shadows native %*\r\n',
        encoding="utf-8",
    )
    manifest = target / f"{HOST_NAME}.json"
    manifest.write_text(json.dumps({
        "name": HOST_NAME,
        "description": "Shadows: anonimizzazione locale dei prompt",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{ext_id}/"],
    }, indent=2), encoding="utf-8")
    return manifest, launcher


def install(browsers: list[str], python: str | None = None) -> dict:
    import winreg

    ext_id = extension_id()
    manifest, launcher = build_files(INSTALL_DIR, python or sys.executable, ext_id)
    for browser in browsers:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{REGISTRY_PATHS[browser]}\\{HOST_NAME}")
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))
        winreg.CloseKey(key)
    return {"extension_id": ext_id, "manifest": str(manifest), "launcher": str(launcher),
            "browsers": browsers}


def registered_browsers() -> list[str]:
    import winreg

    found = []
    for browser, path in REGISTRY_PATHS.items():
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{path}\\{HOST_NAME}"))
            found.append(browser)
        except FileNotFoundError:
            pass
    return found


def uninstall(browsers: list[str]) -> None:
    import winreg

    for browser in browsers:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{REGISTRY_PATHS[browser]}\\{HOST_NAME}")
        except FileNotFoundError:
            pass
    # I file sono condivisi tra i browser: si cancellano solo quando nessuno li usa più.
    if not registered_browsers():
        for name in (f"{HOST_NAME}.json", "shadows-host.bat"):
            (INSTALL_DIR / name).unlink(missing_ok=True)
