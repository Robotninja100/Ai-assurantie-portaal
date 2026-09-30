#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_comps.py - reproduceerbare capture van INTERNATIONALE design-comps.

Legt per bron twee full-page opnames vast:
  <id>_1440.png  (desktop, 1440x900, deviceScaleFactor 2)
  <id>_390.png   (mobiel,  390x844,  deviceScaleFactor 2)
Uitvoer: renders/comps/ + manifest.json (een LIJST van opnamerecords; schema en
afkeurregels: zie scripts/capture_controle.py).

Wat er sinds de meetlat-audit anders is
---------------------------------------
* Elke opname wordt na afloop objectief gemeten (te leeg, cookiewall/modal, foutpagina,
  botmuur, lege banden). `geladen_ok` volgt uit die meting; afgekeurde PNG's gaan naar
  renders/comps/_afgekeurd/ en blijven in het manifest MET reden.
* `wat_het_toont` is de tekst die de opnemer na inspectie van de opname heeft vastgesteld,
  niet wat het bedrijf verkoopt. Elke bron heeft een `klasse`: product_ui of marketing.
* Cookies: er wordt alleen geklikt als de DOM een blokkerende overlay laat zien, en het
  manifest zegt alleen 'geklikt' als de overlay daarna aantoonbaar weg was (gemeten).
* Een HTTP-fout (403/429/407) of tunnelfout wordt gerespecteerd: die bron wordt overgeslagen
  en gemeld, niet opnieuw geprobeerd of omzeild. Tussen ladingen zit een pauze.

Gebruik
-------
  python3 scripts/capture_comps.py                       # alles vastleggen
  python3 scripts/capture_comps.py linear_docs           # selectie op id
  python3 scripts/capture_comps.py --alleen-manifest     # manifest herbouwen zonder netwerk

Omgeving (gesandboxte container): browsers in PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers (NOOIT
`playwright install`); uitgaand HTTPS via $HTTPS_PROXY; de proxy verdraagt Chromium's TLS 1.3
niet, daarom --ssl-version-max=tls1.2. Certificaatverificatie blijft AAN.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture_controle as cc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "renders" / "comps"
MANIFEST = OUT_DIR / "manifest.json"

DEKKING = ("Internationale web-interfaces (documentatie-apps, dashboards, boekingsflow, "
           "catalogi). Geen enkele is een ingelogd Nederlands assurantie-backoffice of een "
           "Nederlandse financiele interface; deze set is alleen een algemene kwaliteitsmaatstaf, "
           "geen vertegenwoordiger van de categorie waarin het product valt.")

