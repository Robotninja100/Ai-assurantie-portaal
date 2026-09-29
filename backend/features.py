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
import re
import unicodedata
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import date, datetime

from retrieval import Corpus
import rekenkern as rk
import grounding


CORPUS = Corpus()
MAX_INVOER = 4000        # zoveel tekens van een dossier of brief gaan naar het model


# --------------------------------------------------------------- hulpfuncties

VERPLICHT = 999.0     # score voor artikelen waarop een berekening rust; altijd in de bronnen


def _uitkomstregel(label: str, u) -> str:
    """De uitkomst zoals het model haar leest. Zonder bedrag staat er nooit 'EUR None', maar de reden."""
    d = u.to_dict()
    if d["bedrag"] is None:
        reden = " ".join(u.waarschuwingen) or u.toelichting or "de invoer volstaat niet"
        return (f"{label}: NIET TE BEREKENEN. Reden: {reden} Noem geen bedrag; leg uit wat er ontbreekt "
                "en wat de volgende stap is.")
    return f"{label}: EUR {d['bedrag']}"


def _stappen_tekst(u) -> str:
    """De rekenstappen zoals het model ze leest, mét uitkomst per stap: het hoeft niets na te rekenen."""
    regels = []
    for s in u.stappen:
        uit = ""
        if s.uitkomst is not None:
            uit = f" = {rk._procent(s.uitkomst) if s.eenheid == '%' else rk._bedrag(s.uitkomst)}"
        regels.append(f"- {s.omschrijving}: {s.formule}{uit}")
    return "\n".join(regels)


def _zelf_te_dragen(u) -> str:
    """Wat de klant zelf draagt, uit de berekening; het model hoeft en mag dit niet zelf uitrekenen."""
    d = u.details or {}
    if "zelf_te_dragen" not in d:
        return ""
    delen = []
    if Decimal(d.get("zelf_te_dragen_door_onderverzekering", "0")) > 0:
        delen.append(f"door onderverzekering EUR {d['zelf_te_dragen_door_onderverzekering']}")
    if Decimal(d.get("zelf_te_dragen_boven_verzekerde_som", "0")) > 0:
        delen.append(f"boven de verzekerde som EUR {d['zelf_te_dragen_boven_verzekerde_som']}")
    if Decimal(d.get("zelf_te_dragen_eigen_risico", "0")) > 0:
        delen.append(f"eigen risico EUR {d['zelf_te_dragen_eigen_risico']}")
    return (f"Zelf te dragen door de klant: EUR {d['zelf_te_dragen']} van een totale schade van EUR "
            f"{d['totale_schade']}" + (f" ({'; '.join(delen)})" if delen else "") + ".\n")


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


# Hoeveel tekens van een bron het model krijgt. De adviseur ziet in de bronlijst de VOLLEDIGE tekst, dus
# altijd minstens wat het model zag; een afgekapt artikel verbergt leden (Wft 4:23 lid 7), daarom heeft een
# artikel waarop een berekening rust een ruimere grens. 96% van de polisclausules past in 1.500 tekens.
LIMIET_WET, LIMIET_WET_GRONDSLAG, LIMIET_POLIS, LIMIET_KIFID = 2600, 4000, 1500, 1200
LIMIET_ZICHTBAAR = 6000


def _stuk(tekst: str, lim: int) -> str:
    """Het begin van een tekst tot een woordgrens, met een teken dat er meer is."""
    t = tekst or ""
    if len(t) <= lim:
        return t
    return t[:lim].rsplit(" ", 1)[0].rstrip() + " …"


