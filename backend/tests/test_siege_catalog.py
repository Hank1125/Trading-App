import pytest

from app.siege.catalog import Catalog, CatalogOperator, name_key, team_key
from app.siege.fixtures import load_catalog_fixture


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return load_catalog_fixture()


def test_portal_fixture_has_every_operator_by_side(catalog):
    sides = {o.name: o.side for o in catalog.operators}
    assert sum(s == "attacker" for s in sides.values()) == 39
    assert sum(s == "defender" for s in sides.values()) == 39
    # These two are wrapped differently on the portal and were missed by a first, naive parser.
    assert sides["Blackbeard"] == "attacker"
    assert sides["Warden"] == "defender"  # linked as "Warden (Operator)"
    assert not any("Recruit" in n for n in sides)  # "Legacy" section is not bannable


def test_portal_fixture_maps_use_full_names(catalog):
    assert len(catalog.maps) == 28
    assert "Kafe Dostoyevsky" in catalog.maps and "Kafe" not in catalog.maps


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("Valk", "Valkyrie"),
        ("Capitao", "Capitão"),
        ("Nokk", "Nøkk"),
        ("JAGER", "Jäger"),
        ("solid snake", "Solid Snake"),
    ],
)
def test_operator_spellings_resolve_to_one_operator(catalog, raw, canonical):
    found = catalog.resolve_operator(raw)
    assert found is not None and found.name == canonical


def test_unknown_names_are_not_guessed(catalog):
    assert catalog.resolve_operator("Valkyr") is None
    assert catalog.resolve_map("Kafe") is None


def test_team_keys_merge_case_and_known_aliases():
    assert team_key("FURIA") == team_key("Furia")
    assert team_key("FaZe Clan") == team_key("Faze Clan")
    assert team_key("Ninjas In Pyjamas") == team_key("NIP")
    assert team_key("G2 Esports") != team_key("G2")  # no fuzzy matching beyond the alias table


def test_name_key_strips_accents_case_and_punctuation():
    assert name_key("Capitão") == "capitao"
    assert name_key("Nøkk") == "nokk"
    assert name_key("Virtus.pro") == "virtuspro"


def test_catalog_rejects_names_that_collide_after_normalization():
    with pytest.raises(ValueError, match="duplicate operator"):
        Catalog((CatalogOperator("Capitão", "attacker"), CatalogOperator("Capitao", "attacker"),
                 CatalogOperator("Valkyrie", "defender")), ())  # fmt: skip


def test_catalog_rejects_alias_to_missing_operator():
    with pytest.raises(ValueError, match="alias"):
        Catalog((CatalogOperator("Ash", "attacker"),), ())
