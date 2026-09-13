#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
polisvoorwaarden_lib.py - download + tekstextractie voor corpus/polisvoorwaarden.json

Kernprincipe: de clausuletekst wordt NOOIT met de hand ingetypt. Elke clausule
wordt uit de gedownloade PDF gesneden met een (begin, eind) marker-paar. Wordt
een marker niet gevonden of komt hij meerdere keren voor, dan faalt het script
luid. Zo kan er geen tekst in het corpus komen die niet letterlijk in de bron staat.
"""

import hashlib
import os
import re
import unicodedata
import urllib.request

import pypdf

UA = "Ai-assurantie-portaal/1.0 (corpusbouw polisvoorwaarden; publieke bronnen)"
CACHE = os.environ.get("PV_CACHE", "/tmp/pv_cache")


class BronFout(Exception):
    pass


# ---------------------------------------------------------------- HTTP

def fetch(url, timeout=180):
    """Haalt de URL op. Geeft (status, bytes). Alleen 200 is acceptabel."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        status = r.status
        data = r.read()
    if status != 200:
        raise BronFout(f"HTTP {status} voor {url}")
    return status, data


def fetch_pdf(url, use_cache=True):
    """Download PDF (met lokale cache) en controleer dat het echt een PDF is."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".pdf")
    if use_cache and os.path.exists(path) and os.path.getsize(path) > 1024:
        return path, None
    status, data = fetch(url)
    if not data.startswith(b"%PDF"):
        raise BronFout(f"Geen PDF-inhoud op {url} (begint met {data[:20]!r})")
    with open(path, "wb") as f:
        f.write(data)
    return path, status


def verify_200(url, timeout=120):
    """Losse verificatie dat de bron-URL 200 geeft (HEAD-achtig via GET, 1 byte)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1023"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            # 206 Partial Content telt als bewijs dat de resource bestaat; de
            # bronserver mag Range negeren en 200 sturen.
            return r.status in (200, 206), r.status
    except Exception as e:  # noqa: BLE001
        return False, repr(e)


# ---------------------------------------------------------------- tekst

# Regels die louter paginameubilair zijn en midden in een clausule kunnen vallen.
FURNITURE = [
    r"^\s*\d{1,3}\s*$",                                   # kaal paginanummer
    r"^\s*\*\s*Zie Begrippen\s*$",                        # Klaverblad voetnoot
    r"^\s*terug naar inhoud\s*>\s*$",                     # a.s.r.
    r"^\s*Voorwaarden arbeidsongeschiktheidsverzekering model \d+\s+\d+/\d+\s*$",
    r"^\s*Voorwaarden Woonverzekering\s*$",               # Univé
    r"^\s*Algemene voorwaarden\s*$",                      # Univé / Interpolis
    r"^\s*Pagina \d+/\d+\s*$",                            # Univé
    r"^\s*\d+ van\s?\d+ Verzekeringsvoorwaarden .*$",     # Interpolis
    r"^\s*\d+ van\s?\d+ Algemene voorwaarden .*$",        # Interpolis
    r"^\s*\d+\. (Wettelijke Aansprakelijkheid \(WA\)|Volledig Casco|Beperkt Casco)\s*$",
    r"^\s*°\s*$",                                         # Interpolis tabelglyph
]
FURNITURE_RE = [re.compile(p) for p in FURNITURE]