# ---------------------------------------------------------------------------
# Bronnen. `klasse`, `soort_scherm` en `wat_het_toont` zijn het OORDEEL van de opnemer na
# het bekijken van de opname (`geinspecteerd_op`), niet wat de site zichzelf noemt.
# Ontbreekt `wat_het_toont`, dan is de bron nog niet geinspecteerd en telt hij niet mee.
# ---------------------------------------------------------------------------
CANDIDATES: list[dict] = [
    {"id": "linear_docs", "bron_naam": "Linear", "url": "https://linear.app/docs", "wait_ms": 3500},
    {"id": "linear_product", "bron_naam": "Linear", "url": "https://linear.app/", "wait_ms": 5000},
    {"id": "vercel_geist", "bron_naam": "Vercel (Geist)", "url": "https://vercel.com/geist/introduction", "wait_ms": 4000},
    {"id": "vercel_templates", "bron_naam": "Vercel", "url": "https://vercel.com/templates", "wait_ms": 4500},
    {"id": "attio_crm", "bron_naam": "Attio", "url": "https://attio.com/", "wait_ms": 5000},
    {"id": "attio_help", "bron_naam": "Attio", "url": "https://attio.com/help/reference/attio-101", "wait_ms": 4000},
    {"id": "mercury_banking", "bron_naam": "Mercury", "url": "https://mercury.com/", "wait_ms": 5000},
    {"id": "ramp_finance", "bron_naam": "Ramp", "url": "https://ramp.com/", "wait_ms": 5000},
    {"id": "retool_components", "bron_naam": "Retool", "url": "https://docs.retool.com/apps/reference/components", "wait_ms": 3500,
     # onboarding-tooltip ("New here? ... Got it") wegklikken; dit is een tip, geen consent, login of betaalmuur
     "stappen": [{"click": "button:has-text('Got it')"}, {"wait": 800}]},
    {"id": "metabase_docs", "bron_naam": "Metabase", "url": "https://www.metabase.com/docs/latest/", "wait_ms": 3500},
    {"id": "grafana_play_dashboard", "bron_naam": "Grafana Play",
     "url": "https://play.grafana.org/d/lAoEVhD7z/home-kubernetes-integration", "wait_ms": 8000},
    {"id": "cal_com_booking", "bron_naam": "Cal.com", "url": "https://cal.com/rick/get-rick-rolled", "wait_ms": 6000},
    {"id": "notion_public_page", "bron_naam": "Notion",
     "url": "https://www.notion.so/notion/Notion-Official-83715d7703ee4b8699b5e659a4712dd8", "wait_ms": 8000},
    {"id": "notion_templates", "bron_naam": "Notion", "url": "https://www.notion.com/templates", "wait_ms": 5000},
    {"id": "resend_product", "bron_naam": "Resend", "url": "https://resend.com/", "wait_ms": 5000},
    {"id": "dub_analytics", "bron_naam": "Dub", "url": "https://dub.co/", "wait_ms": 5000},
    {"id": "stripe_checkout", "bron_naam": "Stripe", "url": "https://stripe.com/payments/checkout", "wait_ms": 5000},
    # --- toegevoegd na de audit: publiek toegankelijke ECHTE interfaces (geen account, geen login) ---
    {"id": "plausible_live_demo", "bron_naam": "Plausible Analytics",
     "url": "https://plausible.io/plausible.io", "wait_ms": 6000},
    {"id": "openproject_community", "bron_naam": "OpenProject Community",
     "url": "https://community.openproject.org/projects/openproject/work_packages", "wait_ms": 7000},
    {"id": "trello_roadmap_bord", "bron_naam": "Trello",
     "url": "https://trello.com/b/nC8QJJoZ/trello-development-roadmap", "wait_ms": 15000},
    {"id": "tableau_public_discover", "bron_naam": "Tableau Public",
     "url": "https://public.tableau.com/app/discover", "wait_ms": 7000},
    {"id": "datasette_demo", "bron_naam": "Datasette",
     "url": "https://latest.datasette.io/fixtures/facetable", "wait_ms": 3000},
    {"id": "actual_budget_demo", "bron_naam": "Actual Budget",
     "url": "https://demo.actualbudget.org/", "wait_ms": 5000,
     "stappen": [{"click": "button:has-text('Try the demo')"}, {"wait": 8000},
                 {"click": "button[aria-label='Close']"}, {"wait": 800}],   # sluit de welkomsttoast
     "toegang": "publieke demo; draait lokaal in de browser; geen account, geen server, geen voorwaarden"},
    # Odoo: de publieke demo-dienst maakt zelf een sandbox-sessie aan (geen account, geen inloggegevens
    # ingevoerd, geen voorwaarden geaccepteerd). Per lading een nieuwe demodatabase: daarom maar twee schermen.
    {"id": "odoo_demo_crm", "bron_naam": "Odoo", "url": "https://demo.odoo.com", "wait_ms": 9000,
     "stappen": [{"click": "a.o_app:has-text('CRM')"}, {"wait": 5000}],
     "toegang": "publieke sandbox-demo (demo.odoo.com); sessie door de dienst automatisch aangemaakt; geen account, geen inloggegevens, geen voorwaarden"},
    {"id": "odoo_demo_contacts", "bron_naam": "Odoo", "url": "https://demo.odoo.com", "wait_ms": 9000,
     "stappen": [{"click": "a.o_app:has-text('Contacts')"}, {"wait": 5000}],
     "toegang": "publieke sandbox-demo (demo.odoo.com); sessie door de dienst automatisch aangemaakt; geen account, geen inloggegevens, geen voorwaarden"},
]

for _c in CANDIDATES:
    _c.setdefault("domein", "internationaal")
    _c.setdefault("taal", "en")
    _c.setdefault("dekking_categorie", DEKKING)

