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
import os
import re
import unicodedata
from decimal import Decimal
from typing import Dict, List, Optional
from datetime import date, datetime

from retrieval import Corpus, tokenize
import rekenkern as rk
import grounding


CORPUS = Corpus()
MAX_INVOER = 6000        # zoveel tekens van een dossier of brief gaan naar het model


# --------------------------------------------------------------- hulpfuncties

VERPLICHT = 999.0     # score voor artikelen waarop een berekening rust; altijd in de bronnen


def _uitkomstregel(label: str, u) -> str:
    """De uitkomst zoals het model haar leest. Zonder bedrag staat er nooit 'EUR None', maar de reden."""
    d = u.to_dict()
    if d["bedrag"] is None:
        reden = " ".join(u.waarschuwingen) or u.toelichting or "de invoer volstaat niet"
        return (f"{label}: NIET TE BEREKENEN. Reden: {reden} Noem geen bedrag; leg uit wat er ontbreekt "
                "en wat de volgende stap is.")
    return f"{label}: {rk._bedrag(d['bedrag'])}"


HERSCHRIJF = (
    "Schrijf hiervan in helder Nederlands een toelichting voor een adviseur die dit aan een klant moet uitleggen. "
    "Herschrijf UITSLUITEND wat hierboven staat. Voeg geen oorzaken, redenen, voorbeelden of gevolgen toe die er niet "
    "staan (bijvoorbeeld niets over de toestand van het object of de schuldvraag), laat geen bedrag, datum of artikel "
    "weg dat de uitleg noemt, en tegenspreek de cijfers niet. Sluit af met de vervolgstap uit de code.")


def _uitleg_en_vervolg(u) -> str:
    """De uitleg en de vervolgstap uit de code, zoals het model ze leest: het herschrijft, het bedenkt niet."""
    delen = []
    if u.uitleg:
        delen.append("UITLEG UIT DE CODE (juist en volledig):\n" + "\n".join(f"- {x}" for x in u.uitleg))
    if u.volgende_stap:
        delen.append(f"Vervolgstap uit de code: {u.volgende_stap}")
    return "\n".join(delen) + ("\n" if delen else "")


def _regel(tekst: str, n: int = 120) -> str:
    """Een vrij invoerveld dat in een opdracht aan het model komt: één regel, begrensd."""
    return " ".join((tekst or "").split())[:n]


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
        delen.append(f"door onderverzekering {rk._bedrag(d['zelf_te_dragen_door_onderverzekering'])}")
    if Decimal(d.get("zelf_te_dragen_boven_verzekerde_som", "0")) > 0:
        delen.append(f"boven de verzekerde som {rk._bedrag(d['zelf_te_dragen_boven_verzekerde_som'])}")
    if Decimal(d.get("zelf_te_dragen_eigen_risico", "0")) > 0:
        delen.append(f"eigen risico {rk._bedrag(d['zelf_te_dragen_eigen_risico'])}")
    return (f"Zelf te dragen door de klant: {rk._bedrag(d['zelf_te_dragen'])} van een totale schade van "
            f"{rk._bedrag(d['totale_schade'])}" + (f" ({'; '.join(delen)})" if delen else "") + ".\n")


