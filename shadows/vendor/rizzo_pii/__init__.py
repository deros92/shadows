"""Motore di rizzo-pii incluso in Shadows (licenza MIT, vedi LICENSE in questa cartella).

Origine: https://github.com/Rizzo-AI-Academy/rizzo-pii
commit 30d6f9c675e245bc8494df959adaeaa9d8de35c7 (2026-10-18), Copyright (c) 2026
Simone Rizzo — Rizzo AI Academy.

- detectors.py: copiato SENZA modifiche da src/app/detectors.py (rete regex con checksum).
- engine.py: chunking, inferenza e fusione, adattati da src/app/app.py (chunk_text,
  detect_model, _merge, analyze) togliendo l'interfaccia Flask e la parte PDF.

Non sono inclusi l'app (Flask, Tauri) né PyMuPDF: Shadows legge i PDF da sé.
"""
