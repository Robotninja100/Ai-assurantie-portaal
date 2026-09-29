"""
De twaalf functies van het portaal.

Ze verschillen STRUCTUREEL van elkaar, niet cosmetisch: een deterministische
rekenfunctie, een precedent-aggregatie over echte uitspraken, een documentanalyse,
een verschilanalyse, een procedurele navigator. Twaalf varianten van een chatvenster
zouden hier niet doorheen komen.

Vast patroon per functie:
  invoer -> corpus ophalen -> (eventueel) deterministisch rekenen ->
  contextblok -> model formuleert -> citeerbewaker controleert -> uitvoer met bronnen
"""
from typing import Dict, List, Optional
from datetime import date, datetime

from retrieval import Corpus
import rekenkern as rk
import grounding


CORPUS = Corpus()


# --------------------------------------------------------------- hulpfuncties

VERPLICHT = 999.0     # score voor artikelen waarop een berekening rust; altijd in de bronnen


def _uitkomst(d: Dict) -> str:
    """
    De uitkomst zoals Kifid die zelf formuleert ('Vordering afgewezen'). Nooit het veld 'oordeel':
    dat is een vertaling naar gegrond/ongegrond die nuance verliest (een klacht kan materieel
    gegrond zijn terwijl de vordering wordt afgewezen).
    """
    u = " ".join((d.get("uitkomst_letterlijk") or "").split()).lower().replace("vorderingen", "vordering")
    return u or "uitkomst niet vastgesteld"


def _splits_grondslag(g: str):
    """'BW:7:942:1' -> ('BW', '7:942', '1');  'BGfo:86c:1' -> ('BGfo', '86c', '1')."""
    d = g.split(":")
    if d[0] in ("BW", "Wft"):                   # artikelnummers bevatten zelf een dubbele punt
        return d[0], ":".join(d[1:3]), (d[3] if len(d) > 3 else None)
    return d[0], d[1], (d[2] if len(d) > 2 else None)


def _grondslag_docs(grondslag) -> List[Dict]:
    """
    De wetsartikelen waarop een berekening rust, rechtstreeks uit het corpus. Ze horen ALTIJD bij
    de bronnen: een uitkomst mag niet steunen op een artikel dat de adviseur niet kan inzien, en de
    citeerbewaker zou een terechte verwijzing ernaar anders als 'niet in corpus' aanmerken.
    """
    gezien, uit = set(), []
    for g in grondslag or []:
        wet, artikel, _lid = _splits_grondslag(g)
        if (wet, artikel) in gezien:
            continue
        gezien.add((wet, artikel))
        for d in CORPUS.data.get("wetgeving", []):
            if d.get("wet") == wet and str(d.get("artikel")).lower() == artikel.lower():
                uit.append(d)
                break
    return uit


def _blok(bron: str, rows: List) -> str:
    """Bouwt het contextblok dat het model als enige feitenbron krijgt."""
    if not rows:
        return ""
    uit = []
    for score, d in rows:
        if bron == "wetgeving":
            lim = 3000 if score >= VERPLICHT else 1200
            uit.append(f"[{d.get('wet')} art. {d.get('artikel')}] {d.get('titel') or ''}\n"
                       f"{(d.get('tekst') or '')[:lim]}\nBron: {d.get('bron_url')}")
        elif bron == "kifid":
            uit.append(f"[Kifid {d.get('uitspraaknummer')}] {d.get('titel') or ''}\n"
                       f"Uitkomst (letterlijk uit de uitspraak): {_uitkomst(d)}\n"
                       f"{(d.get('samenvatting') or d.get('kern_klacht') or '')[:900]}\n"
                       f"Bron: {d.get('bron_url')}")
        else:
            uit.append(f"[{d.get('product')} {d.get('clausule_id')} - {d.get('type')}] "
                       f"{d.get('kop') or ''}\n{(d.get('tekst') or '')[:900]}\n"
                       f"Bron: {d.get('bron_url')}")
    return "\n\n".join(uit)


