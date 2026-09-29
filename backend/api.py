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
import json, os, sys, time
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
        yield f"data: {json.dumps({'type':'bronnen','bronnen':opdracht['bronnen']}, ensure_ascii=False)}\n\n"
        if opdracht.get("berekening"):
            yield f"data: {json.dumps({'type':'berekening','berekening':opdracht['berekening']}, ensure_ascii=False)}\n\n"

        # Geen bronnen = geen inhoudelijk antwoord. Dit is de kern van citeer-of-weiger:
        # het portaal zwijgt liever dan dat het ongefundeerd praat.
        if not opdracht["bronnen"]:
            boodschap = ("Er zijn geen bronnen gevonden die deze vraag kunnen onderbouwen. "
                         "Het portaal geeft daarom geen inhoudelijk antwoord.\n\n"
                         "Vervolgstap: verfijn de omschrijving, of vul het corpus aan met de "
                         "polisvoorwaarden of uitspraken die op deze casus van toepassing zijn.")
            yield f"data: {json.dumps({'type':'tekst','tekst':boodschap}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type':'controle','controle':{'oordeel':'GEWEIGERD_GEEN_BRONNEN','gefundeerd':[],'ongefundeerd':[]}}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        volledig = []
        try:
            for stuk in llm.stream(opdracht["systeem"], opdracht["gebruiker"],
                                   max_tokens=opdracht.get("max_tokens", 600)):
                volledig.append(stuk)
                yield f"data: {json.dumps({'type':'tekst','tekst':stuk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'fout','fout':f'{type(e).__name__}: {e}'}, ensure_ascii=False)}\n\n"

        antwoord = "".join(volledig)
        if not antwoord.strip():
            # Een leeg antwoord mag nooit doorgaan voor "geen verwijzingen": dat leest als een
            # geslaagde controle. Meld het als wat het is, een storing in de runtime.
            rt = llm.runtime_info()
            reden = (rt.get("opmerking") or "onbekende reden") if not rt.get("beschikbaar") \
                else "het taalmodel gaf geen bruikbaar antwoord"
            yield f"data: {json.dumps({'type':'fout','fout':'Geen antwoord van het taalmodel: ' + reden + ' De bronnen en de berekening hierboven zijn wel volledig en gecontroleerd.'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        controle = grounding.controleer(antwoord, opdracht["opgehaald"])
        controle["duur_sec"] = round(time.time() - t0, 1)
        yield f"data: {json.dumps({'type':'controle','controle':controle}, ensure_ascii=False)}\n\n"
        if controle["ongefundeerd"]:
            yield f"data: {json.dumps({'type':'gemaskeerd','tekst':grounding.maskeer(antwoord, controle)}, ensure_ascii=False)}\n\n"
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
