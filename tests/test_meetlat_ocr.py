"""
OCR-lekcontrole (audit-punt 2): de bron is af te lezen uit tekst in het beeld. Deze tests
gebruiken synthetische beelden (PIL) en de echte OCR-engines; het eerste deel (matcher) heeft
geen engine nodig.

Elke detectie heeft een tegenproef: een schoon beeld, een engine die niets ziet, of het
gemaskeerde beeld dat de controle moet doorstaan.
"""
from __future__ import annotations

import random

import numpy as np
import pytest
from PIL import Image, ImageDraw

from test_meetlat_hulp import (NietsZienEngine, ZietTekstAlsErContrastIsEngine, blind_ab, bouw_bronnen,
                               cli_args, haal_ocr_engines, lees_sleutel)


# ---------------------------------------------------------------------------
# De matcher (zonder OCR): woordgrenzen, samenstellingen, OCR-verwisselingen
# ---------------------------------------------------------------------------
def regel(tekst: str):
    woorden, x = [], 0.0
    for w in tekst.split(" "):
        woorden.append((w, (x, 0.0, x + 10.0 * len(w), 20.0)))
        x += 10.0 * len(w) + 8.0
    return blind_ab._regel_uit_woorden(woorden, 0.9, "test")


@pytest.fixture(scope="module")
def termen():
    return blind_ab.bouw_verboden_termen()


def treffers(tekst, termen):
    return sorted({blind_ab.vouw(l.term) for l in blind_ab.vind_lekken([regel(tekst)], termen)})


@pytest.mark.parametrize("tekst,verwacht", [
    ("Welkom bij Interpolis Autoverzekeringen", "interpolis"),
    ("Interpolis-autoverzekering", "interpolis"),
    ("curl https://api.stripe.com/v1/charges", "stripe"),
    ("Ga naar Linear", "linear"),
    ("www.moneybird.nl/inloggen", "moneybird"),
    ("Onderdeel van Klaverblad Verzekeringen", "klaverblad"),
    ("Log in bij Retool", "retool"),
    ("Mijn Vercel dashboard", "vercel"),
    ("Exact Online boekhouden", "exactonline"),
    ("Geld.nl vergelijkt", "geldnl"),
    ("A.S.R. Verzekeringen", "asr"),
    ("de KvK zoeken", "kvk"),
    ("AFAS Software", "afas"),
    ("© 2026 PolisBeheer - intern gebruik", "polisbeheer"),
    ("POLISBEHEER", "polisbeheer"),
    ("2026PolisBeheer-intern", "polisbeheer"),
    ("Nationale-Nederlanden", "nationalenederlanden"),
    # RapidOCR levert vaak tekst zonder spaties: een merkwoord met hoofdletter midden in zo'n reeks telt
    ("voorwaardendemeldinggegevensStripeschadeformulieroverzicht", "stripe"),
    ("Notionverzekerdeschadebeheeraanvraaguitsluiting", "notion"),
    ("aanvraagwijzigingklantNotionverzoekaanvraag", "notion"),
    ("Welkom bij LINEAR", "linear"),
])
def test_matcher_vindt_merknamen_in_alle_schrijfwijzen(tekst, verwacht, termen):
    assert blind_ab.vouw(verwacht) in [blind_ab.vouw(x) for x in treffers(tekst, termen)]


@pytest.mark.parametrize("tekst", [
    "lnterpolis", "Interpo1is", "lnterp0lis", "Interpois", "Interpollis",     # OCR-verwisselingen en 1 letter mis
    "MoneyBird", "KLAVERBLAD",
])
def test_matcher_vangt_typische_ocr_fouten(tekst, termen):
    assert treffers(tekst, termen), tekst


