"""
Provider-laag voor het taalmodel.

Primair: gratis modellen via OpenRouter, met een keten van terugvalmodellen. Zonder sleutel valt
het portaal terug op een lokaal model (Qwen3-4B via llama.cpp): draait zonder netwerk, maar op een
CPU ruim honderd keer trager. Optioneel: Anthropic of een OpenAI-compatibele dienst. De rest van de
applicatie merkt daar niets van: het corpus en de rekenkern dragen de correctheid, het model levert
alleen de Nederlandse formulering.

Alles loopt via stream_events(). Dat geeft gebeurtenissen in plaats van kale tekst, omdat de
adviseur moet kunnen zien WELK model een antwoord schreef en waarom een ander model het niet deed.
"""
import json
import os
import threading
import time
from typing import Dict, Iterator, List, Optional

# Standaard in de projectmap (models/ staat in .gitignore). Een pad in een tijdelijke sessiemap
# verdween met de container en liet het lokale model stil onbereikbaar worden.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.environ.get("ASSURANTIE_MODEL_PATH",
                            os.path.join(_ROOT, "models", "qwen3-4b.gguf"))
PROVIDER = os.environ.get("ASSURANTIE_LLM_PROVIDER", "openrouter")
OPENROUTER_URL = os.environ.get("ASSURANTIE_OPENROUTER_URL",
                                "https://openrouter.ai/api/v1/chat/completions")

# OpenRouter-modellen die op echte Nederlandse verzekeringsvragen zijn getest: correcte
# evenredigheidsberekening, bruikbaar Nederlands, en schone 'content' (geen modellen die
# uitsluitend een reasoning-veld vullen of hun denkstappen in het antwoord laten lekken).
# Volgorde = voorkeur; bij een fout schuift de keten door naar het volgende model.
OPENROUTER_MODELLEN = [
    m.strip() for m in os.environ.get("ASSURANTIE_MODELLEN", ",".join([
        # Volgorde op GEMETEN gedrag, niet op modelgrootte. Nemotron-super is het
        # grootste model in de lijst maar lekt zijn redeneerstappen in het antwoord
        # ("We need to answer based solely on...") en staat daarom onderaan.
        "inclusionai/ling-3.0-flash-fin:free",
        "nex-agi/nex-n2.5-pro:free",
        "inclusionai/ling-3.0-flash-sante:free",
        "nex-agi/nex-n2.5-mini:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
    ])).split(",") if m.strip()
]

# Tijd die een model mag nemen voor het eerste teken en tussen twee stukken. Gratis modellen
# staan soms in de wachtrij; daarna komt de tekst binnen enkele seconden.
TIMEOUT_SEC = int(os.environ.get("ASSURANTIE_TIMEOUT", "120"))
# Bovengrens voor één antwoord van begin tot eind. Keepalive-regels zetten de leeslimiet steeds terug,
# dus zonder deze grens kan een hangende verbinding eindeloos "bezig" blijven.
TOTAAL_SEC = int(os.environ.get("ASSURANTIE_TOTAAL_TIMEOUT", "300"))


def _laad_env():
    """Leest .env uit de projectmap. Die staat in .gitignore; sleutels horen niet in git."""
    pad = os.path.join(_ROOT, ".env")
    if not os.path.exists(pad):
        return
    for regel in open(pad, encoding="utf-8"):
        regel = regel.strip()
        if not regel or regel.startswith("#") or "=" not in regel:
            continue
        k, v = regel.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_laad_env()

_lock = threading.Lock()
_llm = None
# llama.cpp laat één generatie tegelijk toe op dezelfde instantie. Een tweede verzoek wacht (de UI toont
# de wachttijd) in plaats van het model te laten crashen.
_lokaal_slot = threading.Semaphore(1)


# ------------------------------------------------------------------ status

def effectieve_provider() -> str:
    """
    De provider die nu daadwerkelijk wordt gebruikt. Staat OpenRouter ingesteld maar ontbreekt de
    sleutel, dan valt het portaal terug op het lokale model als dat er ligt. Dat gebeurt zichtbaar:
    runtime_info() meldt het, en de UI toont het.
    """
    if PROVIDER == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
        return "local" if os.path.exists(MODEL_PATH) else "openrouter"
    return PROVIDER


