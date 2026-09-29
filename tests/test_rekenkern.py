"""
Tests voor de deterministische rekenkern. Elke verwachte waarde is met de hand afgeleid uit
de wettekst in corpus/wetgeving.json, niet uit de uitvoer van de code zelf.
"""
from datetime import date
from decimal import Decimal

import rekenkern as rk


def eur(x):
    return rk._eur(x)


# ------------------------------------------------------------ onderverzekering

def test_bereddingskosten_vallen_binnen_de_evenredigheidsbreuk():
    # Art. 7:959 lid 2 verklaart art. 7:958 lid 5 van overeenkomstige toepassing.
    # 50.000 x 200/250 = 40.000; - 500 eigen risico = 39.500; + 5.000 x 0,8 = 4.000 -> 43.500
    # (de foute versie uit ronde 0 gaf 44.500)
    u = rk.evenredigheidsbeginsel(200000, 250000, 50000, 500, 5000)
    assert eur(u.bedrag) == Decimal("43500.00")
    assert "BW:7:959:2" in u.grondslag


def test_volledig_verzekerd_geen_breuk():
    u = rk.evenredigheidsbeginsel(250000, 250000, 50000)
    assert eur(u.bedrag) == Decimal("50000.00")


def test_uitkering_is_gemaximeerd_op_de_verzekerde_som():
    u = rk.evenredigheidsbeginsel(100000, 100000, 150000)
    assert eur(u.bedrag) == Decimal("100000.00")
    assert any("verzekerde som" in w for w in u.waarschuwingen)


def test_eigen_risico_boven_uitkering_geeft_nihil():
    u = rk.evenredigheidsbeginsel(200000, 250000, 400, 500)
    assert eur(u.bedrag) == Decimal("0.00")


def test_waarde_nul_geeft_geen_bedrag_maar_een_vervolgstap():
    u = rk.evenredigheidsbeginsel(100000, 0, 5000)
    assert u.bedrag is None
    assert u.volgende_stap


# ------------------------------------------------------------ verjaring (art. 7:942 BW)

def verjaring(*a, **k):
    k.setdefault("peildatum", date(2026, 9, 29))
    return rk.verjaring_schadeclaim(*a, **k)


def test_laatste_dag_is_de_dag_met_hetzelfde_nummer_drie_jaar_later():
    # Termijn begint 11 maart 2024 00.00 uur; drie jaar later = 11 maart 2027 00.00 uur.
    u = verjaring(date(2024, 3, 10))
    assert u.details["laatste_dag"] == "2027-03-10"
    assert u.details["eerste_verjaarde_dag"] == "2027-03-11"


def test_op_de_laatste_dag_nog_niet_verjaard_een_dag_later_wel():
    # Regressie: een eerdere versie gaf de adviseur een dag te veel.
    assert verjaring(date(2024, 3, 10), peildatum=date(2027, 3, 10)).details["status"] == "LOOPT"
    assert verjaring(date(2024, 3, 10), peildatum=date(2027, 3, 10)).details["dagen_resterend"] == 0
    assert verjaring(date(2024, 3, 10), peildatum=date(2027, 3, 11)).details["status"] == "VERJAARD"


def test_schrikkeldag_valt_terug_op_de_laatste_dag_van_februari():
    assert verjaring(date(2024, 2, 29)).details["laatste_dag"] == "2027-02-28"


def test_stuiting_zonder_reactie_laat_geen_lopende_termijn_zien():
    # Art. 7:942 lid 2: een nieuwe termijn begint pas na erkenning of afwijzing.
    u = verjaring(date(2024, 1, 10), date(2024, 5, 1))
    assert u.details["status"] == "GESTUIT"
    assert u.details["laatste_dag"] is None
    assert "BW:7:942:2" in u.grondslag


def test_reactie_na_stuiting_start_een_nieuwe_termijn_die_de_oude_vervangt():
    u = verjaring(date(2021, 1, 10), date(2021, 6, 1), date(2022, 6, 1), peildatum=date(2025, 6, 1))
    assert u.details["laatste_dag"] == "2025-06-01"
    assert u.details["status"] == "LOOPT"
    u = verjaring(date(2021, 1, 10), date(2021, 6, 1), date(2022, 6, 1), peildatum=date(2025, 6, 2))
    assert u.details["status"] == "VERJAARD"


def test_aanspraak_na_afloop_van_de_hoofdtermijn_stuit_niets_meer():
    u = verjaring(date(2020, 1, 10), date(2024, 1, 1))
    assert u.details["status"] == "VERJAARD"
    assert u.details["laatste_dag"] == "2023-01-10"
    assert "BW:7:942:2" not in u.grondslag


