#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blind_ab_rapport.py - Leest de ingevulde beoordelingen van een blinde A/B-ronde en
zegt eerlijk wat ze waard zijn.

Invoer
------
- renders/ab/_sleutel.json          (de geheime sleutel; alleen de operator leest hem)
- renders/ab/<ronde>/<viewport>/beoordeling.csv, per viewport ingevuld
  kolommen: label, hierarchie_1_5, typografie_1_5, ritme_witruimte_1_5,
            consistentie_1_5, totaalindruk_1_5, opmerking

Uitvoer
-------
Per viewport: gemiddelde per bron en per criterium, de rangorde, of ons scherm
boven de decoys eindigt, of het anker bovenaan eindigt, of de decoys in hun bedoelde
kwaliteitsvolgorde staan (veld `kwaliteit`: zeer_zwak < zwak < matig < redelijk) en of
de scores intern consistent zijn.

De ronde is ONGELDIG - en er wordt dan GEEN winst gemeld - als een van deze klopt:
  * er ontbreken cellen (of ze zijn geen geheel getal van 1 tot 5), of labels zijn
    onbekend of dubbel
  * alle scores zijn (bijna) gelijk: 90% of meer van de cellen heeft dezelfde waarde,
    of de spreiding van de labelgemiddelden is kleiner dan 0,25
  * het anker staat niet bovenaan (de beoordelaar heeft dan geen smaak, of rekent
    drukte af), of een anker scoort niet boven alle decoys
  * de zwakste decoy staat niet onderaan (er scoort iets lager dan de bedoelde bodem)
  * de decoys staan niet in hun bedoelde kwaliteitsvolgorde
  * het totaalcijfer volgt de deelcijfers niet (rangcorrelatie < 0,30): willekeurig
    invullen
  * de ronde bevat geen anker of geen decoy: dan is er geen controle om op te vertrouwen
  * de sleutel meldt NIET-BRUIKBAAR-VOOR-OORDEEL (testronde), komt van een harnas van
    voor versie 2 (geen OCR-lekcontrole, geen vaste hoogte) of meldt dat de hoogte een
    vingerafdruk is
"Ongeldig" is een geldig en eerlijk resultaat; een schijnwinst nooit. Een viewport
kan geldig zijn terwijl een andere dat niet is; de ronde is pas geldig als alle
beoordeelde viewports dat zijn.

Vergelijkbaarheid. Elke opname heeft een `soort_scherm` (app/dashboard, formulier, register,
docs, ...). Het rapport toont de scores per soort en laat de uitspraak over "ons scherm
t.o.v. de comps" alleen over VERGELIJKBARE comps gaan: werkschermen (app/dashboard,
formulier, register, ...) tegenover werkschermen, niet tegenover documentatie. Is de soort
van ons scherm onbekend, dan volgt er geen uitspraak over het niveau t.o.v. de comps (wel
over de decoys). De familie-indeling staat in SOORT_FAMILIE. Ook meldt het rapport uit
welke manifestvorm elke bron kwam.

Waarschuwingen (maken de ronde niet ongeldig, wel voorzichtiger):
  gemengde ronde (--domein alles), classificatie ontbrekend in de manifesten,
  decoykwaliteit onbekend (de volgordecontrole wordt dan overgeslagen en gemeld),
  weinig comps, matige interne consistentie, beelden met weinig gelezen OCR-tekst,
  een totaalindruk die samenhangt met het aantal gemaskeerde kaders (een masker is zelf
  een signaal), opmerkingen waarin de beoordelaar zelf een bron noemt.

Gebruik
-------
  python3 scripts/blind_ab_rapport.py --ronde ronde1
  python3 scripts/blind_ab_rapport.py --ronde ronde1 --json renders/ab/ronde1_rapport.json
  python3 scripts/blind_ab_rapport.py --sleutel PAD --ronde r --beoordeling desktop=PAD.csv
  python3 scripts/blind_ab_rapport.py --zelftest

Exitcode: 0 = GELDIG, 1 = ONGELDIG of NIET-BRUIKBAAR-VOOR-OORDEEL, 2 = invoerfout.
Alleen standaardbibliotheek.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import statistics
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parent.parent

CRITERIA = ("hierarchie_1_5", "typografie_1_5", "ritme_witruimte_1_5",
            "consistentie_1_5", "totaalindruk_1_5")
CRITERIUM_NAMEN = {"hierarchie_1_5": "hierarchie", "typografie_1_5": "typografie",
                   "ritme_witruimte_1_5": "ritme/witruimte",
                   "consistentie_1_5": "consistentie", "totaalindruk_1_5": "totaalindruk"}
KWALITEIT_VOLGORDE = ("zeer_zwak", "zwak", "matig", "redelijk")     # oplopend

# Welke soorten scherm onderling vergelijkbaar zijn ("werkschermen tegenover werkschermen").
# De waarden komen uit de manifesten van de opnames (soort_scherm is vrije tekst); een waarde die hier
# niet staat en waar ook geen bekend deel in zit, vormt een eigen familie: alleen met zichzelf
# vergelijkbaar. Liever te weinig vergeleken dan appels met peren.
SOORT_FAMILIE = {
    # werkschermen: waar iemand iets doet, zoekt of invult
    "app/dashboard": "werkscherm", "app": "werkscherm", "dashboard": "werkscherm", "werkscherm": "werkscherm",
    "backoffice": "werkscherm", "formulier": "werkscherm", "formulierstap": "werkscherm",
    "register": "werkscherm", "tabel": "werkscherm", "lijst": "werkscherm", "lijstweergave": "werkscherm",
    "detail": "werkscherm", "instellingen": "werkscherm", "wizard": "werkscherm", "flow": "werkscherm",
    "boekingsflow": "werkscherm", "dataviewer": "werkscherm", "resultaten": "werkscherm",
    "zoekresultaten": "werkscherm", "zoeken": "werkscherm", "zoekscherm": "werkscherm",
    "register_zoekresultaten": "werkscherm",
    # documentatie en uitleg
    "docs": "documentatie", "documentatie": "documentatie", "referentie": "documentatie",
    "kennisbank": "documentatie", "help": "documentatie", "informatiepagina": "documentatie",
    "document_lezer": "documentatie", "artikel": "documentatie",
    # marketing en etalage
    "marketing": "marketing", "marketing_home": "marketing", "landing": "marketing",
    "galerij_landing": "marketing", "vergelijker_landing": "marketing", "prijzen": "marketing",
    "prijzenpagina": "marketing", "productpagina": "marketing", "homepage": "marketing",
    "organisatie_homepage": "marketing",
    # de poort naar een omgeving
    "inlogpoort": "toegang", "inlog": "toegang", "login": "toegang",
}


