#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
criticus_ronde.py - laat de rommelige casussen (tests/casussen/*.json) door het portaal lopen en legt
vast wat eruit komt. Beoordelen doet een ander: een onafhankelijke beoordelaar die de vier fatale
fouten toetst (verzonnen feit, niet-citeerbare bron, foute verzekeringslogica, geen vervolgstap).

Twee lagen, want ze bewijzen iets anders:

  deterministisch  in dit proces, zonder taalmodel. Toetst bronnen, berekening en de harde checks uit
                   de casus. Exact en snel; hier vallen rekenfouten en verkeerde classificaties uit.
  volledig         via de HTTP-API van een draaiende server, MET taalmodel. Legt antwoord, controle
                   van verwijzingen, gebruikt model en tijden vast voor de beoordelaar.

  standin          PLAFONDPROEF: dezelfde opdrachten als de API geeft, maar het antwoord komt uit bestanden die een
                   sterk stand-in-model schreef (zie scripts/criticus_prompts.py), en gaat door dezelfde citeercontrole.
                   Zegt hoe goed bronnen, opdrachten en bewaker zijn als het model goed is; niets over de gratis
                   OpenRouter-modellen. Het dossier vermeldt dat de schrijver een stand-in was.

Gebruik:
  python3 scripts/criticus_ronde.py deterministisch
  python3 scripts/criticus_ronde.py volledig --basis http://127.0.0.1:8000 [--functie X] [--max 3]
  python3 scripts/criticus_ronde.py standin --antwoorden /pad/naar/prompts/antwoorden
  python3 scripts/criticus_ronde.py dossier [--laag standin]   # schrijft per functie een leesbaar beoordelingsdossier

De uitvoer staat in criticus/<ronde>/. Exitcode 1 als een harde check faalt (deterministisch) of als er
casussen ontbreken; 0 alleen als alles klopt.
"""
import argparse
import glob
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

TWAALF = ["dekkingscheck", "precedentzoeker", "schadeberekening", "verjaringstoets", "provisietoets",
          "dossiercheck", "polisvergelijker", "klachtroute", "afwijzingsanalyse", "adviesnotitie",
          "waardetoets", "begripsuitleg"]


def laad_casussen(functie=None):
    uit, ontbreekt = [], []
    for f in TWAALF:
        if functie and f != functie:
            continue
        pad = os.path.join(ROOT, "tests", "casussen", f"{f}.json")
        if not os.path.exists(pad):
            ontbreekt.append(f)
            continue
        with open(pad, encoding="utf-8") as fh:
            cs = json.load(fh)
        if len(cs) != 10 and not functie:
            print(f"LET OP: {f}.json heeft {len(cs)} casussen in plaats van 10", file=sys.stderr)
        uit.extend(cs)
    return uit, ontbreekt


# ------------------------------------------------------------------ harde checks

def pad_lees(obj, pad):
    """'details.status' -> obj['details']['status']; ontbrekend geeft een sentinel."""
    huidig = obj
    for deel in pad.split("."):
        if isinstance(huidig, dict) and deel in huidig:
            huidig = huidig[deel]
        else:
            return _ONTBREEKT
    return huidig


_ONTBREEKT = object()


def norm(x):
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, (int, float)):
        return f"{x:.2f}"
    return str(x).strip()


def is_geweigerd(res):
    """Weigert het portaal (nog voor het taalmodel): ongeldige invoer, geen bronnen of een onbepaalde toets?"""
    if res.get("http_status") == 400:
        return True
    if not res.get("bronnen"):
        return True
    ber = res.get("berekening") or {}
    status = (ber.get("details") or {}).get("status")
    if status in ("ONBEPAALD", "ONZEKER"):
        return True
    # Bij deze functies IS het bedrag de uitkomst; zonder bedrag heeft de rekenkern geweigerd. (Bij de
    # verjaringstoets is er nooit een bedrag, daar zegt alleen de status iets.)
    return res.get("functie") in ("schadeberekening", "waardetoets") and bool(ber) and ber.get("bedrag") is None


def toets_harde_checks(casus, res, laag):
    """Geeft een lijst (check, verwacht, gekregen, ok, opmerking)."""
    uit = []
    checks = (casus.get("verwachting") or {}).get("harde_checks") or {}
    for sleutel, verwacht in checks.items():
        if sleutel == "http_status":
            gekregen = res.get("http_status", 200)
            uit.append((sleutel, verwacht, gekregen, gekregen == verwacht, ""))
        elif sleutel == "geweigerd":
            gekregen = is_geweigerd(res)
            if verwacht is True and not res.get("berekening") and res.get("http_status") != 400 and res.get("bronnen"):
                uit.append((sleutel, True, "n.v.t.", None,
                            "weigering van een tekstfunctie blijkt pas uit het antwoord; dat beoordeelt de criticus"))
            else:
                uit.append((sleutel, verwacht, gekregen, gekregen == verwacht, ""))
        else:
            if res.get("http_status") == 400:
                uit.append((sleutel, verwacht, "(400)", False, "de functie weigerde de invoer, verwacht was een uitkomst"))
                continue
            gekregen = pad_lees(res.get("berekening") or {}, sleutel)
            if gekregen is _ONTBREEKT:
                uit.append((sleutel, verwacht, "(ontbreekt)", False, "veld niet in de berekening"))
            else:
                uit.append((sleutel, verwacht, gekregen, norm(gekregen) == norm(verwacht), ""))
    return uit


# ------------------------------------------------------------------ laag 1: deterministisch

def bronnen_kort(bronnen):
    return [{"soort": b["soort"], "label": b["label"], "type": b.get("type"), "kant": b.get("kant"),
             "uitkomst": b.get("uitkomst")} for b in bronnen]


def draai_deterministisch(casus):
    import features
    spec = features.FUNCTIES[casus["functie"]]
    res = {"id": casus["id"], "functie": casus["functie"], "http_status": 200}
    t0 = time.time()
    try:
        opdracht = spec["fn"](**casus["invoer"])
    except (TypeError, ValueError, ArithmeticError) as e:
        res.update(http_status=400, fout=f"{type(e).__name__}: {e}", bronnen=[], berekening=None)
        return res
    res.update(bronnen=bronnen_kort(opdracht["bronnen"]), berekening=opdracht.get("berekening"),
               duur_sec=round(time.time() - t0, 3))
    return res


# ------------------------------------------------------------------ laag 2: volledig via HTTP

_CODE_HASH = None


def versie_sleutel(casus):
    """
    Identificeert 'deze casus tegen deze code en dit corpus'. Een tussenstand van vóór een codewijziging
    mag niet worden hergebruikt: die zou een uitkomst van oude code als die van de nieuwe presenteren.
    """
    global _CODE_HASH
    if _CODE_HASH is None:
        h = hashlib.sha256()
        for pad in sorted(glob.glob(os.path.join(ROOT, "backend", "*.py")) + glob.glob(os.path.join(ROOT, "corpus", "*.json"))):
            with open(pad, "rb") as fh:
                h.update(fh.read())
        _CODE_HASH = h.hexdigest()
    h = hashlib.sha256(_CODE_HASH.encode())
    h.update(json.dumps(casus, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()[:16]


def is_bruikbaar(r):
    """Een run telt alleen als de server antwoordde (200, of 400 voor een bewust geweigerde invoer) en de stroom af was."""
    return r.get("http_status") in (200, 400) and not r.get("onvolledig")

def draai_volledig(casus, basis, timeout):
    res = {"id": casus["id"], "functie": casus["functie"], "http_status": 200, "tekst": "", "gebeurtenissen": []}
    body = json.dumps({"functie": casus["functie"], "invoer": casus["invoer"]}).encode()
    req = urllib.request.Request(basis.rstrip("/") + "/api/vraag", data=body,
                                 headers={"content-type": "application/json"})
    t0 = time.time()
    klaar = False
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for ruw in r:
                regel = ruw.decode("utf-8", "replace").strip()
                if not regel.startswith("data:"):
                    continue
                data = regel[5:].strip()
                if data == "[DONE]":
                    klaar = True
                    break
                e = json.loads(data)
                t = e.get("type")
                if t == "bronnen":
                    res["bronnen_volledig"] = e["bronnen"]
                    res["bronnen"] = bronnen_kort(e["bronnen"])
                elif t == "berekening":
                    res["berekening"] = e["berekening"]
                elif t == "tekst":
                    res["tekst"] += e["tekst"]
                elif t == "model":
                    res["model"] = {k: e.get(k) for k in ("model", "provider", "overgeslagen")}
                elif t == "controle":
                    res["controle"] = e["controle"]
                elif t == "gemaskeerd":
                    res["gemaskeerd"] = e["tekst"]
                elif t == "weigering":
                    res["weigering"] = e["tekst"]
                elif t == "fout":
                    res["fout"] = e
                # 'wacht' is alleen hartslag
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail")
        except Exception:  # noqa: BLE001
            detail = str(e)
        res.update(http_status=e.code, fout=detail, bronnen=[], berekening=None)
    except Exception as e:  # noqa: BLE001
        res.update(http_status=0, fout=f"{type(e).__name__}: {e}")
    else:
        if not klaar:
            res["onvolledig"] = True                      # de stroom hield op zonder [DONE]
    res["duur_sec"] = round(time.time() - t0, 1)
    res.setdefault("bronnen", [])
    res.setdefault("berekening", None)
    return res


# ------------------------------------------------------------------ laag 3: stand-in (plafondproef)

def draai_standin(casus, antwoorden):
    import api
    import features
    res = {"id": casus["id"], "functie": casus["functie"], "http_status": 200, "tekst": "", "gebeurtenissen": []}
    bewaard = os.path.join(antwoorden, os.pardir, "opdrachten", casus["id"] + ".json")
    if os.path.exists(bewaard):                 # precies wat het stand-in-model zag, ook als de code intussen veranderde
        with open(bewaard, encoding="utf-8") as fh:
            opdracht = json.load(fh)
    else:
        try:
            opdracht = features.FUNCTIES[casus["functie"]]["fn"](**casus["invoer"])
        except (TypeError, ValueError, ArithmeticError) as e:
            res.update(http_status=400, fout=f"{type(e).__name__}: {e}", bronnen=[], berekening=None)
            return res
    res.update(bronnen_volledig=opdracht["bronnen"], bronnen=bronnen_kort(opdracht["bronnen"]),
               berekening=opdracht.get("berekening"), opmerkingen=opdracht.get("opmerkingen"))
    if not opdracht["bronnen"]:
        res.update(weigering="Er zijn geen bronnen gevonden die deze vraag kunnen onderbouwen. Het portaal geeft daarom geen "
                             "inhoudelijk antwoord.",
                   controle={"oordeel": "GEWEIGERD_GEEN_BRONNEN", "gefundeerd": [], "ongefundeerd": []})
        return res
    pad = os.path.join(antwoorden, casus["id"] + ".txt")
    if not os.path.exists(pad):
        res.update(onvolledig=True, fout="het stand-in-model schreef geen antwoord voor deze casus")
        return res
    antwoord = open(pad, encoding="utf-8").read().strip()
    controle, gemaskeerd = api.beoordeel_antwoord(opdracht, antwoord, "stop", None, None)
    res.update(tekst=antwoord, controle=controle, model={"model": "stand-in (plafondproef, sterk model)", "provider": "standin",
                                                         "overgeslagen": None})
    if gemaskeerd is not None:
        res["gemaskeerd"] = gemaskeerd
    return res


# ------------------------------------------------------------------ dossier voor de beoordelaar

def dossier(functie, casussen, resultaten):
    regels = [f"# Beoordelingsdossier: {functie}", "",
              "Toets elke casus op vier fatale fouten: (1) VERZONNEN FEIT: een bewering die niet uit de getoonde bronnen of "
              "de berekening volgt; (2) NIET-CITEERBARE BRON: een verwijzing die niet in de bronnen staat of niet klopt; "
              "(3) FOUTE VERZEKERINGSLOGICA: juridisch of rekenkundig onjuist (controleer tegen de wettekst in corpus/wetgeving.json); "
              "(4) GEEN BRUIKBARE VERVOLGSTAP. Weigeren wanneer de bronnen ontbreken is GOED gedrag, geen fout.", ""]
    for c in casussen:
        r = resultaten.get(c["id"], {})
        regels += [f"## {c['id']}: {c['titel']}", "",
                   f"Rommeligheid: {', '.join(c.get('rommeligheid', []))}", "",
                   "**Invoer**", "```json", json.dumps(c["invoer"], ensure_ascii=False, indent=1), "```", "",
                   "**Verwachting van de casusschrijver**",
                   *[f"- MOET: {x}" for x in c["verwachting"].get("moet", [])],
                   *[f"- MAG NIET: {x}" for x in c["verwachting"].get("mag_niet", [])],
                   f"- Bron van waarheid: {c.get('bron_van_waarheid', '')}", ""]
        if r.get("http_status") == 400:
            regels += [f"**Uitkomst: HTTP 400 (invoer geweigerd)**: {r.get('fout')}", ""]
            continue
        for opm in r.get("opmerkingen") or []:
            regels += [f"**Melding van het portaal aan de adviseur**: {opm}", ""]
        regels.append("**Getoonde bronnen**")
        for b in r.get("bronnen_volledig") or []:
            regels.append(f"- [{b['soort']}] {b['label']}" + (f" ({b.get('type') or b.get('uitkomst') or ''})" if (b.get('type') or b.get('uitkomst')) else "")
                          + f": {(b.get('fragment') or '')[:260].replace(chr(10), ' ')}")
        if not r.get("bronnen_volledig") and not r.get("bronnen"):
            regels.append("- (geen bronnen opgehaald)")
        regels.append("")
        if r.get("berekening"):
            regels += ["**Berekening (uit code)**", "```json", json.dumps(r["berekening"], ensure_ascii=False, indent=1)[:2600], "```", ""]
        if "tekst" in r:
            regels += [f"**Antwoord van het taalmodel** (model: {(r.get('model') or {}).get('model', 'onbekend')})", "",
                       "> " + (r.get("tekst") or r.get("weigering") or "(geen antwoord)").replace("\n", "\n> "), ""]
            if r.get("controle"):
                c_ = r["controle"]
                regels += [f"**Citeercontrole van het portaal**: {c_['oordeel']}; niet in de bronnen: "
                           f"{[x['verwijzing'] for x in c_['ongefundeerd']] or 'geen'}", ""]
            if r.get("fout"):
                regels += [f"**Fout**: {r['fout'] if isinstance(r['fout'], str) else r['fout'].get('fout')}", ""]
        regels += ["**Harde checks**"]
        for sleutel, verwacht, gekregen, ok, opm in toets_harde_checks(c, r, "volledig"):
            regels.append(f"- {sleutel}: verwacht {verwacht!r}, gekregen {gekregen!r} -> " +
                          ("OK" if ok else "NIET TOETSBAAR" if ok is None else "FOUT") + (f" ({opm})" if opm else ""))
        regels += ["", "---", ""]
    return "\n".join(regels)


# ------------------------------------------------------------------ hoofdprogramma

def samenvatting(casussen, resultaten, laag):
    per = {}
    fouten = []
    for c in casussen:
        r = resultaten.get(c["id"])
        p = per.setdefault(c["functie"], {"casussen": 0, "checks_ok": 0, "checks_fout": 0, "niet_toetsbaar": 0})
        p["casussen"] += 1
        if r is None:
            continue
        for sleutel, verwacht, gekregen, ok, opm in toets_harde_checks(c, r, laag):
            if ok is None:
                p["niet_toetsbaar"] += 1
            elif ok:
                p["checks_ok"] += 1
            else:
                p["checks_fout"] += 1
                fouten.append((c["id"], sleutel, verwacht, gekregen, opm))
    print(f"\n{'functie':20s} {'casussen':>8s} {'checks ok':>10s} {'fout':>6s} {'n.v.t.':>7s}")
    for f, p in per.items():
        print(f"{f:20s} {p['casussen']:8d} {p['checks_ok']:10d} {p['checks_fout']:6d} {p['niet_toetsbaar']:7d}")
    if fouten:
        print(f"\n{len(fouten)} HARDE CHECK(S) GEFAALD:")
        for cid, sleutel, verwacht, gekregen, opm in fouten:
            print(f"  {cid}: {sleutel}: verwacht {verwacht!r}, gekregen {gekregen!r}" + (f"  [{opm}]" if opm else ""))
    return fouten


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("laag", choices=["deterministisch", "volledig", "standin", "dossier"])
    ap.add_argument("--antwoorden", help="standin: map met <id>.txt-antwoorden van het stand-in-model")
    ap.add_argument("--laag-dossier", "--laag", dest="dossier_laag", choices=["auto", "deterministisch", "volledig", "standin"],
                    default="auto", help="dossier: uit welke laag; standaard de beste beschikbare")
    ap.add_argument("--ronde", default="ronde1")
    ap.add_argument("--functie")
    ap.add_argument("--max", type=int, default=0, help="alleen de eerste N casussen per functie")
    ap.add_argument("--basis", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()

    casussen, ontbreekt = laad_casussen(a.functie)
    if a.max:
        per, gekozen = {}, []
        for c in casussen:
            per[c["functie"]] = per.get(c["functie"], 0) + 1
            if per[c["functie"]] <= a.max:
                gekozen.append(c)
        casussen = gekozen
    if ontbreekt:
        print(f"CASUSSEN ONTBREKEN voor: {', '.join(ontbreekt)}", file=sys.stderr)
    if not casussen:
        print("Geen casussen gevonden.", file=sys.stderr)
        return 1

    uitmap = os.path.join(ROOT, "criticus", a.ronde)
    if a.laag == "dossier":
        # bouwt uit de beste beschikbare uitvoer: volledig als die er is, anders deterministisch
        for f in sorted({c["functie"] for c in casussen}):
            res = {}
            lagen = ("deterministisch", "volledig", "standin") if a.dossier_laag == "auto" else (a.dossier_laag,)
            for laag in lagen:
                pad = os.path.join(uitmap, laag, f"{f}.json")
                if os.path.exists(pad):
                    res = {r["id"]: r for r in json.load(open(pad, encoding="utf-8"))}
            os.makedirs(os.path.join(uitmap, "dossiers"), exist_ok=True)
            tekst = dossier(f, [c for c in casussen if c["functie"] == f], res)
            naam = f"{f}.md" if a.dossier_laag in ("auto", "volledig") else f"{f}.{a.dossier_laag}.md"
            open(os.path.join(uitmap, "dossiers", naam), "w", encoding="utf-8").write(tekst)
            print(f"dossier: criticus/{a.ronde}/dossiers/{naam} ({len(res)} uitkomsten)")
        return 1 if ontbreekt else 0

    if a.laag == "standin":
        if not a.antwoorden or not os.path.isdir(a.antwoorden):
            print("standin heeft --antwoorden <map> nodig (zie scripts/criticus_prompts.py)", file=sys.stderr)
            return 2
        os.makedirs(os.path.join(uitmap, "standin"), exist_ok=True)
        resultaten = {c["id"]: draai_standin(c, a.antwoorden) for c in casussen}
        for f in sorted({c["functie"] for c in casussen}):
            with open(os.path.join(uitmap, "standin", f"{f}.json"), "w", encoding="utf-8") as fh:
                json.dump([resultaten[c["id"]] for c in casussen if c["functie"] == f], fh, ensure_ascii=False, indent=1)
        fouten = samenvatting(casussen, resultaten, "volledig")
        ontbrekend = [i for i, r in resultaten.items() if r.get("onvolledig")]
        if ontbrekend:
            print(f"\n{len(ontbrekend)} antwoord(en) ontbreken: {', '.join(ontbrekend[:8])}", file=sys.stderr)
        return 1 if (fouten or ontbreekt or ontbrekend) else 0

    resultaten = {}
    os.makedirs(os.path.join(uitmap, a.laag), exist_ok=True)
    voortgang = os.path.join(uitmap, a.laag, "_voortgang.jsonl")
    sleutels = {c["id"]: versie_sleutel(c) for c in casussen}
    if a.laag == "volledig" and os.path.exists(voortgang):
        # Een run van uren mag niet alles kwijt zijn bij een onderbreking: hervat waar hij bleef. Alleen
        # complete uitkomsten van DEZELFDE code en casus tellen; een afgekapte laatste regel wordt overgeslagen.
        verouderd = onleesbaar = 0
        for regel in open(voortgang, encoding="utf-8"):
            try:
                r = json.loads(regel)
            except ValueError:
                onleesbaar += 1
                continue
            if r.get("id") not in sleutels:              # een casus van een andere functie: staat in dezelfde tussenstand
                continue
            if r.get("_sleutel") != sleutels[r["id"]] or not is_bruikbaar(r):
                verouderd += 1
                continue
            resultaten[r["id"]] = r
        if resultaten or verouderd or onleesbaar:
            print(f"Hervat: {len(resultaten)} casussen staan al in {os.path.relpath(voortgang, ROOT)}"
                  f" ({verouderd} verouderd of mislukt en opnieuw te draaien, {onleesbaar} onleesbaar)", flush=True)
    for i, c in enumerate(casussen, 1):
        if c["id"] in resultaten:
            continue
        if a.laag == "deterministisch":
            resultaten[c["id"]] = draai_deterministisch(c)
        else:
            print(f"[{i}/{len(casussen)}] {c['id']} ...", flush=True)
            resultaten[c["id"]] = draai_volledig(c, a.basis, a.timeout)
            resultaten[c["id"]]["_sleutel"] = sleutels[c["id"]]
            if is_bruikbaar(resultaten[c["id"]]):          # een mislukte run wordt bij hervatten opnieuw gedaan
                with open(voortgang, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(resultaten[c["id"]], ensure_ascii=False) + "\n")
            print(f"    klaar in {resultaten[c['id']].get('duur_sec')} s; http {resultaten[c['id']].get('http_status')}"
                  f"; controle {(resultaten[c['id']].get('controle') or {}).get('oordeel')}", flush=True)
    resultaten = {c["id"]: resultaten[c["id"]] for c in casussen if c["id"] in resultaten}
    for f in sorted({c["functie"] for c in casussen}):
        lijst = [resultaten[c["id"]] for c in casussen if c["functie"] == f]
        with open(os.path.join(uitmap, a.laag, f"{f}.json"), "w", encoding="utf-8") as fh:
            json.dump(lijst, fh, ensure_ascii=False, indent=1)
    fouten = samenvatting(casussen, resultaten, a.laag)
    mislukt = [cid for cid, r in resultaten.items() if a.laag == "volledig" and not is_bruikbaar(r)]
    if mislukt:
        print(f"\n{len(mislukt)} RUN(S) MISLUKT (server onbereikbaar, HTTP-fout of stroom zonder einde): "
              f"{', '.join(mislukt[:8])}{' ...' if len(mislukt) > 8 else ''}", file=sys.stderr)
    return 1 if (fouten or ontbreekt or mislukt) else 0


if __name__ == "__main__":
    sys.exit(main())
