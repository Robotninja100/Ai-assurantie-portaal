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


def detecteer_browser_chrome(img: Image.Image, max_fractie: float = 0.18) -> tuple[int, str]:
    """
    Browser-chrome is een vlakke, egale balk bovenaan (tabbalk + adresbalk) die
    eindigt met een harde horizontale rand. Playwright-screenshots hebben dit
    normaal NIET; dit is er voor handmatig gemaakte schermafbeeldingen.

    Retourneert (aantal_px_af_te_snijden, reden).
    """
    h = img.height
    grens = max(8, int(h * max_fractie))
    gem, spreiding = _rijprofiel(img)
    gem, spreiding = gem[:grens], spreiding[:grens]
    if len(gem) < 12:
        return 0, "beeld te klein voor chromedetectie"

    beste_r, beste_score = 0, 0.0
    for r in range(6, len(gem) - 4):
        boven_spreiding = float(spreiding[:r].mean())
        stap = abs(float(gem[r - 1]) - float(gem[min(r + 2, len(gem) - 1)]))
        # chrome: rustig erboven (weinig detail), harde stap op de grens
        if boven_spreiding < 26.0 and stap > 18.0:
            score = stap - boven_spreiding * 0.4
            if score > beste_score:
                beste_score, beste_r = score, r
    if beste_r:
        return beste_r, f"vlakke balk boven rij {beste_r} met randcontrast {beste_score:.1f}"
    return 0, "geen browser-chrome aangetroffen (schermafbeelding lijkt chroomloos)"


def detecteer_bodembanner(img: Image.Image,
                          min_px: int = 40,
                          max_fractie: float = 0.22) -> tuple[int, str]:
    """
    Cookiebanner-rest: een egale strook aan de ONDERRAND, duidelijk afgescheiden
    van de inhoud erboven en met weinig eigen structuur. Conservatief: een echte
    footer heeft veel detail en wordt daarom niet weggesneden.
    """
    h = img.height
    venster = max(min_px + 8, int(h * max_fractie))
    if h < venster + 40:
        return 0, "beeld te kort voor bodemdetectie"
    gem, spreiding = _rijprofiel(img)
    start = h - venster

    beste_r, beste_score = 0, 0.0
    for r in range(start, h - min_px):
        band_spreiding = float(spreiding[r:].mean())
        band_gem = float(gem[r:].mean())
        boven_gem = float(gem[max(0, r - 60):r].mean())
        stap = abs(band_gem - boven_gem)
        if band_spreiding < 12.0 and stap > 14.0:
            score = stap - band_spreiding
            if score > beste_score:
                beste_score, beste_r = score, r
    if beste_r:
        return h - beste_r, (f"egale strook vanaf rij {beste_r} "
                             f"(contrast {beste_score:.1f}) - vermoedelijk bannerrest")
    return 0, "geen bannerrest aangetroffen"


# ---------------------------------------------------------------------------
# 5. Merkidentiteit maskeren
# ---------------------------------------------------------------------------
def detecteer_headerhoogte(img: Image.Image, standaard: int) -> int:
    """Eerste harde horizontale scheiding in de bovenste 22% = onderkant header."""
    grens = max(24, int(img.height * 0.22))
    gem, _ = _rijprofiel(img)
    gem = gem[:grens]
    if len(gem) < 24:
        return min(standaard, img.height)
    verschil = np.abs(np.diff(gem))
    zone = verschil[20:]
    if len(zone) == 0:
        return min(standaard, img.height)
    idx = int(np.argmax(zone)) + 20
    if float(zone.max()) > 8.0:
        return max(40, min(idx + 2, grens))
    return min(standaard, img.height)


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
                       maskeer_footer: bool = False) -> tuple[int, list[dict]]:
    """
    Maskeert de plekken waar merkidentiteit vrijwel altijd zit:
      - linksboven in de header (woordmerk/logo)
      - rechtsboven in de header (merkknoppen, accountmerk, taalkiezer)
      - de allerbovenste strook linksbuiten de header (sticky mini-logo)
    Optioneel de footer-linkerhoek.
    """
    standaard = 110 if viewport != "mobile" else 72
    header_h = detecteer_headerhoogte(img, standaard)
    header_h = max(48, min(header_h, int(img.height * 0.22)))
    w = img.width
    regios: list[dict] = []

    kaders = [
        ("header-links", (0, 0, int(w * 0.30), header_h)),
        ("header-rechts", (int(w * 0.72), 0, w, header_h)),
    ]
    if maskeer_footer:
        fy0 = int(img.height * 0.90)
        kaders.append(("footer-links", (0, fy0, int(w * 0.34), img.height)))

    for naam, kader in kaders:
        _pixeleer(img, kader)
        regios.append({"naam": naam, "kader": list(kader)})
    return header_h, regios


