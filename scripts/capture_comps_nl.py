#!/usr/bin/env python3
"""
Vastleggen van Nederlandse financiele/verzekerings-interfaces als comps.

Doel: een EERLIJKE meetlat. We kiezen daarom pagina's met echte
interface-elementen (formulieren, tabellen, stappenflows, resultaatlijsten)
van partijen die in NL als goed ontworpen gelden - geen stromannen.

Twee viewports per bron:
  desktop  1440x900, deviceScaleFactor 2, full page
  mobile    390x844, deviceScaleFactor 2, full page

Output: renders/comps_nl/<slug>-desktop-1440x900.png
        renders/comps_nl/<slug>-mobile-390x844.png
        renders/comps_nl/manifest.json

Gebruik: python3 capture_comps_nl.py [--only slug,slug] [--out DIR]
"""
import argparse, json, os, sys, datetime, traceback

from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ---------------------------------------------------------------- targets
# categorie: vergelijker | verzekeraar | zakelijk-financieel | overheid
TARGETS = [
    dict(slug="independer-autoverzekering-vergelijken",
         name="Independer - autoverzekering vergelijken (aanvraagflow, stap 1)",
         cat="vergelijker",
         url="https://www.independer.nl/autoverzekering/intro.aspx",
         ui="stappenflow met invoerformulier (kenteken, postcode), voortgangsindicator"),
    dict(slug="independer-zorgverzekering-vergelijken",
         name="Independer - zorgverzekering vergelijken",
         cat="vergelijker",
         url="https://www.independer.nl/zorgverzekering/intro.aspx",
         ui="keuzeformulier + vergelijkingsstart"),
    dict(slug="poliswijzer-autoverzekering",
         name="Poliswijzer - autoverzekeringen vergelijken",
         cat="vergelijker",
         url="https://www.poliswijzer.nl/autoverzekering",
         ui="vergelijkformulier en productoverzicht"),
    dict(slug="pricewise-zorgverzekering",
         name="Pricewise - zorgverzekering vergelijken",
         cat="vergelijker",
         url="https://www.pricewise.nl/zorgverzekering/",
         ui="vergelijker-invoer, premie-overzicht"),
    dict(slug="verzekeringskaarten-overzicht",
         name="Verzekeringskaarten.nl (Verbond van Verzekeraars) - kaartenoverzicht",
         cat="vergelijker",
         url="https://www.verzekeringskaarten.nl/",
         ui="zoek + resultaatlijst van gestandaardiseerde verzekeringskaarten"),
    dict(slug="centraalbeheer-autoverzekering",
         name="Centraal Beheer - autoverzekering premie berekenen",
         cat="verzekeraar",
         url="https://www.centraalbeheer.nl/verzekeringen/autoverzekering",
         ui="premieberekening-formulier, dekkingstabel"),
    dict(slug="asr-orv-premie-berekenen",
         name="a.s.r. - overlijdensrisicoverzekering premie berekenen",
         cat="verzekeraar",
         url="https://www.asr.nl/verzekeringen/levensverzekeringen/"
             "overlijdensrisicoverzekering/premie-berekenen",
         ui="premieberekening-formulier met invoervelden en uitkomst"),
    dict(slug="asr-autoverzekering",
         name="a.s.r. - autoverzekering",
         cat="verzekeraar",
         url="https://www.asr.nl/verzekeringen/autoverzekering",
         ui="dekkingskeuze en premieblok"),
    dict(slug="klaverblad-autoverzekering",
         name="Klaverblad - autoverzekering",
         cat="verzekeraar",
         url="https://www.klaverblad.nl/autoverzekering",
         ui="dekkingsoverzicht en aanvraagstart"),
    dict(slug="eboekhouden-prijzen",
         name="e-Boekhouden.nl - prijzen/pakketten",
         cat="zakelijk-financieel",
         url="https://www.e-boekhouden.nl/prijzen",
         ui="pakket- en tarieventabel"),
    dict(slug="exact-online",
         name="Exact Online - boekhoudsoftware",
         cat="zakelijk-financieel",
         url="https://www.exact.com/nl/software/exact-online",
         ui="productinterface-schermen en pakketvergelijking"),
    dict(slug="exact-boekhouden",
         name="Exact - boekhouden (pakketten)",
         cat="zakelijk-financieel",
         url="https://www.exact.com/nl/producten/boekhouden",
         ui="pakketoverzicht met vergelijkingstabel"),
    dict(slug="kifid-klacht-indienen",
         name="Kifid - ik heb een klacht (stappenflow)",
         cat="overheid",
         url="https://www.kifid.nl/ik-heb-een-klacht/",
         ui="stappenuitleg van de klachtprocedure"),
    dict(slug="zorgwijzer-vergelijken",
         name="Zorgwijzer - zorgverzekering vergelijken",
         cat="vergelijker",
         url="https://www.zorgwijzer.nl/vergelijken",
         ui="vergelijkformulier met dekkingsopties en premielijst"),
    dict(slug="geld-nl-autoverzekering",
         name="Geld.nl - autoverzekering vergelijken",
         cat="vergelijker",
         url="https://www.geld.nl/autoverzekering",
         ui="vergelijker-invoer en premie-overzicht"),
    dict(slug="overstappen-zorgverzekering",
         name="Overstappen.nl - zorgverzekering vergelijken",
         cat="vergelijker",
         url="https://www.overstappen.nl/zorgverzekering/",
         ui="vergelijkformulier en resultaatlijst"),
    dict(slug="digid-startscherm",
         name="DigiD - startscherm/inlogportaal",
         cat="overheid",
         url="https://www.digid.nl/",
         ui="overheidsportaal met inlog- en actiekaarten"),
    dict(slug="interpolis-autoverzekering",
         name="Interpolis - autoverzekering",
         cat="verzekeraar",
         url="https://www.interpolis.nl/autoverzekering",
         ui="premie-invoer, dekkingskeuze"),
    dict(slug="nn-autoverzekering",
         name="Nationale-Nederlanden - autoverzekering",
         cat="verzekeraar",
         url="https://www.nn.nl/particulier/schadeverzekeringen/autoverzekering.htm",
         ui="productpagina met dekkingstabel en premieblok"),
    dict(slug="anwb-autoverzekering",
         name="ANWB - autoverzekering",
         cat="verzekeraar",
         url="https://www.anwb.nl/verzekeringen/autoverzekering",
         ui="premie-calculator, dekkingsvergelijking"),
    dict(slug="moneybird-prijzen",
         name="Moneybird - prijzen/pakketten",
         cat="zakelijk-financieel",
         url="https://www.moneybird.nl/prijzen",
         ui="prijstabel met pakketvergelijking"),
    dict(slug="moneybird-facturen",
         name="Moneybird - facturatie (productinterface)",
         cat="zakelijk-financieel",
         url="https://www.moneybird.nl/facturen",
         ui="interface-schermen van facturatiesoftware"),
    dict(slug="rabobank-zakelijke-rekening",
         name="Rabobank - zakelijke betaalrekening",
         cat="zakelijk-financieel",
         url="https://www.rabobank.nl/zakelijk/betalen/zakelijke-rekening",
         ui="pakketvergelijking met tarieventabel"),
    dict(slug="ing-zakelijke-rekening",
         name="ING - zakelijke rekening",
         cat="zakelijk-financieel",
         url="https://www.ing.nl/zakelijk/betalen/zakelijke-rekening",
         ui="productvergelijking, tarieven"),
    dict(slug="kvk-zoeken-resultaten",
         name="KvK Handelsregister - zoekresultaten",
         cat="overheid",
         url="https://www.kvk.nl/zoeken/",
         ui="zoekformulier met filters en resultaatlijst",
         steps=[{"fill": "input[type='search'], input[name='q'], "
                         "input[placeholder*='Zoek']", "value": "assurantie"},
                {"press": "Enter"},
                {"wait": 3500}]),
    dict(slug="kifid-uitspraken-register",
         name="Kifid - uitsprakenregister (zoek + resultaten)",
         cat="overheid",
         url="https://www.kifid.nl/kifid-kennis-en-uitspraken/uitspraken/",
         ui="facetzoeker met filters en resultaatlijst"),
    dict(slug="mijnpensioenoverzicht",
         name="Mijnpensioenoverzicht.nl - inlog/startscherm",
         cat="overheid",
         url="https://www.mijnpensioenoverzicht.nl/",
         ui="DigiD-inlogscherm, overheidshuisstijl"),
    dict(slug="mijnoverheid-inloggen",
         name="MijnOverheid - inlogscherm",
         cat="overheid",
         url="https://mijn.overheid.nl/",
         ui="DigiD-inlog, Rijkshuisstijl"),
    dict(slug="belastingdienst-zakelijk-btw",
         name="Belastingdienst zakelijk - btw-aangifte",
         cat="overheid",
         url="https://www.belastingdienst.nl/wps/wcm/connect/nl/btw/btw",
         ui="overheidsinformatie-interface met navigatie/tabellen"),
]

