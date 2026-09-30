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

Uitgangspunt (versie 2): winnen tegen een nepbar is erger dan niet winnen. Dit
harnas WEIGERT daarom een ronde te schrijven die niets meet of die identiteit
lekt, in plaats van stilletjes door te draaien met exitcode 0. De eerste versie
deed dat wel; een onafhankelijke audit (state.json -> meetlat_audit_ronde_0)
verklaarde de meetlat daarom KAPOT.

Exitcodes
---------
  0  ronde geschreven, alle controles geslaagd
  1  interne fout (zelftest mislukt, een bronbeeld liet zich niet verwerken)
  2  ONVOLLEDIGE INVOER: geen enkel eigen scherm (in een te bouwen viewport),
     of geen enkel bronbeeld, of een verboden woord in de rondenaam. De ronde
     zou niets meten. Bewuste uitzondering: --zonder-eigen-schermen.
  3  IDENTITEITSLEK: de OCR vindt na automatisch maskeren nog steeds een
     verboden woord (merk-, product- of eigen naam) in de PIXELS van een beeld.
  4  BLINDERING NIET TE GARANDEREN: geen werkende OCR-engine, of de engine
     haalde de ijkcontrole niet. Zonder OCR is niet te bewijzen dat er geen
     merknaam in beeld staat, dus wordt er niets geschreven.
  5  RONDE-EIGENSCHAP GESCHONDEN: beeldhoogte is een vingerafdruk (meer dan een
     unieke hoogte per viewport) of een bestandsnaam verraadt de bron.
Bij elke weigering (2-5) blijft er GEEN half afgemaakte ronde staan: er wordt
in een tijdelijke map gebouwd en pas na alle controles op zijn plaats gezet.

