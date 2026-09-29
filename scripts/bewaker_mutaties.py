#!/usr/bin/env python3
"""
Mutatietest van de citeerbewaker: hoeveel bewust ingebouwde fouten ziet hij?

De criticusronde meet of de bewaker terecht alarm slaat op wat een model schreef. Dat zegt weinig over wat hij MIST: een
sterk model maakt weinig fouten, en wie niets vindt heeft niet bewezen dat er niets te vinden was. Deze test bouwt de
fouten zelf in. Elk echt antwoord (bijvoorbeeld van de stand-in-laag) krijgt, één tegelijk, een verzonnen artikel, een
verzonnen uitspraak, een artikel bij de verkeerde wet, een verzonnen bedrag, percentage, datum, citaat of ECLI, een
gewijzigd bedrag of een lid dat niet bestaat. Daarna telt het aantal keer dat de bewaker DAT punt aanwijst (niet een
alarm dat er al stond).

Er is ook een controlemutatie zonder fout: een zin die een al gefundeerde verwijzing herhaalt. Die mag niet
alarmeren; dat meet de valse alarmen.

Gebruik (draai het in een werkboom van de commit waarvan de opdrachten zijn, als de opdrachten sindsdien zijn veranderd):
    python3 scripts/bewaker_mutaties.py --antwoorden /pad/naar/prompts/antwoorden [--json uitvoer.json]

Wat dit NIET meet: of het ontdekte punt in de tekst zichtbaar wordt gemarkeerd (dat doet `grounding.maskeer`, getest in
tests/test_bewaker_review.py), en fouten in de redenering die geen verwijzing, getal of citaat zijn. Die ziet de bewaker
niet; daarvoor zijn de onafhankelijke beoordelaars.
"""
import argparse
import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import api          # noqa: E402
import features     # noqa: E402
import criticus_ronde as cr   # noqa: E402

WET_WISSEL = {"BW": "Wft", "Wft": "BW", "BGfo": "BW"}
RE_WET = re.compile(r"(?P<pre>art(?:ikel|\.)?\s*)(?P<nr>\d+:\d+[a-z]?|\d+[a-z]?)(?P<lid>(?:\s+lid\s+\d+)?)(?P<mid>\s+(?:van\s+(?:het|de)\s+)?)(?P<wet>BW|Wft|BGfo)\b")


def _controle(opdracht, tekst):
    return api.beoordeel_antwoord(opdracht, tekst, "stop")[0]


def _aangewezen(opdracht, tekst, marker):
    """Wijst de bewaker juist dit punt aan? Vergelijking zonder spaties en hoofdletters."""
    n = lambda x: re.sub(r"\s+", "", x).lower()
    c = _controle(opdracht, tekst)
    return any(n(marker) in n(x["verwijzing"]) or n(x["verwijzing"]) in n(marker) for x in c["ongefundeerd"])


def _achter(tekst, zin):
    return tekst.rstrip() + "\n\n" + zin