def runtime_info() -> Dict:
    """Eerlijke status. De UI toont dit; we verbergen niet welk model er draait."""
    prov = effectieve_provider()
    info = {"provider": prov, "ingesteld": PROVIDER, "beschikbaar": False, "model": None,
            "opmerking": "", "snelheid": None}
    if prov == "local":
        info["model"] = os.path.basename(MODEL_PATH)
        if os.path.exists(MODEL_PATH):
            info["beschikbaar"] = True
            info["snelheid"] = "traag"
            info["opmerking"] = (
                "Lokaal model op CPU: een antwoord duurt minuten. "
                + ("Teruggevallen omdat OPENROUTER_API_KEY ontbreekt. "
                   if PROVIDER == "openrouter" else "")
                + "Feiten komen uit het corpus, niet uit het model.")
        else:
            info["opmerking"] = "Het lokale modelbestand ontbreekt (zie ASSURANTIE_MODEL_PATH in de README)."
    elif prov == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY")
        info["beschikbaar"] = bool(key)
        info["model"] = OPENROUTER_MODELLEN[0] if OPENROUTER_MODELLEN else None
        info["fallbacks"] = OPENROUTER_MODELLEN[1:]
        info["snelheid"] = "snel" if key else None
        info["opmerking"] = (
            "Gratis modellen via OpenRouter, meestal een paar seconden per antwoord. "
            "Feiten komen uit het corpus, niet uit het model."
            if key else
            "Geen OPENROUTER_API_KEY gevonden en geen lokaal model aanwezig. Zet de sleutel in de "
            "omgeving of in .env, of plaats een GGUF-model in models/ (zie de README).")
    else:
        key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")
        info["beschikbaar"] = bool(key)
        info["model"] = os.environ.get("ASSURANTIE_MODEL_NAAM", "onbekend")
        if not key:
            info["opmerking"] = "Geen API-sleutel ingesteld voor deze provider."
    return info


# ------------------------------------------------------------------ denkblokken

class _ZonderDenkblok:
    """
    Sommige modellen (Qwen3, DeepSeek-distillaties) openen hun antwoord met <think>...</think>.
    Dat zijn redeneerstappen, geen antwoord: ze horen niet bij de adviseur. Streamingveilig: houdt
    tekst vast zolang het begin nog een denkblok kan zijn.
    """
    OPEN, SLUIT = "<think>", "</think>"

    def __init__(self):
        self.stand = "begin"          # begin -> (denken ->) door
        self.buf = ""
        self.kaal = True              # nog niets uitgegeven: voorloop-witruimte is nooit inhoud

    def voer(self, stuk: str) -> str:
        uit = self._voer(stuk)
        if self.kaal and uit:
            uit = uit.lstrip()
            if uit:
                self.kaal = False
        return uit

    def _voer(self, stuk: str) -> str:
        if self.stand == "door":
            return stuk
        self.buf += stuk
        if self.stand == "begin":
            kaal = self.buf.lstrip()
            if not kaal:
                return ""
            if len(kaal) < len(self.OPEN) and self.OPEN.startswith(kaal):
                return ""             # nog onduidelijk of dit <think> wordt
            if kaal.startswith(self.OPEN):
                self.stand = "denken"
                self.buf = kaal[len(self.OPEN):]
            else:
                uit, self.buf, self.stand = self.buf, "", "door"
                return uit
        if self.stand == "denken":
            i = self.buf.find(self.SLUIT)
            if i < 0:
                self.buf = self.buf[-len(self.SLUIT):]   # bewaar alleen een mogelijk begin van </think>
                return ""
            rest = self.buf[i + len(self.SLUIT):].lstrip()
            self.buf, self.stand = "", "door"
            return rest
        return ""

    def einde(self) -> str:
        """Wat er nog vastzit als de stroom eindigt (een antwoord dat toevallig op '<' begon)."""
        if self.stand == "begin":
            uit, self.buf = self.buf, ""
            return uit.lstrip() if self.kaal else uit
        return ""


class ModelFout(Exception):
    pass


# ------------------------------------------------------------------ OpenRouter

