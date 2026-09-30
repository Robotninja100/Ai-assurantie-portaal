#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capture_comps_nl.py - Nederlandse financiele/administratieve pagina's vastleggen als comps.

Doel: een EERLIJKE meetlat voor het domein waarin het product valt. Er is publiek geen
enkel ingelogd Nederlands assurantie-backoffice te vinden (dat zit achter een login); wat
wel publiek is (zoek- en registerapplicaties, rekentools, comparison-flows, marketing) wordt
vastgelegd en per bron GECLASSIFICEERD als `product_ui` of `marketing`. Het manifest zegt dat
plat in `dekking_categorie`.

Twee viewports per bron:
  desktop  1440x900, deviceScaleFactor 2, full page
  mobile    390x844, deviceScaleFactor 2, full page

Uitvoer: renders/comps_nl/<slug>-desktop-1440x900.png
         renders/comps_nl/<slug>-mobile-390x844.png
         renders/comps_nl/manifest.json  (object met "comps" en "overgeslagen")

Wat er sinds de meetlat-audit anders is
---------------------------------------
* Naharde opnamecontrole per PNG (scripts/capture_controle.py): `geladen_ok`, `controle`,
  afkeurredenen. Afgekeurde PNG's gaan naar renders/comps_nl/_afgekeurd/.
* De cookieafhandeling meet voor en na; het manifest zegt alleen 'geklikt' als de overlay
  daarna aantoonbaar weg was.
* `ignore_https_errors` en de stealth-vlag `AutomationControlled` zijn verwijderd:
  certificaatverificatie blijft AAN en er wordt geen botdetectie omzeild.
* Hosts die bots blokkeren of die de proxy weigert (403/407) worden overgeslagen en gemeld.
* Geen account, geen login, geen voorwaarden accepteren. Alleen een zoekopdracht in een
  publiek zoekveld, waar dat in `steps` staat.

Gebruik: python3 scripts/capture_comps_nl.py [--only slug,slug] [--alleen-manifest] [--out DIR]
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture_controle as cc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "renders" / "comps_nl"

DEKKING = ("GEEN echte vertegenwoordiger van een ingelogd Nederlands assurantie-backoffice "
           "beschikbaar: dat soort software zit achter een login of demo-aanvraag en is publiek "
           "niet vast te leggen zonder account. Wat hier staat zijn publiek toegankelijke "
           "Nederlandse pagina's: zoek-/registerapplicaties, de eerste stap van publieke offerteformulieren "
           "van verzekeraars en een documentlezer (product_ui; consumentenschermen, geen backoffice) en "
           "marketing- of informatiepagina's van Nederlandse financiele partijen (marketing).")
DOEL = ("Opnamen van publiek toegankelijke Nederlandse financiele en administratieve pagina's, "
        "per bron geclassificeerd (product_ui | marketing). Bedoeld als NL-domeinmaatstaf, met de "
        "kanttekening in dekking_categorie.")

