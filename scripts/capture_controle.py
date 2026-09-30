#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_controle.py - naharde opnamecontrole en manifestschema voor de meetlat-opnames.

Waarom
------
De meetlat-audit (state.json -> meetlat_audit_ronde_0) vond opnames die bijna leeg waren,
achter een cookiewall zaten of een foutpagina toonden en toch als 'geladen' in het
manifest stonden, en een manifest dat beschreef wat een bedrijf verkoopt in plaats van wat
er is vastgelegd. Deze module maakt dat onmogelijk: elke opname wordt objectief gemeten
en `geladen_ok` volgt uit die metingen, niet uit de bedoeling van de opnemer.

Gebruik
-------
  python3 scripts/capture_controle.py --zelftest                 # tests op synthetische beelden
  python3 scripts/capture_controle.py --zelftest --met-browser   # idem + echte Chromium-fixtures
  python3 scripts/capture_controle.py --controleer renders/comps # meet alle PNG's in een map
  python3 scripts/capture_controle.py --valideer renders/*/manifest.json

De capture-scripts (capture_comps.py, capture_comps_nl.py, capture_anker.py) en maak_decoy.py
importeren deze module. Het harnas kan `lees_opnames()` gebruiken om elk manifest uniform te
lezen.

Wat er per opname wordt gemeten
-------------------------------
BEELD (uit de PNG zelf, dus achteraf herhaalbaar):
  inkt_aandeel               aandeel pixels dat afwijkt van de dominante achtergrondkleur
  structuur_aandeel          aandeel randpixels (tekst, lijnen, vlakovergangen)
  effen_wit_aandeel          aandeel bijna-witte pixels (alleen ter info)
  effen_blokken_aandeel      aandeel blokken van 32x32 css-px zonder enige afwijking van de
                             dominante kleur; meet 'te veel effen vlak' zonder dat gewone
                             tekst op wit al als leeg telt
  langste_lege_band_css_px   langste aaneengesloten reeks rijen zonder enige structuur
  grote_lege_banden_aandeel  aandeel van de paginahoogte in lege banden >= 240 css-px
  lege_staart_css_px         lege strook onderaan (scroll-animaties die nooit afgingen)
  overlay.gecentreerd_blok   helder, gevuld blok midden in de eerste viewport met een duidelijk
                             donkerder rand eromheen (modal/cookiewall)
  overlay.dimming_boven_vouw de eerste viewport is scherp donkerder dan de rest van de pagina
                             (Chromium schildert een fixed dim-laag in een full-page opname
                             alleen over de eerste viewporthoogte)
DOM (op het opnamemoment; alleen aanwezig bij een echte capture):
  http_status, eind_url, titel, h1, tekst_tekens, taal_gemeten
  fout_patroon               foutpagina/botmuur/captcha/'access denied' in titel of tekst
  overlays_na                zichtbare, blokkerende overlays vlak voor de screenshot
  cookies                    wat er met een cookiebanner is gedaan, MET meting voor en na

Afkeuren (`geladen_ok` = false) gebeurt bij (de codes staan in `afkeurredenen`):
  capture_mislukt, http_4xx/5xx          de lading faalde of de site weigerde; geen tweede poging, geen omweg
  toegang_geweigerd, botmuur_of_captcha, niet_gevonden, server_of_onderhoud, javascript_niet_gerenderd
                                         foutpagina of botmuur in titel/kop/korte tekst, of een ZICHTBARE captcha
  omleiding_naar_consent_of_login        de eind-URL is een login- of consentpagina
  vrijwel_geen_tekst (< 100 tekens), te_weinig_tekst (< 300, tenzij >= 3 zichtbare invoerelementen)
                                         pagina niet gerenderd, of een titel met een paar links; een
                                         formulierstap met weinig tekst maar wel keuzes en knoppen telt mee
  geen_html_pagina, platte_tekst_pagina  de URL levert een afbeelding of platte tekst/markdown ('machineversie')
  blokkerende_overlay_dom                een dialoog, cookiebanner of dim-laag die het beeld bedekt en niet
                                         (gemeten) is verwijderd; login- en betaalmuren worden NOOIT weggehaald
  gecentreerd_blok_in_beeld, dimming_boven_vouw
                                         modal/cookiewall zichtbaar in het beeld zelf (onafhankelijk van de DOM)
  bijna_leeg, te_veel_effen_vlak, grote_lege_band, lege_staart
                                         te weinig inkt/structuur, of secties die nooit zijn geladen
  breder_dan_viewport                    horizontale overflow: de layout is uitgeschaald (mobiel 980 i.p.v. 390 css-px)
De drempels staan in `Drempels`; ze zijn gekalibreerd op de eigen opnames en op de synthetische
foutgevallen van `--zelftest`.

Een afgekeurde PNG gaat naar `<map>/_afgekeurd/`, zodat een lezer die alleen `<map>/*.png`
globt hem niet per ongeluk meeneemt; het manifest bewaart de regel MET reden.

Wat deze controle NIET kan
--------------------------
Ze bewijst dat een opname schoon, gevuld en geladen IS; ze bewijst niet dat de pagina de
juiste is. Daarom staat `wat_het_toont` in de scripts als door de opnemer geinspecteerde tekst
(met datum) en niet als afgeleide van de bedrijfsomschrijving. Een overlay die noch in de
DOM (bijvoorbeeld in een gesloten shadow-root of cross-origin iframe) noch als gedimd,
gecentreerd blok in het beeld zichtbaar is, glipt door; daarom is elk beeld ook visueel
nagelopen (zie `geinspecteerd_op` in de manifesten).

MANIFESTSCHEMA (versie 2)
-------------------------
Drie vormen blijven bestaan (het harnas leest ze al); ze delen hetzelfde OPNAMERECORD.

  renders/comps/manifest.json        lijst van opnamerecords
  renders/comps_nl/manifest.json     object {"comps": [bron, ...], "overgeslagen": [...], ...};
                                     per bron staat onder "bestanden" -> "desktop"/"mobile"
                                     een opnamerecord (met "file" als oude alias van "bestand")
  renders/decoy/manifest.json        object {"bestanden": [opnamerecord, ...], "decoys": [...]}
  renders/anker/manifest.json        object {"bestanden": [opnamerecord, ...], "ankers": [...]}

OPNAMERECORD (per PNG; alle velden verplicht tenzij anders vermeld):
  bestand            bestandsnaam ten opzichte van de map van het manifest; goed = "x.png",
                     afgekeurd = "_afgekeurd/x.png"; null voor een bron zonder PNG (overgeslagen of
                     mislukt; klasse en taal zijn dan null omdat de opnemer de pagina nooit heeft gezien,
                     geladen_ok is false en afkeurredenen/afkeurreden geven de reden)
  bron_naam          leesbare naam van de bron (alleen voor de sleutel, nooit voor de beoordelaar)
  viewport_naam      "desktop" (1440 breed) of "mobile" (390 breed)
  klasse             "product_ui" | "marketing" | "decoy" | "anker"
                       product_ui  werkende of demo-interface waarmee je een taak doet of iets
                                   opzoekt (app, register/zoekapplicatie, rekentool, formulier-
                                   flow, documentatie-applicatie); publiek, zonder account
                       marketing   pagina om iets te verkopen, uit te leggen of naar een login te leiden
                                   (homepage, prijzen, productpagina, vergelijker-landing met een
                                   invulwidget, inlogpoort), ook als er mockups of screenshots van
                                   een product of een los zoekveld in staan
                       decoy       zelfgemaakt nepscherm van bewust benoemde kwaliteit
                       anker       positieve controle: echte UI van uitzonderlijke kwaliteit
  domein             "nl_financieel" | "internationaal" | "decoy" | "anker"
  taal               "nl" | "en" (gemeten aan de zichtbare tekst waar mogelijk)
  geladen_ok         bool. False = niet gebruiken in een meetronde; reden in afkeurredenen
  afkeurredenen      lijst codes (leeg als geladen_ok true)
  controle           dict met de meetwaarden (zie boven), inclusief "beeld" en "dom"
  wat_het_toont      wat er WERKELIJK is vastgelegd, op basis van inspectie en meting
  kwaliteit          alleen decoys: "zeer_zwak" | "zwak" | "matig" | "redelijk"
  soort_scherm       label voor fijnere selectie en rapportage per soort. product_ui: app, dashboard,
                     dataviewer, boekingsflow, zoekresultaten, formulier, document_lezer, catalogus, docs.
                     marketing: marketing_home, productpagina, prijzenpagina, vergelijker_landing,
                     informatiepagina, inlogpoort, organisatie_homepage, galerij_landing. Let op: "docs"
                     (documentatie-interface) is echte UI maar geen werkscherm; een strikte ronde sluit
                     het uit, en een conclusie hoort alleen over vergelijkbare soorten te gaan.
  dekking_categorie  wat deze set WEL en NIET vertegenwoordigt (ook in de lijstvorm, omdat een
                     lijst geen kopveld heeft)
  plus de bestaande velden (id/slug, url, viewport, vastgelegd_op, bestandsgrootte_bytes, ...)

Aanvullende (optionele) velden op een opnamerecord:
  afkeurreden        dezelfde redenen als leesbare tekst (alleen bij geladen_ok false)
  geinspecteerd_op   datum waarop de opnemer de opname heeft bekeken en klasse/wat_het_toont vaststelde
  toegang            hoe de pagina publiek toegankelijk is (bijvoorbeeld 'publieke sandbox-demo, geen account')
  stappen            de klik-/zoekstappen die zijn uitgevoerd om de getoonde staat te bereiken, elk met uitkomst
                     ("ok: ..." of "MISLUKT (...)"); getypt wordt alleen een zoekterm in een publiek zoekveld
                     (en gezocht); in offerte- of aanvraagformulieren wordt niets ingevuld of verzonden
  traag_scrollen_herpoging   true als bij grote lege banden eenmalig langzamer is gescrold en opnieuw opgenomen
  taal_opmerking     alleen als de gemeten taal afwijkt van de verwachte
  wat_het_toont_mobiel   alleen als de mobiele opname wezenlijk anders is dan de desktopopname
  kwaliteit, bewuste_zwaktes, indeling, bron_html   alleen decoys (zie scripts/maak_decoy.py)
  onderbouwing       alleen ankers: externe bronnen voor 'breed aangehaald als referentie'

Structuur van `controle` (alle sleutels optioneel behalve `schema`):
  beeld        metingen aan de PNG (zie boven), of null als er geen PNG is
  dom          http_status, eind_url, titel, h1, tekst_tekens, bediening_zichtbaar (aantal zichtbare
               invoerelementen), content_type, aantal_elementen, taal_gemeten, fout_patroon,
               captcha_element, overlays_na, scroll_vergrendeld, inner_afmeting
  cookies      actie (geen_banner | geklikt | css_verborgen | js_verborgen | gesloten | vanzelf_verdwenen |
               verdwenen_tussen_metingen | niet_verwijderd), stappen, blokkerend_voor, blokkerend_na,
               beschrijving. `beschrijving` is de
               ENIGE bron voor een uitspraak over cookies: 'geklikt' staat er alleen als de overlay daarna
               aantoonbaar uit de DOM was.
  leesbaarheid alleen decoys: overflow, afgekapte tekst/invoer, bedekte bediening, lettergrootte, contrast
  overgeslagen true bij een bron die niet is geladen (geen PNG; bestand is dan null)

`geladen_ok` op bronniveau (comps_nl) is de EN over de bestanden; de waarheid per viewport staat
in bestanden.<viewport>.geladen_ok. Lezers moeten op bestandsniveau filteren.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # full-page opnames zijn legitiem enorm

SCHEMA_VERSIE = 2
CONTROLE_VERSIE = "1"

PROJECT = Path(__file__).resolve().parent.parent
CHROME = os.environ.get("COMPS_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

KLASSEN = ("product_ui", "marketing", "decoy", "anker")
DOMEINEN = ("nl_financieel", "internationaal", "decoy", "anker")
TALEN = ("nl", "en")
KWALITEITEN = ("zeer_zwak", "zwak", "matig", "redelijk")
VIEWPORT_NAMEN = ("desktop", "mobile")

# Nominale viewports (css-px). De echte innerHeight wordt bij een capture gemeten.
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}
DEVICE_SCALE = 2
AFGEKEURD_MAP = "_afgekeurd"
MAX_PAGINA_CSS_PX = 10000          # veiligheidsplafond voor extreem lange pagina's
PAUZE_TUSSEN_LADINGEN_S = 3.0      # beleefdheid: pauze tussen twee paginaladingen

UA_DESKTOP = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
UA_MOBIEL = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

# Hosts waarvan bekend is dat ze bots blokkeren (eerdere run). We slaan ze over en melden het;
# we proberen het niet te omzeilen.
BEKEND_GEBLOKKEERD = {
    "independer.nl": "bekend bot-geblokkeerd (eerdere run); niet omzeild",
    "nn.nl": "bekend bot-geblokkeerd (eerdere run); niet omzeild",
    "centraalbeheer.nl": "bekend bot-geblokkeerd (eerdere run); niet omzeild",
    "rabobank.nl": "bekend bot-geblokkeerd (eerdere run); niet omzeild",
    "ing.nl": "bekend bot-geblokkeerd (eerdere run); niet omzeild",
}


# ===========================================================================
# 1. Drempels
# ===========================================================================
@dataclass(frozen=True)
class Drempels:
    """
    Alle drempels op een plek. Ze zijn gekalibreerd met `--controleer` op de eigen opnames en
    op synthetische foutgevallen (zie `--zelftest`): leeg, cookiewall en lege band MOETEN
    worden afgekeurd, gewone tekstpagina's, donkere sidebars en dark mode niet. De meetwaarden
    staan per opname in het manifest (controle.beeld), zodat elke drempel achteraf ter
    discussie te stellen is.
    """
    # bijna leeg: te weinig randen/inkt over de hele pagina
    min_structuur_aandeel: float = 0.0030
    min_inkt_aandeel: float = 0.012
    # te veel effen vlak: blokken van 32x32 css-px zonder enige afwijking
    max_effen_blokken_aandeel: float = 0.93
    # lege banden
    grote_band_css_px: int = 240
    max_grote_lege_banden_aandeel: float = 0.45
    max_langste_lege_band_css_px: int = 1500
    max_langste_lege_band_aandeel: float = 0.55
    max_lege_staart_css_px: int = 700
    max_lege_staart_aandeel: float = 0.30
    # overlay in beeld
    min_blok_contrast: float = 50.0          # helderheid blok min helderheid ring
    min_vouwstap: float = 35.0               # helderheidssprong op de vouw
    min_vouw_scherpte: float = 20.0          # sprong tussen naburige rijen op de vouw
    # tekst (zichtbare tekens in de DOM). Gekalibreerd op de eigen opnames: de laagste goede opname
    # (Vercel Geist mobiel) heeft 513 tekens, een schaarse Notion-pagina (titel + vijf links) 236, de eerste
    # stap van een formulierflow (a.s.r.-premiecalculator: kop, vraag, drie keuzes, twee knoppen) 217.
    min_tekst_tekens_leeg: int = 100         # minder = pagina niet gerenderd
    min_tekst_tekens: int = 300              # minder = te weinig inhoud om als scherm te dienen ...
    min_bediening_bij_weinig_tekst: int = 3  # ... tenzij er minstens zoveel zichtbare invoerelementen zijn
    max_tekst_voor_foutpatroon: int = 2500   # foutpatroon in lange pagina's telt alleen in titel/h1


DREMPELS = Drempels()


# ===========================================================================
# 2. Beeldmetingen
# ===========================================================================
def _hex(rgb: Iterable[int]) -> str:
    r, g, b = (int(x) for x in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _dominante_kleur(rgb: np.ndarray) -> tuple[tuple[int, int, int], float]:
    """Exacte modus van de kleuren op een steekproef (elke 5e rij, elke 3e kolom)."""
    s = rgb[::5, ::3].reshape(-1, 3).astype(np.int64)
    sleutel = (s[:, 0] << 16) | (s[:, 1] << 8) | s[:, 2]
    waarden, aantallen = np.unique(sleutel, return_counts=True)
    i = int(aantallen.argmax())
    k = int(waarden[i])
    return ((k >> 16) & 255, (k >> 8) & 255, k & 255), float(aantallen[i] / sleutel.size)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Aaneengesloten True-reeksen als (start, lengte)."""
    if mask.size == 0:
        return []
    m = np.concatenate(([False], mask, [False])).astype(np.int8)
    d = np.diff(m)
    starts = np.flatnonzero(d == 1)
    eindes = np.flatnonzero(d == -1)
    return [(int(s), int(e - s)) for s, e in zip(starts, eindes)]


def _label_grootste(mask: np.ndarray) -> tuple[int, tuple[int, int, int, int]] | None:
    """Grootste 4-verbonden component van een booleaanse cellenmask: (aantal, (r0, r1, c0, c1))."""
    h, w = mask.shape
    gezien = np.zeros(mask.shape, dtype=bool)
    beste: tuple[int, tuple[int, int, int, int]] | None = None
    for r in range(h):
        for c in range(w):
            if not mask[r, c] or gezien[r, c]:
                continue
            q = deque([(r, c)])
            gezien[r, c] = True
            n = 0
            r0 = r1 = r
            c0 = c1 = c
            while q:
                y, x = q.popleft()
                n += 1
                r0, r1 = min(r0, y), max(r1, y)
                c0, c1 = min(c0, x), max(c1, x)
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not gezien[ny, nx]:
                        gezien[ny, nx] = True
                        q.append((ny, nx))
            if beste is None or n > beste[0]:
                beste = (n, (r0, r1, c0, c1))
    return beste


def _overlay_beeld(L_top: np.ndarray, rijgem: np.ndarray, onder: np.ndarray | None,
                   vp_px: int, schaal: int, mobiel: bool, d: Drempels) -> dict[str, Any]:
    """
    Zoekt de handtekening van een modal/cookiewall in de EERSTE viewport van het beeld.

    Bevinding uit een experiment met Playwright/Chromium: bij `full_page=True` wordt een
    `position: fixed` dim-laag met gecentreerde dialoog alleen over de eerste viewporthoogte
    geschilderd; daaronder is de pagina onbedekt. Twee handtekeningen:
      A. gecentreerd_blok: een heldere, bijna gevulde rechthoek, in het midden, niet tegen de
         rand aan, met een duidelijk donkerder ring eromheen.
      B. dimming_boven_vouw: de eerste viewport is op de vouw scherp donkerder dan direct
         eronder, en zelfs zijn helderste inhoud (buiten het blok) is gedimd.
    `L_top` = luminantie van de eerste viewport, `rijgem` = rijgemiddelde luminantie van de
    hele pagina, `onder` = steekproef van de luminantie onder de vouw (of None).
    """
    uit: dict[str, Any] = {"gecentreerd_blok": False, "dimming_boven_vouw": False}
    top_h, W = L_top.shape
    if top_h < 200 or W < 200:
        return uit

    b = max(4, 4 * schaal)                     # celgrootte in beeldpixels (= 4 css-px)
    h8, w8 = top_h // b, W // b
    cel = L_top[: h8 * b, : w8 * b].reshape(h8, b, w8, b).mean(axis=(1, 3))

    frame_waarden = cel.ravel()
    comp = _label_grootste(cel >= 214)
    if comp is not None:
        _n, (r0, r1, c0, c1) = comp
        bh, bw = r1 - r0 + 1, c1 - c0 + 1
        blok = cel[r0: r1 + 1, c0: c1 + 1]
        gevuld = float((blok >= 190).mean())
        cx, cy = (c0 + c1 + 1) / 2, (r0 + r1 + 1) / 2
        rand = 2
        y0, y1 = max(0, r0 - rand), min(h8, r1 + 1 + rand)
        x0, x1 = max(0, c0 - rand), min(w8, c1 + 1 + rand)
        ring = cel[y0:y1, x0:x1]
        binnen = np.zeros(ring.shape, dtype=bool)
        binnen[(r0 - y0): (r1 - y0 + 1), (c0 - x0): (c1 - x0 + 1)] = True
        ring_waarden = ring[~binnen]
        blok_med = float(np.median(blok))
        ring_med = float(np.median(ring_waarden)) if ring_waarden.size else blok_med
        contrast = blok_med - ring_med
        maxb = 0.95 if mobiel else 0.82
        marge_x = 0.02 if mobiel else 0.05
        gecentreerd = (
            abs(cx - w8 / 2) <= 0.12 * w8
            and abs(cy - h8 / 2) <= 0.22 * h8
            and 0.15 * w8 <= bw <= maxb * w8
            and 0.06 * h8 <= bh <= 0.85 * h8
            and c0 >= marge_x * w8 and (c1 + 1) <= (1 - marge_x) * w8
            and r0 >= 0.03 * h8 and (r1 + 1) <= 0.97 * h8
            and gevuld >= 0.75
        )
        uit["blok_bbox_rel"] = [round(c0 / w8, 3), round(r0 / h8, 3),
                                round((c1 + 1) / w8, 3), round((r1 + 1) / h8, 3)]
        uit["blok_gevuld"] = round(gevuld, 3)
        uit["blok_contrast"] = round(contrast, 1)
        uit["ring_mediaan"] = round(ring_med, 1)
        uit["gecentreerd_blok"] = bool(gecentreerd and contrast >= d.min_blok_contrast)
        frame_mask = np.ones(cel.shape, dtype=bool)
        frame_mask[r0: r1 + 1, c0: c1 + 1] = False
        frame_waarden = cel[frame_mask]

    if onder is not None and onder.size:
        v = vp_px
        boven = float(rijgem[max(0, v - 12 * schaal): v - 2].mean())
        eronder = float(rijgem[v + 2: v + 12 * schaal].mean())
        stap = eronder - boven
        scherpte = float(np.abs(np.diff(rijgem[v - 3: v + 3])).max())
        p99_boven = float(np.percentile(frame_waarden, 99)) if frame_waarden.size else 255.0
        p99_onder = float(np.percentile(onder, 99))
        uit["vouwstap"] = round(stap, 1)
        uit["vouw_scherpte"] = round(scherpte, 1)
        uit["helderste_boven_zonder_blok"] = round(p99_boven, 1)
        uit["helderste_onder"] = round(p99_onder, 1)
        uit["dimming_boven_vouw"] = bool(
            stap >= d.min_vouwstap and scherpte >= d.min_vouw_scherpte and p99_boven <= p99_onder - 30)
    return uit


def _lum(a: np.ndarray) -> np.ndarray:
    f = a.astype(np.float32)
    return 0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2]


def meet_beeld(pad: str | Path, viewport_naam: str = "desktop", *, schaal: int = DEVICE_SCALE,
               vp_hoogte_css: int | None = None, d: Drempels = DREMPELS) -> dict[str, Any]:
    """Objectieve metingen aan een opname. Rekent op volle resolutie, in stroken."""
    with Image.open(pad) as im:
        im.load()
        rgb = np.asarray(im.convert("RGB"))
    H, W, _ = rgb.shape
    vp_css = int(vp_hoogte_css or VIEWPORTS.get(viewport_naam, VIEWPORTS["desktop"])["height"])
    mobiel = viewport_naam == "mobile"
    top_px = vp_css * schaal

    dom_kleur, dom_aandeel = _dominante_kleur(rgb)
    dom = np.array(dom_kleur, dtype=np.int16)

    rij_randen = np.zeros(H, dtype=np.int64)
    rijgem = np.zeros(H, dtype=np.float64)
    edge_totaal = ink_totaal = wit_totaal = effen_blokken = blokken_totaal = 0
    blok = 32 * schaal
    strook = 512 - (512 % blok)
    top_delen: list[np.ndarray] = []

    for y in range(0, H, strook):
        s = rgb[y: y + strook]
        L = _lum(s)
        rijgem[y: y + s.shape[0]] = L.mean(axis=1)
        e = np.zeros(L.shape, dtype=bool)
        e[:, 1:] |= np.abs(np.diff(L, axis=1)) > 32
        e[1:, :] |= np.abs(np.diff(L, axis=0)) > 32
        rij_randen[y: y + s.shape[0]] = e.sum(axis=1)
        edge_totaal += int(e.sum())
        # kanalen apart (veel sneller dan min/max over de laatste as)
        r_, g_, b_ = s[..., 0], s[..., 1], s[..., 2]
        afw = np.maximum(np.maximum(np.abs(r_.astype(np.int16) - dom[0]), np.abs(g_.astype(np.int16) - dom[1])),
                         np.abs(b_.astype(np.int16) - dom[2]))
        ink_totaal += int((afw > 20).sum())
        wit_totaal += int((np.minimum(np.minimum(r_, g_), b_) >= 250).sum())
        hh, ww = (s.shape[0] // blok) * blok, (W // blok) * blok
        if hh and ww:
            effen = (afw[:hh, :ww] <= 6).reshape(hh // blok, blok, ww // blok, blok).all(axis=(1, 3))
            effen_blokken += int(effen.sum())
            blokken_totaal += int(effen.size)
        if y < top_px:
            top_delen.append(L[: min(s.shape[0], top_px - y)])

    px = H * W
    leeg_rij = rij_randen <= max(2, int(0.0006 * W))
    banden = _runs(leeg_rij)
    langste = max((n for _s, n in banden), default=0)
    grote = sum(n for _s, n in banden if n / schaal >= d.grote_band_css_px)
    staart = 0
    if banden and banden[-1][0] + banden[-1][1] == H:
        staart = banden[-1][1]

    L_top = np.concatenate(top_delen, axis=0)
    onder = None
    if H > top_px + 60 * schaal:
        onder = _lum(rgb[top_px + 2: min(H, top_px + 6 * top_px): 3, ::3])
    overlay = _overlay_beeld(L_top, rijgem, onder, top_px, schaal, mobiel, d)

    verwacht_b = VIEWPORTS.get(viewport_naam, VIEWPORTS["desktop"])["width"] * schaal
    return {
        "formaat_px": [int(W), int(H)],
        "verwachte_breedte_px": int(verwacht_b),
        "breder_dan_viewport": bool(W > verwacht_b * 1.03),
        "pagina_hoogte_css_px": int(round(H / schaal)),
        "dominante_kleur": _hex(dom_kleur),
        "dominante_aandeel": round(dom_aandeel, 4),
        "inkt_aandeel": round(ink_totaal / px, 4),
        "structuur_aandeel": round(edge_totaal / px, 4),
        "effen_wit_aandeel": round(wit_totaal / px, 4),
        "effen_blokken_aandeel": round(effen_blokken / max(1, blokken_totaal), 4),
        "lege_rijen_aandeel": round(float(leeg_rij.mean()), 4),
        "langste_lege_band_css_px": int(round(langste / schaal)),
        "langste_lege_band_aandeel": round(langste / H, 4),
        "grote_lege_banden_aandeel": round(grote / H, 4),
        "lege_staart_css_px": int(round(staart / schaal)),
        "lege_staart_aandeel": round(staart / H, 4),
        "overlay": overlay,
    }


# ===========================================================================
# 3. Tekstmetingen (foutpagina, botmuur, taal)
# ===========================================================================
FOUTPATRONEN: list[tuple[str, str]] = [
    (r"access denied|toegang geweigerd|toegang ontzegd|\bforbidden\b|"
     r"you don.t have permission to access|geen toegang tot deze pagina", "toegang_geweigerd"),
    (r"just a moment|checking your browser|verif(y|ying) (that )?you are (a )?human|"
     r"verify you are not a robot|are you a robot|not a robot|captcha|attention required|"
     r"security check|je browser wordt gecontroleerd|bevestig dat je (een mens|geen robot)|"
     r"\beven geduld\b|please wait while we|ddos protection|pardon our interruption|"
     r"unusual traffic|request blocked|sorry, you have been blocked|bot detected|incapsula|"
     r"errors\.edgesuite|reference #\d", "botmuur_of_captcha"),
    (r"page not found|pagina niet gevonden|deze pagina bestaat niet|"
     r"this page (doesn.t|does not) exist|no longer exists|\b404\b", "niet_gevonden"),
    (r"502 bad gateway|503 service|service unavailable|internal server error|"
     r"we.ll be right back|werk aan de winkel|even niet bereikbaar|tijdelijk niet beschikbaar|"
     r"onderhoudswerk|under maintenance|\bstoring\b", "server_of_onderhoud"),
    (r"enable javascript|javascript is (required|disabled|uitgeschakeld)|"
     r"you need to enable javascript|zet javascript aan", "javascript_niet_gerenderd"),
]
LOGIN_URL_RE = re.compile(r"(/|\.)(login|log-in|signin|sign-in|inloggen|auth|sso|oauth|"
                          r"consent|cookiewall|cookie-wall|privacy-gate)(/|\?|$|\.)", re.I)

NL_WOORDEN = set("de het een en van voor met op in is niet je we te zijn om bij naar ook of "
                 "dat die als aan uw ons onze meer nog kan wordt worden door over dan".split())
EN_WOORDEN = set("the and of to for with in is you your are on this that it as be or by an "
                 "from at we our can will more not all".split())


def raad_taal(tekst: str) -> str | None:
    """'nl' of 'en' aan de hand van stopwoorden; None als het niet duidelijk is."""
    woorden = re.findall(r"[a-zà-ÿ']+", tekst.lower())[:1500]
    if len(woorden) < 25:
        return None
    nl = sum(1 for w in woorden if w in NL_WOORDEN)
    en = sum(1 for w in woorden if w in EN_WOORDEN)
    if nl >= 1.5 * max(en, 1) and nl >= 6:
        return "nl"
    if en >= 1.5 * max(nl, 1) and en >= 6:
        return "en"
    return None


def zoek_foutpatroon(titel: str, h1: str, tekst: str, d: Drempels = DREMPELS) -> str | None:
    """Naam van het eerste foutpatroon, of None. In lange pagina's telt alleen titel/h1."""
    kop = f"{titel} {h1}".lower()
    kort = len(tekst) <= d.max_tekst_voor_foutpatroon
    hooi = kop + (" " + tekst[:1200].lower() if kort else "")
    for patroon, naam in FOUTPATRONEN:
        if re.search(patroon, hooi):
            return naam
    return None


# ===========================================================================
# 4. DOM-metingen en cookie-afhandeling (op het opnamemoment)
# ===========================================================================
DOM_INFO_JS = r"""
() => {
  const vw = window.innerWidth, vh = window.innerHeight, va = vw * vh;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const lichaam = document.body ? norm(document.body.innerText) : '';
  // Sterke woorden bewijzen zelf een consent-tekst. Zwakke woorden ('partners', 'privacy') staan ook in de
  // menubalk van gewone sites en tellen alleen mee in een korte tekst. ACTIE met woordgrenzen: 'Management'
  // en 'Save both' in een sticky header zijn geen 'beheer'- of 'opslaan'-knop van een cookiebanner.
  const COOKIE_STERK = /(cookie|consent|toestemming|gdpr|\bavg\b|tracking)/i;
  const COOKIE_ZWAK = /(privacy|voorkeuren|personali[sz]|advertentie|partners|trackers)/i;
  const ACTIE = /\b(accept\w*|akkoord|weiger\w*|reject\w*|decline\w*|allow\w*|toestaan|instellen|beheer\w*|manage|customi[sz]e|opslaan|save|alles|alle cookies)\b/i;
  const CMP_NAAM = /(cookie|consent|cmp|gdpr|onetrust|didomi|usercentrics|sp_message|qc-cmp|truste|cookiebot|osano|privacy-gate)/i;
  const alpha = c => { const m = (c || '').match(/rgba?\(([^)]+)\)/); if (!m) return c === 'transparent' ? 0 : 1;
                       const p = m[1].split(',').map(parseFloat); return p.length > 3 ? p[3] : 1; };
  const bevat = (el, knoop) => { let n = knoop; while (n) { if (n === el) return true;
                       n = n.parentNode || (n.getRootNode && n.getRootNode().host) || null; } return false; };
  const bevatHoofd = el => !!(el.querySelector && el.querySelector('main, [role="main"], h1'));
  const overlays = [];
  const bezoek = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) bezoek(el.shadowRoot);
      let cs; try { cs = getComputedStyle(el); } catch (e) { continue; }
      const pos = cs.position;
      const dialoog = !!(el.matches && el.matches('dialog[open],[role="dialog"],[role="alertdialog"],[aria-modal="true"]'));
      const z = parseInt(cs.zIndex) || 0;
      if (!(pos === 'fixed' || pos === 'sticky' || dialoog || (pos === 'absolute' && z >= 100))) continue;
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.05) continue;
      const r = el.getBoundingClientRect();
      const x0 = Math.max(0, r.left), y0 = Math.max(0, r.top), x1 = Math.min(vw, r.right), y1 = Math.min(vh, r.bottom);
      const opp = Math.max(0, x1 - x0) * Math.max(0, y1 - y0);
      if (opp < 0.01 * va) continue;
      const tekst = norm(el.innerText || el.textContent);
      const wortel = el.getRootNode();
      const raak = (wortel.elementFromPoint ? wortel.elementFromPoint(vw / 2, vh / 2) : document.elementFromPoint(vw / 2, vh / 2));
      const bedektMidden = !!(raak && bevat(el, raak));
      const bek = opp / va;
      const naam = (el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '');
      const cookieTekst = COOKIE_STERK.test(tekst) || (COOKIE_ZWAK.test(tekst) && tekst.length < 500);
      const cookie = (cookieTekst && ACTIE.test(tekst) && tekst.length < 1500) || (CMP_NAAM.test(naam) && bek >= 0.02);
      const bg = alpha(cs.backgroundColor);
      const dim = bek >= 0.6 && ((bg >= 0.05 && bg < 0.95) || (cs.backdropFilter && cs.backdropFilter !== 'none'))
                  && cs.pointerEvents !== 'none';
      const opaak = bek >= 0.8 && bg >= 0.95 && tekst.length < 300 && !bevatHoofd(el) && z >= 1;
      const appSchil = bevatHoofd(el) || (lichaam.length > 500 && tekst.length > 0.5 * lichaam.length);
      const reden = [];
      if (dialoog && bek >= 0.05) reden.push('dialoog');
      if (cookie && bek >= 0.01) reden.push('cookiebanner');
      // een dim-laag die het scherm voor >= 90% bedekt is een modal-achtergrond, ook als de dialoog zelf een
      // sibling is (dan is het element in het midden de dialoog en niet deze laag)
      if (dim && (bedektMidden || bek >= 0.9)) reden.push('dim_laag');
      if (opaak && bedektMidden) reden.push('vol_scherm_laag');
      if (!reden.length) continue;
      if (appSchil && !cookie) continue;
      overlays.push({tag: el.tagName.toLowerCase(), id: (el.id || '').slice(0, 60),
        klasse: (typeof el.className === 'string' ? el.className : '').slice(0, 80),
        rol: el.getAttribute('role') || null, bedekking: Math.round(bek * 1000) / 1000,
        reden, cookie, tekst: tekst.slice(0, 100)});
    }
  };
  try { bezoek(document); } catch (e) {}
  // Zichtbare invoerelementen (keuzerondjes, velden, selects; zoekvelden tellen niet mee). Een aangepast
  // keuzerondje heeft vaak een onzichtbare native input: dan telt zijn label.
  let bediening = 0;
  try {
    const zichtbaar = (e) => {
      if (!e) return false;
      const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
      return r.width >= 8 && r.height >= 8 && cs.visibility !== 'hidden' && cs.display !== 'none'
             && parseFloat(cs.opacity) > 0.05 && r.bottom > 0 && r.right > 0 && r.left < vw;
    };
    const kandidaten = document.querySelectorAll(
      'input:not([type=hidden]):not([type=search]), select, textarea, [role=radio], [role=checkbox], ' +
      '[role=textbox], [role=combobox], [role=switch], [role=slider], [role=spinbutton]');
    for (const el of Array.from(kandidaten).slice(0, 400)) {
      const lab = el.closest('label') || (el.id ? document.querySelector('label[for="' + el.id.replace(/"/g, '') + '"]') : null);
      if (zichtbaar(el) || zichtbaar(lab)) bediening++;
    }
  } catch (e) {}
  const h1 = document.querySelector('h1');
  const html = document.documentElement, body = document.body;
  const csH = getComputedStyle(html), csB = body ? getComputedStyle(body) : null;
  const vergrendeld = csH.overflow === 'hidden' || csH.overflowY === 'hidden' ||
                      (csB && (csB.overflow === 'hidden' || csB.overflowY === 'hidden' || csB.position === 'fixed'));
  // Alleen een ZICHTBARE, echt grote captcha telt. Veel gewone pagina's laden een onzichtbare
  // (0x0) reCAPTCHA/hCaptcha-iframe; dat is geen botmuur (dit was een vals positief bij Stripe).
  const captchaEl = Array.from(document.querySelectorAll('iframe[src*="captcha" i], iframe[src*="challenges.cloudflare" i], iframe[title*="captcha" i], .g-recaptcha, .h-captcha, .cf-turnstile, #cf-challenge-running, #challenge-form')).some(e => {
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return r.width >= 120 && r.height >= 50 && cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity) > 0.1
           && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
  });
  return {
    titel: document.title || '', h1: h1 ? norm(h1.innerText).slice(0, 120) : '',
    contentType: document.contentType || '', aantal_elementen: document.getElementsByTagName('*').length,
    tekst_tekens: lichaam.length, tekst_monster: lichaam.slice(0, 4000), bediening_zichtbaar: bediening,
    innerWidth: vw, innerHeight: vh, scroll_vergrendeld: !!vergrendeld, captcha_element: captchaEl,
    pagina_hoogte: Math.max(body ? body.scrollHeight : 0, html.scrollHeight),
    overlays,
  };
}
"""

# Bekende consent-knoppen, exact geadresseerd - veiliger dan op tekst zoeken.
BEKENDE_ACCEPT_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    "#cookiescript_accept",
    "#hs-eu-confirmation-button",
    ".osano-cm-accept-all",
    "[data-testid='uc-accept-all-button']",
    "[data-cky-tag='accept-button']",
    "#didomi-notice-agree-button",
    "button[aria-label*='Accept all' i]",
    "button[aria-label*='Alles accepteren' i]",
]
# Volgorde is belangrijk: specifiek eerst. 'Doorgaan'/'Continue' alleen als laatste redmiddel.
ACCEPT_TEKSTEN = [
    "Accept all cookies", "Accept all", "Allow all cookies", "Allow all", "Accept cookies",
    "Accepteer alle cookies", "Accepteer alle",
    "Alles accepteren", "Accepteer alles", "Alle cookies accepteren", "Alle cookies toestaan",
    "Cookies accepteren", "Accepteer cookies", "Alles toestaan", "Ja, ik accepteer",
    "Ik ga akkoord", "Accepteren", "Accepteer", "Akkoord", "Accept", "I agree", "Got it",
    "Understood", "Begrepen", "Zustimmen", "Alle akzeptieren", "Tout accepter",
    "Doorgaan", "Continue",
]

HIDE_CSS = """
#onetrust-consent-sdk, #onetrust-banner-sdk, .onetrust-pc-dark-filter,
#CybotCookiebotDialog, #CybotCookiebotDialogBodyUnderlay, #cookiescript_injected,
#didomi-host, .didomi-popup-open, #didomi-popup, #didomi-notice,
#usercentrics-root, #usercentrics-cmp-ui, #cmpbox, #cmpbox2, #hs-eu-cookie-confirmation,
.osano-cm-window, .cc-window, .cc-banner, .truste_overlay, .truste_box_overlay,
.qc-cmp2-container, #sp_message_container_1, [id^="sp_message_container"],
[id*="cookie-banner"], [class*="cookie-banner"], [class*="CookieBanner"], .cookie-banner,
[id*="cookie-consent"], [class*="cookie-consent"], [class*="CookieConsent"], .cookie-consent,
[id*="cookiewall"], [class*="cookie-wall"], .cookie-overlay, .consent-modal {
  display: none !important;
}
"""
WIDGET_CSS = """
#hubspot-messages-iframe-container, #intercom-container, .intercom-lightweight-app,
iframe[title*="Intercom" i], iframe[title*="Drift" i], #drift-frame-controller { display: none !important; }
"""
FREEZE_CSS = """
html { scrollbar-width: none !important; }
*, *::before, *::after {
  animation-duration: 0.001s !important; animation-delay: 0s !important;
  animation-iteration-count: 1 !important; transition-duration: 0.001s !important;
  transition-delay: 0s !important; scroll-behavior: auto !important; caret-color: transparent !important;
}
"""
ONTGRENDEL_JS = """() => {
  const st = document.createElement('style');
  st.textContent = 'html,body{overflow:visible !important;position:static !important;height:auto !important;}';
  document.head.appendChild(st);
}"""
# Verbergt ALLEEN consent-achtige overlays (en hun losse dim-laag); nooit login- of betaalmuren.
VERBERG_CONSENT_JS = r"""
() => {
  const vw = innerWidth, vh = innerHeight;
  const re = /(cookie|consent|toestemming|gdpr|cmp|onetrust|didomi|usercentrics|cookiebot|osano|truste|sp_message|privacy-gate)/i;
  const tekstRe = /(cookie|consent|toestemming|gdpr)/i;
  let n = 0;
  const loop = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) loop(el.shadowRoot);
      let cs; try { cs = getComputedStyle(el); } catch (e) { continue; }
      if (!['fixed', 'sticky', 'absolute'].includes(cs.position)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 60 || r.height < 30 || r.width * r.height > vw * vh * 1.01) continue;
      const naam = (el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '');
      const t = (el.innerText || '').trim();
      if (!(re.test(naam) || (t.length > 0 && t.length < 1500 && tekstRe.test(t)))) continue;
      el.style.setProperty('display', 'none', 'important'); n++;
    }
  };
  loop(document);
  // de dim-laag die er meestal los bij zit (alleen als er een consent-element is weggehaald)
  if (n > 0) {
    for (const el of document.querySelectorAll('body *')) {
      const cs = getComputedStyle(el);
      if (cs.position !== 'fixed') continue;
      const r = el.getBoundingClientRect();
      if (r.width >= vw * 0.98 && r.height >= vh * 0.98 && (el.innerText || '').trim().length < 20) {
        const b = cs.backgroundColor; const m = b.match(/rgba?\(([^)]+)\)/);
        const a = m ? (m[1].split(',').length > 3 ? parseFloat(m[1].split(',')[3]) : 1) : 0;
        if (a > 0.05 || (cs.backdropFilter && cs.backdropFilter !== 'none')) { el.style.setProperty('display', 'none', 'important'); n++; }
      }
    }
  }
  return n;
}
"""


def verrijk_dom(info: dict[str, Any], d: Drempels = DREMPELS) -> dict[str, Any]:
    """Voegt de afgeleide velden toe die we bewaren (zodat herberekenen zonder browser kan)."""
    info = dict(info)
    info["fout_patroon"] = zoek_foutpatroon(info.get("titel", ""), info.get("h1", ""),
                                            info.get("tekst_monster", ""), d)
    info["taal_gemeten"] = raad_taal(info.get("tekst_monster", ""))
    info["tekst_begin"] = (info.get("tekst_monster") or "")[:240]
    return info


INVOER_ROLLEN = ("radio", "checkbox", "textbox", "combobox", "spinbutton", "slider", "switch")


def tel_invoerelementen(page) -> int:
    """
    Aantal invoerelementen in de toegankelijkheidsboom (keuzerondjes, velden, selects, schakelaars). Playwright
    kijkt ook door open shadow-DOM heen; dat is nodig voor webcomponenten (bijvoorbeeld de a.s.r.-calculator),
    waarvan de keuzerondjes onzichtbare helperelementen zonder afmeting zijn. Zoekvelden (rol searchbox) tellen
    niet mee.
    """
    n = 0
    for rol in INVOER_ROLLEN:
        try:
            n += page.get_by_role(rol).count()
        except Exception:
            continue
    return n


def verzamel_dom_info(page) -> dict[str, Any]:
    """DOM-feiten op het moment van opnemen. Nooit een uitzondering: minimaal dict bij falen."""
    try:
        info = page.evaluate(DOM_INFO_JS)
    except Exception as exc:  # pagina kan midden in een navigatie zitten
        return {"fout": f"dom-meting mislukt: {str(exc).splitlines()[0][:120]}", "overlays": [],
                "tekst_tekens": 0, "tekst_monster": "", "titel": "", "h1": ""}
    # alleen als de tekst schaars is telt het aantal invoerelementen mee (zie Drempels.min_bediening_bij_weinig_tekst)
    if info.get("tekst_tekens", 10 ** 9) < DREMPELS.min_tekst_tekens:
        info["bediening_zichtbaar"] = max(info.get("bediening_zichtbaar") or 0, tel_invoerelementen(page))
    return info


def blokkerende_overlays(info: dict[str, Any]) -> list[dict[str, Any]]:
    return list(info.get("overlays") or [])


def _host(url: str) -> str:
    m = re.match(r"https?://([^/:?#]+)", url or "")
    h = (m.group(1).lower() if m else "")
    return h[4:] if h.startswith("www.") else h


def host_geblokkeerd(url: str) -> str | None:
    """Reden als de host in de lijst van bekend geblokkeerde hosts staat, anders None."""
    h = _host(url)
    for sleutel, reden in BEKEND_GEBLOKKEERD.items():
        if h == sleutel or h.endswith("." + sleutel):
            return reden
    return None


def _pad_zonder_hash(url: str) -> str:
    return (url or "").split("#")[0].rstrip("/")


def _probeer_klik(page, oorspronkelijke_url: str | None = None) -> str | None:
    """
    Klik een accepteer-knop. Geeft de knoptekst terug, of None.
    Wordt ALLEEN aangeroepen als de DOM een consent-overlay laat zien. Klikt de pagina
    daardoor naar een andere URL (zoals een footerlink 'Accept'), dan gaan we terug en telt
    het niet als klik. 'Terug' is de URL van vlak VOOR de klik, niet de start-URL van de bron:
    na scriptstappen die zelf naar een andere pagina navigeerden (een formulierflow) zou de
    start-URL de bereikte staat vernietigen (`oorspronkelijke_url` blijft voor compatibiliteit).
    """
    voor_url = page.url
    frames = [page] + [f for f in page.frames if f != page.main_frame]
    for frame in frames:
        for sel in BEKENDE_ACCEPT_SELECTORS:
            try:
                loc = frame.locator(sel).first
                if loc.count() and loc.is_visible(timeout=400):
                    loc.click(timeout=2000)
                    page.wait_for_timeout(700)
                    return f"selector {sel}"
            except Exception:
                continue

    def klik(loc, tekst: str) -> str | None:
        """Klikt een kandidaat als hij zichtbaar en klein genoeg is. None = niet geklikt of verkeerde klik."""
        if not loc.count() or not loc.is_visible(timeout=400):
            return None
        doos = loc.bounding_box()
        if not doos or doos["width"] > 420:              # brede knop = waarschijnlijk geen consent-knop
            return None
        loc.click(timeout=2000)
        page.wait_for_timeout(700)
        if _pad_zonder_hash(page.url) != _pad_zonder_hash(voor_url):
            page.goto(voor_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            return "TERUG"                               # verkeerde klik; terug
        return tekst

    for frame in frames:
        for tekst in ACCEPT_TEKSTEN:
            naam = re.compile(re.escape(tekst), re.I)
            # rol knop, dan rol link, dan elk element waarvan de HELE tekst de knoptekst is (bijvoorbeeld een <a>
            # zonder href of een <div> met een click-handler: die hebben geen rol en vielen eerst buiten de boot)
            for zoek in (lambda n=naam: frame.get_by_role("button", name=n),
                         lambda n=naam: frame.get_by_role("link", name=n),
                         lambda t=tekst: frame.get_by_text(re.compile(r"^\s*" + re.escape(t) + r"\s*$", re.I))):
                try:
                    uitkomst = klik(zoek().first, tekst)
                except Exception:
                    continue
                if uitkomst == "TERUG":
                    return None
                if uitkomst:
                    return uitkomst
    return None


# Sluitknoppen van dialogen die GEEN consent zijn (bijvoorbeeld een enquete-uitnodiging).
SLUIT_SELECTORS = [
    f"{d} {b}" for d in ("[role=dialog]", "[role=alertdialog]", "dialog[open]", "[aria-modal=true]")
    for b in ("button[aria-label*='sluit' i]", "button[aria-label*='close' i]",
              "button[title*='sluit' i]", "button[title*='close' i]", "button.close",
              "[data-dismiss]", "[data-bs-dismiss]")
]
# Een dialoog met deze woordenschat is een login-, betaal- of aanmeldmuur: NOOIT wegklikken.
NIET_SLUITEN_RE = re.compile(r"inlog|log in|log-in|login|sign in|sign-in|signin|aanmeld|account|"
                             r"abonn|subscribe|betaal|premium|paywall|wachtwoord|password|registr|word lid",
                             re.I)


def _sluit_dialoog(page) -> dict[str, str] | None:
    """Sluit een niet-consent dialoog via zijn eigen sluitknop, tenzij het een login-/betaalmuur is."""
    for sel in SLUIT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if not loc.count() or not loc.is_visible(timeout=300):
                continue
            tekst = loc.evaluate(
                "el => { const d = el.closest('[role=dialog],[role=alertdialog],dialog,[aria-modal=true]');"
                " return (d ? d.innerText : '').replace(/\\s+/g, ' ').trim(); }")
            if NIET_SLUITEN_RE.search(tekst or ""):
                continue
            loc.click(timeout=2000)
            page.wait_for_timeout(700)
            return {"selector": sel, "dialoogtekst": (tekst or "")[:100]}
        except Exception:
            continue
    return None


# Generieke zoeker voor pop-ups zonder role="dialog" (bijvoorbeeld een nieuwsbriefvenster): zoekt binnen het
# BUITENSTE vaste element dat het midden van het scherm bedekt naar een kleine knop die zichzelf 'sluiten' noemt.
ZOEK_SLUITKNOP_JS = r"""
() => {
  const vw = innerWidth, vh = innerHeight;
  const start = document.elementFromPoint(vw / 2, vh / 2);
  let cont = null;
  for (let n = start; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
    if (getComputedStyle(n).position === 'fixed') cont = n;
  }
  if (!cont) return null;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const NAAM = /^(x|\u00d7|\u2715|\u2716|close|sluiten|sluit|dismiss|niet nu|no thanks|nee,? bedankt|not now)$/i;
  document.querySelectorAll('[data-opname-sluit]').forEach(e => e.removeAttribute('data-opname-sluit'));
  let gekozen = null;
  for (const e of cont.querySelectorAll('button, [role=button], a')) {
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    if (r.width < 8 || r.height < 8 || r.width > 120 || r.height > 120) continue;
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const namen = [e.getAttribute('aria-label'), e.getAttribute('title'), norm(e.innerText)];
    const cls = typeof e.className === 'string' ? e.className : '';
    if (namen.some(t => t && NAAM.test(t.trim())) || /(^|[-_ ])(close|dismiss)/i.test(cls)) { gekozen = e; break; }
  }
  if (!gekozen) return null;
  gekozen.setAttribute('data-opname-sluit', '1');
  return {tekst: norm(cont.innerText).slice(0, 600)};
}
"""


def _sluit_generiek(page) -> dict[str, str] | None:
    """Sluit een pop-up zonder dialoogrol via zijn eigen sluitknop, tenzij het een login-/betaalmuur is."""
    try:
        res = page.evaluate(ZOEK_SLUITKNOP_JS)
    except Exception:
        return None
    if not res or NIET_SLUITEN_RE.search(res.get("tekst", "")):
        return None
    try:
        page.locator('[data-opname-sluit="1"]').first.click(timeout=2000)
        page.wait_for_timeout(700)
    except Exception:
        return None
    return {"selector": "sluitknop in het bovenste vaste element", "dialoogtekst": res["tekst"][:100]}


def _kort(o: dict[str, Any]) -> dict[str, Any]:
    return {k: o.get(k) for k in ("tag", "id", "reden", "bedekking", "tekst")}


def ruim_cookiebanner_op(page, oorspronkelijke_url: str) -> dict[str, Any]:
    """
    Verwijdert een cookiebanner/-wall of een onschuldige dialoog en MEET of dat gelukt is.

    Er wordt alleen iets gedaan als de DOM een blokkerende overlay laat zien (dus geen blind
    klikken op 'Accept'-knoppen):
      1. bij een consent-overlay: klikken op de accepteer-knop; lukt dat niet, dan bekende
         containers met CSS verbergen, dan consent-achtige overlays met JS verbergen;
      2. blijft er daarna een niet-consent dialoog over (bijvoorbeeld een enquete-uitnodiging):
         sluiten via zijn eigen sluitknop, mits het geen login-/betaal-/aanmeldmuur is.
    Login-, betaal- en aanmeldmuren worden NOOIT weggehaald: die blijven staan en veroorzaken
    een afkeuring. Er wordt nergens iets ingevuld of ingediend.
    Het resultaat is de enige bron voor een bewering over cookies/overlays in het manifest.
    """
    res: dict[str, Any] = {"actie": "geen_banner", "knop": None, "verborgen_via": None,
                           "blokkerend_voor": 0, "blokkerend_na": 0, "schoon_na_meting": True,
                           "stappen": []}
    voor = blokkerende_overlays(verzamel_dom_info(page))
    res["blokkerend_voor"] = len(voor)
    if voor:
        res["voor"] = [_kort(o) for o in voor][:4]
        na = voor
        st = res["stappen"]
        if any(o.get("cookie") for o in voor):
            knop = _probeer_klik(page, oorspronkelijke_url)
            na = blokkerende_overlays(verzamel_dom_info(page))
            if knop:
                st.append({"actie": "geklikt", "knop": knop, "overlays_daarna": len(na)})
                res["knop"] = knop
            if na:
                try:
                    page.add_style_tag(content=HIDE_CSS)
                except Exception:
                    pass
                n2 = blokkerende_overlays(verzamel_dom_info(page))
                if len(n2) < len(na) or not n2:
                    st.append({"actie": "css_verborgen", "overlays_daarna": len(n2)})
                    res["verborgen_via"] = "bekende_selectors"
                na = n2
            if na:
                try:
                    n = page.evaluate(VERBERG_CONSENT_JS)
                except Exception:
                    n = 0
                n3 = blokkerende_overlays(verzamel_dom_info(page))
                if n and len(n3) < len(na):
                    st.append({"actie": "js_verborgen", "elementen": n, "overlays_daarna": len(n3)})
                    res["verborgen_via"] = f"consent-overlays via JS ({n} elementen)"
                na = n3
        if na:
            g = _sluit_dialoog(page) or _sluit_generiek(page)
            if g:
                na = blokkerende_overlays(verzamel_dom_info(page))
                st.append({"actie": "gesloten", **g, "overlays_daarna": len(na)})
        if st:
            try:
                if verzamel_dom_info(page).get("scroll_vergrendeld"):
                    page.evaluate(ONTGRENDEL_JS)
                    res["scroll_slot_opgeheven"] = True
            except Exception:
                pass
        res["blokkerend_na"] = len(na)
        res["schoon_na_meting"] = len(na) == 0
        if na:
            res["actie"] = "niet_verwijderd"
            res["na"] = [_kort(o) for o in na][:4]
        elif st:
            res["actie"] = st[-1]["actie"]
        else:
            res["actie"] = "vanzelf_verdwenen"
    try:
        page.add_style_tag(content=WIDGET_CSS)          # chatwidgets: geen blokkade, wel ruis
    except Exception:
        pass
    return res


def samenvoegen_cookies(c1: dict[str, Any], c2: dict[str, Any]) -> dict[str, Any]:
    """
    Twee opruimrondes (na laden en na scrollen) tot een uitspraak. De TWEEDE meting is de laatste voor de
    opname en bepaalt dus of het beeld schoon is; de eerste is alleen historie.
    """
    if c1["actie"] == "geen_banner":
        return c2
    if c2["actie"] == "geen_banner":
        if c1["actie"] == "niet_verwijderd":
            # De overlay stond bij de eerste meting nog en de opruiming kon hem niet weghalen, maar bij de
            # tweede meting is er geen meer: hij is tussen de metingen verdwenen (een scriptstap zoals een
            # 'Got it'-klik, het scrollen, of de pagina zelf). De eerste versie van deze functie gaf hier
            # 'niet_verwijderd' terug en keurde daarmee een schone opname af.
            samen = dict(c1)
            samen.pop("na", None)
            samen.update(actie="verdwenen_tussen_metingen", blokkerend_na=0, schoon_na_meting=True)
            return samen
        return c1
    samen = dict(c2)
    samen["stappen"] = list(c1.get("stappen", [])) + list(c2.get("stappen", []))
    samen["blokkerend_voor"] = c1.get("blokkerend_voor", 0) + c2.get("blokkerend_voor", 0)
    samen["knop"] = c2.get("knop") or c1.get("knop")
    return samen


def cookie_beschrijving(c: dict[str, Any]) -> str:
    """De ENIGE bron voor een uitspraak over cookies/overlays: uitsluitend uit meetwaarden."""
    actie = c.get("actie")
    if actie == "geen_banner":
        return "Geen blokkerende cookiebanner of overlay aangetroffen (DOM gemeten); niets geklikt, gesloten of verborgen."
    delen = []
    for s in c.get("stappen", []):
        a = s.get("actie")
        if a == "geklikt":
            delen.append(f"geklikt op '{s.get('knop')}' ({s.get('overlays_daarna')} blokkerende overlay(s) daarna)")
        elif a == "css_verborgen":
            delen.append(f"consent-container met CSS verborgen ({s.get('overlays_daarna')} daarna)")
        elif a == "js_verborgen":
            delen.append(f"consent-overlay met JS verborgen ({s.get('overlays_daarna')} daarna)")
        elif a == "gesloten":
            delen.append(f"dialoog '{s.get('dialoogtekst', '')[:60]}' gesloten via zijn sluitknop, niets ingevuld "
                         f"({s.get('overlays_daarna')} daarna)")
    if actie == "niet_verwijderd":
        return (f"NIET verwijderd: {c.get('blokkerend_na')} blokkerende overlay(s) bleven staan "
                f"(voor: {c.get('blokkerend_voor')}); geprobeerd: {'; '.join(delen) or 'niets'}.")
    if actie == "vanzelf_verdwenen":
        return "Blokkerende overlay was bij de tweede meting vanzelf verdwenen; niets gedaan."
    if actie == "verdwenen_tussen_metingen":
        return (f"Bij een eerdere meting stond {c.get('blokkerend_voor')} blokkerende overlay(s) die de opruiming niet "
                f"kon weghalen ({'; '.join(delen) or 'niets gelukt'}); bij de laatste meting, na een pauze en/of "
                f"scriptstappen (zie `stappen` in het record) en het scrollen, waren het er 0 (bijvoorbeeld een "
                f"laadscherm dat wegfadet).")
    return f"{'; '.join(delen)}. Daarna gemeten: 0 blokkerende overlays (voor: {c.get('blokkerend_voor')})."


# ===========================================================================
# 5. Capture (gedeeld door capture_comps.py, capture_comps_nl.py en capture_anker.py)
# ===========================================================================
def start_browser(pw):
    """Chromium met TLS 1.2 (de egress-proxy verdraagt Chromium's TLS 1.3 ClientHello niet),
    de proxy aan en certificaatverificatie AAN. Geen stealth-vlaggen."""
    return pw.chromium.launch(
        executable_path=CHROME, headless=True,
        proxy={"server": PROXY} if PROXY else None,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--ssl-version-max=tls1.2",
              "--hide-scrollbars", "--force-color-profile=srgb", "--font-render-hinting=none",
              "--disable-features=EncryptedClientHello,UseDnsHttpsSvcb,UseDnsHttpsSvcbAlpn"])


def maak_context(browser, viewport_naam: str, *, locale: str = "en-US",
                 accept_language: str = "en-US,en;q=0.9"):
    mobiel = viewport_naam == "mobile"
    return browser.new_context(
        viewport=VIEWPORTS[viewport_naam], device_scale_factor=DEVICE_SCALE,
        is_mobile=mobiel, has_touch=mobiel, locale=locale, timezone_id="Europe/Amsterdam",
        reduced_motion="reduce", user_agent=UA_MOBIEL if mobiel else UA_DESKTOP,
        extra_http_headers={"Accept-Language": accept_language})


def autoscroll(page, stap_ms: int = 120) -> None:
    """Door de pagina scrollen zodat lazy-loaded inhoud inlaadt, daarna terug naar boven."""
    try:
        page.evaluate(
            """async (stapMs) => {
              const step = Math.max(400, window.innerHeight * 0.8);
              const max = Math.min(document.body.scrollHeight, 40000);
              for (let y = 0; y < max; y += step) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, stapMs));
              }
              window.scrollTo(0, 0);
              await new Promise(r => setTimeout(r, 400));
            }""", stap_ms)
    except Exception:
        pass


def _stappen_uitvoeren(page, stappen: list[dict[str, Any]] | None) -> list[str]:
    """
    Kleine stappenrunner om een echte formulier-/resultaatstaat te bereiken (zoeken, klikken). Stappen:
      {"fill": css, "value": tekst}    een publiek zoekveld vullen (nooit persoonsgegevens)
      {"click": css}                   klikken op een element
      {"klik_tekst": naam}             klikken op een knop of link met deze naam (ook binnen shadow-DOM)
      {"press": toets}, {"wait": ms}
    Elke stap komt met uitkomst (ok of MISLUKT) in het record; een mislukte stap breekt niets af.
    """
    log: list[str] = []
    for st in stappen or []:
        try:
            if "fill" in st:
                page.locator(st["fill"]).first.fill(st["value"], timeout=8000)
            elif "click" in st:
                page.locator(st["click"]).first.click(timeout=8000)
            elif "klik_tekst" in st:
                naam = re.compile(re.escape(st["klik_tekst"]), re.I)
                loc = page.get_by_role("button", name=naam).first
                if not loc.count():
                    loc = page.get_by_role("link", name=naam).first
                loc.click(timeout=8000)
            elif "press" in st:
                page.keyboard.press(st["press"])
            elif "wait" in st:
                page.wait_for_timeout(st["wait"])
            log.append("ok: " + json.dumps(st, ensure_ascii=False))
        except Exception as exc:
            log.append(f"MISLUKT ({json.dumps(st, ensure_ascii=False)}): {type(exc).__name__}")
    if stappen:
        page.wait_for_timeout(1500)
    return log


def neem_screenshot(page, pad: Path, viewport_naam: str) -> dict[str, Any]:
    """Full-page opname; erg lange pagina's worden op MAX_PAGINA_CSS_PX afgekapt (en gemeld)."""
    try:
        h = int(page.evaluate("() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"))
    except Exception:
        h = 0
    uit: dict[str, Any] = {"pagina_hoogte_css_px": h}
    # 90 s in plaats van de standaard 30 s: zware pagina's (video, canvas) halen de standaardtijd niet
    if h > MAX_PAGINA_CSS_PX:
        uit["afgekapt_op_px"] = MAX_PAGINA_CSS_PX
        page.screenshot(path=str(pad), full_page=True, animations="disabled", timeout=90000,
                        clip={"x": 0, "y": 0, "width": VIEWPORTS[viewport_naam]["width"],
                              "height": MAX_PAGINA_CSS_PX})
    else:
        page.screenshot(path=str(pad), full_page=True, animations="disabled", timeout=90000)
    return uit


def leg_vast(browser, kaart: dict[str, Any], viewport_naam: str, map_pad: Path, bestand: str, *,
             stappen: list[dict[str, Any]] | None = None, wacht_ms: int = 3000,
             locale: str = "en-US", accept_language: str = "en-US,en;q=0.9",
             d: Drempels = DREMPELS) -> dict[str, Any]:
    """
    Laadt de pagina, ruimt een cookiebanner op (gemeten), neemt de opname en verzamelt de
    DOM-feiten. Een HTTP-fout (403/429/407...) of een tunnelfout wordt gerespecteerd: geen
    tweede poging, geen omweg. Geeft `raw` voor `bouw_record`.
    """
    ctx = maak_context(browser, viewport_naam, locale=locale, accept_language=accept_language)
    page = ctx.new_page()
    page.set_default_timeout(30000)
    raw: dict[str, Any] = {"vastgelegd_op": nu_iso(), "fout": None}
    url = kaart["url"]
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        raw["http_status"] = resp.status if resp else None
        if resp and resp.status >= 400:
            raw["fout"] = f"HTTP {resp.status}"       # respecteren: overslaan, niet omzeilen
            return raw
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(wacht_ms)
        c1 = ruim_cookiebanner_op(page, url)
        try:
            page.add_style_tag(content=FREEZE_CSS)
        except Exception:
            pass
        if stappen:
            raw["stappen"] = _stappen_uitvoeren(page, stappen)
        autoscroll(page)
        c2 = ruim_cookiebanner_op(page, url)
        if c2["actie"] == "niet_verwijderd":
            # een laadscherm of uitfadende laag (bijvoorbeeld jQuery BlockUI na een klik in een formulierflow)
            # is een tijdelijke overlay: even wachten en opnieuw meten. Een echte wall blijft staan en keurt af.
            page.wait_for_timeout(2500)
            c2 = samenvoegen_cookies(c2, ruim_cookiebanner_op(page, url))
        raw["cookies"] = samenvoegen_cookies(c1, c2)
        page.wait_for_timeout(500)
        pad = map_pad / bestand
        raw.update(neem_screenshot(page, pad, viewport_naam))
        dom = verzamel_dom_info(page)
        raw["dom"] = verrijk_dom(dom, d)
        raw["eind_url"] = page.url
        # Scroll-geanimeerde pagina's: bij grote lege banden eenmalig langzamer scrollen en
        # opnieuw opnemen (zelfde lading, dus geen extra belasting van de site).
        meting = meet_beeld(pad, viewport_naam, vp_hoogte_css=dom.get("innerHeight"), d=d)
        if any(c in beoordeel(meting, None, d=d) for c in ("grote_lege_band", "lege_staart")):
            autoscroll(page, stap_ms=600)
            page.wait_for_timeout(800)
            raw.update(neem_screenshot(page, pad, viewport_naam))
            raw["traag_scrollen_herpoging"] = True
    except Exception as exc:
        raw["fout"] = str(exc).split("\n")[0][:220]
    finally:
        try:
            ctx.close()
        except Exception:
            pass
    return raw


# ===========================================================================
# 6. Beslissing
# ===========================================================================
def beoordeel(meting: dict[str, Any] | None, dom: dict[str, Any] | None, *,
              http_status: int | None = None, eind_url: str | None = None,
              vraag_url: str | None = None, fout: str | None = None,
              d: Drempels = DREMPELS) -> list[str]:
    """Lijst afkeurcodes. Leeg = de opname is schoon."""
    r: list[str] = []
    if fout:
        r.append("capture_mislukt")
    if http_status is not None and http_status >= 400:
        r.append(f"http_{http_status}")
    if dom is not None:
        fp = dom["fout_patroon"] if "fout_patroon" in dom else zoek_foutpatroon(
            dom.get("titel", ""), dom.get("h1", ""), dom.get("tekst_monster", ""), d)
        if fp:
            r.append(fp)
        if dom.get("captcha_element") and "botmuur_of_captcha" not in r:
            r.append("botmuur_of_captcha")
        tekens = dom.get("tekst_tekens", 10 ** 9)
        if tekens < d.min_tekst_tekens_leeg:
            r.append("vrijwel_geen_tekst")
        elif tekens < d.min_tekst_tekens and (dom.get("bediening_zichtbaar") or 0) < d.min_bediening_bij_weinig_tekst:
            # een titel en enkele links: geen substantieel scherm. Een formulierstap (kop, vraag, keuzes,
            # knoppen) is van nature schaars in tekst maar wel een volledige interface: die telt via de
            # zichtbare invoerelementen mee.
            r.append("te_weinig_tekst")
        ct = dom.get("contentType")
        if ct and ct not in ("text/html", "application/xhtml+xml"):
            r.append("geen_html_pagina")
        # een alternatieve platte-tekstweergave (bijvoorbeeld een markdown 'machineversie' voor
        # geautomatiseerde clients): veel tekst maar vrijwel geen DOM = geen gerenderde interface
        if dom.get("aantal_elementen") is not None and dom["aantal_elementen"] < 15 and tekens > d.min_tekst_tekens:
            r.append("platte_tekst_pagina")
        if blokkerende_overlays(dom):
            r.append("blokkerende_overlay_dom")
        if eind_url and vraag_url:
            if LOGIN_URL_RE.search(eind_url) and not LOGIN_URL_RE.search(vraag_url):
                r.append("omleiding_naar_consent_of_login")
            elif "consent" in _host(eind_url) and "consent" not in _host(vraag_url):
                r.append("omleiding_naar_consent_of_login")
    if meting:
        # De pagina loopt horizontaal over: Chromium schaalt de layout dan uit (bijvoorbeeld 980 css-px
        # in plaats van 390), waardoor de tekst in een mobiel beeld na het harnas onleesbaar klein wordt.
        if meting.get("breder_dan_viewport"):
            r.append("breder_dan_viewport")
        if meting["structuur_aandeel"] < d.min_structuur_aandeel or meting["inkt_aandeel"] < d.min_inkt_aandeel:
            r.append("bijna_leeg")
        elif meting["effen_blokken_aandeel"] > d.max_effen_blokken_aandeel:
            r.append("te_veel_effen_vlak")
        if (meting["grote_lege_banden_aandeel"] > d.max_grote_lege_banden_aandeel
                or (meting["langste_lege_band_css_px"] > d.max_langste_lege_band_css_px
                    and meting["langste_lege_band_aandeel"] > d.max_langste_lege_band_aandeel)):
            r.append("grote_lege_band")
        if meting["lege_staart_css_px"] > d.max_lege_staart_css_px and \
                meting["lege_staart_aandeel"] > d.max_lege_staart_aandeel:
            r.append("lege_staart")
        ov = meting.get("overlay", {})
        # Een helder blok midden in beeld is op zichzelf ook een ontwerppatroon (een wit formulierkaartje
        # op een gekleurde hero). Het telt daarom alleen als modal als het WORDT BEVESTIGD: door dimming
        # boven de vouw, of bij een kort scherm (geen pagina onder de vouw) met een echt donkere ring.
        kort_scherm = "vouwstap" not in ov
        if ov.get("dimming_boven_vouw"):
            r.append("dimming_boven_vouw")
        if ov.get("gecentreerd_blok") and (ov.get("dimming_boven_vouw")
                                           or (kort_scherm and ov.get("ring_mediaan", 255) <= 150)):
            r.append("gecentreerd_blok_in_beeld")
    return list(dict.fromkeys(r))


def controleer_opname(pad: str | Path | None, viewport_naam: str, *, dom: dict[str, Any] | None = None,
                      http_status: int | None = None, eind_url: str | None = None,
                      vraag_url: str | None = None, fout: str | None = None,
                      cookies: dict[str, Any] | None = None, schaal: int = DEVICE_SCALE,
                      d: Drempels = DREMPELS) -> dict[str, Any]:
    """Meet een opname en beslis. Geeft {'geladen_ok', 'afkeurredenen', 'controle'}."""
    meting: dict[str, Any] = {}
    if pad and Path(pad).exists() and not fout:
        vp = (dom or {}).get("innerHeight")
        meting = meet_beeld(pad, viewport_naam, schaal=schaal, vp_hoogte_css=vp, d=d)
    redenen = beoordeel(meting, dom, http_status=http_status, eind_url=eind_url,
                        vraag_url=vraag_url, fout=fout, d=d)
    if cookies and cookies.get("actie") == "niet_verwijderd" and "blokkerende_overlay_dom" not in redenen:
        redenen.append("blokkerende_overlay_dom")
    controle: dict[str, Any] = {"schema": SCHEMA_VERSIE, "controle_versie": CONTROLE_VERSIE,
                                "beeld": meting or None}
    if dom is not None:
        controle["dom"] = {
            "http_status": http_status, "eind_url": eind_url,
            "titel": dom.get("titel", "")[:120], "h1": dom.get("h1", ""),
            "tekst_tekens": dom.get("tekst_tekens"), "tekst_begin": dom.get("tekst_begin", ""),
            "bediening_zichtbaar": dom.get("bediening_zichtbaar"),
            "content_type": dom.get("contentType"), "aantal_elementen": dom.get("aantal_elementen"),
            "taal_gemeten": dom["taal_gemeten"] if "taal_gemeten" in dom else raad_taal(dom.get("tekst_monster", "")),
            "fout_patroon": dom["fout_patroon"] if "fout_patroon" in dom else zoek_foutpatroon(
                dom.get("titel", ""), dom.get("h1", ""), dom.get("tekst_monster", ""), d),
            "captcha_element": bool(dom.get("captcha_element")),
            "overlays_na": blokkerende_overlays(dom)[:4],
            "scroll_vergrendeld": dom.get("scroll_vergrendeld"),
            "inner_afmeting": [dom.get("innerWidth"), dom.get("innerHeight")],
        }
    if cookies is not None:
        controle["cookies"] = {**cookies, "beschrijving": cookie_beschrijving(cookies)}
    return {"geladen_ok": not redenen, "afkeurredenen": redenen, "controle": controle}


# ===========================================================================
# 7. Records en manifesten
# ===========================================================================
def nu_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def plaats_bestand(map_pad: Path, bestand: str, geladen_ok: bool) -> str | None:
    """Zet een PNG in <map>/ (goed) of <map>/_afgekeurd/ (afgekeurd). Geeft het relatieve pad."""
    hoofd = map_pad / bestand
    afg = map_pad / AFGEKEURD_MAP / bestand
    if geladen_ok:
        if afg.exists():
            if hoofd.exists():
                afg.unlink()                      # verouderde afgekeurde kopie van een eerdere run
            else:
                shutil.move(str(afg), str(hoofd))
        return bestand if hoofd.exists() else None
    if hoofd.exists():
        afg.parent.mkdir(parents=True, exist_ok=True)
        if afg.exists():
            afg.unlink()
        shutil.move(str(hoofd), str(afg))
    return f"{AFGEKEURD_MAP}/{bestand}" if afg.exists() else None


def raw_uit_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Herbouwt `raw` uit een eerder record (voor --alleen-manifest, zonder netwerk)."""
    c = rec.get("controle") or {}
    dom = c.get("dom")
    raw: dict[str, Any] = {
        "vastgelegd_op": rec.get("vastgelegd_op"), "http_status": rec.get("http_status"),
        "eind_url": rec.get("eind_url"), "fout": rec.get("fout"),
        "cookies": {k: v for k, v in (c.get("cookies") or {}).items() if k != "beschrijving"} or None,
        "pagina_hoogte_css_px": rec.get("pagina_hoogte_css_px"),
        "afgekapt_op_px": rec.get("afgekapt_op_px"),
        # procesgegevens die een herbouw niet mag laten verdwijnen: welke stappen zijn uitgevoerd (en welke
        # MISLUKT zijn) en of er een tweede, langzamere scrollronde nodig was
        "stappen": rec.get("stappen"),
        "traag_scrollen_herpoging": rec.get("traag_scrollen_herpoging"),
    }
    if dom:
        raw["dom"] = {"titel": dom.get("titel", ""), "h1": dom.get("h1", ""),
                      "contentType": dom.get("content_type"), "aantal_elementen": dom.get("aantal_elementen"),
                      "tekst_tekens": dom.get("tekst_tekens"), "tekst_monster": dom.get("tekst_begin", ""),
                      "tekst_begin": dom.get("tekst_begin", ""), "fout_patroon": dom.get("fout_patroon"),
                      "bediening_zichtbaar": dom.get("bediening_zichtbaar"),
                      "taal_gemeten": dom.get("taal_gemeten"), "captcha_element": dom.get("captcha_element"),
                      "overlays": dom.get("overlays_na") or [], "scroll_vergrendeld": dom.get("scroll_vergrendeld"),
                      "innerWidth": (dom.get("inner_afmeting") or [None, None])[0],
                      "innerHeight": (dom.get("inner_afmeting") or [None, None])[1]}
    return raw


def bouw_record(*, kaart: dict[str, Any], viewport_naam: str, bestand: str, map_pad: Path,
                raw: dict[str, Any], verplaats: bool = True, d: Drempels = DREMPELS,
                extra_redenen: list[str] | None = None,
                extra_controle: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Maakt het uniforme opnamerecord. `kaart` bevat de door de opnemer vastgestelde
    (geinspecteerde) classificatie; `raw` bevat wat de capture heeft gemeten. De PNG moet
    bestaan (in <map>/ of <map>/_afgekeurd/); anders: gebruik `record_zonder_bestand`.
    `extra_redenen` en `extra_controle` laten een aanroeper (bijvoorbeeld maak_decoy.py met
    zijn leesbaarheidsmeting) eigen afkeurredenen en meetwaarden toevoegen.
    """
    pad = map_pad / bestand
    if not pad.exists() and (map_pad / AFGEKEURD_MAP / bestand).exists():
        pad = map_pad / AFGEKEURD_MAP / bestand
    if not pad.exists():
        raise FileNotFoundError(f"{bestand} ontbreekt in {map_pad}")
    uitkomst = controleer_opname(
        pad, viewport_naam, dom=raw.get("dom"), http_status=raw.get("http_status"),
        eind_url=raw.get("eind_url"), vraag_url=kaart.get("url"), fout=raw.get("fout"),
        cookies=raw.get("cookies"), d=d)
    redenen = list(uitkomst["afkeurredenen"]) + list(extra_redenen or [])
    if extra_controle:
        uitkomst["controle"].update(extra_controle)
    if (not kaart.get("wat_het_toont") or not kaart.get("klasse")) and not kaart.get("_concept"):
        redenen.append("nog_niet_geinspecteerd")
    ok = not redenen
    pad_rel = plaats_bestand(map_pad, bestand, ok) if verplaats else bestand
    dom_c = uitkomst["controle"].get("dom") or {}
    taal = dom_c.get("taal_gemeten") or kaart.get("taal")
    rec: dict[str, Any] = {
        "id": kaart.get("id") or kaart.get("slug"),
        "bron_naam": kaart.get("bron_naam"),
        "url": kaart.get("url"),
        "bestand": pad_rel,
        "viewport_naam": viewport_naam,
        "viewport": f'{VIEWPORTS[viewport_naam]["width"]}x{VIEWPORTS[viewport_naam]["height"]}@{DEVICE_SCALE}x',
        "klasse": kaart.get("klasse"),
        "domein": kaart.get("domein"),
        "taal": taal,
        "soort_scherm": kaart.get("soort_scherm"),
        "geladen_ok": ok,
        "afkeurredenen": redenen,
        "controle": uitkomst["controle"],
        "wat_het_toont": kaart.get("wat_het_toont") or "NOG NIET GEINSPECTEERD",
        "geinspecteerd_op": kaart.get("geinspecteerd_op"),
        "vastgelegd_op": raw.get("vastgelegd_op") or nu_iso(),
        "http_status": raw.get("http_status"),
        "eind_url": raw.get("eind_url"),
        "titel": dom_c.get("titel") or raw.get("titel"),
        "dekking_categorie": kaart.get("dekking_categorie"),
    }
    if pad_rel and (map_pad / pad_rel).exists():
        rec["bestandsgrootte_bytes"] = (map_pad / pad_rel).stat().st_size
    for veld in ("pagina_hoogte_css_px", "afgekapt_op_px"):
        if raw.get(veld) is not None:
            rec[veld] = raw[veld]
    if raw.get("stappen"):
        rec["stappen"] = raw["stappen"]
    if raw.get("traag_scrollen_herpoging"):
        rec["traag_scrollen_herpoging"] = True
    if raw.get("fout"):
        rec["fout"] = raw["fout"]
    for extra in ("toegang", "categorie", "kwaliteit", "onderbouwing", "wat_het_toont_mobiel",
                  "bewuste_zwaktes", "indeling", "bron_html"):
        if kaart.get(extra) is not None:
            rec[extra] = kaart[extra]
    if not ok:
        rec["afkeurreden"] = ", ".join(redenen)
    if taal and kaart.get("taal") and taal != kaart["taal"]:
        rec["taal_opmerking"] = f"verwacht {kaart['taal']}, gemeten {taal}"
    return rec


def record_zonder_bestand(*, kaart: dict[str, Any], viewport_naam: str, reden: str,
                          codes: list[str]) -> dict[str, Any]:
    """Regel voor een bron die is overgeslagen (geweigerd, geblokkeerd, mislukt). bestand = null."""
    return {
        "id": kaart.get("id") or kaart.get("slug"), "bron_naam": kaart.get("bron_naam"),
        "url": kaart.get("url"), "bestand": None, "viewport_naam": viewport_naam,
        "viewport": f'{VIEWPORTS[viewport_naam]["width"]}x{VIEWPORTS[viewport_naam]["height"]}@{DEVICE_SCALE}x',
        "klasse": kaart.get("klasse"), "domein": kaart.get("domein"), "taal": kaart.get("taal"),
        "soort_scherm": kaart.get("soort_scherm"), "geladen_ok": False, "afkeurredenen": codes,
        "controle": {"schema": SCHEMA_VERSIE, "controle_versie": CONTROLE_VERSIE, "beeld": None,
                     "overgeslagen": True},
        "wat_het_toont": f"NIET VASTGELEGD: {reden}", "afkeurreden": reden,
        "vastgelegd_op": nu_iso(), "dekking_categorie": kaart.get("dekking_categorie"),
    }


def lees_opnames(manifest: str | Path | list | dict) -> list[dict[str, Any]]:
    """
    Leest een manifest in elk van de vormen en geeft een platte lijst opnamerecords.
    Bij de geneste comps_nl-vorm erven de bestandsrecords de velden van hun bron.
    Records zonder bestand (overgeslagen) blijven in de lijst, met geladen_ok false.
    """
    if isinstance(manifest, (str, Path)):
        data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    else:
        data = manifest
    if isinstance(data, list):
        return [dict(e) for e in data]
    uit: list[dict[str, Any]] = []
    if "comps" in data:
        for c in data["comps"]:
            basis = {k: v for k, v in c.items() if k not in ("bestanden", "controle")}
            for vp, b in (c.get("bestanden") or {}).items():
                rec = {**basis, **(b if isinstance(b, dict) else {"bestand": b})}
                rec.setdefault("bestand", rec.get("file"))
                rec.setdefault("viewport_naam", vp)
                uit.append(rec)
        for s in data.get("overgeslagen", []):
            uit.append({**s, "bestand": None, "geladen_ok": False})
    elif "bestanden" in data:
        basis = {k: data[k] for k in ("dekking_categorie",) if k in data}
        uit.extend({**basis, **dict(e)} for e in data["bestanden"])
    return uit


def leesvoorbeeld(vorm: str) -> dict[str, Any]:
    """
    Korte leeswijzer die in elk object-manifest (comps_nl, decoy, anker) staat: waar de opnamerecords zitten en
    hoe je ze plat leest. `renders/comps/manifest.json` is een lijst en kan geen sleutel dragen; zie de README.
    """
    return {
        "records_staan_in": vorm,
        "plat_lezen_in_python": ("import sys; sys.path.insert(0, 'scripts'); "
                                 "from capture_controle import lees_opnames; "
                                 "records = [r for r in lees_opnames('renders/<map>/manifest.json') "
                                 "if r['geladen_ok'] and r['bestand']]"),
        "velden_per_record": ("bestand, bron_naam, viewport_naam (desktop|mobile), klasse, soort_scherm, domein, "
                              "taal, geladen_ok, afkeurredenen, controle, wat_het_toont (bij decoys ook kwaliteit "
                              "en bewuste_zwaktes)"),
        "pad_van_de_png": ("<map van het manifest>/<bestand>; afgekeurde PNG's (geladen_ok=false) staan in "
                           "<map>/_afgekeurd/ en blijven met reden in het manifest"),
    }


def valideer_records(records: list[dict[str, Any]], *, bron: str = "") -> list[str]:
    """Schemacontrole; geeft een lijst foutmeldingen (leeg = in orde)."""
    fouten: list[str] = []
    for i, r in enumerate(records):
        etiket = f"{bron}[{i}] {r.get('bestand') or r.get('id') or '?'}"
        if (r.get("controle") or {}).get("overgeslagen") or (r.get("bestand") is None and r.get("geladen_ok") is False):
            # bron zonder PNG: nooit gezien, dus klasse/taal mogen null zijn; reden is wel verplicht
            if r.get("geladen_ok") is not False or not r.get("afkeurredenen") or not r.get("afkeurreden"):
                fouten.append(f"{etiket}: overgeslagen bron zonder geladen_ok=false, afkeurredenen of afkeurreden")
            continue
        for veld in ("klasse", "domein", "taal", "geladen_ok", "controle", "wat_het_toont", "viewport_naam"):
            if veld not in r or r[veld] is None:
                fouten.append(f"{etiket}: veld '{veld}' ontbreekt")
        if r.get("klasse") not in KLASSEN:
            fouten.append(f"{etiket}: klasse {r.get('klasse')!r} ongeldig")
        if r.get("domein") not in DOMEINEN:
            fouten.append(f"{etiket}: domein {r.get('domein')!r} ongeldig")
        if r.get("taal") not in TALEN:
            fouten.append(f"{etiket}: taal {r.get('taal')!r} ongeldig")
        if r.get("viewport_naam") not in VIEWPORT_NAMEN:
            fouten.append(f"{etiket}: viewport_naam {r.get('viewport_naam')!r} ongeldig")
        if not isinstance(r.get("geladen_ok"), bool):
            fouten.append(f"{etiket}: geladen_ok is geen bool")
        if not isinstance(r.get("controle"), dict):
            fouten.append(f"{etiket}: controle is geen dict")
        if r.get("klasse") == "decoy" and r.get("kwaliteit") not in KWALITEITEN:
            fouten.append(f"{etiket}: decoy zonder geldige kwaliteit")
        if r.get("klasse") != "decoy" and r.get("kwaliteit") is not None:
            fouten.append(f"{etiket}: kwaliteit hoort alleen bij decoys")
        if r.get("geladen_ok") is True and (r.get("afkeurredenen") or not r.get("bestand")):
            fouten.append(f"{etiket}: geladen_ok true maar reden aanwezig of bestand leeg")
        if r.get("geladen_ok") is False and not r.get("afkeurredenen"):
            fouten.append(f"{etiket}: geladen_ok false zonder afkeurredenen")
        if "NOG NIET GEINSPECTEERD" in str(r.get("wat_het_toont", "")):
            fouten.append(f"{etiket}: wat_het_toont niet ingevuld")
    return fouten


def valideer_manifest(pad: str | Path) -> list[str]:
    return valideer_records(lees_opnames(pad), bron=str(pad))


def schrijf_json(pad: Path, obj: Any) -> None:
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ===========================================================================
# 8. Zelftest
# ===========================================================================
def _synth_pagina(breed: int = 2880, hoog: int = 4000, *, bg=(255, 255, 255),
                  tekst=(40, 40, 40)) -> Image.Image:
    """Een tekstachtige pagina: regels 'tekst' op een achtergrond, met koppen, secties en randen."""
    rng = np.random.default_rng(7)
    a = np.empty((hoog, breed, 3), dtype=np.uint8)
    a[:] = bg
    y = 120
    max_regel = max(60, min(1500, breed - 192))
    while y < hoog - 120:
        a[y: y + 28, 96: 96 + int(rng.integers(min(300, max_regel // 2), max_regel // 2 + 1))] = tekst
        y += 64
        for _ in range(int(rng.integers(3, 6))):
            if y + 20 > hoog:
                break
            lengte = (int(rng.integers(max_regel * 6 // 10, max_regel + 1)) // 6) * 6
            regel = np.where(rng.random((16, lengte // 6)) < 0.55, 0, 1).astype(np.uint8)
            regel = np.repeat(regel, 6, axis=1)[:, :lengte]
            kleur = np.where(regel[..., None] == 0, np.array(tekst, np.uint8), np.array(bg, np.uint8))
            a[y: y + 16, 96: 96 + lengte] = kleur
            y += 40
        a[y: y + 2, :] = tuple(min(255, c + 30) if bg[0] < 128 else max(0, c - 30) for c in bg)
        y += 90
    return Image.fromarray(a)


def _zelftest_beeld() -> list[tuple[str, bool, str]]:
    uit: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)

        def kies(naam: str, im: Image.Image, verwacht_ok: bool, verwacht_code: str | None = None,
                 vp: str = "desktop") -> None:
            p = td_p / f"{naam}.png"
            im.save(p)
            res = controleer_opname(p, vp)
            gelukt = res["geladen_ok"] == verwacht_ok and (
                verwacht_code is None or verwacht_code in res["afkeurredenen"])
            uit.append((naam, gelukt, f"ok={res['geladen_ok']} redenen={res['afkeurredenen']}"))

        kies("goed_tekstpagina", _synth_pagina(), True)
        kies("leeg_wit", Image.new("RGB", (2880, 3000), (255, 255, 255)), False, "bijna_leeg")
        bijna = Image.new("RGB", (2880, 3000), (255, 255, 255))
        bijna.paste(Image.new("RGB", (600, 16), (40, 40, 40)), (200, 400))
        kies("bijna_leeg_een_regel", bijna, False, "bijna_leeg")
        p = np.asarray(_synth_pagina(hoog=5000)).copy()
        p[1400:4300] = 255
        kies("grote_lege_band_midden", Image.fromarray(p), False, "grote_lege_band")
        p = np.asarray(_synth_pagina(hoog=6000)).copy()
        p[2200:] = 255
        kies("lege_staart", Image.fromarray(p), False)
        # cookiewall: dim over de eerste viewport (1800 px), gecentreerde witte dialoog met knop
        p = np.asarray(_synth_pagina(hoog=4200)).copy()
        p[:1800] = (p[:1800] * 0.4).astype(np.uint8)
        p[700:1100, 800:2080] = 255
        p[880:920, 900:1500] = (20, 20, 20)
        p[980:1040, 900:1180] = (10, 88, 202)
        kies("cookiewall_dim_en_dialoog", Image.fromarray(p), False, "gecentreerd_blok_in_beeld")
        p = np.asarray(_synth_pagina(hoog=4200)).copy()
        p[:1800] = (p[:1800] * 0.35).astype(np.uint8)
        kies("dim_zonder_dialoog", Image.fromarray(p), False, "dimming_boven_vouw")
        # kort scherm (geen pagina onder de vouw) met dim + dialoog: moet via het blok worden gevangen
        p = np.asarray(_synth_pagina(hoog=1800)).copy()
        p[:] = (p * 0.4).astype(np.uint8)
        p[600:1200, 900:1980] = 255
        kies("cookiewall_korte_pagina", Image.fromarray(p), False, "gecentreerd_blok_in_beeld")
        p = np.asarray(_synth_pagina(hoog=3600)).copy()
        p[:, :560] = (24, 26, 32)
        kies("goed_sidebar_donker", Image.fromarray(p), True)
        kies("goed_darkmode", _synth_pagina(bg=(14, 14, 16), tekst=(228, 228, 232)), True)
        p = np.asarray(_synth_pagina(hoog=3600)).copy()
        p[:, :500] = (240, 240, 240)
        p[:, -500:] = (240, 240, 240)
        kies("goed_witte_kolom_op_grijs", Image.fromarray(p), True)
        kies("goed_mobiel", _synth_pagina(breed=780, hoog=6000), True, vp="mobile")
        # mobiele cookiewall: dialoog over 90% van de breedte
        p = np.asarray(_synth_pagina(breed=780, hoog=4000)).copy()
        p[:1688] = (p[:1688] * 0.4).astype(np.uint8)
        p[600:1100, 60:720] = 255
        kies("cookiewall_mobiel", Image.fromarray(p), False, "gecentreerd_blok_in_beeld", vp="mobile")
        # regressie (Poliswijzer mobiel): wit formulierkaartje midden op een gekleurde hero die BOVEN de vouw
        # doorloopt. Dat is een ontwerp, geen modal, en moet slagen.
        p = np.asarray(_synth_pagina(breed=780, hoog=5000)).copy()
        p[:2600] = (60, 140, 100)
        p[400:1300, 40:740] = 255
        p[500:540, 80:500] = (30, 30, 30)
        p[700:760, 80:700] = (235, 235, 235)
        kies("goed_hero_met_formulierkaart_mobiel", Image.fromarray(p), True, vp="mobile")
        p = np.asarray(_synth_pagina(breed=2880, hoog=5200)).copy()
        p[:1950] = (60, 140, 100)                      # hero loopt tot voorbij de vouw (1800)
        p[300:1300, 900:1980] = 255
        p[400:460, 960:1500] = (30, 30, 30)
        for y in (1400, 1500, 1600, 1700):             # koptekst/ondertitel van de hero onder het kaartje
            p[y:y + 18, 700:2100] = (245, 245, 245)
        kies("goed_hero_met_formulierkaart_desktop", Image.fromarray(p), True)
    return uit


def _zelftest_tekst() -> list[tuple[str, bool, str]]:
    uit: list[tuple[str, bool, str]] = []
    gevallen = [
        ("tekst_access_denied", "Access Denied", "", "You don't have permission to access this server", "toegang_geweigerd"),
        ("tekst_cloudflare", "Just a moment...", "", "Checking your browser before accessing", "botmuur_of_captcha"),
        ("tekst_captcha_nl", "Controle", "", "Bevestig dat je geen robot bent en klik hier", "botmuur_of_captcha"),
        ("tekst_404", "404 - Pagina niet gevonden", "", "Deze pagina bestaat niet", "niet_gevonden"),
        ("tekst_werk_aan_de_winkel", "Bank", "", "Werk aan de winkel. We zijn even niet bereikbaar.", "server_of_onderhoud"),
        ("tekst_js_vereist", "App", "", "You need to enable JavaScript to run this app.", "javascript_niet_gerenderd"),
        ("tekst_gewone_pagina", "Stripe API Reference", "Introduction",
         "Find anything Ask AI Introduction Authentication Errors " * 50, None),
        ("tekst_lange_pagina_met_captcha_woord", "Docs", "Guide",
         ("Hoe je een captcha gebruikt in je formulier. " * 120), None),
    ]
    for naam, titel, h1, tekst, verwacht in gevallen:
        fp = zoek_foutpatroon(titel, h1, tekst)
        uit.append((naam, fp == verwacht, f"gevonden={fp}"))
    uit.append(("taal_nl", raad_taal("Dit is een tekst over de verzekering van een auto en het is niet moeilijk " * 5) == "nl", ""))
    uit.append(("taal_en", raad_taal("This is a text about the insurance of a car and it is not hard to read " * 5) == "en", ""))
    uit.append(("host_geblokkeerd_ing", host_geblokkeerd("https://www.ing.nl/zakelijk") is not None, ""))
    uit.append(("host_niet_geblokkeerd", host_geblokkeerd("https://www.kvk.nl/zoeken/") is None, ""))
    return uit


def _zelftest_herbouw() -> list[tuple[str, bool, str]]:
    """--alleen-manifest moet een record trouw herbouwen: niets van wat de opname beschrijft mag verdwijnen."""
    uit: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as td:
        map_pad = Path(td)
        _synth_pagina().save(map_pad / "t.png")
        kaart = {"id": "t", "bron_naam": "Test", "url": "https://voorbeeld.test/", "klasse": "product_ui",
                 "domein": "internationaal", "taal": "en", "soort_scherm": "docs", "wat_het_toont": "Testpagina.",
                 "geinspecteerd_op": "2026-09-29", "dekking_categorie": "test"}
        dom = verrijk_dom({"titel": "Test", "h1": "Test", "contentType": "text/html", "aantal_elementen": 300,
                           "tekst_tekens": 900, "tekst_monster": "the page shows some text for the test " * 25,
                           "overlays": [], "innerWidth": 1440, "innerHeight": 900})
        raw = {"vastgelegd_op": "2026-09-29T12:00:00+00:00", "http_status": 200, "eind_url": kaart["url"],
               "fout": None, "pagina_hoogte_css_px": 1500,
               "stappen": ['MISLUKT ({"click": "button"}): TimeoutError', 'ok: {"wait": 5000}'],
               "traag_scrollen_herpoging": True, "dom": dom,
               "cookies": {"actie": "geklikt", "knop": "Accepteren", "verborgen_via": None, "blokkerend_voor": 1,
                           "blokkerend_na": 0, "schoon_na_meting": True,
                           "stappen": [{"actie": "geklikt", "knop": "Accepteren", "overlays_daarna": 0}]}}
        eerste = bouw_record(kaart=kaart, viewport_naam="desktop", bestand="t.png", map_pad=map_pad, raw=raw,
                             verplaats=False)
        tweede = bouw_record(kaart=kaart, viewport_naam="desktop", bestand="t.png", map_pad=map_pad,
                             raw=raw_uit_record(eerste), verplaats=False)
        for veld in ("geladen_ok", "afkeurredenen", "klasse", "wat_het_toont", "stappen", "traag_scrollen_herpoging",
                     "pagina_hoogte_css_px", "http_status", "eind_url", "titel", "taal"):
            uit.append((f"herbouw_behoudt_{veld}", eerste.get(veld) == tweede.get(veld),
                        f"{eerste.get(veld)!r} -> {tweede.get(veld)!r}"[:90]))
        uit.append(("herbouw_behoudt_cookiebeschrijving",
                    eerste["controle"]["cookies"]["beschrijving"] == tweede["controle"]["cookies"]["beschrijving"],
                    tweede["controle"]["cookies"]["beschrijving"][:70]))
    return uit


def _zelftest_samenvoegen() -> list[tuple[str, bool, str]]:
    """De twee opruimrondes (na laden, na scrollen) worden tot een uitspraak samengevoegd; de laatste telt."""
    def rec(actie: str, voor: int = 0, na: int = 0, stappen: list | None = None) -> dict[str, Any]:
        return {"actie": actie, "knop": None, "verborgen_via": None, "blokkerend_voor": voor,
                "blokkerend_na": na, "schoon_na_meting": na == 0, "stappen": stappen or [],
                "na": [{"tag": "div"}] * na}

    uit: list[tuple[str, bool, str]] = []
    # regressie (Retool mobiel): de tip stond bij de eerste meting nog, een scriptstap klikte 'Got it', bij de
    # tweede meting was hij weg. Dat is een schone opname, geen 'niet_verwijderd'.
    r = samenvoegen_cookies(rec("niet_verwijderd", 1, 1), rec("geen_banner"))
    uit.append(("samenvoegen_overlay_verdwenen_tussen_metingen",
                r["actie"] == "verdwenen_tussen_metingen" and r["blokkerend_na"] == 0 and r["schoon_na_meting"]
                and "na" not in r, f"actie={r['actie']}"))
    uit.append(("samenvoegen_beschrijving_zegt_niet_dat_hij_bleef",
                "bleven staan" not in cookie_beschrijving(r), cookie_beschrijving(r)[:70]))
    dom = {"titel": "Pagina", "h1": "Pagina", "tekst_monster": "tekst " * 120, "tekst_tekens": 720, "overlays": [],
           "contentType": "text/html", "aantal_elementen": 300, "taal_gemeten": "en", "fout_patroon": None}
    res = controleer_opname(None, "mobile", dom=dom, http_status=200, cookies=r)
    uit.append(("samenvoegen_keurt_schone_opname_niet_af", "blokkerende_overlay_dom" not in res["afkeurredenen"],
                f"redenen={res['afkeurredenen']}"))
    r = samenvoegen_cookies(rec("geklikt", 1, 0, [{"actie": "geklikt", "knop": "Accepteren", "overlays_daarna": 0}]),
                            rec("geen_banner"))
    uit.append(("samenvoegen_geklikt_en_daarna_niets", r["actie"] == "geklikt", f"actie={r['actie']}"))
    r = samenvoegen_cookies(rec("geen_banner"), rec("niet_verwijderd", 1, 1))
    uit.append(("samenvoegen_overlay_pas_na_scrollen", r["actie"] == "niet_verwijderd" and r["blokkerend_na"] == 1,
                f"actie={r['actie']}"))
    r = samenvoegen_cookies(rec("niet_verwijderd", 1, 1), rec("niet_verwijderd", 1, 1))
    uit.append(("samenvoegen_twee_keer_niet_verwijderd", r["actie"] == "niet_verwijderd" and r["blokkerend_na"] == 1,
                f"actie={r['actie']}"))
    r = samenvoegen_cookies(rec("geklikt", 1, 0), rec("niet_verwijderd", 1, 1))
    uit.append(("samenvoegen_alsnog_overlay_na_klik", r["actie"] == "niet_verwijderd", f"actie={r['actie']}"))
    return uit


# HTML-fixtures voor de browsertest
_FIX_BASIS = """<!doctype html><html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;font:16px Arial;background:#fff;color:#222}header{height:64px;border-bottom:1px solid #ddd;padding:20px 32px;box-sizing:border-box}
section{padding:40px 32px;border-bottom:1px solid #eee}section h2{margin:0 0 12px}p{max-width:640px;line-height:1.5}
.wall{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999}
.dlg{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);width:min(560px,90vw);background:#fff;border-radius:8px;padding:28px;z-index:10000;box-sizing:border-box}
.dlg button{padding:12px 20px;margin-right:8px;border-radius:6px;border:0;background:#0a58ca;color:#fff;font-size:15px}
.rand{position:fixed;left:0;right:0;bottom:0;background:#222;color:#fff;padding:18px;z-index:9000}
.rand button{padding:8px 14px}</style></head><body>
<header><b>Merk</b> &nbsp; Producten &nbsp; Prijzen &nbsp; Documentatie</header>
@@SECTIES@@
@@EXTRA@@
</body></html>"""

# Een formulierstap: weinig tekst, maar een kop, een vraag, drie keuzes (met verborgen native input, zoals veel
# ontwerpsystemen) en twee knoppen. Dit is een volledige interface en moet slagen.
_FIX_FORMULIERSTAP = """<!doctype html><html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;background:#fff7dd;font:18px Arial;color:#222;min-height:100vh}
.stap{display:flex;justify-content:space-between;padding:32px 8vw}
.stap b{width:44px;height:44px;border-radius:50%;background:#e6dfcc;display:inline-block;text-align:center;line-height:44px}
.kaart{width:min(700px,90vw);margin:24px auto;background:#fff;padding:32px;box-sizing:border-box;box-shadow:0 2px 12px rgba(0,0,0,.25)}
.kaart h2{font:30px Georgia;margin:0 0 16px}.kaart label{display:flex;align-items:center;gap:10px;padding:12px 0;font-size:20px}
.kaart input{position:absolute;opacity:0;width:1px;height:1px}.kaart i{width:22px;height:22px;border:2px solid #333;border-radius:50%;display:inline-block}
.knoppen{display:flex;justify-content:space-between;margin-top:28px}.knoppen button{padding:14px 24px;font-size:18px;border:2px solid #111;background:#fff}
.knoppen .p{background:#111;color:#fff}</style></head><body>
<div class="stap"><b>1</b><b>2</b><b>3</b><b>4</b><b>5</b></div>
<div class="kaart"><h2>Premie berekenen</h2><p>Wie wil je verzekeren?</p>
<label><input type="radio" name="w"><i></i> Mijzelf</label><label><input type="radio" name="w"><i></i> Iemand anders</label>
<label><input type="radio" name="w"><i></i> Mijzelf en iemand anders</label>
<div class="knoppen"><button>Terug naar start</button><button class="p">Volgende vraag</button></div></div>
</body></html>"""
# Dezelfde formulierstap als webcomponent (zoals bij a.s.r.): de keuzerondjes zijn helperelementen met
# role="radio" zonder afmeting in een shadow-DOM; alleen de toegankelijkheidsboom ziet ze.
_FIX_FORMULIERSTAP_SHADOW = _FIX_FORMULIERSTAP.split("<label>")[0] + """
<x-keuze>Mijzelf</x-keuze><x-keuze>Iemand anders</x-keuze><x-keuze>Mijzelf en iemand anders</x-keuze>
<div class="knoppen"><button>Terug naar start</button><button class="p">Volgende vraag</button></div></div>
<script>customElements.define('x-keuze', class extends HTMLElement {
  constructor() { super(); const s = this.attachShadow({mode: 'open'});
    s.innerHTML = '<style>:host{display:flex;align-items:center;gap:10px;padding:12px 0;font-size:20px}' +
      'i{width:22px;height:22px;border:2px solid #333;border-radius:50%;display:inline-block}</style>' +
      '<div role="radio" tabindex="0" style="position:absolute;width:0;height:0;overflow:hidden"></div><i></i><slot></slot>'; } });
</script></body></html>"""
# Een titel met een paar links (zoals een schaarse Notion-pagina) en alleen een zoekveld: geen substantieel scherm.
_FIX_TITEL_MET_LINKS = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Notion Official</title>
<style>body{margin:0;font:16px Arial;color:#222}.p{width:min(620px,90vw);margin:120px auto}h1{font-size:34px}
a{display:block;padding:10px 0;border-bottom:1px solid #eee;color:#222;text-decoration:none}</style></head><body>
<div class="p"><h1>Notion Official</h1><a href="#">What's New?</a><a href="#">Careers at Notion</a><a href="#">Notion Community</a>
<a href="#">Media Kit</a><a href="#">Responsible Disclosure Policy</a><p>Got more questions? Message us in the app or email us.</p></div>
<input type="search" placeholder="Search" style="position:fixed;top:8px;right:8px"></body></html>"""
_ALINEA = "De verzekeringsadviseur beoordeelt het dossier van de klant en legt de dekking van de polis uit in eenvoudige taal voor het gesprek. " * 3
_SECTIES = "".join(f"<section><h2>Onderdeel {i}</h2><p>{_ALINEA}</p></section>" for i in range(1, 9))
_FIXTURES: dict[str, tuple[str, bool, str | None]] = {
    # naam: (extra-html, verwacht geladen_ok, verwachte cookie-actie of afkeurcode)
    "fix_schoon": ("", True, "geen_banner"),
    "fix_cookiewall_met_werkende_knop": (
        '<div id="w" class="wall"></div><div id="d" class="dlg"><h3>Wij gebruiken cookies</h3><p>Accepteer alle cookies of stel je voorkeuren in.</p>'
        '<button onclick="document.getElementById(\'w\').remove();document.getElementById(\'d\').remove()">Alles accepteren</button><button>Instellen</button></div>',
        True, "geklikt"),
    # regressie (Univé): de keuzeknoppen zijn <a>-elementen zonder href en dus zonder knop- of linkrol
    "fix_cookiewall_a_zonder_href": (
        '<div id="w" class="wall"></div><div id="d" class="dlg"><h3>Cookies op voorbeeld.nl</h3><p>Wij gebruiken functionele en '
        'analytische cookies. Kies hieronder.</p>'
        '<a style="display:inline-block;padding:12px 20px;background:#0a58ca;color:#fff;cursor:pointer;margin-right:8px" '
        'onclick="document.getElementById(\'w\').remove();document.getElementById(\'d\').remove()">Accepteer alle cookies</a>'
        '<a style="display:inline-block;padding:12px 20px;background:#0a58ca;color:#fff;cursor:pointer">Weiger alle cookies</a></div>',
        True, "geklikt"),
    "fix_cookiewall_kapotte_knop": (
        '<div class="wall cookie-overlay"></div><div class="dlg cookie-consent"><h3>Wij gebruiken cookies</h3><p>Accepteer alle cookies of stel je voorkeuren in.</p>'
        '<button>Alles accepteren</button><button>Instellen</button></div>', True, "css_verborgen"),
    "fix_cookiebalk_onderaan_werkend": (
        '<div id="b" class="rand"><span>We gebruiken cookies voor een betere ervaring.</span> <button onclick="document.getElementById(\'b\').remove()">Accepteren</button></div>',
        True, "geklikt"),
    "fix_loginmuur_niet_wegklikken": (
        '<div class="wall"></div><div class="dlg" role="dialog" aria-modal="true"><h3>Log in om verder te gaan</h3><p>Voor deze pagina heb je een account nodig.</p>'
        '<button>Inloggen</button></div>', False, "blokkerende_overlay_dom"),
    # niet-consent dialoog (enquete-uitnodiging) MET sluitknop: mag gesloten worden, niets invullen
    "fix_enquete_popup_met_sluitknop": (
        '<div id="w" class="wall"></div><div id="e" class="dlg" role="dialog" aria-modal="true">'
        '<button aria-label="Sluiten" style="float:right;background:#eee;color:#222" '
        'onclick="document.getElementById(\'w\').remove();document.getElementById(\'e\').remove()">x</button>'
        '<h3>Denk mee over onze website</h3><p>Doe mee aan ons gebruikersonderzoek en deel jouw ideeen.</p>'
        '<label>Achternaam <input></label><br><label>E-mail <input></label><br><button>Indienen</button></div>',
        True, "gesloten"),
    # loginmuur MET sluitknop: mag NIET gesloten worden (dat zou een omzeiling van de muur zijn)
    "fix_loginmuur_met_sluitknop": (
        '<div id="w" class="wall"></div><div id="e" class="dlg" role="dialog" aria-modal="true">'
        '<button aria-label="Sluiten" style="float:right;background:#eee;color:#222" '
        'onclick="document.getElementById(\'w\').remove();document.getElementById(\'e\').remove()">x</button>'
        '<h3>Log in om verder te gaan</h3><p>Voor deze pagina heb je een account nodig.</p><button>Inloggen</button></div>',
        False, "blokkerende_overlay_dom"),
    # pop-up ZONDER role="dialog" (zoals een nieuwsbriefvenster) met een sluitknop: mag gesloten worden
    "fix_nieuwsbrief_zonder_dialoogrol": (
        '<div id="w" class="wall"></div><div id="e" class="dlg"><button aria-label="Close" style="float:right;background:#eee;color:#222" '
        'onclick="document.getElementById(\'w\').remove();document.getElementById(\'e\').remove()">x</button>'
        '<h3>Blijf op de hoogte</h3><p>Ontvang maandelijks productnieuws in je inbox.</p><label>E-mail <input></label><button>Houd mij op de hoogte</button></div>',
        True, "gesloten"),
    # zelfde vorm maar dan een loginmuur: mag NIET gesloten worden
    "fix_loginmuur_zonder_dialoogrol": (
        '<div id="w" class="wall"></div><div id="e" class="dlg"><button aria-label="Close" style="float:right;background:#eee;color:#222" '
        'onclick="document.getElementById(\'w\').remove();document.getElementById(\'e\').remove()">x</button>'
        '<h3>Log in om verder te lezen</h3><p>Dit artikel is alleen voor abonnees.</p><button>Inloggen</button></div>',
        False, "blokkerende_overlay_dom"),
    "fix_access_denied": ("", False, "toegang_geweigerd"),
    "fix_leeg": ("", False, "bijna_leeg"),
    # regressie: schaarse pagina (titel + paar regels, ~230 tekens) is geen substantieel scherm
    "fix_te_weinig_tekst": ("", False, "te_weinig_tekst"),
    "fix_titel_met_links": ("", False, "te_weinig_tekst"),
    # regressie (a.s.r.-premiecalculator, stap 1): ~130 tekens maar wel keuzes en knoppen = een volledige interface
    "fix_formulierstap_weinig_tekst": ("", True, "geen_banner"),
    "fix_formulierstap_shadow_dom": ("", True, "geen_banner"),
    # regressie: alternatieve platte-tekstweergave (bijvoorbeeld een markdown 'machineversie')
    "fix_platte_tekst": ("", False, "geen_html_pagina"),
    # regressie: Stripe laadt op elke pagina een ONZICHTBARE hCaptcha-iframe; dat is geen botmuur
    "fix_onzichtbare_captcha_iframe": (
        '<iframe src="about:blank#hcaptcha-invisible" style="width:0;height:0;border:0" title=""></iframe>',
        True, "geen_banner"),
    "fix_zichtbare_captcha": (
        '<div style="position:absolute;top:120px;left:40px"><iframe src="about:blank#captcha" style="width:300px;height:80px" title="captcha"></iframe></div>',
        False, "botmuur_of_captcha"),
    # regressie (Ramp): een vaste kopbalk met 'Partners' en 'Management' is geen cookiebanner. De eerste versie
    # zocht 'manage' als deelstring en 'partners' als cookiewoord, en keurde de pagina daarom af.
    "fix_vaste_kopbalk_met_partners": (
        '<div style="position:fixed;top:0;left:0;right:0;z-index:50;background:#fff;padding:14px 32px;'
        'border-bottom:1px solid #ddd">New: AI Token Spend Management - see, understand and control your AI '
        'bill. Products Partners Solutions Pricing Sign in</div>', True, "geen_banner"),
    # ... maar een korte cookiebalk met 'partners' EN een accepteerknop blijft er een
    "fix_cookiebalk_met_partners_zonder_cookiewoord": (
        '<div id="b" class="rand"><span>Wij en onze partners gebruiken gegevens om advertenties te personaliseren.</span> '
        '<button onclick="document.getElementById(\'b\').remove()">Accepteren</button></div>', True, "geklikt"),
}


def _zelftest_browser() -> list[tuple[str, bool, str]]:
    from playwright.sync_api import sync_playwright
    uit: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as td, sync_playwright() as pw:
        td_p = Path(td)
        b = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox", "--hide-scrollbars"])
        for naam, (extra, verwacht_ok, verwacht) in _FIXTURES.items():
            for vp in ("desktop", "mobile"):
                ctx = b.new_context(viewport=VIEWPORTS[vp], device_scale_factor=DEVICE_SCALE, is_mobile=vp == "mobile")
                pg = ctx.new_page()
                if naam == "fix_access_denied":
                    html = ("<!doctype html><html><head><title>Access Denied</title></head><body><h1>Access Denied</h1>"
                            "<p>You don't have permission to access this page on this server.</p></body></html>")
                elif naam == "fix_leeg":
                    html = ("<!doctype html><html><head><meta name='viewport' content='width=device-width'><title>Pagina</title></head>"
                            "<body><p>Laden...</p></body></html>")
                elif naam == "fix_te_weinig_tekst":
                    html = _FIX_BASIS.replace("@@SECTIES@@", "<section><h2>Onderdeel 1</h2><p>Een korte alinea met wat uitleg over "
                                              "het dossier van de klant en de polis, niet meer dan een paar regels tekst.</p></section>"
                                              ).replace("@@EXTRA@@", "")
                elif naam == "fix_titel_met_links":
                    html = _FIX_TITEL_MET_LINKS
                elif naam == "fix_formulierstap_weinig_tekst":
                    html = _FIX_FORMULIERSTAP
                elif naam == "fix_formulierstap_shadow_dom":
                    html = _FIX_FORMULIERSTAP_SHADOW
                else:
                    html = _FIX_BASIS.replace("@@SECTIES@@", _SECTIES).replace("@@EXTRA@@", extra)
                if naam == "fix_platte_tekst":
                    from urllib.parse import quote
                    md = ("# Bedrijf - Machine Version\n\n**Quick links:** [Docs](https://example.org/docs) . [Pricing](https://example.org/p)\n\n"
                          + "## Overzicht\n\n- Regel met uitleg over het product en de mogelijkheden voor teams.\n" * 12)
                    pg.goto("data:text/plain;charset=utf-8," + quote(md))
                else:
                    pg.set_content(html)
                pg.wait_for_timeout(250)
                cookies = ruim_cookiebanner_op(pg, "about:blank")
                dom = verrijk_dom(verzamel_dom_info(pg))
                pad = td_p / f"{naam}_{vp}.png"
                pg.screenshot(path=str(pad), full_page=True)
                res = controleer_opname(pad, vp, dom=dom, http_status=200, eind_url="about:blank",
                                        vraag_url="about:blank", cookies=cookies)
                gelukt = res["geladen_ok"] == verwacht_ok
                if naam.startswith("fix_c") or naam in ("fix_schoon", "fix_onzichtbare_captcha_iframe",
                                                        "fix_enquete_popup_met_sluitknop",
                                                        "fix_nieuwsbrief_zonder_dialoogrol",
                                                        "fix_vaste_kopbalk_met_partners",
                                                        "fix_formulierstap_weinig_tekst",
                                                        "fix_formulierstap_shadow_dom"):
                    gelukt = gelukt and cookies["actie"] == verwacht
                if not verwacht_ok:
                    gelukt = gelukt and verwacht in res["afkeurredenen"]
                uit.append((f"{naam}/{vp}", gelukt,
                            f"ok={res['geladen_ok']} redenen={res['afkeurredenen']} cookies={cookies['actie']}"))
                ctx.close()
        # ONBEHANDELDE cookiewall (zonder opruimen): beeld- en DOM-controle moeten hem vangen
        for vp in ("desktop", "mobile"):
            ctx = b.new_context(viewport=VIEWPORTS[vp], device_scale_factor=DEVICE_SCALE, is_mobile=vp == "mobile")
            pg = ctx.new_page()
            extra = _FIXTURES["fix_cookiewall_kapotte_knop"][0]
            pg.set_content(_FIX_BASIS.replace("@@SECTIES@@", _SECTIES).replace("@@EXTRA@@", extra))
            pg.wait_for_timeout(250)
            dom = verrijk_dom(verzamel_dom_info(pg))
            pad = td_p / f"onbehandeld_{vp}.png"
            pg.screenshot(path=str(pad), full_page=True)
            res = controleer_opname(pad, vp, dom=dom, http_status=200)
            uit.append((f"onbehandelde_cookiewall_beeld_en_dom/{vp}", not res["geladen_ok"],
                        f"redenen={res['afkeurredenen']}"))
            res2 = controleer_opname(pad, vp)
            uit.append((f"onbehandelde_cookiewall_alleen_beeld/{vp}", not res2["geladen_ok"],
                        f"redenen={res2['afkeurredenen']}"))
            ctx.close()
        b.close()
    return uit


def zelftest(met_browser: bool = False) -> int:
    resultaten = _zelftest_beeld() + _zelftest_tekst() + _zelftest_samenvoegen() + _zelftest_herbouw()
    if met_browser:
        resultaten += _zelftest_browser()
    mislukt = 0
    for naam, gelukt, info in resultaten:
        print(f"{'OK  ' if gelukt else 'FOUT'} {naam:<52} {info}")
        mislukt += 0 if gelukt else 1
    print(f"\n{len(resultaten) - mislukt}/{len(resultaten)} geslaagd" + ("" if met_browser else " (zonder browser)"))
    return 1 if mislukt else 0


# ===========================================================================
# 9. CLI
# ===========================================================================
def _viewport_uit_naam(naam: str) -> str:
    n = naam.lower()
    return "mobile" if ("mobile" in n or re.search(r"[_-]390(?:[x_.-]|$)", n)) else "desktop"


def controleer_map(map_pad: Path, als_json: bool = False) -> int:
    rijen = []
    bestanden = sorted(map_pad.glob("*.png")) + sorted((map_pad / AFGEKEURD_MAP).glob("*.png"))
    for p in bestanden:
        vp = _viewport_uit_naam(p.name)
        m = meet_beeld(p, vp)
        rijen.append((p, vp, m, beoordeel(m, None)))
    if als_json:
        print(json.dumps([{"bestand": str(p), "viewport": vp, "meting": m, "redenen": r}
                          for p, vp, m, r in rijen], indent=2))
        return 0
    print(f"{'bestand':<50}{'inkt':>7}{'struct':>8}{'effenbl':>8}{'lgband':>8}{'staart':>7}{'blok':>6}{'dim':>5}  redenen")
    for p, vp, m, r in rijen:
        ov = m["overlay"]
        naam = ('_afg/' if AFGEKEURD_MAP in str(p) else '') + p.name
        print(f"{naam:<50}{m['inkt_aandeel']:>7.3f}{m['structuur_aandeel']:>8.4f}{m['effen_blokken_aandeel']:>8.3f}"
              f"{m['langste_lege_band_css_px']:>8}{m['lege_staart_css_px']:>7}"
              f"{'ja' if ov.get('gecentreerd_blok') else '-':>6}{'ja' if ov.get('dimming_boven_vouw') else '-':>5}"
              f"  {','.join(r) or 'schoon'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Naharde opnamecontrole en manifestvalidatie")
    ap.add_argument("--zelftest", action="store_true")
    ap.add_argument("--met-browser", action="store_true", help="bij --zelftest: ook Chromium-fixtures")
    ap.add_argument("--controleer", metavar="MAP")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--valideer", nargs="+", metavar="MANIFEST")
    a = ap.parse_args(argv)
    if a.zelftest:
        return zelftest(a.met_browser)
    if a.controleer:
        return controleer_map(Path(a.controleer), a.json)
    if a.valideer:
        alle: list[str] = []
        for m in a.valideer:
            f = valideer_manifest(m)
            print(f"{m}: {'in orde' if not f else str(len(f)) + ' fout(en)'}")
            alle += f
        for f in alle[:80]:
            print("  -", f)
        return 1 if alle else 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
