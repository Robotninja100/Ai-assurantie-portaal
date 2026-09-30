"""
Tests voor de streaminglaag. Een lokale HTTP-server bootst het server-sent-events-formaat van
OpenRouter na. Dat toetst ONZE code (parser, modelketen, denkblokfilter, hartslag), niet de dienst:
of de echte OpenRouter-stroom zo binnenkomt is pas bewezen met een echte sleutel.
"""
import http.server
import json
import os
import threading
import time

import pytest

import api
import llm


class NepOpenRouter:
    def __init__(self):
        self.verzoeken = []                 # modelnamen in volgorde van binnenkomst
        self.poort_geopend = threading.Event()
        self.hek = threading.Event()        # de test opent dit zodra hij het eerste stuk zag
        self.hek_verlopen = False
        nep = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def stuur(self, tekst):
                data = tekst.encode()
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()

            def do_POST(self):
                lengte = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(lengte))
                model = body["model"]
                nep.verzoeken.append(model)
                assert body["stream"] is True
                if model == "429":
                    self.send_response(429)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if model in ("jsonfout", "jsonantwoord"):       # een provider die 'stream' negeert
                    inhoud = ({"error": {"message": "tegoed op"}} if model == "jsonfout" else
                              {"choices": [{"message": {"content": "Compleet antwoord"}, "finish_reason": "stop"}]})
                    data = json.dumps(inhoud).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

                def delta(tekst=None, **extra):
                    d = dict(extra)
                    if tekst is not None:
                        d["content"] = tekst
                    self.stuur("data: " + json.dumps({"choices": [{"delta": d}]}) + "\n\n")

                self.stuur(": OPENROUTER PROCESSING\n\n")
                if model == "ok":
                    delta(None, reasoning="ik denk na")          # redeneerveld: geen antwoord
                    delta("Hallo ")
                    if not nep.hek.wait(timeout=5):
                        nep.hek_verlopen = True
                    delta("wereld")
                elif model == "leeg":
                    pass
                elif model == "midfout":
                    delta("Half ")
                    self.stuur("data: " + json.dumps({"error": {"message": "upstream weggevallen"}}) + "\n\n")
                elif model == "denk":
                    delta("<thi")
                    delta("nk>redeneren</think>\n\nAntwoord")
                elif model == "kapot":                          # de verbinding valt weg zonder [DONE] of finish_reason
                    delta("Een halve ")
                    self.wfile.write(b"0\r\n\r\n")
                    return
                self.stuur("data: [DONE]\n\n")
                self.wfile.write(b"0\r\n\r\n")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/chat/completions"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