# ------------------------------------------------------- cookie handling
ACCEPT_TEXTS = [
    "Alles accepteren", "Accepteer alles", "Alle cookies accepteren",
    "Accepteren", "Akkoord", "Ik ga akkoord", "Ja, ik accepteer",
    "Cookies accepteren", "Accepteer cookies", "Alles toestaan",
    "Alle cookies toestaan", "Sta alles toe", "Doorgaan", "Begrepen",
    "Accept all", "Allow all", "Accept",
]

HIDE_CSS = """
#onetrust-consent-sdk, #onetrust-banner-sdk, .onetrust-pc-dark-filter,
#CybotCookiebotDialog, #CybotCookiebotDialogBodyUnderlay,
#didomi-host, .didomi-popup-open, #didomi-popup, #didomi-notice,
#usercentrics-root, #usercentrics-cmp-ui, [id^="usercentrics"],
.cookie-banner, .cookiebanner, .cookie-consent, .cookie-notice,
#cookie-banner, #cookiebar, #cookie-bar, #cookie-consent, #cookieConsent,
[class*="CookieBanner"], [class*="cookie-wall"], [id*="cookiewall"],
.cc-window, .cc-banner, #cmpbox, #cmpbox2, .qc-cmp2-container,
#sp_message_container_1, [id^="sp_message_container"],
.privacy-banner, .consent-modal, [aria-label*="ookie"],
.modal-backdrop, .cookie-overlay { display:none !important; }
html, body { overflow: auto !important; position: static !important; }
"""

