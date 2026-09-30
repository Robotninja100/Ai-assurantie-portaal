"""
Het polisvoorwaardencorpus moet de vragen kunnen beantwoorden waarop de dekkingscheck eerder
strandde: inbraak, storm, water, diefstal uit een auto en fietsdiefstal. Zonder de juiste
clausules in het corpus weigert de dekkingscheck terecht (citeer-of-weiger), en dat is dan een
gat in het corpus, geen fout in het product.

Vier soorten tests:

1. Structuur en herkomst: elk record heeft de verplichte velden, een toegestaan type en een
   bekend product; het corpus is de uitkomst van de clausuletabel in scripts/ (zonder netwerk).
2. Bevriezing: de 69 clausules van voor de uitbreiding zijn ongewijzigd (vingerafdruk per
   record in tests/data/). Alleen opgehaald_op mag afwijken.
3. Dekking van de kernthema's in het corpus zelf (trefwoorden op de brontekst), los van de
   zoekmachine.
4. Retrieval: voor elke kernvraag levert Corpus.zoek('polisvoorwaarden', ...) in de top 5
   minstens een clausule van het juiste product met het juiste type.

Aannames bij de retrievaltests:
- De zoekvraag wordt opgebouwd zoals features.dekkingscheck dat doet: '<product> <situatie>'
  (een test bewijst dat de helper hetzelfde oplevert als de echte functie).
- Elke kernvraag staat in een korte vorm (zoals een adviseur de casus benoemt) en waar dat past
  in een volledige zin. De zoekmachine (BM25, geen stamvorm of synoniemen) haalt 'ingebroken'
  en 'gestolen' niet naar 'inbraak' en 'diefstal'; daarom is de volledige zin voor de
  inbraakcasus als bekende beperking apart vastgelegd (xfail), zodat de beperking zichtbaar
  blijft en niet stilzwijgend in een test verdwijnt.

De vingerafdruk van de 69 oorspronkelijke records is sha256 over
json.dumps(record zonder opgehaald_op, sort_keys=True, ensure_ascii=False,
separators=(',', ':')). Wijzig tests/data/polisvoorwaarden_basis_69.json alleen als bewust
besloten is dat een bestaand record mag veranderen.
"""
import hashlib
import importlib.util
import json
import os
import re

import pytest

import features
import retrieval

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLIS_PAD = os.path.join(ROOT, "corpus", "polisvoorwaarden.json")
BASIS_PAD = os.path.join(ROOT, "tests", "data", "polisvoorwaarden_basis_69.json")

AANTAL_OORSPRONKELIJK = 69

TOEGESTANE_TYPES = {"dekking", "uitsluiting", "eigen risico", "verplichting verzekerde",
                    "schaderegeling", "verjaring"}
VERPLICHTE_VELDEN = {"product", "verzekeraar_of_bron", "document", "clausule_id", "kop", "tekst",
                     "type", "bron_url", "opgehaald_op"}

INBOEDEL = "inboedelverzekering"
OPSTAL = "opstalverzekering"
WOON = "opstal-/inboedelverzekering (woonverzekering)"
AUTO = "autoverzekering (WA/casco)"
FIETS = "fietsverzekering"
REIS = "reisverzekering"
AVP = "aansprakelijkheidsverzekering particulieren (AVP)"
RECHTSBIJSTAND = "rechtsbijstandverzekering"
BEKENDE_PRODUCTEN = {INBOEDEL, OPSTAL, WOON, AUTO, FIETS, REIS, AVP, RECHTSBIJSTAND,
                     "algemene voorwaarden schadeverzekering", "arbeidsongeschiktheidsverzekering (AOV)"}


def _laad_polis():
    with open(POLIS_PAD, encoding="utf-8") as f:
        return json.load(f)


