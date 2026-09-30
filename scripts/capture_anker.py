#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_anker.py - legt het PLAFONDANKER van de blinde meetlat vast (positieve controle).

Waarom
------
De eerste meetronde had geen scherm waarvan vaststond dat het bovenaan hoort. Zonder zo'n anker kun
je niet onderscheiden of een beoordelaar smaak heeft of alleen drukte afstraft: eindigt een scherm
dat breed als uitzonderlijk goed geldt niet bovenaan, dan is het de beoordelaar (of de neutralisatie)
die niet deugt, niet het scherm.

Keuze en de grenzen daarvan
---------------------------
Het anker is echte product-UI van uitzonderlijke kwaliteit, publiek en zonder account toegankelijk:
de documentatie-applicatie van Stripe (docs.stripe.com). Dat het breed als referentie geldt is een
OORDEEL met externe bronnen (zie ONDERBOUWING en het manifest), geen meting. Het is een documentatie-
interface, geen backoffice-app: het anker toetst de smaak van de beoordelaar, niet de domeinmatch.

Twee schermen met een verschillende opbouw:
  stripe_docs_api_reference     drie kolommen (navigatieboom, tekst, codepanelen), dichte informatie
  stripe_docs_payment_methods   documentatie-artikel: navigatieboom, artikelkolom met callout en 'On this page'

Beide docs-pagina's werken met een eigen scroll-container; de desktop-opname is daardoor precies een
viewport hoog (1440x900). Dat is wat er zichtbaar is, geen afkapping door het script.

Een eerdere kandidaat, de interactieve quickstart (docs.stripe.com/payments/quickstart), viel af: op
390 breed loopt die horizontaal over (980 css-px layout), wat de controle als 'breder_dan_viewport'
afkeurt. Dat is een echte eigenschap van die pagina, geen fout van de opname.

Uitvoer: renders/anker/<id>_1440.png, <id>_390.png + manifest.json (object met "bestanden" en
"ankers"; schema: zie scripts/capture_controle.py).

Gebruik
-------
  python3 scripts/capture_anker.py                    # vastleggen
  python3 scripts/capture_anker.py --alleen-manifest  # manifest herbouwen zonder netwerk
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture_controle as cc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "renders" / "anker"
MANIFEST = OUT_DIR / "manifest.json"

DEKKING = ("Internationaal en buiten het domein: een documentatie-interface, geen Nederlands assurantie-"
           "backoffice. Het anker is een positieve controle op de smaak van de beoordelaar en op de "
           "neutralisatie, geen vertegenwoordiger van de categorie waarin het product valt.")

MOTIVATIE = ("Waarom dit anker: de documentatie van Stripe wordt door ontwikkelaars, documentatie-vakmensen "
             "en ontwerpers consequent genoemd als de standaard in de sector (drie kolommen, rustige "
             "informatiehierarchie, strakke typografie, interactieve voorbeelden naast de tekst, hoge dichtheid "
             "zonder drukte). Het is echte, werkende product-UI en publiek zonder account. Dat maakt het een "
             "scherm dat in vrijwel elke pool bovenaan hoort; staat het in een ronde niet in de bovenste helft, "
             "dan meet de beoordelaar iets anders dan visuele kwaliteit (bijvoorbeeld witruimte of "
             "kleurloosheid) en zijn de scores voor onze eigen schermen niet te vertrouwen. Beperking: dit "
             "is een oordeel op grond van externe bronnen, geen meting; en het is een documentatie-interface, "
             "geen backoffice-app.")

ONDERBOUWING = [
    {"titel": "How Stripe creates the best documentation in the industry (Mintlify)",
     "url": "https://www.mintlify.com/blog/stripe-docs"},
    {"titel": "Stripe Developer Experience Teardown: What to Steal in 2026 (Moesif)",
     "url": "https://www.moesif.com/blog/best-practices/api-product-management/the-stripe-developer-experience-and-docs-teardown/"},
    {"titel": "Why Stripe's API Docs Are the Benchmark (Apidog)", "url": "https://apidog.com/blog/stripe-docs/"},
    {"titel": "Stripe developer documentation (InfoQ-presentatie)",
     "url": "https://www.infoq.com/presentations/stripe-developer-documentation"},
]
ONDERBOUWING_NOOT = ("Bronnen gevonden via een zoekopdracht op 2026-09-29; het zijn meningen van derden (deels "
                     "commercieel: Mintlify en Apidog verkopen documentatietools), niet een onafhankelijke meting. "
                     "Ze zijn hier alleen aangehaald om te laten zien dat 'breed aangehaald als referentie' geen "
                     "eigen smaakoordeel van de opnemer is.")

GEINSPECTEERD_OP = "2026-09-29"