def clean_text(raw):
    """Normaliseert PDF-tekst zonder de bewoording te veranderen.

    - NFC-normalisatie en verwijderen van soft hyphens
    - herstellen van typografische afbreking aan regeleind (woord- \n woord)
    - verwijderen van paginameubilair (paginanummers, kop- en voetregels)
    - samentrekken van meervoudige spaties
    Woorden, leestekens en volgorde blijven ongewijzigd.
    """
    t = unicodedata.normalize("NFC", raw)
    t = t.replace("­", "").replace("﻿", "")
    # gesplitste losse letters die pypdf soms produceert in kopteksten
    t = t.replace("T errorisme", "Terrorisme").replace("T otale", "Totale")
    t = t.replace("T eruggevonden", "Teruggevonden")

    lines = []
    for line in t.split("\n"):
        if any(rx.match(line) for rx in FURNITURE_RE):
            continue
        lines.append(line.rstrip())
    t = "\n".join(lines)

    # afbreekstreepje aan regeleind herstellen: alleen letter-'-'-NL-letter
    t = re.sub(r"(?<=[a-zà-öø-ÿ])-\n(?=[a-zà-öø-ÿ])", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blok in iter(lambda: f.read(1 << 16), b""):
            h.update(blok)
    return h.hexdigest()


def pdf_text(path):
    reader = pypdf.PdfReader(path)
    raw = "\n".join((p.extract_text() or "") for p in reader.pages)
    return clean_text(raw)


def snijd(doctext, start, eind, bron_id=""):
    """Snijdt de letterlijke clausuletekst uit doctext.

    start en eind moeten ELK precies één keer voorkomen; anders is de locatie
    dubbelzinnig en faalt de extractie. eind is exclusief (het is het begin van
    het volgende element). eind=None betekent: tot einde document.
    """
    n_start = doctext.count(start)
    if n_start != 1:
        raise BronFout(f"[{bron_id}] startmarker {start!r} komt {n_start}x voor (moet 1x)")
    i = doctext.index(start)
    if eind is None:
        j = len(doctext)
    else:
        n_eind = doctext.count(eind)
        if n_eind != 1:
            raise BronFout(f"[{bron_id}] eindmarker {eind!r} komt {n_eind}x voor (moet 1x)")
        j = doctext.index(eind)
        if j <= i:
            raise BronFout(f"[{bron_id}] eindmarker ligt voor startmarker")
    stuk = doctext[i:j]
    # losse regels binnen een alinea samenvoegen; lijstopsommingen behouden
    stuk = re.sub(r"\n(?![•\-•]|\s*[a-z]\.\s|\s*\d+\.\s)", " ", stuk)
    stuk = re.sub(r"[ \t]+", " ", stuk)
    stuk = re.sub(r" *\n *", "\n", stuk)
    return stuk.strip()


# ---------------------------------------------------------------- body / markers

TOC_LINE = re.compile(r"\S.*\s\d{1,3}\s*$")


def strip_toc(text, scan_lines=220):
    """Verwijdert de inhoudsopgave.

    De inhoudsopgave laat elke regel eindigen op een paginanummer. We zoeken de
    laatste zulke regel binnen de eerste `scan_lines` regels en gooien alles
    daarvoor weg. Zonder deze stap komt elke koptekst twee keer voor (een keer
    in de inhoudsopgave, een keer in de tekst) en is geen enkele marker uniek.
    """
    lines = text.split("\n")
    last = None
    for i, line in enumerate(lines[:scan_lines]):
        if len(line.strip()) > 15 and TOC_LINE.match(line.strip()):
            last = i
    if last is None:
        return text
    body = "\n".join(lines[last + 1:])
    if len(body) < 0.5 * len(text):
        raise BronFout("inhoudsopgave-detectie verwijdert te veel tekst")
    return body


def flatten(text):
    """Geeft (platte tekst, indexkaart). Elke witruimtereeks wordt een spatie.

    Zo kunnen markers als gewone zinnen worden opgeschreven, ongeacht waar de
    PDF-regelafbreking valt. idx[k] is de positie van flat[k] in de brontekst.
    """
    out, idx = [], []
    i, n = 0, len(text)
    prev_space = True
    while i < n:
        ch = text[i]
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                idx.append(i)
                prev_space = True
            i += 1
            continue
        out.append(ch)
        idx.append(i)
        prev_space = False
        i += 1
    return "".join(out), idx


def norm_marker(m):
    return re.sub(r"\s+", " ", m).strip()


def knip(doctext, start, eind, bron_id="", kap=None):
    """Snijdt de letterlijke clausuletekst uit doctext op basis van markers.

    Beide markers moeten na normalisatie van witruimte precies een keer in de
    brontekst voorkomen. Anders is de plaats dubbelzinnig en faalt de extractie.
    """
    flat, idx = flatten(doctext)
    s, e = norm_marker(start), norm_marker(eind) if eind else None

    ns = flat.count(s)
    if ns != 1:
        raise BronFout(f"[{bron_id}] startmarker komt {ns}x voor (moet 1x): {s[:70]!r}")
    a = flat.index(s)
    if e is None:
        b = len(flat)
    else:
        ne = flat.count(e)
        if ne != 1:
            raise BronFout(f"[{bron_id}] eindmarker komt {ne}x voor (moet 1x): {e[:70]!r}")
        b = flat.index(e)
        if b <= a:
            raise BronFout(f"[{bron_id}] eindmarker ligt voor startmarker")

    stuk = herstel_alinea(doctext[idx[a]: idx[b - 1] + 1])
    if kap:
        # Sommige clausules moeten met een unieke, langere marker worden
        # aangesneden. `kap` knipt die aanloop (meestal het kopje zelf, dat
        # apart in het veld "kop" staat) er weer af. Er wordt niets herschreven.
        k = norm_marker(kap)
        if not norm_marker(stuk).startswith(k):
            raise BronFout(f"[{bron_id}] kap-prefix niet gevonden aan het begin")
        flat2, idx2 = flatten(stuk)
        stuk = stuk[idx2[len(k)]:].lstrip()
    return stuk


NIEUWE_REGEL = re.compile(r"^(?:[•·–]|-\s|[a-z]\.\s|\d+\.\s|\d+(?:\.\d+)+\s|Artikel \d+)")


def herstel_alinea(stuk):
    """Voegt PDF-regelafbrekingen binnen een alinea samen.

    Regels die een nieuw opsommings- of lidnummer beginnen blijven op een eigen
    regel staan. Er worden geen woorden gewijzigd, alleen witruimte.
    """
    regels = [r.strip() for r in stuk.split("\n")]
    uit = []
    for r in regels:
        if not r:
            continue
        if uit and not NIEUWE_REGEL.match(r):
            uit[-1] = uit[-1] + " " + r
        else:
            uit.append(r)
    uit = [re.sub(r"[ \t]+", " ", r).strip() for r in uit]
    return "\n".join(uit).strip()
