#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
maak_decoy.py - rendert de DECOYS van de blinde meetlat en schrijft hun manifest.

Waarom
------
De decoys zijn de controlegroep van de meetlat. Het zijn zelfgemaakte, fictieve schermen van
een Nederlands assurantie-backoffice in vier bewust benoemde kwaliteiten:

    redelijk   > matig   > zwak   > zeer_zwak

Als onze beoordelingsmethode deugt, eindigen ze in die volgorde ONDER een goed ontwerp. Eindigt
een decoy erboven, dan meten we niet wat we denken te meten en is de meetlat kapot.

Waarom vier en niet een
-----------------------
De eerste meetronde had een decoy, en die was een domein-tweeling van ons product (Nederlands,
assurantie, backoffice, geen herkenbaar merk). Zodra onze schermen erbij komen zijn dan "wij" en
"de decoy" de enige twee zonder merk: "geen herkenbaar merk" betekent automatisch "wij". Met vier
decoys van wisselende kwaliteit en indeling is dat gat dicht.

Ze zijn verschillend GENOEG om niet een ontwerp met vier knoppen te zijn:

    kwaliteit   indeling                                       dichtheid
    redelijk    admin-template: zijbalk + lijstweergave        middel
    matig       Bootstrap-dashboard: KPI-tegels + panelen      middel
    zwak        invoerformulier met 9 tabbladen, 3 kolommen    zeer hoog
    zeer_zwak   intranet op geneste tabellen: zoeken + lijst   hoog

Bronnen
-------
De HTML-bestanden in renders/decoy/ (decoy_<kwaliteit>.html) ZIJN de bron; ze zijn met de hand
geschreven en worden gecommit. Dit script rendert ze op 1440 en 390 breed, meet of ze leesbaar en
functioneel zijn, en schrijft renders/decoy/manifest.json. De PNG's komen nooit in git.

Leesbaar en functioneel is een MEETRESULTAAT, geen bewering
-----------------------------------------------------------
Per decoy en viewport wordt gemeten (in de gerenderde DOM): geen horizontale overflow, geen
afgekapte tekst of invoerwaarde, geen bedienelement dat door iets anders wordt bedekt, kleinste
lettergrootte >= 10 px, laagste tekstcontrast >= 3:1, geen overlappende tekst. Faalt een meting,
dan krijgt het record geladen_ok=false met reden en wordt de PNG naar _afgekeurd/ verplaatst.

Gebruik
-------
  python3 scripts/maak_decoy.py                       # alle decoys, 1440 + 390, manifest schrijven
  python3 scripts/maak_decoy.py --kwaliteit zwak      # selectie
  python3 scripts/maak_decoy.py --alleen-html         # niets renderen; controleer alleen de bronnen
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture_controle as cc  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
UIT = PROJECT / "renders" / "decoy"
BRON_MAP = UIT

DEKKING = ("Zelfgemaakte, fictieve schermen van een Nederlands assurantie-backoffice in vier bewust "
           "benoemde kwaliteiten. Ze zijn GEEN bewijs van hoe echte producten eruitzien; ze bestaan "
           "zodat 'scherm zonder herkenbaar merk' niet automatisch 'ons product' betekent, en als "
           "controlegroep die onder een goed ontwerp moet eindigen.")
DOEL = ("Controlegroep voor de blinde A/B-meetlat: vier zelfgemaakte assurantie-backofficeschermen van "
        "wisselende, benoemde kwaliteit. Hoort onder een goed ontwerp te eindigen, in de volgorde "
        "redelijk > matig > zwak > zeer_zwak; doet het dat niet, dan is de meetlat kapot.")
