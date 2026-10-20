"""Adapter verso rizzo-pii, con risposte simulate nel formato reale."""

import json

import httpx
import pytest

from shadows.detectors.rizzo_pii import RizzoPiiClient, RizzoPiiUnavailable, segments_to_entities
from shadows.engine import Engine

from conftest import POLICY

TEXT = "Mario Rossi, CF RSSMRA85M01H501Q"
SEGMENTS = [
    {"label": "FULLNAME", "ph": "[FULLNAME_1]", "src": "modello", "validated": False, "t": "Mario Rossi"},
    {"t": ", CF "},
    {"label": "CF", "ph": "[CF_1]", "src": "regex", "validated": True, "t": "RSSMRA85M01H501Q"},
]


def transport(handler):
    return httpx.MockTransport(handler)


def test_segments_are_converted_to_offsets():
    ents = segments_to_entities(SEGMENTS, TEXT)
    assert [(e.label, TEXT[e.start:e.end]) for e in ents] == [
        ("FULLNAME", "Mario Rossi"), ("CF", "RSSMRA85M01H501Q")]


def test_segments_without_text_are_rejected():
    with pytest.raises(RizzoPiiUnavailable):
        segments_to_entities([{"label": "FULLNAME", "ph": "[FULLNAME_1]"}], TEXT)


def test_rizzo_pii_request_and_422_as_empty():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        if seen["body"]["text"] == "niente":
            return httpx.Response(422, json={"error": "nessuna entità"})
        return httpx.Response(200, json={"segments": SEGMENTS})

    client = RizzoPiiClient("http://pii", exclude_tags=["AGE"], transport=transport(handler))
    assert len(client.detect(TEXT)) == 2
    assert seen["body"] == {"text": TEXT, "include_mapping": True, "exclude_tags": ["AGE"]}
    assert client.detect("niente") == []


def test_engine_merges_ner_names_and_degrades_when_down(engine, tmp_path):
    ok = RizzoPiiClient("http://pii", transport=transport(
        lambda r: httpx.Response(200, json={"segments": SEGMENTS})))
    result = Engine(POLICY, base_dir=tmp_path, rizzo_pii=ok).analyze(TEXT)
    assert result.anonymized.text == "[FULLNAME_1], CF [CF_1]"
    assert result.detectors["rizzo-pii"] == "attivo"

    def down(request):
        raise httpx.ConnectError("rifiutata")

    broken = RizzoPiiClient("http://pii", transport=transport(down))
    result = Engine(POLICY, base_dir=tmp_path, rizzo_pii=broken).analyze(TEXT)
    assert result.detectors["rizzo-pii"] == "non raggiungibile"
    assert result.anonymized.text == "Mario Rossi, CF [CF_1]"  # restano regex e dizionari


def test_allow_categories_stay_in_clear(tmp_path):
    text = "Mario Rossi il 3 marzo"
    segments = [
        {"label": "FULLNAME", "ph": "[FULLNAME_1]", "src": "modello", "validated": False, "t": "Mario Rossi"},
        {"t": " il "},
        {"label": "DATE", "ph": "[DATE_1]", "src": "modello", "validated": False, "t": "3 marzo"},
    ]
    pii = RizzoPiiClient("http://pii", transport=transport(
        lambda r: httpx.Response(200, json={"segments": segments})))
    result = Engine(POLICY, base_dir=tmp_path, rizzo_pii=pii).analyze(text)
    assert result.anonymized.text == "[FULLNAME_1] il 3 marzo"