def test_reactie_zonder_aanspraak_rekent_voorzichtig_en_meldt_het_alternatief():
    u = verjaring(date(2021, 1, 10), None, date(2022, 6, 1), peildatum=date(2024, 9, 29))
    assert u.details["status"] == "ONZEKER"
    assert u.details["voorwaardelijk_alternatief"]["laatste_dag"] == "2025-06-01"


def test_aansprakelijkheidsverzekering_stuit_door_onderhandeling_lid_3():
    u = verjaring(date(2024, 1, 10), date(2024, 5, 1), aansprakelijkheid=True)
    assert "BW:7:942:3" in u.grondslag
    assert u.details["status"] == "GESTUIT"


def test_reactie_voor_de_aanspraak_wordt_niet_meegeteld():
    u = verjaring(date(2024, 1, 10), date(2024, 5, 1), date(2024, 2, 1))
    assert u.details["status"] == "GESTUIT"
    assert any("Controleer de invoer" in w for w in u.waarschuwingen)


def test_peildatum_is_standaard_vandaag():
    u = rk.verjaring_schadeclaim(date(2024, 3, 10))
    assert u.details["peildatum"] == date.today().isoformat()


# ------------------------------------------------------------ provisie (BGfo 86c/86d)

def status(product, *a):
    return rk.provisie_toets(product, *a).details["status"]


def test_alleen_wat_art_86c_lid_1_noemt_is_verboden():
    for p in ("overlijdensrisicoverzekering", "uitvaartverzekering", "hypothecair krediet",
              "individuele arbeidsongeschiktheidsverzekering", "complex product",
              "betalingsbeschermer", "premiepensioenvordering"):
        assert status(p) == "VERBODEN", p


def test_spreektaal_wordt_naar_de_wettelijke_term_vertaald():
    assert status("Hypotheek") == "VERBODEN"
    assert status("ORV") == "VERBODEN"
    assert status("individuele AOV") == "VERBODEN"


def test_aov_zonder_individueel_of_collectief_is_onbepaald():
    # Art. 86c lid 1 noemt alleen de individuele AOV.
    u = rk.provisie_toets("arbeidsongeschiktheidsverzekering", 1000, 10)
    assert u.details["status"] == "ONBEPAALD"
    assert u.bedrag is None


def test_schadeverzekering_valt_onder_86d_en_niet_onder_het_verbod():
    u = rk.provisie_toets("opstalverzekering", 600, 15)
    assert u.details["status"] == "TOEGESTAAN_MET_TRANSPARANTIE"
    assert eur(u.bedrag) == Decimal("90.00")
    assert "BGfo:86d:1" in u.grondslag and "BGfo:86c:1" not in u.grondslag


def test_niet_herkend_product_wordt_niet_stilzwijgend_toegestaan():
    u = rk.provisie_toets("iets onbekends", 1000, 10)
    assert u.details["status"] == "ONBEPAALD"
    assert u.bedrag is None


def test_verboden_product_met_provisie_geeft_een_signaal_en_alleen_de_directe_beloning():
    u = rk.provisie_toets("uitvaartverzekering", 1200, 12, 950)
    assert eur(u.bedrag) == Decimal("950.00")
    assert any("compliance-signaal" in w for w in u.waarschuwingen)


# ------------------------------------------------------------ dagwaarde

def test_dagwaarde_onder_de_drempel_geeft_dagwaarde():
    u = rk.nieuwwaarde_of_dagwaarde(2000, 8, 10)     # 20% van de nieuwwaarde < 40%
    assert eur(u.bedrag) == Decimal("400.00")


def test_dagwaarde_boven_de_drempel_geeft_nieuwwaarde():
    u = rk.nieuwwaarde_of_dagwaarde(2000, 2, 10)     # 80% >= 40%
    assert eur(u.bedrag) == Decimal("2000.00")


# ------------------------------------------------------------ elke uitkomst heeft een vervolgstap

def test_elke_uitkomst_noemt_een_vervolgstap():
    uitkomsten = [
        rk.evenredigheidsbeginsel(200000, 250000, 50000),
        rk.verjaring_schadeclaim(date(2024, 1, 10), peildatum=date(2026, 9, 29)),
        rk.provisie_toets("opstalverzekering", 600, 15),
        rk.provisie_toets("hypotheek", 0, 0, 500),
        rk.provisie_toets("onbekend"),
        rk.nieuwwaarde_of_dagwaarde(2000, 2, 10),
    ]
    for u in uitkomsten:
        assert u.volgende_stap, u.onderwerp