Pijplijn per afbeelding
-----------------------
1. browser-chrome wegsnijden (bovenrand)          -> detecteer_browser_chrome()
2. cookiebanner-rest wegsnijden (onderrand)       -> detecteer_bodembanner()
3. schalen naar identieke breedte                 -> --breedte
4. vaste hoogte: 1-3 secties (--secties auto)     -> snij_secties()
5. merkidentiteit maskeren (logo-regio's)         -> maskeer_merkregios()
6. merkkleur neutraliseren (grijs, contrast heel) -> naar_neutraal_grijs()
7. contrast normaliseren                          -> --contrast
8. OCR-lekcontrole op de PIXELS + automatisch maskeren -> controleer_lekken()
9. opslaan als A.png / B.png / ... zonder metadata

Keuzes en waarom (versie 2)
---------------------------
HOOGTE (audit-punten 3 en 4). Een beeldhoogte is een vingerafdruk zolang hij
van de bron afhangt: 17 van 41 desktopbeelden hadden een unieke hoogte, en wie de
originelen heeft leest de labelmapping zo af. Bovendien gooide de oude
hoogtekap 90-94% van de mobiele pagina's weg, zodat de mobiele ronde alleen
hero-secties vergeleek. Oplossing: ELK beeld van een viewport krijgt exact
dezelfde afmetingen, doordat het uit drie vaste uitsneden wordt opgebouwd
(standaard boven, midden en onder van de pagina, elk een schermhoogte, gescheiden
door een grijze balk van vaste kleur en hoogte). Voor de uitsneden is gekozen
boven "de hele pagina schalen naar vaste hoogte", omdat schalen de tekstgrootte
per bron laat verschillen en dus juist de typografie vervormt die beoordeeld
wordt. Uitsneden hebben overal dezelfde schaal. Is een pagina korter dan de
drie uitsneden samen, dan sluiten ze aan vanaf de bovenkant en wordt de rest
opgevuld met de achtergrondkleur van de pagina (nooit herhaalde inhoud). De
ronde TOETST dit als eigenschap: meer dan een unieke hoogte per viewport
betekent weigeren (exitcode 5).

LEGE RUIMTE IS OOK EEN VINGERAFDRUK. Een pagina die korter is dan de uitsneden laat lege
ruimte over, en die verraadt de korte pagina's - vaak juist onze eigen schermen en de decoys
(een appscherm van een schermhoogte naast een marketingpagina van tien). Op de eerste echte
opnames zijn de desktop-decoys 1,0-1,5 schermhoogtes lang, de app-comps en de desktop-ankers
1,0, docs- en registerpagina's 3-11. Daarom kiest --secties auto (de standaard) per viewport
het grootste aantal secties (hoogstens 3) dat ELK beeld helemaal vult; bij zo'n mix is dat
een sectie: iedereen laat dan het bovenste scherm zien. Meer secties kan alleen als alle
bronnen langer zijn (sluit korte bronnen uit of neem ze full-page op). Een vast --secties N
mag, maar het harnas weigert (exitcode 5, nog voor het OCR-werk) als de lege ruimte gemiddeld
25% of meer van het beeld verschilt tussen twee klassen (comps, eigen schermen, decoys,
ankers). De voet van de pagina (footermasker) wordt alleen gemaskeerd als hij in beeld is.

OCR (audit-punt 2). De bron is af te lezen uit tekst in het beeld ("Interpolis
Autoverzekeringen" in een kop, "api.stripe.com", "Cal.com"). Een lijst
maskers per bron schaalt daar niet voor; een lezer wel. Elk geneutraliseerd beeld
gaat daarom door OCR, tegen een lijst verboden woorden die deels vast is
(VERBODEN_MERKEN) en deels dynamisch uit alle manifesten wordt gelezen
(bron-, product- en decoynamen, slugs, domeinen). Een treffer -> automatisch het
woordkader maskeren -> opnieuw lezen -> blijft er een lek, dan weigeren. OCR-engine:
RapidOCR (pip, ONNX, geen GPU) als eerste keuze en tesseract (apt) als tweede
mening wanneer beschikbaar. Reden, gemeten met de echte engineklassen en de echte
matcher op Chromium-opnames met dezelfde bewerking als hier (1440 px -> 1200 px;
mobiel 390 px @2x = 780 px):
  * testpaneel van 35 plaatsingen x 3 pagina's (koppen van 64 tot 20 px, bodytekst van
    16 tot 10 px, laag contrast, licht-op-donker, badges, knoppen, code, middentoon):
    desktop RapidOCR 104/105 (99,0%), tesseract 92/105 (87,6%); mobiel RapidOCR 105/105
    (100%), tesseract 95/105 (90,5%). De ene desktopmisser (een badge) vinden ze samen ook niet.
  * 48 brede regels (65-211 tekens) met het merkwoord vooraan, midden of achteraan:
    RapidOCR 48/48, tesseract 48/48.
  * alle 126 woorden van een gerenderde decoy (grondwaarheid uit de HTML): RapidOCR 96,0%,
    tesseract 91,3%, samen 98,4%.
Tesseract mist vooral laag contrast en licht-op-donker, en was zonder de bandenopbouw nog
slechter (79%): op de HELE pagina las het de footer niet, terwijl het dezelfde strook los
wel las. Daarom leest elke engine in banden. RapidOCR draait zonder hoekclassifier: die
draaide een kwart van de lange regels ondersteboven, waarna het merkwoord wegviel (58% van
de merkwoorden gevonden, zonder classifier 100%). Een OCR is nooit volledig: gemiste woorden
(laag contrast, sierschrift, tekst in illustraties) en logo's ZONDER tekst kan hij niet
vinden, en de cijfers hierboven zijn gemeten op onze eigen testpagina's, niet op een
onafhankelijk paneel. Dat staat eerlijk in de sleutel ("OCR-dekking: gecontroleerd op N
woorden, M kaders gemaskeerd") plus een ijkuitkomst per run; rest-risico: een reviewer die de
eindbeelden bekijkt voor grafische logo's.

GEMASKEERDE PLEKKEN ZIJN ZELF EEN SIGNAAL. Een verpixeld of ingevuld woord valt op, en comps met
veel merktekst krijgen er veel, onze eigen schermen geen; bovendien kan zo'n vlek de typografie
van een comp "beschadigen". De sleutel telt daarom de maskers per klasse (ocr.maskers_per_klasse),
het harnas waarschuwt bij een groot verschil tussen klassen en blind_ab_rapport.py toetst achteraf
of de scores met het aantal maskers samenhangen. Het anker (een merkrijke docs-pagina die toch
bovenaan moet staan) is de natuurlijke proef: straffen de vlekken zwaar, dan faalt het anker.
Logo's die de OCR niet als tekst leest (een woordmerk onder een meldingsbalk buiten de vaste
merkbalk van 8% van de breedte) blijven een handmatige controle: --merkbalk-hoogte en --extra-maskers.

DOMEIN, ANKER, TESTRONDE. --domein nl_financieel|internationaal|alles filtert de
comps op het manifestveld `domein`; decoys, ankers en eigen schermen doen altijd
mee. Bronnen met klasse "anker" (een scherm dat aantoonbaar bovenaan hoort)
worden in de sleutel gemarkeerd (is_anker) en door blind_ab_rapport.py gebruikt
als positieve controle. --zonder-eigen-schermen staat een technische testronde
zonder eigen schermen toe; die krijgt de status NIET-BRUIKBAAR-VOOR-OORDEEL in
sleutel en LEESMIJ (zonder de beoordelaar iets te verklappen).

Manifestvelden (contract met de opnames)
----------------------------------------
klasse "product_ui"|"marketing"|"decoy"|"anker"|"ours"; domein "nl_financieel"|
"internationaal"|"decoy"|"anker"|"ours"; taal "nl"|"en"; geladen_ok true/false
(false = NOOIT in een ronde); kwaliteit (alleen decoys) "zeer_zwak"|"zwak"|
"matig"|"redelijk"; soort_scherm ("app/dashboard", "docs", "formulier",
"register", ...; vrije tekst, het rapport vergelijkt alleen vergelijkbare soorten);
wat_het_toont. Ontbrekende velden krijgen een veilige standaard (klasse ->
product_ui, domein -> volgens de map) met een waarschuwing in de sleutel; marketing
wordt standaard uitgesloten (--inclusief-marketing), en --soort-scherm beperkt de
comps tot een of meer soorten.

Manifestvormen. Het harnas leest elke vorm die de opnamescripts schrijven: een platte
lijst van items (renders/comps), een object met `comps` (renders/comps_nl), en een
object met `bestanden` als lijst van objecten (decoy, anker), als map viewport ->
bestand, of als map bestandsnaam -> velden. Per bron staat in de sleutel uit welke
vorm ze kwam (`manifest_vorm`); het rapport telt dat mee.

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
      --anker renders/anker \
      --domein nl_financieel \
      --uit   renders/ab \
      --ronde ronde1 --seed 7

  python3 scripts/blind_ab.py --zelftest      # controleert neutralisatie, OCR, hoogte, filters, exitcodes

Vereist: numpy, pillow en minstens een OCR-engine (zie requirements-dev.txt en
README.md): `pip install rapidocr-onnxruntime==1.4.4` en/of
`apt-get install tesseract-ocr tesseract-ocr-nld tesseract-ocr-eng`.

De beoordelaar krijgt UITSLUITEND renders/ab/<ronde>/<viewport>/.
NOOIT renders/ab/_sleutel.json.
"""

from __future__ import annotations

import argparse
import binascii
import concurrent.futures
import csv
import gzip
import hashlib
import io
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from importlib import metadata as _metadata
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

Image.MAX_IMAGE_PIXELS = None  # full-page screenshots zijn legitiem enorm

SCRIPT_VERSIE = "2.0.0"
PROJECT = Path(__file__).resolve().parent.parent

# Exitcodes (zie docstring)
EXIT_OK = 0
EXIT_FOUT = 1
EXIT_INVOER = 2
EXIT_LEK = 3
EXIT_GEEN_OCR = 4
EXIT_EIGENSCHAP = 5

# ---------------------------------------------------------------------------
# Woorden die NOOIT in een beoordelingsbestandsnaam mogen voorkomen.
# Substring-controle op NAMEN (labels, rondenaam); niet geschikt voor OCR-tekst,
# want daar zouden "geld", "eigen" en "exact" gewone Nederlandse woorden raken.
# ---------------------------------------------------------------------------
VERBODEN_IN_NAAM = (
    "ours", "onze", "eigen", "portaal", "assurantie", "artifation", "decoy",
    "comp", "stripe", "linear", "vercel", "attio", "mercury", "ramp", "retool",
    "metabase", "grafana", "notion", "resend", "dub", "cal", "anwb", "asr",
    "interpolis", "klaverblad", "kifid", "kvk", "digid", "moneybird", "exact",
    "belastingdienst", "pricewise", "poliswijzer", "overstappen", "geld",
    "mijnoverheid", "mijnpensioenoverzicht", "verzekering", "eboekhouden",
    # uitbreiding v2: merken uit de comp-manifesten, de decoy en ons product
    "geist", "independer", "zorgwijzer", "verzekeringskaarten", "centraalbeheer",
    "rabobank", "polisbeheer", "verzekeringsbeheer", "nmbrs", "afas", "anva",
    "twinfield", "snelstart", "yuki", "visma", "bunq", "anker", "sleutel", "meetlat",
)

# Merk-, product- en eigen namen die in de PIXELS van een beeld niet mogen
# voorkomen (OCR-controle). Aangevuld met alles wat uit de manifesten komt.
# Bron: capture_comps.py, capture_comps_nl.py, maak_decoy.py en ons product.
VERBODEN_MERKEN = (
    # internationale comps (renders/comps)
    "stripe", "linear", "linear.app", "vercel", "geist", "attio", "mercury", "ramp",
    "retool", "metabase", "grafana", "grafana play", "cal.com", "cal", "notion",
    "resend", "dub", "dub.co",
    # Nederlandse comps (renders/comps_nl)
    "independer", "poliswijzer", "pricewise", "verzekeringskaarten", "centraal beheer",
    "centraalbeheer", "a.s.r.", "klaverblad", "e-boekhouden", "exact online",
    "exact.com", "kifid", "zorgwijzer", "geld.nl", "overstappen.nl", "digid",
    "interpolis", "nationale-nederlanden", "nn.nl", "anwb", "moneybird", "rabobank",
    "ing.nl", "kvk", "kvk.nl", "mijnpensioenoverzicht", "mijnoverheid", "belastingdienst",
    # de decoy en ons product
    "polisbeheer", "verzekeringsbeheer", "artifation", "assurantieportaal",
    "ai-assurantie-portaal", "decoy",
    # waarschijnlijke aanvullingen (NL backoffice/fintech); de opname-medewerker
    # vult de echte namen aan via de manifesten
    "nmbrs", "afas", "anva", "faster forward", "twinfield", "snelstart", "yuki",
    "visma", "bunq", "mollie", "adyen",
)

# Gewone woorden die ook merknaam zijn: alleen als HEEL woord (met woordgrens)
# tellen, nooit als deel van een langer woord.
AMBIGUE_WOORDEN = frozenset({"linear", "mercury", "notion", "resend", "stripe", "ramp"})

# Deze woorden staan in VERBODEN_IN_NAAM maar zijn gewoon Nederlands of Engels;
# op zichzelf zijn ze GEEN lek in beeldtekst ("eigen risico", "exact"). Alleen
# hun samenstellingen (exactonline, geld.nl) tellen.
NOOIT_ALLEEN = frozenset({
    "ours", "onze", "eigen", "portaal", "assurantie", "comp", "geld", "exact",
    "verzekering", "overstappen", "play", "design", "system", "overheid", "centraal",
    "beheer", "faster", "forward", "nationale", "nederlanden", "online", "anker",
    "sleutel", "meetlat", "kwaliteit",
})

# Merknamen die tegelijk gewoon vakjargon zijn ("polisbeheer" is een menu-item in elk assurantie-
# backoffice, ook in ons eigen scherm). Die tellen alleen als een aaneengesloten woord in de
# schrijfwijze van het merk (PolisBeheer, POLISBEHEER, polisbeheer), niet als "Polisbeheer" met een
# hoofdletter of als "polis beheer" in twee woorden: zonder die beperking zou de OCR legitieme
# tekst in ons eigen scherm wegmaskeren en de vergelijking scheeftrekken.
STRIKT_HELE_WOORD = frozenset({"polisbeheer", "verzekeringsbeheer"})

# Woorden die uit namen/slugs/id's afgeleid kunnen worden maar geen merk zijn.
GENERIEKE_WOORDEN = frozenset({
    "docs", "doc", "api", "app", "online", "zakelijk", "zakelijke", "product",
    "producten", "checkout", "banking", "finance", "components", "component",
    "public", "page", "pages", "templates", "template", "booking", "play",
    "analytics", "crm", "help", "dashboard", "design", "system", "home", "login",
    "inloggen", "prijzen", "facturen", "vergelijken", "vergelijker", "autoverzekering",
    "zorgverzekering", "berekenen", "premie", "overzicht", "startscherm", "uitspraken",
    "register", "klacht", "indienen", "zoeken", "resultaten", "rekening", "www",
    "nl", "com", "org", "io", "co", "dev", "net", "reference", "introduction",
    "latest", "particulier", "verzekeringen", "schadeverzekeringen", "verzekeraar",
    "verzekeraars", "kaartenoverzicht", "aanvraagflow", "stap", "orv", "mijn",
    "overheid", "wps", "wcm", "connect", "btw", "zakelijk", "betalen", "get", "rick",
    "rolled", "the", "and", "voor", "van", "een", "het", "verbond", "kaarten",
    "docs", "reader", "gallery", "catalogus", "productinterface", "interface",
    # gewone woorden die als eerste deel van een slug voorkomen (data-overheid-datasets, wetten-overheid-wft)
    "data", "dataset", "datasets", "wetten", "wet", "open", "opendata",
})
TLD_DELEN = frozenset({"com", "nl", "org", "net", "io", "co", "dev", "app", "so", "site",
                       "be", "eu", "uk", "de", "aspx", "htm", "html"})

# ---------------------------------------------------------------------------
# Manifestcontract
# ---------------------------------------------------------------------------
KLASSEN = ("product_ui", "marketing", "decoy", "anker", "ours")
DOMEINEN = ("nl_financieel", "internationaal", "decoy", "anker", "ours")
TALEN = ("nl", "en")
KWALITEITEN = ("zeer_zwak", "zwak", "matig", "redelijk")     # oplopend
KLASSE_NAAR_SOORT = {"product_ui": "comp", "marketing": "comp", "decoy": "decoy",
                     "anker": "anker", "ours": "ours"}
SOORT_STANDAARD_KLASSE = {"comp": "product_ui", "decoy": "decoy", "anker": "anker",
                          "ours": "ours"}
SOORT_STANDAARD_DOMEIN = {"decoy": "decoy", "anker": "anker", "ours": "ours"}
SET_STANDAARD_DOMEIN = {"comps": "internationaal", "comps_nl": "nl_financieel"}
SET_STANDAARD_TAAL = {"comps": "en", "comps_nl": "nl", "ours": "nl", "decoy": "nl"}
DOMEIN_FILTERS = ("nl_financieel", "internationaal", "alles")

# Hoogtenormalisatie: een sectie is standaard een schermhoogte van de opname
# (desktop 1440x900 -> 0,625 x breedte; mobiel 390x844 -> 2,164 x breedte).
STANDAARD_SECTIES = 3
SCHEIDING_PX = 40
SCHEIDING_GRIJS = 128
SECTIEHOOGTE_FACTOR = {"desktop": 900 / 1440, "mobile": 844 / 390}
AUTO_TOLERANTIE = 0.15     # bij --secties auto telt een pagina die zoveel van een sectiehoogte tekortkomt nog als 'vol'
VULLING_VERSCHIL = 0.25    # zoveel lege ruimte (aandeel van het beeld) mogen twee klassen gemiddeld verschillen


# ---------------------------------------------------------------------------
# Datamodel
# ---------------------------------------------------------------------------
@dataclass
class Bron:
    pad: Path
    set_naam: str            # 'comps', 'comps_nl', 'ours', 'decoy', 'anker'
    soort: str               # 'comp' | 'ours' | 'decoy' | 'anker'
    bron_naam: str           # leesbare naam, alleen voor de sleutel
    viewport: str            # 'desktop' | 'mobile' | 'onbekend'
    omschrijving: str = ""
    # --- manifestvelden (contract), met veilige standaardwaarden
    klasse: str = ""         # product_ui | marketing | decoy | anker | ours
    domein: str = ""
    taal: str = ""
    geladen_ok: bool | None = None   # None = manifest zegt niets
    kwaliteit: str = ""
    bron_id: str = ""
    soort_scherm: str = ""   # app/dashboard, docs, formulier, register, ... ("" = onbekend)
    manifest_vorm: str = ""  # uit welke manifestvorm de velden kwamen ("" = geen manifest)
    meldingen: list[str] = field(default_factory=list)    # afwijkingen in de classificatie
    ontbrekend: list[str] = field(default_factory=list)   # contractvelden die ontbraken


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
    secties: dict = field(default_factory=dict)


@dataclass
class SectieSpec:
    """Vaste opbouw van elk beeld: `aantal` uitsneden van `hoogte` px, gescheiden
    door een balk van `scheiding` px in grijswaarde `grijs`."""
    aantal: int = STANDAARD_SECTIES
    hoogte: int = 750
    scheiding: int = SCHEIDING_PX
    grijs: int = SCHEIDING_GRIJS

    @property
    def totale_hoogte(self) -> int:
        return self.aantal * self.hoogte + (self.aantal - 1) * self.scheiding


def standaard_sectiespec(viewport: str, breedte: int,
                         aantal: int = STANDAARD_SECTIES) -> SectieSpec:
    factor = SECTIEHOOGTE_FACTOR.get(viewport, SECTIEHOOGTE_FACTOR["desktop"])
    return SectieSpec(aantal=aantal, hoogte=max(64, round(breedte * factor)))


@dataclass
class RondeContext:
    """Alles wat bouw_ronde() moet weten buiten de commandoregelargumenten."""
    domein_filter: str = "alles"
    soort_scherm_filter: list[str] = field(default_factory=list)
    inclusief_marketing: bool = False
    zonder_eigen_schermen: bool = False
    uitgesloten: list[dict] = field(default_factory=list)
    waarschuwingen: list[str] = field(default_factory=list)
    engines: list | None = None             # OCR-engines (None = automatisch kiezen)
    termen: "VerbodenTermen | None" = None  # None = statische lijst
    kalibratie: list[dict] = field(default_factory=list)
    classificatie_ontbreekt: list[dict] = field(default_factory=list)


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


_AFBEELDING_EXT = (".png", ".jpg", ".jpeg")
_META_VELDEN = ("klasse", "domein", "taal", "geladen_ok", "kwaliteit", "wat_het_toont", "soort_scherm")
_NAAM_SLEUTELS = ("bron_naam", "naam", "slug", "id")
_LIJST_SLEUTELS = ("comps", "decoys", "ankers", "items", "schermen", "bestanden",
                   "beelden", "eigen")


def viewport_uit_tekst(tekst: str) -> str:
    """'desktop', 'mobile' of een maat als '1440x900@2x' / '390x844' -> viewportnaam."""
    t = str(tekst).strip().lower()
    if t in ("desktop", "mobile"):
        return t
    m = re.match(r"^(\d{3,4})\s*x", t)
    if m:
        w = int(m.group(1))
        return "desktop" if w >= 1000 else "mobile" if w <= 600 else "onbekend"
    return bepaal_viewport(t)


def _is_afbeelding(s: Any) -> bool:
    return isinstance(s, str) and s.lower().endswith(_AFBEELDING_EXT)


def _norm_token(waarde: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(waarde).strip().lower())


def norm_soort_scherm(waarde: Any) -> str:
    """'App / Dashboard ' -> 'app/dashboard'. Vrije tekst; alleen spaties en hoofdletters worden gelijkgetrokken."""
    return re.sub(r"\s+", " ", re.sub(r"\s*/\s*", "/", str(waarde).strip().lower()))


def _norm_bool(waarde: Any) -> bool | None:
    if isinstance(waarde, bool):
        return waarde
    if isinstance(waarde, (int, float)):
        return bool(waarde)
    if isinstance(waarde, str):
        w = waarde.strip().lower()
        if w in ("true", "ja", "yes", "1", "ok"):
            return True
        if w in ("false", "nee", "no", "0"):
            return False
    return None


def _neem_velden(knoop: dict, eigen: dict, meldingen: list[str]) -> None:
    """Neemt de contractvelden en een naam over uit een manifestknoop."""
    for veld in _META_VELDEN:
        if veld not in knoop or knoop[veld] in (None, ""):
            continue
        w = knoop[veld]
        if veld == "geladen_ok":
            b = _norm_bool(w)
            if b is None:
                meldingen.append(f"geladen_ok heeft onbegrijpelijke waarde {w!r}")
            else:
                eigen["geladen_ok"] = b
        elif veld == "wat_het_toont":
            eigen["wat_het_toont"] = str(w)
        elif veld == "soort_scherm":
            eigen["soort_scherm"] = norm_soort_scherm(w)
        else:
            n = _norm_token(w)
            toegestaan = {"klasse": KLASSEN, "domein": DOMEINEN, "taal": TALEN,
                          "kwaliteit": KWALITEITEN}[veld]
            if n in toegestaan:
                eigen[veld] = n
            else:
                meldingen.append(f"{veld} heeft onbekende waarde {w!r} (genegeerd)")
    for sl in _NAAM_SLEUTELS:
        v = knoop.get(sl)
        if isinstance(v, str) and v.strip():
            eigen["bron_naam"] = v.strip()
            break
    if isinstance(knoop.get("id"), str) and knoop["id"].strip():
        eigen["bron_id"] = knoop["id"].strip()
    elif isinstance(knoop.get("slug"), str) and knoop["slug"].strip():
        eigen["bron_id"] = knoop["slug"].strip()
    if isinstance(knoop.get("viewport"), str) and knoop["viewport"].strip():
        eigen["viewport_manifest"] = knoop["viewport"].strip()
    if isinstance(knoop.get("interface_elementen"), str) and "omschrijving_los" not in eigen:
        eigen["omschrijving_los"] = knoop["interface_elementen"]


def _leaf(uit: dict, bestand: str, eigen: dict, vorm: str = "") -> None:
    rec = dict(eigen)
    rec["omschrijving"] = (rec.get("wat_het_toont") or rec.get("omschrijving_los") or "")
    rec["manifest_vorm"] = vorm
    uit[bestand] = rec


def _loop_manifest(knoop: Any, erf: dict, uit: dict, meldingen: list[str], vorm: str = "lijst") -> None:
    """
    Loopt recursief door een manifest en verzamelt per beeldbestand de velden
    (geerfd van omliggende knopen; het meest specifieke wint) en de vorm waaruit ze kwamen.
    Werkt voor alle bekende vormen:
      lijst                              platte lijst van items (renders/comps)
      object.comps[lijst]                object met `comps` (renders/comps_nl)
      ...bestanden[lijst]                `bestanden` als lijst van objecten (decoy, anker)
      ...bestanden[viewportmap]          `bestanden` als map desktop/mobile -> bestand of object
      ...bestanden[bestandsnaam-map]     `bestanden` als map bestandsnaam -> velden
    plus dezelfde vormen onder `decoys`, `ankers`, `items`, `schermen`, `beelden` en `eigen`.
    """
    if isinstance(knoop, list):
        for e in knoop:
            if isinstance(e, dict):
                _loop_manifest(e, erf, uit, meldingen, vorm)
        return
    if not isinstance(knoop, dict):
        return
    eigen = dict(erf)
    _neem_velden(knoop, eigen, meldingen)
    # Een expliciet `false` op een hoger niveau blijft gelden: nooit opnemen.
    if erf.get("geladen_ok") is False:
        eigen["geladen_ok"] = False
    for sl in ("bestand", "file"):
        b = knoop.get(sl)
        if _is_afbeelding(b):
            _leaf(uit, b, eigen, vorm)
            return
    for sl in _LIJST_SLEUTELS:
        sub = knoop.get(sl)
        pad = f"{vorm}.{sl}"
        if isinstance(sub, list):
            for e in sub:
                if _is_afbeelding(e):
                    _leaf(uit, e, eigen, f"{pad}[lijst]")
                elif isinstance(e, dict):
                    _loop_manifest(e, eigen, uit, meldingen, f"{pad}[lijst]")
        elif isinstance(sub, dict):
            for sleutel, v in sub.items():
                if _is_afbeelding(sleutel) and isinstance(v, dict):
                    eigen_b = dict(eigen)
                    _neem_velden(v, eigen_b, meldingen)
                    if eigen.get("geladen_ok") is False:
                        eigen_b["geladen_ok"] = False
                    _leaf(uit, sleutel, eigen_b, f"{pad}[bestandsnaam-map]")
                    continue
                if sleutel in ("desktop", "mobile"):
                    eigen_vp = {**eigen, "viewport_manifest": sleutel}
                    soort_map = f"{pad}[viewportmap]"
                else:
                    eigen_vp = eigen
                    soort_map = f"{pad}[map]"
                if _is_afbeelding(v):
                    _leaf(uit, v, eigen_vp, soort_map)
                elif isinstance(v, (dict, list)):
                    _loop_manifest(v, eigen_vp, uit, meldingen, soort_map)


def lees_manifest_met_meldingen(map_pad: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Bestandsnaam -> velden, plus meldingen over onleesbare of vreemde waarden."""
    mf = Path(map_pad) / "manifest.json"
    uit: dict[str, dict[str, Any]] = {}
    meldingen: list[str] = []
    if not mf.exists():
        return uit, meldingen
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except Exception as e:
        return uit, [f"{mf}: manifest onleesbaar ({type(e).__name__}); alle beelden "
                     f"in deze map krijgen standaardclassificatie"]
    _loop_manifest(data, {}, uit, meldingen, "lijst" if isinstance(data, list) else "object")
    return uit, meldingen


def _lees_manifest(map_pad: Path) -> dict[str, dict[str, Any]]:
    """Bestandsnaam -> {bron_naam, omschrijving, klasse, domein, taal, geladen_ok,
    kwaliteit, ...}. Werkt voor alle manifest-vormen (zie _loop_manifest)."""
    return lees_manifest_met_meldingen(map_pad)[0]


def verzamel_bronnen(mappen: Iterable[Path], soort: str) -> list[Bron]:
    """
    Alle beelden in `mappen`. Voor de mappen van ours/decoy/anker is `soort`
    leidend; in comp-mappen mag het manifest een beeld tot decoy, anker of ours
    bestempelen (klasse). Velden die ontbreken krijgen een veilige standaard en
    worden vermeld in Bron.ontbrekend / Bron.meldingen.
    """
    bronnen: list[Bron] = []
    for m in mappen:
        m = Path(m)
        if not m.exists():
            continue
        manifest, mmeldingen = lees_manifest_met_meldingen(m)
        for p in sorted(m.glob("*.png")) + sorted(m.glob("*.jpg")) + sorted(m.glob("*.jpeg")):
            meta = manifest.get(p.name, {})
            meldingen = list(mmeldingen)
            ontbrekend: list[str] = []
            klasse = meta.get("klasse", "")
            eff_soort = soort
            if soort == "comp":
                if klasse:
                    eff_soort = KLASSE_NAAR_SOORT.get(klasse, "comp")
            elif klasse and KLASSE_NAAR_SOORT.get(klasse) != soort:
                meldingen.append(f"manifest zegt klasse={klasse} maar de bron staat in de "
                                 f"{soort}-map; de map is leidend")
            if not klasse:
                klasse = SOORT_STANDAARD_KLASSE[eff_soort]
                if eff_soort == "comp":
                    ontbrekend.append("klasse")
            domein = meta.get("domein", "")
            if not domein:
                domein = SOORT_STANDAARD_DOMEIN.get(eff_soort) or SET_STANDAARD_DOMEIN.get(m.name, "")
                if eff_soort == "comp":
                    ontbrekend.append("domein")
            taal = meta.get("taal", "") or SET_STANDAARD_TAAL.get(m.name, "")
            soort_scherm = meta.get("soort_scherm", "")
            if not soort_scherm and eff_soort in ("comp", "ours"):
                ontbrekend.append("soort_scherm")
            if manifest and not meta:
                meldingen.append("beeld staat niet in het manifest van zijn map")
            viewport = bepaal_viewport(p.name)
            if viewport == "onbekend" and meta.get("viewport_manifest"):
                viewport = viewport_uit_tekst(meta["viewport_manifest"])
                if viewport != "onbekend":
                    meldingen.append(f"viewport ({viewport}) uit het manifest gehaald; "
                                     f"de bestandsnaam zegt het niet")
            bronnen.append(Bron(
                pad=p,
                set_naam=m.name,
                soort=eff_soort,
                bron_naam=meta.get("bron_naam") or p.stem,
                viewport=viewport,
                omschrijving=meta.get("omschrijving", ""),
                klasse=klasse,
                domein=domein,
                taal=taal,
                geladen_ok=meta.get("geladen_ok"),
                kwaliteit=meta.get("kwaliteit", "") if eff_soort == "decoy" else "",
                bron_id=meta.get("bron_id", ""),
                soort_scherm=soort_scherm,
                manifest_vorm=meta.get("manifest_vorm", ""),
                meldingen=meldingen,
                ontbrekend=ontbrekend,
            ))
    return bronnen


def filter_bronnen(bronnen: list[Bron], domein: str = "alles",
                   inclusief_marketing: bool = False,
                   soorten_scherm: Iterable[str] | None = None
                   ) -> tuple[list[Bron], list[dict]]:
    """
    Past de rondefilters toe. Uitgesloten (met reden in de terugvoer):
      - geladen_ok == False                      (NOOIT in een ronde)
      - klasse marketing, tenzij --inclusief-marketing
      - comps buiten het gevraagde domein (--domein); eigen schermen, decoys en
        ankers doen altijd mee
      - comps waarvan de soort_scherm buiten --soort-scherm valt (of onbekend is)
    """
    gevraagd = {norm_soort_scherm(x) for x in (soorten_scherm or [])}
    if domein not in DOMEIN_FILTERS:
        raise ValueError(f"onbekend domeinfilter {domein!r}; kies uit {DOMEIN_FILTERS}")
    behouden: list[Bron] = []
    uitgesloten: list[dict] = []

    def uit(b: Bron, reden: str) -> None:
        uitgesloten.append({"bron_bestand": _rel(b.pad), "bron_naam": b.bron_naam,
                            "soort": b.soort, "viewport": b.viewport, "reden": reden})

    for b in bronnen:
        if b.geladen_ok is False:
            uit(b, "geladen_ok=false: de opnamecontrole keurde dit beeld af")
        elif b.soort == "comp" and b.klasse == "marketing" and not inclusief_marketing:
            uit(b, "klasse=marketing (standaard uitgesloten; --inclusief-marketing om mee te nemen)")
        elif b.soort == "comp" and domein != "alles" and b.domein != domein:
            uit(b, f"domein={b.domein or 'onbekend'} valt buiten het filter {domein}")
        elif b.soort == "comp" and gevraagd and b.soort_scherm not in gevraagd:
            uit(b, f"soort_scherm={b.soort_scherm or 'onbekend'} valt buiten het filter "
                   f"{', '.join(sorted(gevraagd))}")
        else:
            behouden.append(b)
    return behouden, uitgesloten


def _rel(pad: Path) -> str:
    return str(pad.relative_to(PROJECT)) if str(pad).startswith(str(PROJECT)) else str(pad)


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
# 3/4. Vaste hoogte: secties boven/midden/onder (hoogte is geen vingerafdruk)
# ---------------------------------------------------------------------------
def sectie_posities(paginahoogte: int, spec: SectieSpec) -> list[int]:
    """
    Beginrij van elke sectie in de pagina (al op uitvoerbreedte geschaald).

    Is de pagina minstens `aantal` secties hoog, dan worden ze gelijkmatig over de
    pagina verdeeld: de eerste begint bovenaan, de laatste eindigt onderaan en de
    rest ligt ertussen (bij drie: boven, midden, onder). Ze overlappen NOOIT: de
    afstand tussen twee begin-rijen is minstens een sectiehoogte. Is de pagina
    korter, dan sluiten de secties aan vanaf de bovenkant; wat voorbij het einde
    van de pagina valt wordt opgevuld. Op de overgang (pagina precies `aantal`
    secties hoog) vallen beide regels samen, dus de uitsnede springt niet.
    """
    s, h = spec.aantal, spec.hoogte
    if s <= 1:
        return [0]
    if paginahoogte >= s * h:
        return [round(i * (paginahoogte - h) / (s - 1)) for i in range(s)]
    return [i * h for i in range(s)]


def _paginaachtergrond(img: Image.Image) -> tuple[int, int, int]:
    """Achtergrondkleur onderaan de pagina: mediaan van de laatste rijen."""
    h = img.height
    strook = np.asarray(img.crop((0, max(0, h - 6), img.width, h)).convert("RGB"))
    return tuple(int(v) for v in np.median(strook.reshape(-1, 3), axis=0))


def snij_secties(img: Image.Image, spec: SectieSpec) -> tuple[Image.Image, dict]:
    """
    Bouwt het beeld met vaste afmetingen: `spec.aantal` uitsneden van de pagina
    (img, RGB, al op uitvoerbreedte) onder elkaar, gescheiden door lege balken.
    Retourneert (beeld, meta); meta bevat de posities, de opvulling en de rijen
    van de scheidingsbalken (die na de contrastbewerking op vaste kleur komen).
    """
    breedte, paginahoogte = img.width, img.height
    s, h, g = spec.aantal, spec.hoogte, spec.scheiding
    ys = sectie_posities(paginahoogte, spec)
    achtergrond = _paginaachtergrond(img)
    doek = Image.new("RGB", (breedte, spec.totale_hoogte), achtergrond)
    gaten: list[tuple[int, int]] = []
    opvulling = 0
    inhoud_einde = 0
    for i, y in enumerate(ys):
        top = i * (h + g)
        y1 = min(paginahoogte, y + h)
        echt = max(0, y1 - y) if y < paginahoogte else 0
        if echt:
            doek.paste(img.crop((0, y, breedte, y + echt)), (0, top))
            inhoud_einde = top + echt
        opvulling += h - echt
        if i < s - 1:
            gaten.append((top + h, top + h + g))
    meta = {
        "aantal": s, "sectiehoogte_px": h, "scheiding_px": g,
        "paginahoogte_px": int(paginahoogte),
        "posities_px": [int(y) for y in ys],
        "opvulling_px": int(opvulling),
        "korte_pagina": bool(paginahoogte < s * h),
        "footer_zichtbaar": bool(ys[-1] + h >= paginahoogte),
        "inhoud_einde_y": int(inhoud_einde),
        "scheidingsrijen": [[int(a), int(b)] for a, b in gaten],
        "achtergrond_rgb": list(achtergrond),
    }
    return doek, meta


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
                       extra: list[list[float]] | None = None,
                       footer_einde_y: int | None = None) -> tuple[int, list[dict]]:
    """
    Maskeert de plekken waar merkidentiteit vrijwel altijd zit:
      - linksboven in de merkbalk (woordmerk/logo)
      - rechtsboven in de merkbalk (accountmerk, taalkiezer, merkknoppen)
    Optioneel de footer-linkerhoek, en handmatig opgegeven extra rechthoeken.
    `footer_einde_y` is het einde van de echte inhoud (bij een pagina die korter
    is dan de secties); standaard de onderkant van het beeld.

    De maskerhoogte is VAST op 8% van de beeldbreedte (circa 115 css px), niet
    gedetecteerd. Automatische detectie van 'de onderkant van de header' faalt
    twee kanten op: bij een dunne meldingsbalk bovenaan stopt het masker te vroeg
    en blijft het logo eronder gewoon staan, en bij een sitekop zonder scheiding
    loopt het door tot over de paginatitel - precies de typografie die beoordeeld
    moet worden. Een vaste, ruime maar begrensde band is voorspelbaarder.

    Dit dekt alleen de PLEK van het merk. Merknamen in koppen, broodtekst en
    URL's vangt de OCR-lekcontrole (controleer_lekken), niet dit masker.
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
        fy1 = min(img.height, footer_einde_y) if footer_einde_y else img.height
        fy0 = max(0, fy1 - int(img.height * 0.08)) if footer_einde_y else int(img.height * 0.92)
        kaders.append(("footer-links", (0, fy0, int(w * 0.34), fy1)))
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
                 extra_maskers: list[list[float]] | None = None,
                 secties: SectieSpec | None = None
                 ) -> tuple[Image.Image, NeutralisatieLog]:
    """
    Zonder `secties`: het oude gedrag (hoogte begrensd op max_hoogte_ratio x
    breedte; de hoogte volgt dan de bron en is dus een vingerafdruk).
    Met `secties`: vaste afmetingen via snij_secties(); max_hoogte_ratio telt dan niet.
    """
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

    sectie_meta: dict = {}
    if secties is None:
        # 3. hoogte begrenzen (identieke leeslengte, en houdt het geheugen hanteerbaar)
        if max_hoogte_ratio and max_hoogte_ratio > 0:
            max_h = int(img.width * max_hoogte_ratio)
            if img.height > max_h:
                log.hoogte_begrensd_px = img.height - max_h
                img = img.crop((0, 0, img.width, max_h))

        # 4. identieke breedte
        nieuwe_h = max(1, round(img.height * breedte / img.width))
        img = img.resize((breedte, nieuwe_h), Image.LANCZOS)
    else:
        # 3+4. identieke breedte, daarna vaste hoogte uit boven/midden/onder
        nieuwe_h = max(1, round(img.height * breedte / img.width))
        img = img.resize((breedte, nieuwe_h), Image.LANCZOS)
        img, sectie_meta = snij_secties(img, secties)
        log.secties = sectie_meta
    log.geschaald_naar = (img.width, img.height)

    # 5. merkregio's maskeren; de footer alleen als het onderste stuk van de pagina in beeld is
    footer_aan = maskeer_footer and (not sectie_meta or bool(sectie_meta.get("footer_zichtbaar", True)))
    header_h, regios = maskeer_merkregios(
        img, viewport, footer_aan, merkbalk_hoogte, extra_maskers,
        footer_einde_y=(sectie_meta.get("inhoud_einde_y") or None) if sectie_meta else None)
    log.headerhoogte_px, log.gemaskeerde_regios = header_h, regios

    # 6. kleur neutraliseren
    img, log.grijs_methode = naar_neutraal_grijs(img, chroma_winst=chroma_winst)

    # 7. contrast
    img, log.contrast_methode = pas_contrast_toe(img, contrast)

    # 7b. scheidingsbalken op vaste kleur, onafhankelijk van de bron
    if secties is not None and sectie_meta.get("scheidingsrijen"):
        d = ImageDraw.Draw(img)
        for y0, y1 in sectie_meta["scheidingsrijen"]:
            d.rectangle([0, y0, img.width, y1 - 1], fill=secties.grijs)

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


def controleer_hoogte_eigenschap(afmetingen: dict[str, list[tuple[int, int]]]) -> list[str]:
    """
    Toetst de ronde-eigenschap "hoogte is geen vingerafdruk": per viewport hoogstens
    EEN unieke hoogte (en breedte). `afmetingen` is viewport -> lijst van
    (breedte, hoogte) van de weggeschreven beelden. Retourneert de schendingen.
    """
    fouten: list[str] = []
    for vp, lijst in afmetingen.items():
        hoogtes = sorted({h for _w, h in lijst})
        breedtes = sorted({w for w, _h in lijst})
        if len(hoogtes) > 1:
            fouten.append(f"{vp}: {len(hoogtes)} unieke hoogtes ({hoogtes[:6]}"
                          f"{'...' if len(hoogtes) > 6 else ''}) - de hoogte verraadt de bron")
        if len(breedtes) > 1:
            fouten.append(f"{vp}: {len(breedtes)} unieke breedtes ({breedtes[:6]})")
    return fouten


# ---------------------------------------------------------------------------
# 8. OCR-lekcontrole op de pixels
# ---------------------------------------------------------------------------
class OcrNietBeschikbaar(RuntimeError):
    """Geen werkende OCR-engine: de blindering is dan niet te garanderen."""


class OcrOnbetrouwbaar(RuntimeError):
    """Een engine draait maar haalt de ijkcontrole niet."""


_FOLD = str.maketrans({"1": "l", "i": "l", "0": "o", "5": "s"})


def vouw(tekst: str) -> str:
    """
    Compacte vergelijkingsvorm: zonder accenten, spaties en leestekens, kleine
    letters, en met de klassieke OCR-verwisselingen samengevouwen (i/l/1, o/0,
    s/5). "lnterpolis" en "Interpolis" worden zo dezelfde string.
    """
    s = unicodedata.normalize("NFKD", tekst)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = "".join(c for c in s if c.isascii() and c.isalnum())
    return s.translate(_FOLD)


_NOOIT_ALLEEN_VORMEN = frozenset(vouw(w) for w in NOOIT_ALLEEN)
_STRIKT_VORMEN = frozenset(vouw(w) for w in STRIKT_HELE_WOORD)
_AMBIGU_VORMEN = frozenset(vouw(w) for w in AMBIGUE_WOORDEN)
_GENERIEK_VORMEN = frozenset(vouw(w) for w in GENERIEKE_WOORDEN)


@dataclass
class VerbodenTerm:
    tekst: str        # zoals opgegeven
    vorm: str         # gevouwen compacte vorm
    modus: str        # 'sub' (mag in een langer woord voorkomen) | 'woord' (heel woord)
    bron: str = "vast"
    strikt: bool = False   # aaneengesloten, en niet als "Titelcase" (zie STRIKT_HELE_WOORD)
    fuzzy: bool = False    # mag met een verlezing (1 bewerking) gevonden worden


class VerbodenTermen:
    """De verzameling verboden woorden voor de OCR-controle."""

    def __init__(self) -> None:
        self._items: dict[str, VerbodenTerm] = {}

    def voeg_toe(self, tekst: str, bron: str = "vast", modus: str | None = None) -> bool:
        vorm = vouw(tekst)
        if len(vorm) < 3:
            return False                       # te kort om betrouwbaar te herkennen
        if vorm in _NOOIT_ALLEEN_VORMEN:
            return False                       # gewoon woord; alleen samenstellingen tellen
        if vorm in self._items:
            return False
        strikt = vorm in _STRIKT_VORMEN
        if modus is None:
            modus = "woord" if (len(vorm) <= 4 or vorm in _AMBIGU_VORMEN) else "sub"
        # Verlezingen alleen bij lange, eigen namen. Een samenstelling van een gewoon woord met een
        # achtervoegsel (geld+nl, overstappen+nl, exact+com) mag NIET fuzzy: "geld na" ligt op een
        # bewerking van "geldnl" en zou elke zin met "geld naar" wegmaskeren.
        gewoon_begin = any(vorm.startswith(n) for n in _NOOIT_ALLEEN_VORMEN if len(n) >= 4)
        fuzzy = len(vorm) >= 8 and not strikt and not gewoon_begin and modus == "sub"
        self._items[vorm] = VerbodenTerm(tekst, vorm, modus, bron, strikt, fuzzy)
        return True

    def __len__(self) -> int:
        return len(self._items)

    @property
    def alle(self) -> list[VerbodenTerm]:
        return list(self._items.values())

    @property
    def sub(self) -> list[VerbodenTerm]:
        return [t for t in self._items.values() if t.modus == "sub"]

    @property
    def woord(self) -> list[VerbodenTerm]:
        return [t for t in self._items.values() if t.modus == "woord"]

    def samenvatting(self) -> dict:
        per_bron: dict[str, int] = {}
        for t in self._items.values():
            per_bron[t.bron.split(":")[0]] = per_bron.get(t.bron.split(":")[0], 0) + 1
        return {"aantal": len(self), "per_bron": per_bron,
                "termen": sorted(t.tekst for t in self._items.values())}


def _termen_uit_naam(naam: str) -> set[str]:
    """Een merknaam uit een 'lange' naam: alleen het eerste segment. Een woord
    tellen we mee; bij meerdere woorden alleen de samenvoeging ("Centraal Beheer"
    -> centraalbeheer), want losse woorden zijn vaak gewoon Nederlands."""
    uit: set[str] = set()
    segment = re.split(r"\s[-–—|:]\s|[(:|,/]", naam, maxsplit=1)[0].strip()
    woorden = [w for w in re.split(r"[\s_]+", segment) if w]
    woorden = [w for w in woorden if vouw(w) and vouw(w) not in _GENERIEK_VORMEN]
    if len(woorden) == 1:
        uit.add(woorden[0].strip(".,"))
    elif len(woorden) > 1:
        uit.add("".join(woorden[:3]))
    return uit


def _termen_uit_slug(slug: str) -> list[tuple[str, bool]]:
    """(term, zwak). Het merk staat vooraan in id's en slugs (stripe_api_docs, independer-auto...);
    volgt een domeinachtervoegsel (cal_com, geld-nl) dan telt de samenvoeging. De losse eerste sectie is
    'zwak': het kan ook gewoon een woord zijn (data-overheid-datasets, actual_budget_demo) en telt daarom
    alleen als HEEL woord, nooit als deel van een langer woord."""
    delen = [d for d in re.split(r"[\s_\-.]+", slug.lower()) if d]
    uit: list[tuple[str, bool]] = []
    if not delen:
        return uit
    eerste = delen[0]
    if len(delen) > 1 and delen[1] in TLD_DELEN:
        uit.append((eerste + delen[1], False))
    if vouw(eerste) not in _GENERIEK_VORMEN:
        uit.append((eerste, True))
    return uit


def _termen_uit_url(url: str) -> set[str]:
    uit: set[str] = set()
    m = re.match(r"^(?:[a-z]+://)?([^/\s?#]+)", url.strip().lower())
    if not m:
        return uit
    labels_ = [l for l in m.group(1).split(".") if l]
    achtervoegsel = ""
    while labels_ and labels_[-1] in TLD_DELEN:
        achtervoegsel = achtervoegsel or labels_[-1]
        labels_.pop()
    if labels_ and labels_[0] in ("www", "docs", "app", "mijn", "play", "api"):
        if len(labels_) > 1:
            eerste = labels_[0]
            labels_ = labels_[1:]
            if eerste == "mijn":
                uit.add("mijn" + labels_[-1])
    if labels_:
        kern = labels_[-1].replace("-", "")
        if vouw(kern) not in _GENERIEK_VORMEN:
            uit.add(kern)
            if achtervoegsel:
                uit.add(kern + achtervoegsel)        # kvk.nl, afm.nl: de vorm zoals ze in beeld staat
    return uit


def _verzamel_manifest_strings(knoop: Any, uit: dict[str, set[str]]) -> None:
    """Loopt door een manifest en verzamelt naam-, slug-, url- en expliciete velden."""
    if isinstance(knoop, list):
        for e in knoop:
            _verzamel_manifest_strings(e, uit)
    elif isinstance(knoop, dict):
        for k, v in knoop.items():
            if isinstance(v, str):
                if k in ("bron_naam", "naam", "merk", "merknaam", "product"):
                    uit["namen"].add(v)
                elif k in ("slug", "id"):
                    uit["slugs"].add(v)
                elif k in ("url", "bron_url", "eind_url"):
                    uit["urls"].add(v)
            elif isinstance(v, list) and k in ("merknamen", "verboden_woorden", "merken"):
                uit["expliciet"].update(str(x) for x in v if isinstance(x, str))
            elif isinstance(v, (dict, list)):
                _verzamel_manifest_strings(v, uit)


def termen_uit_manifesten(mappen: Iterable[Path]) -> list[tuple[str, str]]:
    """(term, herkomst) voor alle merknamen in de manifesten van `mappen`."""
    uit: list[tuple[str, str]] = []
    for m in mappen:
        mf = Path(m) / "manifest.json"
        if not mf.exists():
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        verz: dict[str, set[str]] = {"namen": set(), "slugs": set(), "urls": set(), "expliciet": set()}
        _verzamel_manifest_strings(data, verz)
        herkomst = f"manifest:{Path(m).name}"
        for n in verz["namen"]:
            uit += [(t, herkomst) for t in _termen_uit_naam(n)]
        for s in verz["slugs"]:
            uit += [(t, herkomst + (":zwak" if zwak else "")) for t, zwak in _termen_uit_slug(s)]
        for u in verz["urls"]:
            uit += [(t, herkomst) for t in _termen_uit_url(u)]
        uit += [(t, herkomst) for t in verz["expliciet"]]
    return uit


def bouw_verboden_termen(manifest_mappen: Iterable[Path] = (),
                         extra: Iterable[str] = (),
                         eigen_namen: Iterable[str] = ()) -> VerbodenTermen:
    """De statische lijst + alles uit de manifesten + door de operator opgegeven namen."""
    termen = VerbodenTermen()
    for t in VERBODEN_MERKEN:
        termen.voeg_toe(t, "vast")
    for t, herkomst in termen_uit_manifesten(list(manifest_mappen)):
        termen.voeg_toe(t, herkomst, modus="woord" if herkomst.endswith(":zwak") else None)
    for t in extra:
        termen.voeg_toe(t, "operator")
    for t in eigen_namen:
        termen.voeg_toe(t, "eigen_naam")
    return termen


# ---- OCR-resultaten ---------------------------------------------------------
Kader = tuple[float, float, float, float]


@dataclass
class OcrTeken:
    ch: str
    kader: Kader
    woordstart: bool = False


@dataclass
class OcrRegel:
    tekens: list[OcrTeken]
    kader: Kader
    zekerheid: float
    engine: str

    @property
    def tekst(self) -> str:
        return "".join(t.ch for t in self.tekens)


@dataclass
class Lek:
    term: str
    gelezen: str
    kader: Kader
    engine: str
    zekerheid: float


@dataclass
class OcrRapport:
    engines: list[str] = field(default_factory=list)
    woorden_gelezen: int = 0
    regels_gelezen: int = 0
    kaders_gemaskeerd: int = 0
    doorgangen: int = 0
    gemaskeerde_termen: list[str] = field(default_factory=list)
    rest_lekken: list[dict] = field(default_factory=list)
    dekking: str = "ok"                 # 'ok' | 'laag'
    tijd_s: float = 0.0


def _union(kaders: Iterable[Kader]) -> Kader:
    ks = list(kaders)
    return (min(k[0] for k in ks), min(k[1] for k in ks),
            max(k[2] for k in ks), max(k[3] for k in ks))


def _compact(regel: OcrRegel) -> tuple[str, list[int], list[bool]]:
    """Gevouwen tekst van een regel + per teken de index in regel.tekens + of dat
    teken een woord begint (spatie, leesteken of zichtbare tussenruimte ervoor)."""
    uit: list[str] = []
    idx: list[int] = []
    start: list[bool] = []
    nieuw = True
    for i, t in enumerate(regel.tekens):
        if t.woordstart:
            nieuw = True
        gevouwen = vouw(t.ch)
        if not gevouwen:
            nieuw = True
            continue
        for c in gevouwen:
            uit.append(c)
            idx.append(i)
            start.append(nieuw)
            nieuw = False
    return "".join(uit), idx, start


def _hooguit_een_bewerking(a: str, b: str) -> bool:
    """Editafstand tussen a en b is hoogstens 1 (invoegen, weglaten, vervangen)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    i = j = 0
    fout = 0
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        fout += 1
        if fout > 1:
            return False
        if la == lb:
            i += 1
            j += 1
        elif la > lb:
            i += 1
        else:
            j += 1
    fout += (la - i) + (lb - j)
    return fout <= 1