@pytest.mark.parametrize("tekst", [
    "Welkom in de kalender en de calendar van vandaag",           # 'cal' in gewone woorden
    "local calls en physical",                                     # 'cal' midden in een woord
    "een trampoline en een rampant probleem",                      # 'ramp' in een woord
    "gestreepte stripes striped pattern",                          # 'stripe' als deel van een woord
    "notional interest en nonlinear",                              # 'notion', 'linear' in een woord
    "eigen risico, verplichte verzekering en assurantie",          # gewone vakwoorden
    "Uw eigen portaal voor centrale administratie en beheer",      # idem
    "exact dezelfde uitkomst",                                     # 'exact' alleen
    "Geld terug bij annulering",                                   # 'geld' alleen
    "Overstappen naar een andere verzekeraar",                     # 'overstappen' alleen
    "Interpol onderzoekt de zaak",                                 # bijna-woord (2 bewerkingen)
    "Polisbeheer overzicht",                                       # vakjargon in Titelcase
    "Bekijk de polis beheer uw gegevens",                          # twee woorden
    "Uw polis, premie, schade en dekking; portaal; assurantie",
    "gegevensstripeschadeformulier",                                # dezelfde reeks in kleine letters: geen merk
    "striped rows and stripes in the table",                        # gewone Engelse woorden in kleine letters
    "aanvraagnotionverzoek linearity ramping",
])
def test_matcher_geeft_geen_vals_alarm_op_gewone_tekst(tekst, termen):
    assert treffers(tekst, termen) == [], tekst


def test_korte_acroniemen_tellen_alleen_met_een_hoofdletter():
    """Echte opnames: 'ing' werd weggemaskeerd in 'Afdeling' en 'Wijziging(en)', omdat de tekenkaders van de OCR
    daar een valse woordgrens gaven. Het bank-acroniem zelf (ING) blijft verboden."""
    termen = blind_ab.bouw_verboden_termen(extra=["ING"])

    def regel_met_woordgrens(tekst, grens_bij):
        tekens = [blind_ab.OcrTeken(ch, (i * 10.0, 0.0, i * 10.0 + 9.0, 20.0), woordstart=(i == 0 or i == grens_bij))
                  for i, ch in enumerate(tekst)]
        return blind_ab.OcrRegel(tekens, (0, 0, 200, 20), 0.9, "t")

    assert not blind_ab.vind_lekken([regel_met_woordgrens("Afdeling", 5)], termen)         # 'ling' met valse grens
    assert not blind_ab.vind_lekken([regel_met_woordgrens("ing", 0)], termen)              # kleine letters
    assert blind_ab.vind_lekken([regel_met_woordgrens("ING", 0)], termen)                   # het acroniem zelf
    assert blind_ab.vind_lekken([regel_met_woordgrens("Ing", 0)], termen)
    assert treffers("A.S.R. Verzekeringen", termen) and treffers("de KvK zoeken", termen)  # bestaand gedrag
    assert treffers("bezoek www.kvk.nl voor meer", termen)                                  # lowercase URL: kvknl


def test_woordgrens_hangt_af_van_de_zichtbare_tussenruimte_of_de_hoofdletter():
    """RapidOCR levert vaak tekst zonder spaties; de woordgrens komt dan uit de tekenkaders of, bij aaneengeplakte
    tekst, uit een hoofdletter midden in de reeks. Een dubbelzinnig merkwoord ('linear') telt met een zichtbare
    tussenruimte ervoor of met een hoofdletter, niet als het klein midden in een langer woord staat."""
    termen = blind_ab.bouw_verboden_termen()

    def regel(tekst, gat):
        tekens = [blind_ab.OcrTeken(ch, (i * 10.0 + (30.0 if i >= 6 and gat else 0.0), 0.0,
                                         i * 10.0 + 9.0 + (30.0 if i >= 6 and gat else 0.0), 20.0),
                                    woordstart=bool(gat and i in (0, 6)))
                  for i, ch in enumerate(tekst)]
        return blind_ab.OcrRegel(tekens, (0, 0, 200, 20), 0.9, "t")

    assert blind_ab.vind_lekken([regel("Ganaarlinear", True)], termen)[0].gelezen == "linear"     # tussenruimte
    assert not blind_ab.vind_lekken([regel("Ganaarlinear", False)], termen)                       # klein en aaneen
    assert blind_ab.vind_lekken([regel("GanaarLinear", False)], termen)[0].gelezen == "Linear"    # hoofdletter


