#!/usr/bin/env python3
"""
Extractielogica voor Kifid-uitspraken (gescheiden van het ophalen, zodat de
regels los te testen/reviewen zijn).

Alles wordt afgeleid uit `pdfContent`: de volledige, door Kifid gepubliceerde
uitspraaktekst zoals die in de API-respons zit. Niets wordt geraden.

Belangrijk detail: de tekstextractie van Kifid's eigen PDF's levert de
kopregels in TWEE volgordes op (label-voor-waarde en waarde-voor-label):

  fwd:  "... Datum uitspraak 4 september 2026 ... Aard uitspraak Bindend advies
         Uitkomst Vordering afgewezen Bijlage ..."
  rev:  "... 25 juni 2026 Datum uitspraak ... Niet-bindend advies Aard uitspraak
         Vordering afgewezen Uitkomst Relevante bepalingen ... Bijlage ..."

Beide worden hieronder ondersteund; als de volgorde niet te bepalen is, blijft
het veld null.
"""
import datetime as dt
import html
import re

MAANDEN = {"januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5,
           "juni": 6, "juli": 7, "augustus": 8, "september": 9,
           "oktober": 10, "november": 11, "december": 12}
MND_RE = "|".join(MAANDEN)

# Rommel die de PDF-tekstextractie achterlaat: paginanummers en voetnoten.
_JUNK = re.compile(r"\s*\d{1,2}\s*/\s*\d{1,3}\s*$")


def norm(s):
    return " ".join(s.split()) if s else None


def strip_html(s):
    if not s:
        return None
    return norm(html.unescape(re.sub(r"<[^>]+>", " ", s))) or None


def ticks_to_date(ticks):
    try:
        return dt.datetime.utcfromtimestamp(
            int(ticks) / 10_000_000 - 62_135_596_800).date().isoformat()
    except Exception:
        return None


def detect_layout(pdf):
    if re.search(r"Aard\s+uitspraak\s+(?:Niet-)?[Bb]indend advies", pdf):
        return "fwd"
    if re.search(r"(?:Niet-)?[Bb]indend advies\s+Aard\s+uitspraak", pdf):
        return "rev"
    if re.search(r"Datum\s+uitspraak\s+\d{1,2}\s+(?:%s)\s+\d{4}" % MND_RE, pdf):
        return "fwd"
    if re.search(r"\d{1,2}\s+(?:%s)\s+\d{4}\s+Datum\s+uitspraak" % MND_RE, pdf):
        return "rev"
    return None


def get_aard(pdf, layout):
    m = None
    if layout == "fwd":
        m = re.search(r"Aard\s+uitspraak\s+((?:Niet-)?[Bb]indend advies)", pdf)
    elif layout == "rev":
        m = re.search(r"((?:Niet-)?[Bb]indend advies)\s+Aard\s+uitspraak", pdf)
    if not m:
        return None, None
    aard = norm(m.group(1))
    return aard, (not aard.lower().startswith("niet"))


def get_uitkomst(pdf, layout):
    """De door Kifid zelf in de kop gezette regel 'Uitkomst ...' (letterlijk)."""
    m = None
    if layout == "fwd":
        m = re.search(r"\bUitkomst\s+(.{3,160}?)\s*(?=Bijlage\b|Samenvatting\b|"
                      r"Relevante bepaling|\d\s*\.\s*Procedure\b|"
                      r"\d\s*\.\s*Het procesverloop\b)", pdf)
    elif layout == "rev":
        m = re.search(r"Aard\s+uitspraak\s+(.{3,160}?)\s+Uitkomst\b", pdf)
    if not m:
        return None
    t = norm(m.group(1))
    t = re.split(r"\s*Relevante bepaling", t)[0].strip()
    return t or None


def get_datum(pdf, layout, ticks):
    pat = r"(\d{1,2})\s+(%s)\s+(\d{4})" % MND_RE
    m = None
    if layout == "fwd":
        m = re.search(r"Datum\s+uitspraak\s+" + pat, pdf)
    elif layout == "rev":
        m = re.search(pat + r"\s+Datum\s+uitspraak", pdf)
    uit_tekst = None
    if m:
        try:
            uit_tekst = dt.date(int(m.group(3)), MAANDEN[m.group(2).lower()],
                                int(m.group(1))).isoformat()
        except ValueError:
            uit_tekst = None
    return uit_tekst, ticks_to_date(ticks)


