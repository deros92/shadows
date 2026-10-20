"""Strutture dati condivise tra detector, anonimizzatore e policy."""

from __future__ import annotations

from dataclasses import dataclass

# Priorità di risoluzione quando due entità si sovrappongono: vince la più alta.
# I dizionari aziendali sono la fonte più specifica (sanno che "Bianchi" è un
# CLIENTE, non solo un'organizzazione); le regex validate da checksum sono
# deterministiche; il modello NER è probabilistico.
PRIORITY = {
    "dizionario": 40,
    "regex-validata": 30,
    "regex": 20,
    "rizzo-pii": 10,
}


@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    label: str
    text: str
    source: str  # chiave di PRIORITY
    score: float = 1.0

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def priority(self) -> int:
        return PRIORITY.get(self.source, 0)


def resolve_overlaps(entities: list[Entity]) -> list[Entity]:
    """Tiene un solo span per regione di testo: priorità, poi lunghezza, poi posizione."""
    ranked = sorted(entities, key=lambda e: (-e.priority, -e.length, e.start))
    kept: list[Entity] = []
    for ent in ranked:
        if all(ent.end <= k.start or ent.start >= k.end for k in kept):
            kept.append(ent)
    return sorted(kept, key=lambda e: e.start)
