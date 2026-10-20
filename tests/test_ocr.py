"""OCR su documenti scansionati: PDF fatti solo di immagini e foto."""

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from shadows.documents import extract_text, ocr_available

pytestmark = pytest.mark.skipif(not ocr_available(), reason="Tesseract non installato")

LINES = [
    "CONTRATTO DI FORNITURA",
    "Cliente: SuperMercati Bianchi",
    "Codice fiscale RSSMRA85M01H501Q",
    "IBAN IT60X0542811101000000123456",
    "Il fornitore si impegna alla consegna entro novanta giorni.",
]


def scanned_page() -> Image.Image:
    font_path = Path(r"C:\Windows\Fonts\arial.ttf")
    font = ImageFont.truetype(str(font_path), 34) if font_path.exists() else ImageFont.load_default()
    page = Image.new("L", (1700, 900), 255)
    draw = ImageDraw.Draw(page)
    for i, line in enumerate(LINES):
        draw.text((90, 90 + i * 80), line, fill=0, font=font)
    return page


def test_scanned_pdf_is_read_with_ocr(engine):
    buf = io.BytesIO()
    scanned_page().save(buf, format="PDF", resolution=150)  # PDF senza testo, solo immagine
    doc = extract_text("scansione.pdf", buf.getvalue())
    assert any("OCR" in w for w in doc.warnings)
    assert "RSSMRA85M01H501Q" in doc.text
    assert "IT60X0542811101000000123456" in doc.text.replace(" ", "")

    result = engine.analyze(doc.text)
    labels = {e.label for e in result.entities}
    assert {"CLIENTE", "CF", "IBAN"} <= labels


def test_photo_is_read_with_ocr():
    buf = io.BytesIO()
    scanned_page().convert("RGB").save(buf, format="JPEG", quality=90)
    doc = extract_text("foto.jpg", buf.getvalue())
    assert doc.kind == "immagine"
    assert "SuperMercati Bianchi" in doc.text