# ---------------------------------------------------------------------------
# 6. Merkkleur neutraliseren
# ---------------------------------------------------------------------------
def naar_neutraal_grijs(img: Image.Image, chroma_winst: float = 0.45,
                        sigma: float = 2.0) -> tuple[Image.Image, str]:
    """
    Grijswaarden op basis van CIE-L* (waarneembare lichtheid), plus een hoogdoorlaat
    van de chroma. Daarmee blijven randen tussen kleuren met GELIJKE lichtheid
    (denk: blauwe knop op grijze balk) zichtbaar als structuur, terwijl de kleur
    zelf - en dus 'welk blauw is mooier' - volledig verdwijnt.
    """
    lab = img.convert("RGB").convert("LAB")
    L, A, B = lab.split()
    l = np.asarray(L, dtype=np.float32)
    a = np.asarray(A, dtype=np.float32) - 128.0
    b = np.asarray(B, dtype=np.float32) - 128.0

    chroma = np.sqrt(a * a + b * b)
    ch_img = Image.fromarray(np.clip(chroma, 0, 255).astype(np.uint8), mode="L")
    ch_blur = np.asarray(ch_img.filter(ImageFilter.GaussianBlur(sigma)), dtype=np.float32)
    hoogdoorlaat = chroma - ch_blur           # alleen chroma-RANDEN, geen kleurvlak

    grijs = np.clip(l + chroma_winst * hoogdoorlaat, 0, 255).astype(np.uint8)
    return Image.fromarray(grijs, mode="L"), (
        f"CIE-L* + chroma-hoogdoorlaat (winst {chroma_winst}, sigma {sigma})"
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
                 chroma_winst: float) -> tuple[Image.Image, NeutralisatieLog]:
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
    header_h, regios = maskeer_merkregios(img, viewport, maskeer_footer)
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
def bouw_ronde(bronnen: list[Bron], args, ronde_id: str) -> dict[str, Any]:
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
        "breedte_px": args.breedte,
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
        vp_map = ronde_map / vp
        vp_map.mkdir(parents=True, exist_ok=True)

        items = []
        geschreven: list[Path] = []
        for label, bron in zip(labels(len(lijst)), lijst):
            try:
                img, log = neutraliseer(
                    bron.pad, bron.viewport, args.breedte, args.max_hoogte_ratio,
                    args.contrast, args.snij_boven, args.maskeer_footer, args.chroma_winst)
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

        # alle bestanden op gelijke mtime en (optioneel) gelijke grootte
        for p in geschreven:
            os.utime(p, (1735689600, 1735689600))  # 2025-01-01T00:00:00Z
        gelijke_grootte = 0
        if args.maskeer_grootte:
            gelijke_grootte = maskeer_bestandsgroottes(geschreven)

        schrijf_beoordelingsformulier(vp_map, [i["label"] for i in items])
        sleutel_rondes["viewports"][vp] = {
            "aantal": len(items),
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
    vps = ", ".join(sleutel["viewports"].keys()) or "-"
    tekst = f"""# Blinde beoordeling

Alle schermen zijn geneutraliseerd: merkkleur is verwijderd (grijswaarden met
behoud van contrast en structuur), logo-regio's zijn onherkenbaar gemaakt,
browser-chrome en bannerresten zijn weggesneden en elk beeld is naar dezelfde
breedte ({sleutel['breedte_px']} px) geschaald. Resolutie, kleur en merk zijn dus
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

    # kleurverschil bij gelijke lichtheid moet als structuur overleven
    proef = Image.new("RGB", (200, 100), (120, 120, 120))
    d = ImageDraw.Draw(proef)
    d.rectangle([40, 30, 160, 70], fill=(0, 110, 190))   # merkblauw, ~gelijke L*
    grijs, _ = naar_neutraal_grijs(proef)
    a = np.asarray(grijs, dtype=np.float32)
    randsterkte = float(np.abs(np.diff(a[50])).max())
    if randsterkte < 6:
        fouten.append(f"isoluminante rand verdwijnt (sterkte {randsterkte:.1f})")

    # grijs moet echt grijs zijn: geen kleurkanalen meer
    if grijs.mode != "L":
        fouten.append(f"uitvoer is niet eenkanaals maar {grijs.mode}")

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
    p.add_argument("--breedte", type=int, default=1200, help="identieke breedte in px")
    p.add_argument("--max-hoogte-ratio", type=float, default=3.0,
                   help="max hoogte als veelvoud van de breedte (0 = onbegrensd)")
    p.add_argument("--contrast", choices=["uit", "zacht", "hard"], default="zacht")
    p.add_argument("--chroma-winst", type=float, default=0.45,
                   help="hoeveel chroma-randen als structuur terugkomen in het grijs")
    p.add_argument("--snij-boven", type=int, default=None,
                   help="forceer aantal px browser-chrome dat boven wordt weggesneden")
    p.add_argument("--maskeer-footer", action="store_true",
                   help="ook de footer-linkerhoek maskeren (logo's staan daar vaak)")
    p.add_argument("--viewports", nargs="*", default=["desktop", "mobile"])
    p.add_argument("--max-per-bron", type=int, default=1,
                   help="max aantal beelden per comp-bron per viewport (0 = alles)")
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