KWALITEITSSCHAAL = {
    "redelijk": ("gangbaar en samenhangend, maar duidelijk minder dan een goed ontwerp: geen typografische "
                 "schaal, onregelmatig ritme, te luide bediening"),
    "matig": ("herkenbare structuur maar zichtbaar rommelig: zware randen om alles, ongelijke kolommen, "
              "geen hierarchie in de panelen"),
    "zwak": "geen visuele hierarchie; volgepropt; inconsistente labels, velden en knoppen",
    "zeer_zwak": "verouderd intranetscherm: geneste tabellen, gemengde lettertypen, alles even zwaar",
}
LADDER_TOELICHTING = ("De rangorde redelijk > matig > zwak > zeer_zwak is het oordeel van de maker op grond van de "
                      "ingebouwde zwaktes; ze is niet door een onafhankelijke beoordelaar bevestigd. De "
                      "eerste ronde met het harnas kan haar toetsen: een beoordelaar die de decoys in een andere "
                      "volgorde zet dan deze ladder, of een decoy boven een goed ontwerp, meet iets anders "
                      "dan we denken.")
GEINSPECTEERD_OP = "2026-09-29"

# Leesbaarheidsdrempels (gemeten in de gerenderde DOM)
MIN_LETTERGROOTTE_PX = 10.0
MIN_CONTRAST = 3.0

