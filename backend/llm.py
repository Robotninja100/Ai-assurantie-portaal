"""
Provider-laag voor het taalmodel.

Nu: lokaal Qwen3-4B via llama.cpp. Geen API-key, geen kosten, draait echt.
Later: zet ASSURANTIE_LLM_PROVIDER=anthropic|groq|openrouter + een key, en de rest
van de applicatie verandert niet. Dat is bewust: het corpus en de rekenkern dragen
de correctheid, het model levert alleen de Nederlandse formulering.
"""
import os, threading, json
from typing import Optional, List, Dict

MODEL_PATH = os.environ.get(
    "ASSURANTIE_MODEL_PATH",
    "/tmp/claude-0/-home-user-Ai-assurantie-portaal/"
    "a2ab93d0-b5a6-5ccb-a5c5-6eb44b6f32e7/scratchpad/models/qwen3-4b.gguf")
PROVIDER = os.environ.get("ASSURANTIE_LLM_PROVIDER", "local")

_lock = threading.Lock()
_llm = None


def runtime_info() -> Dict:
    """Eerlijke status. De UI toont dit; we verbergen niet welk model er draait."""
    info = {"provider": PROVIDER, "beschikbaar": False, "model": None, "opmerking": ""}
    if PROVIDER == "local":
        info["model"] = os.path.basename(MODEL_PATH)
        if os.path.exists(MODEL_PATH):
            info["beschikbaar"] = True
            info["opmerking"] = ("Lokaal model op CPU, circa 6-7 tokens/sec. "
                                 "Feiten komen uit het corpus, niet uit het model.")
        else:
            info["opmerking"] = f"Modelbestand niet gevonden op {MODEL_PATH}"
    else:
        key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")
        info["beschikbaar"] = bool(key)
        info["model"] = os.environ.get("ASSURANTIE_MODEL_NAAM", "onbekend")
        if not key:
            info["opmerking"] = "Geen API-sleutel ingesteld voor deze provider."
    return info


def _get_local():
    global _llm
    with _lock:
        if _llm is None:
            from llama_cpp import Llama
            _llm = Llama(model_path=MODEL_PATH, n_ctx=8192,
                         n_threads=os.cpu_count() or 4, verbose=False)
        return _llm


def genereer(systeem: str, gebruiker: str, max_tokens: int = 700,
             temperatuur: float = 0.2) -> str:
    """Eén synchrone completion. Geeft '' terug als er geen runtime is."""
    if PROVIDER == "local":
        if not os.path.exists(MODEL_PATH):
            return ""
        r = _get_local().create_chat_completion(
            messages=[{"role": "system", "content": systeem},
                      {"role": "user", "content": gebruiker}],
            max_tokens=max_tokens, temperature=temperatuur)
        return r["choices"][0]["message"]["content"].strip()

    if PROVIDER == "anthropic":
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())["content"][0]["text"].strip()

    # OpenAI-compatibel: Groq, OpenRouter, Mistral
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
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"].strip()


def stream(systeem: str, gebruiker: str, max_tokens: int = 700,
           temperatuur: float = 0.2):
    """
    Token-voor-token generatie.

    Dit is geen cosmetica. Op een lokale CPU-runtime van circa 6-7 tokens/sec duurt een
    antwoord van 400 tokens ruim een minuut. Wachten op een compleet antwoord maakt het
    portaal onbruikbaar; meelezen terwijl het opbouwt maakt het werkbaar. De snelheid
    van het model is een gegeven, de beleving ervan is een ontwerpkeuze.
    """
    if PROVIDER == "local":
        if not os.path.exists(MODEL_PATH):
            yield ""
            return
        for chunk in _get_local().create_chat_completion(
                messages=[{"role": "system", "content": systeem},
                          {"role": "user", "content": gebruiker}],
                max_tokens=max_tokens, temperature=temperatuur, stream=True):
            d = chunk["choices"][0].get("delta", {})
            if d.get("content"):
                yield d["content"]
        return

    # Niet-lokale providers: val terug op één keer genereren en in stukjes uitgeven.
    tekst = genereer(systeem, gebruiker, max_tokens, temperatuur)
    for i in range(0, len(tekst), 24):
        yield tekst[i:i + 24]
