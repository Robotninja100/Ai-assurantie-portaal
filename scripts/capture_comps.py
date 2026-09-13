#!/usr/bin/env python3
"""
capture_comps.py - Reproduceerbare capture van design-comps (referentie-interfaces)
voor het AI-assurantieportaal.

Legt per bron twee screenshots vast:
  <id>_1440.png  (desktop, 1440x900, deviceScaleFactor 2)
  <id>_390.png   (mobiel,  390x844,  deviceScaleFactor 2)

Uitvoer: renders/comps/  + manifest.json

Gebruik:
  python3 scripts/capture_comps.py            # alles
  python3 scripts/capture_comps.py stripe_api linear_docs   # selectie

Omgeving (dit is een gesandboxte container):
  - Browsers staan in PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers ; NOOIT `playwright install` draaien.
  - Uitgaand HTTPS loopt via de agent-proxy op $HTTPS_PROXY.
  - De egress-proxy termineert TLS opnieuw en verdraagt geen TLS 1.3 ClientHello van
    Chromium (verbinding wordt hard gereset). Daarom --ssl-version-max=tls1.2.
    Certificaatverificatie blijft AAN (de proxy-CA zit in de systeem/NSS-store).
"""

import json
import os
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

# --- paden ---------------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "renders" / "comps"
MANIFEST = OUT_DIR / "manifest.json"

CHROME = os.environ.get(
    "COMPS_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
)
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

VIEWPORTS = {
    "1440": {"width": 1440, "height": 900},
    "390": {"width": 390, "height": 844},
}
DEVICE_SCALE = 2
MAX_PAGE_PX = 10000  # veiligheidsplafond voor extreem lange marketingpagina's

