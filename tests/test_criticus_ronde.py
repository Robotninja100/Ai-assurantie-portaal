"""
Tests voor de criticusrunner: het dossier laat de beoordelaar zien wat het taalmodel echt kreeg.

In ronde 1 kreeg de beoordelaar een fragment van 2.000 tekens per bron, terwijl het model de tekst zag die het portaal
voor de prompt had ingekort. Drie 'ja'-oordelen bleken daardoor onjuist. Deze tests bewaken dat het dossier nu naar de
tekst verwijst die het model kreeg, en niet naar een fragment dat de runner zelf afkapt.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import criticus_ronde as cr   # noqa: E402
import features               # noqa: E402


def _casus(functie="klachtroute", **invoer):
    return {"id": f"{functie}-99", "functie": functie, "titel": "Testcasus", "invoer": invoer,
            "verwachting": {"moet": ["iets"], "mag_niet": ["iets anders"]}}


def test_model_zag_is_het_bronnenblok_uit_de_systeemprompt_en_de_opdracht():
    opdracht = features.begripsuitleg("evenredigheid bij onderverzekering")
    zag = cr.model_zag(opdracht)
    assert zag["gebruiker"] == opdracht["gebruiker"]
    assert opdracht["systeem"].endswith(zag["bronnenblok"] + "\n")
    assert "ABSOLUTE REGELS" not in zag["bronnenblok"]          # de regels horen er niet bij, alleen de bronnen
    assert len(zag["bronnenblok"]) > 200


def test_model_zag_is_leeg_zonder_bronnenmarkering():
    zag = cr.model_zag({"systeem": "geen bronnen hier", "gebruiker": "x"})
    assert zag["bronnenblok"] == "" and zag["gebruiker"] == "x"


def test_de_herberekende_laag_volledig_bewaart_wat_het_model_zag():
    casus = _casus("begripsuitleg", begrip="evenredigheid bij onderverzekering")
    zag = cr._model_zag_herberekend(casus)
    assert zag and zag["bronnenblok"]
    assert cr._model_zag_herberekend(_casus("schadeberekening", verzekerde_som="abc")) is None     # ongeldige invoer: niets te tonen


def test_het_dossier_verwijst_naar_het_bronnenbestand_en_bevat_de_tekst_die_het_model_kreeg():
    opdracht = features.begripsuitleg("evenredigheid bij onderverzekering")
    res = {"id": "begripsuitleg-99", "functie": "begripsuitleg", "http_status": 200,
           "bronnen_volledig": opdracht["bronnen"], "bronnen": cr.bronnen_kort(opdracht["bronnen"]),
           "tekst": "Antwoord.", "model": {"model": "stand-in"}, "model_zag": cr.model_zag(opdracht),
           "controle": {"oordeel": "GEFUNDEERD", "gefundeerd": [], "ongefundeerd": []}}
    casus = _casus("begripsuitleg", begrip="evenredigheid bij onderverzekering")
    tekst, bestanden = cr.dossier("begripsuitleg", [casus], {casus["id"]: res})
    assert "bronnen/begripsuitleg-99.md" in tekst
    assert list(bestanden) == ["begripsuitleg-99"]
    bestand = bestanden["begripsuitleg-99"]
    assert res["model_zag"]["bronnenblok"] in bestand and res["model_zag"]["gebruiker"] in bestand
    assert "precies wat het taalmodel" in bestand


def test_het_dossier_kapt_het_bronnenbestand_niet_af():
    lang = "x" * 9000
    res = {"id": "klachtroute-99", "functie": "klachtroute", "http_status": 200, "bronnen": [{"soort": "wetgeving", "label": "BW art. 1"}],
           "bronnen_volledig": [{"soort": "wetgeving", "label": "BW art. 1", "fragment": lang}],
           "tekst": "A", "model_zag": {"bronnenblok": lang, "gebruiker": "opdracht", "max_tokens": 600}}
    casus = _casus()
    tekst, bestanden = cr.dossier("klachtroute", [casus], {casus["id"]: res}, fragment=260)
    assert lang in bestanden["klachtroute-99"]                  # het bestand is volledig
    assert lang not in tekst and "[…]" in tekst                 # het dossier zelf blijft leesbaar


def test_een_geweigerde_invoer_of_zonder_bronnen_maakt_geen_bronnenbestand():
    casus = _casus()
    tekst, bestanden = cr.dossier("klachtroute", [casus], {casus["id"]: {"http_status": 400, "fout": "kapot"}})
    assert bestanden == {} and "HTTP 400" in tekst
    res = {"id": casus["id"], "functie": "klachtroute", "http_status": 200, "bronnen": [], "weigering": "Er zijn geen bronnen gevonden.",
           "tekst": ""}
    tekst, bestanden = cr.dossier("klachtroute", [casus], {casus["id"]: res})
    assert bestanden == {} and "geen bronnen opgehaald" in tekst


def test_de_reden_van_de_bewaker_staat_in_het_dossier():
    casus = _casus()
    res = {"id": casus["id"], "functie": "klachtroute", "http_status": 200, "bronnen": [{"soort": "wetgeving", "label": "BW art. 1"}],
           "tekst": "Zie art. 4:20 Wft.", "controle": {"oordeel": "ONGEFUNDEERD", "gefundeerd": [],
                                                       "ongefundeerd": [{"verwijzing": "Wft art. 4:20", "reden": "genoemd in een bron, niet opgehaald"}]}}
    tekst, _ = cr.dossier("klachtroute", [casus], {casus["id"]: res})
    assert "Wft art. 4:20: genoemd in een bron, niet opgehaald" in tekst


def test_standin_bewaart_wat_het_model_zag_ook_als_de_code_intussen_veranderde(tmp_path):
    opdracht = features.begripsuitleg("evenredigheid bij onderverzekering")
    opdrachten = tmp_path / "opdrachten"
    opdrachten.mkdir()
    antwoorden = tmp_path / "antwoorden"
    antwoorden.mkdir()
    import json
    (opdrachten / "begripsuitleg-99.json").write_text(json.dumps(opdracht), encoding="utf-8")
    (antwoorden / "begripsuitleg-99.txt").write_text("Dit is een testantwoord.", encoding="utf-8")
    res = cr.draai_standin(_casus("begripsuitleg", begrip="iets anders dat nu andere bronnen zou geven"), str(antwoorden))
    assert res["model_zag"]["bronnenblok"] == cr.model_zag(opdracht)["bronnenblok"]
