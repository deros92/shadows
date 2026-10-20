"""Le operazioni di Shadows, indipendenti da come arrivano le richieste.

Due "trasporti" le espongono all'estensione:
- native messaging (native_host.py): canale privato aperto dal browser, nessuna porta;
- HTTP su 127.0.0.1 (server.py): per la pagina demo, i test e la riga di comando.
"""

from __future__ import annotations

from shadows import __version__
from shadows.anonymizer import restore
from shadows.audit import AuditLog, label_counts
from shadows.documents import UnsupportedDocument, extract_text
from shadows.engine import PROJECT_DIR, AnalysisResult, Engine

MAX_TEXT_CHARS = 200_000


class ServiceError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def audit_from_config(engine: Engine) -> AuditLog:
    cfg = engine.config.get("audit") or {}
    return AuditLog(PROJECT_DIR / cfg["path"] if cfg.get("enabled") else None)


class ShadowsService:
    def __init__(self, engine: Engine, audit: AuditLog):
        self.engine = engine
        self.audit = audit

    def health(self) -> dict:
        return {"status": "ok", "version": __version__, "detectors": self.engine.status()}

    def analyze(self, text: str, site: str | None = None,
                known_mapping: dict[str, str] | None = None) -> dict:
        if len(text) > MAX_TEXT_CHARS:
            raise ServiceError(413, f"testo oltre {MAX_TEXT_CHARS} caratteri")
        result = self.engine.analyze(text, _clean_mapping(known_mapping))
        self._audit("analyze", site, len(text), result)
        return serialize(result)

    def document(self, filename: str, data: bytes, site: str | None = None,
                 known_mapping: dict[str, str] | None = None) -> dict:
        try:
            doc = extract_text(filename or "", data)
        except UnsupportedDocument as exc:
            raise ServiceError(415, str(exc)) from exc
        if not doc.text.strip():
            raise ServiceError(422, "nessun testo estraibile dal documento; " + "; ".join(doc.warnings))
        result = self.engine.analyze(doc.text[:MAX_TEXT_CHARS], _clean_mapping(known_mapping))
        self._audit("document", site, len(doc.text), result, kind=doc.kind)
        body = serialize(result)
        body["document"] = {"kind": doc.kind, "pages": doc.pages, "chars": len(doc.text),
                            "truncated": len(doc.text) > MAX_TEXT_CHARS, "warnings": doc.warnings}
        return body

    def restore(self, text: str, mapping: dict[str, str]) -> dict:
        return {"text": restore(text, _clean_mapping(mapping))}

    def event(self, site: str | None, proposed: str, taken: str) -> dict:
        self.audit.write("outcome", site=site, proposed=str(proposed), taken=str(taken))
        return {"status": "ok"}

    def _audit(self, event: str, site: str | None, n_chars: int, result: AnalysisResult,
               **extra) -> None:
        self.audit.write(event, site=site, chars=n_chars, action=result.decision.action,
                         score=result.decision.score,
                         labels=label_counts([e.label for e in result.entities]),
                         detectors=result.detectors, **extra)


def _clean_mapping(value) -> dict[str, str]:
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ServiceError(400, "la mappa deve essere un oggetto")
    return {str(k): str(v) for k, v in value.items()}


def serialize(result: AnalysisResult) -> dict:
    return {
        "action": result.decision.action,
        "score": result.decision.score,
        "reasons": result.decision.reasons,
        "anonymized_text": result.anonymized.text,
        "mapping": result.anonymized.mapping,
        "entities": [
            {"start": e.start, "end": e.end, "label": e.label, "value": e.text,
             "source": e.source, "placeholder": ph, "optional": e.label in result.optional_labels}
            for e, ph in result.anonymized.replacements
        ],
        "detectors": result.detectors,
    }