# --- bronnen -------------------------------------------------------------
# Criterium: de pagina moet een ECHTE productinterface tonen (tabel, dashboard,
# detailweergave, formulier, component-gallerij), geen kale marketing-hero.
CANDIDATES = [
    {
        "id": "stripe_api_docs",
        "bron_naam": "Stripe",
        "url": "https://docs.stripe.com/api",
        "wat_het_toont": "Live API-referentie: driekolomsinterface met scrollbare navigatieboom, "
                         "parameter-detailweergave en code-paneel. Maatlat voor dichte, rustige "
                         "informatiehierarchie.",
        "wait_ms": 4000,
    },
    {
        "id": "linear_docs",
        "bron_naam": "Linear",
        "url": "https://linear.app/docs",
        "wat_het_toont": "Linear docs-app: sidebar-navigatie, kaartenraster en typografische schaal "
                         "van het echte Linear-designsysteem.",
        "wait_ms": 3500,
    },
    {
        "id": "linear_product",
        "bron_naam": "Linear",
        "url": "https://linear.app/",
        "wat_het_toont": "Linear productpagina met ingebouwde, echte issue-lijst/board-UI: "
                         "rijdichtheid, statusiconen, subtiele randen op donkere achtergrond.",
        "wait_ms": 5000,
    },
    {
        "id": "vercel_geist",
        "bron_naam": "Vercel (Geist Design System)",
        "url": "https://vercel.com/geist/introduction",
        "wat_het_toont": "Geist designsysteem: live componentgallerij met sidebar, tokens en "
                         "interactieve voorbeelden - het interfacevocabulaire van Vercel zelf.",
        "wait_ms": 4000,
    },
    {
        "id": "vercel_templates",
        "bron_naam": "Vercel",
        "url": "https://vercel.com/templates",
        "wat_het_toont": "Echte app-achtige catalogusinterface: facetfilters in de sidebar, "
                         "kaartenraster, zoekveld. Model voor onze bibliotheek-/overzichtschermen.",
        "wait_ms": 4500,
    },
    {
        "id": "attio_crm",
        "bron_naam": "Attio",
        "url": "https://attio.com/",
        "wat_het_toont": "Attio CRM-interface: spreadsheet-achtige recordtabellen, kolomtypes en "
                         "record-detailweergave. Directe maatlat voor onze relatie-/polisoverzichten. "
                         "LET OP: scroll-geanimeerd - enkele desktopsecties blijven leeg in een statische capture; zie attio_help.",
        "wait_ms": 5000,
    },
    {
        "id": "attio_help",
        "bron_naam": "Attio",
        "url": "https://attio.com/help/reference/attio-101",
        "wat_het_toont": "Attio helpcentrum-app: sidebar-navigatie, artikeldetail en ingebedde "
                         "schermafbeeldingen van de echte CRM-tabellen en recordweergaven. "
                         "Rendert statisch, dus betrouwbaarder dan de scroll-geanimeerde homepage.",
        "wait_ms": 4000,
    },
    {
        "id": "mercury_banking",
        "bron_naam": "Mercury",
        "url": "https://mercury.com/",
        "wat_het_toont": "Mercury banking-UI: saldodashboard, transactietabel en kaartdetail. "
                         "Financieel-professionele toon met veel witruimte.",
        "wait_ms": 5000,
    },
    {
        "id": "ramp_finance",
        "bron_naam": "Ramp",
        "url": "https://ramp.com/",
        "wat_het_toont": "Ramp spend-management: uitgavendashboards, goedkeuringsrijen en "
                         "kaartcomponenten. Dichte financiele data, toch rustig.",
        "wait_ms": 5000,
    },
    {
        "id": "retool_components",
        "bron_naam": "Retool",
        "url": "https://docs.retool.com/apps/reference/components",
        "wat_het_toont": "Retool componentreferentie: sidebar + componentcatalogus met tabellen, "
                         "formulieren en inputs zoals ze in de builder verschijnen.",
        "wait_ms": 3500,
    },
    {
        "id": "metabase_docs",
        "bron_naam": "Metabase",
        "url": "https://www.metabase.com/docs/latest/",
        "wat_het_toont": "Metabase-documentatie-app: driekolomslayout met sectienavigatie en "
                         "in-line schermafbeeldingen van de query-/dashboardinterface.",
        "wait_ms": 3500,
    },
    {
        "id": "grafana_play_dashboard",
        "bron_naam": "Grafana Play",
        "url": "https://play.grafana.org/d/lAoEVhD7z/home-kubernetes-integration",
        "wat_het_toont": "LIVE, publiek toegankelijke Grafana-instantie (Kubernetes-dashboard): echte "
                         "panelen, tijdreeksen, stat-tegels en app-chrome - geen screenshot. "
                         "Maatlat voor dashboarddichtheid en paneelindeling.",
        "wait_ms": 8000,
    },
    {
        "id": "cal_com_booking",
        "bron_naam": "Cal.com",
        "url": "https://cal.com/rick/get-rick-rolled",
        "wat_het_toont": "LIVE boekingsinterface: agenda, tijdslot-picker en formulierflow. "
                         "Maatlat voor een uitgeleverd, minimalistisch formulier-/afspraakscherm.",
        "wait_ms": 6000,
    },
    {
        "id": "notion_public_page",
        "bron_naam": "Notion",
        "url": "https://www.notion.so/notion/Notion-Official-83715d7703ee4b8699b5e659a4712dd8",
        "wat_het_toont": "LIVE publieke Notion-pagina, gerenderd in de echte Notion-reader: "
                         "documentopmaak, blokken en typografie van het product zelf.",
        "wait_ms": 8000,
    },
    {
        "id": "notion_templates",
        "bron_naam": "Notion",
        "url": "https://www.notion.com/templates",
        "wat_het_toont": "Template-galerij: categoriefilters, zoekbalk en kaartenraster - een echte "
                         "browse-interface binnen het Notion-product.",
        "wait_ms": 5000,
    },
    {
        "id": "resend_product",
        "url": "https://resend.com/",
        "bron_naam": "Resend",
        "wat_het_toont": "Resend: e-mail-dashboard met logtabel, statusbadges en detailpaneel. "
                         "Strak, monochroom, hoge informatiedichtheid - dicht bij wat wij willen.",
        "wait_ms": 5000,
    },
    {
        "id": "dub_analytics",
        "url": "https://dub.co/",
        "bron_naam": "Dub",
        "wat_het_toont": "Dub analytics-werkblad: linktabel, filters en grafiek-/statpanelen. "
                         "Moderne, rustige SaaS-datadichtheid.",
        "wait_ms": 5000,
    },
    {
        "id": "stripe_checkout",
        "bron_naam": "Stripe",
        "url": "https://stripe.com/payments/checkout",
        "wat_het_toont": "Stripe Checkout/Elements: uitgeleverde betaalformulieren met veldstaten, "
                         "validatie en knopgedrag. Maatlat voor onze formulierdetaillering.",
        "wait_ms": 5000,
    },
]

# --- cookiebanner-opruiming ---------------------------------------------
ACCEPT_TEXTS = [
    "Accept all cookies", "Accept all", "Allow all cookies", "Allow all",
    "Accept cookies", "Accept", "I agree", "Got it", "Understood",
    "Alles accepteren", "Accepteer alles", "Alle cookies accepteren", "Akkoord",
    "Tout accepter", "Alle akzeptieren", "Zustimmen",
    "Continue",  # laatste redmiddel (o.a. Attio); de URL-bewaking vangt misklikken op
]

