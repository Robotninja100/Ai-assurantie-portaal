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

import re
from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timedelta, timezone
from typing import Optional, List


def _nl_zonder_tijdzonedatabase(nu: datetime) -> date:
    """Nederlandse datum voor een UTC-tijdstip met de EU-regel voor zomertijd (laatste zondag van maart/oktober, 01.00 UTC)."""
    def laatste_zondag(jaar, maand):
        d = date(jaar, maand, 31)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    j = nu.year
    begin = datetime(j, 3, laatste_zondag(j, 3).day, 1, tzinfo=timezone.utc)
    eind = datetime(j, 10, laatste_zondag(j, 10).day, 1, tzinfo=timezone.utc)
    return (nu + timedelta(hours=2 if begin <= nu < eind else 1)).date()


def vandaag_nl(nu: Optional[datetime] = None) -> date:
    """
    De datum van vandaag in Nederland. De server draait op UTC: tussen middernacht en 01.00 of 02.00
    uur Nederlandse tijd is het hier al morgen, en dan staat de peildatum een dag achter (een termijn
    lijkt een dag langer te lopen, en 'vandaag bekend' wordt als 'na de peildatum' geweigerd).
    `nu` (een UTC-tijdstip) is er voor de tests.
    """
    nu = nu or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return nu.astimezone(ZoneInfo("Europe/Amsterdam")).date()
    except Exception:  # noqa: BLE001 - geen tijdzonedatabase
        return _nl_zonder_tijdzonedatabase(nu)


def _g(x) -> str:
    """Een getal zoals een Nederlander het schrijft, zonder overbodige nullen: 12,5 / 40 / 6,5."""
    d = Decimal(str(x)).normalize()
    return format(d, "f").replace(".", ",")


