#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape_wetgeving.py — bouwt corpus/wetgeving.json uit de officiele BWB-bron.

Bronketen (volledig reproduceerbaar, geen hardcoded toestand-URLs):
  1. SRU-zoekdienst  https://zoekservice.overheid.nl/sru/Search  (x-connection=BWB)
     -> levert per BWB-id de locatie van het manifest.
  2. manifest.xml    https://repository.officiele-overheidspublicaties.nl/bwb/<BWB>/manifest.xml
     -> lijst van alle 'expressions' (toestanden) met inwerkingtreding + einddatum.
  3. toestand-XML    .../<BWB>/<expressie>/xml/<BWB>_<expressie>.xml
     -> de officiele, gestructureerde wettekst (schema toestand_2016-1.xsd).
  4. verificatie     https://wetten.overheid.nl/<BWB>/<datum>/0/<pad>/Artikel<nr>
     -> 302 met Location die op '#<anchor>' eindigt bewijst dat het artikel op die
        datum bestaat; een onbekend artikel redirect naar de kale regeling zonder anchor.

De letterlijke wettekst komt uitsluitend uit stap 3 (de XML), nooit uit HTML-scraping
en nooit uit modelkennis. Velden die niet in de bron staan worden null.

Gebruik:
    python3 scripts/scrape_wetgeving.py [--datum YYYY-MM-DD] [--out PAD] [--geen-verificatie]
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import lxml.etree as ET

SRU = "https://zoekservice.overheid.nl/sru/Search"
WETTEN = "https://wetten.overheid.nl"
UA = "Ai-assurantie-portaal/1.0 (corpusbouw; publieke BWB-bron)"

NS_SRU = {
    "srw": "http://www.loc.gov/zing/srw/",
    "gzd": "http://standaarden.overheid.nl/sru",
    "bwb": "http://standaarden.overheid.nl/bwb/terms/",
}

# ---------------------------------------------------------------- HTTP