def _zoek_bijna(vorm: str, comp: str) -> tuple[int, int] | None:
    """Eerste stuk van `comp` dat op hooguit een bewerking na gelijk is aan `vorm`.
    Alleen voor lange woorden (>= 6): korte woorden geven te veel vals alarm."""
    n = len(vorm)
    half = n // 2
    if vorm[:half] not in comp and vorm[-half:] not in comp:
        return None                             # goedkope voorselectie
    for lengte in (n, n - 1, n + 1):
        for s in range(0, len(comp) - lengte + 1):
            if _hooguit_een_bewerking(vorm, comp[s:s + lengte]):
                return s, s + lengte
    return None


def vind_lekken(regels: list[OcrRegel], termen: VerbodenTermen) -> list[Lek]:
    """
    Zoekt verboden woorden in gelezen regels. Werkt op de samengevouwen tekst van
    een hele regel, zodat ook samengeplakte tekst ("PolisBeheer-inten") en
    samenstellingen ("api.stripe.com") gevonden worden. Termen in modus 'woord'
    (korte of dubbelzinnige woorden zoals cal, dub, ramp, stripe) tellen alleen als
    heel woord.
    """
    lekken: list[Lek] = []
    for regel in regels:
        comp, idx, start = _compact(regel)
        if len(comp) < 3:
            continue
        gezien: set[tuple[int, int]] = set()

        def noteer(s: int, e: int, term: VerbodenTerm) -> None:
            if (s, e) in gezien:
                return
            gezien.add((s, e))
            tekens = regel.tekens[idx[s]:idx[e - 1] + 1]
            lekken.append(Lek(
                term=term.tekst,
                gelezen="".join(t.ch for t in tekens),
                kader=_union(t.kader for t in tekens),
                engine=regel.engine,
                zekerheid=regel.zekerheid,
            ))

        def strikt_toegestaan(term: VerbodenTerm, s: int, e: int) -> bool:
            """Voor vakjargon-merken: aaneengesloten en niet in Titelcase."""
            if not term.strikt:
                return True
            if any(start[s + 1:e]):
                return False                                    # "polis beheer": twee woorden
            ruw = "".join(t.ch for t in regel.tekens[idx[s]:idx[e - 1] + 1])
            letters = [c for c in ruw if c.isalpha()]
            return not (len(letters) > 1 and letters[0].isupper() and "".join(letters[1:]).islower())

        for term in termen.sub:
            v = term.vorm
            pos = comp.find(v)
            if pos < 0:
                if term.fuzzy:
                    bijna = _zoek_bijna(v, comp)
                    if bijna:
                        noteer(bijna[0], bijna[1], term)
                continue
            while pos >= 0:
                if strikt_toegestaan(term, pos, pos + len(v)):
                    noteer(pos, pos + len(v), term)
                pos = comp.find(v, pos + 1)
        for term in termen.woord:
            v = term.vorm
            # Een term van hoogstens drie letters (ING, AFM, KvK) is als klein woord vrijwel altijd een
            # woorddeel: 'ing' zit in Afdeling en Wijziging, en de tekenkaders van de OCR zetten daar soms
            # een valse woordgrens. Zulke termen tellen daarom alleen met een hoofdletter (URL's vangen de
            # samenstellingen als 'kvknl'). Een term met punten (a.s.r.) valt hier niet onder.
            kort_acroniem = len(v) <= 3 and "." not in term.tekst
            pos = comp.find(v)
            while pos >= 0:
                eind = pos + len(v)
                heel_woord = start[pos] and (eind >= len(comp) or start[eind])
                if heel_woord and kort_acroniem:
                    ruw_kort = "".join(t.ch for t in regel.tekens[idx[pos]:idx[eind - 1] + 1])
                    heel_woord = any(c.isupper() for c in ruw_kort if c.isalpha())
                if not heel_woord and len(v) >= 5 and not term.bron.endswith(":zwak"):
                    # RapidOCR levert vaak tekst zonder spaties ("gegevensStripeschadeformulier"); een
                    # merkwoord van 5+ letters dat met hoofdletter (of in kapitalen) in zo'n reeks staat,
                    # tellen we mee. Kleine letters midden in een woord ("striped") niet. Een 'zwakke' term
                    # (losse slugsectie, kan gewoon een woord zijn) telt nooit als deel van een langer woord.
                    ruw = "".join(t.ch for t in regel.tekens[idx[pos]:idx[eind - 1] + 1])
                    letters = [c for c in ruw if c.isalpha()]
                    heel_woord = bool(letters) and letters[0].isupper() and (
                        "".join(letters[1:]).islower() or "".join(letters).isupper())
                if heel_woord:
                    noteer(pos, eind, term)
                pos = comp.find(v, pos + 1)
    return lekken