def _uit_json_body(body: bytes) -> Iterator[Dict]:
    """Een provider die 'stream' negeert stuurt één JSON-antwoord: een fout, of het complete antwoord."""
    try:
        d = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        raise ModelFout("het antwoord was geen server-sent events en ook geen leesbare JSON")
    if d.get("error"):
        fout = d["error"]
        raise ModelFout(fout.get("message") if isinstance(fout, dict) else str(fout))
    for keuze in d.get("choices") or []:
        tekst = (keuze.get("message") or {}).get("content")
        if tekst:
            yield {"tekst": tekst}
        yield {"einde": keuze.get("finish_reason") or "stop"}


def _openrouter_stukken(model: str, systeem: str, gebruiker: str, max_tokens: int,
                        temperatuur: float, key: str, stop: Optional[threading.Event] = None) -> Iterator[Dict]:
    """
    Eén model, echte server-sent events. Geeft {'tekst': ...} zodra tekst binnenkomt en {'einde': reden}
    aan het eind. Een stroom die stopt zonder [DONE] of finish_reason is afgebroken, niet compleet.
    """
    import urllib.request
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "temperature": temperatuur, "stream": True,
        "messages": [{"role": "system", "content": systeem},
                     {"role": "user", "content": gebruiker}]}).encode()
    req = urllib.request.Request(
        OPENROUTER_URL, data=body,
        headers={"content-type": "application/json", "accept": "text/event-stream",
                 "authorization": f"Bearer {key}", "X-Title": "Assurantieportaal"})
    t0 = time.monotonic()
    klaar = False
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
        if "event-stream" not in (r.headers.get("Content-Type") or "").lower():
            yield from _uit_json_body(r.read(2_000_000))
            return
        while True:
            if stop is not None and stop.is_set():
                return
            if time.monotonic() - t0 > TOTAAL_SEC:
                raise ModelFout(f"de tijdslimiet van {TOTAAL_SEC} seconden is overschreden")
            ruw = r.readline()
            if not ruw:
                if not klaar:
                    raise ModelFout("de verbinding werd verbroken voordat het antwoord compleet was")
                return
            regel = ruw.decode("utf-8", "replace").strip()
            # lege regels scheiden gebeurtenissen; ': OPENROUTER PROCESSING' is een keepalive
            if not regel or regel.startswith(":") or not regel.startswith("data:"):
                continue
            data = regel[5:].strip()
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if chunk.get("error"):
                fout = chunk["error"]
                raise ModelFout(fout.get("message") if isinstance(fout, dict) else str(fout))
            for keuze in chunk.get("choices") or []:
                tekst = (keuze.get("delta") or {}).get("content")
                if tekst:                 # 'reasoning' staat in een eigen veld en telt niet mee
                    yield {"tekst": tekst}
                if keuze.get("finish_reason"):
                    klaar = True
                    yield {"einde": keuze["finish_reason"]}


def _stream_openrouter(systeem, gebruiker, max_tokens, temperatuur,
                       stop: Optional[threading.Event] = None) -> Iterator[Dict]:
    """
    Probeert de modellen op volgorde. Gratis modellen zijn wisselend beschikbaar (403, 429, een
    wachtrij, of een leeg antwoord bij redeneermodellen), dus een keten is hier een voorwaarde.

    Doorschuiven naar het volgende model kan ALLEEN zolang er nog geen tekst is uitgegeven. Valt
    een model halverwege uit, dan zou een tweede model een antwoord op een antwoord schrijven: dat
    melden we als afgebroken antwoord, we plakken er niets achter.
    """
    import urllib.error
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        yield {"type": "fout", "fout": "Geen OPENROUTER_API_KEY.", "afgebroken": False}
        return
    redenen: List[str] = []
    for model in OPENROUTER_MODELLEN:
        filter_ = _ZonderDenkblok()
        gaf_tekst = False
        eindreden = None

        def kop() -> Dict:
            return {"type": "model", "model": model, "provider": "openrouter",
                    "overgeslagen": list(redenen)}
        try:
            for onderdeel in _openrouter_stukken(model, systeem, gebruiker, max_tokens, temperatuur, key, stop):
                if "einde" in onderdeel:
                    eindreden = onderdeel["einde"]
                    continue
                uit = filter_.voer(onderdeel["tekst"])
                if not uit:
                    continue
                if not gaf_tekst:
                    gaf_tekst = True
                    yield kop()
                yield {"type": "delta", "tekst": uit}
            if stop is not None and stop.is_set():
                return                      # de aanvrager is weg: niets meer uitgeven, niets doorschuiven
            rest = filter_.einde()
            if rest:
                if not gaf_tekst:
                    gaf_tekst = True
                    yield kop()
                yield {"type": "delta", "tekst": rest}
            if gaf_tekst:
                yield {"type": "einde", "reden": eindreden or "stop"}
                return
            redenen.append(f"{model}: leeg antwoord")
        except urllib.error.HTTPError as e:
            if gaf_tekst:
                yield {"type": "fout", "afgebroken": True, "model": model,
                       "fout": f"{model} viel weg tijdens het antwoord (HTTP {e.code})."}
                return
            redenen.append(f"{model}: HTTP {e.code}")
        except Exception as e:  # noqa: BLE001 - netwerk, timeout, ModelFout, ongeldige stroom
            if gaf_tekst:
                yield {"type": "fout", "afgebroken": True, "model": model,
                       "fout": f"{model} viel weg tijdens het antwoord ({type(e).__name__}: {e})."}
                return
            redenen.append(f"{model}: {type(e).__name__}" + (f": {e}" if str(e) else ""))
    yield {"type": "fout", "afgebroken": False, "modellen": redenen,
           "fout": "Alle modellen in de keten faalden: " + "; ".join(redenen)}


