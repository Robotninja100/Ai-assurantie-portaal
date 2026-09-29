"""
HTTP-laag. FastAPI, server-sent events voor het streamende antwoord.

Antwoordvolgorde per aanvraag - bewust deze volgorde:
  1. 'bronnen'    : direct, nog voor het model begint. De adviseur ziet eerst WAAROP
                    het antwoord gebaseerd gaat worden. Bronnen na het antwoord tonen
                    nodigt uit tot niet-lezen.
  2. 'berekening' : direct, want die komt uit code en hoeft niet te wachten.
  3. 'tekst'      : token voor token.
  4. 'controle'   : de citeerbewaker, over het VOLLEDIGE antwoord.
"""
import json, os, queue, sys, threading, time
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Dict, Any

import features, grounding, llm
from retrieval import Corpus

app = FastAPI(title="Assurantieportaal", docs_url="/api/docs")
FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))


class Aanvraag(BaseModel):
    functie: str
    invoer: Dict[str, Any] = {}


HARTSLAG_SEC = 4          # zolang het model nog niets heeft uitgegeven sturen we elke paar seconden een teken


def _sse(obj: Dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _model_stroom(systeem: str, gebruiker: str, max_tokens: int):
    """
    Draait het taalmodel in een eigen thread, zodat de HTTP-laag een hartslag kan sturen terwijl
    het model nog niets uitgeeft. Op een lokaal CPU-model duurt het eerste teken minuten; een
    stille verbinding wordt door browsers en proxy's afgekapt en laat de adviseur raden of er iets
    gebeurt. Een 'wacht'-gebeurtenis is een eerlijk teken van leven: de tijd die is verstreken.
    """
    q: "queue.Queue" = queue.Queue()
    stop = threading.Event()

    def werk():
        try:
            for e in llm.stream_events(systeem, gebruiker, max_tokens=max_tokens):
                q.put(e)
                if stop.is_set():
                    break
        except Exception as ex:  # noqa: BLE001
            q.put({"type": "fout", "fout": f"{type(ex).__name__}: {ex}", "afgebroken": False})
        finally:
            q.put(None)

    threading.Thread(target=werk, daemon=True).start()
    t0 = time.time()
    try:
        while True:
            try:
                e = q.get(timeout=HARTSLAG_SEC)
            except queue.Empty:
                yield {"type": "wacht", "sec": int(time.time() - t0)}
                continue
            if e is None:
                return
            yield e
    finally:
        stop.set()


@app.get("/api/status")
def status():
    """Eerlijke systeemstatus. De UI toont dit; we doen niet alsof het corpus vol zit."""
    c = features.CORPUS
    rt = llm.runtime_info()
    return {
        "runtime": rt,
        "corpus": c.status,
        "corpus_totaal": c.totaal(),
        "gereed": rt["beschikbaar"] and c.totaal() > 0,
        "waarschuwing": None if c.totaal() > 0 else
            "Corpus is leeg. Het portaal weigert inhoudelijke antwoorden zonder bronnen.",
    }


@app.get("/api/functies")
def functies():
    return [{"id": k, "naam": v["naam"], "groep": v["groep"],
             "omschrijving": v["omschrijving"]} for k, v in features.FUNCTIES.items()]


@app.get("/api/producten")
def producten():
    """De producten waarvoor het corpus polisclausules heeft; de UI bouwt hier haar keuzelijsten van."""
    rijen = features.CORPUS.data.get("polisvoorwaarden", [])
    telling = {}
    for r in rijen:
        telling[r.get("product")] = telling.get(r.get("product"), 0) + 1
    return [{"product": p, "clausules": n} for p, n in sorted(telling.items()) if p]


@app.post("/api/vraag")
def vraag(a: Aanvraag):
    spec = features.FUNCTIES.get(a.functie)
    if not spec:
        raise HTTPException(404, f"Onbekende functie: {a.functie}")
    try:
        opdracht = spec["fn"](**a.invoer)
    except (TypeError, ValueError, ArithmeticError) as e:
        # ArithmeticError vangt ook decimal.InvalidOperation op: een bedrag als "abc".
        raise HTTPException(400, f"Onjuiste invoer voor {a.functie}: {e}")

    def gen():
        t0 = time.time()
        yield _sse({"type": "bronnen", "bronnen": opdracht["bronnen"]})
        if opdracht.get("berekening"):
            yield _sse({"type": "berekening", "berekening": opdracht["berekening"]})

        # Geen bronnen = geen inhoudelijk antwoord. Dit is de kern van citeer-of-weiger:
        # het portaal zwijgt liever dan dat het ongefundeerd praat.
        if not opdracht["bronnen"]:
            boodschap = ("Er zijn geen bronnen gevonden die deze vraag kunnen onderbouwen. "
                         "Het portaal geeft daarom geen inhoudelijk antwoord.\n\n"
                         "Vervolgstap: verfijn de omschrijving, of vul het corpus aan met de "
                         "polisvoorwaarden of uitspraken die op deze casus van toepassing zijn.")
            yield _sse({"type": "weigering", "tekst": boodschap})
            yield _sse({"type": "controle", "controle": {
                "oordeel": "GEWEIGERD_GEEN_BRONNEN", "gefundeerd": [], "ongefundeerd": []}})
            yield "data: [DONE]\n\n"
            return

        volledig, fout = [], None
        for e in _model_stroom(opdracht["systeem"], opdracht["gebruiker"],
                               opdracht.get("max_tokens", 600)):
            if e["type"] == "delta":
                volledig.append(e["tekst"])
                yield _sse({"type": "tekst", "tekst": e["tekst"]})
            elif e["type"] == "fout":
                fout = e
            else:                                   # 'model' en 'wacht' gaan ongewijzigd door
                yield _sse(e)

        antwoord = "".join(volledig)
        if not antwoord.strip():
            # Een leeg antwoord mag nooit doorgaan voor "geen verwijzingen": dat leest als een
            # geslaagde controle. Meld het als wat het is, een storing in de runtime.
            rt = llm.runtime_info()
            reden = (rt.get("opmerking") or "onbekende reden") if not rt.get("beschikbaar") \
                else (fout["fout"] if fout else "het taalmodel gaf geen bruikbaar antwoord.")
            yield _sse({"type": "fout", "afgebroken": False,
                        "fout": "Geen antwoord van het taalmodel: " + reden +
                                " De bronnen en de berekening hierboven zijn wel volledig en gecontroleerd."})
            yield "data: [DONE]\n\n"
            return
        if fout:                                    # halverwege afgebroken: wat er staat is onvolledig
            yield _sse({"type": "fout", "afgebroken": True,
                        "fout": fout["fout"] + " Het antwoord hierboven is onvolledig."})
        controle = grounding.controleer(antwoord, opdracht["opgehaald"])
        controle["duur_sec"] = round(time.time() - t0, 1)
        yield _sse({"type": "controle", "controle": controle})
        if controle["ongefundeerd"]:
            yield _sse({"type": "gemaskeerd", "tekst": grounding.maskeer(antwoord, controle)})
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/herlaad-corpus")
def herlaad():
    """Na een corpus-update opnieuw indexeren zonder de server te herstarten."""
    features.CORPUS = Corpus()
    return {"corpus": features.CORPUS.status, "totaal": features.CORPUS.totaal()}


@app.get("/")
def index():
    p = os.path.join(FRONTEND, "index.html")
    return FileResponse(p) if os.path.exists(p) else JSONResponse(
        {"fout": "frontend nog niet gebouwd"}, status_code=503)


if os.path.isdir(FRONTEND):
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