def _blok(bron: str, rows: List) -> str:
    """Bouwt het contextblok dat het model als enige feitenbron krijgt."""
    if not rows:
        return ""
    uit = []
    for score, d in rows:
        if bron == "wetgeving":
            lim = LIMIET_WET_GRONDSLAG if score >= VERPLICHT else LIMIET_WET
            uit.append(f"[{d.get('wet')} art. {d.get('artikel')}] {d.get('titel') or ''}\n"
                       f"{_stuk(d.get('tekst'), lim)}\nBron: {d.get('bron_url')}")
        elif bron == "kifid":
            uit.append(f"[Kifid {d.get('uitspraaknummer')}] {d.get('titel') or ''}\n"
                       f"Uitkomst (letterlijk uit de uitspraak): {_uitkomst(d)}\n"
                       f"{_stuk(d.get('samenvatting') or d.get('kern_klacht'), LIMIET_KIFID)}\n"
                       f"Bron: {d.get('bron_url')}")
        else:
            uit.append(f"[{d.get('product')} {d.get('clausule_id')} - {d.get('type')}] "
                       f"{d.get('kop') or ''}\n{_stuk(d.get('tekst'), LIMIET_POLIS)}\n"
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


def _sleutel(tekst: str) -> str:
    """Kleine letters zonder accenten en leestekens; 'a.s.r.' en 'ASR' worden 'asr', 'Univé' wordt 'unive'."""
    t = unicodedata.normalize("NFKD", (tekst or "").lower().replace(".", ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _als_woord(sleutel: str, tekst: str) -> bool:
    return bool(sleutel) and re.search(rf"(?<![a-z0-9]){re.escape(sleutel)}(?![a-z0-9])", tekst) is not None


def _kort(verzekeraar: str) -> str:
    """'Klaverblad Verzekeringen' -> 'Klaverblad'; 'Univé (N.V. Univé Schade)' -> 'Univé'."""
    return re.sub(r"\s*\(.*\)\s*$", "", verzekeraar or "").replace(" Verzekeringen", "").strip()


def _verzekeraars() -> Dict[str, str]:
    """Wie polisvoorwaarden in het corpus heeft: sleutel ('klaverblad') -> volledige naam."""
    uit = {}
    for r in CORPUS.data.get("polisvoorwaarden", []):
        naam = r.get("verzekeraar_of_bron") or ""
        if _kort(naam):
            uit[_sleutel(_kort(naam))] = naam
    return uit


# Bekende verzekeraars waarvan het corpus GEEN voorwaarden heeft. Wie er een noemt, krijgt geen
# clausules van een andere verzekeraar voorgeschoteld onder die naam.
ANDERE_VERZEKERAARS = (
    "centraal beheer", "nationale nederlanden", "nationale-nederlanden", "aegon", "allianz", "fbto", "ohra",
    "delta lloyd", "reaal", "anwb", "de goudse", "goudse", "generali", "avero", "ditzo", "amersfoortse",
    "movir", "de friesland", "zurich", "unigarant", "vivat", "aviva", "hdi", "verzekeruzelf",
    "abn amro", "rabobank", "lloyd s", "lloyds",
)


def _noemt_andere_verzekeraar(sleutel_tekst: str) -> Optional[str]:
    return next((a for a in ANDERE_VERZEKERAARS if _als_woord(_sleutel(a), sleutel_tekst)), None)


def _herken(tekst: str) -> Dict:
    """
    Wat een productveld aanwijst: welk product uit het corpus en, als de tekst er een noemt, welke
    verzekeraar. Deterministisch: bij meerdere producten wint de langste naam die in de tekst past;
    kan het nog steeds meer dan één product zijn, dan is het niet eenduidig en kiezen we er geen.
    """
    p = _sleutel(tekst)
    verz = _verzekeraars()
    genoemd = [naam for sl, naam in sorted(verz.items()) if _als_woord(sl, p)]
    vreemd = _noemt_andere_verzekeraar(p)
    for sl in verz:                                         # de naam van de verzekeraar is geen productnaam
        p = re.sub(rf"(?<![a-z0-9]){re.escape(sl)}(?![a-z0-9])", " ", p)
    if vreemd:
        p = re.sub(rf"(?<![a-z0-9]){re.escape(_sleutel(vreemd))}(?![a-z0-9])", " ", p)
    p = " ".join(p.split())
    producten = sorted({r.get("product") for r in CORPUS.data.get("polisvoorwaarden", []) if r.get("product")})
    uit = {"product": None, "verzekeraar": genoemd[0] if len(genoemd) == 1 else None,
           "meerdere_verzekeraars": len(genoemd) > 1, "buiten_corpus": vreemd, "eenduidig": True}
    if not p:
        return uit
    gelijk = [k for k in producten if _sleutel(k) == p]
    bevat = sorted((k for k in producten if _sleutel(k) in p), key=lambda k: (-len(k), k))
    past_in = [k for k in producten if p in _sleutel(k)]
    if gelijk:
        uit["product"] = gelijk[0]
    elif bevat:
        uit["product"] = bevat[0]
    elif len(past_in) == 1:
        uit["product"] = past_in[0]
    elif len(past_in) > 1:
        uit["eenduidig"] = False
    return uit


def _product_filter(product: str):
    """Filter voor Corpus.zoek op de gekozen productsoort; None als er niets is gekozen of herkend."""
    gelijk = _herken(product)["product"]
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
                            "fragment": _stuk(d.get("tekst"), LIMIET_ZICHTBAAR)})
            elif b == "kifid":
                uit.append({"soort": "kifid", "label": f"Kifid {d.get('uitspraaknummer')}",
                            "titel": d.get("thema") or d.get("titel"), "uitkomst": _uitkomst(d),
                            "url": d.get("bron_url"), "verweerder": d.get("verweerder"),
                            "datum": d.get("datum"), "bindend": d.get("bindend"),
                            "fragment": _stuk(d.get("samenvatting") or d.get("kern_klacht"), LIMIET_ZICHTBAAR)})
            else:
                uit.append({"soort": "polis",
                            "label": f"{d.get('product')} {d.get('clausule_id')}",
                            "titel": d.get("kop"), "type": d.get("type"),
                            "product": d.get("product"), "clausule": d.get("clausule_id"),
                            "verzekeraar": d.get("verzekeraar_of_bron"), "document": d.get("document"),
                            "url": d.get("bron_url"), "fragment": _stuk(d.get("tekst"), LIMIET_ZICHTBAAR)})
    return uit


# =============================================================== 1. dekkingscheck

def dekkingscheck(situatie: str, product: str = "") -> Dict:
    gekozen = _herken(product)["product"]         # de herkende productnaam, niet de ruwe invoer
    vraag = f"{gekozen or ''} {situatie}".strip()
    ctx = _context(vraag, ["polisvoorwaarden", "wetgeving"], per_bron=5,
                   waar={"polisvoorwaarden": _product_filter(product), "wetgeving": VERZEKERINGSRECHT})
    gebruiker = (
        f"SCHADESITUATIE:\n{situatie}\n\nPRODUCT: {gekozen or 'niet opgegeven of niet herkend'}\n\n"
        "Beoordeel op basis van UITSLUITEND de bronnen:\n"
        "1. Welke clausules raken deze situatie? Noem ze bij hun clausulenummer.\n"
        "2. Wijst dit op dekking of op een uitsluiting? Wees expliciet als het onduidelijk is.\n"
        "3. Welke feiten ontbreken om dit hard te maken?\n"
        "Als de bronnen geen uitsluitsel geven, zeg dat en benoem welke polisvoorwaarden "
        "de adviseur moet opvragen.")
    return {"functie": "dekkingscheck", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 1000}


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
            "max_tokens": 800}


