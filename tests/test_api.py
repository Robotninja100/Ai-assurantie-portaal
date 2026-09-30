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
    r = client.post("/api/vraag", json={"functie": "verjaringstoets", "invoer": {"datum_bekend": "10 maart 2024"}})
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
    # geen runtime: nooit een stil leeg antwoord. Waar de uitleg uit code komt, zegt het portaal dat en is dat het antwoord.
    assert "model_overgeslagen" in soorten and "tekst" not in soorten
    assert "Er is geen taalmodel beschikbaar" in next(e for e in sse(r) if e["type"] == "model_overgeslagen")["reden"]
    assert "controle" not in soorten               # en dus ook geen schijnbaar geslaagde controle
    # waar de tekst wel van het model moet komen, blijft een storing een storing
    r2 = client.post("/api/vraag", json={"functie": "dekkingscheck", "invoer": {"situatie": "Inbraak via een raam"}})
    assert "fout" in [e["type"] for e in sse(r2)]
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


# ------------------------------------------------------------ het kleine lokale model schrijft geen uitleg bij een berekening

def _lokaal_met_bestand(monkeypatch, tmp_path):
    model = tmp_path / "klein.gguf"
    model.write_bytes(b"x")
    monkeypatch.setattr(llm, "PROVIDER", "local")
    monkeypatch.setattr(llm, "MODEL_PATH", str(model))
    monkeypatch.delenv("ASSURANTIE_MODEL_ALTIJD", raising=False)


def test_lokaal_model_schrijft_niets_bij_een_berekening_uit_code(monkeypatch, tmp_path):
    _lokaal_met_bestand(monkeypatch, tmp_path)
    aangeroepen = []
    monkeypatch.setattr(llm, "stream_events", lambda *a, **k: aangeroepen.append(1) or iter(()))
    for functie, invoer in (("schadeberekening", {"verzekerde_som": 100000, "werkelijke_waarde": 200000, "schade": 40000}),
                            ("verjaringstoets", {"datum_bekend": "2024-03-10"}),
                            ("waardetoets", {"nieuwwaarde": 1000, "ouderdom_jaren": 3, "levensduur_jaren": 8}),
                            ("provisietoets", {"producttype": "autoverzekering", "jaarpremie": 1000, "provisiepercentage": 10}),
                            ("klachtroute", {"situatie": "Afwijzing", "datum_klacht": "2026-09-01"})):
        events = sse(TestClient(api.app).post("/api/vraag", json={"functie": functie, "invoer": invoer}))
        soorten = [e["type"] for e in events]
        assert soorten[0] == "bronnen" and soorten[1] == "berekening", functie
        assert "model_overgeslagen" in soorten and "tekst" not in soorten and "fout" not in soorten and "controle" not in soorten, functie
    assert not aangeroepen                                    # het model is niet eens gestart


def test_lokaal_model_schrijft_wel_waar_de_tekst_niet_uit_code_komt(monkeypatch, tmp_path):
    _lokaal_met_bestand(monkeypatch, tmp_path)
    monkeypatch.setattr(llm, "stream_events", lambda *a, **k: iter([{"type": "model", "model": "m", "provider": "local"},
                                                                     {"type": "delta", "tekst": "Antwoord."}, {"type": "einde", "reden": "stop"}]))
    events = sse(TestClient(api.app).post("/api/vraag", json={"functie": "klachtroute", "invoer": {"situatie": "Afwijzing van de klacht"}}))
    soorten = [e["type"] for e in events]
    assert "model_overgeslagen" not in soorten and "tekst" in soorten     # klachtroute zonder datum: geen berekening, dus het model schrijft
    events = sse(TestClient(api.app).post("/api/vraag", json={"functie": "dekkingscheck", "invoer": {"situatie": "Inbraak via een raam"}}))
    assert "tekst" in [e["type"] for e in events]


def test_model_altijd_dwingt_het_lokale_model_af(monkeypatch, tmp_path):
    _lokaal_met_bestand(monkeypatch, tmp_path)
    monkeypatch.setenv("ASSURANTIE_MODEL_ALTIJD", "1")
    monkeypatch.setattr(llm, "stream_events", lambda *a, **k: iter([{"type": "model", "model": "m", "provider": "local"},
                                                                     {"type": "delta", "tekst": "Antwoord."}, {"type": "einde", "reden": "stop"}]))
    events = sse(TestClient(api.app).post("/api/vraag", json={"functie": "schadeberekening", "invoer": {
        "verzekerde_som": 100000, "werkelijke_waarde": 200000, "schade": 40000}}))
    soorten = [e["type"] for e in events]
    assert "tekst" in soorten and "model_overgeslagen" not in soorten


def test_een_datum_als_dag_maand_jaar_wordt_gelezen(client):
    r = client.post("/api/vraag", json={"functie": "verjaringstoets", "invoer": {"datum_bekend": "10-03-2024", "peildatum": "29-09-2026"}})
    assert r.status_code == 200
