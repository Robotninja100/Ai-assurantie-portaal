"""
Regressietests voor de bevindingen van de onafhankelijke review van de citeerbewaker: valse alarmen,
gemiste gevallen en het markeren van elke plek. Elk geval hier is een echte fout die is gevonden.
"""
import pytest

import grounding

OPGEHAALD = {
    "wetgeving": [{"artikel": "7:942", "wet": "BW"}, {"artikel": "4:23", "wet": "Wft"}, {"artikel": "86c", "wet": "BGfo"},
                  {"artikel": "43", "wet": "BGfo"},
                  {"artikel": "7:958", "wet": "BW", "leden": ["1. a", "2. b", "3. c", "4. d", "5. e"]}],
    "kifid": [{"uitspraaknummer": "2026-0566"}],
    "polisvoorwaarden": [{"clausule_id": "art. 3.6.2"}, {"clausule_id": "Woonhuis art. 10 sub b"},
                         {"clausule_id": "art. 15"}],
}


def soorten(antwoord, toegestaan=None, opgehaald=OPGEHAALD, berekening=None):
    r = grounding.controleer(antwoord, opgehaald, toegestaan, berekening)
    return ({(x["soort"], x["verwijzing"]) for x in r["gefundeerd"]},
            {(x["soort"], x["verwijzing"]) for x in r["ongefundeerd"]}, r)


# ---------------------------------------------------------------- aanhalingstekens worden in volgorde gepaard

def test_een_korte_term_tussen_aanhalingstekens_maakt_de_tekst_erna_geen_citaat():
    antwoord = 'De term "complex product" staat in art. 86c, terwijl "hypotheek" een spreektaalterm is.'
    ok, slecht, _ = soorten(antwoord, "De term complex product staat in art. 86c terwijl hypotheek een spreektaalterm is.")
    assert not [x for x in ok | slecht if x[0] == "citaat"]


def test_een_citaat_over_twee_regels_van_dezelfde_alinea_wordt_getoetst():
    antwoord = 'Het dossier zegt: "De klant heeft een risicobereidheid\nvan laag opgegeven en wenst dekking" en dat is alles.'
    ok, slecht, _ = soorten(antwoord, "De klant heeft een risicobereidheid van laag opgegeven en wenst dekking voor inboedel.")
    assert [x[0] for x in ok] == ["citaat"] and not slecht


def test_een_apostrofjaartal_of_apostrofwoord_is_geen_opening_van_een_citaat():
    antwoord = "In de jaren '90 werd het 's ochtends ingevuld en 's avonds gecontroleerd door zo'n adviseur, die dat niet meer deed."
    ok, slecht, _ = soorten(antwoord, "irrelevant")
    assert not [x for x in ok | slecht if x[0] == "citaat"]


# ---------------------------------------------------------------- elke plek wordt gemarkeerd

def test_maskeer_markeert_elke_plek_waar_dezelfde_ongefundeerde_verwijzing_staat():
    antwoord = "Zie art. 7:960 voor de kosten. Later: art. 7:960 lid 2 zegt hetzelfde."
    r = grounding.controleer(antwoord, OPGEHAALD)
    assert len(r["ongefundeerd"]) == 1 and len(r["ongefundeerd"][0]["spans"]) == 2
    assert grounding.maskeer(antwoord, r).count("⚠️[niet in de opgehaalde bronnen]") == 2


def test_een_lid_met_komma_en_extra_spaties_wordt_toch_gevonden_en_gemarkeerd():
    antwoord = "Volgens art. 7:958,   lid 9 BW is dat zo. Zie ook art. 7:958 lid 8 BW."
    r = grounding.controleer(antwoord, OPGEHAALD)
    slecht = {x["verwijzing"] for x in r["ongefundeerd"]}
    assert slecht == {"7:958,   lid 9", "7:958 lid 8"}
    assert grounding.maskeer(antwoord, r).count("⚠️") == 2


def test_getal_en_citaat_krijgen_hun_eigen_markering():
    antwoord = 'De uitkering is € 99.999,00 en de brief zegt "de klant heeft alles zelf verzonnen en niets gemeld".'
    r = grounding.controleer(antwoord, {}, "Uitkering: EUR 43500.00", "{}")
    m = grounding.maskeer(antwoord, r)
    assert "€ 99.999,00 ⚠️[niet uit de berekening, de invoer of de bronnen]" in m
    assert 'gemeld" ⚠️[niet letterlijk in de invoer of de bronnen]' in m


# ---------------------------------------------------------------- valse alarmen

def test_jaartalbereiken_zijn_geen_kifid_nummers():
    ok, slecht, _ = soorten("In de periode 2023-2024 en in de jaren 2019-2021 veranderde er veel.")
    assert not [x for x in ok | slecht if x[0] == "kifid"]


def test_kifid_nummer_met_schuine_streep_wordt_herkend_en_genormaliseerd():
    ok, slecht, _ = soorten("Zie Kifid 2026/0566 en Kifid 2026/0881.")
    assert ("kifid", "2026/0566") in ok and ("kifid", "2026/0881") in slecht


def test_tijden_zijn_geen_wetsartikelen():
    ok, slecht, _ = soorten("Het loket sluit om 9:00 en de vergadering begint om 2:00 nadat 9:30 uur is verstreken.")
    assert not [x for x in ok | slecht if x[0] == "wetsartikel"]


