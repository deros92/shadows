"""Riga di comando.

    python -m shadows install-native        registra Shadows presso Chrome ed Edge (uso normale)
    python -m shadows uninstall-native      annulla la registrazione
    python -m shadows native ...            avviato dal browser, non a mano
    python -m shadows serve                 servizio HTTP locale (demo, test)
    python -m shadows scan contratto.pdf    anonimizza un file e stampa il risultato
    python -m shadows scan -                legge il testo da stdin
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shadows.documents import extract_text
from shadows.engine import Engine


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Avviato dal browser: gli argomenti sono di Chrome (origine, --parent-window).
    if argv[:1] == ["native"]:
        from shadows.native_host import run

        return run(argv[1:])

    parser = argparse.ArgumentParser(prog="shadows")
    parser.add_argument("--config", type=Path, help="policy YAML (default config/policy.yaml)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, text in (("install-native", "registra Shadows presso i browser"),
                       ("uninstall-native", "annulla la registrazione")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--browsers", nargs="+", default=["chrome", "edge"],
                       choices=["chrome", "edge", "chromium"])

    serve = sub.add_parser("serve", help="avvia il servizio HTTP locale")
    serve.add_argument("--port", type=int)

    scan = sub.add_parser("scan", help="analizza un file o stdin")
    scan.add_argument("path", help="file (.pdf .docx .txt .md ...) oppure - per stdin")
    scan.add_argument("--json", action="store_true", help="output JSON completo")

    args = parser.parse_args(argv)
    # Su Windows stdin/stdout usano la codepage locale: "€" arriverebbe corrotto.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    if args.cmd in ("install-native", "uninstall-native"):
        from shadows import native_install

        if args.cmd == "uninstall-native":
            native_install.uninstall(args.browsers)
            print(f"Registrazione rimossa per: {', '.join(args.browsers)}")
            return 0
        # Il modello si scarica qui, dove si vede l'avanzamento, e non al primo avvio
        # dal browser, dove l'utente vedrebbe solo "caricamento" per minuti.
        import yaml

        from shadows.detectors.rizzo_local import ensure_model
        from shadows.engine import DEFAULT_CONFIG, PROJECT_DIR

        pii = (yaml.safe_load(Path(args.config or DEFAULT_CONFIG).read_text(encoding="utf-8"))
               .get("rizzo_pii") or {})
        if pii.get("enabled") and pii.get("mode", "integrato") == "integrato":
            ensure_model(PROJECT_DIR / pii.get("model_dir", "models/rizzo-pii-0.3B-v1.5.0"),
                         pii.get("repo", "rizzoaiacademy/rizzo-pii-0.3B"),
                         pii.get("revision", "v1.5.0"))
            print("Modello rizzo-pii presente.")
        info = native_install.install(args.browsers)
        print("Shadows registrato. Da ora è il browser ad avviarlo: nessuna finestra, nessuna porta.")
        print(f"  browser:            {', '.join(info['browsers'])}")
        print(f"  estensione ammessa: {info['extension_id']}")
        print(f"  manifest:           {info['manifest']}")
        print("Ricarica l'estensione in chrome://extensions e riapri le schede delle chat.")
        return 0

    print("Avvio di Shadows: caricamento del modello rizzo-pii (qualche secondo)…",
          file=sys.stderr, flush=True)
    engine = Engine.from_config_file(args.config)

    if args.cmd == "serve":
        import uvicorn

        from shadows.server import create_app

        if hasattr(engine.rizzo_pii, "warm_up"):
            engine.rizzo_pii.warm_up()
        server_cfg = engine.config.get("server") or {}
        port = args.port or int(server_cfg.get("port", 8765))
        print(f"Shadows attivo su http://127.0.0.1:{port}  (demo: /demo, CTRL+C per uscire)",
              flush=True)
        # Volutamente niente opzione --host: il servizio deve restare su loopback.
        uvicorn.run(create_app(engine), host="127.0.0.1", port=port, log_level="warning")
        return 0

    if args.path == "-":
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        warnings: list[str] = []
    else:
        path = Path(args.path)
        doc = extract_text(path.name, path.read_bytes())
        text, warnings = doc.text, doc.warnings

    result = engine.analyze(text)
    if args.json:
        print(json.dumps({
            "action": result.decision.action, "score": result.decision.score,
            "reasons": result.decision.reasons, "detectors": result.detectors,
            "warnings": warnings, "anonymized_text": result.anonymized.text,
            "mapping": result.anonymized.mapping,
        }, ensure_ascii=False, indent=2))
    else:
        for w in warnings:
            print(f"ATTENZIONE: {w}", file=sys.stderr)
        print(f"Decisione: {result.decision.action}  (punteggio {result.decision.score})",
              file=sys.stderr)
        for reason in result.decision.reasons:
            print(f"  - {reason}", file=sys.stderr)
        print(f"Detector: {result.detectors}", file=sys.stderr)
        print("-" * 60, file=sys.stderr)
        print(result.anonymized.text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