# ---------------------------------------------------------------- bronnen
# cat: vergelijker | verzekeraar | zakelijk-financieel | overheid | register | data
# `klasse`, `soort_scherm`, `wat_het_toont` (en `interface_elementen`) zijn het OORDEEL van de
# opnemer na het bekijken van de opname; ontbreken ze, dan telt de bron niet mee.
TARGETS: list[dict] = [
    dict(slug="independer-autoverzekering-vergelijken", name="Independer - autoverzekering vergelijken",
         cat="vergelijker", url="https://www.independer.nl/autoverzekering/intro.aspx"),
    dict(slug="independer-zorgverzekering-vergelijken", name="Independer - zorgverzekering vergelijken",
         cat="vergelijker", url="https://www.independer.nl/zorgverzekering/intro.aspx"),
    dict(slug="poliswijzer-autoverzekering", name="Poliswijzer - autoverzekeringen vergelijken",
         cat="vergelijker", url="https://www.poliswijzer.nl/autoverzekering"),
    dict(slug="pricewise-zorgverzekering", name="Pricewise - zorgverzekering vergelijken",
         cat="vergelijker", url="https://www.pricewise.nl/zorgverzekering/"),
    dict(slug="verzekeringskaarten-overzicht", name="Verzekeringskaarten.nl (verwijst naar de homepage van het Verbond van Verzekeraars)",
         cat="vergelijker", url="https://www.verzekeringskaarten.nl/"),
    dict(slug="centraalbeheer-autoverzekering", name="Centraal Beheer - autoverzekering",
         cat="verzekeraar", url="https://www.centraalbeheer.nl/verzekeringen/autoverzekering"),
    dict(slug="asr-orv-premie-berekenen", name="a.s.r. - overlijdensrisicoverzekering premie berekenen",
         cat="verzekeraar", wait_ms=4000,
         url="https://www.asr.nl/verzekeringen/levensverzekeringen/overlijdensrisicoverzekering/premie-berekenen",
         # alleen doorklikken naar de eerste stap van de publieke rekentool; er wordt niets ingevuld of verzonden
         # (de eerdere CSS-selector `button:has-text(...)` vond de knop niet, de rol-gebaseerde klik wel)
         steps=[{"klik_tekst": "Start berekening"}, {"wait": 5000}]),
    dict(slug="asr-autoverzekering", name="a.s.r. - autoverzekering",
         cat="verzekeraar", url="https://www.asr.nl/verzekeringen/autoverzekering"),
    dict(slug="klaverblad-autoverzekering", name="Klaverblad - autoverzekering",
         cat="verzekeraar", url="https://www.klaverblad.nl/autoverzekering"),
    dict(slug="eboekhouden-prijzen", name="e-Boekhouden.nl - prijzen/pakketten",
         cat="zakelijk-financieel", url="https://www.e-boekhouden.nl/prijzen"),
    dict(slug="exact-online", name="Exact Online - boekhoudsoftware",
         cat="zakelijk-financieel", url="https://www.exact.com/nl/software/exact-online"),
    dict(slug="exact-boekhouden", name="Exact - boekhouden (pakketten)",
         cat="zakelijk-financieel", url="https://www.exact.com/nl/producten/boekhouden"),
    dict(slug="kifid-klacht-indienen", name="Kifid - ik heb een klacht",
         cat="overheid", url="https://www.kifid.nl/ik-heb-een-klacht/"),
    dict(slug="zorgwijzer-vergelijken", name="Zorgwijzer - zorgverzekering vergelijken",
         cat="vergelijker", url="https://www.zorgwijzer.nl/vergelijken"),
    dict(slug="geld-nl-autoverzekering", name="Geld.nl - autoverzekering vergelijken",
         cat="vergelijker", url="https://www.geld.nl/autoverzekering"),
    dict(slug="overstappen-zorgverzekering", name="Overstappen.nl - zorgverzekering vergelijken",
         cat="vergelijker", url="https://www.overstappen.nl/zorgverzekering/"),
    dict(slug="digid-startscherm", name="DigiD - startpagina",
         cat="overheid", url="https://www.digid.nl/"),
    dict(slug="interpolis-autoverzekering", name="Interpolis - autoverzekering",
         cat="verzekeraar", url="https://www.interpolis.nl/autoverzekering"),
    dict(slug="nn-autoverzekering", name="Nationale-Nederlanden - autoverzekering",
         cat="verzekeraar", url="https://www.nn.nl/particulier/schadeverzekeringen/autoverzekering.htm"),
    dict(slug="anwb-autoverzekering", name="ANWB - autoverzekering",
         cat="verzekeraar", url="https://www.anwb.nl/verzekeringen/autoverzekering"),
    dict(slug="moneybird-prijzen", name="Moneybird - prijzen/pakketten",
         cat="zakelijk-financieel", url="https://www.moneybird.nl/prijzen"),
    dict(slug="moneybird-facturen", name="Moneybird - facturatie",
         cat="zakelijk-financieel", url="https://www.moneybird.nl/facturen"),
    dict(slug="rabobank-zakelijke-rekening", name="Rabobank - zakelijke betaalrekening",
         cat="zakelijk-financieel", url="https://www.rabobank.nl/zakelijk/betalen/zakelijke-rekening"),
    dict(slug="ing-zakelijke-rekening", name="ING - zakelijke rekening",
         cat="zakelijk-financieel", url="https://www.ing.nl/zakelijk/betalen/zakelijke-rekening"),
    dict(slug="kvk-zoeken-resultaten", name="KvK Handelsregister - zoekresultaten",
         cat="overheid", url="https://www.kvk.nl/zoeken/",
         steps=[{"fill": "input[type='search'], input[name='q'], input[placeholder*='Zoek']",
                 "value": "assurantie"},
                {"press": "Enter"}, {"wait": 3500}]),
    dict(slug="kifid-uitspraken-register", name="Kifid - uitsprakenregister",
         cat="overheid", url="https://www.kifid.nl/kifid-kennis-en-uitspraken/uitspraken/"),
    dict(slug="mijnpensioenoverzicht", name="Mijnpensioenoverzicht.nl - startpagina",
         cat="overheid", url="https://www.mijnpensioenoverzicht.nl/"),
    dict(slug="mijnoverheid-inloggen", name="MijnOverheid - startpagina",
         cat="overheid", url="https://mijn.overheid.nl/"),
    dict(slug="belastingdienst-zakelijk-btw", name="Belastingdienst - btw",
         cat="overheid", url="https://www.belastingdienst.nl/wps/wcm/connect/nl/btw/btw"),
    # --- toegevoegd na de audit: publieke zoek-/register-/dataapplicaties (geen account, geen login) ---
    dict(slug="afm-register-financiele-dienstverleners",
         name="AFM - register financiele dienstverleners (zoeken)", cat="register",
         url="https://www.afm.nl/nl-nl/sector/registers/vergunningenregisters/financiele-dienstverleners",
         wait_ms=4000,
         steps=[{"fill": "#inputKeywords", "value": "assurantie"}, {"click": "#btn-search-register"},
                {"wait": 5000}]),
    dict(slug="rechtspraak-uitspraken-zoeken", name="Rechtspraak.nl - zoeken in uitspraken", cat="register",
         url="https://uitspraken.rechtspraak.nl/", wait_ms=4000,
         steps=[{"fill": "#zoekterm", "value": "assurantietussenpersoon"}, {"press": "Enter"}, {"wait": 5000}]),
    dict(slug="data-overheid-datasets", name="data.overheid.nl - datasets zoeken", cat="data",
         url="https://data.overheid.nl/datasets", wait_ms=4000),
    dict(slug="cbs-statline-kerncijfers-wijken", name="CBS StatLine - Kerncijfers wijken en buurten", cat="data",
         url="https://opendata.cbs.nl/statline/#/CBS/nl/dataset/83765NED/table", wait_ms=10000),
    dict(slug="wetten-overheid-wft", name="wetten.overheid.nl - Wet op het financieel toezicht", cat="overheid",
         url="https://wetten.overheid.nl/BWBR0020368/", wait_ms=6000),
    # --- publieke offerteformulieren van verzekeraars: alleen de EERSTE stap, niets ingevuld of verzonden ---
    dict(slug="asr-autoverzekering-afsluiten", name="a.s.r. - autoverzekering afsluiten (stap 1: Je situatie)",
         cat="verzekeraar", url="https://www.asr.nl/autoverzekering/afsluiten", wait_ms=5000),
    dict(slug="ohra-autoverzekering-berekenen", name="OHRA - autoverzekering berekenen",
         cat="verzekeraar", url="https://www.ohra.nl/autoverzekering/berekenen", wait_ms=5000),
    dict(slug="unive-autoverzekering-berekenen", name="Univé - autoverzekering premie berekenen",
         cat="verzekeraar", url="https://www.unive.nl/autoverzekering", wait_ms=4000,
         steps=[{"klik_tekst": "Bereken je premie"}, {"wait": 7000}]),
    # FBTO en Klaverblad zijn verkend en bewust weggelaten: de FBTO-flow toont zonder invoer alleen een introscherm
    # (en na de doorklik een blanco pagina); de Klaverblad-calculator rendert leeg (alleen kop en zijblok).
    # --- in de verkenning geweigerd of geblokkeerd: NIET opnieuw geladen, niet omzeild, wel gemeld ---
    dict(slug="dnb-openbaar-register", name="DNB - openbaar register", cat="register",
         url="https://www.dnb.nl/openbaar-register/",
         overslaan="verkenning: eerste lading HTTP 200, tweede lading 'Access Denied' (WAF); niet opnieuw geprobeerd of omzeild"),
    dict(slug="woz-waardeloket", name="WOZ-waardeloket", cat="overheid",
         url="https://www.wozwaardeloket.nl/",
         overslaan="verkenning: HTTP 403; niet omzeild"),
    dict(slug="kadaster-bag-viewer", name="Kadaster - BAG Viewer", cat="overheid",
         url="https://bagviewer.kadaster.nl/lvbag/bag-viewer/",
         overslaan="verkenning: HTTP 403; niet omzeild"),
    dict(slug="cbs-dashboard-economie", name="CBS - dashboard economie", cat="overheid",
         url="https://www.cbs.nl/nl-nl/visualisaties/dashboard-economie",
         overslaan="verkenning: net::ERR_SSL_VERSION_OR_CIPHER_MISMATCH (server accepteert het TLS 1.2-profiel van "
                   "deze proxy niet); certificaatverificatie niet uitgezet, niet omzeild"),
]

