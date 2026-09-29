"""
Tests voor de drie lagen die 'verzonnen feit' en 'niet-citeerbare bron' mechanisch uitsluiten:
retrieval (weigert onbevestigde bronnen), grounding (controleert verwijzingen) en de
integriteit van de corpusbestanden zelf.
"""
import json
import re

import pytest

import grounding
import retrieval


# ------------------------------------------------------------ retrieval

def _schrijf_corpus(map_, kifid, wet=None, polis=None):
    (map_ / "kifid.json").write_text(json.dumps(kifid), encoding="utf-8")
    (map_ / "wetgeving.json").write_text(json.dumps(wet or []), encoding="utf-8")
    (map_ / "polisvoorwaarden.json").write_text(json.dumps(polis or []), encoding="utf-8")


def test_retrieval_weigert_records_met_onbevestigde_bron(tmp_path, monkeypatch):
    _schrijf_corpus(tmp_path, [
        {"uitspraaknummer": "2026-0001", "titel": "waterschade dakgoot", "samenvatting": "waterschade",
         "bron_geverifieerd": True},
        {"uitspraaknummer": "2026-0002", "titel": "waterschade dakgoot", "samenvatting": "waterschade",
         "bron_geverifieerd": False},
    ])
    monkeypatch.setattr(retrieval, "CORPUS_DIR", str(tmp_path))
    c = retrieval.Corpus()
    gevonden = [d["uitspraaknummer"] for _, d in c.zoek("kifid", "waterschade dakgoot")]
    assert gevonden == ["2026-0001"]
    assert c.status["kifid"]["geweigerd_onbevestigde_bron"] == 1
    assert c.status["kifid"]["geweigerde_ids"] == ["2026-0002"]


def test_ontbrekend_corpusbestand_is_zichtbaar_en_niet_stil_leeg(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval, "CORPUS_DIR", str(tmp_path))
    c = retrieval.Corpus()
    assert c.status["kifid"]["geladen"] is False
    assert "fout" in c.status["kifid"]
    assert c.totaal() == 0


def test_echte_corpus_bevat_de_vijf_geweigerde_kifid_uitspraken():
    c = retrieval.Corpus()
    assert set(c.status["kifid"]["geweigerde_ids"]) >= {
        "2026-0832", "2026-0826", "2026-0822", "2026-0617", "2026-0221"}


def test_precisie_exacte_termen_vinden_hun_artikel():
    c = retrieval.Corpus()
    top = [d["artikel"] for _, d in c.zoek("wetgeving", "verjaring rechtsvordering verzekeraar", 3)]
    assert "7:942" in top


# ------------------------------------------------------------ grounding

OPGEHAALD = {
    "wetgeving": [{"artikel": "7:942"}, {"artikel": "86d"}],
    "kifid": [{"uitspraaknummer": "2026-0566"}],
    "polisvoorwaarden": [{"clausule_id": "art. 3.6.2"}],
}


def test_verwijzing_naar_opgehaald_document_is_gefundeerd():
    r = grounding.controleer("Zie art. 7:942 lid 2 BW en uitspraak 2026-0566.", OPGEHAALD)
    assert r["oordeel"] == "GEFUNDEERD"
    assert not r["ongefundeerd"]


def test_verwijzing_buiten_de_opgehaalde_documenten_is_ongefundeerd_ook_als_ze_bestaat():
    # 7:958 staat in het corpus maar is hier niet opgehaald: per definitie niet citeerbaar.
    r = grounding.controleer("Op grond van art. 7:958 lid 5 BW.", OPGEHAALD)
    assert r["oordeel"] == "ONGEFUNDEERD"
    assert [x["verwijzing"] for x in r["ongefundeerd"]] == ["7:958"]


def test_verzonnen_kifid_nummer_wordt_gemarkeerd():
    r = grounding.controleer("Zie uitspraak 2023-9999.", OPGEHAALD)
    assert r["oordeel"] == "ONGEFUNDEERD"