def test_rapidocr_gebruikt_de_hoekclassifier_niet():
    """De classifier draaide ~25% van de lange horizontale regels 180 graden om, waarna de herkenning
    onzin gaf en de regel wegviel (gemeten op 48 brede regels: 58% van de merkwoorden gevonden, zonder classifier 100%).
    Deze test bewaakt dat niemand hem per ongeluk weer aanzet."""
    aanroepen = []

    class NepEngine:
        def __call__(self, arr, **kw):
            aanroepen.append(kw)
            return None, None

    e = blind_ab.RapidOcrEngine.__new__(blind_ab.RapidOcrEngine)
    e._eng = NepEngine()
    assert e._lees(np.zeros((40, 200, 3), dtype=np.uint8), 1.0, 0.0, 0.0) == []
    assert aanroepen and all(kw.get("use_cls") is False for kw in aanroepen)


def test_lekken_op_dezelfde_plek_worden_een_kader_en_een_telling():
    a = blind_ab.Lek("stripe", "Stripe", (10, 10, 60, 30), "rapidocr", 0.9)
    b = blind_ab.Lek("stripe", "Stripe", (12, 11, 62, 31), "tesseract", 0.8)     # zelfde woord, andere engine
    c = blind_ab.Lek("stripe", "Stripe", (10, 200, 60, 220), "rapidocr", 0.9)    # ander woord, andere plek
    samen = blind_ab.voeg_lekken_samen([a, b, c])
    assert len(samen) == 2
    assert samen[0].engine == "rapidocr+tesseract" and samen[0].kader[2] == 62


def test_maskeren_pixeleert_en_vult_daarna_egaal_in():
    rng = np.random.default_rng(1)
    beeld = Image.fromarray(rng.integers(0, 255, (120, 300), dtype=np.uint8), "L")
    lek = blind_ab.Lek("x", "x", (50.0, 40.0, 150.0, 70.0), "t", 0.9)
    a = beeld.copy()
    assert blind_ab.maskeer_lekken(a, [lek], sterkte=1) == 1
    b = beeld.copy()
    assert blind_ab.maskeer_lekken(b, [lek], sterkte=2) == 1
    binnen = (60, 45, 140, 65)
    assert np.asarray(beeld.crop(binnen)).std() > 60
    assert np.asarray(a.crop(binnen)).std() < 25                    # verpixeld: geen tekst meer
    assert np.asarray(b.crop(binnen)).std() < 1                     # ingevuld: egaal
    assert np.array_equal(np.asarray(a.crop((0, 0, 30, 30))), np.asarray(beeld.crop((0, 0, 30, 30))))   # rest ongemoeid


def test_ocr_schaal_volgt_de_tekstgrootte_per_viewport():
    assert blind_ab.ocr_schaal("desktop", 1200) == pytest.approx(2.04, abs=0.05)
    assert blind_ab.ocr_schaal("mobile", 780) == 1.5
    assert blind_ab.ocr_schaal("desktop", 300) == 2.5                # kleine testbeelden: bovengrens