for _t in TARGETS:
    _t.setdefault("id", _t["slug"])
    _t.setdefault("bron_naam", _t["name"])
    _t.setdefault("domein", "nl_financieel")
    _t.setdefault("taal", "nl")
    _t.setdefault("dekking_categorie", DEKKING)
    _t.setdefault("categorie", _t["cat"])

# ---------------------------------------------------------------------------
# Oordeel van de opnemer na het bekijken van de opnames (desktop en mobiel), 2026-09-29.
#   product_ui  scherm waarin je iets opzoekt of doet met echte bediening (zoekveld + filters + resultaten,
#               register, dataviewer, documentlezer). De titel van de site zegt niets: het gaat om wat IN
#               BEELD staat.
#   marketing   pagina om te informeren, te verkopen of naar een login te leiden (homepage, prijzen,
#               productpagina, vergelijker-landing met een invulwidget, inlogpoort), ook als er een
#               formulier of zoekveld in zit.
# Er is geen ingelogd Nederlands assurantie- of boekhoud-backoffice publiek vast te leggen; dat staat in
# `dekking_categorie`. `soort_scherm` maakt het onderscheid binnen de klassen filterbaar. De tekst beschrijft
# wat er in beeld staat, ook bij afgekeurde opnames. Bronnen zonder oordeel zijn niet geinspecteerd.
# ---------------------------------------------------------------------------
GEINSPECTEERD_OP = "2026-09-29"
BEOORDELING: dict[str, dict] = {
    "poliswijzer-autoverzekering": dict(klasse="marketing", soort_scherm="vergelijker_landing", wat_het_toont=(
        "Poliswijzer, 'Autoverzekering vergelijken 2026': groene landingspagina met een invulwidget (kenteken, "
        "geboortedatum, postcode, huisnummer, kilometers, schadevrije jaren, knop 'Vergelijk verzekeringen'), "
        "voordelenlijst, 'Top 5'-tabellen met verzekeraarslogo's en premies en klantreviews. Landing met "
        "formulier; de resultaatpagina van de vergelijker is niet vastgelegd.")),
    "pricewise-zorgverzekering": dict(klasse="marketing", soort_scherm="vergelijker_landing", wat_het_toont=(
        "Pricewise, 'Informatie over de zorgverzekering': blauwe kop, invulwidget (geslacht, geboortedatum, "
        "postcode, gezinsleden, knop 'Check je voordeel') en daaronder lopende uitleg met een zijblok 'Onze "
        "zekerheid'. Informatie- en landingspagina; geen resultaten.")),
    "verzekeringskaarten-overzicht": dict(klasse="marketing", soort_scherm="organisatie_homepage", wat_het_toont=(
        "Homepage van het Verbond van Verzekeraars (verzekeringskaarten.nl verwijst hierheen): fotohero 'De "
        "brancheorganisatie van verzekeraars', drie doorklikblokken (Data analytics, Zelfreguleringsoverzicht, Wat "
        "we voor leden doen) en een donker nieuwsblok. Organisatiehomepage, geen toepassing.")),
    "asr-orv-premie-berekenen": dict(klasse="product_ui", soort_scherm="formulier", wat_het_toont=(
        "a.s.r., stap 1 'Premie berekenen' van de publieke overlijdensrisico-premiecalculator (alleen doorgeklikt "
        "via 'Start berekening'; niets ingevuld of verzonden): flowkop met logo en vijfstaps-voortgang (Premie "
        "berekenen, Gegevens en iDIN check, Extra vragen, Samenvatting, Akkoord), een formulierkaart met "
        "'1 van 4'-voortgangsbalk, de vraag 'Wie wil je verzekeren?' met drie keuzerondjes (Mijzelf, Iemand anders, "
        "Mijzelf en iemand anders) en de knoppen 'Terug naar start' en 'Volgende vraag'; op mobiel overlapt de "
        "zwevende chatknop de knoppen deels. Weinig tekst, maar een volledige en echte formulierstap van een "
        "Nederlandse verzekeraar (geen backoffice).")),
    "asr-autoverzekering": dict(klasse="marketing", soort_scherm="productpagina", wat_het_toont=(
        "a.s.r., productpagina autoverzekering: hero met illustratie, kop 'Autoverzekering', knop 'Bereken je "
        "premie', snelkoppelingen (Inloggen, Schade melden, Service en contact, Groene kaart) en drie "
        "dekkingskaarten (WA, WA + Casco beperkt, WA + Casco allrisk).")),
    "klaverblad-autoverzekering": dict(klasse="marketing", soort_scherm="productpagina", wat_het_toont=(
        "Klaverblad, productpagina autoverzekering: fotohero met blok 'De Klaverblad Autoverzekering', "
        "waarderingsbadge 8,6, knoppen 'Ontvang passend advies' en 'Bereken uw premie', daarna uitleg over drie "
        "dekkingsvarianten (WA, WA+ beperkt casco, WA+ volledig casco).")),
    "eboekhouden-prijzen": dict(klasse="marketing", soort_scherm="prijzenpagina", wat_het_toont=(
        "e-Boekhouden.nl, 'Prijzen voor ondernemers': aanbiedingsblok '15 maanden GRATIS', pakketkaarten (ZZP "
        "Pakket, Standaard, Standaard + Facturen) met maandprijzen en actieknoppen, en een vergelijkingstabel van "
        "functies. Prijspagina van boekhoudsoftware; geen bedieningsscherm.")),
    "exact-online": dict(klasse="marketing", soort_scherm="productpagina", wat_het_toont=(
        "Exact Online, productpagina: kop 'Exact Online biedt compleet inzicht in je onderneming', foto met "
        "laptop, klantlogo's, fotostrook en een strook met kleine productschermen. Marketingpagina; de "
        "productschermen zijn illustraties.")),
    "exact-boekhouden": dict(klasse="marketing", soort_scherm="productpagina", wat_het_toont=(
        "Exact, pagina 'Boekhouden': kop 'Het meest complete boekhoudprogramma', foto, kernpunten, knoppen 'Probeer "
        "30 dagen gratis' en 'of bekijk de demo', klantlogo's en een strook met kleine productafbeeldingen. "
        "Marketingpagina.")),
    "kifid-klacht-indienen": dict(klasse="marketing", soort_scherm="informatiepagina", wat_het_toont=(
        "Kifid, 'Ik heb een klacht': informatiepagina met fotohero, kop 'Een financiele klacht? Kifid kan in veel "
        "gevallen helpen', zes doorklikblokken (Sneltest, Klachtbehandeling, Reglementen, Klachtformulier, "
        "Uitsprakenregister, Dienstverlenersregister) en hoofdmenu. Het klachtformulier zelf is niet "
        "vastgelegd.")),
    "zorgwijzer-vergelijken": dict(klasse="marketing", soort_scherm="afbeelding_zonder_pagina", wat_het_toont=(
        "Geen pagina: de server leverde een JPG-afbeelding (kleine vergelijkingstabel met drie aanbieders, "
        "gecentreerd op een zwarte achtergrond) in plaats van een HTML-pagina. Afgekeurd.")),
    "geld-nl-autoverzekering": dict(klasse="marketing", soort_scherm="vergelijker_landing", wat_het_toont=(
        "Geld.nl, 'Autoverzekering: zorgeloos de weg op': lange tekstpagina met een zijblok 'Autoverzekering "
        "vergelijken' (kentekenveld en knop 'Start vergelijken'), linkenlijsten en veel lopende uitleg.")),
    "overstappen-zorgverzekering": dict(klasse="marketing", soort_scherm="vergelijker_landing", wat_het_toont=(
        "Overstappen.nl, 'Zorgverzekering vergelijken 2026': groene landing met kikker-illustratie, "
        "invulwidget (postcode, geboortedatum, geslacht, knop 'Vergelijk zorgverzekeringen'), Trustpilot-score "
        "en nieuwsartikelen.")),
    "digid-startscherm": dict(klasse="marketing", soort_scherm="inlogpoort", wat_het_toont=(
        "DigiD.nl, startpagina: storingsmelding 'Inlogproblemen met de DigiD app?', oranje hero 'Laat zien wie je "
        "bent' met knoppen Aanvragen en Activeren, blokken 'Machtigen' en 'Code ontvangen' en 'Manieren van "
        "inloggen'. Informatie- en toegangspagina; er wordt niet ingelogd.")),
    "interpolis-autoverzekering": dict(klasse="marketing", soort_scherm="productpagina", wat_het_toont=(
        "Interpolis, productpagina autoverzekering: fotohero met kaart 'Interpolis Autoverzekeringen', "
        "prijsbadge, snelkoppelingen (Ruitschade, Autoschade, Zelf regelen) en drie dekkingskaarten.")),
    "anwb-autoverzekering": dict(klasse="marketing", soort_scherm="productpagina", wat_het_toont=(
        "ANWB, productpagina autoverzekering: hero met foto, waardering 8,2/10, kernpunten, knop 'Kies je "
        "autoverzekering', gele sectie met twee varianten (Veilig Rijden, Reguliere autoverzekering) en "
        "uitlegtekst.")),
    "moneybird-prijzen": dict(klasse="marketing", soort_scherm="prijzenpagina", wat_het_toont=(
        "Moneybird, prijzenpagina: kop 'Betaal alleen voor wat je nodig hebt', jaar/maand-schakelaar en "
        "pakketkaarten Start, Groei en Compleet met kenmerklijsten en knoppen. Prijspagina van "
        "boekhoudsoftware.")),
    "moneybird-facturen": dict(klasse="marketing", soort_scherm="productpagina", wat_het_toont=(
        "Moneybird, pagina 'Facturen': fotohero 'Slimme facturen. Professionele uitstraling.', "
        "kernboodschap 'Binnen 2 minuten professionele facturen' en drie kaarten met kleine "
        "productafbeeldingen (huisstijl, factuur, workflow). Marketingpagina; de afbeeldingen zijn "
        "illustraties.")),
    "kvk-zoeken-resultaten": dict(klasse="product_ui", soort_scherm="zoekresultaten", wat_het_toont=(
        "KvK Handelsregister, pagina 'Zoeken' met de zoekterm 'assurantie': zoekveld met spraakknop, "
        "filterchips (Alles, Handelsregister, Advies en inspiratie, Alle filters), '1434 resultaten' en "
        "resultaatkaarten (bedrijfsnaam, KvK-nummer, vestigingsnummer, adres, knop 'Bestel nu'). Echte "
        "zoektoepassing; publiek, zonder inlog.")),
    "kifid-uitspraken-register": dict(klasse="product_ui", soort_scherm="zoekresultaten", wat_het_toont=(
        "Kifid, Uitsprakenregister: links een zoekveld ('Zoek binnen uitspraken') en filtergroepen (categorie, "
        "instantie, periode), rechts '14810 uitspraken' met sorteermenu en uitspraakkaarten (tegen wie, datum, "
        "samenvatting, 'Lees verder', knop 'Bekijk volledige uitspraak (PDF)'). Echte zoektoepassing; publiek, "
        "zonder inlog.")),
    "mijnpensioenoverzicht": dict(klasse="marketing", soort_scherm="inlogpoort", wat_het_toont=(
        "Mijnpensioenoverzicht.nl, startpagina: fotohero 'Bekijk uw verwachte pensioen', inlogknoppen (DigiD, "
        "eIDAS) en zes nieuws- en uitlegkaarten. Toegangs- en informatiepagina; er wordt niet ingelogd.")),
    "mijnoverheid-inloggen": dict(klasse="marketing", soort_scherm="inlogpoort", wat_het_toont=(
        "MijnOverheid, startpagina: blauwe pagina met een onderhoudsmelding in een klein carrouselblok "
        "(niet schermvullend), knop 'Inloggen met DigiD' en uitleg 'Wat kunt u met MijnOverheid?' "
        "(Berichtenbox, Uw gegevens). Toegangspagina; er wordt niet ingelogd.")),
    "belastingdienst-zakelijk-btw": dict(klasse="marketing", soort_scherm="informatiepagina", wat_het_toont=(
        "Belastingdienst, onderwerp 'Btw (omzetbelasting)': fotohero, vier snelle blokken (aangifte, "
        "naheffingsaanslag, btw-nummer, post) en lange linklijsten per onderwerp. Informatiepagina zonder "
        "bediening.")),
    "afm-register-financiele-dienstverleners": dict(klasse="product_ui", soort_scherm="zoekresultaten",
                                                    wat_het_toont=(
        "AFM, 'Register financiele dienstverleners': bovenaan een uitlegpagina met zijnavigatie (ongeveer de "
        "eerste 1400 css-px), daaronder het paneel 'Doorzoek de registers' met zoekterm 'assurantie', "
        "exportlinks (CSV, XML), '653 resultaten' en een tweekoloms resultatentabel (statutaire naam, "
        "handelsnaam) met paginering. Echte registertoepassing; publiek, zonder inlog.")),
    "rechtspraak-uitspraken-zoeken": dict(klasse="product_ui", soort_scherm="zoekresultaten", wat_het_toont=(
        "Rechtspraak.nl, uitspraken zoeken met de zoekterm 'assurantietussenpersoon': donkere kop met "
        "themafoto, links 'Opnieuw zoeken', 'Huidige zoekopdracht', 'Verfijn zoekopdracht' en inklapbare "
        "filters, rechts 'Resultaten (1657)' met knoppen 'Compacte weergave' en 'Print', sorteermenu en "
        "resultaatkaarten (ECLI, datum uitspraak en publicatie, rechtsgebied, inhoudsindicatie). Echte "
        "zoektoepassing; publiek, zonder inlog.")),
    "data-overheid-datasets": dict(klasse="product_ui", soort_scherm="zoekresultaten", wat_het_toont=(
        "data.overheid.nl, 'Datasets': zoekbalk, uitklapbare filtergroepen links (status, toegang, data-eigenaar, "
        "hoogwaardige dataset, thema, classificatie, groep, ...), '20.611 datasets' met sorteermenu, paginering "
        "en datasetkaarten (titel, beschrijving, data-eigenaar, bijgewerkt, thema, links Informatie en "
        "Databronnen). Echte catalogus- en zoektoepassing; publiek, zonder inlog.")),
    "cbs-statline-kerncijfers-wijken": dict(klasse="product_ui", soort_scherm="dataviewer", wat_het_toont=(
        "CBS StatLine, tabel 'Kerncijfers wijken en buurten 2017': werkbalk (info, delen, downloaden, "
        "tabel- en grafiekweergave), een lichtblauwe hint over het slepen van variabelen en een zeer dichte "
        "statistiektabel met regio-kolommen en tientallen rijen. Echte datatoepassing; publiek, zonder "
        "inlog.")),
    "asr-autoverzekering-afsluiten": dict(klasse="product_ui", soort_scherm="formulier", wat_het_toont=(
        "a.s.r., stap 1 'Je situatie' van de publieke aanvraagflow autoverzekering (direct geladen; niets "
        "ingevuld of verzonden): flowkop met vijfstaps-voortgang (Je situatie, Kies je dekking, Je gegevens, Tot "
        "slot, Samenvatting), formulierkaart 'De auto die je wil verzekeren' met kentekenveld, keuze 'Weet je het "
        "aantal schadevrije jaren?' (Ja/Nee), 'Regelmatige bestuurder' (select) en 'Je gegevens' (kilometers per "
        "jaar, geboortedatum, postcode, huisnummer, toevoeging), een zijkaart 'Waarom onze verzekering?' met drie "
        "voordelen en een zwevende chatknop. Echt offerteformulier van een Nederlandse verzekeraar (geen "
        "backoffice).")),
    "ohra-autoverzekering-berekenen": dict(klasse="product_ui", soort_scherm="formulier", wat_het_toont=(
        "OHRA, pagina 'Autoverzekering berekenen' (direct geladen; niets ingevuld of verzonden): blauwe "
        "navigatiebalk, een promotieblok met illustratie ('1 jaar 10% korting') en daaronder de formulierkaarten "
        "'Je auto' (kentekenveld, vinkje 'Mijn kenteken is (nog) niet bekend', uitvoering), 'Je gegevens' "
        "(postcode, geboortedatum), 'Gegevens auto' (schadevrije jaren, kilometers per jaar), 'Regelmatige "
        "bestuurder' en 'Collectief voordeel' (werkgever, actiecode), met een zijkolom 'Een autoverzekering die "
        "precies bij je past' en een zwevende chatknop. Echt offerteformulier van een Nederlandse verzekeraar "
        "(geen backoffice); de bovenste helft van het eerste scherm is een promotiebanner.")),
    "unive-autoverzekering-berekenen": dict(klasse="product_ui", soort_scherm="formulier", wat_het_toont=(
        "Univé, stap 1 'Basisgegevens' van de premieberekening autoverzekering (doorgeklikt via 'Bereken je "
        "premie'; niets ingevuld of verzonden): kop 'Uw autoverzekering', vijfstaps-voortgang (Basisgegevens, "
        "Premie berekenen, Uw situatie, Uw gegevens, Bijna verzekerd), formulierkaart met kentekenveld, keuze "
        "nieuw/tweedehands, 'Gegevens hoofdbestuurder' (Ikzelf/Mijn partner/Mijn kind/Iemand anders, "
        "geboortedatum, postcode), de vraag naar een bestaande Univé-auto, 'Uw no-claim korting berekenen' "
        "(schadevrije jaren) en de knop 'Volgende: premie berekenen', plus zijkaarten 'Vragen?' en 'De zekerheid "
        "van Univé'. De keuzes 'Ikzelf' en 'Nee' staan standaard geselecteerd. Echt offerteformulier van een "
        "Nederlandse verzekeraar (geen backoffice).")),
    "wetten-overheid-wft": dict(klasse="product_ui", soort_scherm="document_lezer", wat_het_toont=(
        "Wettenbank, 'Wet op het financieel toezicht': blauwe hoofdnavigatie, zoeklinks, inhoudsopgave met "
        "uitklapbare delen links, regelingkop met actieknoppen (link, opslaan, print, download), "
        "artikelblokken en daarna vrijwel uitsluitend lopende wettekst (de pagina is afgekapt op 10.000 "
        "css-px; de hele wet is ruim 700.000 css-px lang). Echte documentlezer; publiek, zonder inlog.")),
}
for _t in TARGETS:
    if _t["slug"] in BEOORDELING:
        _t.update(BEOORDELING[_t["slug"]])
        _t.setdefault("geinspecteerd_op", GEINSPECTEERD_OP)


