"""Dizionari aziendali: ciò che nessun modello PII può sapere.

"SuperMercati Bianchi" non è un dato personale, ma per un'azienda può essere un
cliente riservato. Ogni file di dizionario contiene un termine per riga (le righe che
iniziano con # sono commenti); l'etichetta viene dalla policy.
"""

from __future__ import annotations

import re
from pathlib import Path

from shadows.entities import Entity


class DictionaryDetector:
    def __init__(self, terms_by_label: dict[str, list[str]]):
        self._patterns: list[tuple[str, re.Pattern[str]]] = []
        for label, terms in terms_by_label.items():
            cleaned = sorted({t.strip() for t in terms if t.strip()}, key=len, reverse=True)
            if not cleaned:
                continue
            alternation = "|".join(_term_pattern(t) for t in cleaned)
            self._patterns.append(
                (label, re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE))
            )

    @classmethod
    def from_files(cls, files_by_label: dict[str, Path]) -> DictionaryDetector:
        """Accanto a clienti.txt legge anche clienti.local.txt, se esiste.

        I .txt del repository contengono solo esempi; i nomi veri vanno nei
        .local.txt, che .gitignore esclude: pubblicarli sarebbe proprio la fuga di
        dati che Shadows deve impedire.
        """
        terms: dict[str, list[str]] = {}
        for label, path in files_by_label.items():
            terms[label] = []
            for source in (path, path.with_suffix(".local" + path.suffix)):
                if source.exists():
                    terms[label] += [ln for ln in source.read_text(encoding="utf-8").splitlines()
                                     if ln.strip() and not ln.lstrip().startswith("#")]
        return cls(terms)

    @property
    def size(self) -> int:
        return len(self._patterns)

    def detect(self, text: str) -> list[Entity]:
        return [
            Entity(m.start(), m.end(), label, m.group(0), "dizionario")
            for label, pattern in self._patterns
            for m in pattern.finditer(text)
        ]


def _term_pattern(term: str) -> str:
    # Gli spazi del termine accettano qualunque spaziatura ("Super  Mercati").
    return r"\s+".join(re.escape(part) for part in term.split())