# animaties uit -> stabielere full-page shots
FREEZE_CSS = """
*, *::before, *::after {
  animation-duration: 0s !important; animation-delay: 0s !important;
  transition-duration: 0s !important; transition-delay: 0s !important;
  scroll-behavior: auto !important;
}
"""


def dismiss_cookies(page, log):
    """Probeer echt te klikken (nettere layout) en verberg daarna de rest."""
    clicked = None
    for frame in [page] + list(page.frames):
        for txt in ACCEPT_TEXTS:
            try:
                btn = frame.get_by_role("button", name=txt, exact=False).first
                if btn.count() and btn.is_visible(timeout=700):
                    btn.click(timeout=2500, force=True)
                    clicked = txt
                    page.wait_for_timeout(900)
                    break
            except Exception:
                continue
        if clicked:
            break
    if not clicked:
        # tweede poging: losse links/knoppen buiten de ARIA-rol
        for txt in ACCEPT_TEXTS[:8]:
            try:
                el = page.locator(
                    f"button:has-text('{txt}'), a:has-text('{txt}'), "
                    f"[role='button']:has-text('{txt}')").first
                if el.count() and el.is_visible(timeout=500):
                    el.click(timeout=2000, force=True)
                    clicked = txt
                    page.wait_for_timeout(900)
                    break
            except Exception:
                continue
    try:
        page.add_style_tag(content=HIDE_CSS)
    except Exception:
        pass
    log.append(f"cookies: {'geklikt op ' + clicked if clicked else 'verborgen via CSS'}")
    return clicked