def bestandsnaam(t: dict, vp: str) -> str:
    return f"{t['slug']}-desktop-1440x900.png" if vp == "desktop" else f"{t['slug']}-mobile-390x844.png"


def _kaart(t: dict) -> dict:
    k = dict(t)
    k["_concept"] = not t.get("wat_het_toont")
    return k


def maak_bron(t: dict, recs: dict[str, dict]) -> dict:
    """Bronniveau-object met de per-viewport opnamerecords onder `bestanden`."""
    d, m = recs.get("desktop"), recs.get("mobile")
    hoofd = d or m or {}
    bestanden = {}
    for vp, r in recs.items():
        r = dict(r)
        r["file"] = r.get("bestand")                 # oude alias die het harnas leest
        r["device_scale_factor"] = cc.DEVICE_SCALE
        r["full_page"] = True
        r["bytes"] = r.get("bestandsgrootte_bytes")
        bestanden[vp] = r
    ok = bool(recs) and all(r["geladen_ok"] for r in recs.values())
    redenen = list(dict.fromkeys(c for r in recs.values() for c in r["afkeurredenen"]))
    oms = t.get("wat_het_toont") or "NOG NIET GEINSPECTEERD"
    return {
        "slug": t["slug"], "id": t["slug"], "naam": t["name"], "bron_naam": t["bron_naam"],
        "categorie": t["cat"], "bron_url": t["url"], "eind_url": hoofd.get("eind_url"),
        "pagina_titel": hoofd.get("titel"), "http_status": hoofd.get("http_status"),
        "vastgelegd_op": hoofd.get("vastgelegd_op"),
        "klasse": t.get("klasse"), "domein": t["domein"], "taal": hoofd.get("taal") or t["taal"],
        "soort_scherm": t.get("soort_scherm"), "toegang": t.get("toegang"),
        "geladen_ok": ok, "afkeurredenen": redenen,
        "wat_het_toont": oms, "interface_elementen": oms,
        "geinspecteerd_op": t.get("geinspecteerd_op"),
        "dekking_categorie": t["dekking_categorie"],
        "bestanden": bestanden,
        "notities": "; ".join(f"{vp}: {r['controle']['cookies']['beschrijving']}" for vp, r in recs.items()
                              if r.get("controle", {}).get("cookies")),
    }


