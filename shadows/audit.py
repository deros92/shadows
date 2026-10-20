"""Registro di audit minimizzato.

Il registro di un DLP rischia di diventare l'archivio più sensibile dell'azienda.
Qui si scrivono solo metadati: mai il testo, mai i valori trovati, mai l'utente.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields) -> None:
        if not self.path:
            return
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event}
        record.update(fields)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def label_counts(labels: list[str]) -> dict[str, int]:
    return dict(Counter(labels))