def _eur(x) -> Decimal:
    """Afronden op hele centen, bankierszorg: half naar boven."""
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _bedrag(x) -> str:
    """Een bedrag zoals een Nederlander het schrijft: € 1.234,56 (voor teksten, niet voor rekenen)."""
    tekst = f"{_eur(x):,.2f}"                   # 1,234.56
    return "€ " + tekst.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _procent(x) -> str:
    return f"{_eur(x):.2f}".replace(".", ",") + "%"


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
    # De uitkomst in gewone zinnen, uit code. Het taalmodel herschrijft deze zinnen; het bedenkt geen
    # redenen erbij. Een klein model dat zelf mag uitleggen, verzint oorzaken die er niet zijn.
    uitleg: List[str] = field(default_factory=list)

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
        u.toelichting = "De uitkering kan niet worden berekend zonder werkelijke waarde."
        u.volgende_stap = "Stel eerst de herbouw-/vervangingswaarde vast, desnoods via een taxatie."
        return u

    # De schade kan niet hoger zijn dan de waarde van het verzekerde belang, en de uitkering nooit hoger
    # dan de verzekerde som (art. 7:955 lid 1, behoudens art. 7:959). Een schade boven de waarde is bij
    # totaal verlies de waarde zelf; de invoer is dan tegenstrijdig en dat zeggen we erbij.
    sch_eff = min(sch, ww)
    if sch > ww:
        u.waarschuwingen.append(
            f"De schade ({_bedrag(sch)}) is hoger dan de werkelijke waarde ({_bedrag(ww)}). De berekening gaat "
            "uit van de waarde als hoogste schade (totaal verlies). Controleer de invoer.")

    if vs >= ww:
        u.stappen.append(Stap("Geen onderverzekering: verzekerde som dekt de waarde",
                              f"{_bedrag(vs)} >= {_bedrag(ww)}", None, ""))
        basis = min(sch_eff, vs)
        u.grondslag = ["BW:7:955:1"]
        u.details = {"onderverzekerd": False, "verzekerd_pct": "100.00", "onderverzekering_pct": "0.00"}
        if sch > vs:
            u.waarschuwingen.append(
                f"Schade ({_bedrag(sch)}) overstijgt de verzekerde som ({_bedrag(vs)}); "
                "de uitkering is gemaximeerd op de verzekerde som.")
    else:
        breuk = vs / ww
        u.stappen.append(Stap("Evenredigheidsbreuk bepalen",
                              f"{_bedrag(vs)} / {_bedrag(ww)}", breuk * 100, "%"))
        if sch > ww:
            u.stappen.append(Stap("Schade begrensd op de werkelijke waarde (totaal verlies, art. 7:958 lid 2)",
                                  f"min({_bedrag(sch)}; {_bedrag(ww)})", sch_eff))
        basis = min(sch_eff * breuk, vs)
        u.stappen.append(Stap("Schade naar evenredigheid",
                              f"{_bedrag(sch_eff)} x ({_bedrag(vs)} / {_bedrag(ww)})", basis))
        u.grondslag = ["BW:7:958:5", "BW:7:955:1"] if sch > ww else ["BW:7:958:5"]
        u.details = {"onderverzekerd": True, "verzekerd_pct": str(_eur(breuk * 100)),
                     "onderverzekering_pct": str(_eur((1 - breuk) * 100))}
        u.waarschuwingen.append(
            f"Onderverzekering van {_procent((1 - breuk) * 100)}. "
            "Controleer of een garantie tegen onderverzekering van toepassing is; "
            "die zet de evenredigheidsregel opzij.")

    na_er = basis - er
    if er > 0:
        u.stappen.append(Stap("Eigen risico in mindering", f"{_bedrag(basis)} - {_bedrag(er)}", na_er))
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
                f"{_bedrag(bk)} x ({_bedrag(vs)} / {_bedrag(ww)})", bk_verg))
        else:
            bk_verg = bk
            u.stappen.append(Stap("Bereddingskosten volledig vergoed",
                                  f"{_bedrag(bk)}", bk_verg))
        u.stappen.append(Stap(
            "Bereddingskosten mogen de verzekerde som overschrijden (art. 7:959 lid 1)",
            f"{_bedrag(na_er)} + {_bedrag(bk_verg)}", na_er + bk_verg))
        totaal = na_er + bk_verg
        u.grondslag += ["BW:7:957:2", "BW:7:959:1"]
        if onderverzekerd:
            u.grondslag.append("BW:7:959:2")

    # Wat de verzekerde zelf draagt, in delen: dit bedrag staat niet in de uitkering, maar de adviseur
    # moet het aan de klant kunnen uitleggen en het model moet het niet zelf hoeven uitrekenen.
    totale_schade = sch_eff + bk
    zelf = max(Decimal("0"), totale_schade - totaal)
    er_toegepast = min(er, basis) if er > 0 else Decimal("0")
    zelf_boven = zelf - er_toegepast
    if er > 0 and vs < ww:
        u.waarschuwingen.append(
            "De volgorde (eerst de evenredigheidsbreuk, daarna het eigen risico) volgt uit de "
            "polisvoorwaarden, niet uit de wet. Controleer haar in de voorwaarden van deze verzekeraar: "
            "wordt het eigen risico eerst afgetrokken, dan valt de uitkomst anders uit.")
    if bk > 0 and _eur(na_er) + _eur(totaal - na_er) != _eur(totaal):
        u.waarschuwingen.append(
            "Bedragen zijn afgerond op hele centen; de getoonde tussenbedragen kunnen daardoor 1 cent "
            "afwijken van het getoonde totaal.")
    u.stappen.append(Stap("Zelf te dragen door de verzekerde (schade" + (" en bereddingskosten" if bk > 0 else "") + " min uitkering)",
                          f"{_bedrag(totale_schade)} - {_bedrag(totaal)}", zelf))
    u.details.update({"totale_schade": str(_eur(totale_schade)), "zelf_te_dragen": str(_eur(zelf)),
                      "zelf_te_dragen_door_onderverzekering" if vs < ww else "zelf_te_dragen_boven_verzekerde_som":
                          str(_eur(zelf_boven)),
                      "zelf_te_dragen_eigen_risico": str(_eur(er_toegepast))})
    # --- dezelfde berekening in gewone zinnen
    if sch > ww:
        u.uitleg.append(
            f"De ingevoerde schade ({_bedrag(sch)}) is hoger dan de werkelijke waarde ({_bedrag(ww)}); de berekening "
            f"gaat uit van de waarde als hoogste schade ({_bedrag(sch_eff)}).")
    if vs < ww:
        u.uitleg.append(
            f"De verzekerde som ({_bedrag(vs)}) is {_procent(breuk * 100)} van de werkelijke waarde ({_bedrag(ww)}). "
            f"Er is dus sprake van onderverzekering: volgens art. 7:958 lid 5 BW wordt de schade dan naar evenredigheid "
            f"vergoed, hier {_procent(breuk * 100)} van de schade.")
        u.uitleg.append(f"Bij een schade van {_bedrag(sch_eff)} is dat {_bedrag(basis)}.")
    else:
        u.uitleg.append(
            f"De verzekerde som ({_bedrag(vs)}) is niet lager dan de werkelijke waarde ({_bedrag(ww)}). Er is geen "
            "onderverzekering en de schade wordt niet naar evenredigheid verminderd.")
        if sch_eff > vs:
            u.uitleg.append(
                f"De schade ({_bedrag(sch_eff)}) is hoger dan de verzekerde som; de vergoeding is begrensd op de "
                f"verzekerde som (art. 7:955 lid 1 BW): {_bedrag(basis)}.")
    if er_toegepast > 0:
        u.uitleg.append(
            f"Daarna is het eigen risico van {_bedrag(er_toegepast)} in mindering gebracht; die volgorde volgt uit de "
            f"polisvoorwaarden. Dat geeft {_bedrag(basis - er_toegepast)}.")
    if bk > 0:
        if vs < ww:
            u.uitleg.append(
                f"De bereddingskosten ({_bedrag(bk)}) worden bij onderverzekering ook naar evenredigheid vergoed "
                f"(art. 7:959 lid 2 BW): {_bedrag(bk_verg)}. Ze mogen boven de verzekerde som uitgaan "
                f"(art. 7:959 lid 1 BW).")
        else:
            u.uitleg.append(
                f"De bereddingskosten ({_bedrag(bk)}) worden volledig vergoed, ook boven de verzekerde som "
                f"(art. 7:959 lid 1 BW).")
    delen_zelf = []
    if zelf_boven > 0:
        delen_zelf.append(f"{_bedrag(zelf_boven)} " + ("door onderverzekering" if vs < ww else "boven de verzekerde som"))
    if er_toegepast > 0:
        delen_zelf.append(f"{_bedrag(er_toegepast)} eigen risico")
    u.uitleg.append(
        f"De uitkering is {_bedrag(totaal)}. Van de totale schade van {_bedrag(totale_schade)} draagt de verzekerde "
        f"zelf {_bedrag(zelf)}" + (f" ({' en '.join(delen_zelf)})" if delen_zelf else "") + ".")
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

    De termijn begint op S = D+1 om 00.00 uur en is drie jaar later verstreken op S + 3 jaar om
    00.00 uur; de laatste dag is de dag daarvoor. Voorbeeld: bekend op 10 maart 2024 -> S = 11 maart
    2024 -> verstreken op 11 maart 2027 om 00.00 uur -> laatste dag 10 maart 2027. Een eerdere versie
    rekende tot en met 11 maart en gaf de adviseur daarmee één dag te veel.

    Randgevallen die met 'dezelfde dag drie jaar later' verkeerd uitpakken:
      - bekend op 28 februari 2025: S = 1 maart 2025, verstreken op 1 maart 2028, dus laatste dag
        29 februari 2028 (2028 is een schrikkeljaar);
      - S = 29 februari (bekend op 28 februari in een schrikkeljaar): drie jaar later bestaat die dag
        niet; de termijn eindigt dan op de laatste dag van februari.
    """
    s = _dag_erna(aanvangsgebeurtenis)
    try:
        verstreken = s.replace(year=s.year + 3)
    except ValueError:                          # S is 29 februari en het doeljaar heeft er geen
        return date(s.year + 3, 2, 28)
    return date.fromordinal(verstreken.toordinal() - 1)


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
    peil = peildatum or vandaag_nl()
    if datum_bekend > peil:
        raise ValueError(f"De bekendheid met de opeisbaarheid ({_nl(datum_bekend)}) ligt na de peildatum ({_nl(peil)}).")
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

    # Wat na de peildatum gebeurt (of gepland staat) heeft op de peildatum nog niets gestuit. Zo blijft de
    # uitkomst een momentopname, en een voorgenomen brief geeft niet ten onrechte rust.
    latere_aanspraak = latere_reactie = None
    if datum_stuiting and datum_stuiting > peil:
        latere_aanspraak, datum_stuiting = datum_stuiting, None
    if datum_reactie and datum_reactie > peil:
        latere_reactie, datum_reactie = datum_reactie, None

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

    if latere_aanspraak:
        gebeurtenissen.append({"datum": latere_aanspraak.isoformat(), "soort": "stuiting",
                               "label": f"{aanspraak_woord.capitalize()} (na de peildatum)"})
        deadline = f" Verstuur haar vóór {_nl(eind)}, met verzendbewijs." if (eind and status == "LOOPT") else ""
        u.waarschuwingen.insert(0, f"De {aanspraak_woord} van {_nl(latere_aanspraak)} ligt na de peildatum "
                                   f"({_nl(peil)}) en heeft op die dag nog niets gestuit.{deadline}")
    if latere_reactie:
        u.waarschuwingen.insert(0, f"De {reactie_woord} van {_nl(latere_reactie)} ligt na de peildatum "
                                   f"({_nl(peil)}) en is niet meegeteld.")
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
    Veel inboedel-/opstalpolissen keren nieuwwaarde uit, maar alleen als de dagwaarde MEER DAN een
    drempel (vaak 40% van de nieuwwaarde) bedraagt (Klaverblad art. 2.17.3 sub c); op of onder die
    drempel geldt dagwaarde.
    De drempel is polisafhankelijk en wordt daarom als parameter meegegeven,
    niet hard aangenomen.
    """
    nw = Decimal(str(nieuwwaarde))
    u = Uitkomst(onderwerp="Nieuwwaarde versus dagwaarde", bedrag=None)

    if levensduur_jaren <= 0:
        u.waarschuwingen.append("Levensduur moet groter dan nul zijn.")
        u.toelichting = "De waardetoets kan niet worden uitgevoerd zonder levensduur."
        u.volgende_stap = ("Stel de levensduur vast (uit de polisvoorwaarden, een afschrijvingstabel of een taxatie) "
                           "en start de toets opnieuw.")
        return u

    rest = max(Decimal("0"), Decimal(str(levensduur_jaren)) - Decimal(str(ouderdom_jaren)))
    factor = rest / Decimal(str(levensduur_jaren))
    dagwaarde = nw * factor
    drempel = nw * Decimal(str(dagwaarde_drempel_pct)) / Decimal("100")

    u.stappen.append(Stap("Restlevensduur", f"{_g(levensduur_jaren)} - {_g(ouderdom_jaren)} = {_g(rest)} jaar"))
    u.stappen.append(Stap("Dagwaarde", f"{_bedrag(nw)} x ({_g(rest)}/{_g(levensduur_jaren)})", dagwaarde))
    u.stappen.append(Stap(f"Drempel ({_g(dagwaarde_drempel_pct)}% van nieuwwaarde)",
                          f"{_bedrag(nw)} x {_g(dagwaarde_drempel_pct)}%", drempel))

    u.details = {
        "nieuwwaarde": str(_eur(nw)), "dagwaarde": str(_eur(dagwaarde)), "drempel": str(_eur(drempel)),
        "dagwaarde_pct": str(_eur(factor * 100)), "drempel_pct": str(_eur(Decimal(str(dagwaarde_drempel_pct)))),
        "toegepast": "dagwaarde" if dagwaarde <= drempel else "nieuwwaarde"}
    if dagwaarde == drempel:
        u.waarschuwingen.append(
            "De dagwaarde ligt precies op de drempel. Klaverblad (inboedel, art. 2.17.3 sub c) vraagt 'meer dan "
            "40%' voor nieuwwaarde, dus dan geldt dagwaarde; een andere verzekeraar kan 'ten minste' hanteren.")
    if dagwaarde <= drempel:
        u.bedrag = dagwaarde
        u.toelichting = "Dagwaarde ligt op of onder de polisdrempel; er wordt op dagwaarde afgewikkeld."
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
    "hypotheken": "hypothecair krediet",         # het meervoud laat de dubbele e vallen
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
    "dierenverzekering", "bromfietsverzekering", "motorverzekering", "schadeverzekering",
)


