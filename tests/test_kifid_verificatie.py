"""
Bewaking van de Kifid-bronverificatie voor twee uitspraken die op de wachtlijst stonden.

- 2026-0742: het nummer staat letterlijk in de kop van de PDF, dus geverifieerd.
- 2026-0832: de PDF is geen scan (er is een tekstlaag), maar drukt 'nr. 2026-832' zonder
  voorloopnul, terwijl register en record '2026-0832' gebruiken. De letterlijke eis is bewust
  niet versoepeld, dus het record blijft geweigerd. Deze tests zorgen dat dat een bewuste
  keuze blijft en niet stilzwijgend verandert, en dat de reden in het record klopt.

De tests draaien zonder netwerk. De PDF-koppen hieronder zijn de tekstlaag van de eerste
pagina van de publieke uitspraken, ingekort tot de kop.
"""
import importlib.util
import json
import os

import pytest

import retrieval

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Kop van de PDF van 2026-0832 (Anker Insurance Company N.V.): let op 'nr. 2026-832'.
KOP_0832 = (
    " \n1/4 \nUitspraak Geschillencommissie Kifid nr. 2026-832 \n"
    "(prof. mr. M.L. Hendrikse, voorzitter en mr. F.M.M.L. Fleskens, secretaris) \n"
    "Datum uitspraak 21 augustus 2026 \n"
    "Klacht van De vereniging ‘OVE oud bestuur’ te [plaatsnaam], vertegenwoordigd door de heer \n"
    "[naam], verder te noemen de vereniging  \n"
    "Tegen Anker Insurance Company N.V., gevestigd te Groningen, verder te noemen de \nverzekeraar \n"
    "Aard uitspraak Bindend advies \nUitkomst Vordering afgewezen \n"
    "Bijlage Relevante bepaling uit de verzekeringsvoorwaarden \n1. Procedure \n"
)

# Kop van de PDF van 2026-0742 (Van Roden Assurantien): hier staat het nummer wel met voorloopnul.
KOP_0742 = (
    " \n1/3 \nUitspraak Geschillencommissie Kifid nr. 2026-0742 \n"
    "(mr. M.L. Hendrikse, voorzitter en mr. R.A.F. Coenraad, secretaris) \n"
    "Datum uitspraak 30 juli 2026 \nKlacht van De consument \n"
    "Tegen Van Roden Assurantiën h.o.d.n. Ask4benefits Beesd BV, gevestigd te Deil, verder te \n"
    "noemen de adviseur \nAard uitspraak Bindend advies  \nUitkomst Vordering afgewezen  \n"
    "1. Procedure \n1.1 De behandelend commissie, verder te noemen de commissie, beslist op basis van het \n"
)


@pytest.fixture(scope="module")
def repareer():
    pad = os.path.join(ROOT, "scripts", "repareer_kifid_bronnen.py")
    spec = importlib.util.spec_from_file_location("repareer_kifid_bronnen", pad)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(nummer):
    with open(os.path.join(ROOT, "corpus", "kifid.json"), encoding="utf-8") as f:
        for r in json.load(f):
            if r["uitspraaknummer"] == nummer:
                return r
    raise AssertionError(f"{nummer} ontbreekt in corpus/kifid.json")


# ------------------------------------------------------------ de letterlijke eis zelf

def test_nummer_met_voorloopnul_in_de_pdf_wordt_letterlijk_teruggelezen(repareer):
    assert repareer.nummer_letterlijk_in_tekst("2026-0742", KOP_0742)
    assert repareer.nummer_gedrukt(KOP_0742) == "2026-0742"


def test_nummer_zonder_voorloopnul_in_de_pdf_haalt_de_letterlijke_eis_niet(repareer):
    # Dit is het geval 2026-0832. Als iemand de eis versoepelt (bijvoorbeeld door nummers als
    # getal te vergelijken), moet deze test bewust worden aangepast.
    assert repareer.nummer_gedrukt(KOP_0832) == "2026-832"
    assert not repareer.nummer_letterlijk_in_tekst("2026-0832", KOP_0832)


@pytest.mark.parametrize("fout_nummer", ["2026-0833", "2026-8320", "2025-0832", "2026-0083", ""])
def test_andere_nummers_haken_af_op_dezelfde_pdf(repareer, fout_nummer):
    assert not repareer.nummer_letterlijk_in_tekst(fout_nummer, KOP_0832)
    assert not repareer.nummer_letterlijk_in_tekst(fout_nummer, KOP_0742)


def test_diagnose_zegt_precies_wat_de_pdf_drukt_en_versoepelt_niet(repareer):
    tekst = repareer.diagnose_nummer("2026-0832", KOP_0832)
    assert "nr. 2026-832" in tekst
    assert "zonder voorloopnul" in tekst
    assert "niet geverifieerd" in tekst


def test_diagnose_onderscheidt_een_echt_ander_nummer_van_een_voorloopnul(repareer):
    tekst = repareer.diagnose_nummer("2026-0833", KOP_0832)
    assert "ander nummer" in tekst
    assert "voorloopnul" not in tekst


def test_diagnose_herkent_een_pdf_zonder_tekstlaag(repareer):
    tekst = repareer.diagnose_nummer("2026-0832", " \n1/4 \n")
    assert "geen tekstlaag" in tekst
    assert "gescand" in tekst


def test_alleen_met_onbekend_nummer_stopt_zonder_iets_te_schrijven(repareer, capsys):
    pad = os.path.join(ROOT, "corpus", "kifid.json")
    voor = open(pad, "rb").read()
    assert repareer.main(["--alleen", "1999-0001"]) == 2
    assert "onbekend uitspraaknummer" in capsys.readouterr().err
    assert open(pad, "rb").read() == voor


# ------------------------------------------------------------ de records in het corpus

def test_0742_is_geverifieerd_op_de_pdf_bron():
    r = _record("2026-0742")
    assert r["bron_geverifieerd"] is True
    assert r["bron_url"] == r["pdf_url"]
    assert r["bron_url"].endswith("uitspraak-2026-0742-bindend.pdf")
    assert "letterlijk teruggelezen" in r["bron_verificatie_notitie"]


def test_0832_blijft_geweigerd_en_de_reden_klopt_met_de_pdf():
    r = _record("2026-0832")
    assert r["bron_geverifieerd"] is False
    assert "2026-832" in r["bron_verificatie_notitie"]
    assert "voorloopnul" in r["bron_verificatie_notitie"]
    assert "gescand" not in r["bron_verificatie_notitie"]   # het is geen scan
    assert "audit_bevinding" not in r                       # geen fabricatie gevonden: alleen het nummer wijkt af


def test_retrieval_weigert_0832_en_levert_0742():
    c = retrieval.Corpus()
    assert "2026-0832" in c.status["kifid"]["geweigerde_ids"]
    assert "2026-0742" not in c.status["kifid"]["geweigerde_ids"]
    top = [d["uitspraaknummer"] for _, d in c.zoek("kifid", "lijfrente revisierente adviseur begeleiding", 3)]
    assert "2026-0742" in top
    # ook bij een zoekvraag die precies over 0832 gaat mag het geweigerde record niet terugkomen
    alle = [d["uitspraaknummer"] for _, d in
            c.zoek("kifid", "annuleringsverzekering groepsreis faillissement reisbureau uitvallen accommodatie", 10)]
    assert "2026-0832" not in alle