def _vingerafdruk(record):
    zonder = {k: v for k, v in record.items() if k != "opgehaald_op"}
    blob = json.dumps(zonder, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def corpus():
    return retrieval.Corpus()


def _top(corpus, product, situatie, n=5):
    """Dezelfde zoekvraag en hetzelfde productfilter als features.dekkingscheck."""
    vraag = f"{features._herken(product)['product'] or ''} {situatie}".strip()
    return [d for _, d in corpus.zoek("polisvoorwaarden", vraag, n, features._product_filter(product))]


# ------------------------------------------------------------ 1. structuur en herkomst

def test_elk_record_heeft_de_verplichte_velden_een_toegestaan_type_en_een_bekend_product():
    for r in _laad_polis():
        wie = f"{r.get('product')} {r.get('clausule_id')}"
        assert VERPLICHTE_VELDEN <= set(r), (wie, VERPLICHTE_VELDEN - set(r))
        assert r["type"] in TOEGESTANE_TYPES, wie
        assert r["product"] in BEKENDE_PRODUCTEN, wie
        for veld in ("clausule_id", "kop", "tekst", "verzekeraar_of_bron", "document"):
            assert isinstance(r[veld], str) and r[veld].strip(), (wie, veld)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["opgehaald_op"]), wie


def test_elk_record_wijst_naar_een_https_bron_met_status_200_en_pdf_hash():
    for r in _laad_polis():
        wie = f"{r['product']} {r['clausule_id']}"
        assert r["bron_url"].startswith("https://"), wie
        assert r.get("bron_http_status") == 200, wie
        assert re.fullmatch(r"[0-9a-f]{64}", r.get("bron_pdf_sha256", "")), wie


def test_clausule_id_is_uniek_per_brondocument():
    gezien = {}
    for i, r in enumerate(_laad_polis()):
        sleutel = (r["bron_url"], r["clausule_id"])
        assert sleutel not in gezien, f"{sleutel} staat op positie {gezien[sleutel]} en {i}"
        gezien[sleutel] = i


def test_teksten_zijn_schoon_en_bevatten_geen_paginameubilair():
    """Lijsten behouden hun regeleinden; verder geen tabs, lege regels, dubbele spaties of paginakoppen."""
    meubilair = re.compile(r"pag\d+/\d+|Privé Pakket Online|Aanvullende Voorwaarden versie|"
                           r"Voorwaarden Fietsverzekering\s+\d|^\s*\d+\s*/\s*\d+\s*$", re.M)
    for r in _laad_polis():
        wie = f"{r['product']} {r['clausule_id']}"
        assert "\t" not in r["tekst"] and "  " not in r["tekst"] and "\n\n" not in r["tekst"], wie
        assert all(regel == regel.strip() for regel in r["tekst"].split("\n")), wie
        assert not meubilair.search(r["tekst"]), wie


def _laad_scraper():
    pytest.importorskip("pypdf")
    pad = os.path.join(ROOT, "scripts", "scrape_polisvoorwaarden.py")
    spec = importlib.util.spec_from_file_location("scrape_polisvoorwaarden", pad)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corpus_is_de_uitkomst_van_de_clausuletabel_in_scripts():
    """Zonder netwerk: dezelfde clausules, in dezelfde volgorde, met kop, type en product uit de tabel."""
    scraper = _laad_scraper()
    records = _laad_polis()
    assert len(records) == len(scraper.CLAUSULES)
    for rij, r in zip(scraper.CLAUSULES, records):
        doc, cid, kop, soort = rij[:4]
        meta = scraper.DOCS[doc]
        assert (r["bron_url"], r["clausule_id"], r["kop"], r["type"], r["product"],
                r["verzekeraar_of_bron"], r["document"]) == \
               (meta["url"], cid, kop, soort, meta["product"], meta["verzekeraar"], meta["document"])
    assert {rij[0] for rij in scraper.CLAUSULES} == set(scraper.DOCS), "ongebruikt of ontbrekend brondocument"


# ------------------------------------------------------------ 2. bevriezing van de 69 oorspronkelijke records