def leg_bron_vast(browser, t: dict, pauze: float) -> tuple[dict | None, dict | None]:
    """(bron, overgeslagen). Precies een van beide is gevuld."""
    kaart = _kaart(t)
    if t.get("overslaan"):
        return None, _overgeslagen(t, t["overslaan"], ["verkend_geweigerd"])
    geblokkeerd = cc.host_geblokkeerd(t["url"])
    if geblokkeerd:
        return None, _overgeslagen(t, geblokkeerd, ["bekend_geblokkeerd"])
    recs: dict[str, dict] = {}
    for i, vp in enumerate(cc.VIEWPORT_NAMEN):
        if i:
            time.sleep(cc.PAUZE_TUSSEN_LADINGEN_S)
        bestand = bestandsnaam(t, vp)
        t0 = time.time()
        raw = cc.leg_vast(browser, kaart, vp, OUT_DIR, bestand, wacht_ms=t.get("wait_ms", 3000),
                          stappen=t.get("steps"), locale="nl-NL", accept_language="nl-NL,nl;q=0.9,en;q=0.6")
        if not (OUT_DIR / bestand).exists():
            reden = raw.get("fout") or "geen opname gemaakt"
            code = "http_" + reden.split()[-1] if reden.startswith("HTTP") else "capture_mislukt"
            print(f"SKIP {bestand:<60} {reden}", flush=True)
            if not recs:                                     # al de eerste lading faalde: hele bron overslaan
                return None, _overgeslagen(t, reden, [code])
            # desktop is gelukt, mobiel niet: de goede opname blijft, mobiel krijgt een record zonder bestand
            recs[vp] = cc.record_zonder_bestand(kaart=kaart, viewport_naam=vp, reden=reden, codes=[code])
            break
        rec = cc.bouw_record(kaart=kaart, viewport_naam=vp, bestand=bestand, map_pad=OUT_DIR, raw=raw)
        rec["duur_s"] = round(time.time() - t0, 1)
        recs[vp] = rec
        print(f'{"OK  " if rec["geladen_ok"] else "AFK "} {rec["bestand"]:<60} '
              f'{",".join(rec["afkeurredenen"]) or "schoon"}', flush=True)
    return maak_bron(t, recs), None