# Welke polisproducten bij de gekozen productsoort horen. Een dekkingsvraag over een inboedel mag
# geen autoclausules opleveren, maar de algemene voorwaarden gelden voor elk schadeproduct.
ALGEMEEN = "algemene voorwaarden schadeverzekering"
PRODUCT_FAMILIE = {
    "inboedelverzekering": {"inboedelverzekering", "opstal-/inboedelverzekering (woonverzekering)"},
    "opstalverzekering": {"opstalverzekering", "opstal-/inboedelverzekering (woonverzekering)"},
    "opstal-/inboedelverzekering (woonverzekering)": {"inboedelverzekering", "opstalverzekering",
                                                       "opstal-/inboedelverzekering (woonverzekering)"},
}


def _product_filter(product: str):
    """Filter voor Corpus.zoek op de gekozen productsoort; None als er niets is gekozen of herkend."""
    p = " ".join((product or "").lower().split())
    if not p:
        return None
    kennen = {r.get("product") for r in CORPUS.data.get("polisvoorwaarden", [])}
    gelijk = next((k for k in kennen if k and k.lower() == p), None)
    if gelijk is None:
        gelijk = next((k for k in kennen if k and (p in k.lower() or k.lower() in p)), None)
    if gelijk is None:
        return None
    familie = PRODUCT_FAMILIE.get(gelijk, {gelijk}) | {ALGEMEEN}
    return lambda d: d.get("product") in familie


# Welk deel van de wetgeving bij welke vraag hoort. Een dekkingsvraag gaat over het verzekeringsrecht
# (BW boek 7), niet over de gedragsregels voor adviseurs (Wft, BGfo); andersom geldt hetzelfde. Zonder
# dit filter haalde een inbraakcasus artikelen over meldingsplichten aan de AFM op, alleen omdat
# 'melden' en 'klant' erin voorkomen.
def _wet(*wetten):
    return lambda d: d.get("wet") in wetten


VERZEKERINGSRECHT = _wet("BW")
GEDRAGSREGELS = _wet("Wft", "BGfo")


def _context(vraag: str, bronnen: List[str], per_bron=4, grondslag=(), waar=None) -> Dict:
    opgehaald, blokken = {}, []
    waar = waar or {}
    verplicht = _grondslag_docs(grondslag)
    if verplicht and "wetgeving" not in bronnen:
        bronnen = ["wetgeving"] + list(bronnen)
    for b in bronnen:
        rows = CORPUS.zoek(b, vraag, per_bron, waar.get(b))
        if b == "wetgeving" and verplicht:
            ids = {(d.get("wet"), d.get("artikel")) for d in verplicht}
            rows = ([(VERPLICHT, d) for d in verplicht] +
                    [(s, d) for s, d in rows if (d.get("wet"), d.get("artikel")) not in ids])
        opgehaald[b] = [d for _, d in rows]
        blk = _blok(b, rows)
        if blk:
            titel = {"wetgeving": "WETGEVING", "kifid": "KIFID-UITSPRAKEN",
                     "polisvoorwaarden": "POLISVOORWAARDEN"}[b]
            blokken.append(f"=== {titel} ===\n{blk}")
    return {"opgehaald": opgehaald, "blok": "\n\n".join(blokken) or "(geen bronnen gevonden)"}