def test_de_69_oorspronkelijke_records_zijn_ongewijzigd_en_staan_nog_vooraan():
    with open(BASIS_PAD, encoding="utf-8") as f:
        basis = json.load(f)["records"]
    records = _laad_polis()
    assert len(basis) == AANTAL_OORSPRONKELIJK
    assert len(records) >= AANTAL_OORSPRONKELIJK
    verschillen = []
    for i, b in enumerate(basis):
        r = records[i]
        if (r["bron_url"], r["clausule_id"], r["type"]) != (b["bron_url"], b["clausule_id"], b["type"]):
            verschillen.append(f"positie {i}: {r['clausule_id']!r} ({r['type']}) in plaats van "
                               f"{b['clausule_id']!r} ({b['type']})")
        elif _vingerafdruk(r) != b["sha256"]:
            verschillen.append(f"positie {i}: {b['clausule_id']!r} is inhoudelijk gewijzigd")
    assert not verschillen, "bestaande records mogen niet veranderen:\n  " + "\n  ".join(verschillen)


def test_de_uitbreiding_is_groot_genoeg_en_legt_de_nadruk_op_dekking():
    records = _laad_polis()
    nieuw = records[AANTAL_OORSPRONKELIJK:]
    assert len(nieuw) >= 30, f"{len(nieuw)} nieuwe clausules; de uitbreiding vroeg om minstens 30"
    dekking_nieuw = sum(1 for r in nieuw if r["type"] == "dekking")
    assert dekking_nieuw >= len(nieuw) // 2, "de uitbreiding moet vooral dekkingsclausules bevatten"
    assert sum(1 for r in records if r["type"] == "dekking") >= 30


# ------------------------------------------------------------ 3. dekking van de kernthema's in het corpus

WOONPRODUCTEN = (INBOEDEL, OPSTAL, WOON)

# (thema, producten of None voor alle, types, patroon op kop + tekst, minimaal aantal)
DEKKING = [
    ("inbraak in de inboedeldekking", (INBOEDEL,), ("dekking",), r"inbraak", 2),
    ("inbraak in de woon- en opstaldekking", WOONPRODUCTEN, ("dekking",), r"inbraak", 4),
    ("diefstal in de inboedeldekking", (INBOEDEL,), ("dekking",), r"diefstal", 3),
    ("storm in de inboedeldekking", (INBOEDEL,), ("dekking",), r"storm", 2),
    ("storm in de opstaldekking", (OPSTAL,), ("dekking",), r"storm", 1),
    ("water of leiding in de inboedeldekking", (INBOEDEL,), ("dekking",),
     r"leiding|lekkage|waterschade|water of stoom", 2),
    ("water of leiding in de opstaldekking", (OPSTAL,), ("dekking",), r"leiding|lekkage|waterschade", 1),
    ("bliksem in de woondekking", WOONPRODUCTEN, ("dekking",), r"bliksem", 3),
    ("bliksem in de autodekking", (AUTO,), ("dekking",), r"bliksem", 1),
    ("ontploffing in de woondekking", WOONPRODUCTEN, ("dekking",), r"ontploffing", 1),
    ("glas in de opstaldekking", (OPSTAL,), ("dekking",), r"glas|ruit", 1),
    ("ruitschade in de autodekking", (AUTO,), ("dekking",), r"ruit", 1),
    ("autodiefstal in de autodekking", (AUTO,), ("dekking",), r"diefstal", 2),
    ("diefstal uit een auto in de inboedel- en woondekking", (INBOEDEL, WOON), ("dekking",),
     r"(?=.*auto)(?=.*(diefstal|gestolen))", 2),
    ("fiets: dekking", (FIETS,), ("dekking",), r"fiets", 1),
    ("fiets: slotverplichting", (FIETS,), ("verplichting verzekerde",), r"slot", 1),
    ("fiets: uitsluiting van diefstal", (FIETS,), ("uitsluiting",), r"diefstal", 1),
    ("reis: bagage", (REIS,), ("dekking",), r"bagage", 1),
    ("reis: medische kosten", (REIS,), ("dekking",), r"medisch", 1),
    ("aansprakelijkheid (AVP)", (AVP,), ("dekking",), r"aansprakelijk", 1),
    ("rechtsbijstand", (RECHTSBIJSTAND,), ("dekking",), r"rechtshulp|rechtsbijstand", 1),
    ("maximumbedragen voor waardevolle zaken", (INBOEDEL,), ("dekking",),
     r"sieraden|maximale vergoeding", 2),
    ("beveiligings- en voorzorgseisen", None, ("uitsluiting", "verplichting verzekerde"),
     r"preventie|beveilig|slot|afgesloten|sleutel|zichtbaar", 5),
    ("schaderegeling bij diefstal", None, ("schaderegeling",), r"diefstal|gestolen", 1),
]


