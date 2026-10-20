"""Motore rizzo-pii integrato: logica di chunking e fusione, più il modello vero se presente."""

from pathlib import Path

import pytest

from shadows.vendor.rizzo_pii.engine import chunk_text, merge

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "rizzo-pii-0.3B-v1.5.0"


def ent(text, value, label, source="modello", score=0.9, validated=False, cut=(0, 0)):
    start = text.index(value) + cut[0]
    return {"label": label, "start": start, "end": start + len(value) - cut[1],
            "score": score, "validated": validated, "source": source}


def test_chunks_overlap_and_keep_offsets():
    words = [f"parola{i}" for i in range(250)]
    text = " ".join(words)
    chunks = chunk_text(text, max_words=120, overlap=20)
    assert len(chunks) == 3
    for chunk, offset in chunks:
        assert text[offset:offset + len(chunk)] == chunk
    assert chunks[1][0].split()[0] == "parola100"  # 20 parole di sovrapposizione


def test_merge_extends_partial_words_and_trims_spaces():
    text = "Udienza a Novara domani"
    # il modello copre solo "No" di "Novara" e uno spazio iniziale
    partial = {"label": "CITY", "start": text.index("Novara") - 1, "end": text.index("Novara") + 2,
               "score": 0.8, "validated": False, "source": "modello"}
    [out] = merge([partial], text)
    assert text[out["start"]:out["end"]] == "Novara"


def test_merge_prefers_validated_regex():
    text = "CF RSSMRA85M01H501Q fine"
    model = ent(text, "RSSMRA85M01H5", "ID_DOC", score=0.99)
    regex = ent(text, "RSSMRA85M01H501Q", "CF", source="regex", score=1.0, validated=True)
    [out] = merge([model, regex], text)
    assert out["label"] == "CF"


@pytest.mark.skipif(not (MODEL_DIR / "model.safetensors").exists(), reason="modello non scaricato")
def test_real_model_on_invoice_example():
    from shadows.detectors.rizzo_local import RizzoPiiLocal

    text = ("Mario Rossi p.iva IT3823782372743 chiede pagamento fattura 23255 di importo "
            "1456,78 non pagata da Luigi Verdi p.iva IT7347437")
    found = {(e.label, e.text) for e in RizzoPiiLocal(MODEL_DIR, "", "", auto_download=False).detect(text)}
    assert {("FULLNAME", "Mario Rossi"), ("FULLNAME", "Luigi Verdi"), ("DOCID", "23255")} <= found
