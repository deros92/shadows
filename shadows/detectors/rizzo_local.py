"""rizzo-pii integrato: il modello gira dentro Shadows, senza l'app rizzo-pii.

Al primo avvio il modello (licenza MIT) viene scaricato da Hugging Face nella
cartella models/ del progetto. Si scaricano solo pesi, configurazione e tokenizer:
niente file pickle (training_args.bin), che all'apertura possono eseguire codice.
"""

from __future__ import annotations

import logging
from pathlib import Path

from shadows.entities import Entity

log = logging.getLogger("shadows.rizzo")

MODEL_FILES = ["*.json", "*.safetensors", "*.txt", "*.model", "README.md"]


def ensure_model(model_dir: Path, repo: str, revision: str) -> Path:
    if (model_dir / "config.json").is_file() and any(model_dir.glob("*.safetensors")):
        return model_dir
    from huggingface_hub import snapshot_download

    print(f"Download del modello {repo}@{revision} (circa 1,2 GB, solo la prima volta)…",
          flush=True)
    snapshot_download(repo_id=repo, revision=revision, local_dir=str(model_dir),
                      allow_patterns=MODEL_FILES)
    return model_dir


class RizzoPiiLocal:
    def __init__(self, model_dir: Path, repo: str, revision: str,
                 exclude_tags: list[str] | None = None, auto_download: bool = True):
        from shadows.vendor.rizzo_pii.engine import RizzoPiiEngine

        if auto_download:
            ensure_model(model_dir, repo, revision)
        self.exclude_tags = set(exclude_tags or [])
        self.revision = revision
        self._engine = RizzoPiiEngine(model_dir)

    def healthy(self) -> bool:
        return True

    def warm_up(self) -> None:
        # La prima inferenza costa secondi: meglio pagarla all'avvio che al primo prompt.
        self._engine.analyze("Mario Rossi abita in via Garibaldi 12 a Milano.")

    def detect(self, text: str) -> list[Entity]:
        return [
            Entity(e["start"], e["end"], e["label"], text[e["start"]:e["end"]], "rizzo-pii",
                   score=1.0 if e["validated"] else round(e["score"], 3))
            for e in self._engine.analyze(text, self.exclude_tags)
        ]
