#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blind_ab.py - Blinde A/B-harnas voor visuele beoordeling van interfaceschermen.

Doel
----
Onze eigen schermen naast echte comps leggen en ze laten beoordelen ZONDER dat
de beoordelaar kan zien welk scherm van wie is. Alles wat identiteit verraadt
wordt weggehaald; alleen layout, typografie, ritme en informatiehierarchie
blijven over.

Pijplijn per afbeelding
-----------------------
1. browser-chrome wegsnijden (bovenrand)          -> detecteer_browser_chrome()
2. cookiebanner-rest wegsnijden (onderrand)       -> detecteer_bodembanner()
3. hoogte begrenzen (gelijke 'leeslengte')        -> --max-hoogte-ratio
4. schalen naar identieke breedte                 -> --breedte
5. merkidentiteit maskeren (logo-regio's)         -> maskeer_merkregios()
6. merkkleur neutraliseren (grijs, contrast heel) -> naar_neutraal_grijs()
7. contrast normaliseren                          -> --contrast
8. opslaan als A.png / B.png / ... zonder metadata

Daarna:
- volgorde per ronde willekeurig (seed vastgelegd)
- labels A, B, C, ... ; bestandsnamen verraden niets
- mapping label -> bron in APART sleutelbestand buiten de beoordelingsmap
- optioneel bestandsgrootte-maskering (alle PNG's exact even groot)

Gebruik
-------
  python3 scripts/blind_ab.py \
      --comps renders/comps renders/comps_nl \
      --ours  renders/ours \
      --decoy renders/decoy \
      --uit   renders/ab \
      --ronde ronde1 --seed 7

  python3 scripts/blind_ab.py --zelftest      # controleert de neutralisatie

De beoordelaar krijgt UITSLUITEND renders/ab/<ronde>/<viewport>/.
NOOIT renders/ab/_sleutel.json.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import random
import re
import shutil
import struct
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageFilter, ImageOps

Image.MAX_IMAGE_PIXELS = None  # full-page screenshots zijn legitiem enorm

SCRIPT_VERSIE = "1.0.0"
PROJECT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Woorden die NOOIT in een beoordelingsbestandsnaam mogen voorkomen.
# ---------------------------------------------------------------------------
VERBODEN_IN_NAAM = (
    "ours", "onze", "eigen", "portaal", "assurantie", "artifation", "decoy",
    "comp", "stripe", "linear", "vercel", "attio", "mercury", "ramp", "retool",
    "metabase", "grafana", "notion", "resend", "dub", "cal", "anwb", "asr",
    "interpolis", "klaverblad", "kifid", "kvk", "digid", "moneybird", "exact",
    "belastingdienst", "pricewise", "poliswijzer", "overstappen", "geld",
    "mijnoverheid", "mijnpensioenoverzicht", "verzekering", "eboekhouden",
)


# ---------------------------------------------------------------------------
# Datamodel
# ---------------------------------------------------------------------------
@dataclass
class Bron:
    pad: Path
    set_naam: str            # 'comps', 'comps_nl', 'ours', 'decoy'
    soort: str               # 'comp' | 'ours' | 'decoy'
    bron_naam: str           # leesbare naam, alleen voor de sleutel
    viewport: str            # 'desktop' | 'mobile' | 'onbekend'
    omschrijving: str = ""


@dataclass
class NeutralisatieLog:
    origineel_formaat: tuple[int, int] = (0, 0)
    chrome_afgesneden_px: int = 0
    chrome_reden: str = ""
    bodembanner_afgesneden_px: int = 0
    bodembanner_reden: str = ""
    hoogte_begrensd_px: int = 0
    geschaald_naar: tuple[int, int] = (0, 0)
    headerhoogte_px: int = 0
    gemaskeerde_regios: list[dict] = field(default_factory=list)
    grijs_methode: str = ""
    contrast_methode: str = ""
    eind_formaat: tuple[int, int] = (0, 0)


# ---------------------------------------------------------------------------
# 0. Inlezen / classificeren
# ---------------------------------------------------------------------------
def bepaal_viewport(naam: str) -> str:
    n = naam.lower()
    if "mobile" in n or re.search(r"[_-]390(?:[x_.-]|$)", n):
        return "mobile"
    if "desktop" in n or re.search(r"[_-]1440(?:[x_.-]|$)", n):
        return "desktop"
    return "onbekend"


def _lees_manifest(map_pad: Path) -> dict[str, dict[str, str]]:
    """Bestandsnaam -> {bron_naam, omschrijving}. Werkt voor beide manifest-vormen."""
    mf = map_pad / "manifest.json"
    uit: dict[str, dict[str, str]] = {}
    if not mf.exists():
        return uit
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return uit

    if isinstance(data, list):                       # renders/comps-vorm
        for e in data:
            best = e.get("bestand")
            if best:
                uit[best] = {
                    "bron_naam": e.get("bron_naam") or e.get("id") or "?",
                    "omschrijving": e.get("wat_het_toont", ""),
                }
    elif isinstance(data, dict):                     # renders/comps_nl-vorm
        for c in data.get("comps", []):
            naam = c.get("naam") or c.get("slug") or "?"
            oms = c.get("interface_elementen", "")
            for _vp, b in (c.get("bestanden") or {}).items():
                best = b.get("file") if isinstance(b, dict) else b
                if best:
                    uit[best] = {"bron_naam": naam, "omschrijving": oms}
    return uit


def verzamel_bronnen(mappen: Iterable[Path], soort: str) -> list[Bron]:
    bronnen: list[Bron] = []
    for m in mappen:
        m = Path(m)
        if not m.exists():
            continue
        manifest = _lees_manifest(m)
        for p in sorted(m.glob("*.png")) + sorted(m.glob("*.jpg")) + sorted(m.glob("*.jpeg")):
            meta = manifest.get(p.name, {})
            bronnen.append(Bron(
                pad=p,
                set_naam=m.name,
                soort=soort,
                bron_naam=meta.get("bron_naam") or p.stem,
                viewport=bepaal_viewport(p.name),
                omschrijving=meta.get("omschrijving", ""),
            ))
    return bronnen


# ---------------------------------------------------------------------------
# 1/2. Randdetectie: browser-chrome boven, cookiebanner-rest onder
# ---------------------------------------------------------------------------
def _rijprofiel(img: Image.Image, breedte: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """Per beeldrij: gemiddelde helderheid en spreiding (op een smalle miniatuur)."""
    klein = img.convert("L").resize((breedte, img.height), Image.BILINEAR)
    a = np.asarray(klein, dtype=np.float32)
    return a.mean(axis=1), a.std(axis=1)


def _bandstatistiek(img: Image.Image, y0: int, y1: int) -> dict:
    strook = img.crop((0, y0, img.width, y1))
    klein = strook.resize((96, max(1, min(strook.height, 400))), Image.BILINEAR)
    _L, chroma = _naar_lab(np.asarray(klein.convert("RGB")))
    gem, sp = _rijprofiel(strook)
    return {
        "chroma_gem": float(chroma.mean()),
        "lum_gem": float(gem.mean()),
        "spreiding_gem": float(sp.mean()),
        "vlak_aandeel": float((sp < 6.0).mean()),
    }


def _heeft_adresbalk(img: Image.Image, r: int) -> tuple[bool, str]:
    """
    Zoekt in de balk 0..r naar het enige echt kenmerkende onderdeel van browser-
    chrome: een LICHTE, links-ingesprongen adresbalk met over vele beeldrijen een
    STABIELE linker- en rechterrand, die bovendien LICHTER is dan wat er direct
    boven staat (de pil ligt op de werkbalk).

    Die laatste eis is wat sitekoppen wegfiltert: daar is de 'lichte strook' juist
    de witte achtergrond tussen logo en navigatie, met alleen maar wit erboven.
    """
    kol = 192
    band = img.crop((0, 0, img.width, r)).convert("L").resize((kol, r), Image.BILINEAR)
    a = np.asarray(band, dtype=np.float32)
    y0 = r // 2

    rijen: list[tuple[int, int] | None] = []
    for y in range(y0, r):
        rij = a[y]
        # 25e percentiel, niet de mediaan: een brede adresbalk kan meer dan de
        # helft van de rij beslaan en zou dan zelf de mediaan worden
        basis = float(np.percentile(rij, 25))
        idx = np.flatnonzero(rij > basis + 8.0)
        if idx.size == 0:
            rijen.append(None)
            continue
        segmenten = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
        seg = max(segmenten, key=len)
        links, rechts, breedte = seg[0] / kol, seg[-1] / kol, len(seg) / kol
        # een adresbalk begint linksvoor (na de navigatieknoppen) en loopt niet
        # tot de rand; een zoekpil in een sitekop staat juist rechts van het midden
        if breedte >= 0.30 and 0.015 < links < 0.25 and rechts < 0.95:
            rijen.append((int(seg[0]), int(seg[-1])))
        else:
            rijen.append(None)

    groep: list[tuple[int, int]] = []
    start_y = 0
    for i, rij in enumerate(rijen + [None]):
        if rij is not None:
            if not groep:
                start_y = y0 + i
            groep.append(rij)
            continue
        # de pil moet een geloofwaardig deel van de balkhoogte beslaan: te dun is
        # een dividerlijn of een zoekveldje in een sitebalk, te dik is geen pil
        if len(groep) >= 12 and 0.15 <= len(groep) / max(1, r) <= 0.55:
            l = np.array([g[0] for g in groep], dtype=np.float32)
            rr = np.array([g[1] for g in groep], dtype=np.float32)
            if (l / kol).std() < 0.02 and (rr / kol).std() < 0.03:
                c0, c1 = int(np.median(l)), int(np.median(rr)) + 1
                pil = float(a[start_y:start_y + len(groep), c0:c1].mean())
                bo = max(0, start_y - 6)
                boven = float(a[bo:start_y, c0:c1].mean()) if start_y > bo else 255.0
                if pil > boven + 8.0:
                    return True, (f"adresbalk herkend: {len(groep)} rijen, stabiele "
                                  f"randen, {pil - boven:.0f} lichter dan de werkbalk")
        groep = []
    return False, "geen adresbalk in de balk"


def detecteer_browser_chrome(img: Image.Image,
                             min_px: int = 80,
                             max_px: int = 300) -> tuple[int, str]:
    """
    Snijdt de bovenrand weg als daar BROWSER-CHROME staat (tabbalk + adresbalk).

    BEWUST STRENG. Een soepele variant sneed bij echte sites tot 2000 px weg -
    complete hero-secties - omdat een donkere sitekop ook 'een vlakke balk met
    een harde rand' is. Alles hieronder moet kloppen voordat er iets afgaat:

      1. grens tussen 80 en 300 px (realistische chromehoogte, 1x tot 2x)
      2. de balk is NEUTRAAL grijs (gemiddelde chroma < 3); een sitekop in
         huisstijlkleur valt daarmee af
      3. de balk is overwegend vlak (>= 55% van de rijen nagenoeg effen)
      4. er staat een zichtbare helderheidsstap op de grens
      5. onder de grens zit meer structuur dan erboven (daar begint de pagina)
      6. de balk bevat een herkenbare ADRESBALK - dit is de doorslaggevende eis;
         zonder adresbalk is het geen browser maar gewoon een sitekop

    Gevalideerd: 0 vals alarm op alle 82 aanwezige opnames, wel herkenning op een
    nagebootste browseropname. Retourneert (aantal_px, reden).
    """
    h, w = img.height, img.width
    if h < max_px + 240 or w < 200:
        return 0, "beeld te klein voor chromedetectie"

    gem, sp = _rijprofiel(img)
    beste = (0, 0.0, "")
    for r in range(min_px, min(max_px, h - 220)):
        stap = abs(float(gem[max(0, r - 3)]) - float(gem[min(r + 3, h - 1)]))
        if stap < 6.0:
            continue
        boven = _bandstatistiek(img, 0, r)
        if boven["chroma_gem"] >= 3.0 or boven["vlak_aandeel"] < 0.55:
            continue
        onder = _bandstatistiek(img, r, min(h, r + 200))
        if onder["spreiding_gem"] <= boven["spreiding_gem"] + 4.0:
            continue
        ok, waarom = _heeft_adresbalk(img, r)
        if not ok:
            continue
        # eerste geldige grens = de echte onderkant van de chrome; een latere
        # grens zou een strook paginainhoud meenemen
        beste = (r, stap, (f"browser-chrome tot rij {r}: {waarom}, "
                               f"chroma {boven['chroma_gem']:.1f}, "
                               f"vlak {boven['vlak_aandeel']:.0%}, stap {stap:.0f}"))
        break
    if beste[0]:
        return beste[0], beste[2]
    return 0, "geen browser-chrome aangetroffen (opname lijkt chroomloos)"


def detecteer_bodembanner(img: Image.Image,
                          min_px: int = 40,
                          max_fractie: float = 0.15) -> tuple[int, str]:
    """
    Snijdt aan de ONDERRAND een strook weg die geen inhoud is: een achtergebleven
    cookiebanner-/overlayvlak of lege ruimte onder de pagina.

    BEWUST STRENG, om dezelfde reden als bij de chromedetectie: een soepele versie
    sneed bij 59 van de 82 aanwezige opnames de footer weg - tot 20% van de
    pagina. Een footer heeft tekst, kolommen en links en is dus nooit effen. Er
    gaat pas iets af als de strook praktisch EEN KLEUR is:

      - hoogstens 15% van de paginahoogte, minimaal 40 px
      - 97% van de pixels ligt binnen +/-4 helderheidsniveaus van de mediaan
      - vrijwel geen rijstructuur (spreiding < 3)
      - een duidelijke helderheidsstap (>= 20) ten opzichte van wat erboven staat

    Of dat vlak nu een bannerrest is of gewoon lege ruimte maakt niet uit: in
    beide gevallen is het geen ontwerp en hoort het niet meegewogen te worden.
    """
    h = img.height
    venster = max(min_px + 8, int(h * max_fractie))
    if h < venster + 80:
        return 0, "beeld te kort voor bodemdetectie"
    gem, spreiding = _rijprofiel(img)
    grijs = img.convert("L")
    start = h - venster

    beste, beste_score, beste_reden = 0, 0.0, ""
    for r in range(start, h - min_px, 2):
        if float(spreiding[r:].mean()) >= 3.0:
            continue
        band_gem = float(gem[r:].mean())
        boven_gem = float(gem[max(0, r - 80):r].mean())
        stap = abs(band_gem - boven_gem)
        if stap < 20.0:
            continue
        strook = np.asarray(grijs.crop((0, r, img.width, h)).resize(
            (96, min(h - r, 400)), Image.BILINEAR), dtype=np.float32)
        mediaan = float(np.median(strook))
        uniform = float((np.abs(strook - mediaan) <= 4.0).mean())
        if uniform < 0.97:
            continue
        score = stap * uniform
        if score > beste_score:
            beste, beste_score = r, score
            beste_reden = (f"effen strook vanaf rij {r} ({uniform:.0%} van de pixels "
                           f"in een kleur, stap {stap:.0f}) - geen inhoud")
    if beste:
        return h - beste, beste_reden
    return 0, "geen effen bodemstrook aangetroffen"


# ---------------------------------------------------------------------------
# 5. Merkidentiteit maskeren
# ---------------------------------------------------------------------------
def detecteer_headerhoogte(img: Image.Image, max_px: int) -> int:
    """
    Onderkant van de merkbalk: de eerste harde horizontale scheiding vanaf boven.

    Streng begrensd op max_px. Zonder die grens pakt de detectie de scheiding
    onder de navigatie, de kruimelpaden of zelfs onder de paginatitel - en dan
    maskeer je de KOPTEKST weg, precies de typografie die beoordeeld moet worden.
    """
    grens = max(24, min(max_px, img.height - 1))
    gem, _ = _rijprofiel(img)
    gem = gem[:grens]
    if len(gem) < 24:
        return min(max_px, img.height)
    verschil = np.abs(np.diff(gem))
    zone = verschil[16:]
    if len(zone) and float(zone.max()) > 8.0:
        return max(32, min(int(np.argmax(zone)) + 18, grens))
    return grens


def _pixeleer(img: Image.Image, kader: tuple[int, int, int, int], blok: int = 14) -> None:
    """Regio onherkenbaar maken maar wel 'bezet' houden: blokjes + lichte blur."""
    x0, y0, x1, y1 = kader
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.width, x1), min(img.height, y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    regio = img.crop((x0, y0, x1, y1))
    kw = max(1, (x1 - x0) // blok)
    kh = max(1, (y1 - y0) // blok)
    regio = regio.resize((kw, kh), Image.BILINEAR).resize((x1 - x0, y1 - y0), Image.NEAREST)
    regio = regio.filter(ImageFilter.GaussianBlur(1.2))
    img.paste(regio, (x0, y0))


def maskeer_merkregios(img: Image.Image, viewport: str,
                       maskeer_footer: bool = False,
                       merkbalk_hoogte: int | None = None,
                       extra: list[list[float]] | None = None) -> tuple[int, list[dict]]:
    """
    Maskeert de plekken waar merkidentiteit vrijwel altijd zit:
      - linksboven in de merkbalk (woordmerk/logo)
      - rechtsboven in de merkbalk (accountmerk, taalkiezer, merkknoppen)
    Optioneel de footer-linkerhoek, en handmatig opgegeven extra rechthoeken.

    De maskerhoogte is VAST op 8% van de beeldbreedte (circa 115 css px), niet
    gedetecteerd. Automatische detectie van 'de onderkant van de header' faalt
    twee kanten op: bij een dunne meldingsbalk bovenaan stopt het masker te vroeg
    en blijft het logo eronder gewoon staan, en bij een sitekop zonder scheiding
    loopt het door tot over de paginatitel - precies de typografie die beoordeeld
    moet worden. Een vaste, ruime maar begrensde band is voorspelbaarder.
    """
    header_h = merkbalk_hoogte or max(40, int(img.width * 0.08))
    header_h = min(header_h, max(1, img.height))
    w = img.width
    regios: list[dict] = []

    kaders = [
        ("merkbalk-links", (0, 0, int(w * 0.30), header_h)),
        ("merkbalk-rechts", (int(w * 0.74), 0, w, header_h)),
    ]
    if maskeer_footer:
        fy0 = int(img.height * 0.92)
        kaders.append(("footer-links", (0, fy0, int(w * 0.34), img.height)))
    for i, rel in enumerate(extra or []):
        x0, y0, x1, y1 = rel
        kaders.append((f"extra-{i}", (int(x0 * w), int(y0 * img.height),
                                      int(x1 * w), int(y1 * img.height))))

    for naam, kader in kaders:
        _pixeleer(img, kader)
        regios.append({"naam": naam, "kader": list(kader)})
    return header_h, regios


# ---------------------------------------------------------------------------
# 6. Merkkleur neutraliseren
# ---------------------------------------------------------------------------
def _naar_lab(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    sRGB (uint8) -> (L*, chroma). Eigen implementatie: PIL's LAB-conversie geeft
    afhankelijk van de toegangsweg (split() vs. asarray) een andere offset voor
    a/b, en daar wil je geen meetlat op bouwen.
    """
    x = rgb.astype(np.float32) / 255.0
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    # sRGB D65 -> XYZ
    X = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    Y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    Z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    X /= 0.95047; Z /= 1.08883                      # D65 witpunt
    d = 6.0 / 29.0

    def f(t):
        return np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4.0 / 29.0)

    fx, fy, fz = f(X), f(Y), f(Z)
    L = 116.0 * fy - 16.0                           # 0..100
    a = 500.0 * (fx - fy)
    bb = 200.0 * (fy - fz)
    return L, np.sqrt(a * a + bb * bb)


def naar_neutraal_grijs(img: Image.Image, chroma_winst: float = 0.5,
                        sigma: float = 1.6) -> tuple[Image.Image, str]:
    """
    Grijswaarden op basis van CIE-L* (waarneembare lichtheid). Kleurranden tussen
    tinten met GELIJKE lichtheid (denk: merkblauwe knop op een grijze balk) zouden
    dan verdwijnen; daarom wordt de RAND van het chromaveld als donkere haarlijn
    teruggelegd. Structuur en contrast blijven zo overeind, terwijl de kleur zelf -
    en dus 'welk blauw is mooier' - volledig weg is.
    """
    arr = np.asarray(img.convert("RGB"))
    L, chroma = _naar_lab(arr)

    ch8 = Image.fromarray(np.clip(chroma * 2.0, 0, 255).astype(np.uint8), mode="L")
    ch_blur = np.asarray(ch8.filter(ImageFilter.GaussianBlur(sigma)), dtype=np.float32)
    randen = np.abs(np.asarray(ch8, dtype=np.float32) - ch_blur)   # alleen chroma-RANDEN

    grijs = np.clip(L * 2.55 - chroma_winst * randen, 0, 255).astype(np.uint8)
    return Image.fromarray(grijs, mode="L"), (
        f"CIE-L* (eigen sRGB->Lab) met chroma-randlijnen "
        f"(winst {chroma_winst}, sigma {sigma})"
    )


def pas_contrast_toe(img: Image.Image, methode: str) -> tuple[Image.Image, str]:
    if methode == "uit":
        return img, "geen"
    if methode == "hard":
        return ImageOps.equalize(img), "histogram-egalisatie"
    return ImageOps.autocontrast(img, cutoff=0.5), "autocontrast p0.5-p99.5"


# ---------------------------------------------------------------------------
# Volledige neutralisatie van een enkel beeld
# ---------------------------------------------------------------------------
def neutraliseer(pad: Path, viewport: str, breedte: int,
                 max_hoogte_ratio: float, contrast: str,
                 snij_boven: int | None, maskeer_footer: bool,
                 chroma_winst: float, merkbalk_hoogte: int | None = None,
                 extra_maskers: list[list[float]] | None = None
                 ) -> tuple[Image.Image, NeutralisatieLog]:
    log = NeutralisatieLog()
    img = Image.open(pad)
    img = img.convert("RGB") if img.mode != "RGB" else img
    log.origineel_formaat = (img.width, img.height)

    # 1. browser-chrome
    if snij_boven is not None:
        n, reden = max(0, snij_boven), "handmatig opgegeven via --snij-boven"
    else:
        n, reden = detecteer_browser_chrome(img)
    log.chrome_afgesneden_px, log.chrome_reden = n, reden
    if n:
        img = img.crop((0, n, img.width, img.height))

    # 2. cookiebanner-rest onderaan
    n2, reden2 = detecteer_bodembanner(img)
    log.bodembanner_afgesneden_px, log.bodembanner_reden = n2, reden2
    if n2:
        img = img.crop((0, 0, img.width, img.height - n2))

    # 3. hoogte begrenzen (identieke leeslengte, en houdt het geheugen hanteerbaar)
    if max_hoogte_ratio and max_hoogte_ratio > 0:
        max_h = int(img.width * max_hoogte_ratio)
        if img.height > max_h:
            log.hoogte_begrensd_px = img.height - max_h
            img = img.crop((0, 0, img.width, max_h))

    # 4. identieke breedte
    nieuwe_h = max(1, round(img.height * breedte / img.width))
    img = img.resize((breedte, nieuwe_h), Image.LANCZOS)
    log.geschaald_naar = (img.width, img.height)

    # 5. merkregio's maskeren
    header_h, regios = maskeer_merkregios(img, viewport, maskeer_footer,
                                          merkbalk_hoogte, extra_maskers)
    log.headerhoogte_px, log.gemaskeerde_regios = header_h, regios

    # 6. kleur neutraliseren
    img, log.grijs_methode = naar_neutraal_grijs(img, chroma_winst=chroma_winst)

    # 7. contrast
    img, log.contrast_methode = pas_contrast_toe(img, contrast)

    log.eind_formaat = (img.width, img.height)
    return img, log


# ---------------------------------------------------------------------------
# Opslaan zonder verraad
# ---------------------------------------------------------------------------
def labels(n: int) -> list[str]:
    alfabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    uit = []
    for i in range(n):
        if i < 26:
            uit.append(alfabet[i])
        else:
            uit.append(alfabet[i // 26 - 1] + alfabet[i % 26])
    return uit


def schrijf_kaal_png(img: Image.Image, doel: Path) -> None:
    """PNG zonder tekstblokken, zonder tijdstempel; identieke encoderinstellingen."""
    doel.parent.mkdir(parents=True, exist_ok=True)
    img.save(doel, format="PNG", optimize=True, compress_level=9, pnginfo=None)


def _png_vulchunk(lengte_data: int) -> bytes:
    """Private, veilige-om-te-kopieren PNG-chunk 'paDx' met nulvulling."""
    data = b"\x00" * lengte_data
    typ = b"paDx"
    return struct.pack(">I", lengte_data) + typ + data + struct.pack(
        ">I", binascii.crc32(typ + data) & 0xFFFFFFFF)


def maskeer_bestandsgroottes(bestanden: list[Path]) -> int:
    """
    Bestandsgrootte is een lek: een strak, vlak ontwerp comprimeert anders dan een
    rommelig ontwerp. Alle PNG's worden op exact dezelfde byte-grootte gebracht
    door een negeerbare privechunk voor IEND te schuiven.
    """
    if len(bestanden) < 2:
        return 0
    groottes = [p.stat().st_size for p in bestanden]
    doel = max(groottes) + 12 + 16  # ruimte voor de chunk-overhead zelf
    for p in bestanden:
        ruw = p.read_bytes()
        iend = ruw.rfind(b"\x00\x00\x00\x00IEND")
        if iend < 0:
            continue
        tekort = doel - len(ruw)
        if tekort < 12:
            continue
        p.write_bytes(ruw[:iend] + _png_vulchunk(tekort - 12) + ruw[iend:])
    return doel


def controleer_naam(naam: str) -> list[str]:
    laag = naam.lower()
    return [w for w in VERBODEN_IN_NAAM if w in laag]


# ---------------------------------------------------------------------------
# Ronde bouwen
# ---------------------------------------------------------------------------
def lees_extra_maskers(pad: str | None) -> dict[str, list[list[float]]]:
    """
    Handmatige extra maskers, per bronbestandsnaam, in RELATIEVE coordinaten:
        {"linear_docs_1440.png": [[0.10, 0.18, 0.42, 0.26]]}
    Nodig omdat merknamen ook in de BROODTEKST staan ("Linear Docs",
    "https://api.stripe.com") en een beeldfilter die niet kan lezen.
    """
    if not pad:
        return {}
    p = Path(pad) if Path(pad).is_absolute() else PROJECT / pad
    if not p.exists():
        print(f"LET OP: maskerbestand {p} bestaat niet; genegeerd.")
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def bouw_ronde(bronnen: list[Bron], args, ronde_id: str) -> dict[str, Any]:
    extra_maskers = lees_extra_maskers(getattr(args, "extra_maskers", None))
    uit_map = Path(args.uit)
    ronde_map = uit_map / ronde_id
    if ronde_map.exists():
        shutil.rmtree(ronde_map)
    ronde_map.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    per_viewport: dict[str, list[Bron]] = {}
    for b in bronnen:
        per_viewport.setdefault(b.viewport, []).append(b)

    sleutel_rondes: dict[str, Any] = {
        "seed": args.seed,
        "aangemaakt_op": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "breedte_px": {"desktop": args.breedte, "mobile": args.breedte_mobile},
        "max_hoogte_ratio": args.max_hoogte_ratio,
        "contrast": args.contrast,
        "chroma_winst": args.chroma_winst,
        "viewports": {},
    }
    problemen: list[str] = []
    totaal = 0
    decoy_labels: dict[str, list[str]] = {}

    for vp in sorted(per_viewport):
        if args.viewports and vp not in args.viewports:
            continue
        lijst = list(per_viewport[vp])

        if args.max_per_bron:
            geteld: dict[str, int] = {}
            gefilterd = []
            for b in lijst:
                if b.soort != "comp":
                    gefilterd.append(b)
                    continue
                k = f"{b.set_naam}:{b.bron_naam}"
                geteld[k] = geteld.get(k, 0) + 1
                if geteld[k] <= args.max_per_bron:
                    gefilterd.append(b)
            lijst = gefilterd

        if args.max_comps:
            comps = [b for b in lijst if b.soort == "comp"]
            rest = [b for b in lijst if b.soort != "comp"]
            rng.shuffle(comps)
            lijst = rest + comps[:args.max_comps]

        rng.shuffle(lijst)                       # <- de eigenlijke randomisatie
        # Binnen een viewportgroep is de breedte identiek; tussen groepen wordt
        # niet vergeleken, dus mobiel hoeft niet naar desktopbreedte opgeblazen.
        breedte_vp = args.breedte_mobile if vp == "mobile" else args.breedte
        vp_map = ronde_map / vp
        vp_map.mkdir(parents=True, exist_ok=True)

        items = []
        geschreven: list[Path] = []
        for label, bron in zip(labels(len(lijst)), lijst):
            try:
                img, log = neutraliseer(
                    bron.pad, bron.viewport, breedte_vp, args.max_hoogte_ratio,
                    args.contrast, args.snij_boven, args.maskeer_footer,
                    args.chroma_winst, args.merkbalk_hoogte,
                    extra_maskers.get(bron.pad.name))
            except Exception as e:
                problemen.append(f"{bron.pad}: neutralisatie mislukt: {e}")
                continue
            doel = vp_map / f"{label}.png"
            schrijf_kaal_png(img, doel)
            img.close()
            geschreven.append(doel)
            lek = controleer_naam(doel.name)
            if lek:
                problemen.append(f"bestandsnaam {doel.name} verraadt: {lek}")
            items.append({
                "label": label,
                "bestand": doel.name,
                "soort": bron.soort,
                "is_decoy": bron.soort == "decoy",
                "is_ons": bron.soort == "ours",
                "bron_set": bron.set_naam,
                "bron_naam": bron.bron_naam,
                "bron_bestand": str(bron.pad.relative_to(PROJECT))
                if str(bron.pad).startswith(str(PROJECT)) else str(bron.pad),
                "omschrijving": bron.omschrijving,
                "neutralisatie": asdict(log),
            })
            if bron.soort == "decoy":
                decoy_labels.setdefault(vp, []).append(label)
            totaal += 1

        # Eerst de grootte gelijktrekken (dat herschrijft de bestanden), pas
        # daarna de tijdstempels; anders verraadt de mtime de schrijfvolgorde.
        gelijke_grootte = 0
        if args.maskeer_grootte:
            gelijke_grootte = maskeer_bestandsgroottes(geschreven)
        for p in geschreven:
            os.utime(p, (1735689600, 1735689600))  # 2025-01-01T00:00:00Z

        schrijf_beoordelingsformulier(vp_map, [i["label"] for i in items])
        sleutel_rondes["viewports"][vp] = {
            "aantal": len(items),
            "breedte_px": breedte_vp,
            "gelijke_bestandsgrootte_bytes": gelijke_grootte,
            "items": items,
        }

    schrijf_instructie(ronde_map, sleutel_rondes)
    return {"sleutel": sleutel_rondes, "problemen": problemen,
            "totaal": totaal, "decoy_labels": decoy_labels,
            "ronde_map": str(ronde_map)}


def schrijf_beoordelingsformulier(vp_map: Path, lbls: list[str]) -> None:
    regels = ["label,hierarchie_1_5,typografie_1_5,ritme_witruimte_1_5,"
              "consistentie_1_5,totaalindruk_1_5,opmerking"]
    regels += [f"{l},,,,,," for l in lbls]
    (vp_map / "beoordeling.csv").write_text("\n".join(regels) + "\n", encoding="utf-8")


def schrijf_instructie(ronde_map: Path, sleutel: dict) -> None:
    vps = ", ".join(f"{k} ({v['breedte_px']} px breed)"
                    for k, v in sleutel["viewports"].items()) or "-"
    tekst = f"""# Blinde beoordeling

Alle schermen zijn geneutraliseerd: merkkleur is verwijderd (grijswaarden met
behoud van contrast en structuur), logo-regio's zijn onherkenbaar gemaakt,
browser-chrome en bannerresten zijn weggesneden en elk beeld binnen een map is
naar exact dezelfde breedte geschaald. Resolutie, kleur en merk zijn dus
geen signaal. Beoordeel uitsluitend: informatiehierarchie, typografie, ritme en
witruimte, consistentie, en totaalindruk.

Mappen: {vps}
Vul per map beoordeling.csv in (1 = zwak, 5 = uitstekend).

Je weet niet welk scherm van wie is. Dat is de bedoeling. Raad niet - oordeel.
"""
    (ronde_map / "LEESMIJ.md").write_text(tekst, encoding="utf-8")


def schrijf_sleutel(uit_map: Path, ronde_id: str, sleutel: dict) -> Path:
    uit_map.mkdir(parents=True, exist_ok=True)
    pad = uit_map / "_sleutel.json"
    bestaand = {}
    if pad.exists():
        try:
            bestaand = json.loads(pad.read_text(encoding="utf-8"))
        except Exception:
            bestaand = {}
    bestaand.setdefault("waarschuwing",
                        "GEHEIM. Dit bestand mag de beoordelaar nooit zien. "
                        "Deel uitsluitend renders/ab/<ronde>/.")
    bestaand["script_versie"] = SCRIPT_VERSIE
    bestaand.setdefault("rondes", {})[ronde_id] = sleutel
    pad.write_text(json.dumps(bestaand, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(pad, 0o600)
    except Exception:
        pass
    return pad


# ---------------------------------------------------------------------------
# Zelftest van de neutralisatie
# ---------------------------------------------------------------------------
def zelftest() -> int:
    from PIL import ImageDraw
    fouten = []

    # Zoek een KLEUR met exact dezelfde lichtheid als middengrijs. Zo'n paar is
    # de zwaarste test: naieve grijsconversie laat die rand volledig verdwijnen.
    grijskleur = (128, 128, 128)
    doel_L = float(_naar_lab(np.array([[grijskleur]], dtype=np.uint8))[0][0, 0])
    stap = np.arange(0, 256, 8, dtype=np.uint8)
    R, G, B = np.meshgrid(stap, stap, stap, indexing="ij")
    kandidaten = np.stack([R, G, B], axis=-1).reshape(1, -1, 3).astype(np.uint8)
    kL, kC = _naar_lab(kandidaten)
    naief_luma = (0.299 * kandidaten[0, :, 0] + 0.587 * kandidaten[0, :, 1]
                  + 0.114 * kandidaten[0, :, 2])
    # isoluminant onder BEIDE maten: zowel CIE-L* als de naieve 601-luma
    geldig = (np.abs(kL[0] - doel_L) < 1.0) & (np.abs(naief_luma - 128.0) < 2.0)
    if not geldig.any():
        fouten.append("geen isoluminant testpaar gevonden")
        kleur = (0, 110, 190)
    else:
        score = np.where(geldig, kC[0], -1.0)
        kleur = tuple(int(v) for v in kandidaten[0, int(np.argmax(score))])

    proef = Image.new("RGB", (200, 100), grijskleur)
    d = ImageDraw.Draw(proef)
    d.rectangle([40, 30, 160, 70], fill=kleur)
    grijs, _ = naar_neutraal_grijs(proef)
    a = np.asarray(grijs, dtype=np.float32)
    randsterkte = float(np.abs(np.diff(a[50])).max())
    naief = np.asarray(proef.convert("L"), dtype=np.float32)
    naief_rand = float(np.abs(np.diff(naief[50])).max())
    print(f"  isoluminant paar {grijskleur} vs {kleur}: "
          f"naieve grijsconversie rand={naief_rand:.1f}, onze rand={randsterkte:.1f}")
    if randsterkte < 8 or randsterkte <= naief_rand:
        fouten.append(f"isoluminante rand verdwijnt (sterkte {randsterkte:.1f})")

    # grijs moet echt grijs zijn: geen kleurkanalen meer
    if grijs.mode != "L":
        fouten.append(f"uitvoer is niet eenkanaals maar {grijs.mode}")

    # --- randdetectie: moet aanslaan op echte chrome, en NIET op een sitekop ---
    def _mock_browser(schaal=2, donker=False):
        bg = (255, 255, 255) if not donker else (32, 33, 36)
        tab = (222, 225, 230) if not donker else (41, 42, 45)
        bar = (241, 243, 244) if not donker else (53, 54, 58)
        pil = (255, 255, 255) if not donker else (95, 99, 104)
        tk = (30, 30, 30) if not donker else (230, 230, 230)
        w, h = 1440 * schaal, 900 * schaal
        im = Image.new("RGB", (w, h), bg); d = ImageDraw.Draw(im)
        d.rectangle([0, 0, w, 60 * schaal], fill=tab)
        d.rounded_rectangle([20 * schaal, 10 * schaal, 300 * schaal, 50 * schaal],
                            8 * schaal, fill=bar)
        d.rectangle([0, 60 * schaal, w, 110 * schaal], fill=bar)
        d.rounded_rectangle([60 * schaal, 70 * schaal, 900 * schaal, 100 * schaal],
                            14 * schaal, fill=pil)
        for i in range(45):
            d.text((40 * schaal, (130 + i * 14) * schaal), f"Inhoudsregel {i}", fill=tk)
            d.rectangle([600 * schaal, (130 + i * 14) * schaal,
                         1300 * schaal, (139 + i * 14) * schaal], fill=(90 + i % 40, 140, 190))
        return im

    def _mock_sitekop():
        """Donkere sitekop met logo, navigatie en een zoekpil - geen browser."""
        w, h = 1440, 3000
        im = Image.new("RGB", (w, h), (255, 255, 255)); d = ImageDraw.Draw(im)
        d.rectangle([0, 0, w, 96], fill=(28, 42, 66))
        d.rectangle([40, 30, 190, 66], fill=(240, 240, 240))          # woordmerk
        for i, x in enumerate((320, 430, 540, 650)):
            d.text((x, 44), f"Menu {i}", fill=(235, 235, 235))
        d.rounded_rectangle([980, 32, 1290, 64], 16, fill=(255, 255, 255))  # zoekpil
        for i in range(150):
            d.text((40, 130 + i * 18), f"Pagina-inhoud regel {i}", fill=(40, 40, 40))
        return im

    for naam, mock, verwacht in (("browser licht 2x", _mock_browser(), True),
                                 ("browser licht 1x", _mock_browser(1), True),
                                 ("browser donker", _mock_browser(donker=True), True),
                                 ("sitekop (geen browser)", _mock_sitekop(), False)):
        n, reden = detecteer_browser_chrome(mock)
        print(f"  chromedetectie {naam:24s}: {n:4d} px")
        if bool(n) != verwacht:
            fouten.append(f"chromedetectie {naam}: {n} px, verwacht "
                          f"{'wel' if verwacht else 'geen'} snede ({reden})")

    banner = _mock_sitekop()
    ImageDraw.Draw(banner).rectangle([0, 3000 - 260, 1440, 3000], fill=(31, 41, 55))
    n, _ = detecteer_bodembanner(banner)
    print(f"  bodemdetectie  nagebootste bannerrest : {n:4d} px (260 verwacht)")
    if not (200 <= n <= 300):
        fouten.append(f"bodemdetectie vindt {n} px in plaats van ~260")
    n, _ = detecteer_bodembanner(_mock_sitekop())
    if n:
        fouten.append(f"bodemdetectie snijdt {n} px van een pagina zonder banner")

    # labels
    if labels(28)[26:] != ["AA", "AB"]:
        fouten.append("labelreeks loopt fout na Z")

    # naamcontrole
    if not controleer_naam("ours_dashboard.png"):
        fouten.append("naamcontrole mist 'ours'")
    if controleer_naam("A.png"):
        fouten.append("naamcontrole geeft vals alarm op A.png")

    # chunk-vulling levert geldige PNG
    import io
    buf = io.BytesIO()
    Image.new("L", (8, 8), 128).save(buf, format="PNG")
    ruw = buf.getvalue()
    iend = ruw.rfind(b"\x00\x00\x00\x00IEND")
    gevuld = ruw[:iend] + _png_vulchunk(100) + ruw[iend:]
    try:
        Image.open(io.BytesIO(gevuld)).load()
    except Exception as e:
        fouten.append(f"gevulde PNG onleesbaar: {e}")

    for f in fouten:
        print("ZELFTEST FOUT:", f)
    print("ZELFTEST:", "ok" if not fouten else f"{len(fouten)} fout(en)")
    return 0 if not fouten else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Blinde A/B-harnas voor interfacebeoordeling")
    p.add_argument("--comps", nargs="*", default=["renders/comps", "renders/comps_nl"],
                   help="mappen met comps (echte, externe interfaces)")
    p.add_argument("--ours", nargs="*", default=["renders/ours"],
                   help="mappen met onze eigen schermen")
    p.add_argument("--decoy", nargs="*", default=["renders/decoy"],
                   help="mappen met decoy-beelden (bewust middelmatig ontwerp)")
    p.add_argument("--uit", default="renders/ab", help="uitvoermap")
    p.add_argument("--ronde", default=None, help="naam van de ronde (standaard: tijdstempel)")
    p.add_argument("--seed", type=int, default=None, help="seed voor de volgorde")
    p.add_argument("--breedte", type=int, default=1200,
                   help="identieke breedte in px voor desktop-beelden")
    p.add_argument("--breedte-mobile", type=int, default=780,
                   help="identieke breedte in px voor mobiele beelden "
                        "(apart, zodat mobiel niet onnodig wordt opgeschaald)")
    p.add_argument("--max-hoogte-ratio", type=float, default=3.0,
                   help="max hoogte als veelvoud van de breedte (0 = onbegrensd)")
    p.add_argument("--contrast", choices=["uit", "zacht", "hard"], default="zacht")
    p.add_argument("--chroma-winst", type=float, default=0.5,
                   help="hoeveel chroma-randen als structuur terugkomen in het grijs")
    p.add_argument("--snij-boven", type=int, default=None,
                   help="forceer aantal px browser-chrome dat boven wordt weggesneden")
    p.add_argument("--merkbalk-hoogte", type=int, default=None,
                   help="forceer de hoogte van de gemaskeerde merkbalk in px "
                        "(standaard 8%% van de beeldbreedte)")
    p.add_argument("--extra-maskers", default=None,
                   help="JSON met extra te maskeren rechthoeken per bronbestand, "
                        "in relatieve coordinaten [x0,y0,x1,y1]; voor merknamen "
                        "die in de broodtekst staan")
    p.add_argument("--maskeer-footer", action="store_true",
                   help="ook de footer-linkerhoek maskeren (logo's staan daar vaak)")
    p.add_argument("--viewports", nargs="*", default=["desktop", "mobile"])
    p.add_argument("--max-per-bron", type=int, default=0,
                   help="max aantal schermen per comp-BRON (merk) per viewport; "
                        "0 = alles. Zet op 1 als je niet wilt dat een enkel merk "
                        "de ranglijst domineert - let op: dan vallen schermen weg.")
    p.add_argument("--max-comps", type=int, default=0,
                   help="max aantal comps per viewport (0 = alles)")
    p.add_argument("--maskeer-grootte", action="store_true", default=True,
                   help="alle PNG's op gelijke bestandsgrootte brengen")
    p.add_argument("--geen-groottemaskering", dest="maskeer_grootte", action="store_false")
    p.add_argument("--zelftest", action="store_true")
    args = p.parse_args(argv)

    if args.zelftest:
        return zelftest()

    if args.seed is None:
        args.seed = random.randrange(1, 10**9)
    ronde_id = args.ronde or time.strftime("ronde_%Y%m%d_%H%M%S")

    def paden(lst):
        return [Path(x) if Path(x).is_absolute() else PROJECT / x for x in (lst or [])]

    comps = verzamel_bronnen(paden(args.comps), "comp")
    ours = verzamel_bronnen(paden(args.ours), "ours")
    decoys = verzamel_bronnen(paden(args.decoy), "decoy")

    meldingen = []
    if not comps:
        meldingen.append("GEEN COMPS GEVONDEN - de harnas draait, maar er is niets "
                         "om ons tegen af te zetten.")
    if not ours:
        meldingen.append("GEEN EIGEN SCHERMEN GEVONDEN in "
                         f"{', '.join(map(str, args.ours))} - de ronde bevat alleen "
                         "comps (+ decoy). Zodra onze schermen bestaan, komen ze "
                         "automatisch mee.")
    if not decoys:
        meldingen.append("GEEN DECOY GEVONDEN - de meetlat wordt deze ronde niet "
                         "gecontroleerd. Draai scripts/maak_decoy.py.")
    for m in meldingen:
        print("LET OP:", m)

    bronnen = comps + ours + decoys
    if not bronnen:
        print("Niets te doen: geen enkel bronbeeld gevonden.")
        return 2

    args.uit = str(Path(args.uit) if Path(args.uit).is_absolute() else PROJECT / args.uit)
    res = bouw_ronde(bronnen, args, ronde_id)
    sleutelpad = schrijf_sleutel(Path(args.uit), ronde_id, res["sleutel"])

    print(f"\nRonde     : {ronde_id}")
    print(f"Seed      : {args.seed}")
    print(f"Beelden   : {res['totaal']}")
    print(f"Beoordeel : {res['ronde_map']}   (GEEF ALLEEN DEZE MAP)")
    print(f"Sleutel   : {sleutelpad}   (GEHEIM)")
    for vp, info in res["sleutel"]["viewports"].items():
        print(f"  {vp}: {info['aantal']} beelden, "
              f"decoy = {', '.join(res['decoy_labels'].get(vp, [])) or 'geen'}")
    for pr in res["problemen"]:
        print("PROBLEEM:", pr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
