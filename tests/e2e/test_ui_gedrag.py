"""
Gedrag van de pagina onder onvolledige, afgebroken en gestopte runs, en de weergave van de tekst van
het model. Dit zijn de bevindingen van de onafhankelijke review die alleen in een echte browser te zien zijn.
"""
import json

from playwright.sync_api import expect

SCHADE = {"verzekerde_som": 200000, "werkelijke_waarde": 250000, "schade": 50000}
BRONNEN_EVENT = {"type": "bronnen", "bronnen": [{
    "soort": "wetgeving", "label": "BW art. 7:958", "titel": "waarde van het verzekerd belang", "url": "https://wetten.overheid.nl/x",
    "fragment": "Tekst van het artikel."}]}


def start(pagina, functie="schadeberekening"):
    pagina.goto(pagina.basis + f"/#/f/{functie}")
    pagina.click("text=Voorbeeld invullen")
    pagina.click("button[type=submit]")


# ---------------------------------------------------------------- verborgen knoppen

def test_stop_en_kopieerknop_zijn_verborgen_tot_ze_nodig_zijn(traag_pagina):
    p = traag_pagina
    p.goto(p.basis + "/#/f/schadeberekening")
    stop, kopieer = p.get_by_role("button", name="Stop"), p.get_by_role("button", name="Kopieer")
    assert not stop.is_visible()                                   # het hidden-attribuut werd overschreven door .knop
    p.click("text=Voorbeeld invullen")
    p.click("button[type=submit]")
    expect(stop).to_be_visible()
    expect(p.locator(".cursor")).to_be_visible(timeout=10000)      # er stroomt tekst binnen
    assert not kopieer.is_visible()                                # niet kopiëren voordat de controle klaar is
    expect(p.locator(".sectie", has_text="Controle van verwijzingen")).to_be_visible(timeout=20000)
    expect(kopieer).to_be_visible()
    assert not stop.is_visible()


def test_focus_gaat_naar_stop_tijdens_het_werk_en_terug_naar_de_toetsknop_erna(traag_pagina):
    p = traag_pagina
    p.goto(p.basis + "/#/f/schadeberekening")
    p.click("text=Voorbeeld invullen")
    p.focus("button[type=submit]")
    p.keyboard.press("Enter")
    expect(p.get_by_role("button", name="Stop")).to_be_focused()
    expect(p.locator(".sectie", has_text="Controle van verwijzingen")).to_be_visible(timeout=20000)
    expect(p.locator("button[type=submit]")).to_be_focused()


# ---------------------------------------------------------------- stoppen en onderbreken

def test_stop_midden_in_het_antwoord_laat_een_eerlijke_stand_achter(traag_pagina):
    p = traag_pagina
    start(p)
    expect(p.locator(".cursor")).to_be_visible(timeout=10000)
    p.get_by_role("button", name="Stop").click()
    expect(p.locator(".melding.info", has_text="Gestopt")).to_contain_text("onvolledig en niet gecontroleerd")
    assert p.locator(".cursor").count() == 0                       # de knipperende cursor is weg
    assert p.locator(".pijp-stap.actief").count() == 0
    assert "overgeslagen" in p.locator(".pijp-stap", has_text="Toelichting").get_attribute("class")
    assert "overgeslagen" in p.locator(".pijp-stap", has_text="Controle").get_attribute("class")
    assert p.locator(".sectie", has_text="Controle van verwijzingen").count() == 0
    assert not p.get_by_role("button", name="Kopieer").is_visible()
    assert p.locator(".sectie", has_text="Bronnen").count() >= 1   # wat er al was blijft staan


def test_een_verbroken_verbinding_wist_de_bronnen_niet_en_meldt_dat_het_onderbroken_is(pagina):
    def afgebroken(route):
        route.fulfill(status=200, headers={"content-type": "text/event-stream"},
                      body="data: " + json.dumps(BRONNEN_EVENT) + "\n\n")      # geen [DONE]: de stroom valt weg
    pagina.route("**/api/vraag", afgebroken)
    start(pagina)
    expect(pagina.locator(".melding.fout", has_text="Onderbroken")).to_be_visible(timeout=10000)
    assert pagina.locator(".sectie", has_text="Bronnen").count() == 1        # niet gewist
    assert pagina.locator(".pijp-stap.fout").count() == 1 and pagina.locator(".pijp-stap.actief").count() == 0
    assert "overgeslagen" in pagina.locator(".pijp-stap", has_text="Controle").get_attribute("class")
    assert pagina.get_by_role("button", name="Toets uitvoeren").is_enabled()


def test_een_weigering_maakt_de_pijplijn_niet_groen(pagina):
    def weigering(route):
        route.fulfill(status=200, headers={"content-type": "text/event-stream"}, body="".join([
            "data: " + json.dumps({"type": "bronnen", "bronnen": []}) + "\n\n",
            "data: " + json.dumps({"type": "weigering", "tekst": "Geen bronnen gevonden.\n\nVervolgstap: verfijn."}) + "\n\n",
            "data: " + json.dumps({"type": "controle", "controle": {"oordeel": "GEWEIGERD_GEEN_BRONNEN", "gefundeerd": [], "ongefundeerd": []}}) + "\n\n",
            "data: [DONE]\n\n"]))
    pagina.route("**/api/vraag", weigering)
    start(pagina, "begripsuitleg")
    expect(pagina.locator(".melding.info", has_text="Vervolgstap: verfijn")).to_be_visible()
    for stap in ("Toelichting", "Controle"):
        assert "klaar" not in pagina.locator(".pijp-stap", has_text=stap).get_attribute("class").split()


