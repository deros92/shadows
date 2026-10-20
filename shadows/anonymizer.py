"""Sostituzione reversibile: valore sensibile -> placeholder, e ritorno.

Lo stesso valore riceve sempre lo stesso placeholder, anche tra messaggi diversi
della stessa conversazione (passando `known`), così l'AI può ragionare su
"[CLIENTE_1]" in modo coerente e il ripristino nella risposta resta univoco.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from shadows.entities import Entity

_PLACEHOLDER = re.compile(r"\[([A-Z][A-Z0-9]*)_(\d+)\]")


@dataclass
class Anonymized:
    text: str
    mapping: dict[str, str]  # placeholder -> valore originale
    replacements: list[tuple[Entity, str]] = field(default_factory=list)


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def anonymize(text: str, entities: list[Entity], known: dict[str, str] | None = None) -> Anonymized:
    mapping = dict(known or {})
    by_value = {(_label_of(ph), _norm(v)): ph for ph, v in mapping.items()}
    counters: dict[str, int] = {}
    for ph in mapping:
        m = _PLACEHOLDER.fullmatch(ph)
        if m:
            counters[m.group(1)] = max(counters.get(m.group(1), 0), int(m.group(2)))

    out: list[str] = []
    replacements: list[tuple[Entity, str]] = []
    cursor = 0
    for ent in sorted(entities, key=lambda e: e.start):
        key = (ent.label, _norm(ent.text))
        ph = by_value.get(key)
        if ph is None:
            counters[ent.label] = counters.get(ent.label, 0) + 1
            ph = f"[{ent.label}_{counters[ent.label]}]"
            by_value[key] = ph
            mapping[ph] = ent.text
        out.append(text[cursor:ent.start])
        out.append(ph)
        replacements.append((ent, ph))
        cursor = ent.end
    out.append(text[cursor:])
    return Anonymized("".join(out), mapping, replacements)


def restore(text: str, mapping: dict[str, str]) -> str:
    """Rimette i valori reali. Tollera l'AI che toglie le parentesi ("CLIENTE_1")."""
    if not mapping:
        return text
    bare = {ph.strip("[]"): value for ph, value in mapping.items()}
    names = sorted(bare, key=len, reverse=True)
    pattern = re.compile(
        r"\[(" + "|".join(map(re.escape, names)) + r")\]|\b(" + "|".join(map(re.escape, names)) + r")\b"
    )
    return pattern.sub(lambda m: bare[m.group(1) or m.group(2)], text)


def _label_of(placeholder: str) -> str:
    m = _PLACEHOLDER.fullmatch(placeholder)
    return m.group(1) if m else ""