def run_steps(page, steps, log):
    """Kleine stappenrunner om een echte formulier-/resultaatstaat te bereiken."""
    for st in steps or []:
        try:
            if "fill" in st:
                page.locator(st["fill"]).first.fill(st["value"], timeout=8000)
            elif "click" in st:
                page.locator(st["click"]).first.click(timeout=8000)
            elif "press" in st:
                page.keyboard.press(st["press"])
            elif "wait" in st:
                page.wait_for_timeout(st["wait"])
            log.append("stap ok: " + json.dumps(st, ensure_ascii=False))
        except Exception as e:
            log.append(f"stap mislukt ({json.dumps(st, ensure_ascii=False)}): "
                       f"{type(e).__name__}")
    page.wait_for_timeout(1500)


def settle(page):
    """Lazy-load triggeren en terug naar boven."""
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    try:
        page.evaluate("""async () => {
            const step = Math.round(window.innerHeight * 0.8);
            let y = 0;
            const max = () => document.body.scrollHeight;
            while (y < max() && y < 30000) {
                window.scrollTo(0, y); y += step;
                await new Promise(r => setTimeout(r, 160));
            }
            window.scrollTo(0, 0);
            await new Promise(r => setTimeout(r, 400));
        }""")
    except Exception:
        pass
    page.wait_for_timeout(800)