def _bronlijst(opgehaald: Dict) -> List[Dict]:
    """Wat de UI toont als klikbare herkomst. Zonder dit is niets navolgbaar."""
    uit = []
    for b, docs in opgehaald.items():
        for d in docs:
            if b == "wetgeving":
                uit.append({"soort": "wetgeving", "label": f"{d.get('wet')} art. {d.get('artikel')}",
                            "titel": d.get("onderwerp") or d.get("titel"), "url": d.get("bron_url"),
                            "wet": d.get("wet"), "artikel": d.get("artikel"),
                            "geldig_op": d.get("geldig_op"),
                            "fragment": (d.get("tekst") or "")[:900]})
            elif b == "kifid":
                uit.append({"soort": "kifid", "label": f"Kifid {d.get('uitspraaknummer')}",
                            "titel": d.get("thema") or d.get("titel"), "uitkomst": _uitkomst(d),
                            "url": d.get("bron_url"), "verweerder": d.get("verweerder"),
                            "datum": d.get("datum"), "bindend": d.get("bindend"),
                            "fragment": (d.get("samenvatting") or d.get("kern_klacht") or "")[:900]})
            else:
                uit.append({"soort": "polis",
                            "label": f"{d.get('product')} {d.get('clausule_id')}",
                            "titel": d.get("kop"), "type": d.get("type"),
                            "product": d.get("product"), "clausule": d.get("clausule_id"),
                            "verzekeraar": d.get("verzekeraar_of_bron"), "document": d.get("document"),
                            "url": d.get("bron_url"), "fragment": (d.get("tekst") or "")[:900]})
    return uit


# =============================================================== 1. dekkingscheck

def dekkingscheck(situatie: str, product: str = "") -> Dict:
    vraag = f"{product} {situatie}".strip()
    ctx = _context(vraag, ["polisvoorwaarden", "wetgeving"], per_bron=5,
                   waar={"polisvoorwaarden": _product_filter(product), "wetgeving": VERZEKERINGSRECHT})
    gebruiker = (
        f"SCHADESITUATIE:\n{situatie}\n\nPRODUCT: {product or 'niet opgegeven'}\n\n"
        "Beoordeel op basis van UITSLUITEND de bronnen:\n"
        "1. Welke clausules raken deze situatie? Noem ze bij hun clausulenummer.\n"
        "2. Wijst dit op dekking of op een uitsluiting? Wees expliciet als het onduidelijk is.\n"
        "3. Welke feiten ontbreken om dit hard te maken?\n"
        "Als de bronnen geen uitsluitsel geven, zeg dat en benoem welke polisvoorwaarden "
        "de adviseur moet opvragen.")
    return {"functie": "dekkingscheck", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 550}


# =============================================================== 2. precedentzoeker

def precedentzoeker(geschil: str) -> Dict:
    """
    Aggregeert de WERKELIJK gepubliceerde oordelen van vergelijkbare zaken.
    De statistiek komt uit het corpus, niet uit het model - dat is het hele punt.
    """
    rows = CORPUS.zoek("kifid", geschil, 8)
    docs = [d for _, d in rows]
    telling = {}
    for d in docs:
        o = _uitkomst(d)
        telling[o] = telling.get(o, 0) + 1
    ctx = {"opgehaald": {"kifid": docs}, "blok": _blok("kifid", rows) or "(geen uitspraken gevonden)"}

    samenvatting = ", ".join(f"{v}x {k}" for k, v in sorted(telling.items(), key=lambda x: -x[1]))
    gebruiker = (
        f"GESCHIL:\n{geschil}\n\n"
        f"Gevonden vergelijkbare uitspraken: {len(docs)}. Verdeling van de uitkomsten (zoals Kifid ze zelf formuleert): "
        f"{samenvatting or 'geen'}.\n\n"
        "Analyseer op basis van UITSLUITEND deze uitspraken:\n"
        "1. Welke lijn tekent zich af? Verwijs naar uitspraaknummers.\n"
        "2. Welk feit gaf in deze zaken de doorslag?\n"
        "3. Waar zit het verschil met de voorgelegde casus?\n"
        "Tel zelf NIETS; de verdeling hierboven is al berekend. Trek geen conclusie die "
        "breder is dan deze uitspraken dragen.")
    return {"functie": "precedentzoeker", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]),
            "berekening": {"onderwerp": "Verdeling gepubliceerde uitkomsten",
                           "telling": telling, "aantal_uitspraken": len(docs),
                           "let_op": "Dit is de verdeling binnen de gevonden uitspraken, "
                                     "geen representatieve steekproef van alle Kifid-zaken."},
            "max_tokens": 550}


# =============================================================== 3. schadeberekening