def test_ocr_cache_slaat_een_volledige_lezing_op_en_hergebruikt_haar(tmp_path, monkeypatch):
    monkeypatch.setenv("BLIND_AB_OCR_CACHE", str(tmp_path / "cache"))

    class Teller:
        naam = "teller"
        aantal = 0

        def lees_beeld(self, img, gebieden=None):
            Teller.aantal += 1
            return [blind_ab._regel_uit_woorden([("Interpolis", (1.0, 2.0, 91.0, 22.0))], 0.9, "teller")]

        def beschrijving(self):
            return {"naam": "teller", "versie": "1"}

    img = Image.new("L", (100, 50), 200)
    e = Teller()
    r1 = blind_ab.lees_alle_engines(img, [e])
    r2 = blind_ab.lees_alle_engines(img, [e])
    assert Teller.aantal == 1 and r1[0].tekst == r2[0].tekst == "Interpolis"
    assert r2[0].tekens[0].woordstart is True and r2[0].kader == r1[0].kader
    assert list((tmp_path / "cache").glob("*.json.gz"))
    # een ander beeld, andere opties of een deelgebied lezen wel opnieuw
    blind_ab.lees_alle_engines(Image.new("L", (100, 50), 100), [e])
    assert Teller.aantal == 2
    blind_ab.lees_alle_engines(img, [e], gebieden=[(0.0, 10.0)])
    assert Teller.aantal == 3
    monkeypatch.setenv("BLIND_AB_OCR_CACHE", "")                       # uitgeschakeld
    blind_ab.lees_alle_engines(img, [e])
    assert Teller.aantal == 4


def test_de_ocr_cache_gebruikt_de_code_van_de_engine_in_de_sleutel():
    """Dezelfde beschrijving maar andere leeslogica mag nooit dezelfde bewaarde lezing opleveren (de cache is
    een versneller, geen bron van waarheid; een testengine die verandert moet blijven kunnen falen)."""
    class A:
        naam = "x"

        def lees_beeld(self, img, gebieden=None):
            return []

        def beschrijving(self):
            return {"naam": "x", "versie": "1"}

    class B:
        naam = "x"

        def lees_beeld(self, img, gebieden=None):
            return [blind_ab._regel_uit_woorden([("Interpolis", (1.0, 2.0, 91.0, 22.0))], 0.9, "x")]

        def beschrijving(self):
            return {"naam": "x", "versie": "1"}

    img = Image.new("L", (40, 20), 255)
    assert blind_ab._cachesleutel(img, A()) != blind_ab._cachesleutel(img, B())
    assert blind_ab._cachesleutel(img, A()) == blind_ab._cachesleutel(img, A())


def test_engine_zonder_kennis_van_deelgebieden_leest_dan_het_hele_beeld(tmp_path, monkeypatch):
    monkeypatch.setenv("BLIND_AB_OCR_CACHE", "")

    class Oud:
        naam = "oud"

        def lees_beeld(self, img):
            return []

        def beschrijving(self):
            return {"naam": "oud"}

    assert blind_ab.lees_alle_engines(Image.new("L", (10, 10)), [Oud()], gebieden=[(0.0, 5.0)]) == []


# ---------------------------------------------------------------------------
# De echte engines
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def engines():
    return haal_ocr_engines()


@pytest.fixture(scope="session")
def echte_termen():
    return blind_ab.bouw_verboden_termen()


def lekwoorden(beeld, engines_, termen_):
    return sorted({blind_ab.vouw(l.term) for l in blind_ab.vind_lekken(
        blind_ab.lees_alle_engines(beeld, engines_), termen_)})


GEVALLEN = {
    "grote kop": (blind_ab.tekstbeeld, ("Welkom bij Interpolis Autoverzekeringen", 56, 20, 255)),
    "kleine bodytekst": (blind_ab.tekstbeeld, ("U kunt uw polis beheren via het portaal van Interpolis "
                                              "en daarna verder gaan.", 13, 40, 255)),
    "omgekeerde kleuren": (blind_ab.tekstbeeld, ("Welkom bij Interpolis Autoverzekeringen", 56, 245, 15)),
    "omgekeerde kleine tekst": (blind_ab.tekstbeeld, ("Alles wat u nodig heeft, van Interpolis in een keer.",
                                                     14, 225, 25)),
}


@pytest.mark.parametrize("naam", list(GEVALLEN))
def test_elke_engine_vindt_het_merkwoord_in_kop_bodytekst_en_omgekeerde_kleuren(naam, engines, echte_termen):
    functie, argumenten = GEVALLEN[naam]
    beeld = functie(*argumenten)
    for e in engines:
        gevonden = blind_ab.vind_lekken(e.lees_beeld(beeld), echte_termen)
        assert gevonden, f"{e.naam} mist het merkwoord in '{naam}'"
        assert blind_ab.vouw(gevonden[0].term) == "lnterpolls"               # 'interpolis', gevouwen
        # het gevonden kader ligt om het woord heen, niet ergens anders
        k = gevonden[0].kader
        assert 0 <= k[0] < beeld.width and 0 <= k[1] < beeld.height and k[2] - k[0] > 20


