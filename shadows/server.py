"""Trasporto HTTP su 127.0.0.1: pagina demo, test, riga di comando.

Nell'uso quotidiano l'estensione parla con Shadows via native messaging
(native_host.py), senza porte aperte; questo server serve solo se lo si avvia
esplicitamente con `python -m shadows serve`.

Due controlli impediscono a un sito web qualunque di usarlo dal browser dell'utente:
- Host: deve essere 127.0.0.1 o localhost (difesa dal DNS rebinding);
- Origin: se presente deve essere un'estensione o la pagina demo locale. Le pagine
  web inviano sempre Origin nelle richieste cross-origin, quindi vengono respinte.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from shadows import __version__
from shadows.audit import AuditLog
from shadows.engine import Engine
from shadows.service import MAX_TEXT_CHARS, ServiceError, ShadowsService, audit_from_config

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
EXTENSION_SCHEMES = ("chrome-extension://", "moz-extension://")
DEMO_PAGE = Path(__file__).resolve().parent / "static" / "demo.html"


class AnalyzeRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT_CHARS)
    site: str | None = None
    known_mapping: dict[str, str] = Field(default_factory=dict)


class RestoreRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT_CHARS)
    mapping: dict[str, str]


class OutcomeEvent(BaseModel):
    site: str | None = None
    proposed: str
    taken: str  # sent_original | sent_anonymized | cancelled | ...


def create_app(engine: Engine | None = None, audit: AuditLog | None = None) -> FastAPI:
    engine = engine or Engine.from_config_file()
    service = ShadowsService(engine, audit or audit_from_config(engine))
    app = FastAPI(title="Shadows", version=__version__)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "host non consentito"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and not (origin.startswith(EXTENSION_SCHEMES) or _same_origin(origin, request)):
            return JSONResponse({"detail": "origine non consentita"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ServiceError)
    async def service_error(_request: Request, exc: ServiceError):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    @app.get("/health")
    def health():
        return service.health()

    @app.post("/v1/analyze")
    def analyze(req: AnalyzeRequest):
        return service.analyze(req.text, req.site, req.known_mapping)

    @app.post("/v1/document")
    async def document(file: UploadFile = File(...), known_mapping: str = Form("{}"),
                       site: str | None = Form(None)):
        return service.document(file.filename or "", await file.read(), site,
                                _parse_mapping(known_mapping))

    @app.post("/v1/restore")
    def restore_text(req: RestoreRequest):
        return service.restore(req.text, req.mapping)

    @app.post("/v1/event")
    def event(ev: OutcomeEvent):
        return service.event(ev.site, ev.proposed, ev.taken)

    @app.get("/demo")
    def demo():
        return FileResponse(DEMO_PAGE, media_type="text/html")

    return app


def _same_origin(origin: str, request: Request) -> bool:
    return origin == f"{request.url.scheme}://{request.headers.get('host')}"


def _parse_mapping(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "known_mapping non è JSON valido") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "known_mapping deve essere un oggetto")
    return {str(k): str(v) for k, v in value.items()}
