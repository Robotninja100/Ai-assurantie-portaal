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
import asyncio, inspect, json, os, sys, threading, time
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


async def _model_stroom(systeem: str, gebruiker: str, max_tokens: int):
    """
    Draait het taalmodel in een eigen thread, zodat de HTTP-laag een hartslag kan sturen terwijl
    het model nog niets uitgeeft. Op een lokaal CPU-model duurt het eerste teken minuten; een
    stille verbinding wordt door browsers en proxy's afgekapt en laat de adviseur raden of er iets
    gebeurt. Een 'wacht'-gebeurtenis is een eerlijk teken van leven: de tijd die is verstreken.

    Dit is een async generator, met opzet: sluit de adviseur het tabblad of drukt hij op Stop, dan
    annuleert de server dit punt direct en gaat `stop` open. Een sync generator wordt pas bij de
    volgende garbage collection opgeruimd; het model schreef dan nog een heel antwoord voor niemand.
    """
    loop = asyncio.get_running_loop()
    q: "asyncio.Queue" = asyncio.Queue()
    stop = threading.Event()

    def zet(e):
        try:
            loop.call_soon_threadsafe(q.put_nowait, e)
        except RuntimeError:          # de event loop is al gesloten: niemand luistert meer
            pass

    def werk():
        try:
            for e in llm.stream_events(systeem, gebruiker, max_tokens=max_tokens, stop=stop):
                if stop.is_set():
                    break
                zet(e)
        except Exception as ex:  # noqa: BLE001
            zet({"type": "fout", "fout": f"{type(ex).__name__}: {ex}", "afgebroken": False})
        finally:
            zet(None)

    threading.Thread(target=werk, daemon=True).start()
    t0 = time.time()
    try:
        while True:
            try:
                e = await asyncio.wait_for(q.get(), HARTSLAG_SEC)
            except asyncio.TimeoutError:
                yield {"type": "wacht", "sec": int(time.time() - t0)}
                continue
            if e is None:
                return
            yield e
    finally:
        stop.set()


def beoordeel_antwoord(opdracht, antwoord, einde=None, fout=None, duur_sec=None):
    """
    De citeercontrole over het volledige antwoord: (controle, gemaskeerde tekst of None). Eén plek, ook voor
    de criticusronde, zodat wat daar wordt beoordeeld exact is wat de adviseur ziet.
    """
    # Getallen en citaten mogen alleen uit de berekening, de invoer van de adviseur of de bronnen komen.
    # De nummers van opsommingen ('1.' t/m '9.' in de regels en de vraagstelling) tellen niet als getal.
    toegestaan = grounding.zonder_opsomming("\n".join([opdracht["systeem"], opdracht["gebruiker"]]))
    controle = grounding.controleer(antwoord, opdracht["opgehaald"], toegestaan,
                                    json.dumps(opdracht.get("berekening") or {}, ensure_ascii=False),
                                    bronnen_tekst=opdracht["systeem"], invoer_tekst=opdracht["gebruiker"])
    controle["duur_sec"] = duur_sec
    # Een antwoord dat tegen de maximale lengte aanliep eindigt midden in een zin en mist de
    # vervolgstap. Dat mag nooit voor een volledig antwoord doorgaan.
    controle["afgekapt"] = einde in ("length", "max_tokens", "content_filter") or bool(fout and fout.get("afgebroken"))
    controle["einde_reden"] = einde
    return controle, (grounding.maskeer(antwoord, controle) if controle["ongefundeerd"] else None)


MAX_TEKENS = 20_000        # per tekstveld; daarboven is het geen dossier meer maar een misbruik van de dienst