def _uitkomst(d: Dict) -> str:
    """
    De uitkomst zoals Kifid die zelf formuleert ('Vordering afgewezen'). Nooit het veld 'oordeel':
    dat is een vertaling naar gegrond/ongegrond die nuance verliest (een klacht kan materieel
    gegrond zijn terwijl de vordering wordt afgewezen).
    """
    u = " ".join((d.get("uitkomst_letterlijk") or d.get("uitkomst_letterlijk_uit_pdf") or "").split()).lower().replace("vorderingen", "vordering")
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
# artikel waarop een berekening rust een ruimere grens. De grenzen liggen boven de langste clausule (2.670 tekens)
# en de langste samenvatting (1.678) van het corpus, en voor de grondslagartikelen boven Wft 4:23 en 4:24 (4.288 en
# 4.668): een kleiner model past nog in 12.000 tokens, zie test_de_langste_opdracht_past_in_het_lokale_model.
LIMIET_WET, LIMIET_WET_GRONDSLAG, LIMIET_POLIS, LIMIET_KIFID = 3500, 4800, 2700, 1800
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
            # Met de verzekeraar in de kop: zonder die kan het model niet zeggen van wie een clausule is (alleen de
            # URL verraadt het), en een clausule van de ene verzekeraar wordt dan als 'de' regel gepresenteerd.
            uit.append(f"[{d.get('verzekeraar_of_bron') or 'verzekeraar onbekend'} | {d.get('product')} "
                       f"{d.get('clausule_id')} - {d.get('type')}] "
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
    # 'opstalverzekering en inboedelverzekering' noemt twee producten: dan kiest het portaal er niet stilzwijgend één
    maximaal = [k for k in bevat if not any(k != m and _sleutel(k) in _sleutel(m) for m in bevat)]
    past_in = [k for k in producten if p in _sleutel(k)]
    if gelijk:
        uit["product"] = gelijk[0]
    elif len(maximaal) > 1:
        uit["eenduidig"] = False
        uit["meerdere_producten"] = maximaal
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


def _polisfilter(*teksten, product: str = "", verzekeraar: str = ""):
    """
    Het filter voor polisclausules: het product van de klant en, als bekend, ZIJN verzekeraar. Zonder dit stelt
    een dekkingsoordeel over een Univé-polis clausules van Klaverblad als voorwaarde van de klant voor, en dat
    is precies de fout die een adviseur kan laten uitbetalen of weigeren op de verkeerde voorwaarden.

    De verzekeraar volgt uit het veld `verzekeraar` of anders uit de tekst (een casus- of briefomschrijving die er
    één noemt). Noemt de tekst er meerdere, dan kiest het portaal niet. Is de verzekeraar er wel één, maar staan
    zijn voorwaarden niet in het corpus, dan komt er GEEN polisclausule (van een ander) voor in de plaats.
    Geeft (filter of None, meldingen, verzekeraar kort of None).
    """
    hp = _herken(product)
    genoemd, buiten, meerdere = set(), None, False
    for t in (verzekeraar, *teksten):
        h = _herken(t or "")
        if h["verzekeraar"]:
            genoemd.add(h["verzekeraar"])
        meerdere = meerdere or h["meerdere_verzekeraars"]
        buiten = buiten or h["buiten_corpus"]
    productfilter = _product_filter(product) if hp["product"] else None
    if buiten and not genoemd:
        return (lambda d: False), [f"Van {buiten.title()} staan geen polisvoorwaarden in het corpus. Er zijn daarom geen polisclausules opgehaald: "
                                   "clausules van een andere verzekeraar gelden niet voor deze klant. Vraag de voorwaarden van de klant op."], None
    if len(genoemd) == 1 and not meerdere:
        naam = next(iter(genoemd))
        return ((lambda d: (productfilter is None or productfilter(d)) and d.get("verzekeraar_of_bron") == naam),
                [], _kort(naam))
    meldingen = []
    if len(genoemd) > 1 or meerdere:
        meldingen.append("Er worden meerdere verzekeraars genoemd; het portaal kiest er geen. Bij elke clausule staat van welke verzekeraar en "
                         "welk product ze is: gebruik alleen die van de verzekeraar van de klant.")
    return productfilter, meldingen, None


def _van_wie(kort, polis_docs) -> str:
    """Wat het model moet weten over de verzekeraar van de klant en van wie de aangeleverde clausules zijn."""
    aangeleverd = sorted({_kort(d.get("verzekeraar_of_bron")) for d in polis_docs})
    if kort:
        return f"{kort}. Alleen de voorwaarden van deze verzekeraar zijn aangeleverd."
    if aangeleverd:
        namen = ", ".join(aangeleverd)
        return ("niet vastgesteld. De aangeleverde clausules zijn van " + namen + ("" if namen.endswith(".") else ".")
                + " Noem bij elke clausule van welke verzekeraar en welk product ze is; presenteer er geen als voorwaarde "
                "van deze klant zolang zijn verzekeraar niet vaststaat.")
    return "niet vastgesteld; er zijn geen polisclausules aangeleverd."


# Welk deel van de wetgeving bij welke vraag hoort. Een dekkingsvraag gaat over het verzekeringsrecht
# (BW boek 7), niet over de gedragsregels voor adviseurs (Wft, BGfo); andersom geldt hetzelfde. Zonder
# dit filter haalde een inbraakcasus artikelen over meldingsplichten aan de AFM op, alleen omdat
# 'melden' en 'klant' erin voorkomen.
def _wet(*wetten):
    return lambda d: d.get("wet") in wetten


VERZEKERINGSRECHT = _wet("BW")
GEDRAGSREGELS = _wet("Wft", "BGfo")


def _gelezen_als(correcties) -> Optional[str]:
    """De melding bij een herstelde spelling in de zoekopdracht; None als er niets is hersteld."""
    if not correcties:
        return None
    return ("Zoekopdracht gelezen als: " + "; ".join(f"'{a}' → '{b}'" for a, b in correcties)
            + ". Klopt dat niet, pas dan de spelling aan.")


def _meld(ctx: Dict, opmerkingen=None) -> List[str]:
    """De meldingen bij een aanvraag: wat er met de invoer is gedaan (afgekapt) en hoe de spelling is gelezen."""
    return (list(opmerkingen or []) + list(ctx.get("meldingen") or [])
            + ([m] if (m := _gelezen_als(ctx.get("correcties"))) else []))


# Hoeveel tekens polisclausules het model in één opdracht krijgt. Het corpus heeft hooguit 21 clausules per product; zolang
# ze passen krijgt het model ze allemaal (op relevantie geordend), zodat 'er staat niets over X' echt over het product
# gaat en niet over wat de zoekmachine toevallig bovenaan zette. Een sterk model kan meer aan: ASSURANTIE_POLIS_BUDGET.
POLIS_BUDGET = int(os.environ.get("ASSURANTIE_POLIS_BUDGET", "16000"))


def _polis_alle(vraag: str, filter_, budget: int):
    """Alle clausules die het filter toelaat, de meest relevante eerst, tot het budget op is. Geeft (rijen, totaal)."""
    alle = [d for d in CORPUS.data.get("polisvoorwaarden", []) if filter_(d)]
    scores = {id(d): sc for sc, d in CORPUS.zoek("polisvoorwaarden", vraag, max(len(alle), 1), filter_)}
    volgorde = sorted(alle, key=lambda d: (-scores.get(id(d), 0.0), d.get("verzekeraar_of_bron") or "", d.get("clausule_id") or ""))
    rijen, gebruikt = [], 0
    for d in volgorde:
        n = min(len(d.get("tekst") or ""), LIMIET_POLIS) + 120
        if rijen and gebruikt + n > budget:
            break
        rijen.append((scores.get(id(d), 0.0), d))
        gebruikt += n
    return rijen, len(alle)


def _genoemde_clausules(tekst: str, filter_) -> List[Dict]:
    """De clausules van het gekozen product waar een brief zich op beroept ('artikel 4.2'): die horen er altijd bij."""
    if filter_ is None:
        return []
    nummers = set(re.findall(r"(?i)\bart(?:ikel|\.)?\s*(\d+(?:\.\d+)*)", tekst or ""))
    uit = []
    for d in CORPUS.data.get("polisvoorwaarden", []):
        m = re.match(r"art\.\s*(\d+(?:\.\d+)*)", (d.get("clausule_id") or "").lower())
        if m and m.group(1) in nummers and filter_(d):
            uit.append(d)
    return uit


def _wet_alleen(*artikelen):
    """Filter op wetsartikelen uit een lijst 'Wft:4:20', 'BGfo:86c'."""
    toegestaan = {tuple(a.split(":", 1)) for a in artikelen}
    return lambda d: (d.get("wet"), str(d.get("artikel"))) in toegestaan


def _context(vraag: str, bronnen: List[str], per_bron=4, grondslag=(), waar=None, eigen=None, min_rel=None,
             polis_alle=None, polis_extra=(), dekking=0.0) -> Dict:
    """
    `eigen` is het deel van de zoekvraag dat de adviseur zelf typte. Alleen daarvan meldt het portaal een herstelde
    spelling ('Zoekopdracht gelezen als'); de vaste woorden die de code aan de vraag toevoegt gaan de adviseur niet aan.
    `min_rel`: laat resultaten weg die minder dan dit deel van de beste score van hun bron halen (ruis als 'cv-ketel' bij
    een vraag over zorgplicht). `dekking`: alleen resultaten die dit deel van de zoektermen bevatten (zie Index.zoek). `polis_alle`: heeft de adviseur een product (of verzekeraar) gekozen, dan krijgt het model
    alle clausules daarvan tot dit aantal tekens. `polis_extra`: clausules die altijd horen (de brief noemt ze).
    """
    opgehaald, blokken, meldingen = {}, [], []
    waar = waar or {}
    verplicht = _grondslag_docs(grondslag)
    if verplicht and "wetgeving" not in bronnen:
        bronnen = ["wetgeving"] + list(bronnen)
    for b in bronnen:
        if b == "polisvoorwaarden" and polis_alle and waar.get(b) is not None:
            rows, totaal = _polis_alle(vraag, waar[b], polis_alle)
            if len(rows) < totaal:
                meldingen.append(f"Het corpus heeft {totaal} clausules bij dit product; de {len(rows)} die het best bij de vraag "
                                 "passen zijn aan het model getoond. Een clausule die hier niet staat, is niet bekeken.")
        else:
            n = per_bron.get(b, 0) if isinstance(per_bron, dict) else per_bron
            rows = CORPUS.zoek(b, vraag, n, waar.get(b), dekking) if n else []
            if min_rel and rows:
                rows = [(sc, d) for sc, d in rows if sc >= min_rel * rows[0][0]]
        if b == "polisvoorwaarden" and polis_extra:
            al = {id(d) for _, d in rows}
            rows = [(0.0, d) for d in polis_extra if id(d) not in al] + rows
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
    return {"opgehaald": opgehaald, "blok": "\n\n".join(blokken) or "(geen bronnen gevonden)",
            "correcties": CORPUS.correcties(vraag if eigen is None else eigen), "meldingen": meldingen}


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

def dekkingscheck(situatie: str, product: str = "", verzekeraar: str = "") -> Dict:
    gekozen = _herken(product)["product"]         # de herkende productnaam, niet de ruwe invoer
    polisfilter, meldingen, kort = _polisfilter(situatie, product=product, verzekeraar=verzekeraar)
    vraag = f"{gekozen or ''} {situatie}".strip()
    ctx = _context(vraag, ["polisvoorwaarden", "wetgeving"], per_bron=5, min_rel=0.4, polis_alle=POLIS_BUDGET,
                   waar={"polisvoorwaarden": polisfilter, "wetgeving": VERZEKERINGSRECHT})
    van_wie = _van_wie(kort, ctx["opgehaald"].get("polisvoorwaarden", []))
    gebruiker = (
        f"SCHADESITUATIE:\n{situatie}\n\nPRODUCT: {gekozen or 'niet opgegeven of niet herkend'}\nVERZEKERAAR VAN DE KLANT: {van_wie}\n\n"
        "Beoordeel op basis van UITSLUITEND de bronnen:\n"
        "1. Welke clausules raken deze situatie? Noem ze bij hun clausulenummer.\n"
        "2. Wijst dit op dekking of op een uitsluiting? Wees expliciet als het onduidelijk is.\n"
        "3. Welke feiten ontbreken om dit hard te maken?\n"
        "Als de bronnen geen uitsluitsel geven, zeg dat en benoem welke polisvoorwaarden "
        "de adviseur moet opvragen.")
    return {"functie": "dekkingscheck", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "opmerkingen": _meld(ctx, meldingen),
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 1000}


# =============================================================== 2. precedentzoeker

def precedentzoeker(geschil: str) -> Dict:
    """
    Aggregeert de WERKELIJK gepubliceerde oordelen van vergelijkbare zaken.
    De statistiek komt uit het corpus, niet uit het model - dat is het hele punt.
    """
    rows = CORPUS.zoek("kifid", geschil, 8)
    if rows:                                          # een uitspraak die veel minder past dan de beste is ruis, geen precedent
        rows = [(sc, d) for sc, d in rows if sc >= 0.4 * rows[0][0]]
    docs = [d for _, d in rows]
    telling = {}
    for d in docs:
        o = _uitkomst(d)
        telling[o] = telling.get(o, 0) + 1
    ctx = {"opgehaald": {"kifid": docs}, "blok": _blok("kifid", rows) or "(geen uitspraken gevonden)",
           "correcties": CORPUS.correcties(geschil),
           "meldingen": ([f"Er {'is' if len(docs) == 1 else 'zijn'} maar {len(docs)} passende {'uitspraak' if len(docs) == 1 else 'uitspraken'} "
                          "gevonden; een verdeling zegt dan weinig."] if 0 < len(docs) < 3 else [])}

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
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "opmerkingen": _meld(ctx),
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
    # Alleen de wet. De berekening rust op BW 7:955-7:959; polisclausules van willekeurige verzekeraars zijn hier
    # geen grondslag en het lokale model haalde er bij een echte proef een 'extra eigen risico bij storm tijdens
    # een verbouwing' uit dat niet bij de vraag hoorde. Dat het eigen risico polisafhankelijk is, staat in de waarschuwingen.
    ctx = _context("onderverzekering evenredigheid verzekerde som herbouwwaarde eigen risico",
                   ["wetgeving"], per_bron=0, grondslag=u.grondslag,
                   waar={"wetgeving": VERZEKERINGSRECHT}, eigen="")
    stappen = _stappen_tekst(u)
    gebruiker = (
        f"De berekening is AL UITGEVOERD in deterministische code. Neem deze cijfers "
        f"letterlijk over, reken niets na en wijk er niet van af:\n\n"
        f"{_uitkomstregel('Uitkering', u)}\n{stappen}\n"
        f"{_zelf_te_dragen(u)}"
        f"{_uitleg_en_vervolg(u)}"
        f"Waarschuwingen: {'; '.join(u.waarschuwingen) or 'geen'}\n\n"
        f"{HERSCHRIJF}" + (" Noem expliciet wat de klant zelf draagt en waardoor." if u.bedrag is not None else ""))
    return {"functie": "schadeberekening", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "tekst_uit_code": True,
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 900}


# =============================================================== 4. verjaringstoets

def _echo(waarde, n: int = 40) -> str:
    """Wat de adviseur invulde, ingekort voor in een foutmelding: een geplakt verhaal hoeft niet terug te komen."""
    t = " ".join(str(waarde).split())
    return t if len(t) <= n else t[:n].rstrip() + "…"


def _getal(waarde, naam: str, minimum=0, maximum=10**12, eenheid: str = ""):
    """
    Een bedrag of percentage dat de rekenkern in mag. Onzin (tekst, negatief, een percentage boven
    de 100) wordt geweigerd met een duidelijke melding in plaats van doorgerekend: een rekenkern die
    -312 euro premie netjes verwerkt geeft schijnzekerheid.
    """
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(str(waarde))
    except InvalidOperation:
        t = str(waarde).strip()
        tip = (" Gebruik een punt als decimaalteken (1250.50), zonder duizendtallen." if re.fullmatch(r"[\d.]*\d,\d+", t)
               else " Vul alleen een getal in, zonder tekst of eenheid.")
        raise ValueError(f"{naam}: '{_echo(waarde)}' is geen getal.{tip}")
    if not d.is_finite():
        raise ValueError(f"{naam}: '{_echo(waarde)}' is geen geldig getal.")
    if minimum is not None and d < minimum:
        raise ValueError(f"{naam} mag niet lager zijn dan {minimum}{eenheid} (ingevuld: {_echo(waarde)}{eenheid}).")
    if maximum is not None and d > maximum:
        raise ValueError(f"{naam} mag niet hoger zijn dan {maximum}{eenheid} (ingevuld: {_echo(waarde)}{eenheid}).")
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
    """
    Leest een datum: JJJJ-MM-DD (wat het formulier stuurt) of DD-MM-JJJJ (hoe een Nederlander schrijft). Een onleesbare
    of niet bestaande datum is een invoerfout met een duidelijke melding, geen crash.
    """
    if not waarde:
        return None
    t = str(waarde).strip()
    for vorm in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, vorm).date()
        except ValueError:
            continue
    if re.fullmatch(r"\d{1,2}-\d{1,2}-\d{4}|\d{4}-\d{1,2}-\d{1,2}", t):
        raise ValueError(f"{veld}: {_echo(t)} bestaat niet als datum. Controleer de dag en de maand.")
    raise ValueError(f"{veld}: '{_echo(t)}' is geen datum. Gebruik JJJJ-MM-DD (bijvoorbeeld 2023-11-14) of DD-MM-JJJJ.")


