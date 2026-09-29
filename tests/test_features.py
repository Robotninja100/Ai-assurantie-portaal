"""Tests voor de functies zelf: productbewuste retrieval, de vergelijker en de bronvelden voor de UI."""
import features


def polis(bronnen):
    return [b for b in bronnen if b["soort"] == "polis"]


def test_dekkingscheck_met_product_levert_geen_clausules_van_andere_producten():
    r = features.dekkingscheck("inbraak in woning, dief kwam binnen via een openstaand raam",
                               "inboedelverzekering")
    producten = {b["product"] for b in polis(r["bronnen"])}
    assert producten <= {"inboedelverzekering", "opstal-/inboedelverzekering (woonverzekering)",
                         "algemene voorwaarden schadeverzekering"}
    assert producten


def test_dekkingscheck_voor_auto_blijft_bij_auto():
    r = features.dekkingscheck("aanrijding met een ree, schade aan de bumper", "autoverzekering (WA/casco)")
    assert {b["product"] for b in polis(r["bronnen"])} <= {"autoverzekering (WA/casco)",
                                                            "algemene voorwaarden schadeverzekering"}


def test_polisvergelijker_zet_alleen_clausules_van_het_eigen_product_aan_elke_kant():
    r = features.polisvergelijker("inboedelverzekering", "autoverzekering (WA/casco)")
    a = {b["product"] for b in r["bronnen"] if b["kant"] == "A"}
    b_ = {b["product"] for b in r["bronnen"] if b["kant"] == "B"}
    assert a == {"inboedelverzekering"} and b_ == {"autoverzekering (WA/casco)"}


def test_polisvergelijker_met_onbekend_product_laat_die_kant_leeg_in_plaats_van_te_vullen():
    r = features.polisvergelijker("inboedelverzekering", "kunstverzekering")
    assert {b["kant"] for b in r["bronnen"]} == {"A"}
    assert "(geen clausules in het corpus)" in r["systeem"]


def test_elke_bron_heeft_de_velden_die_de_ui_nodig_heeft():
    r = features.dekkingscheck("inbraak", "inboedelverzekering")
    for b in r["bronnen"]:
        assert b["soort"] in {"wetgeving", "kifid", "polis"}
        assert b["label"] and b["url"].startswith("https://") and b["fragment"]


def test_precedentzoeker_telt_op_de_letterlijke_uitkomst_van_kifid():
    r = features.precedentzoeker("waterschade gesprongen leiding achterstallig onderhoud")
    assert r["berekening"]["telling"]
    for uitkomst in r["berekening"]["telling"]:
        assert uitkomst.startswith("vordering") or uitkomst == "uitkomst niet vastgesteld"
    assert all("oordeel" not in b for b in r["bronnen"])


def test_berekende_functies_nemen_hun_grondslagartikelen_mee_in_de_bronnen():
    r = features.verjaringstoets("2024-03-10", "", "", False, "2026-09-29")
    labels = [b["label"] for b in r["bronnen"]]
    assert "BW art. 7:942" in labels and "BW art. 7:943" in labels
    r = features.provisietoets("opstalverzekering", 600, 15)
    labels = [b["label"] for b in r["bronnen"]]
    assert "BGfo art. 86d" in labels and "BGfo art. 86i" in labels


import pytest


@pytest.mark.parametrize("aanroep", [
    lambda: features.provisietoets("opstalverzekering", -312, 18),
    lambda: features.provisietoets("opstalverzekering", 600, 140),
    lambda: features.provisietoets("opstalverzekering", 600, 10, -5),
    lambda: features.schadeberekening(-1, 100, 10),
    lambda: features.schadeberekening(100, 100, -10),
    lambda: features.schadeberekening(100, 100, 10, -5),
    lambda: features.waardetoets(2000, -1, 10),
    lambda: features.waardetoets(2000, 5, 10, 140),
    lambda: features.schadeberekening("abc", 100, 10),
])
def test_onzin_in_bedragen_wordt_geweigerd_in_plaats_van_doorgerekend(aanroep):
    with pytest.raises((ValueError, ArithmeticError)):
        aanroep()