DECOYS: list[dict] = [
    {
        "kwaliteit": "redelijk",
        "html": "decoy_redelijk.html",
        "bron_naam": "Decoy redelijk (admin-template, polissenlijst)",
        "soort_scherm": "lijstweergave",
        "indeling": "zijbalk met gegroepeerde navigatie, zoekbalk, paginakop met vier knoppen, filterbalk, "
                    "statustabs met tellers, tabel van 12 polissen met rijacties, paginering",
        "dichtheid": "middel",
        "wat_het_toont": ("Zelfgemaakt nepscherm (geen echte software) van een Nederlands assurantie-backoffice: "
                          "een polissenlijst in een admin-template met donkere zijbalk, filterbalk, statustabs, "
                          "tabel van 12 polissen met rijknoppen en paginering. Op het eerste gezicht gangbaar, "
                          "bewust redelijk maar niet goed."),
        "bewuste_zwaktes": [
            "geen typografische schaal: 10,5/11/12/13/17/21 px zonder vaste verhouding; tabelkoppen in 10,5 px "
            "bijna-lichtgrijs met letterafstand",
            "onregelmatig ritme: filtervelden van 30/32/34/36 px hoog naast elkaar en wisselende paddings "
            "(9/11/12/14/22 px)",
            "bediening te luid: vier knoppen in de paginakop (twee omlijnd, een groen, een blauw) en per rij "
            "drie knoppen (Bekijk/Wijzig/Prolongeer) die even zwaar wegen als de data zelf",
            "vijf verschillende statusbadge-vormen (gevulde pil, gevuld blokje, omlijnde pil, vierkant, bolletje "
            "met tekst)",
            "bedragen links uitgelijnd en datums gecentreerd in plaats van consequent uitgelijnd",
            "dubbele zoekfunctie (zoekbalk bovenin en zoekveld in het filter) en statustabs die het statusfilter "
            "dupliceren",
            "mobiele weergave laat de kolomkoppen weg (waarden staan zonder label onder elkaar)",
        ],
        "zwaktes_die_grijswaarde_overleven": "alle; geen enkele steunt op kleur, behalve de vijf badgevormen "
                                             "(die verschillen ook in vorm en gewicht)",
    },
    {
        "kwaliteit": "matig",
        "html": "decoy_matig.html",
        "bron_naam": "Decoy matig (Bootstrap-dashboard, portefeuille)",
        "soort_scherm": "dashboard",
        "indeling": "topbalk met knoppennavigatie, meldingsbalk, vier KPI-tegels, twee kolommen met panelen "
                    "(tabel, staafgrafiek, zoekformulier, takenlijst, voortgangsbalken)",
        "dichtheid": "middel",
        "wat_het_toont": ("Zelfgemaakt nepscherm (geen echte software) van een Nederlands assurantie-backoffice: "
                          "een portefeuille-dashboard in Bootstrap-stijl met vier KPI-tegels, tabel van recente "
                          "polismutaties, staafgrafiek, zoekformulier, taken en voortgangsbalken. Bewust matig: "
                          "zware randen, ongelijke kolommen, geen hierarchie in de panelen."),
        "bewuste_zwaktes": [
            "systeemfont zonder typografische schaal (11/12/13/14/16/22/26 px door elkaar)",
            "randen om vrijwel elk element en drie verschillende hoekradii (0, 3 en 6 px)",
            "inconsistente witruimte (8/10/12/15/18/20/25 px naast elkaar)",
            "vier niet-verwante accentkleuren (blauw, groen, oranje, paars); deze zwakte overleeft de "
            "grijswaardestap NIET",
            "kolombreedtes en knoppen net niet uitgelijnd: KPI-tegels van 24/23/26/22% breed, de laatste "
            "tegel eindigt niet op de rechterrand van het raster",
            "grijs-op-grijs panelen zonder hierarchie tussen kop en inhoud; drie even zware actieknoppen "
            "(blauw, groen, oranje) onder de tabel",
        ],
        "zwaktes_die_grijswaarde_overleven": "alle behalve de vier accentkleuren",
    },
    {
        "kwaliteit": "zwak",
        "html": "decoy_zwak.html",
        "bron_naam": "Decoy zwak (invoerformulier nieuwe polis, negen tabbladen)",
        "soort_scherm": "formulier",
        "indeling": "topbalk, blijvende waarschuwing, negen tabbladen, drie kolommen fieldsets met 55 invoervelden "
                    "en keuzes, dekkingstabel met invoervelden, clausulelijst, elf knoppen verspreid over het scherm",
        "dichtheid": "zeer hoog",
        "wat_het_toont": ("Zelfgemaakt nepscherm (geen echte software) van een Nederlands assurantie-backoffice: "
                          "een volgepropt invoerformulier 'Nieuwe polis invoeren' met negen tabbladen, drie "
                          "kolommen fieldsets, dekkingstabel en clausulelijst. Bewust zwak: geen hierarchie, "
                          "inconsistente labels en knoppen."),
        "bewuste_zwaktes": [
            "geen typografische hierarchie: paginatitel 14 px, veldgroepen 12 px vet, labels 11 px; alles bijna "
            "even groot en even zwaar",
            "labels wisselen van plaats (boven het veld, links rechts uitgelijnd) en de verplicht-markering "
            "staat op drie manieren (* achter, * voor, '(verplicht)')",
            "veldbreedtes willekeurig (40/70/95/130/175/190 px) en kolommen van 31/34/31% met ongelijke "
            "tussenruimte: geen raster",
            "elf knoppen verspreid over het scherm: vier 'Opslaan'-varianten op twee plekken, tweemaal 'Annuleren' en "
            "'Berekenen' midden in het formulier",
            "fieldsets met vier verschillende randstijlen (dun, cursieve legende, hoofdletterlegende, dikke rand)",
            "tabbladen van ongelijke breedte waarvan de actieve nauwelijks afwijkt",
            "hulpteksten van 10 px in grijs die met de velden concurreren; een waarschuwing staat permanent bovenaan",
            "twaalf clausules als ongegroepeerde checkboxlijst",
        ],
        "zwaktes_die_grijswaarde_overleven": "alle; het scherm steunt vrijwel niet op kleur",
    },
    {
        "kwaliteit": "zeer_zwak",
        "html": "decoy_zeer_zwak.html",
        "bron_naam": "Decoy zeer zwak (intranet, polissen zoeken op geneste tabellen)",
        "soort_scherm": "zoekscherm",
        "indeling": "geneste tabellen: titelbalk, ongegroepeerd menu van 18 links, waarschuwingsbalk, "
                    "zoekcriteria in een raster van 12 velden, resultaattabel van 11 kolommen, pager, voetregel",
        "dichtheid": "hoog",
        "wat_het_toont": ("Zelfgemaakt nepscherm (geen echte software) van een Nederlands assurantie-backoffice: "
                          "een verouderd intranetscherm 'Polissen zoeken' op geneste tabellen met menu van 18 links, "
                          "zoekcriteria en een resultaattabel van 12 polissen. Bewust zeer zwak: gemengde "
                          "lettertypen, kader in kader, alles even zwaar."),
        "bewuste_zwaktes": [
            "lettertypen zonder reden door elkaar: Times New Roman voor lopende tekst, Arial voor koppen en "
            "Courier voor invoervelden en teller",
            "opmaak met geneste tabellen en dubbele/inset/outset-randen: kader in kader in kader",
            "geen hierarchie: paginatitel, sectiekop en tabelkop verschillen nauwelijks; de hoofdactie 'Zoeken' "
            "lijkt op de rest",
            "alles in de resultaattabel gecentreerd, 11 px, zware rand om elke cel en sterke zebrastrepen",
            "menu van 18 links in een ongegroepeerde kolom met willekeurig vet en cursief",
            "labels rechts uitgelijnd in grijze cellen, invoervelden van willekeurige breedte in een ander "
            "lettertype",
            "waarschuwingsbalk in hoofdletters met dubbele rand die met de paginatitel concurreert",
            "afkortingen (NST, HOL, A/B/O/R/G) in plaats van leesbare statuswoorden",
        ],
        "zwaktes_die_grijswaarde_overleven": "alle; het scherm steunt vrijwel niet op kleur",
    },
]

