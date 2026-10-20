import pytest

from shadows.detectors import regex_it
from shadows.detectors.dictionary import DictionaryDetector
from shadows.entities import Entity, resolve_overlaps


def labels(text):
    return [(e.label, e.text) for e in resolve_overlaps(regex_it.detect(text))]


@pytest.mark.parametrize("cf,ok", [
    ("RSSMRA85M01H501Q", True),
    ("RSSMRA85M01H501A", False),   # carattere di controllo sbagliato
    ("rssmra85m01h501q", True),    # minuscolo
    ("RSSMRA85M01H50MI", True),    # omocodia: ultima cifra 1 -> M, controllo ricalcolato
])
def test_codice_fiscale_checksum(cf, ok):
    assert regex_it.valid_codice_fiscale(cf) is ok


def test_partita_iva_and_iban_and_card_checksums():
    assert regex_it.valid_partita_iva("01234567897")
    assert not regex_it.valid_partita_iva("01234567890")
    assert not regex_it.valid_partita_iva("00000000000")
    assert regex_it.valid_iban("IT60 X054 2811 1010 0000 0123 456")
    assert not regex_it.valid_iban("IT61 X054 2811 1010 0000 0123 456")
    assert regex_it.valid_card("4111 1111 1111 1111")
    assert not regex_it.valid_card("4111 1111 1111 1112")


def test_invalid_identifiers_are_not_entities():
    text = "Codice RSSMRA85M01H501A, conto IT61X0542811101000000123456, carta 4111111111111112"
    assert labels(text) == []


def test_detects_italian_identifiers_in_context():
    found = labels("CF RSSMRA85M01H501Q, P.IVA IT01234567897, IBAN IT60X0542811101000000123456")
    assert ("CF", "RSSMRA85M01H501Q") in found
    assert ("PIVA", "01234567897") in found
    assert ("IBAN", "IT60X0542811101000000123456") in found


def test_contacts_network_and_secrets():
    found = labels(
        "Scrivi a mario.rossi@megastore.it o al +39 347 123 4567. Host 10.0.12.5, "
        "chiave sk-proj-abcdefghijklmnopqrstuvwx1234, password: Estate2026!"
    )
    assert ("EMAIL", "mario.rossi@megastore.it") in found
    assert ("TELEPHONENUM", "+39 347 123 4567") in found
    assert ("IP", "10.0.12.5") in found
    assert ("SECRET", "sk-proj-abcdefghijklmnopqrstuvwx1234") in found
    assert ("PASSWORD", "Estate2026!") in found  # solo il valore, non la parola "password"


def test_secrets_announced_by_keyword():
    found = labels(
        "ha un API KEY sdk-23hfyhfybibfib2323bbfvbuisdfbi\n"
        "e anche la secret 328774saduad2187218sdfèààè. Il token: abcDEF123456ghiJKL. "
        "Il token è scaduto, la chiave segreta aziendale va ruotata."
    )
    secrets = [v for lab, v in found if lab == "SECRET"]
    assert secrets == ["sdk-23hfyhfybibfib2323bbfvbuisdfbi", "328774saduad2187218sdfèààè",
                       "abcDEF123456ghiJKL"]


def test_password_without_separator():
    found = labels(
        "ha creato un account con email x@y.it e password Asadrubal3059@1847.\n"
        "La password non è sicura e la password scelta va cambiata. Il PIN 48213 è nuovo."
    )
    assert ("PASSWORD", "Asadrubal3059@1847") in found  # senza il punto della frase
    assert ("PASSWORD", "48213") in found
    assert not [v for lab, v in found if lab == "PASSWORD" and v in ("non", "scelta")]


@pytest.mark.parametrize("text,value", [
    ("Mario Rossi nato a Pisa il 4/10/2002 ha creato", "4/10/2002"),
    ("nata il 4 ottobre 2002 a Pisa", "4 ottobre 2002"),
    ("Data di nascita: 04.10.02", "04.10.02"),
    ("luogo e data di nascita Pisa, 2002-10-04", "2002-10-04"),
    ("date of birth: 4-10-2002", "4-10-2002"),
])
def test_birthdate_in_context(text, value):
    assert ("BIRTHDATE", value) in labels(text)


def test_plain_date_is_not_birthdate():
    assert not [lab for lab, _ in labels("la riunione è il 4/10/2002") if lab == "BIRTHDATE"]


def test_loopback_ip_and_version_numbers_ignored():
    assert labels("vai su 127.0.0.1 con la versione 1.2.3") == []


@pytest.mark.parametrize("text,amount", [
    ("valore 2.000.000 euro", "2.000.000 euro"),
    ("budget 2M€ annuo", "2M€"),
    ("costo € 150.000 lordi", "€ 150.000"),
    ("circa 80 mila euro", "80 mila euro"),
    ("totale 1.250,50 EUR", "1.250,50 EUR"),
])
def test_euro_amounts(text, amount):
    assert ("AMOUNT", amount) in labels(text)


def test_dictionary_is_case_and_space_insensitive_and_word_bounded():
    det = DictionaryDetector({"CLIENTE": ["SuperMercati Bianchi"], "FORNITORE": ["Ortofrutta Sud"]})
    found = [(e.label, e.text) for e in det.detect(
        "Ordine per supermercati   bianchi e Ortofrutta Sudest; poi Ortofrutta Sud.")]
    assert found == [("CLIENTE", "supermercati   bianchi"), ("FORNITORE", "Ortofrutta Sud")]


def test_local_dictionary_is_merged(tmp_path):
    (tmp_path / "clienti.txt").write_text("# esempi\nCliente Esempio\n", encoding="utf-8")
    (tmp_path / "clienti.local.txt").write_text("Cliente Vero SpA\n", encoding="utf-8")
    det = DictionaryDetector.from_files({"CLIENTE": tmp_path / "clienti.txt"})
    found = [e.text for e in det.detect("Cliente Esempio e Cliente Vero SpA")]
    assert found == ["Cliente Vero SpA", "Cliente Esempio"] or set(found) == {"Cliente Esempio", "Cliente Vero SpA"}


def test_overlap_prefers_dictionary_over_model():
    model = Entity(0, 20, "ORG", "SuperMercati Bianchi", "rizzo-pii")
    dico = Entity(0, 20, "CLIENTE", "SuperMercati Bianchi", "dizionario")
    inner = Entity(13, 20, "FULLNAME", "Bianchi", "rizzo-pii")
    assert resolve_overlaps([model, inner, dico]) == [dico]
