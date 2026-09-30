#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
criticus_telling.py - telt de oordelen van de onafhankelijke beoordelaars van een criticusronde, en zet twee rondes
naast elkaar.

Een beoordelaar geeft per casus vier oordelen (verzonnen feit, niet-citeerbare bron, foute verzekeringslogica, geen
bruikbare vervolgstap) elk 'geen', 'mogelijk' of 'ja', plus een oordeel over de citeercontrole van het portaal
(terecht, vals alarm, gemist). Dit script telt ze. Het beoordeelt niets zelf.

Gebruik:
  python3 scripts/criticus_telling.py criticus/ronde2/beoordeling
  python3 scripts/criticus_telling.py criticus/ronde1/beoordeling criticus/ronde2/beoordeling   # vergelijk
  ... --markdown        # tabel voor in een README
  ... --json uit.json

Lees de vergelijking met terughoudendheid: het zijn andere beoordelaars, andere antwoorden en andere code. Een daling
is geen bewijs, alleen een aanwijzing; en 'geen' betekent niet dat er niets was, alleen dat een beoordelaar niets vond.
"""
import argparse
import collections
import glob
import json
import os
import sys

FOUTEN = ("verzonnen_feit", "niet_citeerbare_bron", "foute_verzekeringslogica", "geen_bruikbare_vervolgstap")
OORDELEN = ("geen", "mogelijk", "ja", "n.v.t.")
BEWAKER = ("terecht", "vals_alarm", "gemist", "n.v.t.")


def lees(map_):
    """{functie: [beoordeling per casus]}; een ontbrekend of onleesbaar bestand is een fout, geen stille nul."""
    uit = {}
    for pad in sorted(glob.glob(os.path.join(map_, "*.json"))):
        naam = os.path.basename(pad)[:-5]
        try:
            with open(pad, encoding="utf-8") as fh:
                data = json.load(fh)
        except ValueError as e:
            raise SystemExit(f"{pad} is geen geldige JSON: {e}")
        if not isinstance(data, list):
            raise SystemExit(f"{pad}: verwacht een lijst met één object per casus")
        for r in data:
            for f in FOUTEN:
                o = (r.get(f) or {}).get("oordeel")
                if o not in OORDELEN:
                    raise SystemExit(f"{pad}: {r.get('id')}: oordeel '{o}' bij {f} is geen van {OORDELEN}")
            if r.get("bewaker") not in BEWAKER:
                raise SystemExit(f"{pad}: {r.get('id')}: bewaker '{r.get('bewaker')}' is geen van {BEWAKER}")
        uit[naam] = data
    if not uit:
        raise SystemExit(f"geen beoordelingen in {map_}")
    return uit


def tel(rondes):
    totaal = collections.Counter()
    per_fout = {f: collections.Counter() for f in FOUTEN}
    bewaker = collections.Counter()
    per_functie = {}
    casussen = 0
    for functie, lijst in rondes.items():
        ja = mogelijk = 0
        for r in lijst:
            casussen += 1
            for f in FOUTEN:
                o = r[f]["oordeel"]
                per_fout[f][o] += 1
                ja += o == "ja"
                mogelijk += o == "mogelijk"
            bewaker[r["bewaker"]] += 1
        per_functie[functie] = {"casussen": len(lijst), "ja": ja, "mogelijk": mogelijk}
    totaal["ja"] = sum(v["ja"] for v in per_functie.values())
    totaal["mogelijk"] = sum(v["mogelijk"] for v in per_functie.values())
    return {"casussen": casussen, "ja": totaal["ja"], "mogelijk": totaal["mogelijk"],
            "per_fout": {f: dict(c) for f, c in per_fout.items()}, "bewaker": dict(bewaker), "per_functie": per_functie}


def tekst(naam, t):
    r = [f"{naam}: {t['casussen']} casussen; {t['ja']} keer 'ja' en {t['mogelijk']} keer 'mogelijk' (4 oordelen per casus)"]
    for f in FOUTEN:
        c = t["per_fout"][f]
        r.append(f"  {f:28s} " + "  ".join(f"{o}={c.get(o, 0)}" for o in OORDELEN))
    r.append("  bewaker                      " + "  ".join(f"{o}={t['bewaker'].get(o, 0)}" for o in BEWAKER))
    return "\n".join(r)


def markdown(namen, tellingen):
    r = ["| | " + " | ".join(namen) + " |", "|---|" + "---|" * len(namen)]
    r.append("| casussen | " + " | ".join(str(t["casussen"]) for t in tellingen) + " |")
    r.append("| oordeel 'ja' (alle vier de fouten) | " + " | ".join(str(t["ja"]) for t in tellingen) + " |")
    r.append("| oordeel 'mogelijk' | " + " | ".join(str(t["mogelijk"]) for t in tellingen) + " |")
    for f in FOUTEN:
        r.append(f"| {f.replace('_', ' ')}: ja / mogelijk | "
                 + " | ".join(f"{t['per_fout'][f].get('ja', 0)} / {t['per_fout'][f].get('mogelijk', 0)}" for t in tellingen) + " |")
    for b in ("terecht", "vals_alarm", "gemist"):
        r.append(f"| bewaker {b.replace('_', ' ')} | " + " | ".join(str(t["bewaker"].get(b, 0)) for t in tellingen) + " |")
    functies = sorted(set().union(*[set(t["per_functie"]) for t in tellingen]))
    r += ["", "| functie (ja / mogelijk) | " + " | ".join(namen) + " |", "|---|" + "---|" * len(namen)]
    for fn in functies:
        cellen = []
        for t in tellingen:
            v = t["per_functie"].get(fn)
            cellen.append(f"{v['ja']} / {v['mogelijk']}" if v else "-")
        r.append(f"| {fn} | " + " | ".join(cellen) + " |")
    return "\n".join(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mappen", nargs="+", help="map(pen) met <functie>.json-beoordelingen; meerdere = vergelijken")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    namen = [os.path.basename(os.path.dirname(os.path.abspath(m.rstrip("/")))) or m for m in a.mappen]
    tellingen = [tel(lees(m)) for m in a.mappen]
    if a.markdown:
        print(markdown(namen, tellingen))
    else:
        for n, t in zip(namen, tellingen):
            print(tekst(n, t))
            print("  per functie (ja/mogelijk): " + ", ".join(f"{f} {v['ja']}/{v['mogelijk']}" for f, v in sorted(t["per_functie"].items())))
            print()
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(dict(zip(namen, tellingen)), fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
