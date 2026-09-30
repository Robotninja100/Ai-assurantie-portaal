"""
Hulp voor de meetlat-tests (tests/test_meetlat_*.py): synthetische bronbeelden met PIL,
testengines en de OCR-fixtures. Er worden GEEN echte comps gebruikt en er staat niets in
git wat groter is dan tekst; alle beelden ontstaan in de test zelf.

Deze module bevat zelf geen tests.

OCR-tests falen (ze slaan niet over) als er geen OCR-engine is: een controle die niet kan
draaien is geen controle. Wie dat bewust niet wil: MEETLAT_OCR_TESTS=overslaan.
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# De OCR-cache van het harnas staat standaard in ~/.cache en blijft tussen runs bestaan. Voor tests is dat fout:
# een eerdere run kan dan een lezing leveren waar een test juist de eerste, volledige lezing wil zien (en een
# testengine kan door de cache nooit meer falen). Een test die de cache zelf toetst, zet BLIND_AB_OCR_CACHE zelf.
os.environ["BLIND_AB_OCR_CACHE"] = ""

import blind_ab            # noqa: E402
import blind_ab_rapport    # noqa: E402

# Kleine breedtes houden de tests snel; de logica is breedte-onafhankelijk.
BREEDTE_DESKTOP = 300
BREEDTE_MOBIEL = 200
BASIS_ARGS = ["--breedte", str(BREEDTE_DESKTOP), "--breedte-mobile", str(BREEDTE_MOBIEL), "--seed", "3"]

# Een streeppatroon in het bronbeeld (bronbreedte 600 -> beeldbreedte 300): op deze plek
# 'leest' ZietTekstAlsErContrastIsEngine het woord Interpolis, zolang het patroon bestaat.
PATROON = (40, 240, 400, 320)        # x0, y0, x1, y1 in bronpixels van een 600 px brede pagina


# ---------------------------------------------------------------------------
# Testengines (zonder OCR-rekentijd)
# ---------------------------------------------------------------------------
class NietsZienEngine:
    """Leest nooit iets. Bewijst dat de lekcontrole niets vindt als de engine niets ziet
    (en dat de ijkcontrole zo'n blinde engine afkeurt)."""
    naam = "niets-zien"

    def lees_beeld(self, img, gebieden=None):
        return []

    def beschrijving(self):
        return {"naam": self.naam, "versie": "test"}


class ZietAltijdEenLekEngine:
    """Ziet ALTIJD 'Interpolis', ook na maskeren: een lek dat automatisch maskeren niet oplost."""
    naam = "ziet-altijd-lek"

    def lees_beeld(self, img, gebieden=None):
        regel = blind_ab._regel_uit_woorden([("Interpolis", (10.0, 10.0, 120.0, 40.0))], 0.99, self.naam)
        return [regel]

    def beschrijving(self):
        return {"naam": self.naam, "versie": "test"}


class ZietTekstAlsErContrastIsEngine:
    """
    Ziet 'Interpolis' zolang het streeppatroon (brede zwarte en witte stroken naast elkaar)
    in de rij door het midden van een venster van 40 px hoog nog bestaat. Na verpixelen of
    invullen is het patroon weg en ziet de engine niets meer. Zo kan de automask-lus snel en
    deterministisch getest worden, met een engine die aantoonbaar kan falen.
    """
    naam = "ziet-strepen"

    def __init__(self):
        self.aanroepen = 0
        self.gebieden_log = []              # per aanroep: None (hele beeld) of de gevraagde y-bereiken

    def lees_beeld(self, img, gebieden=None):
        import numpy as np
        self.aanroepen += 1
        self.gebieden_log.append(gebieden)
        a = np.asarray(img.convert("L"))
        uit = []
        for y0 in range(0, max(1, a.shape[0] - 40), 20):
            rij = a[y0 + 20, 20:200]
            donker, licht = rij < 70, rij > 190
            toestand, wissels = None, 0
            for d, l in zip(donker, licht):
                nieuw = "d" if d else "l" if l else toestand
                if toestand is not None and nieuw != toestand:
                    wissels += 1
                toestand = nieuw
            if wissels >= 6:
                uit.append(blind_ab._regel_uit_woorden(
                    [("Interpolis", (20.0, float(y0), 200.0, float(y0 + 40)))], 0.99, self.naam))
        return uit

    def beschrijving(self):
        return {"naam": self.naam, "versie": "test"}


# ---------------------------------------------------------------------------
# Synthetische bronnen
# ---------------------------------------------------------------------------
def maak_pagina(pad: Path, breedte: int, hoogte: int, *, achtergrond=(238, 238, 238), zaad: int = 0,
                teksten=(), patroon: bool = False, balken: bool = True) -> None:
    """Een nagebootste schermopname: gekleurde balken op een vlak, optioneel tekst.
    `teksten` = [(x, y, tekst, px, grijswaarde)]. `patroon` zet het streeppatroon op PATROON."""
    rng = random.Random(zaad)
    im = Image.new("RGB", (breedte, hoogte), achtergrond)
    d = ImageDraw.Draw(im)
    for y in range(0, hoogte, 50):
        if not balken or (patroon and PATROON[1] - 30 <= y <= PATROON[3] + 30):
            continue
        kleur = tuple(rng.randrange(60, 200) for _ in range(3))
        d.rectangle([12, y + 6, 12 + rng.randrange(40, max(60, breedte - 40)), y + 20], fill=kleur)
    if patroon and hoogte > PATROON[3] + 10 and breedte >= PATROON[2]:
        x0, y0, x1, y1 = PATROON
        for i, x in enumerate(range(x0, x1, 40)):
            d.rectangle([x, y0, x + 39, y1], fill=(0, 0, 0) if i % 2 == 0 else (255, 255, 255))
    for x, y, tekst, px, grijs in teksten:
        d.text((x, y), tekst, font=blind_ab.lettertype(px), fill=(grijs, grijs, grijs))
    pad.parent.mkdir(parents=True, exist_ok=True)
    im.save(pad)


def bouw_bronnen(root: Path, *, ours: bool | str = True, decoys: tuple = (("zwak", 700),),
                 anker: bool = True, mobiel: bool = True, comp_hoogtes=(500, 1500, 3400),
                 comps_nl_hoogtes=(900, 2300), patroon: bool = False,
                 internationaal: bool = True) -> dict[str, Path]:
    """
    Zet in `root` een complete set bronnen neer: comps (internationaal, lijstmanifest), comps_nl
    (woordenboekmanifest), ours (zonder manifest), decoy (met kwaliteit) en anker. Alle
    beeldhoogten verschillen bewust. `ours` is True (desktop en mobiel), "desktop" (alleen
    desktop) of False (lege map). Retourneert de mappen.
    """
    m = {n: root / n for n in ("comps", "comps_nl", "ours", "decoy", "anker")}
    for p in m.values():
        p.mkdir(parents=True, exist_ok=True)
    lijst = []
    zaad = 0
    if internationaal:
        for i, h in enumerate(comp_hoogtes):
            zaad += 1
            naam = f"intl{i}_desktop_1440.png"
            maak_pagina(m["comps"] / naam, 600, h, zaad=zaad, patroon=patroon)
            lijst.append({"id": f"intl{i}", "bron_naam": f"Internationaal {i}", "bestand": naam,
                          "wat_het_toont": "test", "klasse": "product_ui", "domein": "internationaal",
                          "taal": "en", "geladen_ok": True})
            if mobiel:
                naam_m = f"intl{i}_mobile_390.png"
                maak_pagina(m["comps"] / naam_m, 390, h * 2, zaad=zaad + 50)
                lijst.append({"id": f"intl{i}", "bron_naam": f"Internationaal {i}", "bestand": naam_m,
                              "klasse": "product_ui", "domein": "internationaal", "taal": "en",
                              "geladen_ok": True})
        (m["comps"] / "manifest.json").write_text(json.dumps(lijst), encoding="utf-8")
    nl = []
    for i, h in enumerate(comps_nl_hoogtes):
        zaad += 1
        bestanden = {}
        maak_pagina(m["comps_nl"] / f"nl{i}-desktop-1440x900.png", 600, h, zaad=zaad, patroon=patroon)
        bestanden["desktop"] = {"file": f"nl{i}-desktop-1440x900.png"}
        if mobiel:
            maak_pagina(m["comps_nl"] / f"nl{i}-mobile-390x844.png", 390, h * 2, zaad=zaad + 50)
            bestanden["mobile"] = {"file": f"nl{i}-mobile-390x844.png"}
        nl.append({"slug": f"nl{i}", "naam": f"Nederlands {i} - test", "categorie": "vergelijker",
                   "klasse": "product_ui", "domein": "nl_financieel", "taal": "nl", "bestanden": bestanden})
    (m["comps_nl"] / "manifest.json").write_text(json.dumps({"set": "comps_nl", "comps": nl}), encoding="utf-8")
    if ours:
        maak_pagina(m["ours"] / "portaal-desktop-1440x900.png", 600, 1100, zaad=91, patroon=patroon)
        if mobiel and ours is True:
            maak_pagina(m["ours"] / "portaal-mobile-390x844.png", 390, 1900, zaad=92)
    dec = []
    for i, (kw, h) in enumerate(decoys):
        maak_pagina(m["decoy"] / f"decoy{i}-desktop-1440x900.png", 600, h, zaad=200 + i)
        dec.append({"viewport": "desktop", "bestand": f"decoy{i}-desktop-1440x900.png", "klasse": "decoy",
                    "kwaliteit": kw, "id": f"decoy{i}", "domein": "decoy"})
        if mobiel:
            maak_pagina(m["decoy"] / f"decoy{i}-mobile-390x844.png", 390, h * 2, zaad=210 + i)
            dec.append({"viewport": "mobile", "bestand": f"decoy{i}-mobile-390x844.png", "klasse": "decoy",
                        "kwaliteit": kw, "id": f"decoy{i}", "domein": "decoy"})
    (m["decoy"] / "manifest.json").write_text(json.dumps({"set": "decoy", "bestanden": dec}), encoding="utf-8")
    if anker:
        maak_pagina(m["anker"] / "anker-desktop-1440x900.png", 600, 1700, zaad=300)
        ank = [{"bestand": "anker-desktop-1440x900.png", "klasse": "anker", "domein": "anker",
                "bron_naam": "Ankerbron"}]
        if mobiel:
            maak_pagina(m["anker"] / "anker-mobile-390x844.png", 390, 2600, zaad=301)
            ank.append({"bestand": "anker-mobile-390x844.png", "klasse": "anker", "domein": "anker",
                        "bron_naam": "Ankerbron"})
        (m["anker"] / "manifest.json").write_text(json.dumps({"bestanden": ank}), encoding="utf-8")
    return m


def cli_args(root: Path, mappen: dict[str, Path], *extra: str, ronde: str = "r", uit: str = "ab") -> list[str]:
    """De commandoregel voor blind_ab.main() met de bronnen in `mappen`."""
    return (["--comps", str(mappen["comps"]), str(mappen["comps_nl"]),
             "--ours", str(mappen["ours"]), "--decoy", str(mappen["decoy"]),
             "--anker", str(mappen["anker"]), "--uit", str(root / uit), "--ronde", ronde]
            + BASIS_ARGS + list(extra))


def lees_sleutel(root: Path, ronde: str = "r", uit: str = "ab") -> dict:
    return json.loads((root / uit / "_sleutel.json").read_text(encoding="utf-8"))["rondes"][ronde]


def draai(root: Path, mappen: dict[str, Path], *extra: str, engines=None, ronde: str = "r",
          uit: str = "ab") -> int:
    """blind_ab.main() met stub-engines (standaard: leest niets)."""
    return blind_ab.main(cli_args(root, mappen, *extra, ronde=ronde, uit=uit),
                         ocr_engines=engines if engines is not None else [NietsZienEngine()])


# ---------------------------------------------------------------------------
# OCR-fixtures
# ---------------------------------------------------------------------------
def haal_ocr_engines():
    if os.environ.get("MEETLAT_OCR_TESTS") == "overslaan":
        pytest.skip("MEETLAT_OCR_TESTS=overslaan")
    try:
        engines, _m = blind_ab.beschikbare_ocr_engines("auto")
    except blind_ab.OcrNietBeschikbaar as e:
        pytest.fail(
            "Er is geen OCR-engine; zonder OCR kan de meetlat geen ronde blind garanderen en zijn de "
            "OCR-tests zonder waarde. Installeer er een: `pip install -r requirements-dev.txt` "
            f"(rapidocr) of apt-get install tesseract-ocr tesseract-ocr-nld tesseract-ocr-eng. ({e})")
    return engines