# Bekende consent-knoppen, exact geadresseerd - veiliger dan tekst zoeken.
KNOWN_ACCEPT_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    "#cookiescript_accept",
    "#hs-eu-confirmation-button",
    ".osano-cm-accept-all",
    "[data-testid='uc-accept-all-button']",
    "[data-cky-tag='accept-button']",
    "button[aria-label*='Accept all' i]",
    "button[aria-label*='Alles accepteren' i]",
]

HIDE_CSS = """
  /* bekende cookie-/consent-containers en chat-widgets wegblenden */
  #onetrust-consent-sdk, #onetrust-banner-sdk, .onetrust-pc-dark-filter,
  #CybotCookiebotDialog, #CybotCookiebotDialogBodyUnderlay, #cookiescript_injected,
  #usercentrics-root, #cmpbox, #cmpbox2, #hs-eu-cookie-confirmation,
  [id*="cookie-banner"], [class*="cookie-banner"], [class*="CookieBanner"],
  [id*="cookie-consent"], [class*="cookie-consent"], [class*="CookieConsent"],
  [aria-label*="cookie" i][role="dialog"], [data-testid*="cookie" i],
  .osano-cm-window, .cc-window, .truste_overlay, .truste_box_overlay,
  #hubspot-messages-iframe-container, #intercom-container, .intercom-lightweight-app,
  iframe[title*="Intercom" i], iframe[title*="Drift" i], #drift-frame-controller,
  [id*="onetrust"], [class*="gdpr" i][role="dialog"] { display: none !important; }
  html { scrollbar-width: none !important; }
  /* animaties stilzetten zodat captures deterministisch zijn */
  *, *::before, *::after {
    animation-duration: 0.001s !important;
    animation-delay: 0s !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001s !important;
    caret-color: transparent !important;
  }
"""