# ---------------------------------------------------------------------------
# Oordeel van de opnemer na het bekijken van de opnames (desktop en mobiel), 2026-09-29.
#   product_ui  scherm waarin je iets opzoekt of doet met echte bediening (app, dashboard, dataviewer,
#               boekingsflow, documentatie-interface). Een `soort_scherm` "docs" is echte UI maar geen
#               bedieningsscherm: filter daarop voor een strikte ronde.
#   marketing   pagina om te informeren, te verkopen of naar een login te leiden (homepage, productpagina,
#               galerij-landing), ook als er een mockup, screenshot of zoekveld in zit: een mockup is een
#               illustratie en geen bruikbare interface.
# De tekst beschrijft wat IN BEELD staat, ook bij afgekeurde opnames (die staan met reden in
# `afkeurredenen`). Bronnen zonder oordeel zijn niet geinspecteerd en tellen niet mee.
# ---------------------------------------------------------------------------
GEINSPECTEERD_OP = "2026-09-29"
BEOORDELING: dict[str, dict] = {
    "linear_docs": dict(klasse="product_ui", soort_scherm="docs", wat_het_toont=(
        "Linear Docs (linear.app/docs), donker thema: documentatieportaal met boomnavigatie links, kop 'Linear "
        "Docs' en twee kaartenrasters ('Popular', 'Linear basics') met icoon, titel en een regel uitleg. "
        "Documentatie-interface; geen productscherm.")),
    "linear_product": dict(klasse="marketing", soort_scherm="marketing_home", wat_het_toont=(
        "Linear-homepage (linear.app): donkere marketingpagina met de kop 'The product development system for "
        "teams and agents', navigatie, knoppen en een ingesloten mockup van de app in de hero. De mockup is een "
        "illustratie, geen bruikbare interface.")),
    "vercel_geist": dict(klasse="product_ui", soort_scherm="docs", wat_het_toont=(
        "Vercel Geist Design System (vercel.com/geist/introduction): documentatie van het designsysteem met "
        "zijbalknavigatie (Foundations, Components, ...), introductietekst en voorbeeldtegels (Brand Assets, "
        "Icons, Components, Colors, Grid, Typeface). Documentatie-interface, geen app.")),
    "vercel_templates": dict(klasse="product_ui", soort_scherm="catalogus", wat_het_toont=(
        "Vercel Templates ('Find your Template'): zoekveld, facetfilters links en een kaartenraster met "
        "sjablonen. Alleen de eerste rijen kaarten zijn gerenderd; daaronder blijven grote vlakken leeg "
        "(lazy-loading kwam niet op gang), daarom afgekeurd.")),
    "attio_crm": dict(klasse="marketing", soort_scherm="marketing_home", wat_het_toont=(
        "Attio-homepage (attio.com): marketingpagina 'Welcome to agentic revenue' met een mockup van de app en "
        "klantlogo's. Op desktop blijven scrollgeanimeerde secties leeg (afgekeurd); mobiel is de pagina "
        "gevuld.")),
    "attio_help": dict(klasse="product_ui", soort_scherm="docs", wat_het_toont=(
        "Attio Help Center, artikel 'Attio 101': documentatie-interface met zoekveld en boomnavigatie links, "
        "artikelkop en een genummerde lijst onderwerpen met grijze plaatshouders voor afbeeldingen. Geen "
        "CRM-scherm.")),
    "mercury_banking": dict(klasse="marketing", soort_scherm="marketing_home", wat_het_toont=(
        "Mercury-homepage (mercury.com): marketingpagina met fotohero 'Radically different banking', "
        "aanmeldveld en een ingesloten mockup van een rekeningoverzicht. De mockup is een illustratie.")),
    "ramp_finance": dict(klasse="marketing", soort_scherm="marketing_home", wat_het_toont=(
        "Ramp-homepage (ramp.com): marketingpagina 'Time is money. Save both.' met klantlogo's, productkaarten en "
        "productmockups. De site levert per lading wisselend de echte pagina, een Markdown-'Machine Version' als "
        "platte tekst of een nieuwsbriefvenster met schermdimming: bij de laatste lading was mobiel de echte "
        "pagina en desktop de platte tekst (afgekeurd). Niet omzeild of herhaald.")),
    "retool_components": dict(klasse="product_ui", soort_scherm="docs", wat_het_toont=(
        "Retool Docs, 'Classic apps component reference': documentatie met zijbalkboom, broodkruimel, "
        "waarschuwingsbox en een kaartenraster met componenten (Alert, Button Group, ...), plus een vaste "
        "onderbalk (Version, Domain, Status, Ask AI). Documentatie-interface.")),
    "metabase_docs": dict(klasse="product_ui", soort_scherm="docs", wat_het_toont=(
        "Metabase-documentatie (metabase.com/docs/latest): docs-portaal met kopnavigatie, zijbalkboom, titel, een "
        "afbeelding van een Metabase-dashboard in de artikeltekst en rechts 'On this page'. Het dashboard is een "
        "screenshot in het artikel, niet de app zelf.")),
    "grafana_play_dashboard": dict(klasse="product_ui", soort_scherm="dashboard", wat_het_toont=(
        "Grafana Play (play.grafana.org), live publieke instantie: Kubernetes-integratiedashboard in donker "
        "thema met navigatiezijbalk, variabelenbalk (data source, cluster, instance), tegels (Kubelet, "
        "kube-state-metrics, ...), stat-panelen (Running pods 79, Running containers 138), een dashboardlijst en "
        "een paneel met 'No data'. Echte app-omgeving zonder inlog.")),
    "cal_com_booking": dict(klasse="product_ui", soort_scherm="boekingsflow", wat_het_toont=(
        "Cal.com publieke boekingspagina (cal.com/rick/get-rick-rolled): gecentreerde kaart met profiel, "
        "maandkalender (september 2026) en lijst met tijdsloten. Echte boekingsflow met veel witruimte rondom; "
        "geen account nodig.")),
    "notion_public_page": dict(klasse="product_ui", soort_scherm="document", wat_het_toont=(
        "Notion publieke pagina 'Notion Official': titel met icoon en vijf linkregels (What's New?, Careers at "
        "Notion, ...); circa 240 zichtbare tekens. Echte Notion-lezer, maar zo schaars dat er niets te "
        "vergelijken valt; afgekeurd (te_weinig_tekst).")),
    "notion_templates": dict(klasse="marketing", soort_scherm="galerij_landing", wat_het_toont=(
        "Notion Marketplace-startpagina (notion.com/templates): kop 'Discover', zoekveld, promotieblok 'Work "
        "smarter with Notion experts', uitgelichte makers, categorietegels en consultants. Promotiegedreven "
        "startpagina; het zoekveld is het enige interactieve element.")),
    "resend_product": dict(klasse="marketing", soort_scherm="marketing_home", wat_het_toont=(
        "Resend-homepage (resend.com): donkere marketingpagina 'Email for developers' met knoppen, "
        "klantlogo's en een 3D-illustratie. Geen productscherm.")),
    "dub_analytics": dict(klasse="marketing", soort_scherm="marketing_home", wat_het_toont=(
        "Dub-homepage (dub.co): marketingpagina 'Turn clicks into revenue' met navigatie, knoppen, een "
        "productmockup en klantlogo's. De mockup is een illustratie.")),
    "stripe_checkout": dict(klasse="marketing", soort_scherm="productpagina", wat_het_toont=(
        "Stripe Checkout-productpagina (stripe.com/payments/checkout): marketingpagina 'We built Checkout so "
        "you don't have to' met een betaalscherm-mockup en promotiesecties.")),
    "plausible_live_demo": dict(klasse="product_ui", soort_scherm="dashboard", wat_het_toont=(
        "Plausible Analytics, publiek dashboard van plausible.io (laatste 28 dagen): KPI-rij (unique visitors, "
        "total visits, pageviews, views per visit, bounce rate, visit duration), lijngrafiek, tabbladen "
        "Channels/Sources/Campaigns, Top Pages, landenkaart en browsers. Echte app-omgeving zonder inlog.")),
    "openproject_community": dict(klasse="product_ui", soort_scherm="app", wat_het_toont=(
        "OpenProject Community (publiek project): werkpakkettenlijst 'All open' met zijbalk, "
        "knoppenbalk (Create, Include projects, Baseline, Filter) en een dichte tabel (ID, onderwerp, type, "
        "status, verantwoordelijke) met paginering. Echte app-omgeving zonder inlog.")),
    "trello_roadmap_bord": dict(klasse="product_ui", soort_scherm="bord", wat_het_toont=(
        "Publiek Trello-ontwikkelbord: alleen de kopbalk (Trello, Log in, Get Trello for free) is gerenderd; het "
        "bord zelf bleef ook na 15 s wachten leeg (mobiel: een paars venster 'Trello is better on the mobile "
        "app'). Afgekeurd.")),
    "tableau_public_discover": dict(klasse="marketing", soort_scherm="galerij_landing", wat_het_toont=(
        "Tableau Public 'Discover': landingspagina met kop 'Discover Tableau Public', zoekveld, 'Viz of the "
        "Day' en een galerij met visualisaties en extensies. Galerij- en landingspagina, geen bewerkbare "
        "interface.")),
    "datasette_demo": dict(klasse="product_ui", soort_scherm="dataviewer", wat_het_toont=(
        "Datasette-demo (latest.datasette.io, tabel 'facetable'): kale data-interface met filterformulier, "
        "tabel van 15 rijen, facetsuggesties, exportopties en het SQL-schema. Functioneel maar eenvoudig "
        "vormgegeven.")),
    "actual_budget_demo": dict(klasse="product_ui", soort_scherm="app", wat_het_toont=(
        "Actual Budget publieke demo (demo.actualbudget.org, lokale testbegroting): financiele app met donkere "
        "zijbalk (rekeningen met saldo's), maandkeuze bovenin, samenvattingsblok 'To Budget' en een "
        "begrotingstabel per categorie (Budgeted, Spent, Balance).")),
    "odoo_demo_crm": dict(klasse="product_ui", soort_scherm="app", wat_het_toont=(
        "Odoo CRM in de publieke sandbox-demo: pipeline-kanban met vier fases (New, Qualified, Proposition, "
        "Won), bedragen per fase, kaarten met klant, sterren, tags en acties; zoekbalk en weergaveschakelaars. "
        "Echte backoffice-ERP-omgeving (Engels, niet assurantie).")),
    "odoo_demo_contacts": dict(klasse="product_ui", soort_scherm="app", wat_het_toont=(
        "Odoo Contacten in de publieke sandbox-demo: lijstweergave met zoekbalk, weergaveschakelaars, "
        "paginering (1-80 van 163) en tabel (naam, e-mail, telefoon, activiteiten, land) met avatars en "
        "tellers. Echte backoffice-ERP-omgeving (Engels, niet assurantie).")),
}
for _c in CANDIDATES:
    if _c["id"] in BEOORDELING:
        _c.update(BEOORDELING[_c["id"]])
        _c.setdefault("geinspecteerd_op", GEINSPECTEERD_OP)