def test_maskeer_markeert_zichtbaar_en_verwijdert_niets():
    antwoord = "Dit volgt uit art. 7:958 lid 5 BW en art. 7:942 BW."
    r = grounding.controleer(antwoord, OPGEHAALD)
    m = grounding.maskeer(antwoord, r)
    assert "7:958 ⚠️[niet in de opgehaalde bronnen]" in m
    assert "7:942 ⚠️" not in m
    assert m.replace(" ⚠️[niet in de opgehaalde bronnen]", "") == antwoord


def test_antwoord_zonder_verwijzingen_krijgt_dat_oordeel():
    assert grounding.controleer("Neem contact op met de verzekeraar.", OPGEHAALD)["oordeel"] == "GEEN_VERWIJZINGEN"


# ------------------------------------------------------------ integriteit van het corpus

def _laad(naam):
    with open(f"corpus/{naam}.json", encoding="utf-8") as f:
        d = json.load(f)
    return d.get("records", d) if isinstance(d, dict) else d


def test_elk_bruikbaar_kifid_record_heeft_een_bevestigde_pdf_bron():
    for r in _laad("kifid"):
        if r.get("bron_geverifieerd") is False:
            continue
        assert re.fullmatch(r"20\d{2}-\d{3,5}", r["uitspraaknummer"]), r["uitspraaknummer"]
        assert r["bron_url"].startswith("https://www.kifid.nl/"), r["uitspraaknummer"]
        assert r["bron_url"].endswith(".pdf"), r["uitspraaknummer"]
        assert r.get("bron_geverifieerd") is True, r["uitspraaknummer"]


def test_elk_wetsartikel_wijst_naar_wetten_overheid_nl():
    for r in _laad("wetgeving"):
        assert r["bron_url"].startswith("https://wetten.overheid.nl/"), (r["wet"], r["artikel"])
        assert r["tekst"].strip()


def test_elke_polisclausule_heeft_een_hash_en_een_bron():
    for r in _laad("polisvoorwaarden"):
        if r.get("bron_geverifieerd") is False:
            continue
        assert re.fullmatch(r"[0-9a-f]{64}", r["bron_pdf_sha256"]), r["clausule_id"]
        assert r["bron_url"].startswith("https://"), r["clausule_id"]
        assert r["tekst"].strip()


def test_clausule_met_voorvoegsel_kan_gewoon_als_artikel_worden_geciteerd():
    # Regressie: 'Woonhuis art. 11.6' en 'art. 2.16 sub f' werden nooit herkend, waardoor een terechte
    # verwijzing als 'niet in corpus' werd gemarkeerd.
    opgehaald = {"polisvoorwaarden": [{"clausule_id": "Woonhuis art. 11.6"},
                                      {"clausule_id": "art. 2.16 sub f"},
                                      {"clausule_id": "par. 4.2"}]}
    r = grounding.controleer("Zie art. 11.6, artikel 2.16 en art. 4.2 van de voorwaarden.", opgehaald)
    assert r["oordeel"] == "GEFUNDEERD", r
    assert {x["verwijzing"] for x in r["gefundeerd"]} == {"11.6", "2.16", "4.2"}


def test_clausule_die_niet_is_opgehaald_blijft_ongefundeerd():
    opgehaald = {"polisvoorwaarden": [{"clausule_id": "Woonhuis art. 11.6"}]}
    r = grounding.controleer("Zie art. 11.7 van de voorwaarden.", opgehaald)
    assert r["oordeel"] == "ONGEFUNDEERD"


# ------------------------------------------------------------ getallen en data in het antwoord

TOEGESTAAN = (
    "Uitkering: EUR 43500.00\n- Evenredigheidsbreuk: 200000.00 / 250000.00 = 80.00\n"
    '{"bedrag": "43500.00", "details": {"laatste_dag": "2027-03-10", "onderverzekering_pct": "20.00"}}\n'
    "De laatste dag is 10 maart 2027. Polisclausule: het eigen risico is € 250 per gebeurtenis.")