def _overgeslagen(t: dict, reden: str, codes: list[str]) -> dict:
    return {"slug": t["slug"], "id": t["slug"], "naam": t["name"], "bron_naam": t["bron_naam"],
            "url": t["url"], "categorie": t["cat"], "bestand": None, "geladen_ok": False,
            "afkeurredenen": codes, "afkeurreden": reden, "reden": reden,
            "klasse": None, "domein": t["domein"], "taal": None, "viewport_naam": "desktop",
            "wat_het_toont": f"NIET VASTGELEGD: {reden}", "vastgelegd_op": cc.nu_iso(),
            "dekking_categorie": t["dekking_categorie"],
            "controle": {"schema": cc.SCHEMA_VERSIE, "controle_versie": cc.CONTROLE_VERSIE,
                         "beeld": None, "overgeslagen": True}}


def herbouw_bron(t: dict, vorig: dict) -> tuple[dict | None, dict | None]:
    """--alleen-manifest: uit opgeslagen feiten + PNG's, zonder netwerk."""
    for s in vorig.get("overgeslagen", []):
        if s.get("slug") == t["slug"]:
            reden = s.get("reden") or s.get("afkeurreden") or "overgeslagen"
            nieuw = _overgeslagen(t, reden, s.get("afkeurredenen") or ["capture_mislukt"])
            if s.get("vastgelegd_op"):
                nieuw["vastgelegd_op"] = s["vastgelegd_op"]      # een herbouw verandert het tijdstip van de vaststelling niet
            return None, nieuw
    oud = next((c for c in vorig.get("comps", []) if c["slug"] == t["slug"]), None)
    if oud is None:
        return None, None
    kaart = _kaart(t)
    recs = {}
    for vp, r in (oud.get("bestanden") or {}).items():
        b = bestandsnaam(t, vp)
        if not (OUT_DIR / b).exists() and not (OUT_DIR / cc.AFGEKEURD_MAP / b).exists():
            recs[vp] = r                                     # was overgeslagen (geen PNG): regel behouden
            continue
        recs[vp] = cc.bouw_record(kaart=kaart, viewport_naam=vp, bestand=b,
                                  map_pad=OUT_DIR, raw=cc.raw_uit_record(r))
    return maak_bron(t, recs), None