def get_kern(pdf):
    """Kifid's eigen sectie waarin de klacht wordt samengevat."""
    for pat in (r"\b\d\s*\.\s*De kern\b\s*(.*?)(?=\b\d\s*\.\s*[A-Z])",
                r"\b\d\s*\.\s*Het geschil\b\s*(.*?)(?=\b\d\s*\.\s*[A-Z])",
                r"\b\d\s*\.\s*De klacht\b\s*(.*?)(?=\b\d\s*\.\s*[A-Z])",
                r"\bSamenvatting\b\s*(.*?)(?=\b\d\s*\.\s*(?:Procedure|"
                r"Het procesverloop|Procesverloop)\b)"):
        m = re.search(pat, pdf, re.S)
        if m:
            t = norm(m.group(1))
            if t and len(t) >= 60:
                return t[:1500]
    return None


def get_beslissing(pdf):
    m = re.search(r"(?:\b\d\s*\.\s*)?\bDe beslissing\b\s*(.*?)"
                  r"(?=Deze uitspraak is|Of u tegen deze uitspraak|"
                  r"Binnen 2 weken|Bij deze uitspraak|In artikel \d+ van het "
                  r"Reglement|U kunt|$)", pdf, re.S)
    if not m:
        m = re.search(r"\bBeslissing\b\s*(.*?)(?=Deze uitspraak is|"
                      r"Of u tegen deze uitspraak|Binnen 2 weken|"
                      r"In artikel \d+ van het Reglement|U kunt|$)", pdf, re.S)
    if not m:
        return None
    t = norm(m.group(1)) or ""
    # voetnootblokken en paginanummers die de PDF-extractie erin plakt
    t = re.split(r"\s+\d+\s+(?:Artikel|HR |Hoge Raad|Zie ook|Verordening|Dit volgt)", t)[0]
    t = _JUNK.sub("", t).strip()
    return t[:700] if len(t) > 10 else None


def get_conclusie(pdf):
    """Laatste 'Conclusie'-kopje vóór de beslissing = de dragende overweging."""
    best = None
    for m in re.finditer(r"\bConclusie\b\s*(.*?)"
                         r"(?=(?:\b\d\s*\.\s*)?\bDe beslissing\b|$)", pdf, re.S):
        t = norm(m.group(1)) or ""
        t = _JUNK.sub("", t).strip()
        if 60 < len(t) < 2500:
            best = t
    return best[:900] if best else None