# ---------------------------------------------------------------- gemiste gevallen

def test_een_ecli_is_alleen_goed_als_hij_in_de_invoer_of_de_bronnen_staat():
    antwoord = "Zie ECLI:NL:HR:2011:BQ1234 en ECLI:NL:HR:2019:999."
    ok, slecht, _ = soorten(antwoord, "In het dossier staat ECLI:NL:HR:2011:BQ1234 genoemd.")
    assert ("uitspraak", "ECLI:NL:HR:2011:BQ1234") in ok and ("uitspraak", "ECLI:NL:HR:2019:999") in slecht


def test_clausule_wordt_ook_als_woord_herkend():
    ok, slecht, _ = soorten("Zie clausule 3.6.2 en clausule 9.9.9.")
    assert ("polisclausule", "3.6.2") in ok and ("polisclausule", "9.9.9") in slecht


def test_clausules_zonder_punt_worden_herkend_en_getoetst():
    ok, slecht, _ = soorten("Zie art. 10 sub b, art. 10 sub c en artikel 15.")
    assert ("polisclausule", "art. 10 sub b") in ok
    assert ("polisclausule", "art. 10 sub c") in slecht
    assert ("polisclausule", "artikel 15") in ok


def test_art_10b_uit_een_polis_is_geen_verzonnen_wetsartikel():
    ok, slecht, _ = soorten("Zie art. 10b.")
    assert not slecht


def test_bgfo_met_de_wetnaam_voor_het_nummer_wordt_gevonden():
    ok, slecht, _ = soorten("Zie BGfo 86c en BGfo art. 86z.")
    assert ("wetsartikel", "86c") in ok and ("wetsartikel", "86z") in slecht


def test_artikel_uit_de_verkeerde_wet_wordt_gemarkeerd():
    ok, slecht, r = soorten("Zie art. 7:942 Wft en art. 4:23 Wft en BW 7:942 en art. 43 BGfo.")
    assert ("wetsartikel", "7:942 Wft") in slecht
    assert ("wetsartikel", "4:23") in ok and ("wetsartikel", "7:942") in ok and ("wetsartikel", "43") in ok
    assert next(x for x in r["ongefundeerd"] if x["verwijzing"] == "7:942 Wft")["reden"] == "art. 7:942 staat in de BW, niet in de Wft"


@pytest.mark.parametrize("tekst", ["Het percentage is 17.5% van de waarde.", "Het is 12,5 procent van de waarde."])
def test_percentages_met_decimale_punt_of_het_woord_procent_worden_getoetst(tekst):
    ok, slecht, _ = soorten(tekst, "Vergoeding 40% van de waarde", berekening="{}")
    assert [x[0] for x in slecht] == ["percentage"]
    ok, slecht, _ = soorten(tekst, "Vergoeding 17,5% en 12,5 procent van de waarde", berekening="{}")
    assert not slecht


# ---------------------------------------------------------------- getallen uit de opsomming tellen niet

def test_opsommingsnummers_uit_de_vraagstelling_gelden_niet_als_toegestane_getallen():
    prompt = "Beoordeel het volgende:\n1. Welke clausules raken dit?\n2. Wijst het op dekking?\n3. Wat ontbreekt?\n5. Vervolgstap"
    toegestaan = grounding.zonder_opsomming(prompt)
    ok, slecht, _ = soorten("Dat is 5% van de waarde en € 3 per maand.", toegestaan, berekening="{}")
    assert {x[0] for x in slecht} == {"percentage", "bedrag"}


def test_kleine_kale_getallen_in_de_bronnen_gelden_niet_maar_getallen_met_eenheid_en_kale_getallen_vanaf_100_wel():
    bron = "Het eigen risico is € 250. De vergoeding is 40% van de nieuwwaarde. De schade was 12500 en er waren 3 kamers."
    ok, slecht, _ = soorten("€ 250, 40%, € 12.500 maar ook € 3 en 3%.", bron, berekening="{}")
    assert {x[1] for x in slecht} == {"€ 3", "3%"}


def test_alles_uit_de_berekening_mag_ook_als_het_een_klein_getal_is():
    ok, slecht, _ = soorten("Het is 5% en € 8.", "geen getallen hier", berekening='{"a": "5", "b": "8.00"}')
    assert not slecht


def test_een_tweede_lid_van_een_artikel_van_een_alinea_wordt_gemarkeerd():
    # BW 7:944 is één alinea zonder ledennummers: lid 1 kan, lid 2 of hoger bestaat niet.
    import features
    o = features.verjaringstoets("2024-03-10", "", "", False, "2026-09-29")
    bw944 = [d for d in features.CORPUS.data["wetgeving"] if d.get("artikel") == "7:944"]
    assert bw944 and not bw944[0].get("leden")
    opgehaald = {"wetgeving": bw944}
    for lid, verwacht in (("1", "GEFUNDEERD"), ("2", "ONGEFUNDEERD"), ("99", "ONGEFUNDEERD")):
        c = grounding.controleer(f"Zie art. 7:944 lid {lid} BW.", opgehaald, "", "{}")
        assert c["oordeel"] == verwacht, (lid, c)