# =============================================================== 3. schadeberekening

def schadeberekening(verzekerde_som: float, werkelijke_waarde: float, schade: float,
                     eigen_risico: float = 0, bereddingskosten: float = 0) -> Dict:
    for naam, w in (("verzekerde som", verzekerde_som), ("werkelijke waarde", werkelijke_waarde), ("schade", schade),
                    ("eigen risico", eigen_risico), ("bereddingskosten", bereddingskosten)):
        _getal(w, naam)
    u = rk.evenredigheidsbeginsel(verzekerde_som, werkelijke_waarde, schade,
                                  eigen_risico, bereddingskosten)
    ctx = _context("onderverzekering evenredigheid verzekerde som herbouwwaarde eigen risico",
                   ["wetgeving", "polisvoorwaarden"], per_bron=3, grondslag=u.grondslag,
                   waar={"wetgeving": VERZEKERINGSRECHT})
    stappen = _stappen_tekst(u)
    gebruiker = (
        f"De berekening is AL UITGEVOERD in deterministische code. Neem deze cijfers "
        f"letterlijk over, reken niets na en wijk er niet van af:\n\n"
        f"{_uitkomstregel('Uitkering', u)}\n{stappen}\n"
        f"{_zelf_te_dragen(u)}"
        f"Waarschuwingen: {'; '.join(u.waarschuwingen) or 'geen'}\n\n"
        "Leg in helder Nederlands uit wat hier gebeurt en waarom, voor een adviseur die dit "
        "aan een klant moet uitleggen. Noem expliciet wat de klant zelf draagt en waarom.")
    return {"functie": "schadeberekening", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 900}


