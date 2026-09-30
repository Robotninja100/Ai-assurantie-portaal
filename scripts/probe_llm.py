#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_llm.py - controleert in een minuut of de taalmodel-runtime doet wat het portaal ervan verwacht.

Draai dit zodra OPENROUTER_API_KEY is gezet (nooit in de chat: als omgevingsvariabele of in .env). Het stuurt
elk model uit de keten dezelfde kleine opdracht (een uitleg die uitsluitend uit meegegeven tekst mag bestaan) en
meldt per model: bereikbaar, tijd tot het eerste teken, totale tijd, hoe het stopte, of het redeneerstappen of
Engels uitgeeft, of het Nederlands schrijft en of het zich aan de bron houdt (het mag geen bedrag of artikel
noemen dat er niet in staat).

  python3 scripts/probe_llm.py            # de keten van nu (wat OpenRouter nog aanbiedt van de ingestelde modellen)
  python3 scripts/probe_llm.py --live     # alle gratis tekstmodellen die OpenRouter NU aanbiedt, ook nieuwe
  python3 scripts/probe_llm.py --json     # machineleesbaar

Gratis modellen komen en gaan: op 30 september 2026 bleken drie van de vijf modellen uit de eerste keten niet meer
gratis te bestaan. Met --live meet je wat er nu is en krijg je een voorstel voor ASSURANTIE_MODELLEN.

