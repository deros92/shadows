"""Motore di policy deterministico.

I detector producono segnali; la decisione la prendono regole leggibili in YAML.
Così ogni blocco è spiegabile in un audit ("bloccato perché conteneva SECRET"),
cosa che un punteggio prodotto da un modello non garantisce.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shadows.entities import Entity

ACTIONS = ["allow", "warn", "redact", "block"]


def _rank(action: str) -> int:
    return ACTIONS.index(action)


def stricter(a: str, b: str) -> str:
    return a if _rank(a) >= _rank(b) else b


@dataclass
class CategoryRule:
    weight: int
    action: str


@dataclass
class Decision:
    action: str
    score: int
    reasons: list[str] = field(default_factory=list)


class Policy:
    def __init__(self, categories: dict[str, CategoryRule], default: CategoryRule,
                 thresholds: dict[str, int]):
        for rule in [*categories.values(), default]:
            if rule.action not in ACTIONS:
                raise ValueError(f"azione sconosciuta: {rule.action}")
        self.categories = categories
        self.default = default
        self.thresholds = thresholds

    @classmethod
    def from_dict(cls, raw: dict) -> Policy:
        def rule(d: dict) -> CategoryRule:
            return CategoryRule(int(d.get("peso", 0)), d.get("azione", "allow"))

        return cls(
            categories={k: rule(v) for k, v in raw.get("categorie", {}).items()},
            default=rule(raw.get("default", {"peso": 10, "azione": "redact"})),
            thresholds={k: int(v) for k, v in raw.get("soglie", {}).items()},
        )

    def rule_for(self, label: str) -> CategoryRule:
        return self.categories.get(label, self.default)

    def decide(self, entities: list[Entity]) -> Decision:
        action = "allow"
        reasons: list[str] = []
        seen: set[tuple[str, str]] = set()
        score = 0
        for ent in entities:
            rule = self.rule_for(ent.label)
            key = (ent.label, " ".join(ent.text.split()).casefold())
            if key not in seen:  # lo stesso valore ripetuto non accumula rischio
                seen.add(key)
                score += rule.weight
            if _rank(rule.action) > _rank(action):
                reasons.append(f"{ent.label}: azione '{rule.action}' da policy")
            action = stricter(action, rule.action)

        score = min(score, 100)
        for level in ("warn", "redact", "block"):
            limit = self.thresholds.get(level)
            if limit is not None and score >= limit and _rank(level) > _rank(action):
                reasons.append(f"punteggio {score} >= soglia '{level}' ({limit})")
                action = level
        return Decision(action, score, reasons)