def main() -> int:
    global OUT_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--only", default="")
    ap.add_argument("--alleen-manifest", action="store_true", help="geen netwerk: herbereken het manifest")
    ap.add_argument("--pauze", type=float, default=4.0, help="seconden pauze tussen bronnen")
    args = ap.parse_args()
    OUT_DIR = Path(args.out).resolve()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    todo = [t for t in TARGETS if not only or t["slug"] in only]
    mpath = OUT_DIR / "manifest.json"
    vorig = {}
    if mpath.exists():
        try:
            vorig = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            vorig = {}

    bronnen: dict[str, dict] = {c["slug"]: c for c in vorig.get("comps", [])}
    skipped: dict[str, dict] = {s["slug"]: s for s in vorig.get("overgeslagen", [])}
    if args.alleen_manifest:
        for t in todo:
            b, s = herbouw_bron(t, vorig)
            _verwerk(t, b, s, bronnen, skipped)
    else:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = cc.start_browser(pw)
            for n, t in enumerate(todo):
                if n:
                    time.sleep(args.pauze)
                b, s = leg_bron_vast(browser, t, args.pauze)
                _verwerk(t, b, s, bronnen, skipped)
            browser.close()

    volgorde = {t["slug"]: i for i, t in enumerate(TARGETS)}
    comps = sorted((c for c in bronnen.values() if c["slug"] in volgorde), key=lambda c: volgorde[c["slug"]])
    overgeslagen = sorted((s for s in skipped.values() if s["slug"] in volgorde), key=lambda s: volgorde[s["slug"]])
    n_files = sum(len(c["bestanden"]) for c in comps)
    n_ok = sum(1 for c in comps for r in c["bestanden"].values() if r["geladen_ok"])
    manifest = {
        "set": "comps_nl",
        "schema_versie": cc.SCHEMA_VERSIE,
        "doel": DOEL,
        "dekking_categorie": DEKKING,
        "gegenereerd_op": cc.nu_iso(),
        "generator": "scripts/capture_comps_nl.py (Playwright/Chromium 1194) + scripts/capture_controle.py",
        "viewports": {"desktop": {"width": 1440, "height": 900, "device_scale_factor": 2, "full_page": True},
                      "mobile": {"width": 390, "height": 844, "device_scale_factor": 2, "full_page": True}},
        "cookie_afhandeling": ("Alleen als de DOM een blokkerende overlay toont: eerst klikken, dan bekende "
                               "containers met CSS verbergen, dan consent-overlays met JS verbergen. "
                               "Per opname staat in controle.cookies wat er GEMETEN is gebeurd; een bewering "
                               "als 'geklikt' staat er alleen als de overlay daarna aantoonbaar weg was."),
        "leesvoorbeeld": cc.leesvoorbeeld(
            "manifest['comps'] = lijst bronnen; per bron manifest['comps'][i]['bestanden']['desktop'|'mobile'] is een "
            "opnamerecord (oude alias 'file'); bronnen die niet zijn vastgelegd staan in manifest['overgeslagen'] "
            "(bestand null, met reden)"),
        "aantal_comps": len(comps),
        "aantal_bestanden": n_files,
        "aantal_geladen_ok": n_ok,
        "comps": comps,
        "overgeslagen": overgeslagen,
    }
    cc.schrijf_json(mpath, manifest)
    print(f"\n{len(comps)} bronnen, {n_files} bestanden ({n_ok} geladen_ok) -> {mpath}")
    print(f"{len(overgeslagen)} overgeslagen")
    for c in comps:
        for vp, r in c["bestanden"].items():
            if not r["geladen_ok"]:
                print(f"  afgekeurd: {c['slug']:<42} {vp:<8} {r.get('afkeurreden', '')}")
    return 0


def _verwerk(t: dict, b: dict | None, s: dict | None, bronnen: dict, skipped: dict) -> None:
    if b is not None:
        bronnen[t["slug"]] = b
        skipped.pop(t["slug"], None)
    elif s is not None:
        skipped[t["slug"]] = s
        bronnen.pop(t["slug"], None)


if __name__ == "__main__":
    sys.exit(main())
