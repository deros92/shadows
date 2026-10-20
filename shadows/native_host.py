"""Native messaging host: Shadows avviato dal browser, senza porte di rete.

Protocollo di Chrome: ogni messaggio è JSON in UTF-8 preceduto dalla sua lunghezza
in 4 byte (little-endian). Il browser scrive su stdin e legge da stdout; quando
chiude il canale (o termina), stdin arriva a fine file e Shadows esce: nessun
processo resta orfano.

Accorgimenti:
- stdout trasporta SOLO messaggi del protocollo. Qualsiasi altra scrittura
  (avvisi di librerie, print) lo corromperebbe: il descrittore 1 viene quindi
  rediretto sul log e il protocollo usa una copia privata del descrittore originale;
- il modello si carica in un thread: "health" risponde subito ("loading") e le
  altre richieste attendono che il caricamento finisca;
- i messaggi verso il browser hanno un limite di 1 MB: le risposte più grandi
  (documenti lunghi) vengono spezzate in parti e ricomposte dall'estensione.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import queue
import struct
import sys
import threading
import traceback

from shadows.native_install import extension_id

log = logging.getLogger("shadows.native")

MAX_MESSAGE = 1024 * 1024          # limite di Chrome per i messaggi host -> browser
CHUNK_CHARS = 60_000               # con ensure_ascii al peggio ~12 byte per carattere


class NativeChannel:
    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer
        self._lock = threading.Lock()

    def read(self) -> dict | None:
        header = self._read_exact(4)
        if header is None:
            return None
        (length,) = struct.unpack("<I", header)
        body = self._read_exact(length)
        return None if body is None else json.loads(body.decode("utf-8"))

    def _read_exact(self, n: int) -> bytes | None:
        data = b""
        while len(data) < n:
            part = self._reader.read(n - len(data))
            if not part:
                return None
            data += part
        return data

    def send(self, message: dict) -> None:
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        if len(body) <= MAX_MESSAGE - 64:
            self._write(body)
            return
        text = json.dumps(message, ensure_ascii=False)
        parts = [text[i:i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)]
        for index, part in enumerate(parts):
            self._write(json.dumps({"id": message.get("id"), "chunk": index, "of": len(parts),
                                    "part": part}).encode("utf-8"))

    def _write(self, body: bytes) -> None:
        with self._lock:
            self._writer.write(struct.pack("<I", len(body)) + body)
            self._writer.flush()


class Host:
    def __init__(self, channel: NativeChannel):
        self.channel = channel
        self.service = None
        self.load_error: str | None = None
        self.ready = threading.Event()
        self.jobs: queue.Queue = queue.Queue()

    def load(self) -> None:
        try:
            from shadows.engine import Engine
            from shadows.service import ShadowsService, audit_from_config

            engine = Engine.from_config_file()
            if hasattr(engine.rizzo_pii, "warm_up"):
                engine.rizzo_pii.warm_up()
            self.service = ShadowsService(engine, audit_from_config(engine))
            log.info("modello pronto")
        except Exception as exc:  # noqa: BLE001 - va riportato all'estensione
            self.load_error = f"{exc.__class__.__name__}: {exc}"
            log.error("caricamento fallito\n%s", traceback.format_exc())
        finally:
            self.ready.set()

    def worker(self) -> None:
        while True:
            msg = self.jobs.get()
            self.ready.wait()
            self.channel.send(self.handle(msg))

    def handle(self, msg: dict) -> dict:
        from shadows.service import ServiceError

        mid = msg.get("id")
        if self.load_error:
            return {"id": mid, "ok": False, "status": 503, "error": self.load_error}
        try:
            return {"id": mid, "ok": True, "data": self.dispatch(msg)}
        except ServiceError as exc:
            return {"id": mid, "ok": False, "status": exc.status, "error": exc.detail}
        except Exception as exc:  # noqa: BLE001
            log.error("errore su %s\n%s", msg.get("type"), traceback.format_exc())
            return {"id": mid, "ok": False, "status": 500, "error": str(exc)}

    def dispatch(self, msg: dict) -> dict:
        kind = msg.get("type")
        s = self.service
        if kind == "health":
            return {**s.health(), "transport": "native"}
        if kind == "analyze":
            return s.analyze(str(msg.get("text", "")), msg.get("site"), msg.get("known_mapping"))
        if kind == "document":
            data = base64.b64decode(msg.get("data_b64") or "")
            return s.document(str(msg.get("filename", "")), data, msg.get("site"),
                              msg.get("known_mapping"))
        if kind == "restore":
            return s.restore(str(msg.get("text", "")), msg.get("mapping") or {})
        if kind == "event":
            return s.event(msg.get("site"), msg.get("proposed", ""), msg.get("taken", ""))
        raise ValueError(f"tipo di messaggio sconosciuto: {kind}")

    def serve(self) -> None:
        threading.Thread(target=self.load, daemon=True).start()
        threading.Thread(target=self.worker, daemon=True).start()
        while True:
            msg = self.channel.read()
            if msg is None:  # il browser ha chiuso il canale
                log.info("canale chiuso dal browser: uscita")
                return
            if msg.get("type") == "health" and not self.ready.is_set():
                self.channel.send({"id": msg.get("id"), "ok": True,
                                   "data": {"status": "loading", "transport": "native"}})
                continue
            self.jobs.put(msg)


def run(argv: list[str]) -> int:
    from shadows.engine import PROJECT_DIR

    # 1) Il canale del browser viene staccato dagli standard del processo:
    #    - stdout: copia privata per il protocollo; il descrittore 1 (e il 2) vanno
    #      sul log, così nessuna scritta estranea corrompe i messaggi;
    #    - stdin: copia privata per il protocollo; il descrittore 0 punta a NUL.
    #      Su Windows le operazioni su un handle sincrono si mettono in coda: mentre
    #      un thread aspetta un messaggio, il caricamento di una DLL (numpy, torch)
    #      che interroga lo standard input resterebbe bloccato per sempre.
    protocol_out = os.fdopen(os.dup(1), "wb", buffering=0)
    protocol_in = os.fdopen(os.dup(0), "rb", buffering=0)
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    sys.stdin = open(os.devnull, encoding="utf-8")  # noqa: SIM115
    log_path = PROJECT_DIR / "logs" / "native.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    os.dup2(log_file.fileno(), 1)
    os.dup2(log_file.fileno(), 2)
    sys.stdout = sys.stderr = log_file
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(protocol_in.fileno(), os.O_BINARY)
        msvcrt.setmode(protocol_out.fileno(), os.O_BINARY)
    logging.basicConfig(stream=log_file, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # 2) Il browser passa l'origine del chiamante come primo argomento: Chrome la
    #    verifica già con allowed_origins, qui la si ricontrolla.
    origin = next((a for a in argv if a.startswith("chrome-extension://")), "")
    expected = f"chrome-extension://{extension_id()}/"
    if origin != expected:
        log.error("origine non autorizzata: %r", origin)
        return 1
    log.info("avvio (pid %s) per %s", os.getpid(), origin)

    Host(NativeChannel(protocol_in, protocol_out)).serve()
    # Uscita immediata: i thread del modello non devono tenere vivo il processo.
    log_file.flush()
    os._exit(0)
