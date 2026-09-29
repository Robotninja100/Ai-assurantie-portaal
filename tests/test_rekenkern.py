"""
Tests voor de deterministische rekenkern. Elke verwachte waarde is met de hand afgeleid uit
de wettekst in corpus/wetgeving.json, niet uit de uitvoer van de code zelf.
"""
from datetime import date
from decimal import Decimal

import pytest

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


# ------------------------------------------------------------ classificatie van producten (BGfo 86c/86d)

def test_producten_uit_verschillende_regimes_door_elkaar_zijn_onbepaald():
    # Regressie: 'hypotheek + inboedelverzekering' werd als schadeverzekering geclassificeerd omdat de
    # tekst op 'verzekering' eindigde.
    u = rk.provisie_toets("hypotheek + inboedelverzekering", 1850, 12)
    assert u.details["status"] == "ONBEPAALD" and u.bedrag is None


def test_individuele_aov_is_verboden_en_de_kale_aov_onbepaald_ook_binnen_een_zin():
    assert status("individuele arbeidsongeschiktheidsverzekering voor een zzp'er") == "VERBODEN"
    assert status("arbeidsongeschiktheidsverzekering voor een zzp'er") == "ONBEPAALD"


def test_een_zakelijke_brandverzekering_valt_onder_86d():
    assert status("zakelijke brandverzekering") == "TOEGESTAAN_MET_TRANSPARANTIE"
    assert status("schadeverzekeringen") == "TOEGESTAAN_MET_TRANSPARANTIE"


def test_meervoud_van_een_verboden_product_wordt_herkend():
    assert status("hypotheken") == "VERBODEN"
    assert status("uitvaartverzekeringen") == "VERBODEN"


def test_individueel_bij_een_aov_maakt_er_de_verboden_individuele_aov_van():
    for tekst in ("AOV, individueel", "aov (individueel)", "individuele AOV", "arbeidsongeschiktheidsverzekering, individueel"):
        assert status(tekst) == "VERBODEN", tekst
    assert status("collectieve AOV") == "ONBEPAALD"
    assert status("AOV individueel of collectief") == "ONBEPAALD"      # niet vast te stellen welke van de twee


def test_provisie_zonder_premie_of_percentage_geeft_geen_nulbedrag():
    for premie, pct in ((0, 15), (600, 0), (0, 0)):
        u = rk.provisie_toets("opstalverzekering", premie, pct)
        assert u.details["status"] == "TOEGESTAAN_MET_TRANSPARANTIE"
        assert u.bedrag is None, (premie, pct)


# ------------------------------------------------------------ gevonden door de onafhankelijke casusschrijvers

def test_schade_boven_de_waarde_wordt_bij_onderverzekering_begrensd_op_de_verzekerde_som():
    # Regressie: 300.000 x 50% = 150.000 werd uitgekeerd bij een verzekerde som van 100.000 (art. 7:955 lid 1).
    u = rk.evenredigheidsbeginsel(100000, 200000, 300000)
    assert eur(u.bedrag) == Decimal("100000.00")
    assert any("hoger dan de werkelijke waarde" in w for w in u.waarschuwingen)
    assert "BW:7:955:1" in u.grondslag


def test_uitkering_is_nooit_hoger_dan_de_waarde_ook_bij_een_te_hoge_verzekerde_som():
    u = rk.evenredigheidsbeginsel(250000, 200000, 300000)
    assert eur(u.bedrag) == Decimal("200000.00")


def test_aanspraak_na_de_peildatum_heeft_nog_niets_gestuit():
    # Regressie: een voorgenomen brief (2 okt) gaf op 29 sep al 'gestuit', terwijl de termijn nog gewoon loopt.
    u = verjaring(date(2023, 10, 5), date(2026, 10, 2), peildatum=date(2026, 9, 29))
    assert u.details["status"] == "LOOPT"
    assert u.details["laatste_dag"] == "2026-10-05" and u.details["dagen_resterend"] == 6
    assert any("ligt na de peildatum" in w for w in u.waarschuwingen)


