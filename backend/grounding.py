"""
Citeerbewaker. Dit is de module die het portaal door de criticus heen moet slepen.

De criticus doodt vier dingen: verzonnen feit, niet-citeerbare bron, foute
verzekeringslogica, geen bruikbare vervolgstap. Deze module adresseert de eerste twee
MECHANISCH in plaats van door het model netjes te vragen.

Werking: elke verwijzing die het model uitspreekt (wetsartikel, Kifid-uitspraaknummer,
polisclausule) wordt teruggezocht in de documenten die DAADWERKELIJK zijn opgehaald.
Een verwijzing die daar niet in staat is per definitie niet-citeerbaar en wordt
gemarkeerd als ONGEFUNDEERD - ook als hij toevallig zou kloppen. Beter een terechte
bewering onderdrukken dan een onterechte doorlaten.
"""
import re
from typing import List, Dict, Tuple

# 'art. 4:23', 'artikel 7:958 lid 5', '4:9 Wft', '86c BGfo'
RE_ARTIKEL = re.compile(r"\b(?:art(?:ikel)?\.?\s*)?(\d+:\d+[a-z]?|\d+[a-z])\b(?:\s*lid\s*(\d+))?", re.I)
# Kifid: '2024-0123', 'uitspraak 2023-456'
RE_KIFID = re.compile(r"\b(20\d{2}-\d{3,5})\b")
# clausule: 'art. 5.2', 'artikel 3.1.4'
RE_CLAUSULE = re.compile(r"\b(?:art(?:ikel)?\.?\s*)(\d+(?:\.\d+){1,3})\b", re.I)


def _wetgeving_sleutels(docs: List[Dict]) -> set:
    s = set()
    for d in docs:
        a = str(d.get("artikel") or "").strip().lower()
        if a:
            s.add(a)
            s.add(a.replace("art.", "").replace("artikel", "").strip())
    return {x for x in s if x}


def _kifid_sleutels(docs: List[Dict]) -> set:
    return {str(d.get("uitspraaknummer") or "").strip() for d in docs if d.get("uitspraaknummer")}


_NUMMER = re.compile(r"\d+(?:\.\d+)+")


def _clausule_sleutels(docs: List[Dict]) -> set:
    """
    Een clausule wordt geciteerd als 'art. 11.6', maar staat in het corpus als 'Woonhuis art. 11.6',
    'art. 2.16 sub f' of 'par. 4.2'. Zonder het kale nummer als sleutel werd een terechte verwijzing
    naar een opgehaalde clausule als 'niet in corpus' aangemerkt. Alleen documenten die voor DEZE
    vraag zijn opgehaald tellen mee, dus een nummer dat in twee producten voorkomt wordt hier niet
    ruimer dan de opgehaalde bronnen.
    """
    s = set()
    for d in docs:
        c = str(d.get("clausule_id") or "").strip().lower()
        if c:
            s.add(c)
            s.add(re.sub(r"^art(?:ikel)?\.?\s*", "", c).strip())
            s.update(_NUMMER.findall(c))
    return {x for x in s if x}


def controleer(antwoord: str, opgehaald: Dict[str, List[Dict]]) -> Dict:
    """
    antwoord  : de door het model gegenereerde tekst
    opgehaald : {'wetgeving': [...], 'kifid': [...], 'polisvoorwaarden': [...]}
                uitsluitend de documenten die ECHT zijn opgehaald voor deze vraag.

    Geeft terug: gefundeerde en ongefundeerde verwijzingen, plus een oordeel.
    """
    wet = _wetgeving_sleutels(opgehaald.get("wetgeving", []))
    kif = _kifid_sleutels(opgehaald.get("kifid", []))
    cla = _clausule_sleutels(opgehaald.get("polisvoorwaarden", []))

    gefundeerd, ongefundeerd = [], []

    for m in RE_KIFID.finditer(antwoord):
        nr = m.group(1)
        (gefundeerd if nr in kif else ongefundeerd).append(
            {"soort": "kifid", "verwijzing": nr, "positie": m.start()})

    for m in RE_ARTIKEL.finditer(antwoord):
        art = m.group(1).lower()
        if ":" not in art:                      # '86c' -> alleen als BGfo-achtige sleutel
            if art in wet:
                gefundeerd.append({"soort": "wetsartikel", "verwijzing": art, "positie": m.start()})
            continue
        (gefundeerd if art in wet else ongefundeerd).append(
            {"soort": "wetsartikel", "verwijzing": art, "positie": m.start()})

    for m in RE_CLAUSULE.finditer(antwoord):
        c = m.group(1).lower()
        (gefundeerd if c in cla else ongefundeerd).append(
            {"soort": "polisclausule", "verwijzing": c, "positie": m.start()})

    # dedupliceer op (soort, verwijzing)
    def _uniek(rows):
        seen, out = set(), []
        for r in rows:
            k = (r["soort"], r["verwijzing"])
            if k not in seen:
                seen.add(k)
                out.append(r)
        return out

    gefundeerd, ongefundeerd = _uniek(gefundeerd), _uniek(ongefundeerd)

    if ongefundeerd:
        oordeel = "ONGEFUNDEERD"
    elif gefundeerd:
        oordeel = "GEFUNDEERD"
    else:
        oordeel = "GEEN_VERWIJZINGEN"

    return {
        "oordeel": oordeel,
        "gefundeerd": gefundeerd,
        "ongefundeerd": ongefundeerd,
        "bronnen_beschikbaar": {"wetgeving": len(wet), "kifid": len(kif), "polisclausules": len(cla)},
    }


def maskeer(antwoord: str, controle: Dict) -> str:
    """
    Zet een zichtbare markering bij elke ongefundeerde verwijzing. We verwijderen de
    zin niet stilzwijgend: de adviseur moet ZIEN dat het model iets beweerde dat niet
    onderbouwd is. Onzichtbaar filteren zou het probleem verbergen in plaats van tonen.
    """
    if not controle.get("ongefundeerd"):
        return antwoord
    uit = antwoord
    for r in sorted(controle["ongefundeerd"], key=lambda x: -x["positie"]):
        v = r["verwijzing"]
        uit = re.sub(r"(?<![\w>])" + re.escape(v) + r"(?![\w<])",
                     f"{v} ⚠️[niet in corpus]", uit, count=1)
    return uit


def systeemprompt(context_blok: str) -> str:
    """
    De systeemprompt is de tweede verdedigingslinie, niet de eerste.
    De eerste is controleer(); deze prompt verlaagt alleen hoe vaak die moet ingrijpen.
    """
    return (
        "Je bent een Nederlandse assurantie-expert die een ervaren adviseur ondersteunt.\n\n"
        "ABSOLUTE REGELS:\n"
        "1. Je mag UITSLUITEND feiten noemen die letterlijk in de onderstaande bronnen staan.\n"
        "2. Noem NOOIT een wetsartikel, Kifid-uitspraaknummer of polisclausule die niet in de "
        "bronnen voorkomt. Elke verwijzing wordt automatisch gecontroleerd.\n"
        "3. Staat het antwoord niet in de bronnen? Zeg dan exact: 'Dit staat niet in de "
        "geraadpleegde bronnen.' en benoem wat de adviseur zou moeten opvragen.\n"
        "4. Reken NIET zelf. Bedragen worden apart berekend en aangeleverd.\n"
        "5. Sluit ALTIJD af met een concrete vervolgstap voor de adviseur.\n"
        "6. Schrijf in zakelijk Nederlands, bondig, geen disclaimers vooraf.\n\n"
        f"BRONNEN:\n{context_blok}\n"
    )