def verjaringstoets(datum_bekend: str, datum_stuiting: str = "", datum_reactie: str = "",
                    aansprakelijkheid: bool = False, peildatum: str = "") -> Dict:
    if not datum_bekend:
        raise ValueError("datum_bekend: verplicht (JJJJ-MM-DD)")
    u = rk.verjaring_schadeclaim(_datum(datum_bekend, "datum_bekend"),
                                 _datum(datum_stuiting, "datum_stuiting"),
                                 _datum(datum_reactie, "datum_reactie"),
                                 _bool(aansprakelijkheid, "aansprakelijkheid"),
                                 _datum(peildatum, "peildatum"))
    # Alleen de wet: geen enkele Kifid-uitspraak in het corpus gaat over verjaring, en de zoekmachine geeft toch
    # de best scorende drie terug (op 'verzekeraar' en 'afwijzing'). Een irrelevante uitspraak in de bronnen
    # nodigt uit tot een citaat dat niets bewijst.
    # De polissen kennen een eigen termijn om op een beslissing te reageren (Klaverblad 1.7.3, Univé 9.3): die staan er als
    # voorbeeld bij, van verschillende verzekeraars, zodat de adviseur weet waar hij in de polis van de klant moet zoeken.
    ctx = _context("verjaring rechtsvordering verzekeraar stuiting termijn afwijzing reageren beslissing",
                   ["wetgeving", "polisvoorwaarden"], per_bron={"wetgeving": 0, "polisvoorwaarden": 3}, grondslag=u.grondslag,
                   waar={"wetgeving": VERZEKERINGSRECHT,
                         "polisvoorwaarden": lambda d: d.get("type") == "verjaring" and "reageren" in (d.get("kop") or "").lower()},
                   eigen="")
    gebruiker = (
        f"De termijnberekening is AL UITGEVOERD. Neem letterlijk over:\n"
        f"{u.toelichting}\n"
        + _stappen_tekst(u) +
        f"\n{_uitleg_en_vervolg(u)}"
        f"Waarschuwingen: {'; '.join(u.waarschuwingen) or 'geen'}\n\n"
        f"{HERSCHRIJF} Noem stuiting alleen zoals de toelichting, de stappen en de vervolgstap hierboven dat doen. "
        "Reken zelf niets na.")
    return {"functie": "verjaringstoets", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "tekst_uit_code": True,
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 650}