@pytest.mark.parametrize("tekst", [
    "Overzicht portefeuille en openstaande schades van uw relaties",
    "Het calendarium en de kalender: eigen risico, exact dezelfde premie, geld terug en portaal",
    "Facturen, betalingen, rapportages, klantgegevens en polisoverzicht voor assurantieadviseurs",
])
def test_schoon_beeld_geeft_geen_vals_alarm(tekst, engines, echte_termen):
    for e in engines:
        for px, vg, ag in ((30, 30, 255), (13, 40, 255), (40, 240, 20)):
            beeld = blind_ab.tekstbeeld(tekst, px, vg, ag)
            gelezen = " ".join(r.tekst for r in e.lees_beeld(beeld))
            assert len(gelezen) > 15, f"{e.naam} las niets: dan zegt 'geen alarm' niets"   # de proef heeft betekenis
            assert not blind_ab.vind_lekken(e.lees_beeld(beeld), echte_termen), (e.naam, px, gelezen)


def test_een_engine_die_niets_ziet_vindt_niets_dus_de_toets_kan_falen(echte_termen):
    beeld = blind_ab.tekstbeeld("Welkom bij Interpolis", 56, 20, 255)
    assert blind_ab.vind_lekken(NietsZienEngine().lees_beeld(beeld), echte_termen) == []


def test_detectiegraad_op_een_paneel_van_wisselende_grootte_polariteit_en_contrast(engines, echte_termen, capsys):
    """De gemeten detectiegraad, per engine en samen. Ondergrens; de exacte uitkomst wordt getoond."""
    woorden = ["Interpolis", "Klaverblad", "Moneybird", "Vercel", "Grafana", "Belastingdienst", "Poliswijzer",
               "Independer", "Rabobank", "Metabase"]
    plaatsingen = []       # (px, voorgrond, achtergrond, categorie, moet)
    for px in (56, 40, 28, 20, 16, 14, 12):
        plaatsingen.append((px, 20, 255, f"zwart op wit {px}px", px >= 14))
        plaatsingen.append((px, 245, 15, f"wit op zwart {px}px", px >= 14))
    plaatsingen += [(14, 150, 245, "laag contrast 14px", False), (13, 130, 235, "laag contrast 13px", False),
                    (16, 250, 110, "wit op middengrijs 16px", True), (14, 30, 200, "zwart op lichtgrijs 14px", True)]
    totaal = {e.naam: 0 for e in engines}
    gevonden = {e.naam: 0 for e in engines}
    samen = 0
    moet_gemist = []
    for i, (px, vg, ag, cat, moet) in enumerate(plaatsingen):
        woord = woorden[i % len(woorden)]
        beeld = blind_ab.tekstbeeld(f"Welkom bij {woord} voor teams en bedrijven", px, vg, ag, breedte=900)
        hits = set()
        for e in engines:
            totaal[e.naam] += 1
            treffer = any(blind_ab.vouw(l.term) == blind_ab.vouw(woord) for l in blind_ab.vind_lekken(e.lees_beeld(beeld), echte_termen))
            gevonden[e.naam] += treffer
            if treffer:
                hits.add(e.naam)
        samen += bool(hits)
        if moet and not hits:
            moet_gemist.append(f"{cat} ({woord})")
    n = len(plaatsingen)
    with capsys.disabled():
        print(f"\n  OCR-detectiegraad op {n} plaatsingen: samen {samen}/{n} = {samen / n:.0%}; "
              + ", ".join(f"{k} {v}/{n} = {v / n:.0%}" for k, v in gevonden.items()))
    assert not moet_gemist, f"gemist terwijl ze gevonden moeten worden: {moet_gemist}"
    assert samen / n >= 0.85