def _controleer_invoer(fn, invoer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Type en lengte van elk veld, vóór de functie het ziet. JSON kent meer typen dan de functies: een
    getal waar tekst hoort, een lijst waar een bedrag hoort. Dat moet een duidelijke 400 worden,
    geen 500 en geen dossier van een half miljoen tekens naar het model.
    """
    params = inspect.signature(fn).parameters
    for naam, p in params.items():
        if p.default is inspect.Parameter.empty and naam not in invoer:
            raise ValueError(f"{naam}: dit veld is verplicht")
    schoon = {}
    for naam, waarde in invoer.items():
        p = params.get(naam)
        if p is None:
            raise ValueError(f"{naam}: onbekend veld")
        soort = p.annotation if p.annotation is not inspect.Parameter.empty else type(p.default)
        if soort is str:
            if waarde is None:
                waarde = ""
            if not isinstance(waarde, str):
                raise ValueError(f"{naam}: verwacht tekst")
            if len(waarde) > MAX_TEKENS:
                raise ValueError(f"{naam}: te lang ({len(waarde):,} tekens; maximaal {MAX_TEKENS:,})".replace(",", "."))
        elif soort in (float, int):
            if isinstance(waarde, bool) or not isinstance(waarde, (int, float, str)):
                raise ValueError(f"{naam}: verwacht een getal")
        elif soort is bool:
            if not isinstance(waarde, (bool, str, int)) or waarde is None:
                raise ValueError(f"{naam}: verwacht ja of nee")
        schoon[naam] = waarde
    return schoon


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
    """
    De producten waarvoor het corpus polisclausules heeft; de UI bouwt hier haar keuzelijsten van.
    `varianten` is product x verzekeraar: een vergelijking gaat over het aanbod van één verzekeraar.
    """
    rijen = features.CORPUS.data.get("polisvoorwaarden", [])
    telling, varianten = {}, {}
    for r in rijen:
        p, v = r.get("product"), r.get("verzekeraar_of_bron")
        if not p:
            continue
        telling[p] = telling.get(p, 0) + 1
        varianten.setdefault(p, {})[v] = varianten.setdefault(p, {}).get(v, 0) + 1
    return [{"product": p, "clausules": n,
             "varianten": [{"waarde": f"{p} · {features._kort(v)}", "verzekeraar": features._kort(v), "clausules": c}
                           for v, c in sorted(varianten[p].items(), key=lambda kv: str(kv[0])) if v]}
            for p, n in sorted(telling.items())]


@app.post("/api/vraag")
def vraag(a: Aanvraag):
    spec = features.FUNCTIES.get(a.functie)
    if not spec:
        raise HTTPException(404, f"Onbekende functie: {a.functie}")
    try:
        opdracht = spec["fn"](**_controleer_invoer(spec["fn"], a.invoer))
    except ArithmeticError:
        # Ook decimal.InvalidOperation: een bedrag als "abc" of een getal dat de rekenkern niet aankan.
        raise HTTPException(400, f"Onjuiste invoer voor {a.functie}: een getal is ongeldig of te groot.")
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"Onjuiste invoer voor {a.functie}: {e}")

    async def gen():
        t0 = time.time()
        yield _sse({"type": "bronnen", "bronnen": opdracht["bronnen"]})
        if opdracht.get("berekening"):
            yield _sse({"type": "berekening", "berekening": opdracht["berekening"]})
        if opdracht.get("opmerkingen"):
            yield _sse({"type": "opmerkingen", "opmerkingen": opdracht["opmerkingen"]})

        # Waar berekening, uitleg en vervolgstap volledig uit code komen, schrijft het kleine lokale model
        # niets: het verzon bij een echte proef redenen die er niet zijn (zie state.json, lokale_modelrun_1).
        # Is er helemaal geen model, dan is de uitleg uit code ook het volledige antwoord. Een sterker model
        # (OpenRouter) herschrijft de uitleg wel. ASSURANTIE_MODEL_ALTIJD=1 dwingt het lokale model af.
        rt0 = llm.runtime_info()
        if (opdracht.get("tekst_uit_code") and not os.environ.get("ASSURANTIE_MODEL_ALTIJD")
                and (rt0["provider"] == "local" or not rt0["beschikbaar"])):
            reden = ("Het lokale model is te klein om dit betrouwbaar uit te leggen: bij een proef verzon het redenen die er niet "
                     "zijn. " if rt0["beschikbaar"] else "Er is geen taalmodel beschikbaar. ")
            yield _sse({"type": "model_overgeslagen",
                        "reden": reden + "De uitleg, de bedragen en de vervolgstap hierboven komen uit code en zijn volledig."})
            yield "data: [DONE]\n\n"
            return

        # Geen bronnen = geen inhoudelijk antwoord. Dit is de kern van citeer-of-weiger:
        # het portaal zwijgt liever dan dat het ongefundeerd praat.
        if not opdracht["bronnen"]:
            yield _sse({"type": "weigering", "tekst": features.weigertekst(opdracht.get("functie", ""))})
            yield _sse({"type": "controle", "controle": {
                "oordeel": "GEWEIGERD_GEEN_BRONNEN", "gefundeerd": [], "ongefundeerd": []}})
            yield "data: [DONE]\n\n"
            return

        volledig, fout, einde = [], None, None
        async for e in _model_stroom(opdracht["systeem"], opdracht["gebruiker"],
                                     opdracht.get("max_tokens", 600)):
            if e["type"] == "delta":
                volledig.append(e["tekst"])
                yield _sse({"type": "tekst", "tekst": e["tekst"]})
            elif e["type"] == "fout":
                fout = e
            elif e["type"] == "einde":
                einde = e["reden"]
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
        controle, gemaskeerd = beoordeel_antwoord(opdracht, antwoord, einde, fout, round(time.time() - t0, 1))
        yield _sse({"type": "controle", "controle": controle})
        if gemaskeerd is not None:
            yield _sse({"type": "gemaskeerd", "tekst": gemaskeerd})
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