for _d in DECOYS:
    _d["id"] = f"decoy_{_d['kwaliteit']}"


def bestandsnaam(kwaliteit: str, viewport_naam: str) -> str:
    v = cc.VIEWPORTS[viewport_naam]
    return f"decoy-{kwaliteit}-{viewport_naam}-{v['width']}x{v['height']}.png"


# ---------------------------------------------------------------------------
# Leesbaarheid en bruikbaarheid, gemeten in de gerenderde DOM
# ---------------------------------------------------------------------------
LEESBAARHEID_JS = r"""
() => {
  const doc = document.documentElement;
  const res = {};
  res.viewport_breedte = doc.clientWidth;
  res.document_breedte = doc.scrollWidth;
  res.horizontale_overflow = doc.scrollWidth > doc.clientWidth + 1;
  res.hoogte_css_px = Math.max(document.body.scrollHeight, doc.scrollHeight);

  const parse = c => { const m = (c || '').match(/rgba?\(([^)]+)\)/); if (!m) return [255, 255, 255, 1];
                       const p = m[1].split(',').map(parseFloat); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                               return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const achtergrond = el => {
    const lagen = []; let n = el;
    while (n && n.nodeType === 1) { const c = parse(getComputedStyle(n).backgroundColor); if (c[3] > 0) lagen.push(c); if (c[3] >= 0.99) break; n = n.parentElement; }
    let r = 255, g = 255, b = 255;
    for (let i = lagen.length - 1; i >= 0; i--) { const [lr, lg, lb, la] = lagen[i]; r = lr * la + r * (1 - la); g = lg * la + g * (1 - la); b = lb * la + b * (1 - la); }
    return [r, g, b];
  };
  const contrast = (a, b) => { const l1 = lum(a), l2 = lum(b); const hi = Math.max(l1, l2), lo = Math.min(l1, l2); return (hi + 0.05) / (lo + 0.05); };

  // tekstknopen: lettergrootte, contrast, rechthoeken
  let minFont = 999, minContrast = 999, aantalTeksten = 0;
  const klein = [], laag = [], rects = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const t = node.textContent.trim();
    if (!t) continue;
    const el = node.parentElement; if (!el) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const rs = Array.from(range.getClientRects()).filter(r => r.width > 1 && r.height > 1);
    if (!rs.length) continue;
    aantalTeksten++;
    const fs = parseFloat(cs.fontSize);
    const fg = parse(cs.color);
    const ratio = contrast(fg, achtergrond(el));
    if (fs < minFont) minFont = fs;
    if (ratio < minContrast) minContrast = ratio;
    if (fs < 10) klein.push(t.slice(0, 24) + ' (' + fs + 'px)');
    if (ratio < 3) laag.push(t.slice(0, 24) + ' (' + ratio.toFixed(2) + ')');
    for (const r of rs) rects.push({x0: r.left + scrollX, y0: r.top + scrollY, x1: r.right + scrollX, y1: r.bottom + scrollY, el, t: t.slice(0, 20)});
  }
  res.tekstfragmenten = aantalTeksten;
  res.min_lettergrootte_px = minFont === 999 ? null : Math.round(minFont * 10) / 10;
  res.min_contrast = minContrast === 999 ? null : Math.round(minContrast * 100) / 100;
  res.te_kleine_teksten = klein.slice(0, 5);
  res.te_lage_contrasten = laag.slice(0, 5);

  // overlappende tekst (verschillende elementen, wezenlijke overlap)
  let overlap = 0; const voorbeelden = [];
  for (let i = 0; i < rects.length; i++) {
    for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i], b = rects[j];
      if (a.el === b.el || a.el.contains(b.el) && false) continue;
      const w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0), h = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
      if (w <= 1 || h <= 1) continue;
      const opp = w * h, kl = Math.min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0));
      if (opp > 0.3 * kl) { overlap++; if (voorbeelden.length < 3) voorbeelden.push(a.t + ' / ' + b.t); }
    }
  }
  res.overlappende_teksten = overlap;
  res.overlap_voorbeelden = voorbeelden;

  // afgekapte inhoud: overflow hidden met meer inhoud dan zichtbaar, en afgekapte invoerwaarden
  let afgekapt = 0; const afgekaptVoorbeelden = [];
  for (const el of document.body.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none') continue;
    if ((cs.overflowX === 'hidden' || cs.overflowX === 'clip') && el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1) {
      afgekapt++; if (afgekaptVoorbeelden.length < 3) afgekaptVoorbeelden.push(el.tagName + '.' + (el.className || ''));
    }
  }
  res.afgekapte_elementen = afgekapt;
  let afgekapteInvoer = 0; const invoerVoorbeelden = [];
  const canvas = document.createElement('canvas').getContext('2d');
  for (const el of document.querySelectorAll('input[type=text], input:not([type]), select')) {
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (cs.display === 'none' || r.width === 0) continue;
    if (el.tagName === 'INPUT') {
      if (el.scrollWidth > el.clientWidth + 1) { afgekapteInvoer++; invoerVoorbeelden.push('input:' + (el.value || '').slice(0, 24)); }
    } else {
      canvas.font = cs.font;
      const opt = el.options[el.selectedIndex];
      const w = canvas.measureText(opt ? opt.text : '').width;
      const beschikbaar = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 22;
      if (w > beschikbaar) { afgekapteInvoer++; invoerVoorbeelden.push('select:' + (opt ? opt.text : '').slice(0, 24)); }
    }
  }
  res.afgekapte_invoer = afgekapteInvoer;
  res.afgekapte_invoer_voorbeelden = invoerVoorbeelden.slice(0, 4);

  // bedienelementen: aantal en of ze bedekt worden door iets anders
  const bediening = Array.from(document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea'))
    .filter(e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; });
  res.bedieningselementen = bediening.length;
  let bedekt = 0; const bedektVoorbeelden = [];
  for (const e of bediening) {
    e.scrollIntoView({block: 'center', inline: 'center'});
    const r = e.getBoundingClientRect();
    const x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), y = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
    const hit = document.elementFromPoint(x, y);
    if (hit && !(hit === e || e.contains(hit) || hit.contains(e))) { bedekt++; if (bedektVoorbeelden.length < 3) bedektVoorbeelden.push(e.tagName + ':' + (e.innerText || e.value || '').slice(0, 16)); }
  }
  window.scrollTo(0, 0);
  res.bedekte_bediening = bedekt;
  res.bedekte_bediening_voorbeelden = bedektVoorbeelden;
  res.tekst_tekens = document.body.innerText.length;
  return res;
}
"""


