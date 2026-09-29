"""
Deterministische rekenkern voor Nederlandse schade- en assurantieberekeningen.

ONTWERPPRINCIPE (zie state.json -> architecture_decision):
Geen enkele berekening loopt via het taalmodel. Het model formuleert alleen;
de cijfers komen hier vandaan. Daarmee is "wrong Dutch insurance logic"
structureel uitgesloten in plaats van hoopvol vermeden.

CITEER-OF-WEIGER:
Elke uitkomst draagt een `grondslag` (wetsartikel-verwijzing). Die verwijzing wordt
bij het opstarten gevalideerd tegen het corpus (zie citatie.py). Staat het artikel niet
in het corpus, dan mag de app de bewering NIET als onderbouwd tonen.
"""

from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional, List


def _eur(x) -> Decimal:
    """Afronden op hele centen, bankierszorg: half naar boven."""
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Stap:
    """Eén navolgbare rekenstap. De adviseur moet dit kunnen narekenen op papier."""
    omschrijving: str
    formule: str
    uitkomst: Optional[Decimal] = None
    eenheid: str = "EUR"                                 # "EUR" | "%" | "" (datum of tekst)


@dataclass
class Uitkomst:
    onderwerp: str
    bedrag: Optional[Decimal]
    stappen: List[Stap] = field(default_factory=list)
    grondslag: List[str] = field(default_factory=list)   # bv. ["BW:7:958:5"]
    toelichting: str = ""
    volgende_stap: str = ""                              # criticus eist een bruikbare vervolgstap
    waarschuwingen: List[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)          # gestructureerde uitkomst voor de UI

    def to_dict(self):
        d = asdict(self)
        d["bedrag"] = None if self.bedrag is None else str(_eur(self.bedrag))
        for s in d["stappen"]:
            s["uitkomst"] = None if s["uitkomst"] is None else str(_eur(s["uitkomst"]))
        return d


# ---------------------------------------------------------------- onderverzekering