GETALSOORTEN = {"bedrag", "percentage", "datum"}


def geefgetallen(antwoord, toegestaan=TOEGESTAAN):
    r = grounding.controleer(antwoord, {}, toegestaan)
    return ({x["verwijzing"] for x in r["gefundeerd"] if x["soort"] in GETALSOORTEN},
            {x["verwijzing"] for x in r["ongefundeerd"] if x["soort"] in GETALSOORTEN}, r)


def test_bedrag_uit_de_berekening_is_gefundeerd_in_elke_nederlandse_schrijfwijze():
    ok, slecht, r = geefgetallen("De uitkering is € 43.500,00, dus 43.500 euro, of EUR 43500.")
    assert not slecht, slecht
    assert ok


def test_verzonnen_of_verkeerd_overgenomen_bedrag_wordt_gemarkeerd():
    ok, slecht, r = geefgetallen("De uitkering is € 44.500,00.")
    assert slecht == {"€ 44.500,00"}
    assert r["oordeel"] == "ONGEFUNDEERD"
    assert r["ongefundeerd"][0]["soort"] == "bedrag"


def test_bedrag_uit_een_bron_mag_ook():
    ok, slecht, _ = geefgetallen("Het eigen risico is € 250.")
    assert not slecht


def test_percentage_dat_uit_de_berekening_volgt_mag_een_verzonnen_percentage_niet():
    ok, slecht, _ = geefgetallen("Je bent voor 80% verzekerd en 20% zelf verantwoordelijk, niet voor 35%.")
    assert slecht == {"35%"}


def test_datum_uit_de_berekening_in_elke_schrijfwijze_is_gefundeerd_een_andere_datum_niet():
    ok, slecht, _ = geefgetallen("Laatste dag: 10 maart 2027 (10-03-2027). Niet 11 maart 2027.")
    assert slecht == {"11 maart 2027"}


def test_artikelnummers_aantallen_en_jaartallen_zijn_geen_bedragen():
    ok, slecht, _ = geefgetallen("Volgens art. 7:942 lid 2 loopt er 3 jaar een termijn sinds 2024 in 2 stappen.")
    assert not slecht and not ok


def test_zonder_toegestane_tekst_worden_getallen_niet_gecontroleerd():
    r = grounding.controleer("Het bedrag is € 99.999,00.", {})
    assert r["oordeel"] == "GEEN_VERWIJZINGEN"


# ------------------------------------------------------------ artikelen zonder dubbele punt, leden, tijden

BGFO = {"wetgeving": [{"artikel": "86d", "leden": ["1. Een aanbieder...", "2. Voor de toepassing..."]},
                      {"artikel": "43", "leden": []},
                      {"artikel": "7:958", "leden": ["1. a", "2. b", "3. c", "4. d", "5. e"]}]}


def ongefundeerd(antwoord, opgehaald=BGFO):
    return {x["verwijzing"] for x in grounding.controleer(antwoord, opgehaald)["ongefundeerd"]}


def test_verzonnen_bgfo_artikel_met_letter_wordt_gevonden():
    # Regressie: 'art. 86z BGfo' werd nooit gemarkeerd omdat kale nummers stil werden overgeslagen.
    assert ongefundeerd("Zie art. 86z BGfo.") == {"86z"}
    assert ongefundeerd("Zie artikel 86d lid 1 BGfo.") == set()


def test_bgfo_artikel_zonder_letter_telt_alleen_met_de_wetnaam():
    assert ongefundeerd("Zie artikel 99 BGfo.") == {"99"}
    assert ongefundeerd("Zie artikel 43 BGfo.") == set()
    assert ongefundeerd("Zie artikel 5 van de polis.") == set()          # geen wetsverwijzing


