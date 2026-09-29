#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_ours.py - legt onze EIGEN schermen vast voor de blinde A/B-meetlat (renders/ours/).

Elk scherm komt uit een echte run tegen een draaiende server: het formulier wordt met het voorbeeld
gevuld, de toets wordt uitgevoerd en pas als het resultaat er echt staat (inclusief de controle van
verwijzingen) wordt de opname gemaakt. Staat er een storingsmelding, dan geldt de opname als mislukt
(geladen_ok = false) en gaat hij niet mee in een ronde: een scherm waarop 'geen antwoord van het
taalmodel' staat meet de runtime, niet het ontwerp.

Het manifest volgt het contract van de meetlat: klasse, domein, taal, geladen_ok, controle,
wat_het_toont. Bestandsnamen verraden niets; het harnas hernoemt ze toch naar A, B, C.

Gebruik:
  python3 scripts/capture_ours.py --basis http://127.0.0.1:8000 [--schermen overzicht,schadeberekening]
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = os.environ.get("PLAYWRIGHT_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

# Zes structureel verschillende schermen: overzicht, twee berekende resultaten (bedrag, tijdlijn), twee
# bronnengedreven resultaten (clausules, uitspraken) en de twee-kolomsvergelijking.
SCHERMEN = [
    {"id": "overzicht", "route": "/", "run": False,
     "toont": "Overzichtspagina van een Nederlandse assurantie-applicatie met drie uitgangspunten, twaalf functies in vier groepen en de corpusstatus."},
    {"id": "schadeberekening", "route": "/f/schadeberekening", "run": True,
     "toont": "Schadeberekening met invoer, heldgetal, verhoudingsbalk, rekenstappen, wettelijke grondslag, gestreamde toelichting en citeercontrole."},
    {"id": "verjaringstoets", "route": "/f/verjaringstoets", "run": True,
     "toont": "Verjaringstoets met oordeelkaart, tijdlijn van gebeurtenissen, rekenstappen, toelichting en citeercontrole."},
    {"id": "dekkingscheck", "route": "/f/dekkingscheck", "run": True, "open_bron": True,
     "toont": "Dekkingscheck met bronnenlijst per soort, uitgeklapt fragment, gestreamde toelichting met verwijzingschips en citeercontrole."},
    {"id": "precedentzoeker", "route": "/f/precedentzoeker", "run": True,
     "toont": "Kifid-precedentzoeker met verdelingsbalk van uitkomsten, uitspraaklijst, toelichting en citeercontrole."},
    {"id": "polisvergelijker", "route": "/f/polisvergelijker", "run": True,
     "toont": "Polisvergelijker met twee varianten naast elkaar, toelichting en citeercontrole."},
]
VIEWPORTS = {"desktop": (1440, 900), "mobile": (390, 844)}
KLAAR = ".sectie:has-text('Controle van verwijzingen'), .melding.fout"


def draai(basis, schermen, uit, wacht_sec):
    from playwright.sync_api import sync_playwright
    os.makedirs(uit, exist_ok=True)
    manifest = []
    with sync_playwright() as p:
        # Nederlandse taal voor de browser zelf: anders tonen datumvelden mm/dd/jjjj.
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox", "--lang=nl"],
                                    env={**os.environ, "LANGUAGE": "nl", "LANG": "nl_NL.UTF-8"})
        for sch in schermen:
            for vp, (b, h) in VIEWPORTS.items():
                ctx = browser.new_context(viewport={"width": b, "height": h}, device_scale_factor=2, locale="nl-NL")
                pg = ctx.new_page()
                fouten = []
                pg.on("pageerror", lambda e: fouten.append(str(e)))
                pg.on("console", lambda m: fouten.append(m.text) if m.type == "error" else None)
                bestand = f"scherm-{sch['id']}-{b}.png"
                rec = {"bestand": bestand, "bron_naam": f"eigen-{sch['id']}", "viewport": vp, "klasse": "ours",
                       "domein": "ours", "taal": "nl", "wat_het_toont": sch["toont"], "geladen_ok": False,
                       "controle": {}}
                t0 = time.time()
                try:
                    pg.goto(f"{basis}/#{sch['route']}")
                    pg.wait_for_selector("h1", timeout=15000)
                    if sch["run"]:
                        pg.click("text=Voorbeeld invullen")
                        pg.click("button[type=submit]")
                        pg.wait_for_selector(KLAAR, timeout=wacht_sec * 1000)
                        storing = pg.locator(".melding.fout").count()
                        rec["controle"]["storing_zichtbaar"] = storing > 0
                        rec["controle"]["model"] = (pg.locator(".sectie-meta", has_text="Geschreven door").first.inner_text()
                                                    if pg.locator(".sectie-meta", has_text="Geschreven door").count() else None)
                        if sch.get("open_bron") and pg.locator(".bron-rij").count():
                            pg.locator(".bron-rij").first.click()
                    pg.wait_for_timeout(500)
                    pg.evaluate("window.scrollTo(0, 0)")
                    pg.wait_for_timeout(200)
                    pg.screenshot(path=os.path.join(uit, bestand), full_page=True)
                    rec["controle"].update({"console_fouten": fouten, "duur_sec": round(time.time() - t0, 1),
                                            "horizontaal_scrollen": pg.evaluate(
                                                "document.documentElement.scrollWidth > document.documentElement.clientWidth")})
                    rec["geladen_ok"] = (not rec["controle"].get("storing_zichtbaar")) and not fouten \
                        and not rec["controle"]["horizontaal_scrollen"]
                except Exception as e:  # noqa: BLE001
                    rec["controle"]["fout"] = f"{type(e).__name__}: {e}"
                ctx.close()
                manifest.append(rec)
                print(f"{'OK ' if rec['geladen_ok'] else 'MIS'} {bestand} {rec['controle'].get('duur_sec', '')}s", flush=True)
        browser.close()
    with open(os.path.join(uit, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"set": "ours", "doel": "Eigen schermen voor de blinde A/B-meetlat; elke run is echt uitgevoerd.",
                   "gegenereerd_op": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "basis": basis, "comps": manifest,
                   "bestanden": manifest}, f, ensure_ascii=False, indent=2)
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--basis", default="http://127.0.0.1:8000")
    ap.add_argument("--uit", default=os.path.join(ROOT, "renders", "ours"))
    ap.add_argument("--schermen", help="kommagescheiden ids; standaard alle")
    ap.add_argument("--wacht-sec", type=int, default=1200, help="hoe lang op het taalmodel wachten per run")
    a = ap.parse_args()
    keuze = [s for s in SCHERMEN if not a.schermen or s["id"] in a.schermen.split(",")]
    if not keuze:
        print("Geen scherm gekozen.", file=sys.stderr)
        return 2
    m = draai(a.basis.rstrip("/"), keuze, a.uit, a.wacht_sec)
    slecht = [r["bestand"] for r in m if not r["geladen_ok"]]
    if slecht:
        print(f"\n{len(slecht)} opname(n) niet bruikbaar voor de meetlat: {', '.join(slecht)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