# `wat_het_toont` is na het bekijken van de opnames (desktop en mobiel) door de opnemer vastgesteld.
ANKERS: list[dict] = [
    {"id": "stripe_docs_api_reference", "bron_naam": "Stripe documentatie - API-referentie",
     "url": "https://docs.stripe.com/api", "wait_ms": 5000,
     "wat_het_toont": ("Stripe API-referentie (docs.stripe.com/api): documentatie-applicatie in drie kolommen. "
                       "Desktop: zoekbalk en navigatieboom links, introductietekst in het midden, rechts codepanelen "
                       "(base URL, clientbibliotheken). Mobiel: dezelfde tekst als een kolom onder een compacte "
                       "kopbalk. De opname is een viewport hoog omdat de pagina in een eigen scroll-container werkt."),
     "geinspecteerd_op": GEINSPECTEERD_OP},
    {"id": "stripe_docs_payment_methods", "bron_naam": "Stripe documentatie - ondersteunde betaalmethoden",
     "url": "https://docs.stripe.com/payments/payment-methods/overview", "wait_ms": 7000,
     "wat_het_toont": ("Stripe-documentatie 'Supported payment methods': artikel met navigatieboom links, artikelkolom "
                       "(titel, lead, bulletlijst, callout 'Pricing and fees') en rechts een inhoudsopgave 'On this "
                       "page'. Geen tabel in beeld. Mobiel: artikel als een kolom (circa 7500 css-px lang)."),
     "geinspecteerd_op": GEINSPECTEERD_OP},
]
for _a in ANKERS:
    _a.setdefault("klasse", "anker")
    _a.setdefault("domein", "anker")
    _a.setdefault("taal", "en")
    _a.setdefault("soort_scherm", "docs")
    _a.setdefault("dekking_categorie", DEKKING)
    _a.setdefault("onderbouwing", ONDERBOUWING)
    _a.setdefault("toegang", "publiek, zonder account")


def bestandsnaam(a: dict, vp: str) -> str:
    return f'{a["id"]}_{"1440" if vp == "desktop" else "390"}.png'


def _kaart(a: dict) -> dict:
    k = dict(a)
    k["_concept"] = not a.get("wat_het_toont")
    return k


def leg_vast(browser, a: dict) -> list[dict]:
    kaart = _kaart(a)
    recs: list[dict] = []
    for i, vp in enumerate(cc.VIEWPORT_NAMEN):
        if i:
            time.sleep(cc.PAUZE_TUSSEN_LADINGEN_S)
        bestand = bestandsnaam(a, vp)
        raw = cc.leg_vast(browser, kaart, vp, OUT_DIR, bestand, wacht_ms=a.get("wait_ms", 5000),
                          stappen=a.get("stappen"))
        if not (OUT_DIR / bestand).exists():
            reden = raw.get("fout") or "geen opname gemaakt"
            code = "http_" + reden.split()[-1] if reden.startswith("HTTP") else "capture_mislukt"
            for vp2 in cc.VIEWPORT_NAMEN[i:]:
                recs.append(cc.record_zonder_bestand(kaart=kaart, viewport_naam=vp2, reden=reden, codes=[code]))
            print(f"SKIP {bestand:<40} {reden}", flush=True)
            return recs
        rec = cc.bouw_record(kaart=kaart, viewport_naam=vp, bestand=bestand, map_pad=OUT_DIR, raw=raw)
        recs.append(rec)
        print(f'{"OK  " if rec["geladen_ok"] else "AFK "} {rec["bestand"]:<48} '
              f'{",".join(rec["afkeurredenen"]) or "schoon"}', flush=True)
    return recs


def main() -> int:
    ap = argparse.ArgumentParser(description="Leg het plafondanker vast")
    ap.add_argument("--alleen-manifest", action="store_true")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    if args.alleen_manifest:
        oud = {(e["id"], e["viewport_naam"]): e for e in cc.lees_opnames(MANIFEST)} if MANIFEST.exists() else {}
        for a in ANKERS:
            for vp in cc.VIEWPORT_NAMEN:
                e = oud.get((a["id"], vp))
                if e is None:
                    continue
                if not e.get("bestand"):
                    records.append(e)
                    continue
                records.append(cc.bouw_record(kaart=_kaart(a), viewport_naam=vp, bestand=bestandsnaam(a, vp),
                                              map_pad=OUT_DIR, raw=cc.raw_uit_record(e)))
    else:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = cc.start_browser(pw)
            for n, a in enumerate(ANKERS):
                if n:
                    time.sleep(4)
                records += leg_vast(browser, a)
            browser.close()

    manifest = {
        "set": "anker",
        "schema_versie": cc.SCHEMA_VERSIE,
        "doel": ("Plafondanker (positieve controle): echte product-UI van uitzonderlijke kwaliteit die in elke "
                 "ronde bovenaan hoort te eindigen."),
        "dekking_categorie": DEKKING,
        "motivatie": MOTIVATIE,
        "onderbouwing": ONDERBOUWING,
        "onderbouwing_noot": ONDERBOUWING_NOOT,
        "gegenereerd_op": cc.nu_iso(),
        "generator": "scripts/capture_anker.py + scripts/capture_controle.py",
        "leesvoorbeeld": cc.leesvoorbeeld("manifest['bestanden'] (een lijst opnamerecords: elk anker x 2 viewports); "
                                          "manifest['ankers'] noemt de bronnen"),
        "ankers": [{"id": a["id"], "bron_naam": a["bron_naam"], "url": a["url"]} for a in ANKERS],
        "bestanden": records,
    }
    cc.schrijf_json(MANIFEST, manifest)
    ok = sum(1 for r in records if r["geladen_ok"])
    print(f"\n{ok}/{len(records)} opnames geladen_ok -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