def maak_mutaties(opdracht, antwoord, controle):
    """Yield (naam, nieuw_antwoord, marker) voor elke mutatie die op dit antwoord van toepassing is."""
    yield "wetsartikel_verzonnen", _achter(antwoord, "Zie ook art. 7:999 BW."), "7:999"
    yield "wft_artikel_verzonnen", _achter(antwoord, "Zie ook art. 4:999 Wft."), "4:999"
    yield "bgfo_artikel_verzonnen", _achter(antwoord, "Zie ook art. 86z BGfo."), "86z"
    yield "kifid_verzonnen", _achter(antwoord, "Vergelijk Kifid 2026-9999."), "2026-9999"
    opgehaald = {d.get("uitspraaknummer") for d in opdracht["opgehaald"].get("kifid", [])}
    ander = next((d["uitspraaknummer"] for d in features.CORPUS.data["kifid"] if d["uitspraaknummer"] not in opgehaald), None)
    if ander:
        yield "kifid_bestaat_maar_niet_opgehaald", _achter(antwoord, f"Vergelijk Kifid {ander}."), ander
    yield "polisclausule_verzonnen", _achter(antwoord, "Zie ook art. 9.99.9 sub z van de polisvoorwaarden."), "9.99.9"
    yield "ecli_verzonnen", _achter(antwoord, "Zie ECLI:NL:HR:2019:1234."), "ECLI:NL:HR:2019:1234"
    yield "bedrag_verzonnen", _achter(antwoord, "De vergoeding bedraagt € 12.345,67."), "12.345,67"
    yield "percentage_verzonnen", _achter(antwoord, "Het percentage is 37,5%."), "37,5%"
    yield "datum_verzonnen", _achter(antwoord, "Dit moet uiterlijk op 12 maart 2031 gebeuren."), "12 maart 2031"
    yield "citaat_verzonnen", _achter(antwoord, 'De polis zegt: "de verzekeraar vergoedt altijd de volledige schade zonder eigen risico".'), \
        "de verzekeraar vergoedt altijd de volledige schade zonder eigen risico"

    # De volgende mutaties passen een bestaand, gefundeerd punt aan.
    m = RE_WET.search(antwoord)
    while m:
        nr, wet = m.group("nr"), m.group("wet")
        if any(g["soort"] == "wetsartikel" and nr in g["verwijzing"] for g in controle["gefundeerd"]):
            nieuw = antwoord[:m.start("wet")] + WET_WISSEL[wet] + antwoord[m.end("wet"):]
            yield "wet_verwisseld", nieuw, nr
            break
        m = RE_WET.search(antwoord, m.end())
    m = re.search(r"art(?:ikel|\.)?\s*(\d+:\d+[a-z]?)\s+lid\s+(\d+)", antwoord)
    if m and any(m.group(1) in g["verwijzing"] for g in controle["gefundeerd"]):
        yield "lid_bestaat_niet", antwoord[:m.start(2)] + "99" + antwoord[m.end(2):], f"{m.group(1)} lid 99"
    for g in controle["gefundeerd"]:
        if g["soort"] == "bedrag":
            oud = antwoord[g["positie"]:g["einde"]]
            nieuw_bedrag = "€ 98.765,43"
            yield "bedrag_gewijzigd", antwoord[:g["positie"]] + nieuw_bedrag + antwoord[g["einde"]:], nieuw_bedrag
            break
    # Controle zonder fout: een al gefundeerde verwijzing herhalen mag niet alarmeren.
    for g in controle["gefundeerd"]:
        if g["soort"] in ("wetsartikel", "polisclausule"):
            yield "CONTROLE_herhaalde_gefundeerde_verwijzing", _achter(antwoord, f"Zie ook {antwoord[g['positie']:g['einde']]}."), None
            break


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--antwoorden", required=True, help="map met <casus-id>.txt")
    ap.add_argument("--json", help="schrijf het resultaat naar dit bestand")
    a = ap.parse_args()

    casussen, _ = cr.laad_casussen()
    telling = collections.defaultdict(lambda: [0, 0])          # naam -> [toepasbaar, ontdekt]
    gemist = collections.defaultdict(list)
    valse = []
    for c in casussen:
        pad = os.path.join(a.antwoorden, c["id"] + ".txt")
        if not os.path.exists(pad):
            continue
        try:
            opdracht = features.FUNCTIES[c["functie"]]["fn"](**c["invoer"])
        except (TypeError, ValueError, ArithmeticError):
            continue
        antwoord = open(pad, encoding="utf-8").read().strip()
        controle = _controle(opdracht, antwoord)
        for naam, nieuw, marker in maak_mutaties(opdracht, antwoord, controle):
            if naam.startswith("CONTROLE"):
                telling[naam][0] += 1
                if any(x["verwijzing"] in nieuw[len(antwoord):] for x in _controle(opdracht, nieuw)["ongefundeerd"]
                       if x["verwijzing"] not in [y["verwijzing"] for y in controle["ongefundeerd"]]):
                    telling[naam][1] += 1
                    valse.append(c["id"])
                continue
            telling[naam][0] += 1
            if _aangewezen(opdracht, nieuw, marker):
                telling[naam][1] += 1
            else:
                gemist[naam].append(c["id"])

    print(f"{'mutatie':44s} {'toepasbaar':>10s} {'ontdekt':>8s}  {'ontdekt %':>9s}")
    uit = {}
    for naam in sorted(telling):
        n, o = telling[naam]
        if naam.startswith("CONTROLE"):
            print(f"{naam:44s} {n:10d} {o:8d}  (valse alarmen; moet 0 zijn)")
        else:
            print(f"{naam:44s} {n:10d} {o:8d}  {100 * o / n if n else 0:8.1f}%")
        uit[naam] = {"toepasbaar": n, "ontdekt": o, "gemist_in": gemist.get(naam, [])[:12]}
    for naam, ids in gemist.items():
        print(f"\nGEMIST {naam}: {', '.join(ids[:12])}{' ...' if len(ids) > 12 else ''}")
    if valse:
        print(f"\nVALSE ALARMEN: {', '.join(valse[:12])}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(uit, fh, ensure_ascii=False, indent=1)
    gemist_totaal = sum(len(v) for v in gemist.values())
    return 1 if (gemist_totaal or valse) else 0


if __name__ == "__main__":
    sys.exit(main())