def test_reactie_na_de_peildatum_is_nog_niet_gebeurd():
    u = verjaring(date(2024, 1, 10), date(2024, 5, 1), date(2027, 1, 1), peildatum=date(2026, 9, 29))
    assert u.details["status"] == "GESTUIT"


def test_bekendheid_na_de_peildatum_is_een_invoerfout():
    with pytest.raises(ValueError):
        verjaring(date(2027, 1, 1), peildatum=date(2026, 9, 29))


def test_dagwaarde_precies_op_de_drempel_geeft_dagwaarde_want_de_clausule_zegt_meer_dan():
    # Klaverblad inboedel art. 2.17.3 sub c: nieuwwaarde alleen als de dagwaarde MEER DAN 40% bedraagt.
    u = rk.nieuwwaarde_of_dagwaarde(1000, 6, 10)
    assert u.details["toegepast"] == "dagwaarde" and eur(u.bedrag) == Decimal("400.00")
    assert any("precies op de drempel" in w for w in u.waarschuwingen)
    assert rk.nieuwwaarde_of_dagwaarde(1000, 5.9, 10).details["toegepast"] == "nieuwwaarde"


# ------------------------------------------------------------ de laatste dag: schrikkeljaren

@pytest.mark.parametrize("bekend,laatste", [
    (date(2024, 3, 10), date(2027, 3, 10)),
    (date(2025, 2, 28), date(2028, 2, 29)),     # S = 1 maart 2025, verstreken 1 maart 2028: 2028 heeft een 29 februari
    (date(2024, 2, 28), date(2027, 2, 28)),     # S = 29 februari 2024; die dag bestaat in 2027 niet
    (date(2024, 2, 29), date(2027, 2, 28)),
    (date(2020, 2, 29), date(2023, 2, 28)),
    (date(2023, 12, 31), date(2026, 12, 31)),
])
def test_laatste_dag_volgt_de_letterlijke_momentlezing(bekend, laatste):
    assert rk.laatste_dag_termijn(bekend) == laatste


# ------------------------------------------------------------ klachttermijnen (art. 43 BGfo)

def test_klachttermijnen_tonen_beide_lezingen_van_de_of_in_lid_3():
    u = rk.klachttermijnen(date(2026, 9, 1), date(2026, 9, 10), date(2026, 9, 29))
    d = u.details
    assert d["bevestiging_uiterlijk"] == "2026-09-15"                 # twee weken
    assert d["acht_weken_na_indienen"] == "2026-10-27"
    assert d["zes_weken_na_bevestiging"] == "2026-10-22"
    assert d["kan_naar_geschilleninstantie"] is False


def test_tussen_de_twee_lezingen_zegt_de_toets_dat_het_afhangt():
    u = rk.klachttermijnen(date(2026, 9, 1), date(2026, 9, 10), date(2026, 10, 24))
    assert u.details["afhankelijk_van_de_lezing"] is True and u.details["kan_naar_geschilleninstantie"] is False
    assert "hangt het af van de lezing" in u.toelichting


def test_na_beide_data_kan_het_zeker():
    assert rk.klachttermijnen(date(2026, 9, 1), date(2026, 9, 10), date(2026, 10, 27)).details["kan_naar_geschilleninstantie"] is True


def test_zonder_bevestigingsdatum_wordt_alleen_de_acht_wekenregel_berekend():
    u = rk.klachttermijnen(date(2026, 9, 1), None, date(2026, 9, 29))
    assert u.details["zes_weken_na_bevestiging"] is None and u.details["vroegste_datum_geschilleninstantie"] == "2026-10-27"


def test_laat_bevestigen_wordt_gesignaleerd():
    u = rk.klachttermijnen(date(2026, 9, 1), date(2026, 9, 20), date(2026, 9, 29))
    assert any("kwam na de termijn van twee weken" in w for w in u.waarschuwingen)