def map_oordeel(uitkomst, beslissing):
    """
    Normaliseert naar gegrond / ongegrond / gedeeltelijk gegrond /
    niet-ontvankelijk. Retourneert (oordeel, herkomst).

    Regel 1 (sterkst): expliciete gegrond/ongegrond-formulering in DE BESLISSING.
    Regel 2: Kifid's eigen kopregel 'Uitkomst'.
    Regel 3: de beslissing luidt exact 'De commissie wijst de vordering(en) af.'
    Anders: None. Er wordt nooit gegokt.
    """
    b = (beslissing or "").lower()
    u = " ".join((uitkomst or "").lower().split()).strip(" .:")
    u = u.replace("vorderingen", "vordering")

    # 1. expliciete gegrond/ongegrond-formulering
    if re.search(r"klacht (?:is |wordt )?(?:deels|gedeeltelijk) gegrond", b) or \
       re.search(r"verklaart de klacht (?:deels|gedeeltelijk) gegrond", b):
        return "gedeeltelijk gegrond", "expliciet in beslissing"
    if re.search(r"klacht (?:is|wordt)? ?ongegrond", b) or \
       re.search(r"verklaart de klacht ongegrond", b):
        return "ongegrond", "expliciet in beslissing"
    if re.search(r"verklaart de klacht gegrond", b) or \
       re.search(r"\bklacht is gegrond\b", b):
        return "gegrond", "expliciet in beslissing"
    if re.fullmatch(r"de commissie verklaart de klacht niet[- ]behandelbaar\.?",
                    b.strip()) or \
       re.fullmatch(r"de commissie verklaart de consument niet[- ]ontvankelijk\.?",
                    b.strip()):
        return "niet-ontvankelijk", "expliciet in beslissing"

    # 2. Kifid's eigen kopregel 'Uitkomst'
    if u:
        if "niet-ontvankelijk" in u or "niet ontvankelijk" in u:
            return "niet-ontvankelijk", "kopregel Uitkomst"
        if "niet-behandelbaar" in u or "niet behandelbaar" in u:
            if "gedeeltelijk" in u or "deels" in u:
                return None, None
            return "niet-ontvankelijk", "kopregel Uitkomst"
        if u in ("vordering afgewezen", "vordering geheel afgewezen"):
            return "ongegrond", "kopregel Uitkomst"
        if u in ("vordering toegewezen", "vordering geheel toegewezen"):
            return "gegrond", "kopregel Uitkomst"
        if u in ("vordering gedeeltelijk toegewezen",
                 "vordering (gedeeltelijk) toegewezen",
                 "vordering deels toegewezen",
                 "vordering gedeeltelijk afgewezen"):
            return "gedeeltelijk gegrond", "kopregel Uitkomst"
        return None, None

    # 3. ondubbelzinnige beslissing zonder kopregel
    if re.fullmatch(r"de commissie wijst de vordering(?:en)?"
                    r"(?: van de consument)? af\.?", b.strip()):
        return "ongegrond", "letterlijke beslissing"
    return None, None


def extract(item, thema=None):
    pdf = item.get("pdfContent") or ""
    title = norm(item.get("title")) or ""
    if not pdf:
        return None

    m = re.search(r"(\d{4}-\d{3,5})", title) or \
        re.search(r"\bnr\.?\s*(\d{4}-\d{3,5})", pdf)
    if not m:
        return None
    nummer = m.group(1)

    layout = detect_layout(pdf)
    aard, bindend = get_aard(pdf, layout)
    if bindend is None and re.search(r"Deze uitspraak is bindend", pdf):
        bindend, aard = True, aard or "Deze uitspraak is bindend"
    uitkomst = get_uitkomst(pdf, layout)
    beslissing = get_beslissing(pdf)
    oordeel, herkomst = map_oordeel(uitkomst, beslissing)
    datum_tekst, datum_api = get_datum(pdf, layout, item.get("date"))
    conclusie = get_conclusie(pdf)
    kernoverweging = conclusie or beslissing
    kernoverweging_bron = ("Conclusie-paragraaf uit de uitspraak" if conclusie
                           else ("Sectie 'De beslissing' uit de uitspraak"
                                 if beslissing else None))

    return {
        "uitspraaknummer": nummer,
        "datum": datum_tekst or datum_api,
        "titel": title or None,
        "categorie": norm(item.get("category")),
        "kern_klacht": get_kern(pdf),
        "oordeel": oordeel,
        "bindend": bindend,
        "samenvatting": strip_html(item.get("summary")),
        "kernoverweging": kernoverweging,
        "kernoverweging_bron": kernoverweging_bron,
        "bron_url": item.get("url"),
        "opgehaald_op": dt.date.today().isoformat(),
        # --- verifieerbaarheid: letterlijke brontekst, geen interpretatie ---
        "uitkomst_letterlijk": uitkomst,
        "beslissing_letterlijk": beslissing,
        "aard_uitspraak_letterlijk": aard,
        "oordeel_herkomst": herkomst,
        "instantie": norm(item.get("authority")),
        "verweerder": norm(item.get("defendant")),
        "kifid_onderwerp_tags": [t.strip() for t in
                                 (item.get("judgementTags") or "").split(",")
                                 if t.strip()] or None,
        "pdf_url": item.get("statementLink"),
        "thema": thema,
        "datum_uit_uitspraaktekst": datum_tekst,
        "datum_uit_api": datum_api,
        "kop_layout": layout,
    }
