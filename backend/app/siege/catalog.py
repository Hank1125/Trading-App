"""Operator/map catalog and name resolution (pure).

Canonical names come from Liquipedia's Portal:Operators and Portal:Maps pages (saved as fixtures).
Match pages spell names inconsistently ("Capitao" vs "Capitão", "Valk" vs "Valkyrie", "Furia" vs
"FURIA"), so lookups go through `name_key` (accent/case/punctuation-insensitive) plus a short,
explicit alias table. Anything still unknown is reported, never guessed.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

Side = Literal["attacker", "defender"]

# Liquipedia editor shorthands seen in match pages -> canonical name. Keep explicit and small.
OPERATOR_ALIASES: dict[str, str] = {
    "valk": "Valkyrie",
}

# Team names that are the same org written differently (beyond case/accents). Key -> canonical key.
TEAM_ALIASES: dict[str, str] = {
    "ninjasinpyjamas": "nip",
}

_TRANSLITERATE = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ß": "ss"})


def name_key(name: str) -> str:
    """'Capitão' -> 'capitao', 'Nøkk' -> 'nokk', 'FURIA' -> 'furia', 'Solid Snake' -> 'solidsnake'."""
    decomposed = unicodedata.normalize("NFKD", name.translate(_TRANSLITERATE))
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", ascii_only.casefold())


def team_key(name: str) -> str:
    """Identity key for a team: 'FURIA'/'Furia' -> 'furia', 'Ninjas In Pyjamas' -> 'nip'."""
    key = name_key(name)
    return TEAM_ALIASES.get(key, key)


@dataclass(frozen=True)
class CatalogOperator:
    name: str
    side: Side


@dataclass(frozen=True)
class Catalog:
    operators: tuple[CatalogOperator, ...]
    maps: tuple[str, ...]

    def __post_init__(self) -> None:
        for kind, names in (("operator", [o.name for o in self.operators]), ("map", list(self.maps))):
            keys = [name_key(n) for n in names]
            if len(set(keys)) != len(keys):
                raise ValueError(f"duplicate {kind} names after normalization")
        for alias, target in OPERATOR_ALIASES.items():
            if name_key(target) not in {name_key(o.name) for o in self.operators}:
                raise ValueError(f"alias {alias!r} points at unknown operator {target!r}")

    def resolve_operator(self, raw: str) -> CatalogOperator | None:
        key = name_key(raw)
        key = name_key(OPERATOR_ALIASES.get(key, raw))
        return next((o for o in self.operators if name_key(o.name) == key), None)

    def resolve_map(self, raw: str) -> str | None:
        key = name_key(raw)
        return next((m for m in self.maps if name_key(m) == key), None)


_GALLERY_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_SECTION_SIDES: dict[str, Side] = {"Attackers": "attacker", "Defenders": "defender"}


def parse_operator_portal(wikitext: str) -> tuple[CatalogOperator, ...]:
    """Operators from Portal:Operators gallery lines, under the Attackers/Defenders headers.

    The displayed link text is the name (`[[Warden (Operator)|Warden]]` -> Warden). Other sections
    (e.g. "Legacy", which holds the unbannable Recruits) are ignored.
    """
    parts = re.split(r">(Attackers|Defenders|Legacy)<", wikitext)
    ops: list[CatalogOperator] = []
    for header, body in zip(parts[1::2], parts[2::2], strict=True):
        side = _SECTION_SIDES.get(header)
        if side is None:
            continue
        for line in body.splitlines():
            if not line.startswith("File:") or "|link=" not in line:
                continue
            link = _GALLERY_LINK.search(line.split("|link=", 1)[1])
            if link:
                ops.append(CatalogOperator((link.group(2) or link.group(1)).strip(), side))
    if not ops:
        raise ValueError("no operators found in Portal:Operators wikitext")
    return tuple(ops)


def parse_map_portal(wikitext: str) -> tuple[str, ...]:
    """Map names from Portal:Maps gallery link targets (`link=Kafe Dostoyevsky/siege`)."""
    names = re.findall(r"\|link=([^|/\]]+)/siege\|", wikitext)
    if not names:
        raise ValueError("no maps found in Portal:Maps wikitext")
    return tuple(dict.fromkeys(n.strip() for n in names))
