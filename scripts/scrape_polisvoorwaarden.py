#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape_polisvoorwaarden.py - bouwt corpus/polisvoorwaarden.json

Bronnen: publiek gepubliceerde polisvoorwaarden-PDF's op de eigen domeinen van
Nederlandse verzekeraars. Geen tussenpersoon-kopieen, geen samenvattingen.

  Klaverblad Verzekeringen   www.klaverblad.nl/voorwaarden-*.pdf
  Univé (N.V. Univé Schade)  www.unive.nl/binaries/.../voorwaarden-*.pdf
  Interpolis (Achmea)        www.interpolis.nl/-/media/files/*.pdf
  a.s.r.                     www.asr.nl/asr/api/asrnl/pod/getpdf?uri=...

Elke clausuletekst wordt met een (start, eind) markerpaar uit de gedownloade PDF
gesneden; markers moeten uniek zijn. Niets wordt met de hand ingetypt of
geparafraseerd. Ontbreekt een marker (bijv. na een nieuwe documentversie), dan
faalt het script luid in plaats van stil verouderde tekst te leveren.

Gebruik:
    python3 scripts/scrape_polisvoorwaarden.py [--out PAD] [--geen-verificatie]
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from polisvoorwaarden_lib import (BronFout, fetch_pdf, knip, pdf_text, sha256,  # noqa: E402
                                  strip_toc, verify_200)

# ---------------------------------------------------------------- bronnen

DOCS = {
    "kb_avp": {
        "url": "https://www.klaverblad.nl/voorwaarden-aansprakelijkheid.pdf",
        "verzekeraar": "Klaverblad Verzekeringen",
        "document": "Aansprakelijkheidsverzekering voor particulieren, Polisvoorwaarden nr. AP 18 (AVWAP18/1908)",
        "product": "aansprakelijkheidsverzekering particulieren (AVP)",
    },
    "kb_woonhuis": {
        "url": "https://www.klaverblad.nl/voorwaarden-woonhuis.pdf",
        "verzekeraar": "Klaverblad Verzekeringen",
        "document": "Royaal woonhuisverzekering, Polisvoorwaarden BW 22 (AVWBW/2210)",
        "product": "opstalverzekering",
    },
    "kb_inboedel": {
        "url": "https://www.klaverblad.nl/voorwaarden-inboedel.pdf",
        "verzekeraar": "Klaverblad Verzekeringen",
        "document": "Inboedelverzekering, Polisvoorwaarden BI 24 (AVWBI/2409)",
        "product": "inboedelverzekering",
    },
    "kb_auto": {
        "url": "https://www.klaverblad.nl/voorwaarden-auto.pdf",
        "verzekeraar": "Klaverblad Verzekeringen",
        "document": "Klaverblad Autoverzekering, Polisvoorwaarden AU24 (AVWAU/2404)",
        "product": "autoverzekering (WA/casco)",
    },
    "kb_rb": {
        "url": "https://www.klaverblad.nl/voorwaarden-rechtsbijstand.pdf",
        "verzekeraar": "Klaverblad Verzekeringen",
        "document": "Rechtsbijstandverzekering voor particulieren, Polisvoorwaarden nr. RB 18",
        "product": "rechtsbijstandverzekering",
    },
    "kb_reis": {
        "url": "https://www.klaverblad.nl/voorwaarden-reis.pdf",
        "verzekeraar": "Klaverblad Verzekeringen",
        "document": "Doorlopende reisverzekering, Polisvoorwaarden nr. DR 22 (AVWDR22/2301)",
        "product": "reisverzekering",
    },
    "unive_woon": {
        "url": "https://www.unive.nl/binaries/br/content/assets/particulier-sales/woonverzekering/voorwaarden-unive-woonverzekering-versie-4.1.pdf",
        "verzekeraar": "Univé (N.V. Univé Schade)",
        "document": "Voorwaarden Woonverzekering versie 4.1 (2043.04.26)",
        "product": "opstal-/inboedelverzekering (woonverzekering)",
    },
    "unive_av": {
        "url": "https://www.unive.nl/binaries/br/content/assets/particulier-sales/generiek/algemene_voorwaarden.pdf",
        "verzekeraar": "Univé (N.V. Univé Schade)",
        "document": "Algemene voorwaarden Univé, versie 4 (2000.01.24)",
        "product": "algemene voorwaarden schadeverzekering",
    },
    "ip_av": {
        "url": "https://www.interpolis.nl/-/media/files/av-02-251.pdf",
        "verzekeraar": "Interpolis (Achmea Schadeverzekeringen N.V.)",
        "document": "Particuliere verzekeringen, Algemene voorwaarden AV-02-251 (december 2025)",
        "product": "algemene voorwaarden schadeverzekering",
    },
    "ip_casco": {
        "url": "https://www.interpolis.nl/-/media/files/pav-rv-58-252.pdf",
        "verzekeraar": "Interpolis (Achmea Schadeverzekeringen N.V.)",
        "document": "Autoverzekering, Verzekeringsvoorwaarden WA + Volledig Casco PAV-RV-58-252 (december 2025)",
        "product": "autoverzekering (WA/casco)",
    },
    "asr_aov": {
        # Model 221 (42435) is door a.s.r. uit de lijst gehaald (HTTP 404). Model 231 is de
        # opvolger op https://www.asr.nl/arbeidsongeschiktheidsverzekering/overzicht-voorwaarden-en-vergoedingen
        "url": "https://www.asr.nl/asr/api/asrnl/pod/getpdf?uri=/POD/r/Pdf/44141_2025.pdf",
        "verzekeraar": "a.s.r. (ASR Schadeverzekering N.V.)",
        "document": "Voorwaarden arbeidsongeschiktheidsverzekering model 231 (44141_2025)",
        "product": "arbeidsongeschiktheidsverzekering (AOV)",
    },
}

# ---------------------------------------------------------------- clausules
# (doc, clausule_id, kop, type, startmarker, eindmarker[, kap])
# `kap` = aanloop die na het snijden van de clausuletekst wordt afgeknipt; nodig
# als de marker alleen uniek is met het kopje erbij.
CLAUSULES = [
    # --- AVP, Klaverblad AP 18 ---
    ("kb_avp", "art. 2.4", "Wat is verzekerd? - particuliere hoedanigheid", "dekking",
     "4. U bent verzekerd als particulier.", "5. U bent meestal niet aansprakelijk"),
    ("kb_avp", "art. 2.7", "Wat is verzekerd? - gebeurtenis voor de ingangsdatum", "uitsluiting",
     "7. Schade ontstaat door een gebeurtenis", "8. Soms is de schade verzekerd op meer verzekeringen."),
    ("kb_avp", "art. 2.8", "Wat is verzekerd? - samenloop met andere verzekeringen", "schaderegeling",
     "8. Soms is de schade verzekerd op meer verzekeringen.", "Artikel 3 Verzekerd bedrag en verzekerde kosten"),
    ("kb_avp", "art. 6.1", "Aansprakelijkheid voor schade met motorrijtuigen of elobikes", "uitsluiting",
     "1. Iemand kan u aansprakelijk stellen voor schade die met of door een motorrijtuig is gemaakt.",
     "2. Iemand kan u aansprakelijk stellen voor schade die met of door een elobike is gemaakt."),
    ("kb_avp", "art. 10.1", "Uitsluitingen - opzet, wetsovertreding en seksuele gedragingen", "uitsluiting",
     "1. a. U bent niet verzekerd in de volgende gevallen.", "2. U bent niet verzekerd als de aansprakelijkheid"),
    ("kb_avp", "art. 10.2", "Uitsluitingen - molest, atoomkernreacties en natuurrampen", "uitsluiting",
     "2. U bent niet verzekerd als de aansprakelijkheid verband houdt met molest",
     "3. Wij betalen niets en u krijgt geen rechtshulp als u of een belanghebbende"),
    ("kb_avp", "art. 11.1", "Verplichtingen bij schade - meldtermijn", "verjaring",
     "1. U moet een schade zo snel mogelijk aan ons melden.", "2. Bij schade of dreigende schade"),
    ("kb_avp", "art. 11.3", "Verplichtingen bij schade - medewerking", "verplichting verzekerde",
     "3. Bij schade moet u meewerken aan het vaststellen en regelen van de schade.",
     "4. Als u zich niet houdt aan deze verplichtingen, dan kunnen wij daar nadeel van hebben."),
    ("kb_avp", "art. 11.4", "Verplichtingen bij schade - sanctie bij niet nakomen", "verplichting verzekerde",
     "4. Als u zich niet houdt aan deze verplichtingen, dan kunnen wij daar nadeel van hebben.",
     "Artikel 12 Schade regelen met de tegenpartij"),

    # --- opstal / woonhuis, Klaverblad BW 22 ---
    ("kb_woonhuis", "Algemeen art. 4.1", "Wat moet u doen bij schade?", "verplichting verzekerde",
     "1. Heeft u schade of dreigt er schade te ontstaan? Dan gelden de volgende verplichtingen:",
     "2. Als u zich niet houdt aan de bepalingen in lid 1"),
    ("kb_woonhuis", "Algemeen art. 4.2", "Gevolgen van het niet nakomen van de schadeverplichtingen", "verplichting verzekerde",
     "2. Als u zich niet houdt aan de bepalingen in lid 1, kunnen wij daar nadeel van hebben.",
     "Artikel 5 Inschakeling van een expert"),
    ("kb_woonhuis", "Woonhuis art. 2.2", "Voor welk bedrag bent u verzekerd? - herbouwwaarde", "schaderegeling",
     "2. Het verzekerde bedrag is maximaal de herbouwwaarde", "3. In sommige gevallen kunt u kiezen voor een garantie tegen onderverzekering."),
    ("kb_woonhuis", "Woonhuis art. 10 sub b", "Wat vergoeden we niet? - natuur- en weersinvloeden", "uitsluiting",
     "b. We vergoeden geen schade die is ontstaan door de volgende natuur- en weersinvloeden:",
     "c. Wij vergoeden geen schade die is ontstaan door vervuiling door stoffen in de lucht."),
    ("kb_woonhuis", "Woonhuis art. 10 sub f", "Wat vergoeden we niet? - opzet, roekeloosheid, ernstige schuld", "uitsluiting",
     "f. We vergoeden geen schade die is ontstaan door opzet, roekeloosheid of ernstige schuld",
     "g. We vergoeden geen schade die is ontstaan door of tijdens strafbare activiteiten."),
    ("kb_woonhuis", "Woonhuis art. 10 sub h", "Wat vergoeden we niet? - achterstallig onderhoud", "uitsluiting",
     "h. We vergoeden geen schade die het gevolg is van achterstallig onderhoud.",
     "i. We vergoeden geen schade die het gevolg is van ondeskundig uitgevoerde werkzaamhe"),
    ("kb_woonhuis", "Woonhuis art. 10 sub j", "Wat vergoeden we niet? - constructiefouten en eigen gebrek", "uitsluiting",
     "j. We vergoeden geen schade die het gevolg is van constructiefouten",
     "k. We vergoeden geen schade die het gevolg is van verzakking"),
    ("kb_woonhuis", "Woonhuis art. 11.1", "Schadevergoeding - herstelkosten of verkoopwaarde", "schaderegeling",
     "1. Bij schade vergoeden wij meestal de herstelkosten.", "2. Als de verkoopwaarde hoger is dan de herstelkosten"),
    ("kb_woonhuis", "Woonhuis art. 11.6", "Schadevergoeding - onderverzekering en evenredigheid", "schaderegeling",
     "6. Is uw verzekerd bedrag lager dan de herbouwwaarde van uw woonhuis?",
     "7. De garantie tegen onderverzekering geldt niet in de volgende gevallen:"),
    ("kb_woonhuis", "Woonhuis art. 11.7", "Wanneer de garantie tegen onderverzekering vervalt", "schaderegeling",
     "7. De garantie tegen onderverzekering geldt niet in de volgende gevallen:",
     "8. Is uw schade op meer verzekeringen verzekerd?"),
    ("kb_woonhuis", "Woonhuis art. 11.9", "Schadevergoeding - eigen risico", "eigen risico",
     "9. Heeft u een eigen risico, dan trekken wij dit af van het bedrag dat wij vergoeden.",
     "10. Wij betalen geen wettelijke rente"),

    # --- inboedel, Klaverblad BI 25 ---
    ("kb_inboedel", "art. 1.7.2", "Wat bent u verplicht te doen bij schade?", "verplichting verzekerde",
     "Heeft u schade of dreigt er schade te ontstaan? Hieronder leest u wat u in dat geval verplicht bent te doen.",
     "Het is belangrijk dat u zich goed aan de verplichtingen in dit artikel houdt."),
    ("kb_inboedel", "art. 1.7.3", "Termijn om te reageren op onze beslissing", "verjaring",
     "Bent u het niet eens met onze beslissing? Laat het ons dan zo snel mogelijk weten, maar uiterlijk",
     "Registratie van uw schademelding"),
    ("kb_inboedel", "art. 2.6.3", "Voor welk bedrag bent u verzekerd? - onderverzekering", "schaderegeling",
     "3. Is het verzekerde bedrag lager dan de totale waarde van uw inboedel?",
     "4. In sommige gevallen kunt u kiezen voor een garantie tegen onderverzekering."),
    ("kb_inboedel", "art. 2.16 sub f", "Wat vergoeden we niet? - strafbare/illegale activiteiten", "uitsluiting",
     "f. We vergoeden geen schade die is ontstaan door of tijdens strafbare activiteiten.",
     "g. We vergoeden geen schade die het gevolg is van achterstallig onderhoud."),
    ("kb_inboedel", "art. 2.16 sub n", "Wat vergoeden we niet? - normaal dagelijks gebruik", "uitsluiting",
     "n. We vergoeden geen schade die het gevolg is van normaal dagelijks gebruik van uw spullen.",
     "o. We vergoeden geen schade doordat spullen vanzelf kapot gaan."),
    ("kb_inboedel", "art. 2.17.3", "Schadevergoeding - wanneer nieuwwaarde", "schaderegeling",
     "3. We vergoeden de nieuwwaarde als voldaan is aan de volgende 3 voorwaarden:",
     "4. We vergoeden de dagwaarde als het gaat om de volgende spullen:"),
    ("kb_inboedel", "art. 2.17.10", "Schadevergoeding - onderverzekering en evenredigheid", "schaderegeling",
     "10. Is het verzekerde bedrag lager dan de totale waarde van uw inboedel? Dan bent u onderver",
     "11. De garantie tegen onderverzekering geldt niet in de volgende gevallen:"),
    ("kb_inboedel", "art. 2.17.14", "Schadevergoeding - eigen risico", "eigen risico",
     "14. Heeft u een eigen risico? Dan trekken wij dit af van het bedrag dat wij vergoeden.",
     "15. Wij vergoeden geen wettelijke rente"),

    # --- auto, Klaverblad ---
    ("kb_auto", "art. 1.7.2", "Wat bent u verplicht te doen bij schade?", "verplichting verzekerde",
     "Heeft u schade of dreigt er schade te ontstaan? Hieronder leest u wat u in dat geval verplicht bent te doen.",
     "Het is belangrijk dat u zich goed aan de verplichtingen in dit artikel houdt."),
    ("kb_auto", "art. 1.7.3", "Termijn om te reageren op onze beslissing", "verjaring",
     "Bent u het niet eens met onze beslissing? Laat het ons dan zo snel mogelijk weten, maar uiterlijk",
     "Registratie van uw schademelding"),
    ("kb_auto", "art. 2.2.2", "Uitsluitingen - bestuurder, gebruik en tenaamstelling", "uitsluiting",
     "2. We vergoeden de schade niet in de volgende situaties:",
     "3. Een uitsluiting van lid a t/m g geldt niet als u bewijst"),
    ("kb_auto", "art. 2.2.3", "Uitsluitingen - tegenbewijs door verzekerde", "uitsluiting",
     "3. Een uitsluiting van lid a t/m g geldt niet als u bewijst dat u niets kon doen aan de situatie die daar is beschreven.",
     "4. Wij vergoeden geen schade als er sprake is van een uitsluiting in de algemene voorwaarden"),
    ("kb_auto", "art. 2.11.1", "Uitsluitingen module WA", "uitsluiting",
     "1. De volgende schades zijn niet verzekerd:\na. Schade door een losse aanhanger",
     "2. Wij verzekeren u niet als een uitsluiting van artikel 2.2 geldt.\n2.12 Schade regelen met de tegenpartij"),
    ("kb_auto", "art. 2.13.1", "U moet een schade terugbetalen (regres WAM)", "schaderegeling",
     "1. Het kan zijn dat wij volgens de Wet Aansprakelijkheidsverzekering Motorrijtuigen",
     "2. U hoeft de schade niet terug te betalen als u het volgende bewijst:"),
    ("kb_auto", "art. 2.18", "Eigen risico's module Casco", "eigen risico",
     "1. U heeft geen standaard eigen risico bij diefstal of totaal verlies van uw auto.",
     "2.19 Uitsluitingen module Casco"),
    ("kb_auto", "art. 2.19.1", "Uitsluitingen module Casco", "uitsluiting",
     "1. Wij vergoeden de volgende schade niet:\na. Schade door vermindering van de waarde van uw auto.",
     "2. Wij verzekeren u niet als een uitsluiting van artikel 2.2 geldt.\n2.20 Expert"),

    # --- rechtsbijstand, Klaverblad RB 18 ---
    ("kb_rb", "art. 6.2", "Uitsluitingen - wanneer krijgt u geen rechtshulp", "uitsluiting",
     "2. In de volgende gevallen krijgt u geen rechtshulp.",
     "3. U krijgt geen rechtshulp als uw juridische probleem te maken heeft met een van de volgende onderwerpen."),
    ("kb_rb", "art. 6.3", "Uitsluitingen - uitgesloten rechtsgebieden", "uitsluiting",
     "3. U krijgt geen rechtshulp als uw juridische probleem te maken heeft met een van de volgende onderwerpen.",
     "4. U krijgt geen rechtshulp als het juridische probleem verband houdt met molest"),
    ("kb_rb", "art. 7.1", "Verplichtingen bij een verzoek om rechtshulp - meldtermijn", "verjaring",
     "1. U moet een juridisch probleem zo snel mogelijk schriftelijk aan de Stichting melden.",
     "2. U moet meewerken aan de behandeling van uw juridische probleem."),
    ("kb_rb", "art. 7.4", "Gevolgen van het niet nakomen van de verplichtingen", "verplichting verzekerde",
     "4. Als u zich niet houdt aan deze verplichtingen, dan kan de Stichting daar nadeel van hebben.",
     "Artikel 8 Afwikkeling van een verzoek om rechtshulp"),

    # --- reis, Klaverblad ---
    ("kb_reis", "art. 6.1", "Uitsluitingen - te verwachten gebeurtenis, opzet, gevaarlijke activiteiten", "uitsluiting",
     "1. U bent niet verzekerd en wij verlenen geen hulp in de volgende gevallen.",
     "2. De uitsluitingen in lid 1 b, c en d gelden niet in de volgende gevallen:"),
    ("kb_reis", "art. 6.3", "Uitsluitingen - zakelijke reizen en professionele sport", "uitsluiting",
     "3. U bent niet verzekerd als u op reis bent voor uw bedrijf",
     "4. U bent niet verzekerd als uw schade of letsel verband houdt met molest"),
    ("kb_reis", "art. 7.1", "Verplichtingen bij schade", "verplichting verzekerde",
     "1. Wordt u tijdens uw vakantiereis getroffen door schade, dan heeft u de volgende verplich",
     "Artikel 8 Expert"),

    # --- Univé woonverzekering ---
    ("unive_woon", "art. 4.4.2", "Schade melden", "verplichting verzekerde",
     "Meld uw schade zo snel mogelijk bij Univé.", "4.4.3 Aanwijzingen opvolgen"),
    ("unive_woon", "art. 4.6.6", "Eigen risico", "eigen risico",
     "Wij halen uw eventuele eigen risico af van onze vergoeding.", "5. Wat verwachten wij van u?"),
    ("unive_woon", "art. 7.7", "Vergoedingsregelingen - premier risque en garantie tegen onderverzekering", "schaderegeling",
     "7.7 Vergoedingsregelingen Staat er op uw polis een bedrag waarvoor u bent verzekerd?",
     "Vergoedingsregeling andere zaken en gebouwen Toelichting", "7.7 Vergoedingsregelingen"),

    # --- Univé algemene voorwaarden ---
    ("unive_av", "art. 4.1.5", "Opzet", "uitsluiting",
     "Wij vergoeden geen schade als u in strijd met het recht met opzet iets doet of niet doet waardoor schade ontstaat.",
     "Wij kunnen de verzekering ook stoppen als er sprake is van opzet."),
    ("unive_av", "art. 9.1", "Wat zijn uw plichten als u schade heeft?", "verplichting verzekerde",
     "• Probeer altijd om meer schade te voorkomen of te beperken. Dit noemen wij beredding.",
     "9.2. Wat gebeurt er als u zich niet houdt aan de plichten bij schade?"),
    ("unive_av", "art. 9.3", "Hoe lang kunt u nog reageren als wij een schade niet vergoeden?", "verjaring",
     "Bent u het niet eens met onze beslissing? Laat ons dat dan weten.", "10. Privacy"),

    # --- Interpolis algemene voorwaarden ---
    ("ip_av", "art. 15", "Wat zijn de gevolgen als u te laat betaalt?", "schaderegeling",
     "Wij mogen de achterstallige premie in 1 keer opeisen.", "16. Wat als u de eerste premie niet betaalt?"),
    ("ip_av", "art. 16", "Wat als u de eerste premie niet betaalt?", "uitsluiting",
     "Dan komt er geen verzekering tot stand.", "Aanpassen van uw verzekering"),

    # --- Interpolis auto WA + Volledig Casco ---
    ("ip_casco", "art. 1.17", "Wanneer moet een verzekerde schade en kosten aan ons terugbetalen?", "schaderegeling",
     "Als wij een schade moeten betalen terwijl de verzekerde de polisvoorwaarden niet heeft nageleefd.",
     "1.18. Wat als de schade dubbel verzekerd is?"),
    ("ip_casco", "art. 1.18", "Wat als de schade dubbel verzekerd is?", "schaderegeling",
     "1.18. Wat als de schade dubbel verzekerd is? De andere verzekering gaat voor.",
     "1.19. Heeft een schade gevolgen voor uw premie?", "1.18. Wat als de schade dubbel verzekerd is?"),
    ("ip_casco", "art. 2.10", "Wanneer betaalt u zelf een deel van de schade (eigen risico)?", "eigen risico",
     "Bij schade betaalt u zelf het eigen risico.", "2.11. Wanneer is schade niet verzekerd?"),

    # --- a.s.r. AOV model 231 ---
    ("asr_aov", "art. 4.2", "Wat moet u doen als u arbeidsongeschikt bent?", "verplichting verzekerde",
     "- U moet ons zo snel mogelijk laten weten dat u arbeidsongeschikt bent.",
     "4.3 Wat zijn de gevolgen als u uw verplichtingen niet nakomt?"),
    ("asr_aov", "art. 4.3", "Wat zijn de gevolgen als u uw verplichtingen niet nakomt? (met verjaring na drie jaar)", "verjaring",
     "Komt u de verplichtingen uit artikel 4.2 ‘Wat moet u doen als u arbeidsongeschikt bent?’ niet na en worden wij in redelijk belang geschaad?",
     "4.4 Hoe wordt uw arbeidsongeschiktheid vastgesteld?"),
    ("asr_aov", "art. 5.1", "Wanneer heeft u recht op een uitkering bij arbeidsongeschiktheid?", "dekking",
     "U heeft recht op een uitkering als aan de volgende voorwaarden is voldaan:",
     "In bepaalde gevallen is er wel sprake van arbeidsongeschiktheid of een ongeval, maar is er toch geen dekking. We spreken dan van uitsluitingen. In hoofdstuk 7 ‘In welke bijzondere situaties heeft u geen recht op een uitkering?’ leest u hier meer over."),
    ("asr_aov", "art. 5.2", "Orgaandonatie: recht op uitkering en eigen risicotermijn", "eigen risico",
     "Orgaandonatie beschouwen we als arbeidsongeschiktheid.",
     "5.3 Wanneer heeft u recht op een uitkering bij zwangerschap en bevalling?"),
    ("asr_aov", "art. 7.1", "Uitsluiting opzet of roekeloosheid", "uitsluiting",
     "Er is geen dekking als:\n- u uw arbeidsongeschiktheid of ongeval met opzet of roekeloosheid zelf heeft veroorzaakt;",
     "7.2 Alcohol, geneesmiddelen, drugs, verdovende en opwekkende middelen"),
    ("asr_aov", "art. 7.2", "Uitsluiting alcohol, geneesmiddelen, drugs, verdovende en opwekkende middelen", "uitsluiting",
     "Er is geen dekking als:\n- het alcoholgehalte in uw bloed op het moment van een ongeval hoger is dan wettelijk mag;",
     "7.3 Detentie"),
    ("asr_aov", "art. 7.3", "Uitsluiting detentie", "uitsluiting",
     "Er is geen dekking als u in Nederland of in het buitenland:", "7.4 Molest"),
    ("asr_aov", "art. 7.4", "Uitsluiting molest", "uitsluiting",
     "Er is geen dekking als u arbeidsongeschikt bent geworden of een ongeval heeft gehad door molest.",
     "7.5 Atoomkernreactie"),
# --- Univé woonverzekering, aanvullend ---
    ("unive_woon", "art. 3.5 sub f", "Wat is niet verzekerd? - ontbreken vonkenvanger bij rieten dak", "uitsluiting",
     "Heeft uw woning een rieten dak en stookt u met vaste brandstoffen?",
     "g. Waterschade zoals hiernaast beschreven"),
    ("unive_woon", "art. 3.6.1", "Uw woning wordt gebouwd, verbouwd of gerenoveerd", "dekking",
     "Tijdens de aanbouw, verbouw of renovatie van uw woning bent u beperkt verzekerd",
     "3.6.2 Uw woning is onbewoond of staat leeg"),
    ("unive_woon", "art. 3.6.2", "Uw woning is onbewoond of staat leeg", "dekking",
     "Is uw woning langer dan drie maanden onbewoond", "3.6.3 Uw inboedel tijdens verhuizing"),
    ("unive_woon", "art. 3.6.4", "Verhuur van uw woning", "uitsluiting",
     "Verhuurt u uw woning, (recreatie)woning, een kamer of inboedel aan anderen dan",
     "3.7 Uw inboedel op een ander adres"),
    ("unive_woon", "art. 4.1", "Vaststellen schadebedrag", "schaderegeling",
     "Het schadebedrag stellen wij samen met u vast.", "4.2 (Contra-)expert of arbiter"),
    ("unive_woon", "art. 4.2", "(Contra-)expert of arbiter", "schaderegeling",
     "Twijfelt u aan het schadebedrag? Dan kunt u zelf ook een expert inschakelen.",
     "Goed om te weten: experts beslissen niet over de dekking"),

    # --- Interpolis algemene voorwaarden, aanvullend ---
    ("ip_av", "art. 7", "Wanneer is schade niet verzekerd?", "uitsluiting",
     "Schade door ernstige conflicten (molest). Bij ernstige conflicten, zoals een oorlog",
     "8. Bent u verzekerd voor schade door terrorisme?"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "..", "corpus", "polisvoorwaarden.json"))
    ap.add_argument("--geen-verificatie", action="store_true")
    ap.add_argument("--geen-cache", action="store_true")
    args = ap.parse_args()

    vandaag = dt.date.today().isoformat()
    teksten, http_status, digests = {}, {}, {}

    for key, meta in DOCS.items():
        path, status = fetch_pdf(meta["url"], use_cache=not args.geen_cache)
        teksten[key] = strip_toc(pdf_text(path))
        digests[key] = sha256(path)
        if args.geen_verificatie:
            http_status[key] = None
        else:
            ok, st = verify_200(meta["url"])
            if not ok:
                raise BronFout(f"{meta['url']} geeft geen 200/206 maar {st}")
            http_status[key] = 200
        print(f"[ok] {key:12s} {len(teksten[key]):7d} tekens  {meta['url']}", file=sys.stderr)

    records, fouten = [], []
    for rij in CLAUSULES:
        doc, cid, kop, soort, start, eind = rij[:6]
        kap = rij[6] if len(rij) > 6 else None
        meta = DOCS[doc]
        try:
            tekst = knip(teksten[doc], start, eind, bron_id=f"{doc} {cid}", kap=kap)
        except BronFout as e:
            fouten.append(str(e))
            continue
        records.append({
            "product": meta["product"],
            "verzekeraar_of_bron": meta["verzekeraar"],
            "document": meta["document"],
            "clausule_id": cid,
            "kop": kop,
            "tekst": tekst,
            "type": soort,
            "bron_url": meta["url"],
            "bron_http_status": http_status[doc],
            "bron_pdf_sha256": digests[doc],
            "opgehaald_op": vandaag,
        })

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n{len(records)} clausules -> {out}", file=sys.stderr)
    if fouten:
        print(f"\n{len(fouten)} MISLUKTE extracties:", file=sys.stderr)
        for e in fouten:
            print("  " + e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
