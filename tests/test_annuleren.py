"""
Wie het tabblad sluit of op Stop drukt, mag het model niet nog een heel antwoord laten schrijven.
Getest met een echte server (uvicorn) en een traag nep-model: sluit de client, dan moet ons portaal
zijn verbinding met het model ook sluiten, ver voordat het antwoord af is.
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from nep_llm import NepLLM  # noqa: E402


def _poort():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server():
    nep = NepLLM(stukvertraging=0.15)
    poort = _poort()
    env = {**os.environ, "OPENROUTER_API_KEY": "test", "ASSURANTIE_LLM_PROVIDER": "openrouter",
           "ASSURANTIE_OPENROUTER_URL": nep.url, "ASSURANTIE_MODELLEN": "testmodel"}
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "api:app", "--app-dir", "backend",
                          "--port", str(poort), "--log-level", "warning"], cwd=ROOT, env=env)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{poort}/api/status", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        p.kill()
        raise RuntimeError("server startte niet")
    yield nep, poort
    p.terminate()
    p.wait(timeout=10)
    nep.stop()


def test_het_sluiten_van_de_verbinding_stopt_de_generatie_bij_het_model(server):
    nep, poort = server
    c = http.client.HTTPConnection("127.0.0.1", poort, timeout=20)
    c.request("POST", "/api/vraag", body=json.dumps({"functie": "schadeberekening", "invoer": {
        "verzekerde_som": 200000, "werkelijke_waarde": 250000, "schade": 50000}}),
        headers={"content-type": "application/json"})
    r = c.getresponse()
    gezien = ""
    while '"type": "tekst"' not in gezien:                 # wacht tot de eerste tekst er is
        gezien += r.fp.readline().decode("utf-8", "replace")
    for _ in range(100):                                    # de teller van het nep-model loopt een fractie achter
        if nep.stukken >= 1:
            break
        time.sleep(0.02)
    assert nep.stukken >= 1
    c.close()                                               # de adviseur sluit het tabblad
    assert nep.onderbroken.wait(timeout=15), "het portaal bleef het model doorlaten schrijven"
    kort = nep.stukken
    time.sleep(1.0)
    assert nep.stukken == kort, "er zijn na het sluiten nog stukken geschreven"


def test_te_lang_veld_type_en_ontbrekend_veld_geven_een_duidelijke_400(server):
    _, poort = server

    def post(functie, invoer):
        req = urllib.request.Request(f"http://127.0.0.1:{poort}/api/vraag", method="POST",
                                     data=json.dumps({"functie": functie, "invoer": invoer}).encode(),
                                     headers={"content-type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())["detail"]
        return 200, ""

    assert post("dekkingscheck", {"situatie": "x" * 25000}) == (400, "Onjuiste invoer voor dekkingscheck: situatie: te lang (25.000 tekens; maximaal 20.000)")
    code, detail = post("verjaringstoets", {"datum_bekend": 20240310})
    assert code == 400 and "verwacht tekst" in detail
    code, detail = post("schadeberekening", {"verzekerde_som": [1], "werkelijke_waarde": 1, "schade": 1})
    assert code == 400 and "verwacht een getal" in detail
    code, detail = post("schadeberekening", {"werkelijke_waarde": 1, "schade": 1})
    assert code == 400 and "verzekerde_som: dit veld is verplicht" in detail
    code, detail = post("schadeberekening", {"verzekerde_som": "1e30", "werkelijke_waarde": 1, "schade": 1})
    assert code == 400 and "InvalidOperation" not in detail
    code, detail = post("schadeberekening", {"verzekerde_som": 1, "werkelijke_waarde": 1, "schade": 1, "x": 1})
    assert code == 400 and "onbekend veld" in detail