# =============================================================== 5. provisietoets

def provisietoets(producttype: str, jaarpremie: float = 0, provisiepercentage: float = 0,
                  directe_beloning: float = 0) -> Dict:
    _getal(jaarpremie, "jaarpremie")
    _getal(provisiepercentage, "provisiepercentage", 0, 100, "%")
    _getal(directe_beloning, "directe beloning")
    u = rk.provisie_toets(producttype, jaarpremie, provisiepercentage, directe_beloning)
    # Alleen de wet, om dezelfde reden als bij de verjaringstoets: geen Kifid-uitspraak in het corpus gaat over
    # provisie of beloning; de autoverzekering-uitspraken die 'producttype' opleverde zeggen hier niets over.
    ctx = _context(f"provisieverbod beloning {producttype} dienstverleningsdocument "
                   f"transparantie complex product", ["wetgeving"], per_bron=0,
                   grondslag=u.grondslag + ["Wft:4:25a", "Wft:4:25b"] + (["BGfo:86f"] if (u.details or {}).get("status") == "VERBODEN" else []),
                   waar={"wetgeving": GEDRAGSREGELS}, eigen=producttype)
    bedrag = u.to_dict()["bedrag"]
    gebruiker = (
        f"PRODUCT: {_regel(producttype)}\n"
        f"Toets is AL UITGEVOERD: {u.toelichting}\n"
        f"Bedrag: {rk._bedrag(bedrag) if bedrag else 'niet vast te stellen'}\n"
        f"Signalen: {'; '.join(u.waarschuwingen) or 'geen'}\n"
        f"{_uitleg_en_vervolg(u)}\n"
        "Onderbouw dit met de wetsartikelen uit de bronnen. Noem ALLEEN artikelen die er "
        "letterlijk in staan. Voeg geen feiten toe die hierboven of in de bronnen niet staan. "
        "Sluit af met wat de adviseur in het dossier moet vastleggen.")
    return {"functie": "provisietoets", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "tekst_uit_code": True,
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 650}