def schadeberekening(verzekerde_som: float, werkelijke_waarde: float, schade: float,
                     eigen_risico: float = 0, bereddingskosten: float = 0) -> Dict:
    u = rk.evenredigheidsbeginsel(verzekerde_som, werkelijke_waarde, schade,
                                  eigen_risico, bereddingskosten)
    ctx = _context("onderverzekering evenredigheid verzekerde som herbouwwaarde eigen risico",
                   ["wetgeving", "polisvoorwaarden"], per_bron=3, grondslag=u.grondslag,
                   waar={"wetgeving": VERZEKERINGSRECHT})
    stappen = "\n".join(f"- {s.omschrijving}: {s.formule}" for s in u.stappen)
    gebruiker = (
        f"De berekening is AL UITGEVOERD in deterministische code. Neem deze cijfers "
        f"letterlijk over, reken niets na en wijk er niet van af:\n\n"
        f"Uitkering: EUR {u.to_dict()['bedrag']}\n{stappen}\n"
        f"Waarschuwingen: {'; '.join(u.waarschuwingen) or 'geen'}\n\n"
        "Leg in helder Nederlands uit wat hier gebeurt en waarom, voor een adviseur die dit "
        "aan een klant moet uitleggen. Noem expliciet wat de klant zelf draagt en waarom.")
    return {"functie": "schadeberekening", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 400}


# =============================================================== 4. verjaringstoets

