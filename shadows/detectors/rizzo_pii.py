"""Adapter per rizzo-pii (NER italiano) eseguito come servizio separato.

rizzo-pii gira come processo a sé (app desktop, Docker o `python src/app/app.py`) e
Shadows lo chiama via HTTP: il suo codice non viene incluso né modificato, quindi
la licenza dei suoi binari non si estende a Shadows.

POST /analyze risponde con `segments`, la sequenza ordinata dei pezzi di testo:
i segmenti di testo hanno solo `t`, quelli di entità hanno `label`, `ph`, `src`,
`validated` e `t` (quest'ultimo solo se il mapping è attivo). Gli offset non sono
restituiti, quindi li ricostruiamo sommando le lunghezze dei segmenti.
"""

from __future__ import annotations

import httpx

from shadows.entities import Entity


class RizzoPiiUnavailable(RuntimeError):
    pass


class RizzoPiiClient:
    def __init__(self, url: str, timeout: float = 10.0, exclude_tags: list[str] | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        self.exclude_tags = exclude_tags or []
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def healthy(self) -> bool:
        try:
            return self._client.get(f"{self.url}/health").status_code == 200
        except httpx.HTTPError:
            return False

    def detect(self, text: str) -> list[Entity]:
        payload = {"text": text, "include_mapping": True}
        if self.exclude_tags:
            payload["exclude_tags"] = self.exclude_tags
        try:
            resp = self._client.post(f"{self.url}/analyze", json=payload)
        except httpx.HTTPError as exc:
            raise RizzoPiiUnavailable(str(exc)) from exc
        if resp.status_code == 422:  # nessuna entità trovata
            return []
        if resp.status_code != 200:
            raise RizzoPiiUnavailable(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return segments_to_entities(resp.json().get("segments", []), text)


def segments_to_entities(segments: list[dict], source_text: str) -> list[Entity]:
    entities: list[Entity] = []
    pos = 0
    for seg in segments:
        if "t" not in seg:
            raise RizzoPiiUnavailable(
                "rizzo-pii ha risposto senza testo nei segmenti: attivare il mapping "
                "(mapping_enabled) per poter ricostruire le posizioni"
            )
        chunk = seg["t"]
        # Il testo può essere stato normalizzato a monte: riallineiamo cercando il pezzo.
        found = source_text.find(chunk, pos)
        start = found if found != -1 else pos
        end = start + len(chunk)
        if "label" in seg and chunk.strip():
            entities.append(Entity(start, end, seg["label"], source_text[start:end], "rizzo-pii",
                                   score=1.0 if seg.get("validated") else 0.9))
        pos = end
    return entities
