"""Motore di rizzo-pii senza l'app: modello NER + rete regex + fusione.

Adattato da src/app/app.py di rizzo-pii (MIT, Copyright (c) 2026 Simone Rizzo —
Rizzo AI Academy). La logica di chunking e fusione è la stessa dell'app, così il
riconoscimento resta identico; cambia solo che il modello viene caricato qui.
"""

from __future__ import annotations

import bisect
import re
import threading
from pathlib import Path

from .detectors import SOFT_REGEX_LABELS, complete_time, detect_regex

MAX_WORDS = 120  # parole per chunk (~180 subword, sotto i 512 del training)
OVERLAP = 20     # parole di sovrapposizione tra chunk consecutivi


def chunk_text(text: str, max_words: int = MAX_WORDS, overlap: int = OVERLAP):
    """[(sottostringa, offset_globale), ...] senza tagliare parole."""
    words = list(re.finditer(r"\S+", text))
    if not words:
        return []
    chunks, i = [], 0
    step = max(1, max_words - overlap)
    while i < len(words):
        block = words[i:i + max_words]
        start, end = block[0].start(), block[-1].end()
        chunks.append((text[start:end], start))
        if i + max_words >= len(words):
            break
        i += step
    return chunks


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def merge(cands: list[dict], text: str) -> list[dict]:
    """Greedy senza overlap. Priorità: checksum valido > regex (non soft) > score > lunghezza.
    Poi allinea gli span ai confini di parola: meglio mascherare un carattere in più
    che lasciare "[CITY_1]vara"."""
    order = sorted(
        cands,
        key=lambda e: (1 if e["validated"] else 0,
                       1 if (e["source"] == "regex" and e["label"] not in SOFT_REGEX_LABELS) else 0,
                       e["score"], e["end"] - e["start"]),
        reverse=True,
    )
    kept: list[dict] = []
    for e in order:
        i = bisect.bisect_right(kept, e["start"], key=lambda k: k["start"])
        if (i and kept[i - 1]["end"] > e["start"]) or (i < len(kept) and kept[i]["start"] < e["end"]):
            continue
        kept.insert(i, e)
    for e in kept:  # niente spazi inglobati negli span
        while e["start"] < e["end"] and text[e["start"]].isspace():
            e["start"] += 1
        while e["end"] > e["start"] and text[e["end"] - 1].isspace():
            e["end"] -= 1
    kept = [e for e in kept if e["end"] > e["start"]]
    for e in kept:  # estensione ai confini di parola
        while e["start"] > 0 and _is_word(text[e["start"] - 1]) and _is_word(text[e["start"]]):
            e["start"] -= 1
        while e["end"] < len(text) and _is_word(text[e["end"]]) and _is_word(text[e["end"] - 1]):
            e["end"] += 1
    kept.sort(key=lambda e: (e["start"], -(e["end"] - e["start"])))
    merged: list[dict] = []
    for e in kept:
        if merged and e["start"] < merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], e["end"])
            continue
        if merged and e["start"] == merged[-1]["end"] and e["label"] == merged[-1]["label"]:
            merged[-1]["end"] = e["end"]
            continue
        merged.append(e)
    return merged


class RizzoPiiEngine:
    """Carica il modello una volta; analyze() è sicuro tra thread (un lock per l'inferenza)."""

    def __init__(self, model_dir: Path, device: int = -1):
        from transformers import pipeline

        self.model_dir = Path(model_dir)
        self._nlp = pipeline("token-classification", model=str(self.model_dir),
                             tokenizer=str(self.model_dir), aggregation_strategy="simple",
                             device=device)
        self._lock = threading.Lock()

    def _detect_model(self, text: str) -> list[dict]:
        chunks = chunk_text(text)
        if not chunks:
            return []
        with self._lock:
            results = self._nlp([c for c, _ in chunks])
        if isinstance(results, dict):
            results = [results]
        ents = []
        for (_, off), res in zip(chunks, results):
            for e in res:
                ents.append({"label": e["entity_group"], "start": int(e["start"]) + off,
                             "end": int(e["end"]) + off, "score": float(e["score"]),
                             "validated": False, "source": "modello"})
        return ents

    def analyze(self, text: str, excluded: set[str] | None = None) -> list[dict]:
        """Entità finali come in rizzo-pii: dict con label, start, end, score, validated, source."""
        model_ents = self._detect_model(text)
        complete_time(model_ents, text)  # il modello taglia i minuti delle ore
        cands = model_ents + detect_regex(text)
        if excluded:
            cands = [e for e in cands if e["label"] not in excluded]
        return merge(cands, text)