# =============================================================== 4. verjaringstoets

def _getal(waarde, naam: str, minimum=0, maximum=10**12):
    """
    Een bedrag of percentage dat de rekenkern in mag. Onzin (tekst, negatief, een percentage boven
    de 100) wordt geweigerd met een duidelijke melding in plaats van doorgerekend: een rekenkern die
    -312 euro premie netjes verwerkt geeft schijnzekerheid.
    """
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(str(waarde))
    except InvalidOperation:
        raise ValueError(f"{naam}: '{waarde}' is geen getal")
    if not d.is_finite():
        raise ValueError(f"{naam}: '{waarde}' is geen geldig getal")
    if minimum is not None and d < minimum:
        raise ValueError(f"{naam} mag niet lager zijn dan {minimum} (ingevuld: {waarde})")
    if maximum is not None and d > maximum:
        raise ValueError(f"{naam} mag niet hoger zijn dan {maximum} (ingevuld: {waarde})")
    return waarde


def _bool(waarde, naam: str) -> bool:
    """Een schakelaar. 'nee' is in Python waar; een API-client die 'nee' stuurt bedoelt onwaar."""
    if isinstance(waarde, bool):
        return waarde
    if waarde is None or waarde == "":
        return False
    t = str(waarde).strip().lower()
    if t in ("ja", "true", "1", "aan", "waar", "yes"):
        return True
    if t in ("nee", "false", "0", "uit", "onwaar", "no"):
        return False
    raise ValueError(f"{naam}: '{waarde}' is geen ja/nee-waarde")


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
                                 _bool(aansprakelijkheid, "aansprakelijkheid"),
                                 _datum(peildatum, "peildatum"))
    ctx = _context("verjaring rechtsvordering verzekeraar stuiting termijn afwijzing",
                   ["wetgeving", "kifid"], per_bron=3, grondslag=u.grondslag,
                   waar={"wetgeving": VERZEKERINGSRECHT})
    gebruiker = (
        f"De termijnberekening is AL UITGEVOERD. Neem letterlijk over:\n"
        f"{u.toelichting}\n"
        + _stappen_tekst(u) +
        "\n\nLeg uit wat dit betekent en wat de adviseur NU moet doen. Wees concreet over "
        "stuiting. Reken zelf niets na.")
    return {"functie": "verjaringstoets", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 650}


# =============================================================== 5. provisietoets

def provisietoets(producttype: str, jaarpremie: float = 0, provisiepercentage: float = 0,
                  directe_beloning: float = 0) -> Dict:
    _getal(jaarpremie, "jaarpremie")
    _getal(provisiepercentage, "provisiepercentage", 0, 100)
    _getal(directe_beloning, "directe beloning")
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
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 650}


# =============================================================== 6. dossiercheck