def _regel_uit_woorden(woorden: list[tuple[str, Kader]], zekerheid: float, engine: str
                       ) -> OcrRegel | None:
    """Regel opbouwen uit woorden met kader; tekenkaders volgens gelijke verdeling."""
    tekens: list[OcrTeken] = []
    for tekst, kader in woorden:
        if not tekst:
            continue
        x0, y0, x1, y1 = kader
        n = len(tekst)
        stap = (x1 - x0) / n
        for k, ch in enumerate(tekst):
            tekens.append(OcrTeken(ch, (x0 + k * stap, y0, x0 + (k + 1) * stap, y1),
                                   woordstart=(k == 0)))
    if not tekens:
        return None
    return OcrRegel(tekens, _union(t.kader for t in tekens), zekerheid, engine)


def _dedup_regels(regels: list[OcrRegel]) -> list[OcrRegel]:
    """Banden overlappen; dezelfde regel wordt dan twee keer gelezen."""
    gezien: set[tuple[str, int, int]] = set()
    uit: list[OcrRegel] = []
    for r in regels:
        sl = (vouw(r.tekst), round(r.kader[0] / 12), round(r.kader[1] / 12))
        if sl in gezien:
            continue
        gezien.add(sl)
        uit.append(r)
    return uit


def tel_woorden(regels: list[OcrRegel]) -> int:
    n = 0
    for r in _dedup_regels(regels):
        comp, _idx, start = _compact(r)
        n += max(1, sum(1 for s in start if s)) if comp else 0
    return n


BLANCO_BEREIK = 10        # een band met minder helderheidsverschil dan dit bevat geen leesbare tekst


def _raakt(y0: int, y1: int, gebieden: list[tuple[float, float]] | None) -> bool:
    """Ligt de band (y0, y1) over een van de gebieden? Zonder gebieden: altijd."""
    if gebieden is None:
        return True
    return any(g0 < y1 and g1 > y0 for g0, g1 in gebieden)


def _is_blanco(band: Image.Image) -> bool:
    """Geen enkele rij met leesbaar contrast: lege pagina-opvulling of een egale scheidingsbalk."""
    a = np.asarray(band.convert("L")).astype(np.int16)
    return int((a.max(axis=1) - a.min(axis=1)).max()) < BLANCO_BEREIK


def _overlap_fractie(a: Kader, b: Kader) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    kleinste = max(1e-6, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))
    return (ix * iy) / kleinste


def voeg_lekken_samen(lekken: list["Lek"]) -> list["Lek"]:
    """Dezelfde plek wordt door meerdere banden, passes en engines gevonden; overlappende
    kaders (>= 30% van het kleinste) worden een kader, zodat er een keer gemaskeerd en
    eerlijk geteld wordt."""
    samen: list[Lek] = []
    for l in sorted(lekken, key=lambda x: (x.kader[1], x.kader[0])):
        for m in samen:
            if _overlap_fractie(l.kader, m.kader) >= 0.3:
                m.kader = _union([l.kader, m.kader])
                if l.engine not in m.engine.split("+"):
                    m.engine += "+" + l.engine
                break
        else:
            samen.append(Lek(l.term, l.gelezen, l.kader, l.engine, l.zekerheid))
    return samen


def _bands(hoogte: int, band: int, overlap: int) -> list[tuple[int, int]]:
    uit: list[tuple[int, int]] = []
    y = 0
    while True:
        y1 = min(hoogte, y + band)
        uit.append((y, y1))
        if y1 >= hoogte:
            return uit
        y = y1 - overlap


def _ocr_threads() -> int:
    """Aantal rekendraden voor RapidOCR. Standaard 2: op een gedeelde of drukke machine is dat
    aantoonbaar sneller dan alle cores (hier 1,6 s tegen 3,7 s per band, met de helft van de
    CPU-tijd), en op een rustige machine verlies je weinig. BLIND_AB_OCR_THREADS overschrijft;
    0 of -1 = alle cores."""
    env = os.environ.get("BLIND_AB_OCR_THREADS")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return max(1, min(2, os.cpu_count() or 1))


def ocr_schaal(viewport: str, breedte: int) -> float:
    """
    Vergrotingsfactor voor de OCR, zodat kleine tekst voor de engine groot genoeg is. Op
    desktopopnames (1440 css px naar 1200 px, dus 0,83 px per css px) is 13 px bodytekst nog
    maar 11 px hoog en helpt 2x vergroten aantoonbaar (92% -> 99% op het testpaneel).
    Mobiele opnames (390 css px op 780 px) zijn al 2 px per css px: daar haalde 1,0x tot 1,5x
    100% (n=105) en is 1,5x alleen marge. Kleine testbeelden krijgen de bovengrens.
    """
    css_breedte = 390 if viewport == "mobile" else 1440
    px_per_css = max(0.05, breedte / css_breedte)
    return round(min(2.5, max(1.5, 1.7 / px_per_css)), 2)


class RapidOcrEngine:
    """
    RapidOCR (PP-OCR via ONNX Runtime): pip-installeerbaar, geen GPU, modellen zitten in het
    pakket. Leest per uitsnede (sectie) in banden van 800 px, op de schaal die ocr_schaal()
    kiest; de resolutielimiet van de engine (2000 px langste zijde) staat verhoogd zodat er
    niet stil wordt teruggeschaald. Tussen twee secties staat een egale balk, dus een
    tekstregel loopt daar nooit doorheen en overlap is onnodig; alleen binnen een hoge sectie
    (mobiel) overlappen de banden. Een aanvullende detectiepass op het hele, sterk verkleinde
    beeld leest alleen zeer grote letters die de bandpasses niet al hadden.
    Gemeten op de gerenderde decoy (126 woorden als grondwaarheid uit de HTML): 96,0% desktop.
    Een volledige tweede lezing op het omgekeerde beeld gaf +2 woorden voor 3x de rekentijd en
    een omgekeerde detectiepass niets voor +25%, dus die zitten er niet in; de tweede mening
    komt van tesseract (samen 98,4%), dat licht-op-donker badges anders leest.
    De herkenning per regel is de dure stap, niet de detectie; daarom geen dubbel werk.
    """
    naam = "rapidocr"
    SCHAAL = 2.0
    BAND_HOOGTE = 800
    BAND_TOLERANTIE = 1.3      # een sectie tot 1,3 x de bandhoogte blijft een band
    OVERLAP = 160
    GROF_MAX_ZIJDE = 900
    GROF_MIN_HOOGTE = 50       # de grove pass leest alleen kaders die zo hoog zijn (px in het beeld)
    MIN_BAND_HOOGTE = 320      # dunnere banden worden aangevuld: zeer brede, lage beelden (>8:1) worden
                               # door de detector niet meer betrouwbaar gelezen (gemeten: een zin van
                               # 2200 x 70 px leverde niets op)
    BOX_THRESH = 0.4
    TEXT_SCORE = 0.35

    def __init__(self, threads: int | None = None) -> None:
        from rapidocr_onnxruntime import RapidOCR   # ImportError -> niet beschikbaar
        self.threads = threads if threads is not None else _ocr_threads()
        kw: dict = {}
        if self.threads > 0:
            t = self.threads
            kw = dict(intra_op_num_threads=t, inter_op_num_threads=1,
                      det_intra_op_num_threads=t, det_inter_op_num_threads=1,
                      cls_intra_op_num_threads=t, cls_inter_op_num_threads=1,
                      rec_intra_op_num_threads=t, rec_inter_op_num_threads=1)
        self._eng = RapidOCR(**kw)
        self._eng.max_side_len = 4000

    @staticmethod
    def beschikbaar() -> tuple[bool, str]:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            import onnxruntime  # noqa: F401
        except Exception as e:
            return False, f"rapidocr-onnxruntime niet te importeren ({type(e).__name__}: {e})"
        return True, RapidOcrEngine.versie_tekst()

    @staticmethod
    def versie_tekst() -> str:
        try:
            return (f"rapidocr-onnxruntime {_metadata.version('rapidocr-onnxruntime')}, "
                    f"onnxruntime {_metadata.version('onnxruntime')}")
        except Exception:
            return "rapidocr-onnxruntime (versie onbekend)"

    def beschrijving(self) -> dict:
        return {"naam": self.naam, "versie": self.versie_tekst(),
                "instelling": {"schaal_desktop_standaard": self.SCHAAL, "band_px": self.BAND_HOOGTE,
                               "overlap_px": self.OVERLAP, "threads": self.threads,
                               "grove_detectiepass_grote_letters": True, "box_thresh": self.BOX_THRESH,
                               "text_score": self.TEXT_SCORE}}

    def _lees(self, arr: np.ndarray, schaal: float, x_off: float, y_off: float) -> list[OcrRegel]:
        # use_cls=False: de hoekclassifier draait willekeurig ~25% van de lange, horizontale regels
        # 180 graden om, waarna de herkenning onzin geeft (score < 0,35) en de regel wegvalt. Gemeten
        # op een pagina met 48 brede regels (65-211 tekens): 58% van de merkwoorden gevonden met,
        # 100% zonder classifier. Interface-tekst staat nooit ondersteboven.
        res, _ = self._eng(arr, use_cls=False, box_thresh=self.BOX_THRESH, text_score=self.TEXT_SCORE,
                           unclip_ratio=1.6, return_word_box=True)
        uit: list[OcrRegel] = []
        for r in (res or []):
            try:
                regel = self._parse(r, schaal, x_off, y_off)
            except Exception:
                regel = None
            if regel is not None:
                uit.append(regel)
        return uit

    def _parse(self, r: list, schaal: float, x_off: float, y_off: float) -> OcrRegel | None:
        box, tekst, score = r[0], str(r[1]), float(r[2])
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        kader = (x_off + min(xs) / schaal, y_off + min(ys) / schaal,
                 x_off + max(xs) / schaal, y_off + max(ys) / schaal)
        hoogte = max(1.0, kader[3] - kader[1])
        tekens: list[OcrTeken] = []
        if len(r) >= 5 and r[3] and r[4] and len(r[3]) == len(r[4]):
            vorige_x1 = None
            for ch, b in zip(r[4], r[3]):
                bx = [p[0] for p in b]
                by = [p[1] for p in b]
                k = (x_off + min(bx) / schaal, y_off + min(by) / schaal,
                     x_off + max(bx) / schaal, y_off + max(by) / schaal)
                gat = None if vorige_x1 is None else k[0] - vorige_x1
                # tussenruimte > 0,28 x regelhoogte of een echte spatie = nieuw woord
                tekens.append(OcrTeken(str(ch), k, woordstart=(
                    str(ch).isspace() or (gat is not None and gat > 0.28 * hoogte))))
                vorige_x1 = k[2]
        if not tekens:                         # val terug op gelijke verdeling over de regel
            return self._regel_uit_tekst(tekst, kader, score)
        return OcrRegel(tekens, kader, score, self.naam)

    def _regel_uit_tekst(self, tekst: str, kader: Kader, score: float) -> OcrRegel | None:
        delen = [w for w in re.split(r"\s+", tekst) if w]
        if not delen:
            return None
        breedte = kader[2] - kader[0]
        totaal = max(1, sum(len(d) for d in delen))
        x = kader[0]
        woorden = []
        for d in delen:
            w_d = breedte * len(d) / totaal
            woorden.append((d, (x, kader[1], x + w_d, kader[3])))
            x += w_d
        return _regel_uit_woorden(woorden, score, self.naam)

    def _extra_kaders(self, detectiebeeld: Image.Image, det_schaal: float, bron: Image.Image,
                      y_off: float, bekend: list[OcrRegel],
                      gebieden: list[tuple[float, float]] | None,
                      min_hoogte: float = 8.0) -> list[OcrRegel]:
        """
        Detectie op `detectiebeeld` (andere polariteit of schaal dan de hoofdpass); alleen kaders
        die nog niemand las worden herkend, op de uitsnede uit `bron` (volle resolutie), in beide
        polariteiten waarvan de beste telt. Zo kost een tweede blik vooral detectie, niet de dure
        herkenning van regels die al gelezen zijn.
        """
        try:
            boxes, _ = self._eng(np.asarray(detectiebeeld.convert("RGB")), use_det=True, use_cls=False,
                                 use_rec=False, box_thresh=self.BOX_THRESH, unclip_ratio=1.6)
        except Exception:
            return []
        uit: list[OcrRegel] = []
        for box in (boxes or []):
            xs = [p[0] / det_schaal for p in box]
            ys = [p[1] / det_schaal for p in box]
            lokaal = (min(xs), min(ys), max(xs), max(ys))               # in bron-coordinaten
            kader = (lokaal[0], lokaal[1] + y_off, lokaal[2], lokaal[3] + y_off)   # in beeldcoordinaten
            if kader[2] - kader[0] < 6 or kader[3] - kader[1] < min_hoogte:
                continue
            if gebieden is not None and not _raakt(kader[1], kader[3], gebieden):
                continue
            if any(_overlap_fractie(kader, r.kader) >= 0.3 for r in bekend):
                continue
            m = 3
            crop = bron.crop((max(0, int(lokaal[0]) - m), max(0, int(lokaal[1]) - m),
                              min(bron.width, int(lokaal[2]) + m), min(bron.height, int(lokaal[3]) + m)))
            if crop.width < 4 or crop.height < 4:
                continue
            try:
                res, _ = self._eng.text_rec([np.asarray(crop.convert("RGB")),
                                             np.asarray(ImageOps.invert(crop).convert("RGB"))], False)
                tekst, score = max(((str(t), float(sc)) for t, sc in res), key=lambda x: x[1])
            except Exception:
                continue
            if score < self.TEXT_SCORE or not tekst.strip():
                continue
            regel = self._regel_uit_tekst(tekst, kader, score)
            if regel is not None:
                uit.append(regel)
        return uit

    def _vul_aan(self, band: Image.Image) -> tuple[Image.Image, int]:
        """Vult een te lage band boven en onder aan met de achtergrondkleur; retourneert (band, opvulling boven)."""
        if band.height >= self.MIN_BAND_HOOGTE:
            return band, 0
        totaal = self.MIN_BAND_HOOGTE - band.height
        boven = totaal // 2
        achtergrond = int(np.median(np.asarray(band)))
        doek = Image.new("L", (band.width, self.MIN_BAND_HOOGTE), achtergrond)
        doek.paste(band, (0, boven))
        return doek, boven

    def lees_beeld(self, img: Image.Image, gebieden: list[tuple[float, float]] | None = None,
                   segmenten: list[tuple[int, int]] | None = None,
                   schaal: float | None = None) -> list[OcrRegel]:
        """
        Leest het beeld. `segmenten` zijn de inhoudsstroken (de secties); banden lopen nooit over
        de grens van een strook. Met `gebieden` (y-bereiken) alleen de banden die daarover liggen,
        bedoeld voor het hercontroleren van gemaskeerde plekken. Volledig lege banden (geen
        leesbaar contrast) worden overgeslagen. `schaal` volgt uit ocr_schaal().

        Per band een volledige lezing; daarna, over het hele beeld, een detectie op een sterk
        verkleinde versie voor zeer grote letters (kaders van minstens GROF_MIN_HOOGTE px die nog
        niet gelezen zijn).
        """
        grijs = img.convert("L")
        schaal = float(schaal or self.SCHAAL)
        stroken = segmenten or [(0, grijs.height)]
        regels: list[OcrRegel] = []
        for (s0, s1) in stroken:
            s0, s1 = max(0, int(s0)), min(grijs.height, int(s1))
            if s1 <= s0:
                continue
            lengte = s1 - s0
            banden = ([(0, lengte)] if lengte <= self.BAND_HOOGTE * self.BAND_TOLERANTIE
                      else _bands(lengte, self.BAND_HOOGTE, self.OVERLAP))
            for (a, b) in banden:
                y0, y1 = s0 + a, s0 + b
                if not _raakt(y0, y1, gebieden):
                    continue
                band = grijs.crop((0, y0, grijs.width, y1))
                if _is_blanco(band):
                    continue
                band, opvulling = self._vul_aan(band)
                groot = band.resize((round(band.width * schaal), round(band.height * schaal)), Image.LANCZOS)
                regels += self._lees(np.asarray(groot.convert("RGB")), schaal, 0.0, float(y0 - opvulling))
        zij = max(grijs.width, grijs.height)
        if zij > 0:
            s = min(1.0, self.GROF_MAX_ZIJDE / zij)
            klein = grijs.resize((max(1, round(grijs.width * s)), max(1, round(grijs.height * s))),
                                 Image.LANCZOS)
            regels += self._extra_kaders(klein, s, grijs, 0.0, regels, gebieden,
                                         min_hoogte=self.GROF_MIN_HOOGTE)
        return regels