def http_get(url, accept=None, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if accept:
        req.add_header("Accept", accept)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_no_redirect_opener = urllib.request.build_opener(NoRedirect)


def http_head_location(url, timeout=60):
    """Return (status, location_header) zonder de redirect te volgen."""
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with _no_redirect_opener.open(req, timeout=timeout) as r:
            return r.status, r.headers.get("Location")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location")


# ---------------------------------------------------------------- BWB ophalen

def sru_manifest_url(bwb_id):
    q = urllib.parse.urlencode({
        "version": "1.2",
        "operation": "searchRetrieve",
        "x-connection": "BWB",
        "query": f"dcterms.identifier=={bwb_id}",
        "maximumRecords": "1",
    })
    status, body = http_get(f"{SRU}?{q}", accept="application/xml")
    if status != 200:
        raise RuntimeError(f"SRU gaf HTTP {status} voor {bwb_id}")
    root = ET.fromstring(body)
    loc = root.find(".//bwb:locatie_manifest", namespaces=NS_SRU)
    if loc is None or not loc.text:
        raise RuntimeError(f"SRU leverde geen manifest-locatie voor {bwb_id}")
    return loc.text.strip()


def kies_toestand(manifest_xml, peildatum):
    """Selecteer de expressie die op peildatum in werking is."""
    root = ET.fromstring(manifest_xml)
    kandidaten = []
    for expr in root.findall("expression"):
        meta = expr.find("metadata")
        if meta is None:
            continue
        iw = meta.findtext("datum_inwerkingtreding")
        eind = meta.findtext("einddatum") or "9999-12-31"
        if not iw:
            continue
        if iw <= peildatum <= eind:
            items = [i.get("label") for m in expr.findall("manifestation")
                     if m.get("label") == "xml" for i in m.findall("item")]
            if items:
                kandidaten.append((iw, eind, expr.get("label"), items[0]))
    if not kandidaten:
        raise RuntimeError(f"Geen toestand gevonden die geldig is op {peildatum}")
    kandidaten.sort()
    return kandidaten[-1]  # laatst ingegane geldige toestand


def haal_toestand(bwb_id, peildatum):
    manifest_url = sru_manifest_url(bwb_id)
    status, manifest = http_get(manifest_url)
    if status != 200:
        raise RuntimeError(f"manifest HTTP {status}")
    iw, eind, label, item = kies_toestand(manifest, peildatum)
    base = manifest_url.rsplit("/", 1)[0]
    xml_url = f"{base}/{label}/xml/{item}"
    status, xml = http_get(xml_url)
    if status != 200:
        raise RuntimeError(f"toestand-XML HTTP {status}")
    return {
        "bwb_id": bwb_id,
        "inwerkingtreding": iw,
        "einddatum": eind,
        "expressie": label,
        "xml_url": xml_url,
        "manifest_url": manifest_url,
        "root": ET.fromstring(xml),
    }


# ---------------------------------------------------------------- XML -> tekst

SKIP_TAGS = {"meta-data", "kop", "noot", "redactie"}


def _norm(s):
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


def inline_text(el):
    parts = [el.text or ""]
    for ch in el:
        tag = ch.tag if isinstance(ch.tag, str) else ET.QName(ch).localname
        if tag not in SKIP_TAGS:
            parts.append(inline_text(ch))
        parts.append(ch.tail or "")
    return "".join(parts)


def block_lines(el, depth=0):
    lines = []
    for ch in el:
        tag = ch.tag if isinstance(ch.tag, str) else ET.QName(ch).localname
        if tag in SKIP_TAGS or tag in ("lidnr", "li.nr"):
            continue
        if tag == "al":
            t = _norm(inline_text(ch))
            if t:
                lines.append("  " * depth + t)
        elif tag == "lijst":
            for li in ch:
                ltag = li.tag if isinstance(li.tag, str) else ET.QName(li).localname
                if ltag != "li":
                    continue
                nr = _norm(li.findtext("li.nr") or "")
                sub = block_lines(li, depth + 1)
                if sub:
                    lines.append("  " * (depth + 1) + (nr + " " if nr else "") + sub[0].lstrip())
                    lines.extend(sub[1:])
                elif nr:
                    lines.append("  " * (depth + 1) + nr)
        elif tag == "table":
            # tabelonderschrift/-opschrift hoort bij de wettekst
            titel_el = ch.find("title")
            if titel_el is not None:
                t = _norm(inline_text(titel_el))
                if t:
                    lines.append("  " * depth + t)
            for row in ch.iter("row"):
                # lege cellen bewaren: die dragen betekenis (voortzetting van de
                # bovenliggende rij), weglaten zou de kolomindeling vervalsen
                cells = [_norm(inline_text(c)) for c in row.iter("entry")]
                if any(cells):
                    lines.append("  " * depth + " | ".join(cells))
        elif tag in ("lid", "artikel"):
            continue
        else:
            sub = block_lines(ch, depth)
            if sub:
                lines.extend(sub)
            else:
                t = _norm(inline_text(ch))
                if t:
                    lines.append("  " * depth + t)
    return lines


def artikel_nr(art):
    return _norm(art.findtext("kop/nr") or "") or None


def artikel_titel(art):
    kop = art.find("kop")
    if kop is None:
        return None
    tit = kop.find("titel")
    if tit is None:
        return None
    return _norm(inline_text(tit)) or None


def artikel_leden(art):
    lids = [c for c in art
            if (c.tag if isinstance(c.tag, str) else ET.QName(c).localname) == "lid"]
    if lids:
        leden = []
        for lid in lids:
            nr = _norm(lid.findtext("lidnr") or "")
            body = "\n".join(block_lines(lid)).strip()
            leden.append(f"{nr}. {body}" if nr else body)
        return leden, "\n".join(leden)
    return None, "\n".join(block_lines(art)).strip()


def structuurpad(art):
    """Opschriften van bovenliggende hoofdstukken/afdelingen/paragrafen."""
    out = []
    p = art.getparent()
    while p is not None:
        kop = p.find("kop")
        if kop is not None:
            lbl = f"{kop.findtext('label') or ''} {kop.findtext('nr') or ''}".strip()
            tit = kop.find("titel")
            t = _norm(inline_text(tit)) if tit is not None else None
            if lbl:
                out.append(f"{lbl} - {t}" if t else lbl)
        p = p.getparent()
    return list(reversed(out)) or None


def variabel_deel(art):
    return art.get("bwb-ng-variabel-deel")


def anchor(art):
    v = variabel_deel(art)
    return v.lstrip("/").replace("/", "_") if v else None


# ---------------------------------------------------------------- selectie

# (artikelnummer, onderwerp-label). Labels zijn onze eigen korte aanduiding;
# titel/tekst komen altijd letterlijk uit de bron.
SELECTIE = {
    "Wft": [
        ("4:9",   "vakbekwaamheid en geschiktheid"),
        ("4:10",  "betrouwbaarheid beleidsbepalers"),
        ("4:11",  "integere bedrijfsuitoefening"),
        ("4:15",  "beheerste en integere bedrijfsvoering"),
        ("4:16",  "uitbesteding van werkzaamheden"),
        ("4:17",  "klachtafhandeling en aansluiting geschilleninstantie"),
        ("4:19",  "informatieverstrekking: correct, duidelijk en niet misleidend"),
        ("4:20",  "informatieverstrekking voor, tijdens en na de overeenkomst"),
        ("4:21",  "informatieverstrekking bij tussenkomst van een bemiddelaar"),
        ("4:22",  "grondslag nadere regels informatieverstrekking (BGfo)"),
        ("4:22a", "wensen en behoeften bij verzekeringen"),
        ("4:23",  "passend advies / ken-uw-klant"),
        ("4:24",  "passendheidstoets bij dienstverlening zonder advies"),
        ("4:24a", "zorgplicht financiele dienstverlener"),
        ("4:25a", "grondslag beloningsregels en provisieverbod"),
        ("4:25b", "actieve provisie- en kostentransparantie"),
        ("4:26",  "meldingsplicht wijzigingen aan de AFM"),
    ],
    "BGfo": [
        ("5a",  "vakbekwaamheid medewerkers: nadere regels"),
        ("6",   "vakbekwaamheid financiele dienstverlener (uitwerking art. 4:9 lid 2 Wft)"),
        ("7",   "diplomaplicht adviseurs"),
        ("9",   "afgifte diploma en onderliggende modules"),
        ("11",  "bevoegdheid en geldigheid van het diploma"),
        ("39",  "reikwijdte interne klachtenprocedure"),
        ("40",  "interne klachtenprocedure"),
        ("41",  "klachtenadministratie"),
        ("42",  "informeren over geschilleninstantie bij afwijzing klacht"),
        ("43",  "afhandelingstermijn en bevestiging van klachten"),
        ("44",  "waarborgen voor zorgvuldige klachtbehandeling"),
        ("57",  "verplichte precontractuele informatie (o.a. aansluiting geschilleninstantie)"),
        ("86c", "provisieverbod complexe producten en impactvolle verzekeringen"),
        ("86d", "provisieregels schadeverzekeringen"),
        ("86f", "vergelijkingskaart bij producten onder het provisieverbod"),
        ("86i", "provisietransparantie bij schadeverzekeringen"),
        ("86k", "provisieregime contracten van voor invoering art. 86c"),
        ("86l", "afsluitprovisiebalans contracten van voor invoering art. 86c"),
        ("86m", "terugboeking provisie bij vroegtijdige beeindiging (oude contracten)"),
    ],
    "BW": [
        ("925", "definitie verzekeringsovereenkomst"),
        ("928", "mededelingsplicht van de verzekeringnemer bij het aangaan"),
        ("929", "gevolgen van niet-nakoming mededelingsplicht"),
        ("930", "uitkering bij schending mededelingsplicht"),
        ("940", "einde en opzegging van de overeenkomst"),
        ("941", "meldingsplicht bij verwezenlijking van het risico"),
        ("942", "verjaring van de rechtsvordering tegen de verzekeraar"),
        ("943", "dwingend recht bij consumentenverzekeringen"),
        ("944", "definitie schadeverzekering"),
        ("952", "opzet en roekeloosheid van de verzekerde"),
        ("954", "directe actie van de benadeelde"),
        ("955", "vergoeding beperkt tot de verzekerde som"),
        ("957", "bereddingsplicht en vergoeding van bereddingskosten"),
        ("958", "waarde van het verzekerd belang en onderverzekering"),
        ("959", "kosten van vaststelling van de schade"),
        ("960", "indemniteitsbeginsel: geen verrijking door uitkering"),
        ("961", "samenloop van verzekeringen"),
    ],
}

WETTEN_BRON = {
    "Wft": "BWBR0020368",
    "BGfo": "BWBR0020421",
    "BW": "BWBR0005290",          # Burgerlijk Wetboek Boek 7 (titel 17: verzekering)
}


# ---------------------------------------------------------------- verificatie

def verify_url(bwb_id, datum, var_deel, verwacht_anchor, pauze=0.4):
    """Controleer via een echte HTTP-call dat het artikel op deze datum bestaat.

    wetten.overheid.nl antwoordt op een artikelpad met 302. De Location bevat
    '#<anchor>' als het artikel bestaat, en alleen de kale regeling als niet.
    """
    pad = var_deel.lstrip("/")
    url = f"{WETTEN}/{bwb_id}/{datum}/0/{pad}"

    # wetten.overheid.nl reset de verbinding onder belasting. Een netwerkfout is GEEN
    # bewijs dat het artikel niet bestaat, dus die mag de verificatie niet stilzwijgend
    # laten falen en al helemaal niet de hele corpusbouw afbreken. We proberen opnieuw
    # met oplopende pauze en geven bij aanhoudende fout 'onbekend' terug (None), niet False.
    laatste = None
    for poging in range(4):
        try:
            status, loc = http_head_location(url)
            time.sleep(pauze)
            ok = status in (301, 302) and loc is not None and loc.endswith("#" + verwacht_anchor)
            return ok, status, loc, url
        except Exception as e:
            laatste = e
            time.sleep(1.5 * (2 ** poging))
    return None, f"netwerkfout: {type(laatste).__name__}", None, url


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datum", default=dt.date.today().isoformat(),
                    help="peildatum geldend recht (default: vandaag)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--geen-verificatie", action="store_true")
    args = ap.parse_args()

    hier = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(hier)
    out = args.out or os.path.join(root_dir, "corpus", "wetgeving.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    opgehaald_op = dt.date.today().isoformat()
    records, problemen, geverifieerd = [], [], 0

    for wet, artikelen in SELECTIE.items():
        bwb_id = WETTEN_BRON[wet]
        print(f"[{wet}] {bwb_id}: toestand ophalen voor {args.datum} ...", file=sys.stderr)
        toestand = haal_toestand(bwb_id, args.datum)
        print(f"[{wet}] toestand {toestand['expressie']} "
              f"(iwt {toestand['inwerkingtreding']}) <- {toestand['xml_url']}", file=sys.stderr)

        index = {}
        for a in toestand["root"].findall(".//artikel"):
            nr = artikel_nr(a)
            if nr and nr not in index:
                index[nr] = a

        geldig_op = toestand["inwerkingtreding"]

        for nr, onderwerp in artikelen:
            art = index.get(nr)
            if art is None:
                problemen.append(f"{wet} art. {nr}: niet aangetroffen in toestand "
                                 f"{toestand['expressie']}")
                continue
            leden, tekst = artikel_leden(art)
            if not tekst.strip():
                problemen.append(f"{wet} art. {nr}: lege tekst in bron (vervallen artikel?)")
                continue

            vd = variabel_deel(art)
            anc = anchor(art)
            bron_url = f"{WETTEN}/{bwb_id}/{geldig_op}#{anc}" if anc else \
                       f"{WETTEN}/{bwb_id}/{geldig_op}"

            verified = None
            if not args.geen_verificatie and vd and anc:
                ok, status, loc, vurl = verify_url(bwb_id, geldig_op, vd, anc)
                verified = ok            # True / False / None(=onbereikbaar)
                if ok is True:
                    geverifieerd += 1
                elif ok is None:
                    problemen.append(f"{wet} art. {nr}: verificatie onbereikbaar ({status}); "
                                     f"tekst komt uit de officiele XML en is wel opgenomen")
                else:
                    problemen.append(f"{wet} art. {nr}: verificatie faalde "
                                     f"(HTTP {status}, location={loc})")
                merk = {True: "OK", False: "FAIL", None: "ONBEREIKBAAR"}[ok]
                print(f"   art. {nr:6s} verify={merk}", file=sys.stderr)

            # BW-artikelen heten in de XML '942'; in de praktijk citeert men '7:942'.
            # We slaan de citeervorm op zodat de citeerbewaker dezelfde sleutel ziet
            # als de adviseur intypt.
            artikel_label = f"7:{nr}" if wet == "BW" else nr

            records.append({
                "wet": wet,
                "bwb_id": bwb_id,
                "artikel": artikel_label,
                "titel": artikel_titel(art),
                "tekst": tekst,
                "leden": leden,
                "onderwerp": onderwerp,
                "structuur": structuurpad(art),
                "geldig_op": geldig_op,
                "toestand_einddatum": (None if toestand["einddatum"] == "9999-12-31"
                                       else toestand["einddatum"]),
                "bron_url": bron_url,
                "bron_xml_url": toestand["xml_url"],
                "bron_verificatie_url": (f"{WETTEN}/{bwb_id}/{geldig_op}/0/{vd.lstrip('/')}"
                                         if vd else None),
                "bron_geverifieerd": verified,
                "opgehaald_op": opgehaald_op,
            })

    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n{len(records)} artikelen -> {out}", file=sys.stderr)
    print(f"{geverifieerd} bron-URLs met HTTP-verificatie bevestigd", file=sys.stderr)
    for p in problemen:
        print("PROBLEEM:", p, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