def norm_soort_scherm(waarde: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*/\s*", "/", str(waarde or "").strip().lower()))


def familie(soort_scherm: str) -> str:
    """Familie van een soort scherm: eerst de hele waarde, dan (bij een samengestelde waarde als
    'formulier_landing') het eerste deel dat we kennen, anders de waarde zelf als eigen familie."""
    s = norm_soort_scherm(soort_scherm)
    if not s:
        return "onbekend"
    if s in SOORT_FAMILIE:
        return SOORT_FAMILIE[s]
    delen = [d for d in re.split(r"[\s/_\-]+", s) if d]
    if len(delen) > 1:
        for d in delen:
            if d in SOORT_FAMILIE:
                return SOORT_FAMILIE[d]
    return s


# Alle drempels op een plek, en ze worden in de JSON-uitvoer meegegeven.
DREMPELS = {
    "marge_boven": 0.25,              # verschil (schaalpunten) dat als 'boven' telt
    "tolerantie_anker_top": 0.25,     # anker mag zoveel onder de hoogste bron staan
    "tolerantie_bodem": 0.25,         # zwakste decoy mag zoveel boven de laagste andere bron staan
    "tolerantie_volgorde": 0.20,      # decoypaar mag zoveel 'verkeerd' om staan (ruis)
    "gelijk_aandeel": 0.90,           # aandeel cellen met dezelfde waarde = bijna alles gelijk
    "gelijk_sd": 0.25,                # sd van de labelgemiddelden hieronder = bijna alles gelijk
    "consistentie_ongeldig": 0.30,    # Spearman totaalindruk vs. rest, hieronder ongeldig
    "consistentie_waarschuwing": 0.60,
    "min_labels_consistentie": 8,     # zo weinig beelden: consistentie niet te beoordelen
    "weinig_comps": 5,
    "masker_samenhang": 0.5,          # |Spearman| tussen totaalindruk en aantal maskers: waarschuwing
}


# ---------------------------------------------------------------------------
# Hulpfuncties (alleen standaardbibliotheek)
# ---------------------------------------------------------------------------
def _gem(waarden: list[float]) -> float:
    return sum(waarden) / len(waarden)


def _rangen(waarden: list[float]) -> list[float]:
    """Rangnummers met gemiddelde rang bij gelijke waarden."""
    gesorteerd = sorted(range(len(waarden)), key=lambda i: waarden[i])
    rang = [0.0] * len(waarden)
    i = 0
    while i < len(gesorteerd):
        j = i
        while j + 1 < len(gesorteerd) and waarden[gesorteerd[j + 1]] == waarden[gesorteerd[i]]:
            j += 1
        for k in range(i, j + 1):
            rang[gesorteerd[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return rang


def spearman(x: list[float], y: list[float]) -> float | None:
    """Rangcorrelatie; None als een reeks constant is (dan is er niets te correleren)."""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = _rangen(x), _rangen(y)
    mx, my = _gem(rx), _gem(ry)
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sx * sy)


def _vouw(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _f(x: float | None, nd: int = 2) -> str:
    return "-" if x is None else f"{x:.{nd}f}".replace(".", ",")


# ---------------------------------------------------------------------------
# Datamodel
# ---------------------------------------------------------------------------
@dataclass
class Item:
    label: str
    bron_naam: str
    soort: str                  # comp | ours | decoy | anker
    kwaliteit: str = ""
    bron_bestand: str = ""
    soort_scherm: str = ""
    manifest_vorm: str = ""
    maskers: int | None = None      # aantal door de OCR gemaskeerde kaders in dit beeld (None: onbekend)

    @property
    def sleutel(self) -> tuple[str, str, str]:
        return (self.soort, self.bron_naam, self.soort_scherm)


@dataclass
class Bron:
    soort: str
    naam: str
    labels: list[str]
    kwaliteit: str
    gem: float                                   # over alle vijf criteria en alle labels
    per_criterium: dict[str, float]
    totaalindruk: float
    kleinste_label: float = 0.0
    grootste_label: float = 0.0
    soort_scherm: str = ""
    manifest_vorm: str = ""


@dataclass
class ViewportUitslag:
    viewport: str
    geldig: bool = True
    redenen_ongeldig: list[str] = field(default_factory=list)
    waarschuwingen: list[str] = field(default_factory=list)
    controles: list[dict] = field(default_factory=list)      # {naam, ok, tekst}
    bronnen: list[Bron] = field(default_factory=list)        # gesorteerd, hoogste eerst
    per_criterium_totaal: dict[str, float] = field(default_factory=dict)
    per_soort: list[dict] = field(default_factory=list)
    conclusie: dict[str, Any] = field(default_factory=dict)
    maskers_vs_score: dict[str, Any] = field(default_factory=dict)
    aantal_labels: int = 0

    def controle(self, naam: str, ok: bool | None, tekst: str, ongeldig_bij_fout: bool = True) -> None:
        """ok=None betekent 'niet gecontroleerd'."""
        self.controles.append({"naam": naam, "ok": ok, "tekst": tekst})
        if ok is False and ongeldig_bij_fout:
            self.geldig = False
            self.redenen_ongeldig.append(tekst)


# ---------------------------------------------------------------------------
# Inlezen
# ---------------------------------------------------------------------------
def lees_sleutel(pad: Path, ronde: str) -> dict:
    data = json.loads(Path(pad).read_text(encoding="utf-8"))
    rondes = data.get("rondes", {})
    if ronde not in rondes:
        raise KeyError(f"ronde {ronde!r} staat niet in {pad} (bekend: {sorted(rondes)})")
    return rondes[ronde]


def lees_csv(pad: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Retourneert ({label: {criterium: waarde|None|'ONGELDIG:..', 'opmerking': str}}, meldingen)."""
    tekst = Path(pad).read_text(encoding="utf-8-sig")
    meldingen: list[str] = []
    monster = tekst[:2000]
    delim = ","
    if monster.count(";") > monster.count(","):
        delim = ";"
    elif monster.count("\t") > monster.count(","):
        delim = "\t"
    lezer = csv.DictReader(io.StringIO(tekst), delimiter=delim)
    kop = [(k or "").strip().lower() for k in (lezer.fieldnames or [])]
    ontbreekt = [c for c in ("label",) + CRITERIA if c not in kop]
    if ontbreekt:
        raise ValueError(f"{pad}: kolommen ontbreken: {', '.join(ontbreekt)} (gevonden: {kop})")
    uit: dict[str, dict[str, Any]] = {}
    for rij in lezer:
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in rij.items() if k is not None}
        label = r.get("label", "")
        if not label:
            continue
        if label in uit:
            meldingen.append(f"label {label} komt meer dan een keer voor")
            uit[label]["_dubbel"] = True
            continue
        rec: dict[str, Any] = {"opmerking": r.get("opmerking", "")}
        for c in CRITERIA:
            ruw = r.get(c, "")
            if ruw == "":
                rec[c] = None
                continue
            try:
                w = float(ruw.replace(",", "."))
            except ValueError:
                rec[c] = f"ONGELDIG:{ruw}"
                continue
            if w != int(w) or not (1 <= w <= 5):
                rec[c] = f"ONGELDIG:{ruw}"
            else:
                rec[c] = float(int(w))
        uit[label] = rec
    return uit, meldingen


# ---------------------------------------------------------------------------
# Analyse van een viewport
# ---------------------------------------------------------------------------
def analyseer_viewport(viewport: str, items: list[Item], scores: dict[str, dict[str, Any]] | None,
                       csv_meldingen: list[str], drempels: dict = DREMPELS) -> ViewportUitslag:
    u = ViewportUitslag(viewport=viewport, aantal_labels=len(items))
    d = drempels

    # ---- 1. cellen compleet en geldig
    if scores is None:
        u.controle("cellen", False, f"{viewport}: er is geen ingevulde beoordeling.csv")
        return u
    keylabels = [i.label for i in items]
    onbekend = sorted(set(scores) - set(keylabels))
    ontbrekend_labels = [l for l in keylabels if l not in scores]
    lege: list[str] = []
    ongeldige: list[str] = []
    for l in keylabels:
        rec = scores.get(l)
        if not rec:
            continue
        for c in CRITERIA:
            v = rec.get(c)
            if v is None:
                lege.append(f"{l}:{CRITERIUM_NAMEN[c]}")
            elif isinstance(v, str):
                ongeldige.append(f"{l}:{CRITERIUM_NAMEN[c]}={v.split(':', 1)[1]}")
    dubbel = [l for l, rec in scores.items() if rec.get("_dubbel")]
    totaal_cellen = len(keylabels) * len(CRITERIA)
    fout_cellen = len(lege) + len(ongeldige) + len(ontbrekend_labels) * len(CRITERIA)
    problemen = []
    if ontbrekend_labels:
        problemen.append(f"{len(ontbrekend_labels)} labels ontbreken in het bestand ({', '.join(ontbrekend_labels[:6])})")
    if lege:
        problemen.append(f"{len(lege)} lege cellen (bijv. {', '.join(lege[:4])})")
    if ongeldige:
        problemen.append(f"{len(ongeldige)} cellen zijn geen geheel getal van 1 tot 5 (bijv. {', '.join(ongeldige[:4])})")
    if onbekend:
        problemen.append(f"onbekende labels in het bestand: {', '.join(onbekend[:6])}")
    if dubbel:
        problemen.append(f"dubbele labels: {', '.join(dubbel[:6])}")
    if problemen:
        u.controle("cellen", False, f"{viewport}: onvolledige of ongeldige beoordeling: "
                   + "; ".join(problemen) + f" ({fout_cellen} van {totaal_cellen} cellen)")
        return u                                    # verder rekenen heeft geen zin
    u.controle("cellen", True, f"alle {totaal_cellen} cellen ({len(keylabels)} beelden x 5) zijn ingevuld")

    # ---- 2. bronnen aggregeren
    matrix = {l: [float(scores[l][c]) for c in CRITERIA] for l in keylabels}
    per_bron: dict[tuple[str, str, str], list[Item]] = {}
    for it in items:
        per_bron.setdefault(it.sleutel, []).append(it)
    bronnen: list[Bron] = []
    for (soort, naam, sscherm), its in per_bron.items():
        rijen = [matrix[i.label] for i in its]
        celw = [w for r in rijen for w in r]
        kwal = next((i.kwaliteit for i in its if i.kwaliteit), "")
        gemlabel = [_gem(r) for r in rijen]
        bronnen.append(Bron(
            soort=soort, naam=naam, labels=[i.label for i in its], kwaliteit=kwal,
            gem=_gem(celw),
            per_criterium={c: _gem([r[k] for r in rijen]) for k, c in enumerate(CRITERIA)},
            totaalindruk=_gem([r[CRITERIA.index("totaalindruk_1_5")] for r in rijen]),
            kleinste_label=min(gemlabel), grootste_label=max(gemlabel),
            soort_scherm=sscherm, manifest_vorm=its[0].manifest_vorm))
    bronnen.sort(key=lambda b: (-b.gem, b.naam))
    u.bronnen = bronnen
    u.per_criterium_totaal = {c: _gem([r[k] for r in matrix.values()]) for k, c in enumerate(CRITERIA)}
    per_soort: dict[str, dict[str, Any]] = {}
    for b in bronnen:
        k = b.soort_scherm or "onbekend"
        rec = per_soort.setdefault(k, {"soort_scherm": k, "familie": familie(k), "rollen": {}})
        rec["rollen"].setdefault(b.soort, []).append(b.gem)
    u.per_soort = [
        {"soort_scherm": k, "familie": v["familie"],
         "rollen": {rol: {"aantal_bronnen": len(g), "gemiddelde": _gem(g), "min": min(g), "max": max(g)}
                    for rol, g in sorted(v["rollen"].items())}}
        for k, v in sorted(per_soort.items())]

    # ---- 3. (bijna) alles gelijk?
    alle = [w for r in matrix.values() for w in r]
    modus_aandeel = max(alle.count(v) for v in set(alle)) / len(alle)
    label_gem = [_gem(r) for r in matrix.values()]
    sd = statistics.pstdev(label_gem) if len(label_gem) > 1 else 0.0
    gelijk = modus_aandeel >= d["gelijk_aandeel"] or sd < d["gelijk_sd"]
    u.controle("spreiding", not gelijk,
               (f"alle scores zijn (bijna) gelijk: {modus_aandeel:.0%} van de cellen heeft dezelfde waarde, "
                f"spreiding van de labelgemiddelden {_f(sd)}; de beoordelaar onderscheidt niets")
               if gelijk else
               f"scores lopen uiteen ({modus_aandeel:.0%} modale waarde, spreiding {_f(sd)})")

    # ---- 4. anker bovenaan
    ankers = [b for b in bronnen if b.soort == "anker"]
    decoys = [b for b in bronnen if b.soort == "decoy"]
    ons = [b for b in bronnen if b.soort == "ours"]
    comps = [b for b in bronnen if b.soort == "comp"]
    anderen_niet_anker = [b for b in bronnen if b.soort != "anker"]
    if not ankers:
        u.controle("anker", False, f"{viewport}: de ronde bevat geen anker (positieve controle); "
                   "zonder anker is niet te onderscheiden of de beoordelaar smaak heeft of alleen "
                   "drukte afstraft")
    else:
        beste_anker = max(ankers, key=lambda b: b.gem)
        hoogste_andere = max((b.gem for b in anderen_niet_anker), default=None)
        top_ok = hoogste_andere is None or beste_anker.gem >= hoogste_andere - d["tolerantie_anker_top"]
        boven_ons = [b for b in anderen_niet_anker if b.gem > beste_anker.gem + d["tolerantie_anker_top"]]
        if top_ok:
            u.controle("anker", True, f"het anker ({beste_anker.naam}, {_f(beste_anker.gem)}) staat bovenaan")
        else:
            wie = ", ".join(f"{b.naam} ({_f(b.gem)})" + (" = ONS SCHERM" if b.soort == "ours" else "")
                            for b in boven_ons[:4])
            u.controle("anker", False, f"het anker staat niet bovenaan: {beste_anker.naam} scoort "
                       f"{_f(beste_anker.gem)} en er staat hoger: {wie}")
        if decoys:
            hoogste_decoy = max(b.gem for b in decoys)
            onder = [b for b in ankers if b.gem <= hoogste_decoy]
            u.controle("anker_boven_decoys", not onder,
                       (f"anker {', '.join(b.naam for b in onder)} scoort niet boven alle decoys "
                        f"({_f(hoogste_decoy)})") if onder else "elk anker scoort boven alle decoys")

    # ---- 5. zwakste decoy onderaan + volgorde
    if not decoys:
        u.controle("bodem", False, f"{viewport}: de ronde bevat geen decoy; zonder decoy is er geen "
                   "bodemcontrole")
    else:
        bekende = [b for b in decoys if b.kwaliteit in KWALITEIT_VOLGORDE]
        if bekende:
            laagste_q = min(KWALITEIT_VOLGORDE.index(b.kwaliteit) for b in bekende)
            zwakste = [b for b in bekende if KWALITEIT_VOLGORDE.index(b.kwaliteit) == laagste_q]
            zwakste_wat = f"de zwakste decoy ({', '.join(b.naam for b in zwakste)}, {KWALITEIT_VOLGORDE[laagste_q]})"
        else:
            zwakste = [min(decoys, key=lambda b: b.gem)]
            zwakste_wat = f"de laagst scorende decoy ({zwakste[0].naam})"
            u.waarschuwingen.append("geen decoykwaliteit in de sleutel: als 'zwakste decoy' geldt de "
                                    "laagst scorende decoy, dus de bodemcontrole is zwakker")
        zw_gem = min(b.gem for b in zwakste)
        niet_decoys = [b for b in bronnen if b.soort != "decoy"]
        eronder = [b for b in niet_decoys if b.gem < zw_gem - d["tolerantie_bodem"]]
        if eronder:
            wie = ", ".join(f"{b.naam} ({_f(b.gem)})" + (" = ONS SCHERM" if b.soort == "ours" else "")
                            for b in eronder[:4])
            u.controle("bodem", False, f"{zwakste_wat} staat niet onderaan ({_f(zw_gem)}): er scoort "
                       f"lager: {wie}. Dat kan een slecht scherm zijn, maar de schaal van de "
                       "beoordelaar is dan niet te vertrouwen")
        else:
            u.controle("bodem", True, f"{zwakste_wat} staat onderaan ({_f(zw_gem)})")

        # volgorde tussen decoys
        if len(bekende) >= 2 and len({b.kwaliteit for b in bekende}) >= 2:
            fouten = []
            for i in range(len(bekende)):
                for j in range(len(bekende)):
                    qi = KWALITEIT_VOLGORDE.index(bekende[i].kwaliteit)
                    qj = KWALITEIT_VOLGORDE.index(bekende[j].kwaliteit)
                    if qi < qj and bekende[i].gem > bekende[j].gem + d["tolerantie_volgorde"]:
                        fouten.append(f"{bekende[i].naam} ({bekende[i].kwaliteit}, {_f(bekende[i].gem)}) staat "
                                      f"boven {bekende[j].naam} ({bekende[j].kwaliteit}, {_f(bekende[j].gem)})")
            u.controle("decoyvolgorde", not fouten,
                       ("de decoys staan niet in hun bedoelde kwaliteitsvolgorde: " + "; ".join(fouten[:4]))
                       if fouten else "de decoys staan in hun bedoelde kwaliteitsvolgorde")
        else:
            u.controle("decoyvolgorde", None,
                       "decoyvolgorde NIET gecontroleerd: de sleutel kent voor minder dan twee decoys "
                       "een `kwaliteit` (of ze hebben dezelfde)", ongeldig_bij_fout=False)

    # ---- 6. interne consistentie
    if len(keylabels) >= d["min_labels_consistentie"]:
        totaal_i = CRITERIA.index("totaalindruk_1_5")
        totaal = [r[totaal_i] for r in matrix.values()]
        rest = [_gem([w for k, w in enumerate(r) if k != totaal_i]) for r in matrix.values()]
        rho = spearman(totaal, rest)
        if rho is None:
            u.controle("consistentie", None, "consistentie niet te berekenen (een reeks is constant)",
                       ongeldig_bij_fout=False)
        elif rho < d["consistentie_ongeldig"]:
            u.controle("consistentie", False, f"het totaalcijfer volgt de deelcijfers niet (rangcorrelatie "
                       f"{_f(rho)}, minimum {_f(d['consistentie_ongeldig'])}): de beoordeling lijkt willekeurig")
        else:
            u.controle("consistentie", True, f"totaalindruk volgt de deelcijfers (rangcorrelatie {_f(rho)})")
            if rho < d["consistentie_waarschuwing"]:
                u.waarschuwingen.append(f"matige interne consistentie (rangcorrelatie {_f(rho)})")
    else:
        u.controle("consistentie", None, f"consistentie niet beoordeeld: minder dan "
                   f"{d['min_labels_consistentie']} beelden", ongeldig_bij_fout=False)

    # ---- 6b. hangt de score samen met het aantal gemaskeerde plekken?
    # Een masker is zelf een signaal: de beoordelaar kan 'gemaskeerde plek' leren als 'externe bron'. Dat maakt
    # de ronde niet ongeldig (het kan ook inhoud zijn: comps met veel merktekst), maar de uitslag verdient
    # dan meer voorzichtigheid.
    maskers = [i.maskers for i in items]
    if (len(items) >= d["min_labels_consistentie"] and all(m is not None for m in maskers)
            and len(set(maskers)) > 1):
        totaal_i = CRITERIA.index("totaalindruk_1_5")
        rho_m = spearman([float(m) for m in maskers], [matrix[i.label][totaal_i] for i in items])
        u.maskers_vs_score = {"rho": rho_m, "n": len(items)}
        if rho_m is not None and abs(rho_m) >= d["masker_samenhang"]:
            richting = "lager" if rho_m < 0 else "hoger"
            u.waarschuwingen.append(
                f"de totaalindruk hangt samen met het aantal gemaskeerde kaders per beeld (rangcorrelatie "
                f"{_f(rho_m)}, n={len(items)}): beelden met meer maskers scoren {richting}. Mogelijk leest de "
                "beoordelaar een gemaskeerde plek als teken van herkomst; het kan ook inhoud zijn (comps met "
                "veel merktekst). Weeg de uitslag hiermee")

    # ---- 7. conclusie (alleen als de viewport geldig is)
    ons_gewogen = None
    if ons:
        ons_gewogen = _gem([w for b in ons for l in b.labels for w in matrix[l]])
    c: dict[str, Any] = {"ons_gemiddelde": ons_gewogen, "aantal_eigen_bronnen": len(ons)}
    if ons_gewogen is not None and decoys:
        beste_decoy = max(decoys, key=lambda b: b.gem)
        marge = ons_gewogen - beste_decoy.gem
        c["beste_decoy"] = {"naam": beste_decoy.naam, "gemiddelde": beste_decoy.gem}
        c["marge_op_beste_decoy"] = marge
        c["boven_decoys"] = marge >= d["marge_boven"]
        c["onder_decoys"] = marge <= -d["marge_boven"]
        c["eigen_schermen_boven_alle_decoys"] = sum(1 for b in ons if b.gem > beste_decoy.gem)

    # ons scherm t.o.v. de comps: ALLEEN vergelijkbare soorten scherm
    ons_groepen: dict[str, list[Bron]] = {}
    for b in ons:
        ons_groepen.setdefault(b.soort_scherm, []).append(b)
    vergelijkingen: list[dict[str, Any]] = []
    for soort_o, groep in sorted(ons_groepen.items()):
        gem_o = _gem([w for b in groep for l in b.labels for w in matrix[l]])
        e: dict[str, Any] = {"ons_soort": soort_o or "onbekend", "ons_gemiddelde": gem_o,
                             "aantal_eigen_bronnen": len(groep), "op_niveau": None}
        if not soort_o:
            e["reden"] = ("de soort_scherm van ons scherm is onbekend: vergelijkbaarheid met de comps is "
                          "niet vast te stellen, dus geen uitspraak over het niveau t.o.v. de comps")
            u.waarschuwingen.append(e["reden"])
        else:
            fam = familie(soort_o)
            vb = [b for b in comps if b.soort_scherm and familie(b.soort_scherm) == fam]
            buiten: dict[str, int] = {}
            for b in comps:
                if b not in vb:
                    buiten[b.soort_scherm or "onbekend"] = buiten.get(b.soort_scherm or "onbekend", 0) + 1
            e.update({"familie": fam, "aantal_vergelijkbaar": len(vb),
                      "soorten_vergelijkbaar": sorted({b.soort_scherm for b in vb}),
                      "buiten_vergelijking": dict(sorted(buiten.items()))})
            if vb:
                mediaan = statistics.median([b.gem for b in vb])
                e.update({"comps_mediaan": mediaan, "comps_gemiddelde": _gem([b.gem for b in vb]),
                          "rang": 1 + sum(1 for b in vb if b.gem > gem_o), "aantal_comps": len(vb),
                          "op_niveau": gem_o >= mediaan - d["marge_boven"]})
                if len(vb) < d["weinig_comps"]:
                    u.waarschuwingen.append(
                        f"slechts {len(vb)} vergelijkbare comps voor {soort_o} ({fam}); een vergelijking met "
                        "'echte, goede interfaces' rust dan op weinig")
            else:
                e["reden"] = f"er zijn geen comps van een vergelijkbare soort ({fam}) in deze ronde"
                u.waarschuwingen.append(e["reden"])
        vergelijkingen.append(e)
    zonder_soort = [b for b in comps if not b.soort_scherm]
    if zonder_soort:
        u.waarschuwingen.append(f"{len(zonder_soort)} comps hebben geen soort_scherm en zijn niet als "
                                "vergelijkbaar met ons scherm gerekend")
    c["vergelijking_met_comps"] = vergelijkingen
    niveaus = [e["op_niveau"] for e in vergelijkingen if e["op_niveau"] is not None]
    c["op_niveau_van_comps"] = (all(niveaus) if niveaus else None)
    if len(vergelijkingen) == 1 and vergelijkingen[0].get("aantal_comps"):
        e = vergelijkingen[0]
        c.update({"comps_mediaan": e["comps_mediaan"], "comps_gemiddelde": e["comps_gemiddelde"],
                  "rang_onder_comps": e["rang"], "aantal_comps": e["aantal_comps"]})
    if ankers:
        c["beste_anker"] = {"naam": max(ankers, key=lambda b: b.gem).naam,
                            "gemiddelde": max(b.gem for b in ankers)}
    # robuustheid: hetzelfde oordeel op basis van het totaalcijfer alleen
    if ons and decoys:
        ons_t = _gem([b.totaalindruk for b in ons])
        dec_t = max(b.totaalindruk for b in decoys)
        c["boven_decoys_op_totaalindruk"] = (ons_t - dec_t) >= d["marge_boven"]
        if c.get("boven_decoys") != c["boven_decoys_op_totaalindruk"] and u.geldig:
            u.waarschuwingen.append("het oordeel 'boven de decoys' verschilt tussen het gemiddelde van "
                                    "alle criteria en het totaalcijfer alleen: niet robuust")
    u.conclusie = c
    return u


# ---------------------------------------------------------------------------
# Hele ronde
# ---------------------------------------------------------------------------
def items_uit_sleutel(vp_data: dict) -> list[Item]:
    uit = []
    for it in vp_data.get("items", []):
        soort = it.get("soort") or ("ours" if it.get("is_ons") else "decoy" if it.get("is_decoy")
                                    else "anker" if it.get("is_anker") else "comp")
        if it.get("is_anker"):
            soort = "anker"
        uit.append(Item(label=it["label"], bron_naam=it.get("bron_naam") or it["label"], soort=soort,
                        kwaliteit=it.get("kwaliteit", "") or "", bron_bestand=it.get("bron_bestand", ""),
                        soort_scherm=norm_soort_scherm(it.get("soort_scherm", "")),
                        manifest_vorm=it.get("manifest_vorm", "") or "",
                        maskers=(lambda n: n if isinstance(n, int) and not isinstance(n, bool) else None)(
                            (it.get("ocr") or {}).get("kaders_gemaskeerd"))))
    return uit


def beoordeel_ronde(sleutel: dict, csv_per_viewport: dict[str, Path | None],
                    drempels: dict = DREMPELS) -> dict[str, Any]:
    """Het volledige oordeel over een ronde. Retourneert een JSON-baar woordenboek."""
    meetlat = sleutel.get("meetlat")
    globaal_ongeldig: list[str] = []
    waarschuwingen: list[str] = []
    status_sleutel = (meetlat or {}).get("status")

    versie = str(sleutel.get("script_versie", "0"))
    try:
        oud = int(versie.split(".")[0]) < 2
    except ValueError:
        oud = True
    if meetlat is None or oud:
        globaal_ongeldig.append("de sleutel komt van een meetlat van voor versie 2 (geen OCR-lekcontrole, "
                                "geen vaste beeldhoogte): de blindering is niet aangetoond")
    niet_bruikbaar = bool(meetlat) and meetlat.get("bruikbaar_voor_oordeel") is False
    if meetlat:
        for vp, h in (sleutel.get("hoogte_eigenschap") or {}).items():
            if h.get("unieke_hoogtes", 1) > 1:
                globaal_ongeldig.append(f"{vp}: de beeldhoogte is een vingerafdruk "
                                        f"({h['unieke_hoogtes']} unieke hoogtes)")
        if meetlat.get("domein_filter") == "alles":
            waarschuwingen.append("gemengde ronde (--domein alles): NL financieel en internationaal door "
                                  "elkaar; ons scherm is dan niet uitsluitend tegen zijn eigen categorie gelegd")
    for w in sleutel.get("waarschuwingen", []) or []:
        if w not in waarschuwingen:
            waarschuwingen.append(w)
    ocr = sleutel.get("ocr") or {}
    if ocr.get("beelden_met_lage_dekking"):
        waarschuwingen.append("weinig OCR-tekst gelezen in beelden "
                              + ", ".join(ocr["beelden_met_lage_dekking"]) + ": blindering daar minder zeker")

    viewports = sleutel.get("viewports", {})
    uitslagen: dict[str, ViewportUitslag] = {}
    for vp, vdata in viewports.items():
        items = items_uit_sleutel(vdata)
        pad = csv_per_viewport.get(vp)
        scores, meldingen = (None, [])
        if pad is not None and Path(pad).exists():
            scores, meldingen = lees_csv(Path(pad))
        u = analyseer_viewport(vp, items, scores, meldingen, drempels)
        # opmerkingen waarin de beoordelaar zelf een bron noemt
        if scores:
            namen = {_vouw(i.bron_naam.split(" ")[0]) for i in items if i.soort in ("comp", "anker")}
            namen = {n for n in namen if len(n) >= 4}
            genoemd = []
            for l, rec in scores.items():
                op = _vouw(rec.get("opmerking", ""))
                if op and (any(n in op for n in namen) or "decoy" in op):
                    genoemd.append(l)
            if genoemd:
                u.waarschuwingen.append(f"de beoordelaar noemt zelf een bron of 'decoy' in de opmerking "
                                        f"bij {', '.join(genoemd[:8])}: de blindering is daar mogelijk doorbroken")
        uitslagen[vp] = u

    ronde_geldig = (not globaal_ongeldig and not niet_bruikbaar
                    and bool(uitslagen) and all(u.geldig for u in uitslagen.values()))
    verdict = ("NIET-BRUIKBAAR-VOOR-OORDEEL" if niet_bruikbaar
               else "GELDIG" if ronde_geldig else "ONGELDIG")
    redenen = list(globaal_ongeldig)
    if niet_bruikbaar:
        redenen = (meetlat.get("redenen_niet_bruikbaar") or ["testronde"]) + redenen
    for vp, u in uitslagen.items():
        redenen += [f"[{vp}] {r}" for r in u.redenen_ongeldig]
    if not uitslagen:
        redenen.append("de sleutel bevat geen viewports")
    winst_desktop = {}
    for vp, u in uitslagen.items():
        winst_desktop[vp] = bool(ronde_geldig and u.geldig and u.conclusie.get("boven_decoys"))
    vormen: dict[str, set[str]] = {}
    for vp, vdata in viewports.items():
        for it in items_uit_sleutel(vdata):
            vormen.setdefault(it.manifest_vorm or "onbekend (sleutel zonder vormveld)", set()).add(
                f"{it.bron_naam} ({SOORT_LABEL.get(it.soort, it.soort)})")
    return {
        "verdict": verdict,
        "geldig": ronde_geldig,
        "redenen_ongeldig": redenen,
        "winst_boven_decoys": {vp: (w if ronde_geldig else False) for vp, w in winst_desktop.items()},
        "waarschuwingen": waarschuwingen,
        "drempels": drempels,
        "sleutelstatus": status_sleutel,
        "ocr_dekking": ocr.get("dekking"),
        "manifestvormen": {v: sorted(n) for v, n in sorted(vormen.items())},
        "soort_scherm_familie": {x: familie(x) for x in sorted(
            {b.soort_scherm for u in uitslagen.values() for b in u.bronnen if b.soort_scherm})},
        "viewports": {vp: {
            "geldig": u.geldig, "redenen_ongeldig": u.redenen_ongeldig, "waarschuwingen": u.waarschuwingen,
            "controles": u.controles, "aantal_beelden": u.aantal_labels,
            "bronnen": [{"soort": b.soort, "naam": b.naam, "kwaliteit": b.kwaliteit, "gemiddelde": b.gem,
                         "soort_scherm": b.soort_scherm or "onbekend", "manifest_vorm": b.manifest_vorm or "onbekend",
                         "per_criterium": b.per_criterium, "aantal_beelden": len(b.labels)}
                        for b in u.bronnen],
            "per_soort_scherm": u.per_soort,
            "maskers_vs_score": u.maskers_vs_score,
            "per_criterium_totaal": u.per_criterium_totaal,
            "conclusie": u.conclusie if (ronde_geldig and u.geldig) else {},
            "conclusie_ter_informatie": u.conclusie,
        } for vp, u in uitslagen.items()},
        "_uitslagen": uitslagen,          # voor de tekstweergave; niet in de JSON
    }


# ---------------------------------------------------------------------------
# Weergave
# ---------------------------------------------------------------------------
SOORT_LABEL = {"comp": "comp", "ours": "ONS", "decoy": "decoy", "anker": "ANKER"}


def maak_tekst(res: dict[str, Any], ronde: str) -> str:
    r: list[str] = []
    r.append(f"BLIND A/B-RAPPORT  ronde {ronde}")
    r.append("=" * 72)
    r.append(f"OORDEEL: {res['verdict']}")
    if res["verdict"] != "GELDIG":
        r.append("GEEN CONCLUSIE MOGELIJK; hieronder staat alleen wat er aan de hand is. "
                 "Er wordt geen winst gemeld.")
        for x in res["redenen_ongeldig"]:
            r.append(f"  - {x}")
    for w in res["waarschuwingen"]:
        r.append(f"  ! {w}")
    if res.get("ocr_dekking"):
        r.append(f"  blindering: {res['ocr_dekking']}")
    uitslagen: dict[str, ViewportUitslag] = res["_uitslagen"]
    for vp, u in uitslagen.items():
        r.append("")
        r.append(f"--- {vp} ({u.aantal_labels} beelden): {'GELDIG' if u.geldig else 'ONGELDIG'}")
        for c in u.controles:
            teken = {True: "ok   ", False: "FOUT ", None: "n.v.t"}[c["ok"]]
            r.append(f"  [{teken}] {c['tekst']}")
        for w in u.waarschuwingen:
            r.append(f"  ! {w}")
        if u.bronnen:
            r.append("  Rangorde (gemiddelde van de vijf criteria, 1-5):")
            r.append(f"   {'#':>2} {'bron':34} {'soort':7} {'gem':>5}  "
                     + " ".join(f"{CRITERIUM_NAMEN[c][:5]:>5}" for c in CRITERIA) + "  soort scherm")
            for k, b in enumerate(u.bronnen, 1):
                extra = f" ({b.kwaliteit})" if b.kwaliteit else ""
                r.append(f"   {k:>2} {(b.naam[:30] + extra)[:34]:34} {SOORT_LABEL[b.soort]:7} "
                         f"{_f(b.gem):>5}  " + " ".join(f"{_f(b.per_criterium[c]):>5}" for c in CRITERIA)
                         + f"  {b.soort_scherm or 'onbekend'}")
            r.append("   alle beelden: " + ", ".join(
                f"{CRITERIUM_NAMEN[c]} {_f(u.per_criterium_totaal[c])}" for c in CRITERIA))
        if u.per_soort:
            r.append("  Per soort scherm (gemiddelde van de vijf criteria):")
            for ps in u.per_soort:
                delen = []
                for rol, g in ps["rollen"].items():
                    delen.append(f"{SOORT_LABEL.get(rol, rol)} n={g['aantal_bronnen']} gem {_f(g['gemiddelde'])}"
                                 + (f" ({_f(g['min'])}-{_f(g['max'])})" if g["aantal_bronnen"] > 1 else ""))
                r.append(f"   {ps['soort_scherm']} [{ps['familie']}]: " + "; ".join(delen))
        c = u.conclusie
        if u.geldig and res["geldig"]:
            r.append("  Uitkomst (geldig):")
            if "boven_decoys" in c:
                txt = ("BOVEN" if c["boven_decoys"] else "ONDER" if c["onder_decoys"] else "GELIJK AAN (binnen ruis)")
                r.append(f"   - ons scherm ({_f(c['ons_gemiddelde'])}) eindigt {txt} de decoys "
                         f"(beste decoy {c['beste_decoy']['naam']} {_f(c['beste_decoy']['gemiddelde'])}, "
                         f"marge {'+' if c['marge_op_beste_decoy'] >= 0 else ''}{_f(c['marge_op_beste_decoy'])})")
            for e in c.get("vergelijking_met_comps", []):
                if e.get("aantal_comps"):
                    buiten = e["buiten_vergelijking"]
                    r.append(f"   - t.o.v. vergelijkbare comps ({e['familie']}: {', '.join(e['soorten_vergelijkbaar'])}; "
                             f"{e['aantal_comps']} bronnen): ons {e['ons_soort']} {_f(e['ons_gemiddelde'])}, rang "
                             f"{e['rang']} van {e['aantal_comps'] + 1}, comps-mediaan {_f(e['comps_mediaan'])}; "
                             f"{'OP' if e['op_niveau'] else 'ONDER'} het niveau van die comps"
                             + (f"; buiten de vergelijking gelaten: "
                                + ", ".join(f"{k} {v}x" for k, v in buiten.items()) if buiten else ""))
                else:
                    r.append(f"   - t.o.v. de comps: GEEN uitspraak ({e['ons_soort']}): {e.get('reden', '')}")
            if "beste_anker" in c:
                r.append(f"   - het anker ({c['beste_anker']['naam']}, {_f(c['beste_anker']['gemiddelde'])}) "
                         "staat bovenaan: de beoordelaar heeft dus een werkende smaak")
        elif u.conclusie:
            r.append("  (ter informatie, GEEN conclusie) ons scherm: "
                     f"{_f(c.get('ons_gemiddelde'))}")
    if res.get("manifestvormen"):
        r.append("")
        r.append("Manifestvormen (uit welke vorm elke bron kwam):")
        for vorm, namen in res["manifestvormen"].items():
            r.append(f"  {vorm}: " + ", ".join(namen[:8]) + (f" (+{len(namen) - 8})" if len(namen) > 8 else ""))
    r.append("")
    r.append("Drempels: " + ", ".join(f"{k}={v}" for k, v in res["drempels"].items()))
    return "\n".join(r)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Rapport over een ingevulde blinde A/B-ronde")
    p.add_argument("--ronde", help="naam van de ronde (zoals in de sleutel)")
    p.add_argument("--uit", default="renders/ab", help="map met _sleutel.json en de rondes")
    p.add_argument("--sleutel", default=None, help="pad naar _sleutel.json (standaard <uit>/_sleutel.json)")
    p.add_argument("--beoordeling", nargs="*", default=[], metavar="VIEWPORT=CSV",
                   help="CSV per viewport, bijv. desktop=pad.csv (standaard <uit>/<ronde>/<viewport>/beoordeling.csv)")
    p.add_argument("--json", default=None, help="schrijf het oordeel ook als JSON naar dit pad")
    p.add_argument("--zelftest", action="store_true")
    args = p.parse_args(argv)

    if args.zelftest:
        return zelftest()
    if not args.ronde:
        p.error("--ronde is verplicht")

    uit = Path(args.uit) if Path(args.uit).is_absolute() else PROJECT / args.uit
    sleutelpad = Path(args.sleutel) if args.sleutel else uit / "_sleutel.json"
    if not sleutelpad.exists():
        print(f"FOUT: sleutel {sleutelpad} bestaat niet.")
        return 2
    try:
        sleutel = lees_sleutel(sleutelpad, args.ronde)
    except (KeyError, ValueError) as e:
        print(f"FOUT: {e}")
        return 2
    csvs: dict[str, Path | None] = {}
    for vp in sleutel.get("viewports", {}):
        csvs[vp] = uit / args.ronde / vp / "beoordeling.csv"
    for opgave in args.beoordeling:
        if "=" not in opgave:
            print(f"FOUT: --beoordeling verwacht VIEWPORT=PAD, kreeg {opgave!r}")
            return 2
        vp, pad = opgave.split("=", 1)
        csvs[vp.strip()] = Path(pad)
    if not any(pad and Path(pad).exists() for pad in csvs.values()):
        print("FOUT: geen enkele beoordeling.csv gevonden: " + ", ".join(str(v) for v in csvs.values()))
        return 2
    try:
        res = beoordeel_ronde(sleutel, csvs)
    except ValueError as e:
        print(f"FOUT: {e}")
        return 2
    print(maak_tekst(res, args.ronde))
    if args.json:
        out = {k: v for k, v in res.items() if not k.startswith("_")}
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if res["geldig"] else 1


# ---------------------------------------------------------------------------
# Zelftest: een gefingeerde ronde
# ---------------------------------------------------------------------------
def _demo_sleutel() -> dict:
    def it(label, naam, soort, kw=""):
        return {"label": label, "bron_naam": naam, "soort": soort, "kwaliteit": kw,
                "is_decoy": soort == "decoy", "is_ons": soort == "ours", "is_anker": soort == "anker"}
    items = [it("A", "Anker", "anker"), it("B", "Ons", "ours")]
    for k, n in enumerate(("Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot")):
        items.append(it(chr(ord("C") + k), n, "comp"))
    items += [it("I", "Decoy zeer zwak", "decoy", "zeer_zwak"), it("J", "Decoy matig", "decoy", "matig")]
    return {"script_versie": "2.0.0",
            "meetlat": {"bruikbaar_voor_oordeel": True, "status": "BRUIKBAAR", "domein_filter": "nl_financieel"},
            "hoogte_eigenschap": {"desktop": {"unieke_hoogtes": 1}},
            "viewports": {"desktop": {"items": items}}}


def _demo_csv(waarden: dict[str, tuple[int, int, int, int, int] | None]) -> str:
    regels = ["label,hierarchie_1_5,typografie_1_5,ritme_witruimte_1_5,consistentie_1_5,totaalindruk_1_5,opmerking"]
    for l, w in waarden.items():
        regels.append(f"{l}," + (",".join(str(x) for x in w) if w else ",,,,") + ",")
    return "\n".join(regels) + "\n"


def zelftest() -> int:
    fouten: list[str] = []

    def draai(sleutel, waarden) -> dict:
        with tempfile.TemporaryDirectory() as td:
            pad = Path(td) / "b.csv"
            pad.write_text(_demo_csv(waarden), encoding="utf-8")
            return beoordeel_ronde(sleutel, {"desktop": pad})

    def rij(v):
        return (v, v, v, v, v)

    goed = {"A": rij(5), "B": rij(4), "C": (4, 4, 3, 4, 4), "D": (3, 4, 3, 3, 3), "E": rij(4),
            "F": (3, 3, 3, 3, 3), "G": (2, 3, 3, 3, 3), "H": (3, 2, 3, 3, 3),
            "I": rij(1), "J": (2, 2, 2, 2, 2)}
    r = draai(_demo_sleutel(), goed)
    print(f"  gezonde ronde: {r['verdict']}")
    if r["verdict"] != "GELDIG":
        fouten.append(f"gezonde ronde is niet geldig: {r['redenen_ongeldig']}")
    r = draai(_demo_sleutel(), {l: rij(3) for l in goed})
    print(f"  alles gelijk: {r['verdict']}")
    if r["verdict"] != "ONGELDIG" or any(r["winst_boven_decoys"].values()):
        fouten.append("alles gelijk wordt niet als ONGELDIG zonder winst gemeld")
    ondersteboven = dict(goed)
    ondersteboven["A"] = rij(1)
    r = draai(_demo_sleutel(), ondersteboven)
    print(f"  anker onderaan: {r['verdict']}")
    if r["verdict"] != "ONGELDIG":
        fouten.append("anker onderaan wordt niet als ONGELDIG gemeld")
    ontbrekend = dict(goed)
    ontbrekend["C"] = None
    r = draai(_demo_sleutel(), ontbrekend)
    print(f"  ontbrekende cellen: {r['verdict']}")
    if r["verdict"] != "ONGELDIG":
        fouten.append("ontbrekende cellen worden niet als ONGELDIG gemeld")
    for f in fouten:
        print("ZELFTEST FOUT:", f)
    print("ZELFTEST:", "ok" if not fouten else f"{len(fouten)} fout(en)")
    return 0 if not fouten else 1


if __name__ == "__main__":
    sys.exit(main())