def test_de_lopende_tijd_staat_buiten_het_live_gebied_voor_schermlezers(pagina):
    start(pagina)
    expect(pagina.locator(".sectie", has_text="Controle van verwijzingen")).to_be_visible(timeout=15000)
    assert pagina.locator(".pijp-tijd").get_attribute("aria-hidden") == "true"
    assert "klaar" in pagina.locator(".pijplijn .alleen-lezers").first.inner_text()


def test_wachtmelding_noemt_geen_lokaal_model_bij_een_snelle_provider(pagina):
    start(pagina)
    assert "CPU" not in pagina.locator(".resultaat").inner_text()


# ---------------------------------------------------------------- de tekst van het model

def render(pagina, tekst, verwijzingen=None):
    pagina.goto(pagina.basis + "/")
    return pagina.evaluate(
        "([t, v]) => import('/static/tekst.js').then((m) => m.renderAntwoord(t, v).outerHTML)", [tekst, verwijzingen or []])


def test_een_markdowntabel_wordt_een_echte_tabel(pagina):
    html = render(pagina, "Vergelijking:\n\n| Punt | Variant A | Variant B |\n|---|---|---|\n| Eigen risico | € 250 | € 500 |\n| Inbraak | ja | nee |\n")
    assert html.count("<th ") == 3 and html.count("<td>") == 6
    assert '<th scope="col">Variant A</th>' in html


def test_geneste_lijsten_en_lijstnummers_van_maximaal_twee_cijfers(pagina):
    html = render(pagina, "1. Eerste punt\n   - sub a\n   - sub b\n     - subsub\n2. Tweede punt\n\n2024. Het jaar van de wijziging.")
    assert html.count("<ol") == 1 and html.count("<li") == 5
    assert "<ul><li><p>sub a</p></li><li><p>sub b</p><ul><li><p>subsub</p>" in html.replace(" style=\"counter-set: n 1\"", "")
    assert "<p>2024. Het jaar van de wijziging.</p>" in html          # geen lijst met teller 2024


def test_vet_met_cursief_erin_en_losse_sterretjes(pagina):
    html = render(pagina, "**vet met *cursief* erin** en *cursief* en 5 * 3 * 2 blijft staan.")
    assert "<strong>vet met <em>cursief</em> erin</strong>" in html
    assert "<em>cursief</em> en 5 * 3 * 2 blijft staan." in html


def test_citaat_en_html_in_de_tekst_komen_als_tekst_in_de_pagina(pagina):
    html = render(pagina, "> Dit is een citaat.\n\nNormaal <img src=x onerror=alert(1)> en <script>alert(2)</script>.")
    assert "<blockquote>" in html
    assert "<img" not in html and "<script" not in html and "&lt;img" in html


def test_verwijzing_krijgt_ook_een_chip_in_code_en_achter_art_punt(pagina):
    html = render(pagina, "Zie `7:960` en art.7:960 en 1.7:960x.", [{"verwijzing": "7:960", "soort": "wetsartikel", "status": "slecht"}])
    assert html.count('class="verw slecht"') == 2                   # in de codeopmaak en achter 'art.'
    assert "1.7:960x" in html and html.count('class="verw') == 2


def test_aangehaalde_tekst_krijgt_de_woordelijk_markering(pagina):
    tekst = 'Het dossier zegt "de klant heeft een risicobereidheid van laag opgegeven" en dat klopt.'
    html = render(pagina, tekst, [{"verwijzing": "de klant heeft een risicobereidheid van laag opgegeven", "soort": "citaat", "status": "ok"}])
    assert 'class="verw citaat ok"' in html


# ---------------------------------------------------------------- het kleine lokale model schrijft geen uitleg bij een berekening

def test_met_het_lokale_model_staat_de_uitleg_uit_code_en_schrijft_het_model_niets(lokaal_pagina):
    p = lokaal_pagina
    start(p, "schadeberekening")
    expect(p.locator(".melding.info", has_text="Geen toelichting van een taalmodel")).to_be_visible(timeout=15000)
    assert "te klein" in p.locator(".melding.info", has_text="Geen toelichting").inner_text()
    expect(p.locator(".uitleg")).to_contain_text("art. 7:958 lid 5 BW")           # de uitleg uit code staat er
    assert p.locator(".sectie", has_text="Toelichting").count() == 0 or p.locator(".sectie h3", has_text="Toelichting").count() == 0
    assert p.locator(".sectie", has_text="Controle van verwijzingen").count() == 0
    for stap in ("Toelichting", "Controle"):
        assert "overgeslagen" in p.locator(".pijp-stap", has_text=stap).get_attribute("class")
    assert p.get_by_role("button", name="Toets uitvoeren").is_enabled()
    assert p.fouten == []


def test_met_het_lokale_model_schrijft_het_model_wel_waar_de_tekst_niet_uit_code_komt(lokaal_pagina):
    p = lokaal_pagina
    start(p, "dekkingscheck")
    # het nepbestand is geen echt model: de storing wordt eerlijk gemeld, niet weggemoffeld
    expect(p.locator(".melding.fout")).to_be_visible(timeout=20000)
    assert p.locator(".melding.info", has_text="Geen toelichting van een taalmodel").count() == 0


def test_waardetoets_toont_de_uitleg_uit_code_en_beweert_niet_dat_de_drempel_per_verzekeraar_verschilt(pagina):
    p = pagina
    start(p, "waardetoets")
    expect(p.locator(".uitleg")).to_contain_text("In gewone woorden", timeout=15000)
    expect(p.locator(".uitleg")).to_contain_text("volgt uit de polisvoorwaarden, niet uit de wet")
    assert "verschilt per verzekeraar" not in p.locator("body").inner_text()
    assert p.fouten == []