def evenredigheidsbeginsel(verzekerde_som, werkelijke_waarde, schade,
                           eigen_risico=0, bereddingskosten=0) -> Uitkomst:
    """
    Onderverzekering: is de verzekerde som lager dan de waarde van het verzekerd
    belang, dan vergoedt de verzekeraar naar evenredigheid.

    uitkering = schade * (verzekerde som / werkelijke waarde), daarna eigen risico eraf.

    Bereddingskosten (art. 7:957) volgen een eigen regime in art. 7:959 BW:
      lid 1 - zij komen ten laste van de verzekeraar OOK als daardoor de verzekerde
              som wordt overschreden;
      lid 2 - MAAR bij onderverzekering worden zij "met overeenkomstige toepassing van
              artikel 958 lid 5" eveneens naar evenredigheid verminderd.
    Die twee leden worden vaak door elkaar gehaald: dat bereddingskosten boven de
    verzekerde som uit mogen betekent NIET dat zij buiten de evenredigheidsbreuk vallen.
    """
    vs, ww = Decimal(str(verzekerde_som)), Decimal(str(werkelijke_waarde))
    sch, er = Decimal(str(schade)), Decimal(str(eigen_risico))
    bk = Decimal(str(bereddingskosten))

    u = Uitkomst(onderwerp="Onderverzekering (evenredigheidsbeginsel)", bedrag=None)

    if ww <= 0:
        u.waarschuwingen.append("Werkelijke waarde is nul of negatief; breuk niet te bepalen.")
        u.volgende_stap = "Stel eerst de herbouw-/vervangingswaarde vast, desnoods via een taxatie."
        return u

    if vs >= ww:
        u.stappen.append(Stap("Geen onderverzekering: verzekerde som dekt de waarde",
                              f"{_eur(vs)} >= {_eur(ww)}"))
        basis = min(sch, vs)
        u.grondslag = ["BW:7:955:1"]
        if sch > vs:
            u.waarschuwingen.append(
                f"Schade ({_eur(sch)}) overstijgt de verzekerde som ({_eur(vs)}); "
                "de uitkering is gemaximeerd op de verzekerde som.")
    else:
        breuk = vs / ww
        u.stappen.append(Stap("Evenredigheidsbreuk bepalen",
                              f"{_eur(vs)} / {_eur(ww)}", breuk * 100, "%"))
        basis = sch * breuk
        u.stappen.append(Stap("Schade naar evenredigheid",
                              f"{_eur(sch)} x ({_eur(vs)} / {_eur(ww)})", basis))
        u.grondslag = ["BW:7:958:5"]
        u.waarschuwingen.append(
            f"Onderverzekering van {_eur((1 - breuk) * 100)}%. "
            "Controleer of een garantie tegen onderverzekering van toepassing is; "
            "die zet de evenredigheidsregel opzij.")

    na_er = basis - er
    if er > 0:
        u.stappen.append(Stap("Eigen risico in mindering", f"{_eur(basis)} - {_eur(er)}", na_er))
    if na_er < 0:
        u.waarschuwingen.append("Eigen risico overstijgt de berekende uitkering; uitkering is nihil.")
        na_er = Decimal("0")

    totaal = na_er
    if bk > 0:
        onderverzekerd = vs < ww
        if onderverzekerd:
            bk_verg = bk * (vs / ww)
            u.stappen.append(Stap(
                "Bereddingskosten eveneens naar evenredigheid verminderd "
                "(art. 7:959 lid 2 verwijst naar art. 7:958 lid 5)",
                f"{_eur(bk)} x ({_eur(vs)} / {_eur(ww)})", bk_verg))
        else:
            bk_verg = bk
            u.stappen.append(Stap("Bereddingskosten volledig vergoed",
                                  f"{_eur(bk)}", bk_verg))
        u.stappen.append(Stap(
            "Bereddingskosten mogen de verzekerde som overschrijden (art. 7:959 lid 1)",
            f"{_eur(na_er)} + {_eur(bk_verg)}", na_er + bk_verg))
        totaal = na_er + bk_verg
        u.grondslag += ["BW:7:957:2", "BW:7:959:1"]
        if onderverzekerd:
            u.grondslag.append("BW:7:959:2")

    u.bedrag = totaal
    u.toelichting = (
        "Bij onderverzekering draagt de verzekerde het niet-verzekerde deel zelf. "
        "De breuk wordt toegepast op de schade, niet op de verzekerde som."
    )
    u.volgende_stap = (
        "Leg de herbouwwaarde vast met een recente taxatie of herbouwwaardemeter en "
        "stel de verzekerde som bij. Controleer of de polis een indexclausule kent."
    )
    return u


# ---------------------------------------------------------------- verjaring

_MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli",
            "augustus", "september", "oktober", "november", "december"]


def _nl(d: date) -> str:
    return f"{d.day} {_MAANDEN[d.month - 1]} {d.year}"


def _dag_erna(d: date) -> date:
    return date.fromordinal(d.toordinal() + 1)


def _dagen(n: int) -> str:
    return f"{n} dag" if abs(n) == 1 else f"{n} dagen"