def beoordeel_leesbaarheid(m: dict) -> list[str]:
    """Afkeurcodes uit de leesbaarheidsmeting. Leeg = leesbaar en functioneel."""
    r: list[str] = []
    if m.get("horizontale_overflow"):
        r.append("horizontale_overflow")
    if m.get("afgekapte_elementen"):
        r.append("afgekapte_elementen")
    if m.get("afgekapte_invoer"):
        r.append("afgekapte_invoerwaarde")
    if m.get("bedekte_bediening"):
        r.append("bedekte_bediening")
    if m.get("overlappende_teksten"):
        r.append("overlappende_tekst")
    if m.get("min_lettergrootte_px") is not None and m["min_lettergrootte_px"] < MIN_LETTERGROOTTE_PX:
        r.append("lettergrootte_te_klein")
    if m.get("min_contrast") is not None and m["min_contrast"] < MIN_CONTRAST:
        r.append("contrast_te_laag")
    if not m.get("bedieningselementen"):
        r.append("geen_bedienelementen")
    return r


def kaart_van(d: dict) -> dict:
    return {
        "id": d["id"], "bron_naam": d["bron_naam"], "url": None,
        "klasse": "decoy", "domein": "decoy", "taal": "nl",
        "soort_scherm": d["soort_scherm"], "kwaliteit": d["kwaliteit"],
        "wat_het_toont": d["wat_het_toont"], "geinspecteerd_op": GEINSPECTEERD_OP,
        "dekking_categorie": DEKKING, "bewuste_zwaktes": d["bewuste_zwaktes"],
        "indeling": d["indeling"], "bron_html": d["html"],
    }