def _treffers(pt: str):
    """
    Alle productnamen uit de drie lijsten die als heel woord in de tekst staan, als
    (regime, term, begin, eind). Een meervoud of verbogen vorm telt mee. Een treffer die binnen een
    langere treffer valt vervalt: 'individuele arbeidsongeschiktheidsverzekering' is de VERBODEN term,
    niet ook nog de onbepaalde 'arbeidsongeschiktheidsverzekering' die er als deel in zit.
    """
    kandidaten = []
    lijsten = ([("VERBODEN", t, t) for t in VERBOD_86C] + [("VERBODEN", a, t) for a, t in _ALIAS_VERBOD.items()]
               + [("ONBEPAALD", t, t) for t in _ONBEPAALD] + [("SCHADE", t, t) for t in SCHADE])
    for regime, zoek, term in lijsten:
        for m in re.finditer(r"(?<!\w)" + re.escape(zoek) + r"(?:en|s)?(?!\w)", pt):
            kandidaten.append((regime, term, m.start(), m.end()))
    return [k for k in kandidaten
            if not any(o is not k and o[2] <= k[2] and k[3] <= o[3] and (o[3] - o[2]) > (k[3] - k[2])
                       for o in kandidaten)]


def classificeer_product(producttype: str):
    """
    Geeft (status, wettelijke_term, uitleg):
      VERBODEN      - het product staat in art. 86c lid 1 BGfo
      SCHADE        - een schadeverzekering die art. 86c niet noemt (art. 86d)
      ONBEPAALD     - kwalificatie volgt niet uit het corpus, of er staan producten uit verschillende
                      regimes door elkaar; de toets weigert dan een uitspraak
    """
    pt = " ".join((producttype or "").lower().split())
    treffers = _treffers(pt)
    # 'AOV, individueel' en 'AOV (individueel)': het woord 'individueel' bij een AOV maakt er de
    # individuele arbeidsongeschiktheidsverzekering van die art. 86c lid 1 letterlijk noemt. Staat er
    # ook 'collectief' (bijvoorbeeld 'individueel of collectief'), dan is het juist niet vast te stellen.
    aov_termen = ("aov", "arbeidsongeschiktheidsverzekering", "individuele arbeidsongeschiktheidsverzekering")
    aov = [t for t in treffers if t[1] in aov_termen]
    if aov:
        individueel = re.search(r"(?<!\w)individu(?:eel|ele)(?!\w)", pt)
        collectief = re.search(r"(?<!\w)collectie(?:f|ve)(?!\w)", pt)
        if collectief:
            treffers = [t for t in treffers if t not in aov] + [("ONBEPAALD", "aov", 0, 0)]
        elif individueel:
            treffers = [t for t in treffers if t not in aov] + [("VERBODEN", "individuele arbeidsongeschiktheidsverzekering", 0, 0)]
    regimes = {t[0] for t in treffers}
    if len(regimes) > 1:
        namen = ", ".join(sorted({t[1] for t in treffers}))
        return "ONBEPAALD", None, (
            f"In de invoer staan producten uit verschillende regimes door elkaar ({namen}). Voor een "
            "hypotheek e.d. geldt het verbod van art. 86c lid 1, voor een schadeverzekering art. 86d. "
            "Toets elk product apart.")
    if regimes == {"VERBODEN"}:
        term = treffers[0][1]
        return "VERBODEN", term, (f"Genoemd in art. 86c lid 1 BGfo." if term == pt
                                  else f"Het ingevoerde producttype valt onder '{term}', genoemd in art. 86c lid 1 BGfo.")
    if regimes == {"ONBEPAALD"}:
        return "ONBEPAALD", None, _ONBEPAALD[treffers[0][1]]
    if regimes == {"SCHADE"}:
        return "SCHADE", None, "Niet genoemd in art. 86c lid 1 BGfo; voor schadeverzekeringen geldt art. 86d."
    return "ONBEPAALD", None, (
        "Het ingevoerde producttype is niet herkend. Bepaal eerst of het onder art. 86c lid 1 BGfo "
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
    # In de teksten staat de herkende wettelijke term, niet de ruwe invoer: dat is korter, klopt met de wet
    # en laat geen vrije tekst van de gebruiker in de opdracht aan het taalmodel belanden.
    naam = term or "het ingevoerde product"
    u = Uitkomst(onderwerp="Provisietoets", bedrag=None)
    jp, pct = Decimal(str(jaarpremie or 0)), Decimal(str(provisiepercentage or 0))
    prov = jp * pct / Decimal("100")

    if status == "VERBODEN":
        u.grondslag = ["BGfo:86c:1", "BGfo:86c:2"]
        u.stappen.append(Stap("Toets: valt het product onder het provisieverbod?",
                              f"'{term}' staat in art. 86c lid 1", None, ""))
        if pct > 0:
            u.stappen.append(Stap("Ingevulde provisie (NIET toegestaan voor dit product)",
                                  f"{_bedrag(jp)} x {pct}%", prov))
            u.waarschuwingen.append(
                "Er is een provisiepercentage ingevuld voor een product onder het provisieverbod. "
                "Dit is een compliance-signaal, geen rekenfout.")
        u.bedrag = _eur(directe_beloning or 0)
        u.stappen.append(Stap("Toegestane beloning: rechtstreeks door de klant verschaft (lid 2 onder a)",
                              "directe beloning door de klant", Decimal(str(directe_beloning or 0))))
        u.toelichting = (
            f"Voor '{naam}' geldt het provisieverbod van art. 86c lid 1 BGfo. Beloning loopt "
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
                              f"'{naam}' is een schadeverzekering", None, ""))
        if jp > 0 and pct > 0:
            u.stappen.append(Stap("Provisie over jaarpremie", f"{_bedrag(jp)} x {pct}%", prov))
            u.bedrag = prov
        else:
            # Een lege premie of een leeg percentage is geen nul: dat zou schijnzekerheid geven.
            u.stappen.append(Stap("Geen jaarpremie of provisiepercentage ingevuld: geen bedrag berekend",
                                  "vul beide in voor een bedrag", None, ""))
            u.bedrag = None
        u.toelichting = (
            f"Voor '{naam}' geldt het verbod van art. 86c lid 1 BGfo niet. Art. 86d lid 1 staat "
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
                                  f"{_bedrag(jp)} x {pct}%", prov))
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