# ------------------------------------------------------------------ lokaal

def _get_local():
    global _llm
    with _lock:
        if _llm is None:
            from llama_cpp import Llama
            _llm = Llama(model_path=MODEL_PATH, n_ctx=12288,
                         n_threads=os.cpu_count() or 4, verbose=False)
        return _llm


def _stream_local(systeem, gebruiker, max_tokens, temperatuur,
                  stop: Optional[threading.Event] = None) -> Iterator[Dict]:
    if not os.path.exists(MODEL_PATH):
        yield {"type": "fout", "afgebroken": False,
               "fout": "Het lokale modelbestand ontbreekt (zie de README)."}
        return
    filter_ = _ZonderDenkblok()
    gaf_tekst = False
    eindreden = None
    naam = os.path.basename(MODEL_PATH)
    _lokaal_slot.acquire()
    stroom = None
    try:
        # Wie tijdens het wachten op het slot is weggegaan mag geen prefill van minuten meer kosten.
        if stop is not None and stop.is_set():
            return
        # '/no_think' schakelt bij Qwen3 het redeneerblok uit; op een CPU kost elk token seconden.
        stroom = _get_local().create_chat_completion(
            messages=[{"role": "system", "content": systeem},
                      {"role": "user", "content": gebruiker + "\n\n/no_think"}],
            max_tokens=max_tokens, temperature=temperatuur, stream=True)
        for chunk in stroom:
            if stop is not None and stop.is_set():
                return
            if chunk["choices"][0].get("finish_reason"):
                eindreden = chunk["choices"][0]["finish_reason"]
            stuk = chunk["choices"][0].get("delta", {}).get("content")
            if not stuk:
                continue
            uit = filter_.voer(stuk)
            if uit:
                if not gaf_tekst:
                    gaf_tekst = True
                    yield {"type": "model", "model": naam, "provider": "local"}
                yield {"type": "delta", "tekst": uit}
        rest = filter_.einde()
        if rest:
            if not gaf_tekst:
                gaf_tekst = True
                yield {"type": "model", "model": naam, "provider": "local"}
            yield {"type": "delta", "tekst": rest}
    except Exception as e:  # noqa: BLE001
        yield {"type": "fout", "afgebroken": gaf_tekst,
               "fout": f"Lokaal model faalde: {type(e).__name__}: {e}"}
        return
    finally:
        if stroom is not None and hasattr(stroom, "close"):
            stroom.close()
        _lokaal_slot.release()
    if not gaf_tekst:
        yield {"type": "fout", "afgebroken": False, "fout": "Het lokale model gaf een leeg antwoord."}
    else:
        yield {"type": "einde", "reden": eindreden or "stop"}


# ------------------------------------------------------------------ overige providers

