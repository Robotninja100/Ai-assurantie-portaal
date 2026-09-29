"""
Rommelige invoer: spreektaal, werkwoordsvormen, typefouten, aan elkaar geschreven woorden, accenten.
Elke vraag moet een bron opleveren waarin het verwachte begrip echt staat; de verwachting wordt getoetst op
de tekst van de gevonden bronnen en niet op een vast clausulenummer, zodat een uitgebreider corpus de test niet breekt.
"""
import pytest

import retrieval


@pytest.fixture(scope="module")
def corpus():
    return retrieval.Corpus()


def tekst(d):
    """Alle tekstvelden van een bron (kop, tekst, samenvatting, uitkomst...), zonder verwijzingen naar bestanden."""
    return " ".join(v for k, v in d.items() if isinstance(v, str) and not k.startswith("bron_")).lower()


# (vraag, bron, begrippen waarvan er minstens één in de tekst van een van de eerste vijf resultaten moet staan)
GEVALLEN = [
    ("Er is ingebroken en mijn laptop is weg", "polisvoorwaarden", ("inbraak",)),
    ("de inbrekers hebben het slot geforceerd", "polisvoorwaarden", ("inbraak",)),
    ("mijn fiets is gestolen van het station", "polisvoorwaarden", ("fiets",)),
    ("dieven hebben de auto opengebroken", "polisvoorwaarden", ("diefstal",)),
    ("lekkge in de badkamer", "polisvoorwaarden", ("lekkage", "lek")),
    ("de wasmachine is gelekt en er staat water in huis", "polisvoorwaarden", ("lekkage", "water")),
    ("stormscade aan het dak", "polisvoorwaarden", ("storm",)),
    ("de storm heeft dakpannen losgerukt", "polisvoorwaarden", ("storm",)),
    ("steenslag in de voorruit", "polisvoorwaarden", ("ruit",)),
    ("ruitschade aan de auto", "polisvoorwaarden", ("ruit", "glas")),
    ("fietsdiefstal", "polisvoorwaarden", ("fiets",)),
    ("waterschade in de kelder", "polisvoorwaarden", ("water",)),
    ("brandschade in de keuken", "polisvoorwaarden", ("brand",)),
    ("een vandaal heeft de ruiten vernield", "polisvoorwaarden", ("vandalisme", "vernieling", "vernield")),
    ("de auto is aangereden op de parkeerplaats", "polisvoorwaarden", ("aanrijding", "botsing")),
    ("mijn huis is onderverzekerd", "wetgeving", ("onderverzekering", "evenredig")),
    ("de vordering is verjaard", "wetgeving", ("verjaring", "verjaart")),
    ("de verzekeraar heeft de claim afgewezen", "kifid", ("afgewezen", "afwijzing")),
    ("klagen bij het Kifid over de afhandeling", "wetgeving", ("klacht",)),
    ("geinformeerd over de provisie", "wetgeving", ("geïnformeerd", "informeert", "informatie")),
]


@pytest.mark.parametrize("vraag,bron,begrippen", GEVALLEN, ids=[g[0][:38] for g in GEVALLEN])
def test_rommelige_vraag_vindt_een_bron_met_het_juiste_begrip(corpus, vraag, bron, begrippen):
    top = [d for _, d in corpus.zoek(bron, vraag, 5)]
    assert top, "niets gevonden"
    assert any(b in tekst(d) for d in top for b in begrippen), (
        f"geen van de eerste vijf bronnen noemt {begrippen}: " + "; ".join(str(d.get('clausule_id') or d.get('artikel') or d.get('uitspraaknummer')) for d in top))


# ---------------------------------------------------------------- de bouwstenen

def test_werkwoordsvormen_en_spreektaal_worden_de_term_uit_het_corpus():
    assert retrieval.tokenize("Er is ingebroken en het is gestolen") == ["inbraak", "diefstal"]
    assert retrieval.tokenize("onderverzekerd") == ["onderverzekering"]


def test_samenstellingen_van_bekende_delen_worden_gesplitst_andere_niet():
    assert retrieval.tokenize("fietsdiefstal") == ["fietsdiefstal", "fiets", "diefstal"]
    assert retrieval.tokenize("waterschade") == ["waterschade", "water", "schade"]
    assert retrieval.tokenize("brandstof") == ["brandstof"]                    # 'stof' is geen bekend deel
    assert retrieval.tokenize("eigenrisico") == ["eigenrisico", "eigen", "risico"]


def test_accenten_doen_er_niet_toe():
    assert retrieval.tokenize("Univé geïnformeerd") == retrieval.tokenize("unive geinformeerd") == ["unive", "geinformeerd"]


def test_afstand_telt_een_verwisseling_als_een_fout():
    assert retrieval._afstand("lekkage", "lekkage", 2) == 0
    assert retrieval._afstand("lekkge", "lekkage", 2) == 1
    assert retrieval._afstand("lekakge", "lekkage", 2) == 1               # verwisseling
    assert retrieval._afstand("lekkage", "storm", 1) > 1