def shoot(browser, target, viewport, dsf, path, is_mobile, log):
    ctx = browser.new_context(
        viewport=viewport, device_scale_factor=dsf,
        is_mobile=is_mobile, has_touch=is_mobile,
        user_agent=UA, locale="nl-NL", timezone_id="Europe/Amsterdam",
        ignore_https_errors=True,
        extra_http_headers={"Accept-Language": "nl-NL,nl;q=0.9,en;q=0.6"},
    )
    ctx.set_default_timeout(30000)
    page = ctx.new_page()
    try:
        resp = page.goto(target["url"], wait_until="domcontentloaded", timeout=45000)
        status = resp.status if resp else None
        if status and status >= 400:
            raise RuntimeError(f"HTTP {status}")
        page.wait_for_timeout(1500)
        dismiss_cookies(page, log)
        try:
            page.add_style_tag(content=FREEZE_CSS)
        except Exception:
            pass
        run_steps(page, target.get("steps"), log)
        settle(page)
        try:
            page.add_style_tag(content=HIDE_CSS)
        except Exception:
            pass
        title = (page.title() or "").strip()
        body = (page.inner_text("body")[:3000] if page.locator("body").count()
                else "")
        for bad in ("Werk aan de winkel", "even niet bereikbaar",
                    "Access Denied", "Pardon Our Interruption",
                    "Even geduld", "verify you are human",
                    "Je browser wordt gecontroleerd"):
            if bad.lower() in body.lower():
                raise RuntimeError(f"blokkade-/onderhoudspagina ({bad!r})")
        final_url = page.url
        page.screenshot(path=path, full_page=True, animations="disabled")
        return dict(status=status, title=title, final_url=final_url,
                    bytes=os.path.getsize(path))
    finally:
        ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/home/user/Ai-assurantie-portaal/renders/comps_nl")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    targets = [t for t in TARGETS if not only or t["slug"] in only]

    comps, skipped = [], []
    launch = dict(executable_path=CHROME, headless=True,
                  args=["--no-sandbox", "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                        "--hide-scrollbars", "--force-color-profile=srgb",
                        # De agent-proxy verbreekt TLS1.3-tunnels van Chromium
                        # (ws_closed_mid_exchange). TLS1.2 werkt wel.
                        "--ssl-version-max=tls1.2",
                        "--disable-features=EncryptedClientHello,UseDnsHttpsSvcb,"
                        "UseDnsHttpsSvcbAlpn"])
    if PROXY:
        launch["proxy"] = {"server": PROXY}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch)
        for t in targets:
            log = []
            d_path = os.path.join(out, f"{t['slug']}-desktop-1440x900.png")
            m_path = os.path.join(out, f"{t['slug']}-mobile-390x844.png")
            try:
                d = shoot(browser, t, {"width": 1440, "height": 900}, 2,
                          d_path, False, log)
                m = shoot(browser, t, {"width": 390, "height": 844}, 2,
                          m_path, True, log)
                comps.append(dict(
                    slug=t["slug"], naam=t["name"], categorie=t["cat"],
                    bron_url=t["url"], eind_url=d["final_url"],
                    pagina_titel=d["title"],
                    interface_elementen=t["ui"],
                    http_status=d["status"],
                    vastgelegd_op=datetime.datetime.now(
                        datetime.timezone.utc).isoformat(timespec="seconds"),
                    bestanden={
                        "desktop": dict(
                            file=os.path.basename(d_path),
                            viewport="1440x900", device_scale_factor=2,
                            full_page=True, bytes=d["bytes"]),
                        "mobile": dict(
                            file=os.path.basename(m_path),
                            viewport="390x844", device_scale_factor=2,
                            full_page=True, bytes=m["bytes"]),
                    },
                    notities="; ".join(log),
                ))
                print(f"OK   {t['slug']}  ({d['bytes']//1024}kB / {m['bytes']//1024}kB)",
                      flush=True)
            except Exception as e:
                for p in (d_path, m_path):
                    if os.path.exists(p) and os.path.getsize(p) < 4000:
                        os.remove(p)
                reden = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
                skipped.append(dict(slug=t["slug"], naam=t["name"],
                                    url=t["url"], reden=reden))
                print(f"SKIP {t['slug']}  {reden}", flush=True)
        browser.close()

    manifest = dict(
        set="comps_nl",
        doel=("Eerlijke meetlat: beste publiek toegankelijke Nederlandse "
              "financiele/verzekerings-interfaces met echte interface-elementen "
              "(formulieren, tabellen, stappenflows, resultaatlijsten)."),
        gegenereerd_op=datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        generator="scripts/capture_comps_nl.py (Playwright/Chromium 1194)",
        viewports=dict(
            desktop=dict(width=1440, height=900, device_scale_factor=2, full_page=True),
            mobile=dict(width=390, height=844, device_scale_factor=2, full_page=True)),
        cookie_afhandeling=("Consent-knop geklikt waar mogelijk; anders bekende "
                            "CMP-containers via CSS verborgen en scroll-lock opgeheven."),
        aantal_comps=len(comps),
        aantal_bestanden=len(comps) * 2,
        comps=comps,
        overgeslagen=skipped,
    )
    mpath = os.path.join(out, "manifest.json")
    if os.path.exists(mpath):
        try:
            prev = json.load(open(mpath, encoding="utf-8"))
            done = {c["slug"] for c in comps}
            merged = [c for c in prev.get("comps", []) if c["slug"] not in done]
            merged += comps
            merged.sort(key=lambda c: (c["categorie"], c["slug"]))
            comps = merged
            fail = {x["slug"] for x in skipped}
            ok = {c["slug"] for c in comps}
            skipped = ([x for x in prev.get("overgeslagen", [])
                        if x["slug"] not in fail and x["slug"] not in ok]
                       + [x for x in skipped if x["slug"] not in ok])
            manifest["comps"] = comps
            manifest["overgeslagen"] = skipped
            manifest["aantal_comps"] = len(comps)
            manifest["aantal_bestanden"] = len(comps) * 2
        except Exception as e:
            print("waarschuwing: kon oude manifest niet mergen:", e)
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n{len(comps)} comps, {len(comps)*2} bestanden -> {mpath}")
    print(f"{len(skipped)} overgeslagen")


if __name__ == "__main__":
    main()