# =============================================================== 6. dossiercheck

def _nl_getal(n: int) -> str:
    return f"{n:,}".replace(",", ".")


_BESLISSING = re.compile(r"wij wijzen|wijzen (?:uw|de) (?:claim|schade|aanvraag)|afgewezen|afwijz|uitgesloten|uitsluit|geen dekking|"
                         r"niet verzekerd|weiger|vergoeden (?:wij )?niet|op grond van|artikel\s+\d|art\.\s*\d|voorwaarden", re.I)


def _kernvraag(tekst: str, kop: int = 400, staart: int = 300, zinnen: int = 3) -> str:
    """
    De zoekvraag uit een lange brief of dossier: het begin, het slot en de eerste zinnen waar een beslissing of een
    clausule in staat. Alleen de eerste 600 tekens zoeken (zoals eerst) mist de beslissende passage midden of achterin.
    """
    t = " ".join((tekst or "").split())
    if len(t) <= kop + staart + 100:
        return t
    midden = t[kop:len(t) - staart]
    gekozen = []
    for zin in re.split(r"(?<=[.!?])\s+", midden):
        if _BESLISSING.search(zin):
            gekozen.append(zin[:240])
            if len(gekozen) >= zinnen:
                break
    return " ".join([t[:kop], *gekozen, t[-staart:]])


def _afkap(tekst: str, wat: str):
    """De eerste MAX_INVOER tekens gaan naar het model; wat er daarna komt wordt niet gelezen. Zeg dat."""
    tekst = tekst or ""
    if len(tekst) <= MAX_INVOER:
        return tekst, [], ""
    opm = (f"{wat} is {_nl_getal(len(tekst))} tekens lang; alleen de eerste {_nl_getal(MAX_INVOER)} zijn gelezen "
           "en getoetst. Wat daarna staat is niet meegewogen.")
    return tekst[:MAX_INVOER], [opm], (f"\nLET OP: {wat.lower()} is afgekapt na {MAX_INVOER} tekens. Zeg in je "
                                       "antwoord dat alleen het eerste deel is getoetst.\n")


# De artikelen waartegen elk adviesdossier wordt getoetst: wensen en behoeften vaststellen (4:22a), de
# ken-uw-klantplicht en de toelichting op het advies (4:23), de zorgplicht (4:24a) en de informatie over
# dienstverlening en beloning (4:25b). Ze horen altijd bij de bronnen: welke ervan bovenaan de zoekresultaten
# staat, hangt anders af van de woorden in het dossier.
DOSSIER_ARTIKELEN = ["Wft:4:22a", "Wft:4:23", "Wft:4:24a", "Wft:4:25b"]

# Noemt het dossier een provisie of beloning, of een product uit het verbod van art. 86c lid 1, dan horen ook de
# artikelen erbij die zeggen wanneer beloning via provisie mag: 86c (het verbod) en 86d/86i (schadeverzekeringen).
# Zonder die artikelen kan het model de vraag 'mag dit?' niet uit de bronnen beantwoorden, ook al staat het antwoord
# in het corpus.
PROVISIE_ARTIKELEN = ["BGfo:86c", "BGfo:86d", "BGfo:86i"]
# De informatieplichten die bij advies horen en die de zoekmachine erbij mag halen. Vakbekwaamheid (Wft 4:9, BGfo 6),
# klachten (BGfo 40, 41, 43) en de vergelijkingskaart van producten onder het provisieverbod (BGfo 86f) horen er niet bij.
DOSSIER_EXTRA = ["Wft:4:19", "Wft:4:20", "Wft:4:21"]


def _kifid_zorgplicht(d: Dict) -> bool:
    """Uitspraken over de zorgplicht: dat is waar een adviesdossier op wordt getoetst. Andere uitspraken zijn ruis."""
    return any("zorgplicht" in str(t).lower() for t in d.get("kifid_onderwerp_tags") or [])
RE_PROVISIE = re.compile(
    r"provisie|beloning|commissie|kickback|tegemoetkoming|\bvergoeding\b[^.\n]{0,40}\b(?:bank|verzekeraar|aanbieder|maatschappij)"
    r"|hypothe\w*|arbeidsongeschikt\w*|\baov\b|overlijdensrisico\w*|uitvaart\w*|betalingsbeschermer|premiepensioen\w*"
    r"|complex(?:e)? product", re.IGNORECASE)


def dossiercheck(dossiertekst: str) -> Dict:
    tekst, opmerkingen, afgekapt = _afkap(dossiertekst, "Het dossier")
    # De zoekvraag bestaat niet alleen uit de vaste zorgplichttermen: het dossier zelf bepaalt welke
    # productregels erbij horen (provisie, hypotheek, beleggingsverzekering).
    provisie = bool(RE_PROVISIE.search(tekst))
    grondslag = DOSSIER_ARTIKELEN + (PROVISIE_ARTIKELEN if provisie else [])
    ctx = _context("passend advies klantprofiel zorgplicht informatieverstrekking "
                   "kennis ervaring doelstelling risicobereidheid financiele positie " + _kernvraag(tekst, 600, 400, 0),
                   ["wetgeving", "kifid"], per_bron=3, min_rel=0.4, eigen=tekst[:800], grondslag=grondslag,
                   waar={"wetgeving": _wet_alleen(*(grondslag + DOSSIER_EXTRA + ["Wft:4:24"])),
                         "kifid": _kifid_zorgplicht})
    gebruiker = (
        f"ADVIESDOSSIER:\n---\n{tekst}\n---\n{afgekapt}\n"
        "Toets dit dossier tegen de zorgplicht- en adviesvereisten uit de bronnen.\n"
        "1. Welke verplichte elementen zijn AANWEZIG? Citeer waar je ze ziet.\n"
        "2. Welke ONTBREKEN? Dit is het belangrijkste deel.\n"
        "3. Welk concreet risico loopt de adviseur bij een klacht?\n"
        "Wees streng. Een ontbrekend element niet benoemen is erger dan te streng zijn.")
    return {"functie": "dossiercheck", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "opmerkingen": _meld(ctx, opmerkingen),
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 900}


