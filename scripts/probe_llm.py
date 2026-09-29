#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_llm.py - controleert in een minuut of de taalmodel-runtime doet wat het portaal ervan verwacht.

Draai dit zodra OPENROUTER_API_KEY is gezet (nooit in de chat: als omgevingsvariabele of in .env). Het stuurt
elk model uit de keten dezelfde kleine opdracht (een uitleg die uitsluitend uit meegegeven tekst mag bestaan) en
meldt per model: bereikbaar, tijd tot het eerste teken, totale tijd, hoe het stopte, of het redeneerstappen in
het antwoord lekt, of het Nederlands schrijft en of het zich aan de bron houdt (het mag het verzonnen bedrag niet noemen).

  python3 scripts/probe_llm.py            # alle modellen in de keten
  python3 scripts/probe_llm.py --json     # machineleesbaar
"""
import argparse
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
    antwoord = "".join(tekst).strip()
    woorden = re.findall(r"[a-zà-ÿ]+", antwoord.lower())
    return {"model": model, "ok": bool(antwoord), "eerste_teken_sec": round(eerste, 1) if eerste else None,
            "totaal_sec": round(time.monotonic() - t0, 1), "einde": einde, "tekens": len(antwoord),
            "lekt_redenering": bool(LEK.search(antwoord)),
            "nederlands": bool(woorden) and sum(w in NL for w in woorden) / len(woorden) > 0.12,
            "noemt_20_000": "20.000" in antwoord or "20000" in antwoord,
            "verzint_bedrag_of_artikel": bool(re.search(r"€\s?(?!100\.000|200\.000|40\.000|20\.000)\d|art(?:ikel)?\.?\s*(?!7:958)\d", antwoord)),
            "antwoord": antwoord}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY")
    info = llm.runtime_info()
    if not key:
        print("Geen OPENROUTER_API_KEY in de omgeving of .env; er valt niets te proberen.\n"
              f"Runtime nu: provider={info['provider']} beschikbaar={info['beschikbaar']}. {info['opmerking']}", file=sys.stderr)
        return 2
    res = [probeer(m, key) for m in llm.OPENROUTER_MODELLEN]
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(f"{'model':46s} {'ok':3s} {'eerste':>7s} {'totaal':>7s} {'einde':>7s}  lek  nl  20.000  verzint")
        for r in res:
            if not r["ok"]:
                print(f"{r['model']:46s} NEE  {r.get('fout', 'leeg antwoord')}")
                continue
            print(f"{r['model']:46s} ja  {r['eerste_teken_sec']!s:>7s} {r['totaal_sec']:>7} {r['einde']!s:>7s}  "
                  f"{'ja ' if r['lekt_redenering'] else 'nee'}  {'ja' if r['nederlands'] else 'NEE'}  "
                  f"{'ja' if r['noemt_20_000'] else 'NEE'}     {'JA' if r['verzint_bedrag_of_artikel'] else 'nee'}")
    goed = [r for r in res if r["ok"] and r["nederlands"] and not r["lekt_redenering"] and r["noemt_20_000"] and not r["verzint_bedrag_of_artikel"]]
    print(f"\n{len(goed)} van {len(res)} modellen doen wat het portaal verwacht.", file=sys.stderr)
    return 0 if goed else 1


if __name__ == "__main__":
    sys.exit(main())