class TesseractEngine:
    """
    tesseract (apt: tesseract-ocr + tesseract-ocr-nld/-eng) als tweede mening of
    terugval. Leest in smalle banden (200 px) op dubbele schaal, met per band
    autocontrast, beide polariteiten en Sauvola-drempels. Op het testpaneel vond
    deze combinatie 88%; zonder banden en Sauvola 79%. Zwakker dan RapidOCR bij
    laag contrast en licht-op-donker, maar onafhankelijk, dus nuttig als aanvulling.
    """
    naam = "tesseract"
    SCHAAL = 2.0
    BAND_HOOGTE = 200
    OVERLAP = 50
    MIN_ZEKERHEID = 10.0

    def __init__(self) -> None:
        pad = shutil.which("tesseract")
        if not pad:
            raise OcrNietBeschikbaar("tesseract staat niet op het pad")
        self._pad = pad
        r = subprocess.run([pad, "--list-langs"], capture_output=True, text=True, timeout=60)
        talen = {t.strip() for t in r.stdout.splitlines()[1:] if t.strip()}
        if "eng" not in talen:
            raise OcrNietBeschikbaar("tesseract mist de taaldata 'eng' (apt: tesseract-ocr-eng)")
        self.taal = "nld+eng" if "nld" in talen else "eng"
        self._versie = (subprocess.run([pad, "--version"], capture_output=True, text=True,
                                       timeout=60).stdout.splitlines() or ["tesseract"])[0].strip()

    @staticmethod
    def beschikbaar() -> tuple[bool, str]:
        pad = shutil.which("tesseract")
        if not pad:
            return False, "tesseract niet gevonden (apt-get install tesseract-ocr tesseract-ocr-nld tesseract-ocr-eng)"
        try:
            r = subprocess.run([pad, "--list-langs"], capture_output=True, text=True, timeout=60)
        except Exception as e:
            return False, f"tesseract draait niet ({type(e).__name__})"
        talen = {t.strip() for t in r.stdout.splitlines()[1:] if t.strip()}
        if "eng" not in talen:
            return False, "tesseract mist taaldata 'eng' (apt-get install tesseract-ocr-eng)"
        return True, "tesseract"

    def beschrijving(self) -> dict:
        return {"naam": self.naam, "versie": f"{self._versie}, talen {self.taal}",
                "instelling": {"schaal": self.SCHAAL, "band_px": self.BAND_HOOGTE,
                               "overlap_px": self.OVERLAP, "psm": 11,
                               "drempel": "Sauvola", "polariteit": "normaal+omgekeerd",
                               "autocontrast_per_band": True}}

    def _band(self, band: Image.Image, y0: int, tmp: Path, nr: int, omgekeerd: bool) -> list[OcrRegel]:
        b = ImageOps.autocontrast(band, cutoff=1)
        b = b.resize((round(b.width * self.SCHAAL), round(b.height * self.SCHAAL)), Image.LANCZOS)
        if omgekeerd:
            b = ImageOps.invert(b)
        pad = tmp / f"b{nr}{'i' if omgekeerd else 'n'}.png"
        b.save(pad)
        env = dict(os.environ)
        env["OMP_THREAD_LIMIT"] = "1"
        r = subprocess.run(
            [self._pad, str(pad), "stdout", "-l", self.taal, "--psm", "11", "--dpi", "300",
             "-c", "thresholding_method=2", "tsv"],
            capture_output=True, text=True, timeout=180, env=env)
        return self._parse_tsv(r.stdout, y0)

    def _parse_tsv(self, tekst: str, y0: int) -> list[OcrRegel]:
        per_regel: dict[tuple[str, str, str], list[tuple[str, Kader, float]]] = {}
        for rij in csv.DictReader(io.StringIO(tekst), delimiter="\t", quoting=csv.QUOTE_NONE):
            try:
                if int(rij["level"]) != 5:
                    continue
                woord = (rij.get("text") or "").strip()
                zeker = float(rij["conf"])
                if not woord or zeker < self.MIN_ZEKERHEID:
                    continue
                l, t, w, h = (int(rij[k]) for k in ("left", "top", "width", "height"))
            except (KeyError, ValueError, TypeError):
                continue
            kader = (l / self.SCHAAL, y0 + t / self.SCHAAL,
                     (l + w) / self.SCHAAL, y0 + (t + h) / self.SCHAAL)
            per_regel.setdefault((rij["block_num"], rij["par_num"], rij["line_num"]), []
                                 ).append((woord, kader, zeker))
        uit: list[OcrRegel] = []
        for woorden in per_regel.values():
            woorden.sort(key=lambda x: x[1][0])
            zeker = sum(w[2] for w in woorden) / len(woorden) / 100.0
            regel = _regel_uit_woorden([(w[0], w[1]) for w in woorden], zeker, self.naam)
            if regel:
                uit.append(regel)
        return uit

    def lees_beeld(self, img: Image.Image, gebieden: list[tuple[float, float]] | None = None,
                   segmenten: list[tuple[int, int]] | None = None,
                   schaal: float | None = None) -> list[OcrRegel]:
        grijs = img.convert("L")
        taken = [(nr, y0, y1, om) for nr, (y0, y1) in enumerate(
            _bands(grijs.height, self.BAND_HOOGTE, self.OVERLAP)) for om in (False, True)
            if _raakt(y0, y1, gebieden) and not _is_blanco(grijs.crop((0, y0, grijs.width, y1)))]
        regels: list[OcrRegel] = []
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            werkers = max(1, min(8, os.cpu_count() or 1))
            with concurrent.futures.ThreadPoolExecutor(max_workers=werkers) as ex:
                futs = [ex.submit(self._band, grijs.crop((0, y0, grijs.width, y1)), y0, tmp, nr, om)
                        for nr, y0, y1, om in taken]
                for f in futs:
                    regels += f.result()
        return regels


def beschikbare_ocr_engines(voorkeur: str = "auto") -> tuple[list, list[str]]:
    """
    Kiest OCR-engines. 'auto' = alle beschikbare (RapidOCR eerst); 'rapidocr' of
    'tesseract' = alleen die; 'beide' = allebei verplicht. Retourneert
    (engines, meldingen). Zonder enige werkende engine: OcrNietBeschikbaar.
    """
    meldingen: list[str] = []
    engines: list = []
    gevraagd = {"auto": ("rapidocr", "tesseract"), "rapidocr": ("rapidocr",),
                "tesseract": ("tesseract",), "beide": ("rapidocr", "tesseract")}[voorkeur]
    for naam in gevraagd:
        klasse = RapidOcrEngine if naam == "rapidocr" else TesseractEngine
        ok, info = klasse.beschikbaar()
        if not ok:
            meldingen.append(f"{naam} niet beschikbaar: {info}")
            continue
        try:
            engines.append(klasse())
        except Exception as e:
            meldingen.append(f"{naam} start niet ({type(e).__name__}: {e})")
    if voorkeur == "beide" and len(engines) < 2:
        raise OcrNietBeschikbaar("--ocr-engine beide vereist rapidocr EN tesseract: "
                                 + "; ".join(meldingen))
    if not engines:
        raise OcrNietBeschikbaar(
            "GEEN WERKENDE OCR-ENGINE. Zonder OCR is niet te garanderen dat er geen merknaam "
            "in beeld staat, dus er wordt geen ronde geschreven. Installeer een engine: "
            "`pip install rapidocr-onnxruntime==1.4.4` (aanbevolen; zie requirements-dev.txt) "
            "en/of `apt-get install -y tesseract-ocr tesseract-ocr-nld tesseract-ocr-eng`. "
            "Details: " + "; ".join(meldingen))
    return engines, meldingen


def _cachemap() -> Path | None:
    """Map voor OCR-uitkomsten van hele beelden. BLIND_AB_OCR_CACHE="" schakelt de cache uit."""
    env = os.environ.get("BLIND_AB_OCR_CACHE")
    if env == "":
        return None
    kandidaten = [Path(env)] if env else [Path.home() / ".cache" / "blind_ab_ocr",
                                          Path(tempfile.gettempdir()) / "blind_ab_ocr"]
    for k in kandidaten:
        try:
            k.mkdir(parents=True, exist_ok=True)
            return k
        except Exception:
            continue
    return None


_CODE_HASH: dict[type, str] = {}


def _engine_codehash(engine) -> str:
    """Hash van dit script en de broncode van de engineklasse. Verandert de leeslogica (drempels, banden, classifier)
    of een testengine, dan zijn eerder bewaarde uitkomsten niet meer geldig: de cache is alleen een versneller en
    mag nooit een verouderde lezing teruggeven."""
    klasse = type(engine)
    if klasse not in _CODE_HASH:
        import inspect
        h = hashlib.sha256(SCRIPT_VERSIE.encode())
        try:
            h.update(Path(__file__).read_bytes())
        except OSError:
            pass
        try:
            h.update(inspect.getsource(klasse).encode())
        except (OSError, TypeError):
            h.update(klasse.__qualname__.encode())
        _CODE_HASH[klasse] = h.hexdigest()[:16]
    return _CODE_HASH[klasse]


def _cachesleutel(img: Image.Image, engine, opties: dict | None = None) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(engine.beschrijving(), sort_keys=True).encode())
    h.update(_engine_codehash(engine).encode())
    h.update(json.dumps(opties or {}, sort_keys=True, default=list).encode())
    h.update(str(img.size).encode())
    h.update(img.convert("L").tobytes())
    return h.hexdigest()


def _regels_naar_json(regels: list[OcrRegel]) -> list:
    return [[r.zekerheid, r.engine, [round(v, 1) for v in r.kader],
             [[t.ch, [round(v, 1) for v in t.kader], int(t.woordstart)] for t in r.tekens]]
            for r in regels]


def _regels_uit_json(data: list) -> list[OcrRegel]:
    return [OcrRegel([OcrTeken(ch, tuple(k), bool(ws)) for ch, k, ws in tekens],
                     tuple(kader), float(z), eng) for z, eng, kader, tekens in data]


def _roep_engine(engine, img: Image.Image, **opties):
    """Roept engine.lees_beeld aan met de opties die die engine kent (een testengine mag er minder kennen;
    een engine die deelgebieden niet kent leest dan het hele beeld, wat een bovenverzameling is)."""
    import inspect
    try:
        bekend = set(inspect.signature(engine.lees_beeld).parameters)
    except (TypeError, ValueError):
        bekend = set()
    return engine.lees_beeld(img, **{k: v for k, v in opties.items() if k in bekend and v is not None})


def lees_alle_engines(img: Image.Image, engines: list,
                      gebieden: list[tuple[float, float]] | None = None,
                      segmenten: list[tuple[int, int]] | None = None,
                      schaal: float | None = None) -> list[OcrRegel]:
    """
    Leest een beeld met alle engines. Een VOLLEDIGE lezing wordt bewaard onder de hash
    van de pixels + de engine-instelling + de opties (de uitkomst hangt van niets anders af),
    zodat een tweede ronde met dezelfde bronnen niet opnieuw hoeft te rekenen.
    """
    regels: list[OcrRegel] = []
    cache = _cachemap() if gebieden is None else None
    opties = {"segmenten": [list(x) for x in segmenten] if segmenten else None, "schaal": schaal}
    for e in engines:
        pad = None
        if cache is not None:
            try:
                pad = cache / f"{_cachesleutel(img, e, opties)}.json.gz"
                if pad.exists():
                    with gzip.open(pad, "rt", encoding="utf-8") as f:
                        regels += _regels_uit_json(json.load(f))
                    continue
            except Exception:
                pad = None
        gelezen = _roep_engine(e, img, gebieden=gebieden, segmenten=segmenten, schaal=schaal)
        if pad is not None:
            try:
                tmp = pad.with_suffix(f".{os.getpid()}.tmp")
                with gzip.open(tmp, "wt", encoding="utf-8") as f:
                    json.dump(_regels_naar_json(gelezen), f)
                os.replace(tmp, pad)
            except Exception:
                pass
        regels += gelezen
    return regels


# ---- Testbeelden en ijkcontrole ---------------------------------------------
def lettertype(px: int) -> ImageFont.ImageFont:
    """Schaalbaar lettertype zonder afhankelijkheid van systeemfonts (Pillow >= 10.1)."""
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        for pad in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
            if Path(pad).exists():
                return ImageFont.truetype(pad, px)
        raise RuntimeError("geen schaalbaar lettertype beschikbaar; werk Pillow bij (>= 10.1)")


def tekstbeeld(tekst: str, px: int, voorgrond: int, achtergrond: int,
               breedte: int = 1000, marge: int = 24) -> Image.Image:
    """Een grijswaardenbeeld met een regel tekst (voor tests en de ijkcontrole)."""
    f = lettertype(px)
    l, t, r, b = f.getbbox(tekst)
    im = Image.new("L", (max(breedte, r - l + 2 * marge), (b - t) + 2 * marge), achtergrond)
    ImageDraw.Draw(im).text((marge, marge - t), tekst, font=f, fill=voorgrond)
    return im


# (naam, tekstsjabloon, px, voorgrond, achtergrond, verplicht)
IJK_RIJEN = (
    ("kop 44px", "Welkom bij {A}", 44, 20, 255, True),
    ("body 16px", "U kunt uw polis beheren via het portaal van {B} en daarna verder gaan.", 16, 40, 255, True),
    ("body 12px", "U kunt uw polis beheren via het portaal van {B} en daarna verder gaan.", 12, 40, 255, False),
    ("omgekeerde kop 40px", "Ontdek {C} voor teams", 40, 245, 15, True),
    ("omgekeerde body 14px", "Alles wat u nodig heeft, van {A} in een keer.", 14, 225, 25, True),
    ("laag contrast 12px", "Gebouwd door {B} - alle rechten voorbehouden", 12, 150, 245, False),
    ("middentoon 14px", "Nieuw bij {C}: bekijk de release", 14, 250, 110, True),
    ("url 13px", "curl https://api.{c}.com/v1/charges", 13, 30, 250, False),
)
IJK_WOORDEN = ("Interpolis", "Klaverblad", "Moneybird")


def maak_ijkbeeld() -> tuple[Image.Image, list[tuple[int, int, str, bool, str]]]:
    """Een paneel met bekende merkwoorden in wisselende grootte, polariteit en
    contrast. Retourneert (beeld, [(y0, y1, naam, verplicht, woord)])."""
    a, b, c = IJK_WOORDEN
    rijen = []
    y = 0
    beelden = []
    for naam, sjabloon, px, vg, ag, verplicht in IJK_RIJEN:
        tekst = sjabloon.format(A=a, B=b, C=c, c=c.lower())
        woord = next(w for w in (a, b, c) if w in tekst or w.lower() in tekst)
        im = tekstbeeld(tekst, px, vg, ag)
        beelden.append((im, naam, verplicht, woord))
    breedte = max(im.width for im, *_ in beelden)
    hoogte = sum(im.height for im, *_ in beelden)
    paneel = Image.new("L", (breedte, hoogte), 255)
    for im, naam, verplicht, woord in beelden:
        paneel.paste(im, (0, y))
        rijen.append((y, y + im.height, naam, verplicht, woord))
        y += im.height
    return paneel, rijen


def kalibreer_engine(engine, termen: VerbodenTermen) -> dict:
    """
    IJkcontrole: leest een paneel met bekende merkwoorden. De verplichte rijen
    (grote kop, gewone tekst, omgekeerd, middentoon) moeten gevonden worden; anders
    is de engine onbetrouwbaar en wordt hij niet gebruikt. Rijen met kleine of
    lichte tekst tellen mee in de meting maar zijn niet verplicht.
    """
    paneel, rijen = maak_ijkbeeld()
    t0 = time.time()
    lekken = vind_lekken(engine.lees_beeld(paneel), termen)
    per_rij = []
    for y0, y1, naam, verplicht, woord in rijen:
        gevonden = any(y0 - 4 <= (l.kader[1] + l.kader[3]) / 2 <= y1 + 4
                       and vouw(l.term) == vouw(woord) for l in lekken)
        per_rij.append({"rij": naam, "verplicht": verplicht, "gevonden": bool(gevonden)})
    gemist_verplicht = [r["rij"] for r in per_rij if r["verplicht"] and not r["gevonden"]]
    return {
        "engine": engine.naam,
        "gevonden": sum(r["gevonden"] for r in per_rij),
        "van": len(per_rij),
        "gemist": [r["rij"] for r in per_rij if not r["gevonden"]],
        "verplicht_gevonden": not gemist_verplicht,
        "gemist_verplicht": gemist_verplicht,
        "rijen": per_rij,
        "tijd_s": round(time.time() - t0, 1),
    }


def kalibreer_engines(engines: list, termen: VerbodenTermen) -> tuple[list, list[dict], list[str]]:
    """Behoudt alleen engines die de ijkcontrole halen. Zonder enige: OcrOnbetrouwbaar."""
    goed, uitslagen, meldingen = [], [], []
    for e in engines:
        try:
            k = kalibreer_engine(e, termen)
        except Exception as ex:
            k = {"engine": e.naam, "gevonden": 0, "van": len(IJK_RIJEN), "gemist": ["alles"],
                 "verplicht_gevonden": False, "gemist_verplicht": ["fout: %s" % ex], "rijen": []}
        uitslagen.append(k)
        if k["verplicht_gevonden"]:
            goed.append(e)
        else:
            meldingen.append(f"OCR-engine {e.naam} haalde de ijkcontrole niet (miste "
                             f"{', '.join(k['gemist_verplicht'])}) en wordt niet gebruikt")
    if not goed:
        raise OcrOnbetrouwbaar("; ".join(meldingen) or "geen engine haalde de ijkcontrole")
    return goed, uitslagen, meldingen