def bestandsnaam(cand: dict, viewport_naam: str) -> str:
    return f'{cand["id"]}_{"1440" if viewport_naam == "desktop" else "390"}.png'


def _kaart(cand: dict) -> dict:
    kaart = dict(cand)
    kaart["_concept"] = not cand.get("wat_het_toont")
    return kaart


def _lees_vorig() -> dict[tuple[str, str], dict]:
    if not MANIFEST.exists():
        return {}
    try:
        return {(e["id"], e["viewport_naam"]): e for e in cc.lees_opnames(MANIFEST)}
    except Exception:
        return {}


def leg_bron_vast(browser, cand: dict, pauze: float) -> list[dict]:
    """Beide viewports van een bron; slaat over bij HTTP-fout of geblokkeerde host."""
    kaart = _kaart(cand)
    geblokkeerd = cc.host_geblokkeerd(cand["url"])
    if geblokkeerd:
        return [cc.record_zonder_bestand(kaart=kaart, viewport_naam=vp, reden=geblokkeerd,
                                         codes=["bekend_geblokkeerd"]) for vp in cc.VIEWPORT_NAMEN]
    records: list[dict] = []
    for i, vp in enumerate(cc.VIEWPORT_NAMEN):
        if i:
            time.sleep(cc.PAUZE_TUSSEN_LADINGEN_S)
        bestand = bestandsnaam(cand, vp)
        t0 = time.time()
        raw = cc.leg_vast(browser, kaart, vp, OUT_DIR, bestand,
                          wacht_ms=cand.get("wait_ms", 3000), stappen=cand.get("stappen"))
        if not (OUT_DIR / bestand).exists():
            # geen PNG: fout of HTTP-status gerespecteerd, mobiele lading overslaan
            reden = raw.get("fout") or "geen opname gemaakt"
            code = "http_" + reden.split()[-1] if reden.startswith("HTTP") else "capture_mislukt"
            for vp2 in cc.VIEWPORT_NAMEN[i:]:
                records.append(cc.record_zonder_bestand(kaart=kaart, viewport_naam=vp2, reden=reden, codes=[code]))
            print(f"SKIP {bestand:<44} {reden}", flush=True)
            return records
        rec = cc.bouw_record(kaart=kaart, viewport_naam=vp, bestand=bestand, map_pad=OUT_DIR, raw=raw)
        rec["duur_s"] = round(time.time() - t0, 1)
        records.append(rec)
        print(f'{"OK  " if rec["geladen_ok"] else "AFK "} {rec["bestand"]:<44} '
              f'{",".join(rec["afkeurredenen"]) or "schoon"}', flush=True)
    return records


