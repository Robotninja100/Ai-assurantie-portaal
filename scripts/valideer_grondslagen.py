#!/usr/bin/env python3
"""
Toetst of elke wetsverwijzing die de rekenkern uitspreekt ECHT in het corpus staat.

Citeer-of-weiger geldt ook voor onze eigen code. Een rekenfunctie die naar een artikel
verwijst dat we niet kunnen tonen, is precies de 'uncitable source' waar de criticus
op schiet - ongeacht of de verwijzing toevallig juist is.

Exitcode 1 als er een verwijzing niet te onderbouwen is.
"""
import json, os, sys, inspect
from datetime import date

HIER = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HIER)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import rekenkern as rk

with open(os.path.join(ROOT, "corpus", "wetgeving.json"), encoding="utf-8") as f:
    CORPUS = json.load(f)
BESCHIKBAAR = {f"{r['wet']}:{r['artikel']}": r for r in CORPUS}

# Representatieve aanroepen; elke tak die een grondslag zet moet hier langskomen.
AANROEPEN = [
    ("evenredigheid onderverzekerd + beredding", lambda: rk.evenredigheidsbeginsel(200000, 250000, 50000, 500, 5000)),
    ("evenredigheid volledig verzekerd",         lambda: rk.evenredigheidsbeginsel(250000, 250000, 50000)),
    ("evenredigheid schade boven som",           lambda: rk.evenredigheidsbeginsel(100000, 100000, 150000)),
    ("verjaring loopt",                          lambda: rk.verjaring_schadeclaim(date(2024, 1, 10), peildatum=date(2026, 9, 29))),
    ("verjaring gestuit zonder reactie",         lambda: rk.verjaring_schadeclaim(date(2024, 1, 10), date(2024, 5, 1), peildatum=date(2026, 9, 29))),
    ("verjaring gestuit met reactie",            lambda: rk.verjaring_schadeclaim(date(2021, 1, 10), date(2021, 6, 1), date(2022, 6, 1), peildatum=date(2026, 9, 29))),
    ("verjaring aansprakelijkheid (lid 3)",      lambda: rk.verjaring_schadeclaim(date(2024, 1, 10), date(2024, 5, 1), aansprakelijkheid=True, peildatum=date(2026, 9, 29))),
    ("verjaring reactie zonder aanspraak",       lambda: rk.verjaring_schadeclaim(date(2021, 1, 10), None, date(2022, 6, 1), peildatum=date(2026, 9, 29))),
    ("provisie onder verbod",                    lambda: rk.provisie_toets("overlijdensrisicoverzekering", 1200, 0, 950)),
    ("provisie schadeverzekering (86d)",         lambda: rk.provisie_toets("opstalverzekering", 600, 15)),
    ("provisie onbepaald",                       lambda: rk.provisie_toets("levensverzekering", 600, 15)),
    ("waarde nieuwwaarde",                       lambda: rk.nieuwwaarde_of_dagwaarde(2000, 2, 10)),
    ("waarde dagwaarde",                         lambda: rk.nieuwwaarde_of_dagwaarde(2000, 8, 10)),
]


def normaliseer(g: str):
    """'BW:7:958:5' -> ('BW:7:958', '5');  'BGfo:86c' -> ('BGfo:86c', None)"""
    d = g.split(":")
    if d[0] == "BW":
        return f"BW:{d[1]}:{d[2]}", (d[3] if len(d) > 3 else None)
    return f"{d[0]}:{d[1]}", (d[2] if len(d) > 2 else None)


def main():
    gezien, fouten = set(), []
    for naam, fn in AANROEPEN:
        u = fn()
        for g in u.grondslag:
            sleutel, lid = normaliseer(g)
            gezien.add(g)
            rec = BESCHIKBAAR.get(sleutel)
            if not rec:
                fouten.append(f"{naam}: '{g}' -> artikel {sleutel} ONTBREEKT in corpus")
                continue
            if lid:
                leden = rec.get("leden") or []
                if not any((l or "").strip().startswith(f"{lid}.") for l in leden):
                    fouten.append(f"{naam}: '{g}' -> art. {sleutel} bestaat, maar lid {lid} "
                                  f"niet aantoonbaar ({len(leden)} leden in bron)")
        if not u.volgende_stap:
            fouten.append(f"{naam}: geen bruikbare vervolgstap (criticus noemt dit fataal)")

    print(f"Corpus: {len(BESCHIKBAAR)} artikelen")
    print(f"Gecontroleerde verwijzingen: {len(gezien)}")
    for g in sorted(gezien):
        s, lid = normaliseer(g)
        r = BESCHIKBAAR.get(s)
        merk = "OK " if r else "MIS"
        ond = (r or {}).get("onderwerp", "-")
        print(f"  [{merk}] {g:16s} {ond}")
    if fouten:
        print("\nNIET ONDERBOUWD:")
        for f in fouten:
            print("  x", f)
        return 1
    print("\nAlle grondslagen onderbouwd door het corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