# ---- Automatisch maskeren --------------------------------------------------
def _ring_mediaan(img: Image.Image, kader: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = kader
    a = np.asarray(img)
    delen = []
    for (ax0, ay0, ax1, ay1) in ((x0, max(0, y0 - 4), x1, y0), (x0, y1, x1, min(img.height, y1 + 4)),
                                 (max(0, x0 - 4), y0, x0, y1), (x1, y0, min(img.width, x1 + 4), y1)):
        if ax1 > ax0 and ay1 > ay0:
            delen.append(a[ay0:ay1, ax0:ax1].reshape(-1))
    if not delen:
        return 128
    return int(np.median(np.concatenate(delen)))


def maskeer_lekken(img: Image.Image, lekken: list[Lek], sterkte: int = 1) -> int:
    """
    Maskeert de gevonden woordkaders in het (grijswaarden)beeld, met ruime marge.
    Sterkte 1: verpixelen (blokgrootte volgt de letterhoogte); sterkte 2 of meer:
    egaal invullen met de omringende grijswaarde. Retourneert het aantal kaders.
    """
    n = 0
    for lek in lekken:
        x0, y0, x1, y1 = lek.kader
        h = max(6.0, y1 - y0)
        px, py = max(5.0, 0.4 * h) * sterkte, max(4.0, 0.3 * h) * sterkte
        kader = (int(x0 - px), int(y0 - py), int(x1 + px), int(y1 + py))
        kader = (max(0, kader[0]), max(0, kader[1]), min(img.width, kader[2]), min(img.height, kader[3]))
        if kader[2] - kader[0] < 2 or kader[3] - kader[1] < 2:
            continue
        if sterkte <= 1:
            _pixeleer(img, kader, blok=max(6, int(h * 0.6)))
        else:
            ImageDraw.Draw(img).rectangle([kader[0], kader[1], kader[2] - 1, kader[3] - 1],
                                          fill=_ring_mediaan(img, kader))
        n += 1
    return n


MAX_DOORGANGEN = 3
MIN_WOORDEN_PER_BEELD = 8
MASKER_VERSCHIL = 1.5      # gemiddeld aantal gemaskeerde kaders per beeld waarmee twee klassen mogen verschillen
_KLASSE_NAAM = {"comp": "comps", "ours": "eigen schermen", "decoy": "decoys", "anker": "anker"}


def maskerprofiel(per_soort: dict[str, list[int]]) -> tuple[dict[str, dict], str | None]:
    """
    Een gemaskeerde plek is zelf een signaal: hebben de comps gemiddeld veel gemaskeerde kaders en onze
    schermen geen, dan kan een beoordelaar 'gemaskeerd' leren als 'externe bron'. Vat samen hoeveel kaders
    per beeld per klasse zijn gemaskeerd en geeft een waarschuwing bij een groot verschil. (Het rapport
    toetst achteraf of de scores met het aantal maskers samenhangen.)
    """
    stats: dict[str, dict] = {}
    for soort, lijst in per_soort.items():
        if lijst:
            stats[soort] = {"beelden": len(lijst), "beelden_met_masker": sum(1 for n in lijst if n),
                            "gemiddeld_kaders": round(sum(lijst) / len(lijst), 2)}
    if len(stats) < 2:
        return stats, None
    gem = {sd: v["gemiddeld_kaders"] for sd, v in stats.items()}
    if max(gem.values()) - min(gem.values()) < MASKER_VERSCHIL:
        return stats, None
    tekst = ", ".join(f"{_KLASSE_NAAM.get(sd, sd)} {gem[sd]:.1f}".replace(".", ",")
                      for sd in sorted(gem, key=lambda k: -gem[k]))
    return stats, (f"gemaskeerde kaders per beeld verschillen per klasse ({tekst}): een beoordelaar kan een "
                   "gemaskeerde plek als teken van een externe bron leren. Bekijk de eindbeelden; het rapport "
                   "meldt of de scores met het aantal maskers samenhangen")


def controleer_lekken(img: Image.Image, engines: list, termen: VerbodenTermen,
                      max_doorgangen: int = MAX_DOORGANGEN,
                      segmenten: list[tuple[int, int]] | None = None,
                      schaal: float | None = None
                      ) -> tuple[Image.Image, OcrRapport]:
    """
    OCR-lekcontrole op de pixels van een (geneutraliseerd) beeld:
      1. lees het beeld met alle engines en zoek verboden woorden;
      2. bij een treffer: maskeer de gevonden woordkaders (eerst verpixelen, daarna
         egaal invullen) en lees het beeld OPNIEUW volledig;
      3. blijft er na de laatste doorgang een lek, dan staat het in
         OcrRapport.rest_lekken en moet de aanroeper de ronde weigeren.
    Het teruggegeven beeld is altijd het beeld dat de laatste controle heeft gehaald
    (of, bij rest_lekken, het beeld waarin het lek nog zit).
    """
    t0 = time.time()
    rapport = OcrRapport(engines=[e.naam for e in engines])
    werk = img.convert("L").copy()
    gebieden: list[tuple[float, float]] | None = None    # eerste doorgang: het hele beeld
    for doorgang in range(1, max_doorgangen + 1):
        # Na het maskeren hoeven alleen de banden over de gemaskeerde plekken opnieuw
        # gelezen te worden: OCR van een band hangt van niets anders af dan de pixels van
        # die band, en de rest van het beeld is in doorgang 1 volledig gelezen.
        regels = lees_alle_engines(werk, engines, gebieden, segmenten, schaal)
        rapport.doorgangen = doorgang
        if doorgang == 1:
            rapport.regels_gelezen = len(_dedup_regels(regels))
            rapport.woorden_gelezen = tel_woorden(regels)
            if rapport.woorden_gelezen < MIN_WOORDEN_PER_BEELD:
                rapport.dekking = "laag"
        lekken = voeg_lekken_samen(vind_lekken(regels, termen))
        if not lekken:
            rapport.rest_lekken = []
            break
        if doorgang == max_doorgangen:
            rapport.rest_lekken = [{"woord": l.term, "gelezen": l.gelezen, "engine": l.engine,
                                    "kader": [round(v) for v in l.kader]} for l in lekken]
            break
        rapport.kaders_gemaskeerd += maskeer_lekken(werk, lekken, sterkte=doorgang)
        rapport.gemaskeerde_termen += [l.term for l in lekken]
        marge = max(RapidOcrEngine.OVERLAP, TesseractEngine.OVERLAP) + 40
        gebieden = [(l.kader[1] - marge, l.kader[3] + marge) for l in lekken]
    rapport.tijd_s = round(time.time() - t0, 1)
    return werk, rapport


# ---------------------------------------------------------------------------
# Ronde bouwen
# ---------------------------------------------------------------------------
def lees_extra_maskers(pad: str | None) -> dict[str, list[list[float]]]:
    """
    Handmatige extra maskers, per bronbestandsnaam, in RELATIEVE coordinaten van
    het eindbeeld:
        {"linear_docs_1440.png": [[0.10, 0.18, 0.42, 0.26]]}
    Nog nodig voor logo's ZONDER tekst (een pictogram midden in beeld): die kan
    geen OCR lezen. Merknamen in tekst worden automatisch gemaskeerd.
    """
    if not pad:
        return {}
    p = Path(pad) if Path(pad).is_absolute() else PROJECT / pad
    if not p.exists():
        print(f"LET OP: maskerbestand {p} bestaat niet; genegeerd.")
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def controleer_eigen_schermen(bronnen: list[Bron], viewports: Iterable[str] | None
                              ) -> list[str]:
    """Per te bouwen viewport minstens een eigen scherm; anders meet de ronde niets."""
    per_vp: dict[str, list[Bron]] = {}
    for b in bronnen:
        per_vp.setdefault(b.viewport, []).append(b)
    problemen: list[str] = []
    for vp in sorted(per_vp):
        if viewports and vp not in viewports:
            continue
        if not any(b.soort == "ours" for b in per_vp[vp]):
            problemen.append(f"viewport {vp}: {len(per_vp[vp])} beelden maar GEEN ENKEL eigen scherm")
    return problemen


def _sectiespec_voor(args, vp: str, breedte_vp: int, aantal: int | None = None) -> SectieSpec:
    if aantal is None:
        aantal = getattr(args, "secties", None)
        aantal = STANDAARD_SECTIES if aantal in (None, "auto") else max(1, int(aantal))
    spec = standaard_sectiespec(vp, breedte_vp, aantal)
    hoogte = getattr(args, "sectie_hoogte_mobile" if vp == "mobile" else "sectie_hoogte", None)
    ratio = getattr(args, "max_hoogte_ratio_expliciet", None)
    if hoogte:
        spec.hoogte = int(hoogte)
    elif ratio:                                     # verouderde vlag: totaal = ratio x breedte
        spec.hoogte = max(64, round(breedte_vp * ratio / aantal))
    scheiding = getattr(args, "scheiding", None)
    if scheiding is not None:
        spec.scheiding = int(scheiding)
    return spec


def inhoudshoogte_px(pad: Path, breedte: int, snij_boven: int | None = None) -> int:
    """Hoogte van een bronbeeld na het wegsnijden van browser-chrome en bannerrest en het schalen naar
    `breedte`: de lengte van de pagina die neutraliseer() in secties verdeelt."""
    with Image.open(pad) as im:
        img = im.convert("RGB")
    n = max(0, snij_boven) if snij_boven is not None else detecteer_browser_chrome(img)[0]
    if n:
        img = img.crop((0, n, img.width, img.height))
    n2 = detecteer_bodembanner(img)[0]
    return max(1, round((img.height - n2) * breedte / img.width))


def vullingsprofiel(per_vp: dict[str, dict[str, list[float]]]) -> tuple[dict[str, dict], list[str]]:
    """
    Lege ruimte (de opvulling van een pagina die korter is dan de secties) is zelf een signaal: is ze bij onze
    schermen of de decoys anders dan bij de comps, dan zien beoordelaars aan de witruimte onderaan wat wat is.
    `per_vp` is viewport -> klasse -> aandeel lege ruimte per beeld (0..1). Retourneert (statistiek, fouten); een
    verschil van VULLING_VERSCHIL of meer tussen twee klassen is een fout (het harnas weigert dan, exitcode 5).
    """
    stats: dict[str, dict] = {}
    fouten: list[str] = []
    for vp, per_soort in per_vp.items():
        st = {soort: {"beelden": len(lijst), "gem_leeg_aandeel": round(sum(lijst) / len(lijst), 3),
                      "beelden_met_lege_ruimte": sum(1 for x in lijst if x > 0.02)}
              for soort, lijst in per_soort.items() if lijst}
        stats[vp] = st
        if len(st) < 2:
            continue
        gem = {k: v["gem_leeg_aandeel"] for k, v in st.items()}
        hoog, laag = max(gem, key=lambda k: gem[k]), min(gem, key=lambda k: gem[k])
        if gem[hoog] - gem[laag] >= VULLING_VERSCHIL:
            fouten.append(
                f"{vp}: de lege ruimte onderaan verraadt de klasse - gemiddeld {gem[hoog]:.0%} van het beeld is leeg "
                f"bij {_KLASSE_NAAM.get(hoog, hoog)} tegen {gem[laag]:.0%} bij {_KLASSE_NAAM.get(laag, laag)}, "
                "omdat kortere pagina's meer lege ruimte overhouden. Gebruik --secties auto (standaard) of een "
                "kleiner aantal secties, kies een kleinere --sectie-hoogte, of sluit de kortste bronnen uit")
    return stats, fouten


def bepaal_secties(lijsten: dict[str, list[Bron]], breedte_van: dict[str, int], args
                   ) -> tuple[dict[str, int], dict[str, dict], dict[str, dict], list[str]]:
    """
    Het aantal secties per viewport, met onderbouwing. Een vast getal (--secties N) geldt overal. Met 'auto'
    (standaard) wordt het het grootste aantal (hoogstens STANDAARD_SECTIES) dat ELK beeld van de viewport helemaal
    vult: lege opvulling verraadt welke pagina's kort zijn, en dat zijn vaak juist de eigen schermen en de decoys.
    Bij een mix van app-schermen van een schermhoogte en lange pagina's is dat een sectie: iedereen laat dan het
    bovenste scherm zien. Retourneert (aantal per viewport, info per viewport, vulling-statistiek, vulling-fouten);
    de laatste toetsen de klassegebonden lege ruimte VOORDAT er OCR-rekenwerk is gedaan.
    """
    keuze = getattr(args, "secties", "auto")
    legacy = bool(getattr(args, "max_hoogte_ratio_expliciet", None))
    aantallen: dict[str, int] = {}
    info: dict[str, dict] = {}
    voorspeld: dict[str, dict[str, list[float]]] = {}
    for vp, lijst in lijsten.items():
        breedte = breedte_van[vp]
        sh = _sectiespec_voor(args, vp, breedte, aantal=STANDAARD_SECTIES if legacy else 1).hoogte
        bekend: list[tuple[int, Bron]] = []
        for b in lijst:
            try:
                bekend.append((inhoudshoogte_px(b.pad, breedte, getattr(args, "snij_boven", None)), b))
            except Exception:
                continue                                  # onleesbaar: de bouwstap meldt dat zelf
        vol = [max(0, int(h / sh + AUTO_TOLERANTIE)) for h, _b in bekend]
        if legacy or keuze not in ("auto", None):
            n, modus = (STANDAARD_SECTIES if legacy else max(1, int(keuze))), "vast"
        else:
            n, modus = max(1, min(STANDAARD_SECTIES, min(vol) if vol else STANDAARD_SECTIES)), "auto"
        aantallen[vp] = n
        rec: dict[str, Any] = {"modus": modus, "gekozen": n, "sectiehoogte_px": sh, "beelden": len(lijst)}
        if bekend:
            lengtes = sorted(h / sh for h, _b in bekend)
            kortste = min(bekend, key=lambda t: t[0])[1]
            rec.update({"kortste_pagina_secties": round(lengtes[0], 2),
                        "mediane_pagina_secties": round(lengtes[len(lengtes) // 2], 2),
                        "langste_pagina_secties": round(lengtes[-1], 2),
                        "kortste_bron": f"{kortste.bron_naam} ({_KLASSE_NAAM.get(kortste.soort, kortste.soort)})"})
            if modus == "auto" and n < STANDAARD_SECTIES:
                rec["waarschuwing"] = (
                    f"--secties auto koos {n} van de maximaal {STANDAARD_SECTIES} secties: de kortste pagina "
                    f"({rec['kortste_bron']}) is maar {lengtes[0]:.2f} sectiehoogtes lang, en opvulling met lege "
                    "ruimte zou verraden welke beelden kort zijn. Elk beeld toont daardoor "
                    + ("alleen het bovenste scherm" if n == 1 else f"{n} uitsneden")
                    + "; langere pagina's worden afgekapt. Meer secties kan alleen als alle bronnen in deze "
                      "viewport langer zijn (sluit korte bronnen uit of neem ze full-page op)")
            capaciteit = n * sh
            voorspeld[vp] = {}
            for h, b in bekend:
                voorspeld[vp].setdefault(b.soort, []).append(max(0.0, capaciteit - h) / capaciteit)
        info[vp] = rec
    stats, fouten = vullingsprofiel(voorspeld)
    return aantallen, info, stats, fouten


def bouw_ronde(bronnen: list[Bron], args, ronde_id: str,
               context: RondeContext | None = None) -> dict[str, Any]:
    """
    Bouwt een ronde in een tijdelijke map en zet haar pas op zijn plaats als ALLE
    controles zijn geslaagd (OCR-lek, hoogte-eigenschap, bestandsnamen, geen
    uitgevallen bron). Bij een weigering staat in het resultaat
    `geweigerd = {"code": <exitcode>, "redenen": [...]}` en blijft er niets achter.
    """
    ctx = context or RondeContext()
    extra_maskers = lees_extra_maskers(getattr(args, "extra_maskers", None))
    uit_map = Path(args.uit)
    ronde_map = uit_map / ronde_id
    uit_map.mkdir(parents=True, exist_ok=True)
    staging = uit_map / f".bouw_{ronde_id}_{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    engines = ctx.engines if ctx.engines is not None else getattr(args, "ocr_engines", None)
    if engines is None:
        engines, _m = beschikbare_ocr_engines("auto")       # geen omweg zonder OCR
    termen = ctx.termen or bouw_verboden_termen()

    rng = random.Random(args.seed)
    per_viewport: dict[str, list[Bron]] = {}
    for b in bronnen:
        per_viewport.setdefault(b.viewport, []).append(b)

    maakt_ronde_zonder_ons = False
    sleutel_rondes: dict[str, Any] = {
        "seed": args.seed,
        "aangemaakt_op": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "script_versie": SCRIPT_VERSIE,
        "breedte_px": {"desktop": args.breedte, "mobile": args.breedte_mobile},
        "max_hoogte_ratio": getattr(args, "max_hoogte_ratio_expliciet", None),
        "contrast": args.contrast,
        "chroma_winst": args.chroma_winst,
        "viewports": {},
    }
    problemen: list[str] = []
    lek_meldingen: list[str] = []
    lek_beelden: set[str] = set()
    eigenschap_fouten: list[str] = []
    geen_ons_fouten: list[str] = []
    totaal = 0
    decoy_labels: dict[str, list[str]] = {}
    afmetingen: dict[str, list[tuple[int, int]]] = {}
    ocr_totalen = {"beelden": 0, "woorden": 0, "kaders": 0, "beelden_met_automask": 0,
                   "laag_dekking": [], "tijd_s": 0.0, "maskers_per_soort": {}}
    aantallen = {"comp": 0, "ours": 0, "decoy": 0, "anker": 0}
    uitval = False

    try:
        # fase A: welke bronnen per viewport, in willekeurige volgorde (hier wordt de seed gebruikt)
        lijsten: dict[str, list[Bron]] = {}
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
            lijsten[vp] = lijst

        # fase B: het aantal secties per viewport, en de toets dat lege ruimte de klasse niet verraadt
        # (voordat er rekenwerk is gedaan: een ronde die toch wordt geweigerd kost dan geen OCR-uren)
        breedte_van = {vp: (args.breedte_mobile if vp == "mobile" else args.breedte) for vp in lijsten}
        secties_per_vp, secties_info, vulling_stats, vulling_fouten = bepaal_secties(lijsten, breedte_van, args)
        sleutel_rondes["secties_keuze"] = secties_info
        sleutel_rondes["vulling_per_klasse"] = vulling_stats
        for vp, rec in secties_info.items():
            if rec.get("waarschuwing"):
                ctx.waarschuwingen.append(f"{vp}: {rec['waarschuwing']}")
        eigenschap_fouten += vulling_fouten
        if vulling_fouten:
            lijsten = {}                             # niet bouwen; de ronde wordt hieronder geweigerd

        # fase C: bouwen
        for vp, lijst in lijsten.items():
            # Binnen een viewportgroep is de breedte identiek; tussen groepen wordt
            # niet vergeleken, dus mobiel hoeft niet naar desktopbreedte opgeblazen.
            breedte_vp = breedte_van[vp]
            spec = _sectiespec_voor(args, vp, breedte_vp, secties_per_vp[vp])
            vp_map = staging / vp
            vp_map.mkdir(parents=True, exist_ok=True)

            items = []
            geschreven: list[Path] = []
            for label, bron in zip(labels(len(lijst)), lijst):
                try:
                    img, log = neutraliseer(
                        bron.pad, bron.viewport, breedte_vp, args.max_hoogte_ratio,
                        args.contrast, args.snij_boven, args.maskeer_footer,
                        args.chroma_winst, args.merkbalk_hoogte,
                        extra_maskers.get(bron.pad.name), secties=spec)
                except Exception as e:
                    problemen.append(f"{bron.pad}: neutralisatie mislukt: {e}")
                    uitval = True
                    continue
                # --- de OCR-lekcontrole op de definitieve pixels ---
                secs = log.secties or {}
                stroken = ([(i * (secs["sectiehoogte_px"] + secs["scheiding_px"]),
                             i * (secs["sectiehoogte_px"] + secs["scheiding_px"]) + secs["sectiehoogte_px"])
                            for i in range(secs["aantal"])] if secs else None)
                img, ocr = controleer_lekken(img, engines, termen, segmenten=stroken,
                                             schaal=ocr_schaal(vp, breedte_vp))
                ocr_totalen["beelden"] += 1
                ocr_totalen["woorden"] += ocr.woorden_gelezen
                ocr_totalen["kaders"] += ocr.kaders_gemaskeerd
                ocr_totalen["maskers_per_soort"].setdefault(bron.soort, []).append(ocr.kaders_gemaskeerd)
                ocr_totalen["tijd_s"] += ocr.tijd_s
                if ocr.kaders_gemaskeerd:
                    ocr_totalen["beelden_met_automask"] += 1
                if ocr.dekking == "laag":
                    ocr_totalen["laag_dekking"].append(f"{vp}/{label}")
                if not getattr(args, "stil", False):
                    print(f"  OCR {vp} {label}: {ocr.woorden_gelezen} woorden, "
                          f"{ocr.kaders_gemaskeerd} kader(s) gemaskeerd, {ocr.tijd_s}s", flush=True)
                if ocr.rest_lekken:
                    lek_beelden.add(f"{vp}/{label}")
                    for rl in ocr.rest_lekken:
                        lek_meldingen.append(
                            f"beeld {label} ({vp}, bron {_rel(bron.pad)}): verboden woord "
                            f"{rl['woord']!r} (gelezen als {rl['gelezen']!r}, {rl['engine']}) "
                            f"blijft leesbaar na automatisch maskeren")
                doel = vp_map / f"{label}.png"
                schrijf_kaal_png(img, doel)
                afmetingen.setdefault(vp, []).append((img.width, img.height))
                img.close()
                geschreven.append(doel)
                lek = controleer_naam(doel.name)
                if lek:
                    eigenschap_fouten.append(f"bestandsnaam {doel.name} verraadt: {lek}")
                items.append({
                    "label": label,
                    "bestand": doel.name,
                    "soort": bron.soort,
                    "is_decoy": bron.soort == "decoy",
                    "is_ons": bron.soort == "ours",
                    "is_anker": bron.soort == "anker",
                    "klasse": bron.klasse,
                    "domein": bron.domein,
                    "taal": bron.taal,
                    "kwaliteit": bron.kwaliteit,
                    "soort_scherm": bron.soort_scherm,
                    "manifest_vorm": bron.manifest_vorm or "geen manifest",
                    "bron_set": bron.set_naam,
                    "bron_naam": bron.bron_naam,
                    "bron_bestand": _rel(bron.pad),
                    "omschrijving": bron.omschrijving,
                    "neutralisatie": asdict(log),
                    "ocr": {"woorden_gelezen": ocr.woorden_gelezen,
                            "regels_gelezen": ocr.regels_gelezen,
                            "kaders_gemaskeerd": ocr.kaders_gemaskeerd,
                            "gemaskeerde_woorden": ocr.gemaskeerde_termen,
                            "doorgangen": ocr.doorgangen,
                            "dekking": ocr.dekking,
                            "tijd_s": ocr.tijd_s},
                })
                aantallen[bron.soort] = aantallen.get(bron.soort, 0) + 1
                if bron.soort == "decoy":
                    decoy_labels.setdefault(vp, []).append(label)
                totaal += 1

            if not any(i["is_ons"] for i in items) and not ctx.zonder_eigen_schermen:
                geen_ons_fouten.append(f"viewport {vp}: geen eigen scherm in de ronde")
            if not any(i["is_ons"] for i in items):
                maakt_ronde_zonder_ons = True

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
                "hoogte_px": items and items[0]["neutralisatie"]["eind_formaat"][1] or 0,
                "secties": asdict(spec),
                "gelijke_bestandsgrootte_bytes": gelijke_grootte,
                "items": items,
            }

        # --- eigenschappen van de ronde als geheel ---
        eigenschap_fouten += controleer_hoogte_eigenschap(afmetingen)
        sleutel_rondes["hoogte_eigenschap"] = {
            vp: {"unieke_hoogtes": len({h for _w, h in lst}),
                 "unieke_breedtes": len({w for w, _h in lst}),
                 "hoogte_px": sorted({h for _w, h in lst})[0] if lst else 0,
                 "breedte_px": sorted({w for w, _h in lst})[0] if lst else 0}
            for vp, lst in afmetingen.items()}

        aantal_ons = aantallen["ours"]
        redenen_onbruikbaar = []
        if maakt_ronde_zonder_ons or aantal_ons == 0:
            redenen_onbruikbaar.append("de ronde bevat geen enkel eigen scherm (bewuste testronde)")
        sleutel_rondes["meetlat"] = {
            "status": ("BRUIKBAAR" if not redenen_onbruikbaar
                       else "NIET-BRUIKBAAR-VOOR-OORDEEL"),
            "bruikbaar_voor_oordeel": not redenen_onbruikbaar,
            "redenen_niet_bruikbaar": redenen_onbruikbaar,
            "zonder_eigen_schermen_vlag": bool(ctx.zonder_eigen_schermen),
            "domein_filter": ctx.domein_filter,
            "soort_scherm_filter": list(ctx.soort_scherm_filter),
            "inclusief_marketing": bool(ctx.inclusief_marketing),
            "heeft_anker": aantallen["anker"] > 0,
            "aantal_eigen": aantal_ons,
            "aantal_decoys": aantallen["decoy"],
            "aantal_ankers": aantallen["anker"],
            "aantal_comps": aantallen["comp"],
        }
        masker_stats, masker_waarschuwing = maskerprofiel(ocr_totalen["maskers_per_soort"])
        if masker_waarschuwing:
            ctx.waarschuwingen.append(masker_waarschuwing)
        sleutel_rondes["ocr"] = {
            "engines": [e.beschrijving() for e in engines],
            "verboden_termen": {"aantal": len(termen)},
            "ijkcontrole": ctx.kalibratie,
            "beelden_gecontroleerd": ocr_totalen["beelden"],
            "woorden_gelezen": ocr_totalen["woorden"],
            "kaders_gemaskeerd": ocr_totalen["kaders"],
            "beelden_met_automask": ocr_totalen["beelden_met_automask"],
            "beelden_met_lek_na_automask": len(lek_beelden),
            "beelden_met_lage_dekking": ocr_totalen["laag_dekking"],
            "maskers_per_klasse": masker_stats,
            "dekking": (f"OCR-dekking: gecontroleerd op {ocr_totalen['woorden']} woorden in "
                        f"{ocr_totalen['beelden']} beelden, {ocr_totalen['kaders']} kaders "
                        f"gemaskeerd ({ocr_totalen['beelden_met_automask']} beelden)"),
            "kwalificatie": (
                "OCR is niet volledig. Dat na maskeren geen verboden woord meer wordt gelezen "
                "bewijst niet dat er geen merk in beeld staat: woorden in laag contrast, "
                "sierschrift of illustraties kunnen gemist zijn en logo's zonder tekst leest "
                "OCR niet. Bekijk de eindbeelden daarom op grafische logo's."),
            "tijd_s": round(ocr_totalen["tijd_s"], 1),
        }
        vormen: dict[str, int] = {}
        for b in bronnen:
            vormen[b.manifest_vorm or "geen manifest"] = vormen.get(b.manifest_vorm or "geen manifest", 0) + 1
        sleutel_rondes["manifestvormen"] = dict(sorted(vormen.items()))
        sleutel_rondes["waarschuwingen"] = list(ctx.waarschuwingen)
        sleutel_rondes["uitgesloten"] = list(ctx.uitgesloten)
        sleutel_rondes["classificatie_ontbreekt"] = list(ctx.classificatie_ontbreekt)

        # --- weigeren? ---
        geweigerd = None
        if geen_ons_fouten:
            geweigerd = {"code": EXIT_INVOER, "redenen": geen_ons_fouten}
        elif lek_meldingen:
            geweigerd = {"code": EXIT_LEK, "redenen": lek_meldingen}
        elif eigenschap_fouten:
            geweigerd = {"code": EXIT_EIGENSCHAP, "redenen": eigenschap_fouten}
        elif uitval:
            geweigerd = {"code": EXIT_FOUT, "redenen": problemen}

        if geweigerd is None:
            schrijf_instructie(staging, sleutel_rondes)
            if ronde_map.exists():
                shutil.rmtree(ronde_map)
            staging.rename(ronde_map)
            staging = None  # type: ignore[assignment]
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    return {"sleutel": sleutel_rondes, "problemen": problemen,
            "totaal": totaal, "decoy_labels": decoy_labels,
            "ronde_map": str(ronde_map), "geweigerd": geweigerd,
            "lekken": lek_meldingen}


def schrijf_beoordelingsformulier(vp_map: Path, lbls: list[str]) -> None:
    regels = ["label,hierarchie_1_5,typografie_1_5,ritme_witruimte_1_5,"
              "consistentie_1_5,totaalindruk_1_5,opmerking"]
    regels += [f"{l},,,,,," for l in lbls]
    (vp_map / "beoordeling.csv").write_text("\n".join(regels) + "\n", encoding="utf-8")


def schrijf_instructie(ronde_map: Path, sleutel: dict) -> None:
    def _uitsneden(v: dict) -> str:
        n = (v.get("secties") or {}).get("aantal")
        return f", {n} uitsnede{'n' if n != 1 else ''}" if n else ""

    vps = ", ".join(f"{k} ({v['breedte_px']} px breed{_uitsneden(v)})"
                    for k, v in sleutel["viewports"].items()) or "-"
    meetlat = sleutel.get("meetlat") or {}
    status = ""
    if meetlat.get("bruikbaar_voor_oordeel") is False:
        # Alleen dat de scores niet meetellen; NIETS over de reden of de inhoud.
        status = ("\nStatus: NIET-BRUIKBAAR-VOOR-OORDEEL. Dit is een technische testronde; "
                  "de scores worden niet gebruikt.\n")
    tekst = f"""# Blinde beoordeling
{status}
Alle schermen zijn geneutraliseerd: merkkleur is verwijderd (grijswaarden met
behoud van contrast en structuur), logo-regio's en herkenbare namen zijn
onherkenbaar gemaakt, browser-chrome en bannerresten zijn weggesneden en elk
beeld binnen een map heeft exact dezelfde afmetingen. Resolutie, kleur, merk en
paginalengte zijn dus geen signaal. Beoordeel uitsluitend: informatiehierarchie,
typografie, ritme en witruimte, consistentie, en totaalindruk.

Elk beeld toont een of meer uitsneden van een pagina onder elkaar (bij meer dan een:
boven, midden en onder), gescheiden door een grijze balk; het aantal staat per map
hieronder. Is een pagina korter, dan is de rest van het beeld leeg gelaten; dat is
geen fout en zegt niets over kwaliteit.

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
# Zelftest van de neutralisatie en de meetlat-eigenschappen
# ---------------------------------------------------------------------------
def zelftest() -> int:
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
    buf = io.BytesIO()
    Image.new("L", (8, 8), 128).save(buf, format="PNG")
    ruw = buf.getvalue()
    iend = ruw.rfind(b"\x00\x00\x00\x00IEND")
    gevuld = ruw[:iend] + _png_vulchunk(100) + ruw[iend:]
    try:
        Image.open(io.BytesIO(gevuld)).load()
    except Exception as e:
        fouten.append(f"gevulde PNG onleesbaar: {e}")

    # --- nieuw in v2: hoogte, filters, exitcodes, OCR ---
    fouten += _zelftest_hoogte()
    fouten += _zelftest_filters()
    fouten += _zelftest_exitcodes()
    fouten += _zelftest_ocr()

    for f in fouten:
        print("ZELFTEST FOUT:", f)
    print("ZELFTEST:", "ok" if not fouten else f"{len(fouten)} fout(en)")
    return 0 if not fouten else 1


def _zelftest_hoogte() -> list[str]:
    """Elk beeld van een viewport heeft dezelfde afmetingen, ook bij zeer
    verschillende paginalengtes; en de mobiele ronde toont meer dan de bovenkant."""
    fouten: list[str] = []
    # lege ruimte die de klasse verraadt wordt geweigerd; gelijke lege ruimte niet
    if not vullingsprofiel({"desktop": {"comp": [0.0, 0.05], "ours": [0.6]}})[1]:
        fouten.append("lege ruimte die de klasse verraadt wordt niet geweigerd")
    if vullingsprofiel({"desktop": {"comp": [0.5, 0.6], "ours": [0.55]}})[1]:
        fouten.append("gelijke lege ruimte bij alle klassen wordt ten onrechte geweigerd")
    spec = SectieSpec(aantal=3, hoogte=200, scheiding=20)
    with tempfile.TemporaryDirectory() as td:
        maten = []
        for i, h in enumerate((150, 380, 600, 1300, 4000)):
            p = Path(td) / f"p{i}.png"
            Image.new("RGB", (300, h), (240, 240, 240)).save(p)
            img, log = neutraliseer(p, "desktop", 300, 3.0, "uit", None, False, 0.5, secties=spec)
            maten.append(img.size)
        uniek = sorted(set(maten))
        print(f"  hoogte: 5 pagina's van 150 tot 4000 px -> afmetingen {uniek}")
        if len(uniek) != 1 or uniek[0] != (300, spec.totale_hoogte):
            fouten.append(f"hoogte is een vingerafdruk: {uniek}")
        # drie herkenbare banden boven, midden, onder van een lange pagina
        lang = Image.new("RGB", (300, 3000), (250, 250, 250))
        dr = ImageDraw.Draw(lang)
        dr.rectangle([0, 10, 300, 90], fill=(0, 0, 0))            # bovenaan
        dr.rectangle([0, 1450, 300, 1550], fill=(0, 0, 0))        # midden
        dr.rectangle([0, 2900, 300, 2990], fill=(0, 0, 0))        # onderaan
        p = Path(td) / "lang.png"
        lang.save(p)
        img, _ = neutraliseer(p, "desktop", 300, 3.0, "uit", None, False, 0.5, secties=spec)
        a = np.asarray(img)
        donker = [bool((a[i * 220:i * 220 + 200] < 60).any()) for i in range(3)]
        print(f"  secties: donkere band zichtbaar in boven/midden/onder = {donker}")
        if not all(donker):
            fouten.append(f"niet alle drie de secties tonen hun deel van de pagina: {donker}")
    if not controleer_hoogte_eigenschap({"desktop": [(300, 100), (300, 120)]}):
        fouten.append("hoogte-eigenschap slaat niet aan op twee verschillende hoogtes")
    if controleer_hoogte_eigenschap({"desktop": [(300, 100), (300, 100)]}):
        fouten.append("hoogte-eigenschap geeft vals alarm op gelijke hoogtes")
    return fouten


def _zelftest_filters() -> list[str]:
    """Domeinfilter, marketing, geladen_ok en ontbrekende velden, op nagebootste manifesten."""
    fouten: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for m in ("comps", "comps_nl", "decoy", "ours", "anker"):
            (root / m).mkdir()
        for n in ("a_1440.png", "b_1440.png", "c_1440.png", "d_1440.png"):
            Image.new("RGB", (40, 40), (200, 200, 200)).save(root / "comps" / n)
        for n in ("nl1-desktop-1440x900.png", "nl2-desktop-1440x900.png"):
            Image.new("RGB", (40, 40), (200, 200, 200)).save(root / "comps_nl" / n)
        Image.new("RGB", (40, 40)).save(root / "decoy" / "dec-desktop-1440.png")
        Image.new("RGB", (40, 40)).save(root / "ours" / "ons-desktop-1440.png")
        Image.new("RGB", (40, 40)).save(root / "anker" / "top-desktop-1440.png")
        (root / "comps" / "manifest.json").write_text(json.dumps([
            {"id": "a", "bron_naam": "Aa", "bestand": "a_1440.png", "klasse": "product_ui",
             "domein": "internationaal", "geladen_ok": True},
            {"id": "b", "bron_naam": "Bb", "bestand": "b_1440.png", "klasse": "marketing",
             "domein": "internationaal", "geladen_ok": True},
            {"id": "c", "bron_naam": "Cc", "bestand": "c_1440.png", "klasse": "product_ui",
             "domein": "internationaal", "geladen_ok": False},
            {"id": "d", "bron_naam": "Dd", "bestand": "d_1440.png"},          # velden ontbreken
        ]), encoding="utf-8")
        (root / "comps_nl" / "manifest.json").write_text(json.dumps({"comps": [
            {"slug": "nl1", "naam": "Een NL", "klasse": "product_ui", "domein": "nl_financieel",
             "bestanden": {"desktop": {"file": "nl1-desktop-1440x900.png"}}},
            {"slug": "nl2", "naam": "Twee NL",
             "bestanden": {"desktop": {"file": "nl2-desktop-1440x900.png"}}},   # velden ontbreken
        ]}), encoding="utf-8")
        (root / "decoy" / "manifest.json").write_text(json.dumps({
            "set": "decoy", "bestanden": [
                {"viewport": "desktop", "bestand": "dec-desktop-1440.png",
                 "klasse": "decoy", "kwaliteit": "zwak"}]}), encoding="utf-8")
        alle = (verzamel_bronnen([root / "comps", root / "comps_nl"], "comp")
                + verzamel_bronnen([root / "ours"], "ours")
                + verzamel_bronnen([root / "decoy"], "decoy")
                + verzamel_bronnen([root / "anker"], "anker"))
        nl, uitgesl = filter_bronnen(alle, "nl_financieel")
        namen = sorted(b.bron_naam for b in nl)
        print(f"  filter nl_financieel behoudt {namen}")
        # verwacht: alle nl-comps (nl1 + nl2 via mapstandaard), decoy, ours, anker; geen internationale
        verwacht = sorted(["Een NL", "Twee NL", "dec-desktop-1440", "ons-desktop-1440", "top-desktop-1440"])
        if namen != verwacht:
            fouten.append(f"domeinfilter nl_financieel behoudt {namen}, verwacht {verwacht}")
        intl, _ = filter_bronnen(alle, "internationaal")
        n_intl = sorted(b.bron_naam for b in intl if b.soort == "comp")
        if n_intl != ["Aa", "Dd"]:
            fouten.append(f"domeinfilter internationaal behoudt comps {n_intl}, verwacht ['Aa', 'Dd']")
        for naam_, lijst_ in (("nl_financieel", uitgesl), ("internationaal", filter_bronnen(alle, "internationaal")[1])):
            if not any(u["bron_naam"] == "Cc" and "geladen_ok=false" in u["reden"] for u in lijst_):
                fouten.append(f"een beeld met geladen_ok=false is niet uitgesloten (filter {naam_})")
        _, uitg_intl = filter_bronnen(alle, "internationaal")
        if not any("marketing" in u["reden"] for u in uitg_intl):
            fouten.append("klasse marketing is niet uitgesloten")
        met_marketing, _ = filter_bronnen(alle, "internationaal", inclusief_marketing=True)
        if "Bb" not in [b.bron_naam for b in met_marketing]:
            fouten.append("--inclusief-marketing neemt marketing niet mee")
        dec = next(b for b in alle if b.soort == "decoy")
        if dec.kwaliteit != "zwak":
            fouten.append(f"decoykwaliteit niet gelezen: {dec.kwaliteit!r}")
        d_ = next(b for b in alle if b.bron_naam == "Dd")
        if "klasse" not in d_.ontbrekend or d_.klasse != "product_ui":
            fouten.append("ontbrekende klasse is niet als product_ui met waarschuwing behandeld")
    return fouten


class _LegeEngine:
    """Test-engine die niets leest (voor exitcode-proeven zonder rekentijd)."""
    naam = "leeg"

    def lees_beeld(self, img, gebieden=None):
        return []

    def beschrijving(self):
        return {"naam": self.naam, "versie": "test"}


class _AltijdLekEngine:
    """Test-engine die ALTIJD een verboden woord 'ziet', ook na maskeren: simuleert
    een lek dat automatisch maskeren niet verhelpt."""
    naam = "altijd-lek"

    def lees_beeld(self, img, gebieden=None):
        r = _regel_uit_woorden([("Interpolis", (20.0, 20.0, 200.0, 50.0))], 0.99, self.naam)
        return [r]

    def beschrijving(self):
        return {"naam": self.naam, "versie": "test"}


def _zelftest_exitcodes() -> list[str]:
    """Exitcode 2 zonder eigen schermen, 3 bij een blijvend lek; testronde gemarkeerd."""
    fouten: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for m in ("comps", "ours", "decoy"):
            (root / m).mkdir()
        for m, n in (("comps", "x-desktop-1440.png"), ("comps", "y-desktop-1440.png"),
                     ("decoy", "d-desktop-1440.png"), ("ours", "o-desktop-1440.png")):
            Image.new("RGB", (400, 700), (225, 225, 225)).save(root / m / n)
        basis = ["--comps", str(root / "comps"), "--decoy", str(root / "decoy"),
                 "--anker", str(root / "geen_anker"), "--uit", str(root / "ab"),
                 "--viewports", "desktop", "--breedte", "300", "--seed", "1", "--ronde", "r"]
        with _stil():
            code_leeg = main(basis + ["--ours", str(root / "bestaat_niet")],
                             ocr_engines=[_LegeEngine()])
        print(f"  exitcode zonder eigen schermen: {code_leeg} (verwacht {EXIT_INVOER})")
        if code_leeg != EXIT_INVOER:
            fouten.append(f"exitcode zonder eigen schermen is {code_leeg}, verwacht {EXIT_INVOER}")
        if (root / "ab" / "r").exists():
            fouten.append("er is toch een ronde geschreven zonder eigen schermen")
        with _stil():
            code_test = main(basis + ["--ours", str(root / "bestaat_niet"),
                                      "--zonder-eigen-schermen"], ocr_engines=[_LegeEngine()])
        sleutel = json.loads((root / "ab" / "_sleutel.json").read_text(encoding="utf-8")) \
            if (root / "ab" / "_sleutel.json").exists() else {}
        meetlat = (sleutel.get("rondes", {}).get("r", {}) or {}).get("meetlat", {})
        leesmij = (root / "ab" / "r" / "LEESMIJ.md")
        tekst = leesmij.read_text(encoding="utf-8") if leesmij.exists() else ""
        print(f"  testronde zonder eigen schermen: exit {code_test}, status {meetlat.get('status')}")
        if code_test != EXIT_OK or meetlat.get("status") != "NIET-BRUIKBAAR-VOOR-OORDEEL" \
                or "NIET-BRUIKBAAR-VOOR-OORDEEL" not in tekst:
            fouten.append("testronde is niet als NIET-BRUIKBAAR-VOOR-OORDEEL gemarkeerd")
        if any(w in tekst.lower() for w in ("eigen scherm", "geen eigen", "ours", "decoy")):
            fouten.append("LEESMIJ verklapt iets over de samenstelling van de testronde")
        with _stil():
            code_lek = main(basis + ["--ours", str(root / "ours"), "--ronde", "lek"],
                            ocr_engines=[_AltijdLekEngine()])
        print(f"  exitcode bij blijvend lek: {code_lek} (verwacht {EXIT_LEK})")
        if code_lek != EXIT_LEK:
            fouten.append(f"exitcode bij blijvend lek is {code_lek}, verwacht {EXIT_LEK}")
        if (root / "ab" / "lek").exists() or any((root / "ab").glob(".bouw_*")):
            fouten.append("na een geweigerde ronde staat er nog een (halve) ronde")
    return fouten


def _zelftest_ocr() -> list[str]:
    """OCR-detectie op grote kop, kleine bodytekst, omgekeerde kleuren en een schoon beeld,
    plus automatisch maskeren; en de ijkcontrole. Zonder engine: dat is zelf een fout."""
    fouten: list[str] = []
    try:
        engines, _m = beschikbare_ocr_engines("auto")
    except OcrNietBeschikbaar as e:
        return [f"geen OCR-engine beschikbaar: {e}"]
    termen = bouw_verboden_termen()
    for e in engines:
        gevallen = (
            ("grote kop", tekstbeeld("Welkom bij Interpolis", 56, 20, 255), True),
            ("kleine bodytekst", tekstbeeld("U kunt uw polis beheren via het portaal van "
                                            "Interpolis en daarna verder gaan.", 13, 40, 255), None),
            ("omgekeerde kleuren", tekstbeeld("Welkom bij Interpolis", 56, 245, 15), True),
            ("schoon beeld", tekstbeeld("Overzicht portefeuille en openstaande schades", 30, 30, 255), False),
        )
        resultaat = []
        for naam, beeld, verwacht in gevallen:
            gevonden = bool(vind_lekken(e.lees_beeld(beeld), termen))
            resultaat.append(f"{naam}={'gevonden' if gevonden else 'niet'}")
            if verwacht is True and not gevonden:
                fouten.append(f"OCR ({e.naam}) mist het merkwoord in '{naam}'")
            if verwacht is False and gevonden:
                fouten.append(f"OCR ({e.naam}) geeft vals alarm op '{naam}'")
        print(f"  ocr {e.naam:9s}: " + ", ".join(resultaat))
    # automatisch maskeren -> opnieuw controleren
    beeld = tekstbeeld("Welkom bij Interpolis Autoverzekeringen", 48, 20, 255)
    schoon, rapport = controleer_lekken(beeld, engines, termen)
    print(f"  automask: {rapport.kaders_gemaskeerd} kader(s) gemaskeerd in {rapport.doorgangen} doorgangen, "
          f"rest {len(rapport.rest_lekken)}")
    if not rapport.kaders_gemaskeerd or rapport.rest_lekken:
        fouten.append("automatisch maskeren verhelpt het lek niet")
    if vind_lekken(lees_alle_engines(schoon, engines), termen):
        fouten.append("na automatisch maskeren is het woord nog leesbaar voor een tweede lezing")
    # de controle moet aantoonbaar kunnen falen: een engine die niets ziet vindt niets
    if vind_lekken(_LegeEngine().lees_beeld(beeld), termen):
        fouten.append("testengine zonder tekst vindt toch lekken")
    try:
        _goed, ijk, _mm = kalibreer_engines(engines, termen)
        for k in ijk:
            print(f"  ijkcontrole {k['engine']:9s}: {k['gevonden']}/{k['van']} gevonden, "
                  f"verplicht ok={k['verplicht_gevonden']}")
    except OcrOnbetrouwbaar as e:
        fouten.append(f"ijkcontrole mislukt: {e}")
    return fouten


class _stil:
    """Onderdrukt stdout tijdens zelftests die main() aanroepen."""
    def __enter__(self):
        self._oud = sys.stdout
        sys.stdout = io.StringIO()
        return self

    def __exit__(self, *exc):
        sys.stdout = self._oud


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _secties_arg(waarde: str):
    if str(waarde).strip().lower() == "auto":
        return "auto"
    try:
        n = int(waarde)
    except ValueError:
        raise argparse.ArgumentTypeError("--secties is een geheel getal of 'auto'")
    if n < 1:
        raise argparse.ArgumentTypeError("--secties moet minstens 1 zijn")
    return n


def _bouw_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Blinde A/B-harnas voor interfacebeoordeling")
    p.add_argument("--comps", nargs="*", default=["renders/comps", "renders/comps_nl"],
                   help="mappen met comps (echte, externe interfaces)")
    p.add_argument("--ours", nargs="*", default=["renders/ours"],
                   help="mappen met onze eigen schermen")
    p.add_argument("--decoy", nargs="*", default=["renders/decoy"],
                   help="mappen met decoy-beelden (bewust middelmatig ontwerp)")
    p.add_argument("--anker", nargs="*", default=["renders/anker"],
                   help="mappen met ankers: schermen waarvan vaststaat dat ze bovenaan "
                        "horen (positieve controle); ook klasse 'anker' in een manifest telt")
    p.add_argument("--domein", choices=DOMEIN_FILTERS, default="alles",
                   help="alleen comps uit dit domein (nl_financieel of internationaal); "
                        "eigen schermen, decoys en ankers doen altijd mee. 'alles' mengt de "
                        "domeinen en wordt in de sleutel als gemengde ronde vastgelegd")
    p.add_argument("--soort-scherm", nargs="*", default=[],
                   help="alleen comps van deze soort(en) scherm (bijv. app/dashboard formulier); "
                        "eigen schermen, decoys en ankers doen altijd mee. Zonder deze vlag doen alle "
                        "soorten mee en verdeelt het rapport de uitkomst per soort")
    p.add_argument("--inclusief-marketing", action="store_true",
                   help="neem beelden met klasse 'marketing' mee (standaard uitgesloten)")
    p.add_argument("--zonder-eigen-schermen", action="store_true",
                   help="sta een TESTRONDE zonder eigen schermen toe; de ronde wordt dan "
                        "NIET-BRUIKBAAR-VOOR-OORDEEL gemarkeerd. Zonder deze vlag is een lege "
                        "eigen-schermenmap exitcode 2")
    p.add_argument("--uit", default="renders/ab", help="uitvoermap")
    p.add_argument("--ronde", default=None, help="naam van de ronde (standaard: tijdstempel)")
    p.add_argument("--seed", type=int, default=None, help="seed voor de volgorde")
    p.add_argument("--breedte", type=int, default=1200,
                   help="identieke breedte in px voor desktop-beelden")
    p.add_argument("--breedte-mobile", type=int, default=780,
                   help="identieke breedte in px voor mobiele beelden "
                        "(apart, zodat mobiel niet onnodig wordt opgeschaald)")
    p.add_argument("--secties", type=_secties_arg, default="auto",
                   help="aantal uitsneden per beeld (bij meer dan een: boven, midden, onder). 'auto' (standaard) "
                        "kiest per viewport het grootste aantal (hoogstens 3) dat ELK beeld helemaal vult, want "
                        "lege opvulling verraadt welke pagina's kort zijn; een getal forceert dat aantal (de "
                        "ronde wordt geweigerd als de lege ruimte de klasse verraadt). Alle beelden van een "
                        "viewport krijgen dezelfde hoogte")
    p.add_argument("--sectie-hoogte", type=int, default=None,
                   help="hoogte van een uitsnede in px voor desktop (standaard een "
                        "schermhoogte: 0,625 x breedte)")
    p.add_argument("--sectie-hoogte-mobile", type=int, default=None,
                   help="hoogte van een uitsnede in px voor mobiel (standaard een "
                        "schermhoogte: 2,16 x breedte)")
    p.add_argument("--scheiding", type=int, default=SCHEIDING_PX,
                   help="hoogte van de grijze balk tussen de uitsneden in px")
    p.add_argument("--max-hoogte-ratio", type=float, default=None,
                   help="VEROUDERD. Werd de maximale hoogte; geeft nu, indien opgegeven, de "
                        "totale hoogte van alle uitsneden als veelvoud van de breedte")
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
                        "in relatieve coordinaten [x0,y0,x1,y1] van het eindbeeld; nog nodig "
                        "voor logo's zonder tekst (tekst maskeert de OCR zelf)")
    p.add_argument("--maskeer-footer", action=argparse.BooleanOptionalAction, default=True,
                   help="ook de footer-linkerhoek maskeren (logo's staan daar vaak); nu "
                        "standaard aan omdat elk beeld de onderkant van de pagina toont")
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
    p.add_argument("--ocr-engine", choices=["auto", "rapidocr", "tesseract", "beide"],
                   default="auto",
                   help="OCR-engine voor de lekcontrole. auto = alle beschikbare (RapidOCR "
                        "eerst, tesseract als tweede mening). Er is bewust geen vlag om OCR "
                        "over te slaan.")
    p.add_argument("--eigen-namen", nargs="*", default=[],
                   help="naam/namen van ons product (en bedrijf) die nooit leesbaar in beeld "
                        "mogen staan; aanvulling op de vaste lijst")
    p.add_argument("--verboden-extra", nargs="*", default=[],
                   help="extra verboden woorden voor de OCR-controle")
    p.add_argument("--verboden-bestand", default=None,
                   help="tekstbestand met extra verboden woorden, een per regel")
    p.add_argument("--zelftest", action="store_true")
    return p


def main(argv=None, ocr_engines=None, kalibreer: bool | None = None) -> int:
    """
    `ocr_engines` laat een aanroeper (tests) eigen engines injecteren; via de
    commandoregel bestaat er geen manier om OCR uit te zetten. Bij injectie wordt
    de ijkcontrole standaard overgeslagen (`kalibreer=True` forceert hem).
    """
    p = _bouw_parser()
    args = p.parse_args(argv)

    if args.zelftest:
        return zelftest()

    # de verouderde vlag: alleen als hij echt is opgegeven, telt hij mee
    args.max_hoogte_ratio_expliciet = args.max_hoogte_ratio
    if args.max_hoogte_ratio is None:
        args.max_hoogte_ratio = 3.0                       # oude standaard, alleen voor neutraliseer()

    if args.seed is None:
        args.seed = random.randrange(1, 10**9)
    ronde_id = args.ronde or time.strftime("ronde_%Y%m%d_%H%M%S")
    lek_naam = controleer_naam(ronde_id)
    if lek_naam:
        print(f"FOUT: de rondenaam {ronde_id!r} verraadt de bron: {lek_naam}. "
              "De beoordelaar ziet deze naam; kies een neutrale naam.")
        return EXIT_INVOER

    def paden(lst):
        return [Path(x) if Path(x).is_absolute() else PROJECT / x for x in (lst or [])]

    comp_mappen, ours_mappen = paden(args.comps), paden(args.ours)
    decoy_mappen, anker_mappen = paden(args.decoy), paden(args.anker)
    comps = verzamel_bronnen(comp_mappen, "comp")
    ours = verzamel_bronnen(ours_mappen, "ours")
    decoys = verzamel_bronnen(decoy_mappen, "decoy")
    ankers = verzamel_bronnen(anker_mappen, "anker")
    alle = comps + ours + decoys + ankers

    if not alle:
        print("Niets te doen: geen enkel bronbeeld gevonden.")
        return EXIT_INVOER

    bronnen, uitgesloten = filter_bronnen(alle, args.domein, args.inclusief_marketing, args.soort_scherm)

    waarschuwingen: list[str] = []
    ontbrekend: list[dict] = []
    for b in bronnen:
        if b.ontbrekend:
            ontbrekend.append({"bron_bestand": _rel(b.pad), "ontbrekend": list(b.ontbrekend)})
        for m in b.meldingen:
            if "staat niet in het manifest" in m or "manifest onleesbaar" in m \
                    or "onbekende waarde" in m or "is leidend" in m:
                waarschuwingen.append(f"{_rel(b.pad)}: {m}")
    if ontbrekend:
        tellers: dict[str, int] = {}
        for o in ontbrekend:
            for v in o["ontbrekend"]:
                tellers[v] = tellers.get(v, 0) + 1
        klasse_domein = {k: n for k, n in tellers.items() if k in ("klasse", "domein")}
        if klasse_domein:
            waarschuwingen.append(
                "classificatie ontbreekt in het manifest ("
                + ", ".join(f"{v}: {n} beelden" for v, n in sorted(klasse_domein.items()))
                + "); standaard toegepast (klasse product_ui, domein volgens de map)")
        if tellers.get("soort_scherm"):
            waarschuwingen.append(
                f"soort_scherm ontbreekt bij {tellers['soort_scherm']} beelden (comps en/of eigen schermen): "
                "het rapport kan die niet als vergelijkbaar met elkaar aanmerken")
    if args.domein == "alles":
        waarschuwingen.append("gemengde ronde (--domein alles): NL financieel en internationaal "
                              "door elkaar; kies --domein voor een vergelijkbare ronde")
    if uitgesloten:
        waarschuwingen.append(f"{len(uitgesloten)} beelden uitgesloten door de rondefilters "
                              f"(zie 'uitgesloten' in de sleutel)")

    onbekend_vp = [b for b in bronnen if b.viewport == "onbekend"]
    if onbekend_vp:
        namen = ", ".join(_rel(b.pad) for b in onbekend_vp[:6]) + ("..." if len(onbekend_vp) > 6 else "")
        waarschuwingen.append(
            f"{len(onbekend_vp)} beelden hebben geen herkenbare viewport (naam bevat geen "
            f"'desktop', 'mobile', '1440' of '390' en het manifest zegt het niet) en doen NIET "
            f"mee: {namen}")
        print("LET OP:", waarschuwingen[-1])
    meldingen = []
    if not any(b.soort == "comp" for b in bronnen):
        meldingen.append("GEEN COMPS GEVONDEN (na filters) - de harnas draait, maar er is niets "
                         "om ons tegen af te zetten.")
    if not any(b.soort == "decoy" for b in bronnen):
        meldingen.append("GEEN DECOY GEVONDEN - de meetlat wordt deze ronde niet "
                         "gecontroleerd. Draai scripts/maak_decoy.py.")
    if not any(b.soort == "anker" for b in bronnen):
        meldingen.append("GEEN ANKER GEVONDEN - er is geen positieve controle; het rapport "
                         "zal deze ronde ONGELDIG noemen.")
    for m in meldingen:
        print("LET OP:", m)
    waarschuwingen += meldingen

    # --- A. zonder eigen schermen geen echte ronde ---
    geen_ons = controleer_eigen_schermen(bronnen, args.viewports)
    if geen_ons and not args.zonder_eigen_schermen:
        print("\nFOUT (exitcode 2): de ronde zou niets meten.")
        for f in geen_ons:
            print("  -", f)
        print(f"  Eigen schermen gezocht in: {', '.join(map(str, ours_mappen))} "
              f"({'map ontbreekt' if not any(m.exists() for m in ours_mappen) else 'geen bruikbaar beeld'} "
              "na filters).")
        print("  Leg onze schermen in die map (of geef --ours), of draai bewust een testronde met "
              "--zonder-eigen-schermen (die wordt NIET-BRUIKBAAR-VOOR-OORDEEL).")
        if any(b.soort == "ours" and b.viewport == "onbekend" for b in bronnen):
            print("  Let op: er ligt wel een eigen scherm zonder herkenbare viewport in de naam; "
                  "geef het 'desktop' of 'mobile' in de bestandsnaam.")
        return EXIT_INVOER
    if geen_ons and args.zonder_eigen_schermen:
        print("LET OP: testronde zonder eigen schermen; de ronde wordt "
              "NIET-BRUIKBAAR-VOOR-OORDEEL gemarkeerd.")
        waarschuwingen.append("testronde zonder eigen schermen: NIET-BRUIKBAAR-VOOR-OORDEEL")

    # --- B. de verboden woorden en een werkende OCR-engine ---
    extra_woorden = list(args.verboden_extra)
    if args.verboden_bestand:
        vb = Path(args.verboden_bestand)
        if not vb.exists():
            print(f"FOUT: verboden-bestand {vb} bestaat niet.")
            return EXIT_INVOER
        extra_woorden += [r.strip() for r in vb.read_text(encoding="utf-8").splitlines()
                          if r.strip() and not r.startswith("#")]
    termen = bouw_verboden_termen(comp_mappen + ours_mappen + decoy_mappen + anker_mappen,
                                  extra_woorden, args.eigen_namen)
    if not args.eigen_namen and not any(t.bron in {"manifest:" + m.name for m in ours_mappen}
                                        for t in termen.alle):
        waarschuwingen.append("geen eigen productnaam opgegeven (--eigen-namen of merknamen in "
                              "renders/ours/manifest.json): de OCR kent alleen de vaste namen "
                              "van ons product")

    kalibratie: list[dict] = []
    if ocr_engines is None:
        try:
            engines, engine_meldingen = beschikbare_ocr_engines(args.ocr_engine)
        except OcrNietBeschikbaar as e:
            print(f"\nFOUT (exitcode {EXIT_GEEN_OCR}): {e}")
            return EXIT_GEEN_OCR
        for m in engine_meldingen:
            print("LET OP:", m)
            waarschuwingen.append(m)
        if kalibreer is not False:
            try:
                engines, kalibratie, km = kalibreer_engines(engines, termen)
            except OcrOnbetrouwbaar as e:
                print(f"\nFOUT (exitcode {EXIT_GEEN_OCR}): de OCR-ijkcontrole is mislukt: {e}")
                return EXIT_GEEN_OCR
            for m in km:
                print("LET OP:", m)
                waarschuwingen.append(m)
            for k in kalibratie:
                print(f"OCR-ijkcontrole {k['engine']}: {k['gevonden']}/{k['van']} testwoorden gevonden "
                      f"(verplichte rijen {'ok' if k['verplicht_gevonden'] else 'GEMIST'})")
        if all(e.naam == "tesseract" for e in engines):
            waarschuwingen.append("alleen tesseract beschikbaar: gemeten detectiegraad 88-91% op het "
                                  "interne testpaneel tegen 99-100% voor RapidOCR; laag contrast en "
                                  "licht-op-donker kunnen gemist zijn")
    else:
        engines = list(ocr_engines)
        if kalibreer:
            engines, kalibratie, _km = kalibreer_engines(engines, termen)

    ctx = RondeContext(
        domein_filter=args.domein,
        soort_scherm_filter=sorted({norm_soort_scherm(x) for x in args.soort_scherm}),
        inclusief_marketing=args.inclusief_marketing,
        zonder_eigen_schermen=args.zonder_eigen_schermen,
        uitgesloten=uitgesloten,
        waarschuwingen=waarschuwingen,
        engines=engines,
        termen=termen,
        kalibratie=kalibratie,
        classificatie_ontbreekt=ontbrekend,
    )

    args.uit = str(Path(args.uit) if Path(args.uit).is_absolute() else PROJECT / args.uit)
    res = bouw_ronde(bronnen, args, ronde_id, ctx)

    if res["geweigerd"]:
        g = res["geweigerd"]
        titel = {EXIT_LEK: "IDENTITEITSLEK", EXIT_EIGENSCHAP: "RONDE-EIGENSCHAP GESCHONDEN",
                 EXIT_FOUT: "BRON VIEL UIT"}.get(g["code"], "GEWEIGERD")
        print(f"\nRonde GEWEIGERD (exitcode {g['code']}): {titel}. Er is niets weggeschreven.")
        for r in g["redenen"]:
            print("  -", r)
        return g["code"]

    sleutelpad = schrijf_sleutel(Path(args.uit), ronde_id, res["sleutel"])
    meetlat = res["sleutel"]["meetlat"]
    print(f"\nRonde     : {ronde_id}")
    print(f"Status    : {meetlat['status']}")
    print(f"Seed      : {args.seed}")
    print(f"Domein    : {meetlat['domein_filter']}"
          + (f"   soort scherm: {', '.join(meetlat['soort_scherm_filter'])}" if meetlat['soort_scherm_filter'] else ""))
    print("Manifest  : " + ", ".join(f"{n}x {v}" for v, n in res["sleutel"]["manifestvormen"].items()))
    print(f"Beelden   : {res['totaal']}")
    keuze = res["sleutel"].get("secties_keuze") or {}
    if keuze:
        print("Secties   : " + ", ".join(f"{vp} {r['gekozen']} ({r['modus']})" for vp, r in keuze.items()))
    print(f"Beoordeel : {res['ronde_map']}   (GEEF ALLEEN DEZE MAP)")
    print(f"Sleutel   : {sleutelpad}   (GEHEIM)")
    for vp, info in res["sleutel"]["viewports"].items():
        print(f"  {vp}: {info['aantal']} beelden van {info['breedte_px']}x{info['hoogte_px']} px, "
              f"decoy = {', '.join(res['decoy_labels'].get(vp, [])) or 'geen'}")
    print(res["sleutel"]["ocr"]["dekking"])
    if res["sleutel"]["ocr"]["beelden_met_lage_dekking"]:
        print("LET OP: weinig tekst gelezen in beeld(en) "
              + ", ".join(res["sleutel"]["ocr"]["beelden_met_lage_dekking"])
              + " - controleer die handmatig op merknamen")
    for w in waarschuwingen:
        print("WAARSCHUWING:", w)
    for pr in res["problemen"]:
        print("PROBLEEM:", pr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