def _datum(waarde: str, veld: str) -> Optional[date]:
    """Leest een ISO-datum (JJJJ-MM-DD). Een onleesbare datum is een invoerfout, geen crash."""
    if not waarde:
        return None
    try:
        return datetime.strptime(waarde.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{veld}: '{waarde}' is geen datum in de vorm JJJJ-MM-DD")


def verjaringstoets(datum_bekend: str, datum_stuiting: str = "", datum_reactie: str = "",
                    aansprakelijkheid: bool = False, peildatum: str = "") -> Dict:
    if not datum_bekend:
        raise ValueError("datum_bekend: verplicht (JJJJ-MM-DD)")
    u = rk.verjaring_schadeclaim(_datum(datum_bekend, "datum_bekend"),
                                 _datum(datum_stuiting, "datum_stuiting"),
                                 _datum(datum_reactie, "datum_reactie"),
                                 bool(aansprakelijkheid),
                                 _datum(peildatum, "peildatum"))
    ctx = _context("verjaring rechtsvordering verzekeraar stuiting termijn afwijzing",
                   ["wetgeving", "kifid"], per_bron=3, grondslag=u.grondslag,
                   waar={"wetgeving": VERZEKERINGSRECHT})
    gebruiker = (
        f"De termijnberekening is AL UITGEVOERD. Neem letterlijk over:\n"
        f"{u.toelichting}\n"
        + "\n".join(f"- {s.omschrijving}: {s.formule}" for s in u.stappen) +
        "\n\nLeg uit wat dit betekent en wat de adviseur NU moet doen. Wees concreet over "
        "stuiting. Reken zelf niets na.")
    return {"functie": "verjaringstoets", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 400}


# =============================================================== 5. provisietoets

def provisietoets(producttype: str, jaarpremie: float = 0, provisiepercentage: float = 0,
                  directe_beloning: float = 0) -> Dict:
    u = rk.provisie_toets(producttype, jaarpremie, provisiepercentage, directe_beloning)
    ctx = _context(f"provisieverbod beloning {producttype} dienstverleningsdocument "
                   f"transparantie complex product", ["wetgeving", "kifid"], per_bron=4,
                   grondslag=u.grondslag, waar={"wetgeving": GEDRAGSREGELS})
    bedrag = u.to_dict()["bedrag"]
    gebruiker = (
        f"PRODUCT: {producttype}\n"
        f"Toets is AL UITGEVOERD: {u.toelichting}\n"
        f"Bedrag: {('EUR ' + bedrag) if bedrag else 'niet vast te stellen'}\n"
        f"Signalen: {'; '.join(u.waarschuwingen) or 'geen'}\n\n"
        "Onderbouw dit met de wetsartikelen uit de bronnen. Noem ALLEEN artikelen die er "
        "letterlijk in staan. Sluit af met wat de adviseur in het dossier moet vastleggen.")
    return {"functie": "provisietoets", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 450}


# =============================================================== 6. dossiercheck

def dossiercheck(dossiertekst: str) -> Dict:
    ctx = _context("passend advies klantprofiel zorgplicht informatieverstrekking "
                   "kennis ervaring doelstelling risicobereidheid financiele positie",
                   ["wetgeving", "kifid"], per_bron=5, waar={"wetgeving": GEDRAGSREGELS})
    gebruiker = (
        f"ADVIESDOSSIER:\n---\n{dossiertekst[:4000]}\n---\n\n"
        "Toets dit dossier tegen de zorgplicht- en adviesvereisten uit de bronnen.\n"
        "1. Welke verplichte elementen zijn AANWEZIG? Citeer waar je ze ziet.\n"
        "2. Welke ONTBREKEN? Dit is het belangrijkste deel.\n"
        "3. Welk concreet risico loopt de adviseur bij een klacht?\n"
        "Wees streng. Een ontbrekend element niet benoemen is erger dan te streng zijn.")
    return {"functie": "dossiercheck", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 650}


# =============================================================== 7. polisvergelijker

TYPE_VOLGORDE = ["dekking", "uitsluiting", "eigen risico", "verplichting verzekerde",
                 "schaderegeling", "verjaring"]


def _clausules_van(product: str, max_n: int = 10) -> List[Dict]:
    """
    Alle clausules van precies dit product, dekking en uitsluitingen eerst. Een vergelijking moet
    controleerbaar zijn: geen zoekscore die bepaalt wat er wel en niet naast elkaar komt te staan.
    """
    p = " ".join((product or "").lower().split())
    rijen = CORPUS.data.get("polisvoorwaarden", [])
    kennen = {r.get("product") for r in rijen}
    gelijk = next((k for k in kennen if k and k.lower() == p), None) or \
        next((k for k in kennen if k and p and (p in k.lower() or k.lower() in p)), None)
    if not gelijk:
        return []
    mijn = [r for r in rijen if r.get("product") == gelijk]
    mijn.sort(key=lambda r: (TYPE_VOLGORDE.index(r["type"]) if r.get("type") in TYPE_VOLGORDE else 99,
                             r.get("clausule_id") or ""))
    return mijn[:max_n]


def polisvergelijker(product_a: str, product_b: str) -> Dict:
    """Verschilanalyse over echte clausules; het model beschrijft, het corpus levert."""
    ra, rb = _clausules_van(product_a), _clausules_van(product_b)
    docs = ra + rb
    rijen = lambda lst: [(0.0, d) for d in lst]
    blok = (f"=== VARIANT A: {product_a} ===\n{_blok('polisvoorwaarden', rijen(ra)) or '(geen clausules in het corpus)'}\n\n"
            f"=== VARIANT B: {product_b} ===\n{_blok('polisvoorwaarden', rijen(rb)) or '(geen clausules in het corpus)'}")
    gebruiker = (
        f"Vergelijk '{product_a}' met '{product_b}' op basis van UITSLUITEND bovenstaande clausules.\n"
        "1. Waar verschillen de UITSLUITINGEN? Noem clausulenummers aan beide kanten.\n"
        "2. Welk concreet dekkingshiaat ontstaat er als een klant overstapt van A naar B?\n"
        "3. Welke vergelijking kun je NIET maken omdat de clausule aan een kant ontbreekt? "
        "Benoem dat expliciet in plaats van het gat te vullen.")
    bronnen = _bronlijst({"polisvoorwaarden": docs})
    for i, b in enumerate(bronnen):
        b["kant"] = "A" if i < len(ra) else "B"        # de UI toont beide varianten naast elkaar
    return {"functie": "polisvergelijker", "systeem": grounding.systeemprompt(blok),
            "gebruiker": gebruiker, "opgehaald": {"polisvoorwaarden": docs},
            "bronnen": bronnen, "berekening": None, "max_tokens": 600}


# =============================================================== 8. klachtroute

def klachtroute(situatie: str, datum_klacht: str = "", intern_afgehandeld: bool = False) -> Dict:
    ctx = _context("klachtprocedure Kifid ontvankelijkheid termijn bindend advies "
                   "geschilleninstantie interne klachtbehandeling",
                   ["wetgeving", "kifid"], per_bron=4)
    gebruiker = (
        f"SITUATIE:\n{situatie}\n"
        f"Datum klacht: {datum_klacht or 'niet opgegeven'}\n"
        f"Interne klachtprocedure doorlopen: {'ja' if intern_afgehandeld else 'nee'}\n\n"
        "Beschrijf op basis van de bronnen de route:\n"
        "1. Welke stap is nu aan de orde?\n"
        "2. Welke termijnen gelden en waar blijkt dat uit?\n"
        "3. Welke informatie moet mee bij indiening?\n"
        "Staat een termijn niet in de bronnen, zeg dat dan in plaats van een termijn te noemen.")
    return {"functie": "klachtroute", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 550}


# =============================================================== 9. afwijzingsanalyse

def afwijzingsanalyse(brieftekst: str) -> Dict:
    ctx = _context(brieftekst[:600] + " afwijzing dekking uitsluiting mededelingsplicht "
                   "opzet eigen gebrek", ["polisvoorwaarden", "kifid", "wetgeving"], per_bron=4,
                   waar={"wetgeving": VERZEKERINGSRECHT})
    gebruiker = (
        f"AFWIJZINGSBRIEF VAN DE VERZEKERAAR:\n---\n{brieftekst[:4000]}\n---\n\n"
        "Analyseer op basis van UITSLUITEND de bronnen:\n"
        "1. Op welke grond wijst de verzekeraar af? Citeer die grond uit de brief.\n"
        "2. Wordt die grond gedragen door een clausule of wetsartikel uit de bronnen? "
        "Zo nee, zeg dat - dat is het sterkste aanknopingspunt voor de adviseur.\n"
        "3. Welke tegenargumenten volgen uit de bronnen, met verwijzing?\n"
        "4. Welk bewijs moet de adviseur verzamelen?\n"
        "Overschat de zaak niet. Als de afwijzing terecht lijkt, zeg dat eerlijk.")
    return {"functie": "afwijzingsanalyse", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 700}


# =============================================================== 10. adviesnotitie

def adviesnotitie(klantsituatie: str, advies: str) -> Dict:
    ctx = _context("passend advies vastlegging dossier informatieverstrekking klantprofiel "
                   "motivering", ["wetgeving"], per_bron=5, waar={"wetgeving": GEDRAGSREGELS})
    gebruiker = (
        f"KLANTSITUATIE:\n{klantsituatie}\n\nGEGEVEN ADVIES:\n{advies}\n\n"
        "Stel een dossiernotitie op die voldoet aan de vastleggingsvereisten uit de bronnen.\n"
        "Gebruik deze kopjes: Klantsituatie / Doelstelling en risicobereidheid / Overwogen "
        "alternatieven / Advies en motivering / Verstrekte informatie / Vervolgafspraken.\n"
        "Vul NIETS in wat de adviseur niet heeft aangeleverd. Zet bij ontbrekende informatie "
        "letterlijk: '[AAN TE VULLEN DOOR ADVISEUR]'. Een notitie met verzonnen klantgegevens "
        "is erger dan een notitie met gaten.")
    return {"functie": "adviesnotitie", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 800}


# =============================================================== 11. waardetoets

def waardetoets(nieuwwaarde: float, ouderdom_jaren: float, levensduur_jaren: float,
                drempel_pct: float = 40) -> Dict:
    u = rk.nieuwwaarde_of_dagwaarde(nieuwwaarde, ouderdom_jaren, levensduur_jaren, drempel_pct)
    ctx = _context("nieuwwaarde dagwaarde afschrijving vervangingswaarde inboedel",
                   ["polisvoorwaarden", "wetgeving"], per_bron=3)
    gebruiker = (
        f"De waardebepaling is AL UITGEVOERD. Neem letterlijk over:\n"
        f"Uitkomst: EUR {u.to_dict()['bedrag']} - {u.toelichting}\n"
        + "\n".join(f"- {s.omschrijving}: {s.formule}" for s in u.stappen) +
        f"\nWaarschuwingen: {'; '.join(u.waarschuwingen)}\n\n"
        "Leg uit wat dit voor de klant betekent. Benadruk dat de drempel uit de "
        "polisvoorwaarden komt en per verzekeraar verschilt. Reken niets na.")
    return {"functie": "waardetoets", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 400}


# =============================================================== 12. begripsuitleg

def begripsuitleg(begrip: str) -> Dict:
    ctx = _context(begrip, ["wetgeving", "polisvoorwaarden", "kifid"], per_bron=3)
    gebruiker = (
        f"BEGRIP: {begrip}\n\n"
        "Leg dit begrip uit op basis van UITSLUITEND de bronnen.\n"
        "1. Wat zegt de wettekst of clausule letterlijk? Citeer.\n"
        "2. Wat betekent dat in de praktijk voor een adviseur?\n"
        "3. Waar gaat het in de praktijk mis?\n"
        "Komt het begrip niet in de bronnen voor, zeg dan dat het niet in de geraadpleegde "
        "bronnen staat en leg NIETS uit uit eigen kennis.")
    return {"functie": "begripsuitleg", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 500}


FUNCTIES = {
    "dekkingscheck":     {"fn": dekkingscheck,     "naam": "Dekkingscheck",        "groep": "Schade",
                          "omschrijving": "Toets een schadesituatie tegen de polisclausules."},
    "precedentzoeker":   {"fn": precedentzoeker,   "naam": "Kifid-precedent",      "groep": "Geschil",
                          "omschrijving": "Vind vergelijkbare uitspraken en hun werkelijke afloop."},
    "schadeberekening":  {"fn": schadeberekening,  "naam": "Schadeberekening",     "groep": "Schade",
                          "omschrijving": "Evenredigheid, eigen risico en bereddingskosten."},
    "verjaringstoets":   {"fn": verjaringstoets,   "naam": "Verjaringstoets",      "groep": "Geschil",
                          "omschrijving": "Loopt de termijn nog, en tot wanneer?"},
    "provisietoets":     {"fn": provisietoets,     "naam": "Provisietoets",        "groep": "Compliance",
                          "omschrijving": "Mag dit product op provisiebasis beloond worden?"},
    "dossiercheck":      {"fn": dossiercheck,      "naam": "Dossiercheck",         "groep": "Compliance",
                          "omschrijving": "Toets een adviesdossier op zorgplichtvereisten."},
    "polisvergelijker":  {"fn": polisvergelijker,  "naam": "Polisvergelijker",     "groep": "Advies",
                          "omschrijving": "Verschillen in uitsluitingen en dekkingshiaten."},
    "klachtroute":       {"fn": klachtroute,       "naam": "Klachtroute",          "groep": "Geschil",
                          "omschrijving": "Welke stap, welke termijn, wat moet mee."},
    "afwijzingsanalyse": {"fn": afwijzingsanalyse, "naam": "Afwijzingsanalyse",    "groep": "Schade",
                          "omschrijving": "Houdt de afwijzingsgrond van de verzekeraar stand?"},
    "adviesnotitie":     {"fn": adviesnotitie,     "naam": "Adviesnotitie",        "groep": "Advies",
                          "omschrijving": "Dossiernotitie met de verplichte elementen."},
    "waardetoets":       {"fn": waardetoets,       "naam": "Waardetoets",          "groep": "Schade",
                          "omschrijving": "Nieuwwaarde of dagwaarde, met de polisdrempel."},
    "begripsuitleg":     {"fn": begripsuitleg,     "naam": "Begripsuitleg",        "groep": "Advies",
                          "omschrijving": "Wat zegt de bron letterlijk over dit begrip?"},
}