def _nl_getal(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _afkap(tekst: str, wat: str):
    """De eerste MAX_INVOER tekens gaan naar het model; wat er daarna komt wordt niet gelezen. Zeg dat."""
    tekst = tekst or ""
    if len(tekst) <= MAX_INVOER:
        return tekst, [], ""
    opm = (f"{wat} is {_nl_getal(len(tekst))} tekens lang; alleen de eerste {_nl_getal(MAX_INVOER)} zijn gelezen "
           "en getoetst. Wat daarna staat is niet meegewogen.")
    return tekst[:MAX_INVOER], [opm], (f"\nLET OP: {wat.lower()} is afgekapt na {MAX_INVOER} tekens. Zeg in je "
                                       "antwoord dat alleen het eerste deel is getoetst.\n")


def dossiercheck(dossiertekst: str) -> Dict:
    tekst, opmerkingen, afgekapt = _afkap(dossiertekst, "Het dossier")
    # De zoekvraag bestaat niet alleen uit de vaste zorgplichttermen: het dossier zelf bepaalt welke
    # productregels erbij horen (provisie, hypotheek, beleggingsverzekering).
    ctx = _context("passend advies klantprofiel zorgplicht informatieverstrekking "
                   "kennis ervaring doelstelling risicobereidheid financiele positie " + tekst[:800],
                   ["wetgeving", "kifid"], per_bron=5, waar={"wetgeving": GEDRAGSREGELS})
    gebruiker = (
        f"ADVIESDOSSIER:\n---\n{tekst}\n---\n{afgekapt}\n"
        "Toets dit dossier tegen de zorgplicht- en adviesvereisten uit de bronnen.\n"
        "1. Welke verplichte elementen zijn AANWEZIG? Citeer waar je ze ziet.\n"
        "2. Welke ONTBREKEN? Dit is het belangrijkste deel.\n"
        "3. Welk concreet risico loopt de adviseur bij een klacht?\n"
        "Wees streng. Een ontbrekend element niet benoemen is erger dan te streng zijn.")
    return {"functie": "dossiercheck", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "opmerkingen": opmerkingen,
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 900}


# =============================================================== 7. polisvergelijker

TYPE_VOLGORDE = ["dekking", "uitsluiting", "eigen risico", "verplichting verzekerde",
                 "schaderegeling", "verjaring"]


def _kant(tekst: str, plaats: str = "Variant", max_n: int = 10) -> Dict:
    """
    Eén kant van de vergelijking: precies de clausules van het gekozen product, van de gekozen
    verzekeraar als er een genoemd is. Een vergelijking moet controleerbaar zijn: geen zoekscore die
    bepaalt wat er wel en niet naast elkaar komt te staan, en geen verzekeraar die stilzwijgend
    wordt vervangen door een andere.
    """
    h = _herken(tekst)
    rijen = CORPUS.data.get("polisvoorwaarden", [])
    kant = {"product": h["product"], "verzekeraar": h["verzekeraar"], "rijen": [], "opmerking": ""}
    if h["buiten_corpus"]:
        kant["opmerking"] = (f"{plaats}: van {h['buiten_corpus'].title()} staan geen polisvoorwaarden in het corpus, "
                             "dus daar is niets van te vergelijken.")
        return kant
    if h["meerdere_verzekeraars"]:
        kant["opmerking"] = f"{plaats}: dit veld noemt meer dan één verzekeraar; kies per variant één product van één verzekeraar."
        return kant
    if not h["eenduidig"]:
        kant["opmerking"] = f"{plaats}: dit past op meerdere producten; kies er één uit de lijst."
        return kant
    if not h["product"]:
        kant["opmerking"] = (f"{plaats}: dit product staat niet in het corpus." if (tekst or "").strip()
                             else f"{plaats}: dit veld is leeg; kies een product en verzekeraar.")
        return kant
    mijn = [r for r in rijen if r.get("product") == h["product"]
            and (not h["verzekeraar"] or r.get("verzekeraar_of_bron") == h["verzekeraar"])]
    if not mijn:
        kant["opmerking"] = (f"{plaats}: {_kort(h['verzekeraar'])} heeft in het corpus geen {h['product']}; "
                             "die kant blijft leeg in plaats van dat er iets van een andere verzekeraar voor in de plaats komt.")
        return kant
    aanbieders = sorted({r.get("verzekeraar_of_bron") for r in mijn})
    if len(aanbieders) > 1:
        kant["opmerking"] = (f"{plaats}: geen verzekeraar genoemd, dus de clausules van {', '.join(_kort(a) for a in aanbieders)} "
                             "staan door elkaar. Kies een variant met verzekeraar voor een zuivere vergelijking.")
    else:
        kant["verzekeraar"] = aanbieders[0]
    mijn.sort(key=lambda r: (r.get("verzekeraar_of_bron") or "",
                             TYPE_VOLGORDE.index(r["type"]) if r.get("type") in TYPE_VOLGORDE else 99,
                             r.get("clausule_id") or ""))
    if len(mijn) > max_n:
        kant["opmerking"] = (kant["opmerking"] + " " if kant["opmerking"] else "") + \
            f"{plaats}: {len(mijn)} clausules in het corpus; de eerste {max_n} staan hier (dekking en uitsluitingen eerst)."
    kant["rijen"] = mijn[:max_n]
    return kant


def _kantnaam(k: Dict) -> str:
    if k["product"]:
        return f"{k['product']} ({_kort(k['verzekeraar'])})" if k["verzekeraar"] else k["product"]
    return "een product dat het portaal niet herkent"


def polisvergelijker(product_a: str, product_b: str) -> Dict:
    """Verschilanalyse over echte clausules; het model beschrijft, het corpus levert."""
    ka, kb = _kant(product_a, "Variant A"), _kant(product_b, "Variant B")
    ra, rb = ka["rijen"], kb["rijen"]
    opmerkingen = [k["opmerking"] for k in (ka, kb) if k["opmerking"]]
    if ka["product"] and (ka["product"], ka["verzekeraar"]) == (kb["product"], kb["verzekeraar"]) and ra:
        opmerkingen.append("Variant A en B wijzen op hetzelfde product van dezelfde verzekeraar; er is niets te vergelijken.")
    docs = ra + rb
    rijen = lambda lst: [(0.0, d) for d in lst]
    naam_a, naam_b = _kantnaam(ka), _kantnaam(kb)
    blok = (f"=== VARIANT A: {naam_a} ===\n{_blok('polisvoorwaarden', rijen(ra)) or '(geen clausules in het corpus)'}\n\n"
            f"=== VARIANT B: {naam_b} ===\n{_blok('polisvoorwaarden', rijen(rb)) or '(geen clausules in het corpus)'}")
    gebruiker = (
        f"Vergelijk variant A ({naam_a}) met variant B ({naam_b}) op basis van UITSLUITEND bovenstaande clausules.\n"
        "1. Waar verschillen de UITSLUITINGEN? Noem clausulenummers aan beide kanten.\n"
        "2. Welk concreet dekkingshiaat ontstaat er als een klant overstapt van A naar B?\n"
        "3. Welke vergelijking kun je NIET maken omdat de clausule aan een kant ontbreekt? "
        "Benoem dat expliciet in plaats van het gat te vullen.\n"
        + ("".join(f"Let op: {o}\n" for o in opmerkingen)))
    bronnen = _bronlijst({"polisvoorwaarden": docs})
    for i, b in enumerate(bronnen):
        b["kant"] = "A" if i < len(ra) else "B"        # de UI toont beide varianten naast elkaar
    return {"functie": "polisvergelijker", "systeem": grounding.systeemprompt(blok),
            "gebruiker": gebruiker, "opgehaald": {"polisvoorwaarden": docs}, "opmerkingen": opmerkingen,
            "bronnen": bronnen, "berekening": None, "max_tokens": 800}


# =============================================================== 8. klachtroute

KLACHT_ARTIKELEN = ["Wft:4:17", "BGfo:39", "BGfo:40", "BGfo:41", "BGfo:42", "BGfo:43", "BGfo:44"]


def klachtroute(situatie: str, datum_klacht: str = "", intern_afgehandeld: bool = False,
                datum_bevestiging: str = "", peildatum: str = "") -> Dict:
    intern = _bool(intern_afgehandeld, "intern_afgehandeld")
    d_klacht, d_bev = _datum(datum_klacht, "datum_klacht"), _datum(datum_bevestiging, "datum_bevestiging")
    if d_bev and not d_klacht:
        raise ValueError("datum_bevestiging: vul ook de datum van de klacht in")
    u = None
    if d_klacht:
        u = rk.klachttermijnen(d_klacht, d_bev, _datum(peildatum, "peildatum"))
    # De kernartikelen over klachtafhandeling horen bij elke klachtroute; de situatie bepaalt welke
    # uitspraken erbij passen. Met een vaste zoekvraag kreeg elke casus dezelfde bronnen.
    ctx = _context(f"{(situatie or '')[:600]} klachtprocedure Kifid ontvankelijkheid termijn bindend advies "
                   "geschilleninstantie interne klachtafhandeling", ["wetgeving", "kifid"], per_bron=4,
                   grondslag=KLACHT_ARTIKELEN + (u.grondslag if u else []))
    termijnen = ""
    if u:
        termijnen = ("De termijnen zijn AL BEREKEND. Neem deze data letterlijk over en reken niets na:\n"
                     + _stappen_tekst(u) + f"\n{u.toelichting}\n\n")
    gebruiker = (
        f"SITUATIE:\n{situatie}\n"
        f"Datum klacht: {datum_klacht or 'niet opgegeven'}\n"
        f"Interne klachtprocedure doorlopen: {'ja' if intern else 'nee'}\n\n{termijnen}"
        "Beschrijf op basis van de bronnen de route:\n"
        "1. Welke stap is nu aan de orde?\n"
        "2. Welke termijnen gelden en waar blijkt dat uit?\n"
        "3. Welke informatie moet mee bij indiening?\n"
        "Staat een termijn niet in de bronnen, zeg dat dan in plaats van een termijn te noemen.")
    return {"functie": "klachtroute", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict() if u else None, "max_tokens": 800}


# =============================================================== 9. afwijzingsanalyse

def afwijzingsanalyse(brieftekst: str) -> Dict:
    tekst, opmerkingen, afgekapt = _afkap(brieftekst, "De brief")
    ctx = _context(tekst[:600] + " afwijzing dekking uitsluiting mededelingsplicht "
                   "opzet eigen gebrek", ["polisvoorwaarden", "kifid", "wetgeving"], per_bron=4,
                   waar={"wetgeving": VERZEKERINGSRECHT})
    gebruiker = (
        f"AFWIJZINGSBRIEF VAN DE VERZEKERAAR:\n---\n{tekst}\n---\n{afgekapt}\n"
        "Analyseer op basis van UITSLUITEND de bronnen:\n"
        "1. Op welke grond wijst de verzekeraar af? Citeer die grond uit de brief.\n"
        "2. Wordt die grond gedragen door een clausule of wetsartikel uit de bronnen? "
        "Zo nee, zeg dat - dat is het sterkste aanknopingspunt voor de adviseur.\n"
        "3. Welke tegenargumenten volgen uit de bronnen, met verwijzing?\n"
        "4. Welk bewijs moet de adviseur verzamelen?\n"
        "Overschat de zaak niet. Als de afwijzing terecht lijkt, zeg dat eerlijk.")
    return {"functie": "afwijzingsanalyse", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "opmerkingen": opmerkingen,
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 900}


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
    _getal(nieuwwaarde, "nieuwwaarde")
    _getal(ouderdom_jaren, "ouderdom", 0, 1000)
    _getal(levensduur_jaren, "levensduur", 0, 1000)
    _getal(drempel_pct, "drempel", 0, 100)
    u = rk.nieuwwaarde_of_dagwaarde(nieuwwaarde, ouderdom_jaren, levensduur_jaren, drempel_pct)
    ctx = _context("nieuwwaarde dagwaarde afschrijving vervangingswaarde inboedel",
                   ["polisvoorwaarden", "wetgeving"], per_bron=3)
    gebruiker = (
        f"De waardebepaling is AL UITGEVOERD. Neem letterlijk over:\n"
        f"{_uitkomstregel('Uitkomst', u)} - {u.toelichting}\n"
        + _stappen_tekst(u) +
        f"\nWaarschuwingen: {'; '.join(u.waarschuwingen)}\n\n"
        "Leg uit wat dit voor de klant betekent. Benadruk dat de drempel uit de "
        "polisvoorwaarden komt en per verzekeraar verschilt. Reken niets na.")
    return {"functie": "waardetoets", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"],
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 600}


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
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 700}


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