Dit is een rooktest met één korte opdracht, geen kwaliteitsmeting. Een model dat hier slaagt, is nog niet bewezen op
de twaalf functies; dat doet de volledige criticusronde (scripts/criticus_ronde.py volledig).
"""
import argparse
import concurrent.futures
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import llm  # noqa: E402

SYSTEEM = ("Je bent een Nederlandse assurantie-expert. Gebruik UITSLUITEND de bronnen. Noem geen artikel of bedrag dat er niet in staat.\n\n"
           "BRONNEN:\n[BW art. 7:958] Is het verzekerde bedrag lager dan de werkelijke waarde, dan wordt de schade vergoed naar evenredigheid "
           "van het verzekerde bedrag tot de waarde.\n")
GEBRUIKER = ("De berekening is AL UITGEVOERD: verzekerde som EUR 100.000, werkelijke waarde EUR 200.000, schade EUR 40.000, uitkering EUR 20.000. "
             "Leg in twee zinnen uit waarom de uitkering lager is dan de schade en sluit af met een vervolgstap. Reken niets na.")
LEK = re.compile(r"(we need to|let'?s|the user|okay,? so|i need to|<think>|<\/think>)", re.I)
NL = set("de het een en van is dat op voor met niet die zijn wordt bij als naar uit".split())

# Modellen die geen gewone tekstgenerator zijn of al eens gemeten en afgewezen zijn (state.json -> afgewezen_modellen).
# Met --live worden ze toch niet overgeslagen wanneer je --ook-afgewezen meegeeft: een andere sleutel kan een ander
# resultaat geven (de HTTP 403 van de google/gemma-4-modellen hing mogelijk aan de privacy-instellingen van dat account).
NIET_GESCHIKT = re.compile(r"content-safety|guard|embed|rerank|lyria|-code|coder")
EERDER_AFGEWEZEN = re.compile(r"gemma-4|inkling|laguna|nemotron-3\.5-lightning|dots-3-note|lfm-2\.5")


def probeer(model, key):
    t0 = time.monotonic()
    eerste = einde = None
    tekst = []
    try:
        for onderdeel in llm._openrouter_stukken(model, SYSTEEM, GEBRUIKER, 220, 0.2, key):
            if "tekst" in onderdeel:
                if eerste is None:
                    eerste = time.monotonic() - t0
                tekst.append(onderdeel["tekst"])
            if "einde" in onderdeel:
                einde = onderdeel["einde"]
    except Exception as e:  # noqa: BLE001
        return {"model": model, "ok": False, "fout": f"{type(e).__name__}: {e}"[:200]}
    antwoord = re.sub(r"<think>.*?</think>", "", "".join(tekst), flags=re.S).strip()
    woorden = re.findall(r"[a-zà-ÿ]+", antwoord.lower())
    return {"model": model, "ok": bool(antwoord), "eerste_teken_sec": round(eerste, 1) if eerste else None,
            "totaal_sec": round(time.monotonic() - t0, 1), "einde": einde, "tekens": len(antwoord),
            "lekt_redenering": bool(LEK.search(antwoord)) or bool(llm._kop_afgekeurd(antwoord[:200])),
            "nederlands": bool(woorden) and sum(w in NL for w in woorden) / len(woorden) > 0.12,
            "noemt_20_000": "20.000" in antwoord or "20000" in antwoord,
            "verzint_bedrag_of_artikel": bool(re.search(r"€\s?(?!100\.000|200\.000|40\.000|20\.000)\d|art(?:ikel)?\.?\s*(?!7:958)\d", antwoord)),
            "antwoord": antwoord}


def geslaagd(r):
    return (r["ok"] and r["einde"] in ("stop", "end_turn", None) and not r["lekt_redenering"] and r["nederlands"]
            and r["noemt_20_000"] and not r["verzint_bedrag_of_artikel"])


def kies_kandidaten(data, ook_afgewezen=False):
    """Uit de modellenlijst van OpenRouter: gratis, tekst als uitvoer, ruim genoeg context, geen bekende afwijzer."""
    uit = []
    for m in data:
        i = m.get("id", "")
        if not i.endswith(":free") or NIET_GESCHIKT.search(i):
            continue
        if "text" not in ((m.get("architecture") or {}).get("output_modalities") or ["text"]):
            continue
        if (m.get("context_length") or 0) < 16000:
            continue
        if EERDER_AFGEWEZEN.search(i) and not ook_afgewezen:
            continue
        uit.append(i)
    return uit


def kandidaten_live(ook_afgewezen):
    """Alle gratis tekstmodellen die OpenRouter nu aanbiedt, uit de openbare lijst (geen sleutel nodig)."""
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(llm._modellen_url(), headers={"accept": "application/json"}), timeout=20) as r:
        return kies_kandidaten(json.loads(r.read().decode("utf-8", "replace"))["data"], ook_afgewezen)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--live", action="store_true", help="alle gratis tekstmodellen van nu, niet alleen de ingestelde keten")
    ap.add_argument("--ook-afgewezen", action="store_true", help="met --live: ook de modellen die eerder zijn afgewezen")
    ap.add_argument("--parallel", type=int, default=3, help="zoveel modellen tegelijk (gratis modellen hebben een verzoeklimiet)")
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY")
    info = llm.runtime_info()
    if not key:
        print("Geen OPENROUTER_API_KEY in de omgeving of .env; er valt niets te proberen.\n"
              f"Runtime nu: provider={info['provider']} beschikbaar={info['beschikbaar']}. {info['opmerking']}", file=sys.stderr)
        return 2
    modellen = kandidaten_live(a.ook_afgewezen) if a.live else llm.modelketen()["modellen"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.parallel)) as pool:
        res = list(pool.map(lambda m: probeer(m, key), modellen))
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(f"{'model':46s} {'ok':3s} {'eerste':>7s} {'totaal':>7s} {'einde':>7s}  lek  nl  20.000  verzint  geslaagd")
        for r in res:
            if not r["ok"]:
                print(f"{r['model']:46s} NEE  {r.get('fout', 'leeg antwoord')}")
                continue
            print(f"{r['model']:46s} ja  {r['eerste_teken_sec']!s:>7s} {r['totaal_sec']:>7} {r['einde']!s:>7s}  "
                  f"{'ja ' if r['lekt_redenering'] else 'nee'}  {'ja' if r['nederlands'] else 'NEE'}  "
                  f"{'ja' if r['noemt_20_000'] else 'NEE'}     {'JA' if r['verzint_bedrag_of_artikel'] else 'nee'}      "
                  f"{'ja' if geslaagd(r) else 'NEE'}")
    goed = sorted((r for r in res if geslaagd(r)), key=lambda r: r["eerste_teken_sec"] or 1e9)
    if goed:
        print("\nGeslaagd op de rooktest, snelste eerst. Een voorstel om te proberen (het meet geen kwaliteit op de twaalf functies):")
        print("ASSURANTIE_MODELLEN=" + ",".join(r["model"] for r in goed))
    else:
        print("\nGeen enkel model slaagde op de rooktest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