def test_brede_regels_van_70_tot_170_tekens_verliezen_het_merkwoord_niet(engines, echte_termen):
    """Bij de bouw viel in brede alinea's ruim de helft van de merkwoorden weg (de hoekclassifier van RapidOCR
    draaide lange regels om). Hier staat het merkwoord vooraan, midden en achteraan in regels tot 1150 px."""
    vul = ("de polis voorwaarden schade dekking premie aanvraag klant beheer overzicht betaling termijn "
           "melding dossier uitkering wijziging verzoek gegevens contract adres relatie afspraak factuur").split()
    merken = ["Interpolis", "Stripe", "Vercel", "Notion", "Klaverblad", "Moneybird", "Grafana", "Metabase", "Rabobank"]
    rng = random.Random(11)
    rij = 56
    doek = Image.new("L", (1400, rij * len(merken) + 20), 255)
    for i, merk in enumerate(merken):
        n = (8, 14, 20)[(i // 3) % 3]
        voor = " ".join(rng.choice(vul) for _ in range(n // 2))
        na = " ".join(rng.choice(vul) for _ in range(n // 2))
        tekst = (f"{merk} {voor} {na}", f"{voor} {merk} {na}", f"{voor} {na} {merk}")[i % 3]
        doek.paste(blind_ab.tekstbeeld(tekst, 14, 40, 255, breedte=100, marge=6), (10, 10 + rij * i))

    def gevonden_per_regel(regels_ocr):
        lekken = blind_ab.vind_lekken(regels_ocr, echte_termen)
        return [any(10 + rij * i - 4 <= (l.kader[1] + l.kader[3]) / 2 <= 10 + rij * (i + 1)
                    and blind_ab.vouw(l.term) == blind_ab.vouw(merk) for l in lekken)
                for i, merk in enumerate(merken)]

    assert not any(gevonden_per_regel(NietsZienEngine().lees_beeld(doek)))            # tegenproef
    for e in engines:
        assert all(gevonden_per_regel(e.lees_beeld(doek))), (e.naam, gevonden_per_regel(e.lees_beeld(doek)))


def test_automask_maskeert_het_kader_en_geen_enkele_engine_leest_het_woord_daarna(engines, echte_termen):
    beeld = blind_ab.tekstbeeld("Welkom bij Interpolis Autoverzekeringen", 48, 20, 255, breedte=1000)
    assert blind_ab.vind_lekken(blind_ab.lees_alle_engines(beeld, engines), echte_termen)          # voor
    schoon, rapport = blind_ab.controleer_lekken(beeld, engines, echte_termen)
    assert rapport.kaders_gemaskeerd >= 1 and not rapport.rest_lekken and rapport.doorgangen >= 2
    assert "interpolis" in [w.lower() for w in rapport.gemaskeerde_termen]
    for e in engines:                                                # na: onafhankelijk gelezen door elke engine
        assert not blind_ab.vind_lekken(e.lees_beeld(schoon), echte_termen), e.naam
    # de rest van de zin is er nog: alleen het woord is weg
    over = " ".join(r.tekst for e in engines[:1] for r in e.lees_beeld(schoon))
    assert "Autoverzekering" in over or "Welkom" in over


def test_dekking_is_laag_bij_een_beeld_zonder_leesbare_tekst_en_ok_bij_een_tekstrijk_beeld(engines, echte_termen):
    leeg = Image.new("L", (600, 300), 240)
    ImageDraw.Draw(leeg).rectangle([50, 50, 550, 250], fill=90)
    _b, r_leeg = blind_ab.controleer_lekken(leeg, engines, echte_termen)
    assert r_leeg.dekking == "laag" and r_leeg.woorden_gelezen < blind_ab.MIN_WOORDEN_PER_BEELD
    rijk = Image.new("L", (1000, 220), 255)
    for i in range(3):
        ImageDraw.Draw(rijk).text((20, 20 + 60 * i), "Overzicht van openstaande schadedossiers en actuele premies",
                                  font=blind_ab.lettertype(22), fill=30)
    _b, r_rijk = blind_ab.controleer_lekken(rijk, engines, echte_termen)
    assert r_rijk.dekking == "ok" and r_rijk.woorden_gelezen >= 15


def test_ijkcontrole_slaagt_voor_de_echte_engines_en_keurt_een_blinde_engine_af(engines, echte_termen):
    goed, uitslagen, meldingen = blind_ab.kalibreer_engines(engines, echte_termen)
    assert [e.naam for e in goed] == [e.naam for e in engines] and meldingen == []
    for u in uitslagen:
        assert u["verplicht_gevonden"] and u["gevonden"] >= 6 and u["van"] == len(blind_ab.IJK_RIJEN)
    with pytest.raises(blind_ab.OcrOnbetrouwbaar):
        blind_ab.kalibreer_engines([NietsZienEngine()], echte_termen)
    # een engine die de helft mist blijft over als de andere goed is, en wordt gemeld
    goed2, _u, meld2 = blind_ab.kalibreer_engines([NietsZienEngine(), engines[0]], echte_termen)
    assert [e.naam for e in goed2] == [engines[0].naam] and "niets-zien" in meld2[0]


def test_de_hercontrole_leest_alleen_de_banden_over_de_gemaskeerde_plek(tmp_path):
    engine = ZietTekstAlsErContrastIsEngine()
    m = bouw_bronnen(tmp_path, patroon=True, mobiel=False)
    beeld, _ = blind_ab.neutraliseer(m["comps"] / "intl2_desktop_1440.png", "desktop", 300, 3.0, "zacht",
                                     None, True, 0.5, secties=blind_ab.standaard_sectiespec("desktop", 300))
    schoon, rapport = blind_ab.controleer_lekken(beeld, [engine], blind_ab.bouw_verboden_termen())
    assert rapport.doorgangen == 2 and not rapport.rest_lekken
    assert engine.gebieden_log[0] is None                           # eerste doorgang: het hele beeld
    assert engine.gebieden_log[1] and all(a < b for a, b in engine.gebieden_log[1])   # tweede: alleen de plek
    y0, y1 = engine.gebieden_log[1][0]
    assert y0 < 140 < y1 and (y1 - y0) < beeld.height              # het patroon zat rond y=120-160, en niet het hele beeld


# ---------------------------------------------------------------------------
# Hele ronde met echte OCR
# ---------------------------------------------------------------------------
def _pagina_met_tekst(pad, breedte, hoogte, regels, zaad=0):
    """Effen pagina met alleen tekst (geen balken erachter die het contrast verstoren)."""
    from test_meetlat_hulp import maak_pagina
    maak_pagina(pad, breedte, hoogte, zaad=zaad, teksten=regels, balken=False)


def test_hele_ronde_met_echte_ocr_maskeert_merknamen_in_kop_en_bodytekst(tmp_path, engines, echte_termen, capsys):
    import json as _json
    m = {n: tmp_path / n for n in ("comps", "comps_nl", "ours", "decoy", "anker")}
    for p in m.values():
        p.mkdir()
    # Pagina's van 1100 px hoog zijn 'kort': de drie secties sluiten aan, dus alles staat in beeld.
    # Tekst op y=150 (sectie 1), 480 (sectie 2) en 900 (sectie 3), buiten header- en footermasker.
    _pagina_met_tekst(m["comps"] / "intl_desktop_1440.png", 600, 1100,
                      [(60, 150, "Welkom bij Interpolis Autoverzekeringen", 34, 20),
                       (60, 480, "Betaal veilig met Stripe en lees de documentatie op api.stripe.com.", 15, 50),
                       (60, 900, "Alle rechten voorbehouden", 14, 60)], 1)
    _pagina_met_tekst(m["comps_nl"] / "nl_desktop_1440x900.png", 600, 1100,
                      [(60, 150, "Vergelijk bij Independer uw zorgverzekering", 30, 20),
                       (60, 480, "Powered by Klaverblad", 14, 60)], 2)
    _pagina_met_tekst(m["ours"] / "portaal-desktop-1440x900.png", 600, 1100,
                      [(60, 150, "Zebraboom schadedossiers", 34, 20),
                       (60, 480, "Ingelogd in het Zebraboom portaal als beheerder", 15, 60)], 3)
    _pagina_met_tekst(m["decoy"] / "decoy0-desktop-1440x900.png", 600, 1100,
                      [(60, 150, "Het PolisBeheer overzicht 4.2", 30, 20)], 4)
    _pagina_met_tekst(m["anker"] / "anker-desktop-1440x900.png", 600, 1100,
                      [(60, 150, "Grafana kubernetes overzicht", 30, 20)], 5)
    (m["comps"] / "manifest.json").write_text(_json.dumps([{"bestand": "intl_desktop_1440.png", "bron_naam": "Bron A",
                                                            "klasse": "product_ui", "domein": "internationaal"}]))
    (m["comps_nl"] / "manifest.json").write_text(_json.dumps({"comps": [
        {"slug": "nl", "naam": "Independer - test", "klasse": "product_ui", "domein": "nl_financieel",
         "bestanden": {"desktop": {"file": "nl_desktop_1440x900.png"}}}]}))
    (m["decoy"] / "manifest.json").write_text(_json.dumps({"bestanden": [
        {"viewport": "desktop", "bestand": "decoy0-desktop-1440x900.png", "klasse": "decoy", "kwaliteit": "matig"}]}))
    (m["anker"] / "manifest.json").write_text(_json.dumps({"bestanden": [
        {"bestand": "anker-desktop-1440x900.png", "klasse": "anker", "bron_naam": "Anker"}]}))

    # voor de proef: zonder de OCR-stap leest OCR de merknamen WEL in het geneutraliseerde beeld
    spec = blind_ab.standaard_sectiespec("desktop", 400)
    onbeschermd, _ = blind_ab.neutraliseer(m["comps"] / "intl_desktop_1440.png", "desktop", 400, 3.0, "zacht",
                                           None, True, 0.5, secties=spec)
    assert lekwoorden(onbeschermd, engines, echte_termen), "de bronbeelden bevatten geen leesbaar merk: proef zonder waarde"

    code = blind_ab.main(cli_args(tmp_path, m, "--viewports", "desktop", "--breedte", "400",
                                  "--eigen-namen", "Zebraboom"))         # echte engines, met ijkcontrole
    uit = capsys.readouterr().out
    assert code == 0, uit
    assert "OCR-ijkcontrole" in uit
    s = lees_sleutel(tmp_path)
    assert s["ocr"]["kaders_gemaskeerd"] >= 5 and s["ocr"]["beelden_met_automask"] >= 4
    assert s["ocr"]["beelden_met_lek_na_automask"] == 0
    assert s["ocr"]["ijkcontrole"] and all(k["verplicht_gevonden"] for k in s["ocr"]["ijkcontrole"])
    assert not any("geen eigen productnaam" in w for w in s["waarschuwingen"])
    gemaskeerd = {w.lower() for it in s["viewports"]["desktop"]["items"] for w in it["ocr"]["gemaskeerde_woorden"]}
    assert {"interpolis", "stripe", "independer", "klaverblad", "zebraboom", "grafana", "polisbeheer"} <= gemaskeerd, gemaskeerd

    # onafhankelijke controle achteraf: lees de uitgeleverde beelden met elke engine opnieuw
    termen = blind_ab.bouw_verboden_termen(extra=["Zebraboom"])
    for png in sorted((tmp_path / "ab" / "r" / "desktop").glob("*.png")):
        with Image.open(png) as im:
            for e in engines:
                assert not blind_ab.vind_lekken(e.lees_beeld(im.copy()), termen), f"{png.name} lekt voor {e.naam}"