def test_alleen_onbekende_woorden_vanaf_vijf_tekens_worden_gecorrigeerd(corpus):
    ix = corpus.index["polisvoorwaarden"]
    assert ix._dichtstbij("lekkge") == "lekkage"
    assert ix._dichtstbij("stormscade") == "stormschade"
    assert ix._dichtstbij("zzzzzz") == "" and ix._dichtstbij("bakker") == ""
    assert ix._dichtstbij("wolk") == ""                                    # te kort
    assert ix._dichtstbij("4:23") == "" and ix._dichtstbij("art") == ""


def test_zoeken_is_deterministisch_ook_bij_een_andere_hashvolgorde():
    import os, subprocess, sys
    code = ("import sys; sys.path.insert(0, 'backend'); import retrieval as r; c = r.Corpus();"
            "print([d.get('clausule_id') for _, d in c.zoek('polisvoorwaarden', 'lekkge en stormscade bij de inboedel', 6)])")
    uitkomsten = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 env={**os.environ, "PYTHONHASHSEED": s}).stdout for s in ("0", "1", "2", "3")}
    assert len(uitkomsten) == 1 and "[" in next(iter(uitkomsten))


def test_een_geldig_woord_dat_alleen_in_deze_bron_ontbreekt_wordt_niet_gecorrigeerd(corpus):
    """'verjaring' staat in de wet en de polissen maar niet in het Kifid-register. Vroeger werd het daar 'verklaring':
    het portaal vond dan een uitspraak en weigerde niet. Een typefout is een woord dat nergens in het corpus staat."""
    kifid = corpus.index["kifid"]
    assert "verjaring" not in kifid.idf and "verjaring" in kifid.bekend
    assert kifid._dichtstbij("verjaring") == ""
    assert corpus.zoek("kifid", "verjaring stuiting 7:942", 5) == []


def test_precedentzoeker_weigert_bij_een_vraag_waar_het_kifid_register_niets_over_heeft():
    import features
    r = features.precedentzoeker("verjaring stuiting 7:942")
    assert r["bronnen"] == []


# ---------------------------------------------------------------- een herstelde spelling wordt altijd gemeld

def test_corpus_meldt_welke_woorden_als_typefout_zijn_gelezen(corpus):
    assert corpus.correcties("onderverzekring") == [("onderverzekring", "onderverzekering")]
    assert corpus.correcties("lekkge en stormscade") == [("lekkge", "lekkage"), ("stormscade", "stormschade")]
    assert corpus.correcties("eigen risico bij inbraak") == []                     # geen typefouten, geen melding
    assert corpus.correcties("verjaring stuiting") == []                           # geldig woord, alleen niet in elke bron


def test_functies_zetten_de_gelezen_spelling_in_de_opmerkingen():
    import features
    r = features.begripsuitleg("onderverzekring")
    assert r["opmerkingen"] == ["Zoekopdracht gelezen als: 'onderverzekring' → 'onderverzekering'. Klopt dat niet, pas dan de spelling aan."]
    assert r["bronnen"], "met de herstelde spelling zijn er bronnen"
    assert any("7:958" in b["label"] for b in r["bronnen"])
    assert features.begripsuitleg("onderverzekering")["opmerkingen"] == []
    for fn, kw in ((features.dekkingscheck, {"situatie": "lekkge in de badkamer"}), (features.precedentzoeker, {"geschil": "lekkge"}),
                   (features.klachtroute, {"situatie": "afwijzing onderverzekring"})):
        assert any("gelezen als" in m for m in fn(**kw)["opmerkingen"]), fn.__name__


def test_een_uitgang_is_geen_typefout():
    # 'definitieve' is 'definitie' met een uitgang; het portaal mag dat niet als spelfout herstellen en melden.
    from retrieval import Corpus
    c = Corpus()
    assert c.correcties("De verzekeraar stuurde een definitieve afwijzing.") == []
    assert ("onderverzekring", "onderverzekering") in c.correcties("onderverzekring bij de opstal")


def test_het_portaal_meldt_alleen_spelfouten_in_wat_de_adviseur_typte_niet_in_de_vaste_zoekwoorden():
    import features
    r = features.klachtroute("De klant is het niet eens met de afwijzing. De verzekeraar stuurde een definitieve afwijzing.",
                             "2026-09-01", False, "")
    assert not any("Zoekopdracht gelezen als" in m for m in r["opmerkingen"])
    r = features.klachtroute("De klant heeft een klacht ingedient bij de verzekeraar", "", False, "")
    assert any("'ingedient' → 'ingediend'" in m for m in r["opmerkingen"])
    for r in (features.schadeberekening(100000, 200000, 40000), features.verjaringstoets("2024-03-10"),
              features.waardetoets(1200, 4, 10), features.adviesnotitie("Alleenstaande.", "Inboedel.")):
        assert not any("Zoekopdracht gelezen als" in m for m in r.get("opmerkingen") or []), r["functie"]