def herbouw_bron(cand: dict, vorig: dict[tuple[str, str], dict]) -> list[dict]:
    """--alleen-manifest: herbereken de regels uit de opgeslagen DOM-feiten en de PNG's."""
    kaart = _kaart(cand)
    out: list[dict] = []
    for vp in cc.VIEWPORT_NAMEN:
        oud = vorig.get((cand["id"], vp))
        bestand = bestandsnaam(cand, vp)
        if oud is None:
            continue
        if not (OUT_DIR / bestand).exists() and not (OUT_DIR / cc.AFGEKEURD_MAP / bestand).exists():
            # was overgeslagen: regel behouden, classificatie verversen
            oud = dict(oud)
            for k in ("bron_naam", "url", "dekking_categorie"):
                oud[k] = kaart.get(k)
            out.append(oud)
            continue
        out.append(cc.bouw_record(kaart=kaart, viewport_naam=vp, bestand=bestand, map_pad=OUT_DIR,
                                  raw=cc.raw_uit_record(oud)))
    return out


def schrijf_manifest(nieuw: list[dict], alle_ids: list[str]) -> list[dict]:
    """Voegt nieuwe regels samen met de bestaande (deel-run) en schrijft de lijstvorm."""
    samen = {(e["id"], e["viewport_naam"]): e for e in _lees_vorig().values()}
    for e in nieuw:
        samen[(e["id"], e["viewport_naam"])] = e
    volgorde = {i: n for n, i in enumerate(alle_ids)}
    rijen = sorted(samen.values(), key=lambda e: (volgorde.get(e["id"], 999),
                                                  0 if e["viewport_naam"] == "desktop" else 1))
    rijen = [e for e in rijen if e["id"] in volgorde]        # bronnen die niet meer bestaan laten vallen
    cc.schrijf_json(MANIFEST, rijen)
    return rijen