# =============================================================== 7. polisvergelijker

# Waar een vergelijking om draait: wat niet is verzekerd en wat het eigen risico is, dan wat wel. Bij een variant met meer
# clausules dan het budget toelaat vallen de laatste weg, niet de uitsluitingen.
TYPE_VOLGORDE = ["uitsluiting", "eigen risico", "dekking", "verplichting verzekerde",
                 "schaderegeling", "verjaring"]


def _suggestie(tekst: str) -> str:
    """
    Bij een product dat het portaal niet herkent: het product uit het corpus dat er het meest op lijkt, of ''. Vergeleken
    wordt de stam vóór 'verzekering' ('inboedl' met 'inboedel'): het woord 'verzekering' zelf lijkt op alles.
    """
    import difflib
    stam = lambda w: re.sub(r"verz\w*$", "", w)
    stammen = {stam(_sleutel(p).split()[0]): p
               for p in {r.get("product") for r in CORPUS.data.get("polisvoorwaarden", []) if r.get("product")}}
    for w in _sleutel(tekst).split():
        t = stam(w)
        if len(t) >= 4:
            gevonden = difflib.get_close_matches(t, [k for k in stammen if k], n=1, cutoff=0.8)
            if gevonden:
                return stammen[gevonden[0]]
    return ""


def _kant(tekst: str, plaats: str = "Variant", budget: int = None) -> Dict:
    """
    Eén kant van de vergelijking: precies de clausules van het gekozen product, van de gekozen
    verzekeraar als er een genoemd is. Een vergelijking moet controleerbaar zijn: geen zoekscore die
    bepaalt wat er wel en niet naast elkaar komt te staan, en geen verzekeraar die stilzwijgend
    wordt vervangen door een andere.
    """
    budget = POLIS_BUDGET if budget is None else budget
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
        genoemd = h.get("meerdere_producten")
        kant["opmerking"] = (f"{plaats}: dit veld noemt meer dan één product ({' en '.join(genoemd)}); kies er één per variant."
                             if genoemd else f"{plaats}: dit past op meerdere producten; kies er één uit de lijst.")
        return kant
    if not h["product"]:
        if not (tekst or "").strip():
            kant["opmerking"] = f"{plaats}: dit veld is leeg; kies een product en verzekeraar."
        else:
            zo = _suggestie(tekst)
            kant["opmerking"] = (f"{plaats}: dit product staat niet in het corpus." + (f" Bedoelde je {zo}?" if zo else ""))
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
    # Eerst het soort clausule (uitsluitingen vooraan), dan de verzekeraar: een variant met twee verzekeraars laat er dan
    # geen helemaal wegvallen als het budget op is.
    mijn.sort(key=lambda r: (TYPE_VOLGORDE.index(r["type"]) if r.get("type") in TYPE_VOLGORDE else 99,
                             r.get("verzekeraar_of_bron") or "", r.get("clausule_id") or ""))
    getoond, gebruikt = [], 0
    for r in mijn:
        n = min(len(r.get("tekst") or ""), LIMIET_POLIS) + 120
        if getoond and gebruikt + n > budget:
            break
        getoond.append(r)
        gebruikt += n
    if len(getoond) < len(mijn):
        kant["opmerking"] = (kant["opmerking"] + " " if kant["opmerking"] else "") + \
            (f"{plaats}: {len(mijn)} clausules in het corpus; {len(getoond)} staan hier (uitsluitingen en eigen risico eerst). "
             "Wat hier niet staat, is niet vergeleken.")
    kant["rijen"] = getoond
    return kant


def _kantnaam(k: Dict) -> str:
    if k["product"]:
        return f"{k['product']} ({_kort(k['verzekeraar'])})" if k["verzekeraar"] else k["product"]
    return "een product dat het portaal niet herkent"