def test_rangtelwoorden_en_tijden_geven_geen_vals_alarm():
    assert ongefundeerd("De 1e en 2e stap; om 14:30 uur en om 9:30 uur; gebouwd in 2a fasen.") == set()


def test_een_lid_dat_niet_bestaat_wordt_gemarkeerd_een_bestaand_lid_niet():
    assert ongefundeerd("Volgens art. 7:958 lid 9 BW geldt dit.") == {"7:958 lid 9"}
    assert ongefundeerd("Volgens art. 7:958 lid 5 BW geldt dit.") == set()
    assert ongefundeerd("Volgens art. 86d lid 3 BGfo geldt dit.") == {"86d lid 3"}


def test_artikel_zonder_bekende_leden_wordt_niet_op_lid_afgekeurd():
    assert ongefundeerd("Zie artikel 43 lid 2 BGfo.") == set()


# ------------------------------------------------------------ citaten: tussen aanhalingstekens staat letterlijke tekst

DOSSIER = ("Adviesdossier: De klant heeft een risicobereidheid van laag opgegeven en wenst dekking voor inboedel. "
           "Er is geen toelichting op het advies vastgelegd.")


def _citaten(antwoord, toegestaan=DOSSIER):
    c = grounding.controleer(antwoord, {}, toegestaan)
    return ([x for x in c["gefundeerd"] if x["soort"] == "citaat"], [x for x in c["ongefundeerd"] if x["soort"] == "citaat"], c)


def test_woordelijk_citaat_uit_de_invoer_is_gefundeerd():
    ok, slecht, _ = _citaten('Het dossier zegt: "De klant heeft een risicobereidheid van laag opgegeven" en dat klopt.')
    assert len(ok) == 1 and not slecht


def test_geparafraseerd_of_verzonnen_citaat_wordt_gemarkeerd():
    ok, slecht, c = _citaten('Het dossier zegt: "De klant heeft een hoge risicobereidheid opgegeven en wenst alles".')
    assert not ok and len(slecht) == 1
    assert c["oordeel"] == "ONGEFUNDEERD"


def test_citaat_mag_hoofdletters_leestekens_en_weglatingen_verschillen_maar_de_woorden_niet():
    ok, slecht, _ = _citaten('Zie “de klant heeft een RISICOBEREIDHEID van laag [...] wenst dekking voor inboedel”.')
    assert len(ok) == 1 and not slecht


def test_korte_aangehaalde_termen_en_apostrofs_geven_geen_vals_alarm():
    ok, slecht, _ = _citaten("Zo'n klant belt 's ochtends; het woord 'collectief' en \"laag\" staan er, zo'n dossier is 's avonds klaar.")
    assert not ok and not slecht


def test_citaat_telt_niet_als_verwijzing_voor_het_oordeel():
    _, _, c = _citaten('Het dossier zegt: "De klant heeft een risicobereidheid van laag opgegeven".')
    assert c["oordeel"] == "GEEN_VERWIJZINGEN"


def test_zonder_toegestane_tekst_worden_citaten_niet_gecontroleerd():
    c = grounding.controleer('Het dossier zegt: "De klant heeft een hoge risicobereidheid opgegeven en wenst alles".', {})
    assert not [x for x in c["ongefundeerd"] if x["soort"] == "citaat"]


def test_maskeer_zet_de_markering_direct_achter_het_ongecontroleerde_citaat_en_laat_de_rest_staan():
    antwoord = 'Volgens art. 7:999 staat er "De klant heeft een hoge risicobereidheid opgegeven en wenst alles" in het dossier.'
    c = grounding.controleer(antwoord, {}, DOSSIER)
    masked = grounding.maskeer(antwoord, c)
    assert 'wenst alles" ⚠️[niet letterlijk in de invoer of de bronnen] in het dossier' in masked
    assert "7:999 ⚠️[niet in de opgehaalde bronnen]" in masked
