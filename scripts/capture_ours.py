#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_ours.py - legt onze EIGEN schermen vast voor de blinde A/B-meetlat (renders/ours/).

Elk scherm komt uit een echte run tegen een draaiende server: het formulier wordt met het voorbeeld
gevuld, de toets wordt uitgevoerd en pas als het resultaat er echt staat wordt de opname gemaakt. Dat is
of het antwoord met de controle van verwijzingen, of (bij een berekening waarvan de uitleg uit code komt en
een lokaal model) de melding dat het model bewust niets schreef; beide zijn afgeronde toestanden van het
portaal en het manifest zegt welke het was (`controle.model_overgeslagen`). Staat er een storingsmelding,
dan geldt de opname als mislukt (geladen_ok = false) en gaat hij niet mee in een ronde: een scherm waarop
'geen antwoord van het taalmodel' staat meet de runtime, niet het ontwerp.

Eén run levert beide viewports: het scherm wordt eerst op desktopbreedte opgenomen, daarna wordt hetzelfde
venster smal gemaakt en opnieuw opgenomen. Dat scheelt de helft van de wachttijd voor het taalmodel.

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
KLAAR = (".sectie:has-text('Controle van verwijzingen'), .melding.fout, "
         ".melding.info:has-text('Geen toelichting van een taalmodel')")


def draai(basis, schermen, uit, wacht_sec):
    from playwright.sync_api import sync_playwright
    os.makedirs(uit, exist_ok=True)
    manifest = []
    with sync_playwright() as p:
        # Nederlandse taal voor de browser zelf: anders tonen datumvelden mm/dd/jjjj.
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox", "--lang=nl"],
                                    env={**os.environ, "LANGUAGE": "nl", "LANG": "nl_NL.UTF-8"})
        for sch in schermen:
            (b0, h0) = VIEWPORTS["desktop"]
            ctx = browser.new_context(viewport={"width": b0, "height": h0}, device_scale_factor=2, locale="nl-NL")
            pg = ctx.new_page()
            fouten = []
            pg.on("pageerror", lambda e: fouten.append(str(e)))
            pg.on("console", lambda m: fouten.append(m.text) if m.type == "error" else None)
            t0 = time.time()
            gedeeld = {"storing_zichtbaar": False, "model": None, "model_overgeslagen": False}
            fout = None
            try:
                pg.goto(f"{basis}/#{sch['route']}")
                pg.wait_for_selector("h1", timeout=15000)
                if sch["run"]:
                    pg.click("text=Voorbeeld invullen")
                    pg.click("button[type=submit]")
                    pg.wait_for_selector(KLAAR, timeout=wacht_sec * 1000)
                    gedeeld["storing_zichtbaar"] = pg.locator(".melding.fout").count() > 0
                    gedeeld["model_overgeslagen"] = pg.locator(".melding.info", has_text="Geen toelichting van een taalmodel").count() > 0
                    if pg.locator(".sectie-meta", has_text="Geschreven door").count():
                        gedeeld["model"] = pg.locator(".sectie-meta", has_text="Geschreven door").first.inner_text()
                    if sch.get("open_bron") and pg.locator(".bron-rij").count():
                        pg.locator(".bron-rij").first.click()
            except Exception as e:  # noqa: BLE001
                fout = f"{type(e).__name__}: {e}"
            duur = round(time.time() - t0, 1)
            for vp, (b, h) in VIEWPORTS.items():
                bestand = f"scherm-{sch['id']}-{b}.png"
                rec = {"bestand": bestand, "bron_naam": f"eigen-{sch['id']}", "viewport": vp, "viewport_naam": vp,
                       "klasse": "ours", "domein": "ours", "taal": "nl", "soort_scherm": "app/dashboard",
                       "wat_het_toont": sch["toont"], "geladen_ok": False, "controle": dict(gedeeld)}
                if fout:
                    rec["controle"]["fout"] = fout
                else:
                    try:
                        pg.set_viewport_size({"width": b, "height": h})
                        pg.wait_for_timeout(500)
                        pg.evaluate("window.scrollTo(0, 0)")
                        pg.wait_for_timeout(200)
                        pg.screenshot(path=os.path.join(uit, bestand), full_page=True)
                        scroll = pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                        rec["controle"].update({"console_fouten": list(fouten), "duur_sec": duur, "horizontaal_scrollen": scroll})
                        rec["geladen_ok"] = (not gedeeld["storing_zichtbaar"]) and not fouten and not scroll
                    except Exception as e:  # noqa: BLE001
                        rec["controle"]["fout"] = f"{type(e).__name__}: {e}"
                manifest.append(rec)
                print(f"{'OK ' if rec['geladen_ok'] else 'MIS'} {bestand} {rec['controle'].get('duur_sec', '')}s"
                      f"{' (model overgeslagen)' if gedeeld['model_overgeslagen'] else ''}", flush=True)
            ctx.close()
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