def render(uit: Path, gekozen: list[dict]) -> list[dict]:
    from playwright.sync_api import sync_playwright

    records: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=cc.CHROME, headless=True,
                                     args=["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars",
                                           "--force-color-profile=srgb", "--font-render-hinting=none"])
        try:
            for d in gekozen:
                html_pad = BRON_MAP / d["html"]
                for vp in cc.VIEWPORT_NAMEN:
                    ctx = browser.new_context(viewport=cc.VIEWPORTS[vp], device_scale_factor=cc.DEVICE_SCALE,
                                              is_mobile=vp == "mobile", has_touch=vp == "mobile",
                                              locale="nl-NL", timezone_id="Europe/Amsterdam")
                    pg = ctx.new_page()
                    pg.goto(html_pad.as_uri(), wait_until="load")
                    pg.wait_for_timeout(400)
                    meting = pg.evaluate(LEESBAARHEID_JS)
                    pg.evaluate("window.scrollTo(0, 0)")
                    pg.wait_for_timeout(150)
                    bestand = bestandsnaam(d["kwaliteit"], vp)
                    pg.screenshot(path=str(uit / bestand), full_page=True)
                    dom = cc.verrijk_dom(cc.verzamel_dom_info(pg))
                    ctx.close()
                    reden = beoordeel_leesbaarheid(meting)
                    raw = {"vastgelegd_op": cc.nu_iso(), "http_status": None, "eind_url": None,
                           "dom": dom, "cookies": None, "pagina_hoogte_css_px": meting["hoogte_css_px"]}
                    rec = cc.bouw_record(
                        kaart=kaart_van(d), viewport_naam=vp, bestand=bestand, map_pad=uit, raw=raw,
                        extra_redenen=reden,
                        extra_controle={"leesbaarheid": {**meting, "afkeurredenen": reden,
                                                         "drempels": {"min_lettergrootte_px": MIN_LETTERGROOTTE_PX,
                                                                      "min_contrast": MIN_CONTRAST}}})
                    records.append(rec)
                    print(f'{"OK  " if rec["geladen_ok"] else "AFK "} {rec["bestand"]:<46} '
                          f'minfont={meting["min_lettergrootte_px"]} contrast={meting["min_contrast"]} '
                          f'bediening={meting["bedieningselementen"]} {",".join(rec["afkeurredenen"])}', flush=True)
        finally:
            browser.close()
    return records