def _plus_jaren(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:                          # 29 februari -> laatste dag van februari
        return d.replace(year=d.year + n, day=28)


def laatste_dag_termijn(aanvangsgebeurtenis: date) -> date:
    """
    Laatste dag waarop nog kan worden gestuit, bij een termijn van drie jaar die begint met
    "de aanvang van de dag, volgende op die waarop" de gebeurtenis plaatsvond (art. 7:942).

    Afleiding, omdat hier een dag scheelt: de termijn begint op D+1 om 00.00 uur en is drie
    jaar later verstreken, dus op D+1 (drie jaar later) om 00.00 uur. Dat is het einde van de
    dag die in nummer overeenkomt met D. Voorbeeld: bekend op 10 maart 2024 -> laatste dag
    10 maart 2027; per 11 maart 2027 is de vordering verjaard. Een eerdere versie van deze
    functie rekende tot en met 11 maart en gaf de adviseur daarmee één dag te veel.
    """
    return _plus_jaren(aanvangsgebeurtenis, 3)


def verjaring_schadeclaim(datum_bekend: date,
                          datum_stuiting: Optional[date] = None,
                          datum_reactie: Optional[date] = None,
                          aansprakelijkheid: bool = False,
                          peildatum: Optional[date] = None) -> Uitkomst:
    """
    Verjaring van de rechtsvordering tegen de verzekeraar, art. 7:942 BW.

    Lid 1: drie jaar, te rekenen vanaf de aanvang van de dag VOLGEND op die waarop de
           gerechtigde met de opeisbaarheid bekend werd.
    Lid 2: een schriftelijke mededeling waarbij aanspraak op uitkering wordt gemaakt STUIT de
           verjaring. Dan loopt er geen termijn totdat de verzekeraar de aanspraak erkent of
           ondubbelzinnig afwijst; met de dag daarna begint een NIEUWE termijn van drie jaar.
           Een stuiting zonder reactie van de verzekeraar laat dus geen einddatum zien: er
           loopt op dat moment niets.
    Lid 3: bij aansprakelijkheidsverzekering stuit iedere onderhandeling; de nieuwe termijn
           begint na erkenning of na de mededeling dat de onderhandelingen worden afgebroken.

    Een aanspraak die pas na het einde van de hoofdtermijn wordt gedaan, stuit niets meer.
    Ontbreekt de datum van de aanspraak terwijl er wel een reactie is, dan rekent de kern
    voorzichtig met de hoofdtermijn en toont de gunstiger uitkomst alleen als voorwaardelijk.
    """
    peil = peildatum or date.today()
    u = Uitkomst(onderwerp="Verjaring rechtsvordering op de verzekeraar", bedrag=None)
    u.grondslag = ["BW:7:942:1"]
    gebeurtenissen = [{"datum": datum_bekend.isoformat(), "soort": "bekendheid",
                       "label": "Bekend met de opeisbaarheid"}]
    aanspraak_woord = "onderhandeling" if aansprakelijkheid else "schriftelijke aanspraak"
    reactie_woord = ("erkenning of afbreken van de onderhandelingen" if aansprakelijkheid
                     else "erkenning of ondubbelzinnige afwijzing")

    start0 = _dag_erna(datum_bekend)
    eind0 = laatste_dag_termijn(datum_bekend)
    u.stappen.append(Stap(
        "Aanvang hoofdtermijn: de dag volgend op de bekendheid met de opeisbaarheid (lid 1)",
        f"{_nl(datum_bekend)} + 1 dag = {_nl(start0)}", None, ""))
    u.stappen.append(Stap(
        "Hoofdtermijn van drie jaar (lid 1): laatste dag waarop nog kan worden gestuit",
        f"{_nl(start0)} + 3 jaar, het einde van de dag ervoor = {_nl(eind0)}", None, ""))
    gebeurtenissen.append({"datum": eind0.isoformat(), "soort": "einde_hoofdtermijn",
                           "label": "Einde hoofdtermijn"})

    stuit_geldig = False
    if datum_stuiting:
        if datum_stuiting < datum_bekend:
            u.waarschuwingen.append(
                f"De datum van de {aanspraak_woord} ({_nl(datum_stuiting)}) ligt vóór de bekendheid "
                f"({_nl(datum_bekend)}). Controleer de invoer.")
        if datum_stuiting > eind0:
            u.waarschuwingen.append(
                f"De {aanspraak_woord} van {_nl(datum_stuiting)} is gedaan nadat de hoofdtermijn op "
                f"{_nl(eind0)} was verstreken en kon de verjaring niet meer stuiten. Ga na of er "
                "eerder al is gestuit.")
            u.stappen.append(Stap(
                f"De {aanspraak_woord} komt na het einde van de hoofdtermijn: geen stuitende werking",
                f"{_nl(datum_stuiting)} > {_nl(eind0)}", None, ""))
        else:
            stuit_geldig = True
            u.grondslag.append("BW:7:942:3" if aansprakelijkheid else "BW:7:942:2")
            u.stappen.append(Stap(
                f"{aanspraak_woord.capitalize()} binnen de termijn stuit de verjaring "
                f"(lid {'3' if aansprakelijkheid else '2'})",
                f"{_nl(datum_stuiting)} <= {_nl(eind0)}", None, ""))
            gebeurtenissen.append({"datum": datum_stuiting.isoformat(), "soort": "stuiting",
                                   "label": aanspraak_woord.capitalize()})

    eind = eind0                    # de laatste dag die nu geldt; None = er loopt geen termijn
    status_gestuit = False
    alternatief = None              # (laatste dag, voorwaarde) als de aanspraak ontbreekt

    if datum_reactie and datum_reactie < (datum_stuiting or datum_bekend):
        u.waarschuwingen.append(
            f"De {reactie_woord} ({_nl(datum_reactie)}) ligt vóór de "
            f"{aanspraak_woord if datum_stuiting else 'bekendheid'}. Controleer de invoer; "
            "de reactie is niet meegeteld.")
        datum_reactie = None

    if datum_reactie:
        if stuit_geldig:
            nieuw_start = _dag_erna(datum_reactie)
            eind = laatste_dag_termijn(datum_reactie)
            u.stappen.append(Stap(
                f"Na {reactie_woord} begint een NIEUWE termijn van drie jaar; deze vervangt de "
                "oorspronkelijke termijn",
                f"{_nl(datum_reactie)} + 1 dag = {_nl(nieuw_start)}; + 3 jaar, laatste dag = "
                f"{_nl(eind)}", None, ""))
            gebeurtenissen.append({"datum": datum_reactie.isoformat(), "soort": "reactie",
                                   "label": reactie_woord.capitalize()})
            gebeurtenissen.append({"datum": eind.isoformat(), "soort": "einde_nieuwe_termijn",
                                   "label": "Einde nieuwe termijn"})
        elif not datum_stuiting:
            alt = laatste_dag_termijn(datum_reactie)
            voorwaarde = (f"als de schademelding een {aanspraak_woord} was en binnen de "
                          f"hoofdtermijn is gedaan, loopt er een nieuwe termijn tot {_nl(alt)}")
            alternatief = (alt, voorwaarde)
            u.waarschuwingen.append(
                f"Er is een {reactie_woord} ingevuld maar geen datum van de {aanspraak_woord}. "
                "Volgens lid 2 begint de nieuwe termijn pas na een stuitende mededeling; deze "
                f"berekening houdt daarom de hoofdtermijn aan (laatste dag {_nl(eind0)}). "
                f"Voorwaardelijk: {voorwaarde}.")
            gebeurtenissen.append({"datum": datum_reactie.isoformat(), "soort": "reactie",
                                   "label": reactie_woord.capitalize()})
    elif stuit_geldig:
        eind = None
        status_gestuit = True
        u.stappen.append(Stap(
            f"Zolang de verzekeraar de aanspraak niet erkent of ondubbelzinnig afwijst, begint "
            f"er geen nieuwe termijn (lid {'3' if aansprakelijkheid else '2'}); de verjaring is gestuit",
            "geen lopende termijn", None, ""))

    # --- status en toelichting
    if status_gestuit:
        status, dagen = "GESTUIT", None
        u.toelichting = (
            f"Op peildatum {_nl(peil)} is de verjaring gestuit door de {aanspraak_woord} van "
            f"{_nl(datum_stuiting)}. Er loopt nu geen termijn: een nieuwe termijn van drie jaar "
            f"begint pas op de dag na {reactie_woord} door de verzekeraar.")
        u.volgende_stap = (
            "Vraag de verzekeraar schriftelijk om een reactie en leg vast op welke datum de "
            "aanspraak wordt erkend of ondubbelzinnig afgewezen: dan begint de nieuwe termijn. "
            "Bewaar het verzendbewijs van de stuitende mededeling.")
    else:
        dagen = (eind - peil).days
        if dagen < 0:
            status = "VERJAARD"
            if alternatief and alternatief[0] >= peil:
                status = "ONZEKER"
        else:
            status = "LOOPT"
        if status == "LOOPT":
            u.toelichting = (
                f"Op peildatum {_nl(peil)} is de vordering nog niet verjaard. De laatste dag om te "
                f"stuiten is {_nl(eind)}; per {_nl(_dag_erna(eind))} is de vordering verjaard "
                f"({'vandaag is de laatste dag' if dagen == 0 else f'{_dagen(dagen)} resterend'}).")
            u.volgende_stap = (
                "Stuit de verjaring per aangetekende brief met een ondubbelzinnige aanspraak op "
                "uitkering, ruim vóór de laatste dag, en bewaar het verzendbewijs."
                if not datum_stuiting else
                "Houd de einddatum in het dossier bij en stuit tijdig opnieuw, met verzendbewijs, "
                "als de verzekeraar niet reageert of de zaak nog loopt.")
            if dagen < 90:
                u.waarschuwingen.append(
                    f"Nog maar {_dagen(dagen)} tot de laatste dag ({_nl(eind)}): handel met spoed."
                    if dagen > 0 else
                    f"Vandaag ({_nl(eind)}) is de laatste dag om te stuiten: verstuur de aanspraak "
                    "vandaag nog aantoonbaar.")
        elif status == "ONZEKER":
            u.toelichting = (
                f"Op peildatum {_nl(peil)} is de hoofdtermijn verstreken op {_nl(eind)}. Of de "
                f"vordering verjaard is, hangt af van één feit dat hier ontbreekt: "
                f"{alternatief[1]}.")
            u.volgende_stap = (
                f"Zoek de datum van de eerste schriftelijke aanspraak op (schademelding, brief of "
                f"e-mail) en bepaal of die vóór {_nl(eind)} is gedaan; vul die datum in en toets opnieuw.")
        else:
            u.toelichting = (
                f"Op peildatum {_nl(peil)} is de vordering VERJAARD: de laatste dag om te stuiten "
                f"was {_nl(eind)} ({_dagen(abs(dagen))} geleden).")
            u.volgende_stap = (
                "Ga na of er eerder rechtsgeldig is gestuit; zonder stuiting is de vordering niet "
                "meer afdwingbaar. Onderzoek subsidiair of de adviseur zelf aansprakelijk is voor "
                "het laten verlopen van de termijn.")

    if not aansprakelijkheid:
        u.waarschuwingen.append(
            "Bij een aansprakelijkheidsverzekering geldt een afwijkende stuitingsregel: iedere "
            "onderhandeling stuit de termijn (art. 7:942 lid 3). Zet de aansprakelijkheidsschakelaar "
            "aan als dat hier speelt.")
    u.waarschuwingen.append(
        "Van art. 7:942 kan niet ten nadele van de verzekeringnemer of de tot uitkering gerechtigde "
        "worden afgeweken (art. 7:943 lid 2). Controleer daarnaast de polisvoorwaarden op een "
        "reactietermijn na een beslissing van de verzekeraar.")
    u.waarschuwingen.append(
        "De datum van bekendheid met de opeisbaarheid is een feitelijke vaststelling. Bij twijfel: "
        "reken met de vroegste aannemelijke datum.")
    u.grondslag.append("BW:7:943:2")

    u.details = {
        "status": status,
        "peildatum": peil.isoformat(),
        "hoofdtermijn_laatste_dag": eind0.isoformat(),
        "laatste_dag": eind.isoformat() if eind else None,
        "eerste_verjaarde_dag": _dag_erna(eind).isoformat() if eind else None,
        "dagen_resterend": dagen,
        "gebeurtenissen": sorted(gebeurtenissen, key=lambda e: e["datum"]),
        "aansprakelijkheid": aansprakelijkheid,
        "voorwaardelijk_alternatief": (
            {"laatste_dag": alternatief[0].isoformat(), "voorwaarde": alternatief[1]}
            if alternatief else None),
    }
    return u


# ---------------------------------------------------------------- dagwaarde

def nieuwwaarde_of_dagwaarde(nieuwwaarde, ouderdom_jaren, levensduur_jaren,
                             dagwaarde_drempel_pct=40) -> Uitkomst:
    """
    Veel inboedel-/opstalpolissen keren nieuwwaarde uit, TENZIJ de dagwaarde onder een
    drempel (vaak 40% van de nieuwwaarde) is gezakt; dan geldt dagwaarde.
    De drempel is polisafhankelijk en wordt daarom als parameter meegegeven,
    niet hard aangenomen.
    """
    nw = Decimal(str(nieuwwaarde))
    u = Uitkomst(onderwerp="Nieuwwaarde versus dagwaarde", bedrag=None)

    if levensduur_jaren <= 0:
        u.waarschuwingen.append("Levensduur moet groter dan nul zijn.")
        return u

    rest = max(Decimal("0"), Decimal(str(levensduur_jaren)) - Decimal(str(ouderdom_jaren)))
    factor = rest / Decimal(str(levensduur_jaren))
    dagwaarde = nw * factor
    drempel = nw * Decimal(str(dagwaarde_drempel_pct)) / Decimal("100")

    u.stappen.append(Stap("Restlevensduur", f"{levensduur_jaren} - {ouderdom_jaren} = {rest} jaar"))
    u.stappen.append(Stap("Dagwaarde", f"{_eur(nw)} x ({rest}/{levensduur_jaren})", dagwaarde))
    u.stappen.append(Stap(f"Drempel ({dagwaarde_drempel_pct}% van nieuwwaarde)",
                          f"{_eur(nw)} x {dagwaarde_drempel_pct}%", drempel))

    if dagwaarde < drempel:
        u.bedrag = dagwaarde
        u.toelichting = "Dagwaarde ligt onder de polisdrempel; er wordt op dagwaarde afgewikkeld."
        u.volgende_stap = ("Controleer de exacte drempelclausule in de polisvoorwaarden; "
                           "die verschilt per verzekeraar en per productversie.")
    else:
        u.bedrag = nw
        u.toelichting = "Dagwaarde ligt boven de polisdrempel; er wordt op nieuwwaarde afgewikkeld."
        u.volgende_stap = "Vraag een aankoopbewijs of vervangingsofferte op ter onderbouwing."
    u.waarschuwingen.append(
        "De drempel en de gehanteerde levensduur volgen uit de polisvoorwaarden, niet uit de wet. "
        "Verifieer beide in het clausulecorpus voordat je dit aan de klant meldt.")
    return u


# ---------------------------------------------------------------- provisie

# Letterlijk uit art. 86c lid 1 BGfo (corpus, toestand 2026-08-28). Alleen wat daar staat is hier
# een verbod. Al het andere is 'niet genoemd' of 'onbepaald' - nooit stilzwijgend 'toegestaan'.
VERBOD_86C = (
    "betalingsbeschermer",
    "complex product",
    "hypothecair krediet",
    "individuele arbeidsongeschiktheidsverzekering",
    "overlijdensrisicoverzekering",
    "premiepensioenvordering",
    "uitvaartverzekering",
)

# Spreektaal -> de term uit het artikel.
_ALIAS_VERBOD = {
    "hypotheek": "hypothecair krediet",
    "hypothecaire lening": "hypothecair krediet",
    "orv": "overlijdensrisicoverzekering",
    "overlijdensrisico": "overlijdensrisicoverzekering",
    "individuele aov": "individuele arbeidsongeschiktheidsverzekering",
    "aov individueel": "individuele arbeidsongeschiktheidsverzekering",
    "individuele arbeidsongeschiktheid": "individuele arbeidsongeschiktheidsverzekering",
    "uitvaart": "uitvaartverzekering",
    "betalingsbescherming": "betalingsbeschermer",
}

_ONBEPAALD_AOV = (
    "Art. 86c lid 1 noemt uitsluitend de INDIVIDUELE arbeidsongeschiktheidsverzekering. Stel vast "
    "of dit een individuele of een collectieve verzekering is. Voor de collectieve variant volgt uit "
    "art. 86c lid 1 geen verbod; welke regels dan gelden vraagt om een productkwalificatie die niet "
    "in het corpus staat.")
_ONBEPAALD_COMPLEX = (
    "Dit product wordt in art. 86c lid 1 niet bij naam genoemd, maar kan een 'complex product' zijn. "
    "De definitie van complex product staat niet in het corpus; stel de kwalificatie vast voordat "
    "je provisie aanneemt.")
_ONBEPAALD = {
    "arbeidsongeschiktheidsverzekering": _ONBEPAALD_AOV,
    "aov": _ONBEPAALD_AOV,
    "levensverzekering": _ONBEPAALD_COMPLEX,
    "beleggingsverzekering": _ONBEPAALD_COMPLEX,
    "kapitaalverzekering": _ONBEPAALD_COMPLEX,
    "spaarverzekering": _ONBEPAALD_COMPLEX,
    "lijfrente": _ONBEPAALD_COMPLEX,
    "pensioenverzekering": _ONBEPAALD_COMPLEX,
}

# Particuliere schadeverzekeringen die art. 86c lid 1 niet noemt; hier geldt art. 86d.
SCHADE = (
    "autoverzekering", "opstalverzekering", "inboedelverzekering", "woonverzekering",
    "aansprakelijkheidsverzekering", "rechtsbijstandverzekering", "reisverzekering",
    "brandverzekering", "fietsverzekering", "caravanverzekering", "glasverzekering",
    "dierenverzekering", "bromfietsverzekering", "motorverzekering",
)


def classificeer_product(producttype: str):
    """
    Geeft (status, wettelijke_term, uitleg):
      VERBODEN      - het product staat in art. 86c lid 1 BGfo
      SCHADE        - een schadeverzekering die art. 86c niet noemt (art. 86d)
      ONBEPAALD     - kwalificatie volgt niet uit het corpus; de toets weigert een uitspraak
    """
    pt = " ".join((producttype or "").lower().split())
    if pt in VERBOD_86C:
        return "VERBODEN", pt, "Genoemd in art. 86c lid 1 BGfo."
    if pt in _ALIAS_VERBOD:
        term = _ALIAS_VERBOD[pt]
        return "VERBODEN", term, f"'{producttype}' valt onder '{term}', genoemd in art. 86c lid 1 BGfo."
    if pt in _ONBEPAALD:
        return "ONBEPAALD", None, _ONBEPAALD[pt]
    if pt in SCHADE or (pt.endswith("verzekering") and any(s in pt for s in SCHADE)):
        return "SCHADE", None, "Niet genoemd in art. 86c lid 1 BGfo; voor schadeverzekeringen geldt art. 86d."
    return "ONBEPAALD", None, (
        f"Het producttype '{producttype}' is niet herkend. Bepaal eerst of het onder art. 86c lid 1 BGfo "
        "valt (verbod) of een schadeverzekering is (art. 86d).")


def provisie_toets(producttype: str, jaarpremie=0, provisiepercentage=0,
                   directe_beloning=0) -> Uitkomst:
    """
    Toetst of beloning via provisie is toegestaan.

    BGfo art. 86c lid 1: verbod voor een limitatieve lijst producten. BGfo art. 86d: voor
    schadeverzekeringen zijn afsluit- en doorlopende provisie toegestaan MITS de consument kosteloos
    en begrijpelijk is geïnformeerd over bestaan, aard en bedrag (art. 86d lid 1 onder b, art. 86i
    lid 3). Kan het product niet aan een van beide regimes worden toegewezen, dan zegt de toets dat
    en rekent hij het bedrag alleen voorwaardelijk uit.
    """
    status, term, uitleg = classificeer_product(producttype)
    u = Uitkomst(onderwerp="Provisietoets", bedrag=None)
    jp, pct = Decimal(str(jaarpremie or 0)), Decimal(str(provisiepercentage or 0))
    prov = jp * pct / Decimal("100")

    if status == "VERBODEN":
        u.grondslag = ["BGfo:86c:1", "BGfo:86c:2"]
        u.stappen.append(Stap("Toets: valt het product onder het provisieverbod?",
                              f"'{term}' staat in art. 86c lid 1", None, ""))
        if pct > 0:
            u.stappen.append(Stap("Ingevulde provisie (NIET toegestaan voor dit product)",
                                  f"{_eur(jp)} x {pct}%", prov))
            u.waarschuwingen.append(
                "Er is een provisiepercentage ingevuld voor een product onder het provisieverbod. "
                "Dit is een compliance-signaal, geen rekenfout.")
        u.bedrag = _eur(directe_beloning or 0)
        u.stappen.append(Stap("Toegestane beloning: rechtstreeks door de klant verschaft (lid 2 onder a)",
                              "directe beloning door de klant", Decimal(str(directe_beloning or 0))))
        u.toelichting = (
            f"Voor '{producttype}' geldt het provisieverbod van art. 86c lid 1 BGfo. Beloning loopt "
            "via een rechtstreeks met de klant overeengekomen bedrag, niet via de aanbieder.")
        u.volgende_stap = (
            "Leg de directe beloning vast in het dienstverleningsdocument en laat de klant daar "
            "vooraf mee instemmen. Controleer of het bedrag aantoonbaar in verhouding staat tot "
            "de verrichte werkzaamheden: provisie die de klant zelf betaalt is alleen toegestaan "
            "zolang de hoogte niet kennelijk onredelijk is (lid 2 onder a).")
        u.waarschuwingen.append(
            "De overige uitzonderingen van lid 2 (o.a. relatiegeschenken tot € 100 per jaar) zijn "
            "hier niet doorgerekend.")
        u.details = {"status": "VERBODEN", "wettelijke_term": term}
    elif status == "SCHADE":
        u.grondslag = ["BGfo:86d:1", "BGfo:86i:3"]
        u.stappen.append(Stap("Toets: art. 86c lid 1 noemt dit product niet; art. 86d regelt de provisie",
                              f"'{producttype}' is een schadeverzekering", None, ""))
        u.stappen.append(Stap("Provisie over jaarpremie", f"{_eur(jp)} x {pct}%", prov))
        u.bedrag = prov
        u.toelichting = (
            f"Voor '{producttype}' geldt het verbod van art. 86c lid 1 BGfo niet. Art. 86d lid 1 staat "
            "afsluit- en doorlopende provisie toe, mits de consument kosteloos en op begrijpelijke "
            "wijze is geïnformeerd over het bestaan, de aard en het bedrag van de provisie.")
        u.volgende_stap = (
            "Leg vast dat de consument uiterlijk tegelijk met het advies is geïnformeerd over het "
            "bestaan, de aard en het bedrag van de provisie (art. 86i lid 3), en neem de wijze van "
            "beloning op in het dienstverleningsdocument.")
        u.waarschuwingen.append(
            "Art. 86d lid 1 staat alleen de daar genoemde provisievormen toe; andere vormen vallen "
            "erbuiten.")
        u.waarschuwingen.append(
            "Art. 86d geldt voor overeenkomsten aangegaan op of na 1 juli 2024 (lid 4). Voor eerdere "
            "overeenkomsten gold de tekst van 30 juni 2024, die niet in het corpus staat.")
        u.details = {"status": "TOEGESTAAN_MET_TRANSPARANTIE", "wettelijke_term": None}
    else:
        u.grondslag = ["BGfo:86c:1", "BGfo:86d:1"]
        u.stappen.append(Stap("Toets: is vast te stellen onder welk regime het product valt?",
                              "nee: zie toelichting", None, ""))
        if pct > 0 and jp > 0:
            u.stappen.append(Stap("Voorwaardelijk: provisie als het GEEN verboden product blijkt",
                                  f"{_eur(jp)} x {pct}%", prov))
        u.bedrag = None
        u.toelichting = uitleg
        u.volgende_stap = (
            "Stel de kwalificatie van het product vast (art. 86c lid 1 versus art. 86d) en toets "
            "opnieuw. Neem in de tussentijd geen provisie aan: bij een verboden product is dat een "
            "overtreding, bij een toegestaan product kost het uitstel niets.")
        u.waarschuwingen.append(
            "De toets doet bewust geen uitspraak: een verkeerde classificatie zou een onjuist "
            "compliance-oordeel opleveren.")
        u.details = {"status": "ONBEPAALD", "wettelijke_term": None}
    u.details["reden"] = uitleg
    return u


REKENFUNCTIES = {
    "evenredigheidsbeginsel": evenredigheidsbeginsel,
    "verjaring": verjaring_schadeclaim,
    "nieuwwaarde_dagwaarde": nieuwwaarde_of_dagwaarde,
    "provisie": provisie_toets,
}
