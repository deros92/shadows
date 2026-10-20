"""Native messaging: protocollo, risposte spezzate, registrazione, host end-to-end."""

import base64
import io
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from shadows.native_host import MAX_MESSAGE, Host, NativeChannel
from shadows.native_install import build_files, extension_id, extension_id_from_key

ROOT = Path(__file__).resolve().parent.parent


def frame(msg: dict) -> bytes:
    body = json.dumps(msg).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def unframe_all(raw: bytes) -> list[dict]:
    out, i = [], 0
    while i < len(raw):
        (n,) = struct.unpack("<I", raw[i:i + 4])
        out.append(json.loads(raw[i + 4:i + 4 + n]))
        i += 4 + n
    return out


def test_channel_roundtrip_and_eof():
    reader = io.BytesIO(frame({"id": 1, "type": "health"}) + frame({"id": 2, "type": "x"}))
    ch = NativeChannel(reader, io.BytesIO())
    assert ch.read() == {"id": 1, "type": "health"}
    assert ch.read()["id"] == 2
    assert ch.read() is None  # fine del canale: il browser ha chiuso


def test_large_response_is_split_under_chrome_limit():
    out = io.BytesIO()
    big = {"id": 7, "ok": True, "data": {"text": "Mario Rossi è qui. " * 120_000}}
    NativeChannel(io.BytesIO(), out).send(big)
    parts = unframe_all(out.getvalue())
    assert len(parts) > 1
    assert all(len(json.dumps(p).encode()) < MAX_MESSAGE for p in parts)
    assert json.loads("".join(p["part"] for p in parts)) == big


def test_extension_id_matches_chrome_algorithm():
    # Il confronto con l'ID assegnato davvero da Chrome è in tools/check_native.py.
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    ext_id = extension_id_from_key(manifest["key"])
    assert len(ext_id) == 32 and set(ext_id) <= set("abcdefghijklmnop")
    assert ext_id == extension_id()


def test_host_files(tmp_path):
    manifest, launcher = build_files(tmp_path, r"C:\Python\python.exe", "a" * 32)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["type"] == "stdio"
    assert data["allowed_origins"] == [f"chrome-extension://{'a' * 32}/"]
    assert Path(data["path"]) == launcher
    assert "-m shadows native" in launcher.read_text(encoding="utf-8")


def test_host_dispatch(engine, tmp_path):
    from shadows.audit import AuditLog
    from shadows.service import ShadowsService

    host = Host(NativeChannel(io.BytesIO(), io.BytesIO()))
    host.service = ShadowsService(engine, AuditLog(tmp_path / "a.jsonl"))
    ok = host.handle({"id": 1, "type": "analyze", "text": "mail a@b.it"})
    assert ok["ok"] and ok["data"]["anonymized_text"] == "mail [EMAIL_1]"
    doc = host.handle({"id": 2, "type": "document", "filename": "n.txt",
                       "data_b64": base64.b64encode(b"cliente SuperMercati Bianchi").decode()})
    assert doc["data"]["anonymized_text"] == "cliente [CLIENTE_1]"
    bad = host.handle({"id": 3, "type": "document", "filename": "x.xlsx", "data_b64": ""})
    assert bad == {"id": 3, "ok": False, "status": 415, "error": bad["error"]}


def read_reply(stream) -> dict:
    (n,) = struct.unpack("<I", stream.read(4))
    return json.loads(stream.read(n))


def test_native_process_end_to_end():
    """Avvia davvero `python -m shadows native` e ci parla come farebbe il browser."""
    origin = f"chrome-extension://{extension_id()}/"
    proc = subprocess.Popen([sys.executable, "-m", "shadows", "native", origin, "--parent-window=0"],
                            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        proc.stdin.write(frame({"id": 1, "type": "health"}))
        proc.stdin.flush()
        first = read_reply(proc.stdout)  # subito, anche mentre il modello si carica
        assert first["ok"] and first["data"]["transport"] == "native"
        proc.stdin.write(frame({"id": 2, "type": "analyze", "text": "IBAN IT60X0542811101000000123456"}))
        proc.stdin.flush()
        reply = read_reply(proc.stdout)  # attende la fine del caricamento
        assert reply["id"] == 2 and reply["data"]["anonymized_text"] == "IBAN [IBAN_1]"
    finally:
        proc.stdin.close()  # come il browser che chiude il canale
    assert proc.wait(timeout=30) == 0  # uscita pulita: niente processi orfani


def test_native_rejects_foreign_origin():
    proc = subprocess.run([sys.executable, "-m", "shadows", "native",
                           "chrome-extension://" + "b" * 32 + "/"],
                          cwd=ROOT, input=frame({"id": 1, "type": "health"}),
                          capture_output=True, timeout=60)
    assert proc.returncode == 1 and proc.stdout == b""