def dichtheid_meting(records: list[dict], d: dict) -> dict:
    """Beschrijvende dichtheidsmaat uit de metingen (geen kwaliteitsmaat)."""
    dk = next((r for r in records if r["id"] == d["id"] and r["viewport_naam"] == "desktop"), None)
    if not dk:
        return {}
    lb = dk["controle"].get("leesbaarheid", {})
    hoogte = max(1, dk.get("pagina_hoogte_css_px") or 1)
    return {"bedieningselementen_desktop": lb.get("bedieningselementen"),
            "tekst_tekens_desktop": lb.get("tekst_tekens"),
            "bedieningselementen_per_1000_css_px": round(1000 * (lb.get("bedieningselementen") or 0) / hoogte, 1),
            "pagina_hoogte_css_px_desktop": hoogte}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render de decoys van de blinde meetlat")
    ap.add_argument("--uit", default=str(UIT), help="uitvoermap voor PNG's en manifest")
    ap.add_argument("--kwaliteit", default="", help="komma-gescheiden selectie, bv. zwak,matig")
    ap.add_argument("--alleen-html", action="store_true", help="niets renderen; controleer alleen de bronnen")
    args = ap.parse_args(argv)

    uit = Path(args.uit)
    uit.mkdir(parents=True, exist_ok=True)
    wanted = {s.strip() for s in args.kwaliteit.split(",") if s.strip()}
    gekozen = [d for d in DECOYS if not wanted or d["kwaliteit"] in wanted]

    for d in DECOYS:
        pad = BRON_MAP / d["html"]
        print(f"bron {d['kwaliteit']:<10} {pad}  {'aanwezig' if pad.exists() else 'ONTBREEKT'}")
        if not pad.exists():
            return 1
    if args.alleen_html:
        return 0

    records = render(uit, gekozen)
    # bij een deelrun: eerdere records van niet opnieuw gerenderde decoys behouden
    mpad = uit / "manifest.json"
    if wanted and mpad.exists():
        oud = {(e["id"], e["viewport_naam"]): e for e in cc.lees_opnames(mpad)}
        nieuw = {(e["id"], e["viewport_naam"]): e for e in records}
        records = list({**oud, **nieuw}.values())
    volgorde = {d["id"]: i for i, d in enumerate(DECOYS)}
    records.sort(key=lambda e: (volgorde.get(e["id"], 99), 0 if e["viewport_naam"] == "desktop" else 1))

    decoys = []
    for d in DECOYS:
        decoys.append({
            "id": d["id"], "kwaliteit": d["kwaliteit"], "bron_naam": d["bron_naam"], "bron_html": d["html"],
            "soort_scherm": d["soort_scherm"], "indeling": d["indeling"], "dichtheid": d["dichtheid"],
            "dichtheid_gemeten": dichtheid_meting(records, d),
            "wat_het_toont": d["wat_het_toont"], "bewuste_zwaktes": d["bewuste_zwaktes"],
            "zwaktes_die_grijswaarde_overleven": d["zwaktes_die_grijswaarde_overleven"],
            "leesbaar_en_functioneel": all(r["geladen_ok"] for r in records if r["id"] == d["id"]),
        })
    manifest = {
        "set": "decoy",
        "schema_versie": cc.SCHEMA_VERSIE,
        "doel": DOEL,
        "dekking_categorie": DEKKING,
        "kwaliteitsschaal": KWALITEITSSCHAAL,
        "ladder_toelichting": LADDER_TOELICHTING,
        "niet_kapot": ("Per decoy en viewport is in de gerenderde DOM gemeten dat er geen horizontale overflow is, "
                       "geen afgekapte tekst of invoerwaarde, geen bedekt bedienelement, geen overlappende tekst, "
                       "kleinste lettergrootte >= 10 px en laagste tekstcontrast >= 3:1. De meetwaarden staan per "
                       "opname in controle.leesbaarheid. Een decoy die dat niet haalt staat met geladen_ok=false in "
                       "_afgekeurd/."),
        "bewuste_zwaktes": [f"{d['kwaliteit']}: {z}" for d in DECOYS for z in d["bewuste_zwaktes"]],
        "gegenereerd_op": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generator": "scripts/maak_decoy.py + scripts/capture_controle.py",
        "leesvoorbeeld": cc.leesvoorbeeld("manifest['bestanden'] (een lijst opnamerecords, 8 stuks: 4 decoys x 2 "
                                          "viewports); manifest['decoys'] beschrijft per decoy de bewuste zwaktes"),
        "decoys": decoys,
        "bestanden": records,
    }
    cc.schrijf_json(mpad, manifest)
    ok = sum(1 for r in records if r["geladen_ok"])
    print(f"\n{ok}/{len(records)} opnames geladen_ok -> {mpad}")
    fouten = cc.valideer_records(records, bron="decoy")
    for f in fouten:
        print("  schemafout:", f)
    return 0 if ok == len(records) and not fouten else 1


if __name__ == "__main__":
    sys.exit(main())