def polisvergelijker(product_a: str, product_b: str) -> Dict:
    """Verschilanalyse over echte clausules; het model beschrijft, het corpus levert."""
    # Twee kanten delen het budget van één opdracht: samen ongeveer anderhalf keer dat van een dekkingscheck.
    ka, kb = _kant(product_a, "Variant A", POLIS_BUDGET * 3 // 4), _kant(product_b, "Variant B", POLIS_BUDGET * 3 // 4)
    ra, rb = ka["rijen"], kb["rijen"]
    opmerkingen = [k["opmerking"] for k in (ka, kb) if k["opmerking"]]
    if ka["product"] and (ka["product"], ka["verzekeraar"]) == (kb["product"], kb["verzekeraar"]) and ra:
        opmerkingen.append("Variant A en B wijzen op hetzelfde product van dezelfde verzekeraar; er is niets te vergelijken.")
    docs = ra + rb
    rijen = lambda lst: [(0.0, d) for d in lst]
    naam_a, naam_b = _kantnaam(ka), _kantnaam(kb)
    blok = (f"=== VARIANT A: {naam_a} ===\n{_blok('polisvoorwaarden', rijen(ra)) or '(geen clausules in het corpus)'}\n\n"
            f"=== VARIANT B: {naam_b} ===\n{_blok('polisvoorwaarden', rijen(rb)) or '(geen clausules in het corpus)'}")
    gelijk = bool(ra) and (ka["product"], ka["verzekeraar"]) == (kb["product"], kb["verzekeraar"])
    if gelijk:
        vragen = (
            f"Variant A en variant B zijn hetzelfde: {naam_a}. Er valt niets te vergelijken. Zeg dat in één zin, "
            "verzin geen verschillen en beschrijf hooguit kort wat deze clausules regelen. Sluit af met de "
            "vervolgstap: kies voor variant B een ander product of een andere verzekeraar.\n")
    elif not ra or not rb:
        kant, leeg = ("B", "A") if ra else ("A", "B")
        vragen = (
            f"Alleen variant {kant} heeft clausules; variant {leeg} heeft er geen in het corpus. Vergelijken kan dus niet. "
            f"Zeg dat, beschrijf uitsluitend wat de clausules van variant {kant} regelen (met clausulenummers) en "
            f"zeg dat er over variant {leeg} niets te zeggen valt. Sluit af met de vervolgstap: kies voor variant "
            f"{leeg} een product en verzekeraar die in het corpus staan.\n")
    else:
        vragen = (
            f"Vergelijk variant A ({naam_a}) met variant B ({naam_b}) op basis van UITSLUITEND bovenstaande clausules.\n"
            "1. Waar verschillen de UITSLUITINGEN? Noem clausulenummers aan beide kanten.\n"
            "2. Welk concreet dekkingshiaat ontstaat er als een klant overstapt van A naar B?\n"
            "3. Welke vergelijking kun je NIET maken omdat de clausule aan een kant ontbreekt? "
            "Benoem dat expliciet in plaats van het gat te vullen.\n"
            "Uitsluitingen staan ook in dekkingsclausules. Zeg erbij dat dit een vergelijking is van de clausules "
            "hierboven en dat een sluitende vergelijking de volledige voorwaarden vraagt. Zeg over een ontbrekende clausule "
            "alleen dat die 'in de getoonde clausules' ontbreekt, nooit dat een product of verzekeraar 'geen clausule heeft'. "
            "Noem een bedrag of grens bij de clausule waar het staat.\n")
    gebruiker = vragen + "".join(f"Let op: {o}\n" for o in opmerkingen)
    bronnen = _bronlijst({"polisvoorwaarden": docs})
    for i, b in enumerate(bronnen):
        b["kant"] = "A" if i < len(ra) else "B"        # de UI toont beide varianten naast elkaar
    return {"functie": "polisvergelijker", "systeem": grounding.systeemprompt(blok),
            "gebruiker": gebruiker, "opgehaald": {"polisvoorwaarden": docs}, "opmerkingen": opmerkingen,
            "bronnen": bronnen, "berekening": None, "max_tokens": 800}


# =============================================================== 8. klachtroute

KLACHT_ARTIKELEN = ["Wft:4:17", "BGfo:39", "BGfo:40", "BGfo:41", "BGfo:42", "BGfo:43", "BGfo:44", "BGfo:57"]


def klachtroute(situatie: str, datum_klacht: str = "", intern_afgehandeld: bool = False,
                datum_bevestiging: str = "", peildatum: str = "", datum_verzoek: str = "",
                termijn_dagen: int = 0, datum_ontvangen: str = "") -> Dict:
    intern = _bool(intern_afgehandeld, "intern_afgehandeld")
    d_klacht, d_bev = _datum(datum_klacht, "datum_klacht"), _datum(datum_bevestiging, "datum_bevestiging")
    d_verzoek, d_ontv = _datum(datum_verzoek, "datum_verzoek"), _datum(datum_ontvangen, "datum_ontvangen")
    dagen = int(float(_getal(termijn_dagen, "termijn_dagen", 0, 365, " dagen"))) if str(termijn_dagen or "").strip() else 0
    if (d_bev or d_verzoek or d_ontv or dagen) and not d_klacht:
        raise ValueError("Vul ook de datum van de klacht in: de andere data zijn termijnen bij die klacht.")
    u = None
    if d_klacht:
        try:
            u = rk.klachttermijnen(d_klacht, d_bev, _datum(peildatum, "peildatum"), d_verzoek, dagen or None, d_ontv, intern)
        except ValueError as e:
            raise ValueError(str(e))
    # De kernartikelen over klachtafhandeling horen bij elke klachtroute; de situatie bepaalt welke
    # uitspraken erbij passen. Met een vaste zoekvraag kreeg elke casus dezelfde bronnen.
    # Alleen de wet. Geen enkele Kifid-uitspraak in het corpus gaat over ontvankelijkheid of procedure; de best scorende
    # (op 'afwijzing', 'termijn') zijn uitspraken over de inhoud van een geschil en horen bij de precedentzoeker.
    ctx = _context(f"{(situatie or '')[:600]} klachtenprocedure geschilleninstantie interne klachtafhandeling", ["wetgeving"],
                   per_bron=0, grondslag=KLACHT_ARTIKELEN + (u.grondslag if u else []), eigen=(situatie or "")[:600])
    termijnen = ""
    if u:
        termijnen = ("De termijnen zijn AL BEREKEND. Neem deze data letterlijk over en reken niets na:\n"
                     + _stappen_tekst(u) + f"\n{u.toelichting}\n"
                     + f"Waarschuwingen: {'; '.join(u.waarschuwingen) or 'geen'}\n"
                     + f"Vervolgstap uit de code: {u.volgende_stap}\n\n")
    gebruiker = (
        f"SITUATIE:\n{situatie}\n"
        f"Datum klacht: {datum_klacht or 'niet opgegeven'}\n"
        f"Interne klachtprocedure doorlopen: {'ja' if intern else 'nee'}\n\n{termijnen}"
        "Beschrijf op basis van de bronnen de route:\n"
        "1. Welke stap is nu aan de orde?\n"
        "2. Welke termijnen gelden en waar blijkt dat uit?\n"
        "3. Welke informatie moet mee bij indiening?\n"
        "Staat iets hiervan niet in de bronnen (een termijn, wat er mee moet bij indiening, hoe de geschilleninstantie "
        "werkt), zeg dan dat het niet in de geraadpleegde bronnen staat en noem het niet uit eigen kennis.")
    return {"functie": "klachtroute", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "tekst_uit_code": bool(u), "opmerkingen": _meld(ctx),
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict() if u else None, "max_tokens": 800}


# =============================================================== 9. afwijzingsanalyse

def afwijzingsanalyse(brieftekst: str) -> Dict:
    tekst, opmerkingen, afgekapt = _afkap(brieftekst, "De brief")
    polisfilter, meldingen, kort = _polisfilter(tekst)
    ctx = _context(_kernvraag(tekst) + " afwijzing dekking uitsluiting mededelingsplicht "
                   "opzet eigen gebrek", ["polisvoorwaarden", "kifid", "wetgeving"], per_bron=4, min_rel=0.4,
                   polis_alle=POLIS_BUDGET, polis_extra=_genoemde_clausules(tekst, polisfilter),
                   waar={"wetgeving": VERZEKERINGSRECHT, "polisvoorwaarden": polisfilter}, eigen=tekst[:600])
    opmerkingen = opmerkingen + meldingen
    gebruiker = (
        f"AFWIJZINGSBRIEF VAN DE VERZEKERAAR:\n---\n{tekst}\n---\n{afgekapt}\n"
        f"VERZEKERAAR IN DE BRIEF: {_van_wie(kort, ctx['opgehaald'].get('polisvoorwaarden', []))}\n\n"
        "Analyseer op basis van UITSLUITEND de bronnen:\n"
        "1. Op welke grond wijst de verzekeraar af? Citeer die grond uit de brief.\n"
        "2. Wordt die grond gedragen door een clausule of wetsartikel uit de bronnen? "
        "Zo nee, zeg dat - dat is het sterkste aanknopingspunt voor de adviseur.\n"
        "3. Welke tegenargumenten volgen uit de bronnen, met verwijzing?\n"
        "4. Welk bewijs moet de adviseur verzamelen?\n"
        "Overschat de zaak niet. Als de afwijzing terecht lijkt, zeg dat eerlijk.")
    return {"functie": "afwijzingsanalyse", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "opmerkingen": _meld(ctx, opmerkingen),
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 900}


# =============================================================== 10. adviesnotitie

def adviesnotitie(klantsituatie: str, advies: str) -> Dict:
    provisie = bool(RE_PROVISIE.search(f"{klantsituatie} {advies}"))
    grondslag = DOSSIER_ARTIKELEN + (PROVISIE_ARTIKELEN if provisie else [])
    ctx = _context("passend advies vastlegging dossier informatieverstrekking klantprofiel "
                   "motivering", ["wetgeving"], per_bron=2, min_rel=0.4, grondslag=grondslag, eigen="",
                   waar={"wetgeving": _wet_alleen(*(grondslag + DOSSIER_EXTRA))})
    gebruiker = (
        f"KLANTSITUATIE:\n{klantsituatie}\n\nGEGEVEN ADVIES:\n{advies}\n\n"
        "Stel een dossiernotitie op met de onderdelen die de bronnen als vaststelling of informatie aan de klant noemen. "
        "De bronnen bevatten geen vastleggings- of bewaarplicht voor adviesdossiers: noem er geen en zeg dat het niet "
        "in de geraadpleegde bronnen staat als je erover schrijft.\n"
        "Gebruik deze kopjes: Klantsituatie / Doelstelling en risicobereidheid / Overwogen "
        "alternatieven / Advies en motivering / Verstrekte informatie / Vervolgafspraken.\n"
        "Vul NIETS in wat de adviseur niet heeft aangeleverd. Zet bij ontbrekende informatie "
        "letterlijk: '[AAN TE VULLEN DOOR ADVISEUR]'. Een notitie met verzonnen klantgegevens "
        "is erger dan een notitie met gaten.")
    return {"functie": "adviesnotitie", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "opmerkingen": _meld(ctx),
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": None, "max_tokens": 800}


# =============================================================== 11. waardetoets

def waardetoets(nieuwwaarde: float, ouderdom_jaren: float, levensduur_jaren: float,
                drempel_pct: float = 40) -> Dict:
    _getal(nieuwwaarde, "nieuwwaarde")
    _getal(ouderdom_jaren, "ouderdom", 0, 1000)
    _getal(levensduur_jaren, "levensduur", 0, 1000)
    _getal(drempel_pct, "drempel_pct", 0, 100, "%")
    u = rk.nieuwwaarde_of_dagwaarde(nieuwwaarde, ouderdom_jaren, levensduur_jaren, drempel_pct)
    ctx = _context("nieuwwaarde dagwaarde afschrijving vervangingswaarde inboedel", ["polisvoorwaarden"], per_bron=3,
                   waar={"polisvoorwaarden": lambda d: d.get("type") == "schaderegeling"
                         and re.search(r"nieuwwaarde|dagwaarde", d.get("tekst") or "", re.I) is not None}, eigen="")
    gebruiker = (
        f"De waardebepaling is AL UITGEVOERD. Neem letterlijk over:\n"
        f"{_uitkomstregel('Uitkomst', u)} - {u.toelichting}\n"
        + _stappen_tekst(u) +
        f"\n{_uitleg_en_vervolg(u)}"
        f"Waarschuwingen: {'; '.join(u.waarschuwingen)}\n"
        f"VERZEKERAAR VAN DE KLANT: {_van_wie(None, ctx['opgehaald'].get('polisvoorwaarden', []))}\n\n"
        f"{HERSCHRIJF} Reken niets na.")
    return {"functie": "waardetoets", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "tekst_uit_code": True,
            "bronnen": _bronlijst(ctx["opgehaald"]), "berekening": u.to_dict(), "max_tokens": 600}


# =============================================================== 12. begripsuitleg

def begripsuitleg(begrip: str) -> Dict:
    # Een begrip van een paar woorden moet in elke bron die het toont ook echt voorkomen (dekking): zonder die eis vindt
    # 'Solvency II kapitaalvereisten voor verzekeraars' negen bronnen op het ene woord 'verzekeraar'. Een uitgeschreven vraag of
    # casus (meer dan zes woorden) heeft nooit alle woorden in één bron; die krijgt een strengere relatieve grens en minder bronnen.
    kort = len(set(tokenize(begrip))) <= 6
    ctx = _context(begrip, ["wetgeving", "polisvoorwaarden", "kifid"], per_bron=6 if kort else 4,
                   min_rel=0.35 if kort else 0.6, dekking=0.5 if kort else 0.0)
    gebruiker = (
        f"BEGRIP: {begrip}\n\n"
        "Leg dit begrip uit op basis van UITSLUITEND de bronnen. Polisclausules verschillen per verzekeraar: noem bij elke "
        "clausule van welke verzekeraar en welk product ze is, en presenteer er geen als algemene regel.\n"
        "1. Wat zegt de wettekst of clausule letterlijk? Citeer.\n"
        "2. Wat betekent dat in de praktijk voor een adviseur?\n"
        "3. Waar gaat het in de praktijk mis?\n"
        "Beantwoord alleen de onderdelen waarvoor de bronnen iets bevatten. Bij een onderdeel waarvoor ze niets bevatten "
        "(of komt het begrip helemaal niet in de bronnen voor) zeg je dat het niet in de geraadpleegde bronnen staat; "
        "leg NIETS uit uit eigen kennis.")
    return {"functie": "begripsuitleg", "systeem": grounding.systeemprompt(ctx["blok"]),
            "gebruiker": gebruiker, "opgehaald": ctx["opgehaald"], "opmerkingen": _meld(ctx),
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
