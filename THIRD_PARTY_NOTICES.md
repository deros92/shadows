# Componenti di terze parti

Shadows è distribuito con licenza MIT. Tutti i componenti sotto hanno licenze
permissive che **non** obbligano a pubblicare il codice di Shadows né a cambiarne
la licenza. **PyMuPDF non è usato** (licenza AGPL-3.0).

## Incluso nel repository

| Componente | Licenza | Dove |
|---|---|---|
| Motore di [rizzo-pii](https://github.com/Rizzo-AI-Academy/rizzo-pii): `detectors.py` (senza modifiche) e logica di chunking/fusione adattata da `app.py`, commit `30d6f9c` | MIT, Copyright (c) 2026 Simone Rizzo — Rizzo AI Academy | [shadows/vendor/rizzo_pii/](shadows/vendor/rizzo_pii/), licenza in `LICENSE` nella stessa cartella |

## Scaricato al primo avvio (non nel repository)

| Componente | Licenza | Note |
|---|---|---|
| Modello [rizzoaiacademy/rizzo-pii-0.3B](https://huggingface.co/rizzoaiacademy/rizzo-pii-0.3B) v1.5.0 | MIT, © 2026 Simone Rizzo — Rizzo AI Academy | in `models/`; basato su [jhu-clsp/mmBERT-base](https://huggingface.co/jhu-clsp/mmBERT-base) (MIT) |
| Modelli Tesseract tessdata_best (ita, eng) | Apache-2.0 | in `tessdata/`, solo se si usa l'OCR |

Chi usa rizzo-pii in lavori accademici è invitato dall'autore a citarlo
(riferimento BibTeX nella pagina del modello).

## Dipendenze Python

| Libreria | Licenza | Uso |
|---|---|---|
| FastAPI | MIT | servizio HTTP |
| Uvicorn | BSD-3-Clause | server ASGI |
| Pydantic | MIT | validazione delle richieste |
| PyYAML | MIT | lettura della policy |
| HTTPX | BSD-3-Clause | client verso servizi esterni facoltativi |
| python-multipart | Apache-2.0 | upload dei documenti |
| pdfplumber, pdfminer.six | MIT | estrazione del testo dai PDF |
| pypdfium2 / PDFium | Apache-2.0 o BSD-3-Clause / BSD-3-Clause | render delle pagine per l'OCR |
| python-docx | MIT | estrazione del testo dai file Word |
| PyTorch | BSD-3-Clause | esecuzione del modello |
| Transformers, huggingface_hub | Apache-2.0 | caricamento e download del modello |
| pytesseract + Tesseract (facoltativi) | Apache-2.0 | OCR delle scansioni e delle foto |

## Servizio esterno facoltativo (chiamato via HTTP, non incluso)

| Servizio | Licenza | Nota |
|---|---|---|
| App rizzo-pii (modalità `servizio`) | codice MIT; binari rilasciati AGPL-3.0 (includono PyMuPDF) | Processo separato avviato dall'utente: gli obblighi AGPL riguardano quell'app, non Shadows |

Questa tabella è una ricognizione tecnica, non un parere legale.
