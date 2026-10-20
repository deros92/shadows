"""Pipeline completa: detector -> risoluzione sovrapposizioni -> policy -> anonimizzazione."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from shadows.anonymizer import Anonymized, anonymize
from shadows.detectors import regex_it
from shadows.detectors.dictionary import DictionaryDetector
from shadows.detectors.rizzo_pii import RizzoPiiClient, RizzoPiiUnavailable
from shadows.entities import Entity, resolve_overlaps
from shadows.policy import Decision, Policy

log = logging.getLogger("shadows")

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_DIR / "config" / "policy.yaml"


@dataclass
class AnalysisResult:
    decision: Decision
    entities: list[Entity]
    anonymized: Anonymized
    detectors: dict[str, str]
    optional_labels: set[str] = field(default_factory=set)


class Engine:
    def __init__(self, config: dict, base_dir: Path = PROJECT_DIR,
                 rizzo_pii=None):  # RizzoPiiClient, RizzoPiiLocal o altro con .detect()
        self.config = config
        self.policy = Policy.from_dict(config)
        self.dictionary = DictionaryDetector.from_files(
            {label: base_dir / rel for label, rel in (config.get("dizionari") or {}).items()}
        )

        pii_cfg = config.get("rizzo_pii") or {}
        if rizzo_pii is None and pii_cfg.get("enabled"):
            if pii_cfg.get("mode", "integrato") == "integrato":
                # Il modello gira dentro Shadows: niente app rizzo-pii da installare.
                from shadows.detectors.rizzo_local import RizzoPiiLocal

                rizzo_pii = RizzoPiiLocal(
                    base_dir / pii_cfg.get("model_dir", "models/rizzo-pii-0.3B-v1.5.0"),
                    repo=pii_cfg.get("repo", "rizzoaiacademy/rizzo-pii-0.3B"),
                    revision=pii_cfg.get("revision", "v1.5.0"),
                    exclude_tags=pii_cfg.get("exclude_tags"),
                )
            else:
                # Modalità "servizio": un'app rizzo-pii già avviata a parte (desktop o Docker).
                rizzo_pii = RizzoPiiClient(pii_cfg["url"], float(pii_cfg.get("timeout", 10)),
                                           pii_cfg.get("exclude_tags"))
        self.rizzo_pii = rizzo_pii

    @classmethod
    def from_config_file(cls, path: Path | None = None) -> Engine:
        path = Path(path or os.environ.get("SHADOWS_CONFIG") or DEFAULT_CONFIG)
        with path.open(encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
        return cls(config, base_dir=PROJECT_DIR)

    def status(self) -> dict[str, str]:
        return {
            "regex": "attivo",
            "dizionari": f"{self.dictionary.size} categorie",
            "rizzo-pii": self._remote_status(self.rizzo_pii),
        }

    @staticmethod
    def _remote_status(client) -> str:
        if client is None:
            return "disattivato"
        return "attivo" if client.healthy() else "non raggiungibile"

    def analyze(self, text: str, known: dict[str, str] | None = None) -> AnalysisResult:
        detectors = {"regex": "attivo", "dizionari": f"{self.dictionary.size} categorie"}
        candidates = regex_it.detect(text) + self.dictionary.detect(text)

        if self.rizzo_pii is None:
            detectors["rizzo-pii"] = "disattivato"
        else:
            try:
                candidates += self.rizzo_pii.detect(text)
                detectors["rizzo-pii"] = "attivo"
            except RizzoPiiUnavailable as exc:
                # Si degrada a regex + dizionari e lo si dichiara: l'estensione lo mostra.
                log.warning("rizzo-pii non disponibile: %s", exc)
                detectors["rizzo-pii"] = "non raggiungibile"

        entities = resolve_overlaps(candidates)
        decision = self.policy.decide(entities)

        # Le categorie "allow" (es. le date) restano in chiaro: la policy le ritiene innocue.
        entities = [e for e in entities if self.policy.rule_for(e.label).action != "allow"]
        optional = {e.label for e in entities if self.policy.rule_for(e.label).action == "warn"}
        return AnalysisResult(decision, entities, anonymize(text, entities, known),
                              detectors, optional)
