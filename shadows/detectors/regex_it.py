"""Livello deterministico: regex con validazione dei checksum per gli identificativi italiani.

Un match conta come entità solo se supera il checksum (codice fiscale, partita IVA,
IBAN mod-97, carta con Luhn): così le stringhe che "sembrano" un identificativo
ma non lo sono non generano falsi positivi. Le etichette coincidono con quelle di
rizzo-pii dove esistono, così i due livelli si fondono senza tabelle di conversione.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Iterator

from shadows.entities import Entity

# --- Checksum ---------------------------------------------------------------

_CF_ODD = {
    **dict(zip("0123456789", [1, 0, 5, 7, 9, 13, 15, 17, 19, 21])),
    **dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
               [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12,
                14, 16, 10, 22, 25, 24, 23])),
}
_CF_EVEN = {**{str(d): d for d in range(10)},
            **{c: i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}}


def valid_codice_fiscale(cf: str) -> bool:
    cf = cf.upper()
    if len(cf) != 16:
        return False
    total = sum(_CF_ODD[c] if i % 2 == 0 else _CF_EVEN[c] for i, c in enumerate(cf[:15]))
    return chr(ord("A") + total % 26) == cf[15]


def valid_partita_iva(piva: str) -> bool:
    if len(piva) != 11 or not piva.isdigit() or piva == "0" * 11:
        return False
    return luhn(piva)


def luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def valid_iban(iban: str) -> bool:
    iban = iban.replace(" ", "").upper()
    if not 15 <= len(iban) <= 34:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def valid_card(number: str) -> bool:
    digits = re.sub(r"[ -]", "", number)
    return 13 <= len(digits) <= 19 and luhn(digits)


def valid_ipv4(ip: str) -> bool:
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return not (addr.is_loopback or addr.is_unspecified)


# --- Pattern ----------------------------------------------------------------

_OMO = "[0-9LMNPQRSTUV]"  # cifre del CF sostituibili per omocodia
_NUM = r"\d{1,3}(?:[.,]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d+)?"
_MULT = r"(?:\s?(?:k|K|M|mln|mila|milion[ei](?:\s+di)?|miliard[io](?:\s+di)?))?"
_CUR = r"(?:€|euro|EUR)"
_PWD_KEY = r"(?:password|passwd|pwd|passcode|passphrase|parola d'ordine)"
_PWD_VAL = r"[^\s,;\"']{3,}[^\s,;\"'.:)]"
_MESI = (r"(?:gen(?:naio)?|feb(?:braio)?|mar(?:zo)?|apr(?:ile)?|mag(?:gio)?|giu(?:gno)?"
         r"|lug(?:lio)?|ago(?:sto)?|set(?:tembre)?|ott(?:obre)?|nov(?:embre)?|dic(?:embre)?)\.?")
_DATA = (r"(?:\d{1,2}[/.\-]\d{1,2}[/.\-](?:\d{4}|\d{2})(?!\d)"
         rf"|\d{{1,2}}(?:°|º)?\s+{_MESI}\s+\d{{4}}"
         r"|\d{4}-\d{2}-\d{2})")


_SECRET_KEY = (r"(?:api[\s_-]?key|apikey|access[\s_-]?key|secret(?:[\s_-]?key)?"
               r"|client[\s_-]?secret|(?:access[\s_-]?|bearer\s+)?token|bearer"
               r"|chiave\s+(?:api|segreta|privata|di\s+accesso)|segreto)")
_SECRET_VAL = r"[^\s,;\"']{11,}[^\s,;\"'.:)]"


def looks_like_secret(value: str) -> bool:
    """Una chiave mescola lettere e cifre ed è lunga: "scaduto" o "aziendale" no."""
    return (len(value) >= 12 and any(c.isalpha() for c in value)
            and any(c.isdigit() for c in value))


def looks_like_password(value: str) -> bool:
    """Senza separatore esplicito: lettere mescolate a cifre o simboli, almeno 6 caratteri."""
    if len(value) < 6:
        return False
    has_alpha = any(c.isalpha() for c in value)
    has_digit = any(c.isdigit() for c in value)
    has_symbol = any(not c.isalnum() for c in value)
    return has_alpha and (has_digit or has_symbol)


class _Rule:
    def __init__(self, label: str, pattern: str, flags: int = 0,
                 validator: Callable[[str], bool] | None = None, group: int = 0):
        self.label = label
        self.regex = re.compile(pattern, flags)
        self.validator = validator
        self.group = group

    def finditer(self, text: str) -> Iterator[Entity]:
        for m in self.regex.finditer(text):
            value = m.group(self.group)
            if not value:
                continue
            if self.validator and not self.validator(value):
                continue
            yield Entity(
                start=m.start(self.group),
                end=m.end(self.group),
                label=self.label,
                text=value,
                source="regex-validata" if self.validator else "regex",
            )


RULES: list[_Rule] = [
    # Segreti tecnici: chiavi API note e assegnazioni di password.
    _Rule("SECRET", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    _Rule("SECRET", r"\bAKIA[0-9A-Z]{16}\b"),
    _Rule("SECRET", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    _Rule("SECRET", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    _Rule("SECRET", r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    _Rule("SECRET", r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    _Rule("SECRET", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # Chiavi senza un prefisso noto: le riconosce la parola che le annuncia ("API KEY
    # sdk-…", "la secret 3287…"), purché il valore abbia la forma di una chiave.
    _Rule("SECRET",
          rf"\b{_SECRET_KEY}\b\s*(?:[:=]|è|e'|é)?\s*({_SECRET_VAL})",
          re.IGNORECASE, validator=looks_like_secret, group=1),
    # Password scritte da una persona: con un separatore ("password: X") il valore si
    # prende sempre; senza ("con password X") solo se ha la forma di una password,
    # altrimenti "la password non è sicura" darebbe "non". Il punto finale è della frase.
    _Rule("PASSWORD",
          rf"\b{_PWD_KEY}\s*(?:[:=]|è|e'|é)\s*({_PWD_VAL})",
          re.IGNORECASE, group=1),
    _Rule("PASSWORD", rf"\b{_PWD_KEY}\s+({_PWD_VAL})",
          re.IGNORECASE, validator=looks_like_password, group=1),
    _Rule("PASSWORD", r"\bpin\b\s*(?:[:=]|è|e'|é)?\s*(\d{4,8})(?!\d)", re.IGNORECASE, group=1),
    # Data di nascita: una data qualunque resta in chiaro (serve all'AI), ma accanto a
    # "nato il" o "data di nascita" diventa un dato personale che identifica.
    _Rule("BIRTHDATE",
          rf"\b(?:nat[oaie]\b[^.\n]{{0,60}}?\b(?:il|in data|nel)|"
          rf"(?:data|luogo e data|data e luogo) di nascita\b[^.\n\d]{{0,30}}?|"
          rf"nascita\s*[:=]|d\.?o\.?b\.?\s*[:=]?|born(?:\s+on)?|date of birth\s*[:=]?)"
          rf"\s*({_DATA})",
          re.IGNORECASE, group=1),
    # Identificativi con checksum.
    _Rule("CF",
          rf"(?<![A-Za-z0-9])[A-Za-z]{{6}}{_OMO}{{2}}[ABCDEHLMPRSTabcdehlmprst]{_OMO}{{2}}"
          rf"[A-Za-z]{_OMO}{{3}}[A-Za-z](?![A-Za-z0-9])",
          validator=valid_codice_fiscale),
    _Rule("IBAN", r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b",
          validator=valid_iban),
    _Rule("CREDITCARDNUMBER", r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])",
          validator=valid_card),
    _Rule("PIVA", r"(?:(?<=\bIT)|(?<![\w]))\d{11}(?!\d)", validator=valid_partita_iva),
    # Contatti e rete.
    _Rule("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    _Rule("TELEPHONENUM",
          r"(?<![\w+])(?:\+39[ .-]?)?(?:3\d{2}[ .-]?\d{3}[ .-]?\d{3,4}|0\d{1,3}[ .-]?\d{3,4}[ .-]?\d{3,4})(?!\d)"),
    _Rule("IP", r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", validator=valid_ipv4),
    # Importi in euro: "2.000.000 euro", "2M€", "€ 150.000", "80 mila euro".
    _Rule("AMOUNT", rf"{_CUR}\s?(?:{_NUM}){_MULT}"),
    _Rule("AMOUNT", rf"(?<![\w.,])(?:{_NUM}){_MULT}\s?{_CUR}(?!\w)"),
]


def detect(text: str) -> list[Entity]:
    return [ent for rule in RULES for ent in rule.finditer(text)]
