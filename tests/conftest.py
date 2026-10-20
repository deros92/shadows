import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shadows.engine import Engine  # noqa: E402

POLICY = {
    "dizionari": {},
    "soglie": {"warn": 10, "redact": 30, "block": 101},
    "default": {"peso": 15, "azione": "redact"},
    "categorie": {
        "SECRET": {"peso": 100, "azione": "block"},
        "IBAN": {"peso": 50, "azione": "redact"},
        "CF": {"peso": 40, "azione": "redact"},
        "EMAIL": {"peso": 20, "azione": "redact"},
        "CLIENTE": {"peso": 30, "azione": "redact"},
        "AMOUNT": {"peso": 10, "azione": "warn"},
        "DATE": {"peso": 2, "azione": "allow"},
    },
}


@pytest.fixture
def engine(tmp_path):
    clienti = tmp_path / "clienti.txt"
    clienti.write_text("# commento\nSuperMercati Bianchi\nRossi Food Service\n", encoding="utf-8")
    config = {**POLICY, "dizionari": {"CLIENTE": "clienti.txt"}}
    return Engine(config, base_dir=tmp_path)
