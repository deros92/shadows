"""Genera la chiave dell'estensione e fissa il suo ID (da eseguire UNA volta sola).

Chrome ricava l'ID di un'estensione dalla chiave pubblica nel manifest ("key").
Senza chiave, l'ID di un'estensione non pacchettizzata dipende dalla cartella da cui
la si carica: il native messaging, che autorizza un ID preciso, non funzionerebbe.

- la chiave pubblica va nel manifest (non è un segreto);
- la chiave privata (keys/shadows-extension.pem, esclusa da git) serve solo per
  impacchettare un .crx da distribuire in azienda: chi la possiede può pubblicare
  aggiornamenti con lo stesso ID, quindi va custodita.

    python tools/make_extension_key.py          # rifiuta se la chiave esiste già
"""

import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "extension" / "manifest.json"
PRIVATE = ROOT / "keys" / "shadows-extension.pem"
sys.path.insert(0, str(ROOT))

from shadows.native_install import extension_id_from_key  # noqa: E402


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if "key" in manifest or PRIVATE.exists():
        print("Chiave già presente: rigenerarla cambierebbe l'ID dell'estensione. Nessuna modifica.")
        return 1
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    PRIVATE.parent.mkdir(exist_ok=True)
    PRIVATE.write_bytes(private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    key_b64 = base64.b64encode(public_der).decode()
    # "key" subito dopo "description", per leggibilità.
    ordered = {}
    for k, v in manifest.items():
        ordered[k] = v
        if k == "description":
            ordered["key"] = key_b64
    MANIFEST.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"ID dell'estensione: {extension_id_from_key(key_b64)}")
    print(f"Chiave privata: {PRIVATE} (non pubblicarla)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
