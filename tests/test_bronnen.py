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
    assert "7:958 ⚠️[niet in corpus]" in m
    assert "7:942 ⚠️" not in m
    assert m.replace(" ⚠️[niet in corpus]", "") == antwoord


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