def dismiss_consent(page, original_url):
    """Accepteer-knoppen wegklikken.

    Alleen ECHTE knoppen (geen <a>), en na elke klik controleren we of de URL nog
    klopt. Een eerdere versie klikte per ongeluk op footerlinks als "I agree" /
    "Accept" en belandde op juridische pagina's; die bewaking voorkomt dat.
    """
    for sel in KNOWN_ACCEPT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=500):
                loc.click(timeout=1500)
                page.wait_for_timeout(600)
                return True
        except Exception:
            continue

    for txt in ACCEPT_TEXTS:
        for sel in (f'button:has-text("{txt}")', f'[role="button"]:not(a):has-text("{txt}")'):
            try:
                loc = page.locator(sel).first
                if not loc.count() or not loc.is_visible(timeout=400):
                    continue
                box = loc.bounding_box()
                if not box or box["width"] > 420:   # brede knop = waarschijnlijk geen consent-knop
                    continue
                loc.click(timeout=1500)
                page.wait_for_timeout(600)
                if page.url.rstrip("/") != original_url.rstrip("/"):
                    # verkeerde klik: terug naar de doelpagina, verder alleen CSS verbergen
                    page.goto(original_url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(1500)
                    return False
                return True
            except Exception:
                continue
    return False


KILL_OVERLAYS_JS = """
() => {
  // Verwijder overgebleven consent-/cookieoverlays die geen bekende selector hebben:
  // alleen zwevende elementen (fixed/sticky/absolute) met cookie-/consent-woordenschat.
  const re = /cookie|cookies|consent|toestemming|privacybeleid|privacy policy|we use .* to improve/i;
  let n = 0;
  for (const el of document.querySelectorAll('body *')) {
    let cs;
    try { cs = getComputedStyle(el); } catch (e) { continue; }
    if (!['fixed', 'sticky', 'absolute'].includes(cs.position)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 60 || r.height < 30) continue;
    if (r.width * r.height > window.innerWidth * window.innerHeight * 0.9) continue;
    const txt = (el.innerText || '').trim();
    if (txt.length === 0 || txt.length > 800) continue;
    if (!re.test(txt)) continue;
    el.style.setProperty('display', 'none', 'important');
    n++;
  }
  return n;
}
"""


def kill_overlays(page):
    try:
        return page.evaluate(KILL_OVERLAYS_JS)
    except Exception:
        return 0


def autoscroll(page):
    """Door de pagina scrollen zodat lazy-loaded media inlaadt, daarna terug naar boven."""
    try:
        page.evaluate(
            """async () => {
              const step = Math.max(400, window.innerHeight * 0.8);
              const max = Math.min(document.body.scrollHeight, 40000);
              for (let y = 0; y < max; y += step) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 120));
              }
              window.scrollTo(0, 0);
              await new Promise(r => setTimeout(r, 400));
            }"""
        )
    except Exception:
        pass


def page_height(page):
    try:
        return int(page.evaluate(
            "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"))
    except Exception:
        return 0


def capture(browser, cand, vp_key):
    vp = VIEWPORTS[vp_key]
    is_mobile = vp_key == "390"
    ctx = browser.new_context(
        viewport=vp,
        device_scale_factor=DEVICE_SCALE,
        is_mobile=is_mobile,
        has_touch=is_mobile,
        locale="nl-NL",
        timezone_id="Europe/Amsterdam",
        reduced_motion="reduce",
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            if is_mobile else
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
    )
    page = ctx.new_page()
    page.set_default_timeout(30000)
    rec = {
        "id": cand["id"],
        "bron_naam": cand["bron_naam"],
        "url": cand["url"],
        "viewport": f'{vp["width"]}x{vp["height"]}@{DEVICE_SCALE}x',
        "bestand": f'{cand["id"]}_{vp_key}.png',
        "wat_het_toont": cand["wat_het_toont"],
        "geladen_ok": False,
    }
    try:
        resp = page.goto(cand["url"], wait_until="domcontentloaded", timeout=60000)
        rec["http_status"] = resp.status if resp else None
        if resp and resp.status >= 400:
            rec["fout"] = f"HTTP {resp.status}"
            ctx.close()
            return rec
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(cand.get("wait_ms", 3000))

        dismiss_consent(page, cand["url"])
        page.add_style_tag(content=HIDE_CSS)
        kill_overlays(page)
        page.wait_for_timeout(400)

        autoscroll(page)
        page.add_style_tag(content=HIDE_CSS)  # opnieuw, voor laat gemounte banners
        rec["overlays_verwijderd"] = kill_overlays(page)
        page.wait_for_timeout(600)

        h = page_height(page)
        shot_path = OUT_DIR / rec["bestand"]
        if h > MAX_PAGE_PX:
            rec["afgekapt_op_px"] = MAX_PAGE_PX
            page.screenshot(path=str(shot_path), full_page=True,
                            clip={"x": 0, "y": 0, "width": vp["width"], "height": MAX_PAGE_PX})
        else:
            page.screenshot(path=str(shot_path), full_page=True)

        rec["pagina_hoogte_px"] = h
        rec["titel"] = (page.title() or "")[:120]
        rec["bestandsgrootte_bytes"] = shot_path.stat().st_size
        rec["geladen_ok"] = rec["bestandsgrootte_bytes"] > 5000
        if not rec["geladen_ok"]:
            rec["fout"] = "screenshot te klein / lege pagina"
    except Exception as exc:
        rec["fout"] = str(exc).split("\n")[0][:220]
    finally:
        try:
            ctx.close()
        except Exception:
            pass
    return rec


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wanted = set(sys.argv[1:])
    todo = [c for c in CANDIDATES if not wanted or c["id"] in wanted]

    entries = []
    launch_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        # zie docstring: de egress-proxy breekt op Chromium's TLS 1.3 handshake
        "--ssl-version-max=tls1.2",
        "--disable-features=IsolateOrigins,site-per-process",
        "--hide-scrollbars",
        "--force-color-profile=srgb",
        "--font-render-hinting=none",
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME,
            proxy={"server": PROXY} if PROXY else None,
            args=launch_args,
        )
        for cand in todo:
            for vp_key in ("1440", "390"):
                t0 = time.time()
                rec = capture(browser, cand, vp_key)
                rec["duur_s"] = round(time.time() - t0, 1)
                entries.append(rec)
                mark = "OK " if rec["geladen_ok"] else "SKIP"
                print(f'{mark} {rec["bestand"]:<38} {rec.get("fout","")}', flush=True)
        browser.close()

    # Bij een deel-run: bestaande manifest-regels behouden en alleen de opnieuw
    # vastgelegde combinaties (id + viewport) overschrijven.
    merged = {}
    if MANIFEST.exists():
        try:
            for e in json.loads(MANIFEST.read_text(encoding="utf-8")):
                merged[(e["id"], e["viewport"])] = e
        except Exception:
            pass
    for e in entries:
        merged[(e["id"], e["viewport"])] = e

    order = {c["id"]: i for i, c in enumerate(CANDIDATES)}
    rows = sorted(merged.values(),
                  key=lambda e: (order.get(e["id"], 999), 0 if "1440" in e["viewport"] else 1))
    # regels waarvan het bestand niet meer bestaat, laten we vallen
    rows = [e for e in rows if (OUT_DIR / e["bestand"]).exists()]

    MANIFEST.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for e in rows if e["geladen_ok"])
    print(f"\ndeze run: {sum(1 for e in entries if e['geladen_ok'])}/{len(entries)} geslaagd")
    print(f"manifest totaal: {ok}/{len(rows)} -> {MANIFEST}")


if __name__ == "__main__":
    main()