@pytest.mark.parametrize("thema,producten,types,patroon,minimum", DEKKING, ids=[d[0] for d in DEKKING])
def test_kernthema_komt_voor_in_het_corpus(thema, producten, types, patroon, minimum):
    treffers = [
        r for r in _laad_polis()
        if (producten is None or r["product"] in producten)
        and r["type"] in types
        and re.search(patroon, (r["kop"] + " " + r["tekst"]).lower(), re.S)
    ]
    assert len(treffers) >= minimum, (
        f"{thema}: {len(treffers)} clausule(s), minimaal {minimum} nodig "
        f"(producten={producten}, types={types}, patroon={patroon!r})")


# ------------------------------------------------------------ 4. retrieval: kernvragen in de top 5

# (id, gekozen product, situatie, acceptabele producten, verwacht type)
KERNVRAGEN = [
    ("inbraak-kort", INBOEDEL, "Inbraak in woning via openstaand raam", (INBOEDEL,), "dekking"),
    ("inbraak-zin", INBOEDEL,
     "Er is ingebroken in de woning via een openstaand raam. Laptop en sieraden zijn gestolen.",
     (INBOEDEL,), "dekking"),
    ("storm-kort", OPSTAL, "Stormschade aan dak", (OPSTAL,), "dekking"),
    ("storm-zin", OPSTAL,
     "Tijdens een storm zijn dakpannen van het dak gewaaid en er is water naar binnen gekomen.",
     (OPSTAL,), "dekking"),
    ("storm-inboedel", INBOEDEL, "Stormschade", (INBOEDEL,), "dekking"),
    ("water-kort", INBOEDEL, "Lekkage wasmachine", (INBOEDEL,), "dekking"),
    ("water-zin", INBOEDEL,
     "De aanvoerslang van de wasmachine is losgeschoten en er is water gelekt in de woning.",
     (INBOEDEL,), "dekking"),
    ("water-opstal", OPSTAL, "Lekkage waterleiding", (OPSTAL,), "dekking"),
    ("diefstal-uit-auto-kort", INBOEDEL, "Diefstal uit auto met zichtbare laptop", (INBOEDEL,), "dekking"),
    ("diefstal-uit-auto-zin", INBOEDEL,
     "Uit mijn afgesloten auto is een laptop gestolen die zichtbaar op de achterbank lag.",
     (INBOEDEL,), "dekking"),
    ("diefstal-uit-auto-autopolis", "autoverzekering", "Diefstal uit auto", (AUTO,), "dekking"),
    # Met een gekozen product blijft de zoekactie binnen dat product: wie een inboedelpolis kiest krijgt
    # de inboedelclausules over fietsen, niet die van een fietsverzekering die hij niet heeft.
    ("fietsdiefstal-kort", FIETS, "Fietsdiefstal", (FIETS,), "dekking"),
    ("fietsdiefstal-zin", FIETS,
     "Mijn fiets is gestolen van het station. De fiets stond op slot.", (FIETS,), "dekking"),
    ("fietsdiefstal-inboedel", INBOEDEL, "Fietsdiefstal", (INBOEDEL,), "dekking"),
    ("ruitschade-kort", "autoverzekering", "Ruitschade auto", (AUTO,), "dekking"),
    ("ruitschade-zin", "autoverzekering",
     "Er zit een steenslag in de voorruit van mijn auto en de ruit is gebarsten.", (AUTO,), "dekking"),
    ("bliksem-kort", "woonverzekering", "Bliksem", WOONPRODUCTEN, "dekking"),
    ("bliksem-zin", "woonverzekering",
     "Bliksem is ingeslagen en de televisie en router zijn kapot door overspanning.",
     WOONPRODUCTEN, "dekking"),
    ("reis-bagage-kort", "reisverzekering", "Reis: bagagediefstal", (REIS,), "dekking"),
    ("reis-bagage-zin", "reisverzekering",
     "Tijdens de vakantie is mijn koffer met camera en laptop gestolen uit de hotelkamer.",
     (REIS,), "dekking"),
    ("rechtsbijstand", "rechtsbijstandverzekering", "juridische hulp", (RECHTSBIJSTAND,), "dekking"),
]


