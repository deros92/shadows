from shadows.anonymizer import anonymize, restore
from shadows.entities import Entity
from shadows.policy import Policy

from conftest import POLICY


def ent(text, value, label, source="regex"):
    start = text.index(value)
    return Entity(start, start + len(value), label, value, source)


def test_roundtrip_and_consistent_placeholders():
    text = "Mail a a@b.it e poi ancora a@b.it, in copia c@d.it"
    ents = [Entity(7, 13, "EMAIL", "a@b.it", "regex"),
            Entity(27, 33, "EMAIL", "a@b.it", "regex"),
            Entity(44, 50, "EMAIL", "c@d.it", "regex")]
    out = anonymize(text, ents)
    assert out.text == "Mail a [EMAIL_1] e poi ancora [EMAIL_1], in copia [EMAIL_2]"
    assert out.mapping == {"[EMAIL_1]": "a@b.it", "[EMAIL_2]": "c@d.it"}
    assert restore(out.text, out.mapping) == text


def test_known_mapping_is_reused_across_messages():
    first = anonymize("Cliente Rossi Food Service", [ent("Cliente Rossi Food Service", "Rossi Food Service", "CLIENTE")])
    text2 = "Rossi Food Service e SuperMercati Bianchi"
    second = anonymize(text2, [ent(text2, "Rossi Food Service", "CLIENTE"),
                               ent(text2, "SuperMercati Bianchi", "CLIENTE")], known=first.mapping)
    assert second.text == "[CLIENTE_1] e [CLIENTE_2]"


def test_restore_tolerates_missing_brackets_without_partial_matches():
    mapping = {"[CLIENTE_1]": "Bianchi", "[CLIENTE_10]": "Verdi"}
    assert restore("CLIENTE_1, [CLIENTE_10] e CLIENTE_1X", mapping) == "Bianchi, Verdi e CLIENTE_1X"


def test_policy_actions():
    policy = Policy.from_dict(POLICY)
    assert policy.decide([]).action == "allow"
    assert policy.decide([Entity(0, 1, "DATE", "x", "regex")]).action == "allow"
    assert policy.decide([Entity(0, 1, "AMOUNT", "x", "regex")]).action == "warn"
    assert policy.decide([Entity(0, 1, "IBAN", "x", "regex")]).action == "redact"
    assert policy.decide([Entity(0, 1, "SECRET", "x", "regex")]).action == "block"
    # Etichetta sconosciuta: si applica il default.
    assert policy.decide([Entity(0, 1, "TARGA", "x", "rizzo-pii")]).action == "redact"


def test_score_threshold_escalates_and_duplicates_do_not_accumulate():
    policy = Policy.from_dict(POLICY)
    amounts = [Entity(i, i + 1, "AMOUNT", f"v{i}", "regex") for i in range(3)]
    decision = policy.decide(amounts)  # 3 x 10 = 30 -> soglia redact
    assert (decision.action, decision.score) == ("redact", 30)
    same = [Entity(i, i + 1, "AMOUNT", "uguale", "regex") for i in range(3)]
    assert policy.decide(same).action == "warn"


def test_engine_end_to_end(engine):
    text = "Analizza il contratto con SuperMercati Bianchi per 2.000.000 euro, referente a@b.it"
    result = engine.analyze(text)
    assert result.decision.action == "redact"
    assert result.anonymized.text == "Analizza il contratto con [CLIENTE_1] per [AMOUNT_1], referente [EMAIL_1]"
    assert result.optional_labels == {"AMOUNT"}
    assert result.detectors["rizzo-pii"] == "disattivato"
