"""
End-to-end: de echte pagina in een echte browser, tegen de echte API, corpus en citeerbewaker.
Alleen het taalmodel is een testdouble (tests/nep_llm.py), zodat de test deterministisch is.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from nep_llm import NepLLM  # noqa: E402

CHROME = os.environ.get("PLAYWRIGHT_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="geen Chromium beschikbaar")


def vrije_poort():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app():
    nep = NepLLM(vertraging=0.3)
    poort = vrije_poort()
    env = {**os.environ, "OPENROUTER_API_KEY": "test", "ASSURANTIE_LLM_PROVIDER": "openrouter",
           "ASSURANTIE_OPENROUTER_URL": nep.url, "ASSURANTIE_MODELLEN": "testmodel"}
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "api:app", "--app-dir", "backend",
                          "--port", str(poort), "--log-level", "warning"], cwd=ROOT, env=env)
    basis = f"http://127.0.0.1:{poort}"
    for _ in range(60):
        try:
            urllib.request.urlopen(basis + "/api/status", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        p.kill()
        raise RuntimeError("server startte niet")
    yield basis
    p.terminate()
    p.wait(timeout=10)
    nep.stop()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        yield b
        b.close()


@pytest.fixture()
def pagina(browser, app):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="nl-NL")
    p = ctx.new_page()
    p.fouten = []
    p.on("console", lambda m: p.fouten.append(m.text) if m.type == "error" else None)
    p.on("pageerror", lambda e: p.fouten.append(str(e)))
    p.basis = app
    yield p
    ctx.close()


def test_overzicht_toont_alle_twaalf_functies_en_de_corpusstatus(pagina):
    pagina.goto(pagina.basis + "/")
    expect(pagina.locator("h1")).to_contain_text("Antwoorden met een bron erbij")
    assert pagina.locator(".functiekaart").count() == 12
    expect(pagina.locator(".zij-status")).to_contain_text("53 artikelen")
    assert pagina.fouten == []


def test_schadeberekening_van_invoer_tot_controle(pagina):
    pagina.goto(pagina.basis + "/#/f/schadeberekening")
    pagina.click("text=Voorbeeld invullen")
    pagina.click("button[type=submit]")
    expect(pagina.locator(".sectie", has_text="Controle van verwijzingen")).to_be_visible(timeout=15000)
    # het bedrag komt uit de rekenkern, in Nederlandse notatie
    expect(pagina.locator(".held-getal").first).to_have_text("€ 43.500,00")
    # de bronnen staan er en zijn voor een berekening standaard ingeklapt
    expect(pagina.locator(".sectie", has_text="8 bronnen opgehaald")).to_be_visible()
    # het antwoord bevat een gecontroleerde en een ongecontroleerde verwijzing
    assert pagina.locator(".verw.ok").count() >= 1
    assert pagina.locator(".verw.slecht").count() == 1
    expect(pagina.locator(".verw.slecht")).to_contain_text("7:999")
    expect(pagina.locator(".sectie", has_text="Controle van verwijzingen")).to_contain_text("staat niet in de bronnen")
    assert pagina.fouten == []


def test_klik_op_een_gecontroleerde_verwijzing_toont_de_bron(pagina):
    pagina.goto(pagina.basis + "/#/f/dekkingscheck")
    pagina.click("text=Voorbeeld invullen")
    pagina.click("button[type=submit]")
    expect(pagina.locator(".sectie", has_text="Controle van verwijzingen")).to_be_visible(timeout=15000)
    chip = pagina.locator(".verw.ok").first
    chip.click()
    expect(pagina.locator('.bron[data-open="true"]').first).to_be_visible()


def test_verplichte_velden_geven_een_foutmelding_en_versturen_niets(pagina):
    pagina.goto(pagina.basis + "/#/f/schadeberekening")
    pagina.click("button[type=submit]")
    assert pagina.locator(".veld-fout:not([hidden])").count() == 3
    expect(pagina.locator(".resultaat .leeg")).to_be_visible()


def test_onleesbaar_bedrag_wordt_afgevangen(pagina):
    pagina.goto(pagina.basis + "/#/f/schadeberekening")
    pagina.fill("input[name=verzekerde_som]", "abc")
    pagina.fill("input[name=werkelijke_waarde]", "250.000")
    pagina.fill("input[name=schade]", "50.000")
    pagina.click("button[type=submit]")
    expect(pagina.locator(".veld-fout:not([hidden])").first).to_contain_text("Geen geldig getal")


def test_verjaringstoets_toont_de_gecorrigeerde_dagtelling(pagina):
    pagina.goto(pagina.basis + "/#/f/verjaringstoets")
    pagina.fill("input[name=datum_bekend]", "2024-03-10")
    pagina.fill("input[name=peildatum]", "2027-03-10")
    pagina.click("button[type=submit]")
    expect(pagina.locator(".held-getal").first).to_have_text("10 maart 2027", timeout=15000)
    expect(pagina.locator(".oordeel h4")).to_have_text("Nog niet verjaard")
    pagina.fill("input[name=peildatum]", "2027-03-11")
    pagina.click("button[type=submit]")
    expect(pagina.locator(".oordeel h4")).to_have_text("Verjaard", timeout=15000)


def test_provisietoets_weigert_een_gok_bij_een_onbekend_product(pagina):
    pagina.goto(pagina.basis + "/#/f/provisietoets")
    pagina.fill("input[name=producttype]", "kunstverzekering")
    pagina.click("button[type=submit]")
    expect(pagina.locator(".oordeel h4")).to_have_text("Niet vast te stellen", timeout=15000)


def test_ai_tekst_kan_geen_markup_in_de_pagina_brengen(pagina):
    pagina.goto(pagina.basis + "/#/f/begripsuitleg")
    pagina.fill("input[name=begrip]", '<img src=x onerror="window.__gehackt=1"> onderverzekering')
    pagina.click("button[type=submit]")
    expect(pagina.locator(".sectie", has_text="Controle van verwijzingen")).to_be_visible(timeout=15000)
    assert pagina.evaluate("window.__gehackt") is None
    assert pagina.locator(".antwoord img").count() == 0


def test_op_een_telefoon_zit_de_navigatie_achter_een_menuknop(browser, app):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, locale="nl-NL")
    p = ctx.new_page()
    p.goto(app + "/")
    expect(p.locator("#menuknop")).to_be_visible()
    assert p.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    p.click("#menuknop")
    expect(p.locator("#zij")).to_have_attribute("data-open", "true")
    p.click("#zij >> text=Verjaringstoets")
    expect(p.locator("h1")).to_have_text("Verjaringstoets")
    ctx.close()