@pytest.mark.parametrize("product,situatie,goede_producten,type_", [k[1:] for k in KERNVRAGEN],
                         ids=[k[0] for k in KERNVRAGEN])
def test_top5_bevat_een_clausule_van_het_juiste_product_en_type(
        corpus, product, situatie, goede_producten, type_):
    top = _top(corpus, product, situatie)
    assert len(top) == 5
    assert any(d["product"] in goede_producten and d["type"] == type_ for d in top), (
        f"geen {type_}-clausule van {goede_producten} in de top 5 voor {product!r} + {situatie!r}; "
        "gevonden: " + "; ".join(f"[{d['type']}] {d['product']} {d['clausule_id']}" for d in top))


def test_de_testhelper_bouwt_dezelfde_zoekvraag_als_de_dekkingscheck(corpus):
    """De dekkingscheck toont bij een gekozen product ALLE clausules ervan (tot het budget), de meest relevante eerst; zonder
    gekozen product de top 5. De top 5 van de testhelper is dus altijd de kop van wat de dekkingscheck toont."""
    for product, situatie in (("inboedelverzekering", "Fietsdiefstal"),
                              ("opstalverzekering", "Stormschade aan dak"),
                              ("", "Lekkage wasmachine")):
        echt = [b["label"] for b in features.dekkingscheck(situatie, product)["bronnen"] if b["soort"] == "polis"]
        eigen = [f"{d['product']} {d['clausule_id']}" for d in _top(corpus, product, situatie)]
        assert set(eigen) <= set(echt), (product, situatie)
        if not product:
            assert echt == eigen


def test_bij_een_gekozen_product_krijgt_het_model_alle_clausules_ervan_zolang_ze_passen():
    r = features.dekkingscheck("Storm heeft de dakgoot losgerukt", "opstalverzekering", "Klaverblad")
    polis = [b for b in r["bronnen"] if b["soort"] == "polis"]
    assert len(polis) == 17 and {b["verzekeraar"] for b in polis} == {"Klaverblad Verzekeringen"}
    assert not any("Het corpus heeft" in m for m in r["opmerkingen"])
    # een groter product past niet helemaal: het portaal zegt hoeveel er ontbreken
    r = features.dekkingscheck("Storm heeft de dakgoot losgerukt", "opstalverzekering", "Klaverblad")
    r = features.dekkingscheck("Schade aan de voorruit", "autoverzekering", "Klaverblad")
    polis = [b for b in r["bronnen"] if b["soort"] == "polis"]
    assert 8 <= len(polis) <= 16
    assert sum(len(b["fragment"]) for b in polis) > 5000


def test_dekkingscheck_toont_bij_de_inbraakcasus_polisbronnen_met_type_en_https_url():
    r = features.dekkingscheck("Inbraak in woning via openstaand raam", "inboedelverzekering")
    polis = [b for b in r["bronnen"] if b["soort"] == "polis"]
    assert polis and all(b["type"] in TOEGESTANE_TYPES and b["url"].startswith("https://") for b in polis)


def test_volle_zin_met_werkwoordsvormen_vindt_de_inbraakclausules_van_de_inboedelfamilie(corpus):
    """'ingebroken' en 'gestolen' zijn nu 'inbraak' en 'diefstal' (backend/retrieval.py); vroeger vond dit alleen de kortere vraag."""
    top = _top(corpus, INBOEDEL, "Er is ingebroken in de woning via een openstaand raam. Laptop en sieraden zijn gestolen.", 3)
    assert top[0]["product"] in (INBOEDEL, WOON) and "inbraak" in top[0]["tekst"].lower()
    assert any(d["product"] == INBOEDEL and d["type"] == "dekking" for d in top)