@pytest.fixture()
def nep(monkeypatch):
    n = NepOpenRouter()
    monkeypatch.setattr(llm, "OPENROUTER_URL", n.url)
    monkeypatch.setattr(llm, "PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "TIMEOUT_SEC", 10)
    monkeypatch.setenv("OPENROUTER_API_KEY", "testsleutel")
    yield n
    n.hek.set()
    n.stop()


def ketens(monkeypatch, *modellen):
    monkeypatch.setattr(llm, "OPENROUTER_MODELLEN", list(modellen))


# ------------------------------------------------------------ echte streaming

def test_tekst_komt_binnen_terwijl_de_server_nog_bezig_is(nep, monkeypatch):
    ketens(monkeypatch, "ok")
    events = llm.stream_events("s", "g")
    model = next(events)
    eerste = next(events)
    assert model["type"] == "model" and model["model"] == "ok"
    assert eerste == {"type": "delta", "tekst": "Hallo "}
    # De server houdt het tweede stuk vast tot wij dit eerste zagen. Zou de client alles bufferen
    # tot het einde, dan zou dit punt pas na de time-out van de server bereikt worden.
    assert nep.hek_verlopen is False
    nep.hek.set()
    rest = list(events)
    assert "".join(e["tekst"] for e in rest if e["type"] == "delta") == "wereld"


def test_keepalive_en_redeneerveld_worden_genegeerd(nep, monkeypatch):
    ketens(monkeypatch, "ok")
    nep.hek.set()
    assert llm.genereer("s", "g") == "Hallo wereld"


# ------------------------------------------------------------ modelketen

def test_keten_schuift_door_na_een_http_fout_en_meldt_waarom(nep, monkeypatch):
    ketens(monkeypatch, "429", "ok")
    nep.hek.set()
    events = list(llm.stream_events("s", "g"))
    assert events[0]["type"] == "model"
    assert events[0]["model"] == "ok"
    assert events[0]["overgeslagen"] == ["429: HTTP 429"]
    assert nep.verzoeken == ["429", "ok"]


def test_keten_schuift_door_bij_een_leeg_antwoord(nep, monkeypatch):
    ketens(monkeypatch, "leeg", "ok")
    nep.hek.set()
    events = list(llm.stream_events("s", "g"))
    assert events[0]["model"] == "ok"
    assert events[0]["overgeslagen"] == ["leeg: leeg antwoord"]


def test_als_alle_modellen_falen_is_de_reden_per_model_zichtbaar(nep, monkeypatch):
    ketens(monkeypatch, "429", "leeg")
    events = list(llm.stream_events("s", "g"))
    assert len(events) == 1 and events[0]["type"] == "fout"
    assert events[0]["modellen"] == ["429: HTTP 429", "leeg: leeg antwoord"]
    assert list(llm.stream("s", "g")) == []
    assert llm.genereer("s", "g") == ""


def test_valt_een_model_halverwege_uit_dan_wordt_niet_doorgeschoven(nep, monkeypatch):
    # Een tweede model zou een antwoord op een half antwoord schrijven. Dat melden we liever.
    ketens(monkeypatch, "midfout", "ok")
    nep.hek.set()
    events = list(llm.stream_events("s", "g"))
    assert [e["type"] for e in events] == ["model", "delta", "fout"]
    assert events[-1]["afgebroken"] is True
    assert "upstream weggevallen" in events[-1]["fout"] or "viel weg" in events[-1]["fout"]
    assert nep.verzoeken == ["midfout"]


def test_denkblok_uit_het_antwoord_wordt_gefilterd(nep, monkeypatch):
    ketens(monkeypatch, "denk")
    assert llm.genereer("s", "g") == "Antwoord"


# ------------------------------------------------------------ denkblokfilter

@pytest.mark.parametrize("stukken,verwacht", [
    (["<think>a</think>Hoi"], "Hoi"),
    (["<th", "ink>a", "b</th", "ink>\n\nHoi"], "Hoi"),
    (["Hoi ", "daar"], "Hoi daar"),
    (["<b>vet</b> begin"], "<b>vet</b> begin"),          # begint op '<' maar is geen denkblok
    (["<", "b>x"], "<b>x"),
    (["  <think>a</think> Hoi"], "Hoi"),
    (["<think>nooit gesloten"], ""),                       # niets is beter dan denkstappen als antwoord
])
def test_denkblokfilter(stukken, verwacht):
    f = llm._ZonderDenkblok()
    uit = "".join(f.voer(s) for s in stukken) + f.einde()
    assert uit.strip() == verwacht


# ------------------------------------------------------------ terugval en status

def test_zonder_sleutel_valt_het_portaal_zichtbaar_terug_op_het_lokale_model(monkeypatch, tmp_path):
    model = tmp_path / "m.gguf"
    model.write_bytes(b"x")
    monkeypatch.setattr(llm, "PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "MODEL_PATH", str(model))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    info = llm.runtime_info()
    assert info["provider"] == "local" and info["ingesteld"] == "openrouter"
    assert info["beschikbaar"] and info["snelheid"] == "traag"
    assert "Teruggevallen" in info["opmerking"]


def test_zonder_sleutel_en_zonder_model_is_de_runtime_niet_beschikbaar(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "MODEL_PATH", "/bestaat/niet.gguf")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    info = llm.runtime_info()
    assert info["provider"] == "openrouter" and info["beschikbaar"] is False


# ------------------------------------------------------------ hartslag in de API

def test_api_stuurt_een_hartslag_zolang_het_model_nog_niets_uitgeeft(monkeypatch):
    from fastapi.testclient import TestClient

    def traag(systeem, gebruiker, max_tokens=600, temperatuur=0.2, stop=None):
        time.sleep(0.4)
        yield {"type": "model", "model": "test", "provider": "test"}
        yield {"type": "delta", "tekst": "Antwoord zonder verwijzingen."}

    monkeypatch.setattr(llm, "stream_events", traag)
    monkeypatch.setattr(api, "HARTSLAG_SEC", 0.05)
    r = TestClient(api.app).post("/api/vraag", json={"functie": "dekkingscheck", "invoer": {
        "situatie": "Inbraak in de woning via een openstaand raam"}})
    events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ") and l != "data: [DONE]"]
    soorten = [e["type"] for e in events]
    assert soorten.count("wacht") >= 2
    assert soorten.index("bronnen") < soorten.index("wacht") < soorten.index("model") < soorten.index("tekst")
    assert soorten[-1] == "controle"


# ------------------------------------------------------------ afgekapte antwoorden

def test_llm_meldt_hoe_het_model_stopte(nep, monkeypatch):
    ketens(monkeypatch, "ok")
    nep.hek.set()
    events = list(llm.stream_events("s", "g"))
    assert events[-1] == {"type": "einde", "reden": "stop"} or events[-1]["type"] == "einde"


def test_api_markeert_een_afgekapt_antwoord_in_de_controle(monkeypatch):
    from fastapi.testclient import TestClient
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from nep_llm import NepLLM
    n = NepLLM(einde="length", knip=120)
    monkeypatch.setattr(llm, "OPENROUTER_URL", n.url)
    monkeypatch.setattr(llm, "PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "OPENROUTER_MODELLEN", ["m"])
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    try:
        r = TestClient(api.app).post("/api/vraag", json={"functie": "begripsuitleg", "invoer": {"begrip": "onderverzekering"}})
    finally:
        n.stop()
    events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ") and l != "data: [DONE]"]
    controle = next(e for e in events if e["type"] == "controle")["controle"]
    assert controle["afgekapt"] is True


def test_api_meldt_dat_een_te_lange_invoer_is_afgekapt(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(llm, "PROVIDER", "local")
    monkeypatch.setattr(llm, "MODEL_PATH", "/bestaat/niet.gguf")
    lang = "Het dossier bevat een klantprofiel. " * 200          # ruim boven de 6.000 tekens
    r = TestClient(api.app).post("/api/vraag", json={"functie": "dossiercheck", "invoer": {"dossiertekst": lang}})
    events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ") and l != "data: [DONE]"]
    opm = next(e for e in events if e["type"] == "opmerkingen")["opmerkingen"]
    assert "alleen de eerste 6.000" in opm[0]


# ------------------------------------------------------------ onvolledige en afwijkende stromen

def test_een_stroom_die_zonder_einde_stopt_geldt_als_afgebroken_niet_als_compleet(nep, monkeypatch):
    ketens(monkeypatch, "kapot", "ok")
    events = list(llm.stream_events("s", "g"))
    assert [e["type"] for e in events] == ["model", "delta", "fout"]
    assert events[-1]["afgebroken"] is True
    assert "verbroken" in events[-1]["fout"]
    assert nep.verzoeken == ["kapot"]                       # geen tweede model achter een half antwoord


def test_een_kapotte_stroom_zonder_tekst_schuift_wel_door(nep, monkeypatch):
    # (nog geen tekst uitgegeven: doorschuiven is veilig) - het model "leeg" levert helemaal niets
    ketens(monkeypatch, "leeg", "ok")
    nep.hek.set()
    assert llm.genereer("s", "g") == "Hallo wereld"


def test_een_json_fout_bij_http_200_wordt_als_fout_gemeld_niet_als_leeg_antwoord(nep, monkeypatch):
    ketens(monkeypatch, "jsonfout", "ok")
    nep.hek.set()
    events = list(llm.stream_events("s", "g"))
    assert events[0]["model"] == "ok"
    assert events[0]["overgeslagen"] == ["jsonfout: ModelFout: tegoed op"]


def test_een_provider_die_stream_negeert_levert_toch_een_antwoord(nep, monkeypatch):
    ketens(monkeypatch, "jsonantwoord")
    events = list(llm.stream_events("s", "g"))
    assert "".join(e["tekst"] for e in events if e["type"] == "delta") == "Compleet antwoord"
    assert events[-1] == {"type": "einde", "reden": "stop"}


def test_een_tijdslimiet_voor_het_hele_antwoord_stopt_eindeloze_keepalives(nep, monkeypatch):
    monkeypatch.setattr(llm, "TOTAAL_SEC", -1)              # direct verlopen
    ketens(monkeypatch, "ok")
    nep.hek.set()
    events = list(llm.stream_events("s", "g"))
    assert events[-1]["type"] == "fout" and "tijdslimiet" in events[-1]["fout"]


def test_een_gezette_stop_beeindigt_de_stroom_zonder_fout(nep, monkeypatch):
    ketens(monkeypatch, "ok")
    nep.hek.set()
    stop = threading.Event()
    stop.set()
    assert list(llm.stream_events("s", "g", stop=stop)) == []