def samenvatting(rijen: list[dict]) -> None:
    ok = [e for e in rijen if e["geladen_ok"]]
    print(f"\nmanifest: {len(ok)}/{len(rijen)} opnames geladen_ok  -> {MANIFEST}")
    for e in rijen:
        if not e["geladen_ok"]:
            print(f"  afgekeurd: {e['id']:<28} {e['viewport_naam']:<8} {e.get('afkeurreden', '')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture internationale comps met naharde controle")
    ap.add_argument("ids", nargs="*", help="alleen deze bron-id's")
    ap.add_argument("--alleen-manifest", action="store_true", help="geen netwerk: herbereken het manifest")
    ap.add_argument("--pauze", type=float, default=4.0, help="seconden pauze tussen bronnen")
    args = ap.parse_args()

    wanted = set(args.ids)
    todo = [c for c in CANDIDATES if not wanted or c["id"] in wanted]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    alle_ids = [c["id"] for c in CANDIDATES]

    nieuw: list[dict] = []
    if args.alleen_manifest:
        vorig = _lees_vorig()
        for cand in todo:
            nieuw += herbouw_bron(cand, vorig)
    else:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = cc.start_browser(pw)
            for n, cand in enumerate(todo):
                if n:
                    time.sleep(args.pauze)
                nieuw += leg_bron_vast(browser, cand, args.pauze)
            browser.close()
    samenvatting(schrijf_manifest(nieuw, alle_ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