def _volledig_anthropic(systeem, gebruiker, max_tokens, temperatuur) -> str:
    import urllib.request
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return ""
    body = json.dumps({
        "model": os.environ.get("ASSURANTIE_MODEL_NAAM", "claude-sonnet-5"),
        "max_tokens": max_tokens, "system": systeem,
        "messages": [{"role": "user", "content": gebruiker}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return json.loads(resp.read())["content"][0]["text"].strip()


def _volledig_openai_compatibel(systeem, gebruiker, max_tokens, temperatuur) -> str:
    """Groq, Mistral e.d. via LLM_API_KEY en LLM_BASE_URL."""
    import urllib.request
    key = os.environ.get("LLM_API_KEY", "")
    base = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    if not key:
        return ""
    body = json.dumps({
        "model": os.environ.get("ASSURANTIE_MODEL_NAAM", "llama-3.3-70b-versatile"),
        "max_tokens": max_tokens, "temperature": temperatuur,
        "messages": [{"role": "system", "content": systeem},
                     {"role": "user", "content": gebruiker}]}).encode()
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=body,
        headers={"content-type": "application/json", "authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"].strip()


def _stream_volledig(functie, naam: str, systeem, gebruiker, max_tokens, temperatuur) -> Iterator[Dict]:
    """Providers zonder eigen streaming: één antwoord, in stukjes uitgegeven."""
    try:
        tekst = functie(systeem, gebruiker, max_tokens, temperatuur)
    except Exception as e:  # noqa: BLE001
        yield {"type": "fout", "afgebroken": False, "fout": f"{naam} faalde: {type(e).__name__}: {e}"}
        return
    if not tekst:
        yield {"type": "fout", "afgebroken": False, "fout": f"{naam} gaf geen antwoord (sleutel ontbreekt?)."}
        return
    yield {"type": "model", "model": os.environ.get("ASSURANTIE_MODEL_NAAM", naam), "provider": naam}
    for i in range(0, len(tekst), 24):
        yield {"type": "delta", "tekst": tekst[i:i + 24]}


# ------------------------------------------------------------------ publieke interface

def stream_events(systeem: str, gebruiker: str, max_tokens: int = 700,
                  temperatuur: float = 0.2, stop: Optional[threading.Event] = None) -> Iterator[Dict]:
    """
    Gebeurtenissen van één generatie:
      {"type": "model", "model", "provider", ["overgeslagen": [...]]}   zodra het eerste teken er is
      {"type": "delta", "tekst"}                                         tekst zodra die binnenkomt
      {"type": "einde", "reden": "stop" | "length" | ...}                 hoe het model stopte; 'length' = afgekapt
      {"type": "fout", "fout", "afgebroken": bool, ["modellen": [...]]}  einde zonder (volledig) antwoord

    Dit is geen cosmetica. Op een lokale CPU-runtime duurt een antwoord van 400 tokens minuten;
    meelezen terwijl het opbouwt maakt het werkbaar. De snelheid van het model is een gegeven, de
    beleving ervan is een ontwerpkeuze.

    `stop` is een Event waarmee de aanvrager zegt dat hij weg is (tabblad dicht, Stop ingedrukt): de
    generatie houdt dan zo snel mogelijk op en een wachtend lokaal verzoek begint niet meer.
    """
    prov = effectieve_provider()
    if prov == "local":
        yield from _stream_local(systeem, gebruiker, max_tokens, temperatuur, stop)
    elif prov == "openrouter":
        yield from _stream_openrouter(systeem, gebruiker, max_tokens, temperatuur, stop)
    elif prov == "anthropic":
        yield from _stream_volledig(_volledig_anthropic, "anthropic", systeem, gebruiker,
                                    max_tokens, temperatuur)
    else:
        yield from _stream_volledig(_volledig_openai_compatibel, "openai-compatibel", systeem,
                                    gebruiker, max_tokens, temperatuur)


def stream(systeem: str, gebruiker: str, max_tokens: int = 700, temperatuur: float = 0.2):
    """Alleen de tekststukken. Bij een fout zonder antwoord blijft de stroom leeg."""
    for e in stream_events(systeem, gebruiker, max_tokens, temperatuur):
        if e["type"] == "delta":
            yield e["tekst"]


def genereer(systeem: str, gebruiker: str, max_tokens: int = 700, temperatuur: float = 0.2) -> str:
    """Eén synchrone completion. Geeft '' terug als er geen runtime is."""
    return "".join(stream(systeem, gebruiker, max_tokens, temperatuur)).strip()
