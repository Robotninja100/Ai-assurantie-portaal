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


# Het begin van een antwoord wordt door de kopcontrole vastgehouden tot KOP_TEKENS tekens (of het einde). Een
# testantwoord dat als 'al zichtbaar' moet gelden begint daarom met minstens zoveel tekens gewoon Nederlands.
OK_BEGIN = "Dit is het begin van een antwoord in gewoon Nederlands, "
assert len(OK_BEGIN) > llm.KOP_TEKENS


class NepOpenRouter:
    def __init__(self):
        self.verzoeken = []                 # modelnamen in volgorde van binnenkomst
        self.poort_geopend = threading.Event()
        self.hek = threading.Event()        # de test opent dit zodra hij het eerste stuk zag
        self.hek_verlopen = False
        self.live_ids = None                # wat /v1/models teruggeeft; None = de lijst is niet te lezen (HTTP 500)
        self.live_vertraging = 0.0
        self.modellen_verzoeken = 0         # zoveel keer is de modellenlijst opgevraagd
        nep = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def stuur(self, tekst):
                data = tekst.encode()
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()

            def do_GET(self):
                nep.modellen_verzoeken += 1
                time.sleep(nep.live_vertraging)
                if nep.live_ids is None:
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = json.dumps({"data": [{"id": m} for m in nep.live_ids]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

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
                    delta(OK_BEGIN)
                    if not nep.hek.wait(timeout=5):
                        nep.hek_verlopen = True
                    delta("wereld")
                elif model == "leeg":
                    pass
                elif model == "midfout":                        # valt weg NADAT het begin al is uitgegeven
                    delta(OK_BEGIN)
                    self.stuur("data: " + json.dumps({"error": {"message": "upstream weggevallen"}}) + "\n\n")
                elif model == "kortefout":                      # valt weg binnen het vastgehouden begin: nog niets uitgegeven
                    delta("Half ")
                    self.stuur("data: " + json.dumps({"error": {"message": "upstream weggevallen"}}) + "\n\n")
                elif model == "denk":
                    delta("<thi")
                    delta("nk>redeneren</think>\n\nAntwoord")
                elif model == "kapot":                          # de verbinding valt weg zonder [DONE] of finish_reason
                    delta(OK_BEGIN)
                    self.wfile.write(b"0\r\n\r\n")
                    return
                elif model == "lekt":                           # zoals Nemotron: de redeneerstappen staan in het antwoord
                    delta("We need to answer based solely on the sources provided. ")
                    delta("The user asks about the policy. Let's compute the answer step by step now.")
                elif model == "engels":
                    delta("The policy covers damage caused by fire and the insurer must pay the claim ")
                    delta("within thirty days after the notification of the loss.")
                elif model == "kort":                           # korter dan het vastgehouden begin, maar gewoon Nederlands
                    delta("Dit staat niet in de geraadpleegde bronnen.")
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
    assert eerste == {"type": "delta", "tekst": OK_BEGIN}
    # De server houdt het tweede stuk vast tot wij dit eerste zagen. Zou de client alles bufferen
    # tot het einde, dan zou dit punt pas na de time-out van de server bereikt worden.
    assert nep.hek_verlopen is False
    nep.hek.set()
    rest = list(events)
    assert "".join(e["tekst"] for e in rest if e["type"] == "delta") == "wereld"


def test_keepalive_en_redeneerveld_worden_genegeerd(nep, monkeypatch):
    ketens(monkeypatch, "ok")
    nep.hek.set()
    assert llm.genereer("s", "g") == OK_BEGIN + "wereld"


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


# ------------------------------------------------------------ kopcontrole: geen redeneerstappen of Engels naar de adviseur

def test_een_model_dat_redeneerstappen_uitgeeft_wordt_overgeslagen_voordat_de_adviseur_ze_ziet(nep, monkeypatch):
    ketens(monkeypatch, "lekt", "ok")
    nep.hek.set()
    events = list(llm.stream_events("s", "g"))
    tekst = "".join(e["tekst"] for e in events if e["type"] == "delta")
    assert events[0]["model"] == "ok"
    assert events[0]["overgeslagen"] == ["lekt: schrijft redeneerstappen in het antwoord"]
    assert "We need to" not in tekst and "The user" not in tekst
    assert nep.verzoeken == ["lekt", "ok"]


def test_een_model_dat_engels_schrijft_wordt_overgeslagen(nep, monkeypatch):
    ketens(monkeypatch, "engels", "ok")
    nep.hek.set()
    events = list(llm.stream_events("s", "g"))
    assert events[0]["model"] == "ok"
    assert events[0]["overgeslagen"] == ["engels: antwoordt in het Engels"]
    assert "policy covers" not in "".join(e.get("tekst", "") for e in events)


def test_lekken_alle_modellen_dan_krijgt_de_adviseur_niets_en_ziet_hij_waarom(nep, monkeypatch):
    ketens(monkeypatch, "lekt", "engels")
    events = list(llm.stream_events("s", "g"))
    assert [e["type"] for e in events] == ["fout"]
    assert events[0]["modellen"] == ["lekt: schrijft redeneerstappen in het antwoord", "engels: antwoordt in het Engels"]


def test_een_kort_nederlands_antwoord_haalt_de_kopcontrole_en_komt_ongewijzigd_aan(nep, monkeypatch):
    ketens(monkeypatch, "kort")
    events = list(llm.stream_events("s", "g"))
    assert "".join(e["tekst"] for e in events if e["type"] == "delta") == "Dit staat niet in de geraadpleegde bronnen."
    assert events[-1] == {"type": "einde", "reden": "stop"}


def test_valt_een_model_uit_binnen_het_vastgehouden_begin_dan_schuift_de_keten_wel_door(nep, monkeypatch):
    # Er is nog niets uitgegeven, dus doorschuiven schrijft geen antwoord op een half antwoord.
    ketens(monkeypatch, "kortefout", "ok")
    nep.hek.set()
    events = list(llm.stream_events("s", "g"))
    assert events[0]["model"] == "ok" and events[0]["overgeslagen"][0].startswith("kortefout: ")
    assert nep.verzoeken == ["kortefout", "ok"]


@pytest.mark.parametrize("tekst,reden", [
    ("We need to answer based solely on the sources provided.", "redeneerstappen"),
    ("Okay, so the user wants to know about the policy conditions.", "redeneerstappen"),
    ("Let's compute the answer step by step before we write it down.", "redeneerstappen"),
    ("The user asks", "redeneerstappen"),
    ("The policy covers damage caused by fire and the insurer must pay the claim", "Engels"),
    ("Let op: de polis dekt alleen schade door brand, niet door opzet.", None),
    ("We hebben de berekening gecontroleerd; de uitkering is € 20.000.", None),
    ("De uitkering is lager omdat de verzekerde som lager is dan de werkelijke waarde (art. 7:958 BW).", None),
    ("**Dekking**\n\nDe polis dekt schade door brand, maar niet door opzet.", None),
    ("1. **Welke stap is nu aan de orde?** We moeten binnen twee weken bevestigen.", None),
    ("Dit staat niet in de geraadpleegde bronnen.", None),
])
def test_kopcontrole_herkent_gemeten_gedrag_en_laat_nederlands_met_rust(tekst, reden):
    uitkomst = llm._kop_afgekeurd(tekst)
    assert (uitkomst is None) if reden is None else (reden in (uitkomst or ""))


# ------------------------------------------------------------ de keten van nu: wat OpenRouter niet meer aanbiedt

@pytest.fixture()
def live(nep, monkeypatch):
    monkeypatch.setattr(llm, "LIVE_KETEN", True)
    return nep


def test_modellen_die_openrouter_niet_meer_aanbiedt_worden_niet_eens_geprobeerd(live, monkeypatch):
    ketens(monkeypatch, "weg1", "ok", "weg2")
    live.live_ids = ["ok", "429"]
    live.hek.set()
    keten = llm.modelketen()
    assert keten["modellen"] == ["ok"] and keten["verdwenen"] == ["weg1", "weg2"] and keten["bron"] == "live"
    events = list(llm.stream_events("s", "g"))
    assert events[0]["model"] == "ok" and events[0]["overgeslagen"] == []      # geen ruis over modellen die er niet meer zijn
    assert live.verzoeken == ["ok"]


def test_is_de_lijst_niet_te_lezen_dan_geldt_de_ingestelde_keten_en_wordt_niet_bij_elk_verzoek_opnieuw_geprobeerd(live, monkeypatch):
    ketens(monkeypatch, "429", "ok")
    live.live_ids = None                                   # HTTP 500
    live.hek.set()
    for _ in range(3):
        keten = llm.modelketen()
        assert keten["modellen"] == ["429", "ok"] and keten["bron"] == "statisch" and keten["verdwenen"] == []
    assert live.modellen_verzoeken == 1                    # een mislukte poging wordt even onthouden
    events = list(llm.stream_events("s", "g"))
    assert events[0]["model"] == "ok"                      # en de keten werkt gewoon


def test_de_lijst_wordt_een_uur_onthouden(live, monkeypatch):
    ketens(monkeypatch, "ok")
    live.live_ids = ["ok"]
    for _ in range(4):
        assert llm.modelketen()["bron"] == "live"
    assert live.modellen_verzoeken == 1
    # na de geldigheidsduur wordt opnieuw gelezen
    monkeypatch.setitem(llm._live, "tijd", llm._live["tijd"] - llm.LIVE_TTL_SEC - 1)
    llm.modelketen()
    assert live.modellen_verzoeken == 2


def test_een_zelf_ingestelde_keten_wordt_nooit_aangepast_alleen_gemeld(live, monkeypatch):
    ketens(monkeypatch, "weg", "ok")
    monkeypatch.setattr(llm, "_KETEN_EXPLICIET", True)
    live.live_ids = ["ok"]
    keten = llm.modelketen()
    assert keten["modellen"] == ["weg", "ok"] and keten["bron"] == "ingesteld" and keten["verdwenen"] == ["weg"]


def test_bestaat_volgens_de_lijst_niets_meer_dan_wordt_toch_geprobeerd_en_zegt_de_fout_wat_verdween(live, monkeypatch):
    # De lijst kan onvolledig zijn; liever proberen dan niets. Bestaat het echt niet, dan staat er wat er is gebeurd.
    ketens(monkeypatch, "429", "leeg")
    live.live_ids = ["iets-anders"]
    events = list(llm.stream_events("s", "g"))
    assert live.verzoeken == ["429", "leeg"]
    assert events[-1]["type"] == "fout" and events[-1]["modellen"] == ["429: HTTP 429", "leeg: leeg antwoord"]
    assert "probe_llm.py --live" in events[-1]["fout"]


def test_de_status_meldt_de_keten_van_nu_en_wat_ongemeten_is(live, monkeypatch):
    ketens(monkeypatch, "weg", "qwen/qwen3.8-27b:free", "inclusionai/ling-3.0-flash-sante:free")
    live.live_ids = ["qwen/qwen3.8-27b:free", "inclusionai/ling-3.0-flash-sante:free"]
    llm.live_modellen(wacht=True)
    info = llm.runtime_info()
    assert info["model"] == "qwen/qwen3.8-27b:free" and info["fallbacks"] == ["inclusionai/ling-3.0-flash-sante:free"]
    assert info["keten_bron"] == "live" and info["keten_verdwenen"] == ["weg"]
    assert "niet meer aangeboden" in info["opmerking"] and "nog niet gemeten" in info["opmerking"]


def test_de_statuspagina_wacht_nooit_op_het_netwerk(live, monkeypatch):
    ketens(monkeypatch, "a", "b")
    live.live_ids = ["a"]
    live.live_vertraging = 1.5
    t0 = time.monotonic()
    info = llm.runtime_info()
    assert time.monotonic() - t0 < 1.0                     # de lijst wordt op de achtergrond gelezen
    assert info["keten_bron"] == "statisch"                # nog niets bekend, dus de ingestelde keten
    for _ in range(100):                                   # de achtergrondtaak rondt af; daarna geldt de live-lijst
        if not llm._live["bezig"] and llm._live["ids"] is not None:
            break
        time.sleep(0.05)
    assert llm.runtime_info()["keten_bron"] == "live"


def test_de_standaardketen_bevat_geen_model_dat_gemeten_en_afgewezen_is():
    afgewezen = ("gemma-4", "inkling", "laguna", "nemotron-3.5-lightning", "dots-3-note", "lfm-2.5", "content-safety")
    for m in llm._STANDAARD_KETEN:
        assert not any(a in m for a in afgewezen), m
    assert llm._STANDAARD_KETEN[-1] in llm.GEMETEN_LEKT          # het model dat lekt staat onderaan


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
    assert llm.genereer("s", "g") == OK_BEGIN + "wereld"


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
