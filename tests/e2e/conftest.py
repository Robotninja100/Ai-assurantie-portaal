"""
Gedeelde fixtures voor de browsertests: een echte server (uvicorn) met de echte pagina, API, corpus en
citeerbewaker. Alleen het taalmodel is een testdouble (tests/nep_llm.py).
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from nep_llm import NepLLM  # noqa: E402

def _chrome_pad():
    """Chromium: PLAYWRIGHT_CHROMIUM, anders de vaste plek in deze omgeving, anders wat `playwright install chromium` neerzette."""
    for pad in (os.environ.get("PLAYWRIGHT_CHROMIUM"), "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"):
        if pad and os.path.exists(pad):
            return pad
    try:
        with sync_playwright() as pw:
            pad = pw.chromium.executable_path
        return pad if os.path.exists(pad) else None
    except Exception:  # noqa: BLE001
        return None


CHROME = _chrome_pad()


def pytest_collection_modifyitems(config, items):
    if not CHROME:
        skip = pytest.mark.skip(reason="geen Chromium beschikbaar (playwright install chromium)")
        for item in items:
            if "e2e" in str(item.fspath):
                item.add_marker(skip)


def vrije_poort():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_app(env_extra=None, **nep_opties):
    nep = NepLLM(**nep_opties)
    poort = vrije_poort()
    env = {**os.environ, "OPENROUTER_API_KEY": "test", "ASSURANTIE_LLM_PROVIDER": "openrouter",
           "ASSURANTIE_OPENROUTER_URL": nep.url, "ASSURANTIE_MODELLEN": "testmodel",
           "ASSURANTIE_LIVE_KETEN": "0", **(env_extra or {})}
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
    return basis, nep, p


def stop_app(nep, p):
    p.terminate()
    p.wait(timeout=10)
    nep.stop()


@pytest.fixture(scope="module")
def app():
    basis, nep, p = start_app(vertraging=0.3)
    yield basis
    stop_app(nep, p)


@pytest.fixture(scope="module")
def traag_app():
    """Een model dat zijn antwoord in kleine stukjes met pauzes uitgeeft: er is tijd om op Stop te drukken."""
    basis, nep, p = start_app(vertraging=0.3, stukvertraging=0.25)
    yield basis
    stop_app(nep, p)


@pytest.fixture(scope="module")
def lokaal_app(tmp_path_factory):
    """Een portaal dat terugvalt op het (kleine) lokale model: een leeg bestand volstaat, want het model mag hier niet schrijven."""
    model = tmp_path_factory.mktemp("model") / "klein.gguf"
    model.write_bytes(b"x")
    env = {"ASSURANTIE_LLM_PROVIDER": "local", "ASSURANTIE_MODEL_PATH": str(model), "OPENROUTER_API_KEY": ""}
    basis, nep, p = start_app(env_extra=env)
    yield basis
    stop_app(nep, p)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        yield b
        b.close()


def maak_pagina(browser, basis, **opties):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="nl-NL", **opties)
    p = ctx.new_page()
    p.fouten = []
    p.on("console", lambda m: p.fouten.append(m.text) if m.type == "error" else None)
    p.on("pageerror", lambda e: p.fouten.append(str(e)))
    p.basis = basis
    return ctx, p


@pytest.fixture()
def pagina(browser, app):
    ctx, p = maak_pagina(browser, app)
    yield p
    ctx.close()


@pytest.fixture()
def traag_pagina(browser, traag_app):
    ctx, p = maak_pagina(browser, traag_app)
    yield p
    ctx.close()


@pytest.fixture()
def lokaal_pagina(browser, lokaal_app):
    ctx, p = maak_pagina(browser, lokaal_app)
    yield p
    ctx.close()