# ---------------------------------------------------------------- klachttermijnen

def klachttermijnen(datum_klacht: date, datum_bevestiging: Optional[date] = None,
                    peildatum: Optional[date] = None) -> Uitkomst:
    """
    De termijnen uit art. 43 BGfo, letterlijk toegepast op de datum van de klacht.

    Lid 2: de onderneming bevestigt de ontvangst en bericht binnen twee weken na ontvangst binnen welke
           termijn de klacht wordt afgehandeld.
    Lid 3: de klager kan de klacht rechtstreeks aan de geschilleninstantie voorleggen "vanaf zes weken
           na ontvangst van de ontvangstbevestiging of acht weken na het indienen van de klacht".
           Dat 'of' laat twee lezingen toe; beide data worden getoond en geen van beide wordt
           weggekozen.
    Lid 4: vraagt de onderneming nadere informatie, dan worden de termijnen van lid 3 verlengd met de
           termijn voor beantwoording. Dat is een feit dat hier niet bekend is en dus niet doorgerekend.
    """
    peil = peildatum or vandaag_nl()
    if datum_bevestiging and datum_bevestiging < datum_klacht:
        raise ValueError(f"De ontvangstbevestiging ({_nl(datum_bevestiging)}) ligt vóór de klacht ({_nl(datum_klacht)}).")
    u = Uitkomst(onderwerp="Termijnen bij een klacht (art. 43 BGfo)", bedrag=None)
    u.grondslag = ["BGfo:43:2", "BGfo:43:3"]
    dag = lambda d, n: date.fromordinal(d.toordinal() + n)
    bevestiging_uiterlijk = dag(datum_klacht, 14)
    acht_weken = dag(datum_klacht, 56)
    u.stappen.append(Stap("Klacht ingediend", _nl(datum_klacht), None, ""))
    u.stappen.append(Stap("Uiterlijk bevestiging van ontvangst en bericht over de afhandelingstermijn (lid 2: twee weken)",
                          f"{_nl(datum_klacht)} + 14 dagen = {_nl(bevestiging_uiterlijk)}", None, ""))
    u.stappen.append(Stap("Naar de geschilleninstantie kan vanaf acht weken na het indienen (lid 3)",
                          f"{_nl(datum_klacht)} + 56 dagen = {_nl(acht_weken)}", None, ""))
    zes_weken = None
    if datum_bevestiging:
        zes_weken = dag(datum_bevestiging, 42)
        u.stappen.append(Stap("Naar de geschilleninstantie kan vanaf zes weken na de ontvangstbevestiging (lid 3)",
                              f"{_nl(datum_bevestiging)} + 42 dagen = {_nl(zes_weken)}", None, ""))
        if datum_bevestiging > bevestiging_uiterlijk:
            u.waarschuwingen.append(
                f"De ontvangstbevestiging ({_nl(datum_bevestiging)}) kwam na de termijn van twee weken "
                f"({_nl(bevestiging_uiterlijk)}). Leg dat vast; het kan de klacht ondersteunen.")
    else:
        u.stappen.append(Stap("Zes weken na de ontvangstbevestiging (lid 3)",
                              "datum van de ontvangstbevestiging niet ingevuld: niet te berekenen", None, ""))
    lezingen = [d for d in (acht_weken, zes_weken) if d]
    vroegste, laatste = min(lezingen), max(lezingen)
    # Zonder datum van de ontvangstbevestiging bestaat maar één van de twee data. Dan kan de tweede
    # lezing niet worden uitgesloten: hooguit hangt het van die lezing af, zeker is het nooit.
    zeker = peil >= laatste and zes_weken is not None
    mogelijk = peil >= vroegste
    u.details = {"peildatum": peil.isoformat(), "klacht": datum_klacht.isoformat(),
                 "bevestiging_uiterlijk": bevestiging_uiterlijk.isoformat(), "acht_weken_na_indienen": acht_weken.isoformat(),
                 "zes_weken_na_bevestiging": zes_weken.isoformat() if zes_weken else None,
                 "vroegste_datum_geschilleninstantie": vroegste.isoformat(),
                 "laatste_datum_geschilleninstantie": laatste.isoformat(),
                 "kan_naar_geschilleninstantie": zeker, "afhankelijk_van_de_lezing": mogelijk and not zeker}
    if zeker:
        u.toelichting = (f"Op peildatum {_nl(peil)} kan de klager de klacht rechtstreeks aan de geschilleninstantie "
                         f"voorleggen: beide data uit art. 43 lid 3 zijn verstreken (uiterlijk {_nl(laatste)}).")
    elif zes_weken is None:
        u.toelichting = (
            (f"Op peildatum {_nl(peil)} is acht weken na het indienen verstreken ({_nl(acht_weken)}). "
             if mogelijk else
             f"Op peildatum {_nl(peil)} kan de klager de klacht nog niet voorleggen; acht weken na het indienen is "
             f"{_nl(acht_weken)}. ")
            + "De datum van de ontvangstbevestiging ontbreekt, dus de datum zes weken daarna is niet te berekenen. "
              "Is er geen ontvangstbevestiging gekomen, dan bestaat die datum niet en is dit de enige datum uit "
              "art. 43 lid 3 die te berekenen is; vul anders de datum van de bevestiging in.")
    elif mogelijk:
        u.toelichting = (f"Op peildatum {_nl(peil)} hangt het af van de lezing van art. 43 lid 3: volgens de ene lezing kan de "
                         f"klacht al aan de geschilleninstantie worden voorgelegd (vanaf {_nl(vroegste)}), volgens de andere pas "
                         f"vanaf {_nl(laatste)}. Wacht tot {_nl(laatste)} als je zeker wilt zijn.")
    else:
        u.toelichting = (f"Op peildatum {_nl(peil)} kan de klager de klacht nog niet aan de geschilleninstantie voorleggen; "
                         f"de vroegste datum volgens art. 43 lid 3 is {_nl(vroegste)}.")
    u.waarschuwingen.append(
        "Art. 43 lid 3 zegt 'vanaf zes weken na ontvangst van de ontvangstbevestiging of acht weken na het "
        "indienen van de klacht'. Beide data staan hierboven; het portaal kiest niet tussen de twee lezingen.")
    u.waarschuwingen.append(
        "Vraagt de onderneming de klager om nadere informatie, dan worden de termijnen verlengd met de "
        "termijn voor beantwoording (lid 4). Dat is hier niet meegerekend.")
    u.waarschuwingen.append(
        "Of de geschilleninstantie de klacht in behandeling neemt hangt af van haar eigen reglement, dat niet "
        "in het corpus staat.")
    u.volgende_stap = (
        "Leg de datum van de klacht en van de ontvangstbevestiging vast. Is de vroegste datum bereikt en is de "
        "klacht niet naar tevredenheid afgehandeld, vraag dan het reglement van de geschilleninstantie op voor de "
        "indieningsvoorwaarden."
        if zeker else
        "Leg de datum van de klacht vast en controleer of de onderneming binnen twee weken heeft bevestigd. "
        "Wacht met de geschilleninstantie tot de vroegste datum is bereikt en vraag intussen om een schriftelijke "
        "afhandelingstermijn.")
    return u


REKENFUNCTIES = {
    "evenredigheidsbeginsel": evenredigheidsbeginsel,
    "verjaring": verjaring_schadeclaim,
    "nieuwwaarde_dagwaarde": nieuwwaarde_of_dagwaarde,
    "provisie": provisie_toets,
    "klachttermijnen": klachttermijnen,
}
