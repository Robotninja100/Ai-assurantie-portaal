"""
Tests voor de HTTP-laag. De taalmodel-runtime wordt uitgezet (lokale provider zonder modelbestand),
zodat de test hetzelfde uitvalt met of zonder OPENROUTER_API_KEY in de omgeving.
"""
import json

import pytest
from fastapi.testclient import TestClient

import api
import llm


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "local")
    monkeypatch.setattr(llm, "MODEL_PATH", "/bestaat/niet.gguf")
    return TestClient(api.app)


def sse(response):
    events = []
    for regel in response.text.splitlines():
        if regel.startswith("data: ") and regel != "data: [DONE]":
            events.append(json.loads(regel[6:]))
    return events


def test_status_is_eerlijk_over_de_runtime(client):
    d = client.get("/api/status").json()
    assert d["corpus_totaal"] > 0
    assert d["runtime"]["beschikbaar"] is False
    assert d["gereed"] is False


def test_er_zijn_twaalf_functies_met_unieke_id(client):
    f = client.get("/api/functies").json()
    assert len(f) == 12
    assert len({x["id"] for x in f}) == 12


def test_onbekende_functie_geeft_404(client):
    assert client.post("/api/vraag", json={"functie": "bestaatniet", "invoer": {}}).status_code == 404


def test_onleesbare_datum_geeft_een_duidelijke_400(client):
    r = client.post("/api/vraag", json={"functie": "verjaringstoets", "invoer": {"datum_bekend": "10-03-2024"}})
    assert r.status_code == 400
    assert "JJJJ-MM-DD" in r.json()["detail"]


def test_onleesbaar_bedrag_geeft_400_en_geen_crash(client):
    r = client.post("/api/vraag", json={"functie": "schadeberekening",
                                        "invoer": {"verzekerde_som": "abc", "werkelijke_waarde": 1, "schade": 1}})
    assert r.status_code == 400


def test_bronnen_en_berekening_komen_voor_het_antwoord_en_een_storing_wordt_gemeld(client):
    r = client.post("/api/vraag", json={"functie": "schadeberekening", "invoer": {
        "verzekerde_som": 200000, "werkelijke_waarde": 250000, "schade": 50000,
        "eigen_risico": 500, "bereddingskosten": 5000}})
    assert r.status_code == 200
    soorten = [e["type"] for e in sse(r)]
    assert soorten[0] == "bronnen"
    assert soorten[1] == "berekening"
    assert "fout" in soorten                       # geen runtime: nooit een stil leeg antwoord
    assert "controle" not in soorten               # en dus ook geen schijnbaar geslaagde controle
    berekening = next(e for e in sse(r) if e["type"] == "berekening")["berekening"]
    assert berekening["bedrag"] == "43500.00"


def test_zonder_bronnen_geen_inhoudelijk_antwoord(client, monkeypatch):
    import features
    monkeypatch.setattr(features, "begripsuitleg", lambda begrip: {
        "functie": "begripsuitleg", "systeem": "", "gebruiker": "", "opgehaald": {},
        "bronnen": [], "berekening": None})
    monkeypatch.setitem(features.FUNCTIES["begripsuitleg"], "fn", features.begripsuitleg)
    events = sse(client.post("/api/vraag", json={"functie": "begripsuitleg", "invoer": {"begrip": "x"}}))
    assert events[-1]["controle"]["oordeel"] == "GEWEIGERD_GEEN_BRONNEN"
