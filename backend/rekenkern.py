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


@dataclass
class Uitkomst:
    onderwerp: str
    bedrag: Optional[Decimal]
    stappen: List[Stap] = field(default_factory=list)
    grondslag: List[str] = field(default_factory=list)   # bv. ["BW:7:958:5"]
    toelichting: str = ""
    volgende_stap: str = ""                              # criticus eist een bruikbare vervolgstap
    waarschuwingen: List[str] = field(default_factory=list)

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
                              f"{_eur(vs)} / {_eur(ww)}", breuk * 100))
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

def verjaring_schadeclaim(datum_bekend: date, datum_afwijzing: Optional[date] = None,
                          datum_stuiting: Optional[date] = None,
                          peildatum: Optional[date] = None) -> Uitkomst:
    """
    Verjaring van de rechtsvordering tegen de verzekeraar, art. 7:942 BW.

    Lid 1: drie jaar, te rekenen vanaf "de aanvang van de dag, VOLGENDE OP" die waarop
           de gerechtigde met de opeisbaarheid bekend werd. De termijn begint dus een
           dag later dan de bekendheidsdatum - dat scheelt in randgevallen een dag.
    Lid 2: de termijn wordt GESTUIT door een schriftelijke aanspraak. Daarna loopt een
           NIEUWE termijn van drie jaar vanaf de dag volgend op erkenning of
           ondubbelzinnige afwijzing. Het is dus geen tweede termijn naast de eerste,
           maar een vervangende termijn.
    """
    peil = peildatum or date(2026, 9, 13)
    u = Uitkomst(onderwerp="Verjaring rechtsvordering op de verzekeraar", bedrag=None)
    u.grondslag = ["BW:7:942:1"]

    def _dag_erna(d: date) -> date:
        return date.fromordinal(d.toordinal() + 1)

    def _plus_jaren(d: date, n: int) -> date:
        try:
            return d.replace(year=d.year + n)
        except ValueError:                      # 29 februari
            return d.replace(year=d.year + n, day=28)

    start = _dag_erna(datum_bekend)
    verjaart_op = _plus_jaren(start, 3)
    u.stappen.append(Stap(
        "Aanvang: de dag volgend op de bekendheid met de opeisbaarheid (lid 1)",
        f"{datum_bekend.isoformat()} + 1 dag = {start.isoformat()}"))
    u.stappen.append(Stap("Hoofdtermijn drie jaar (lid 1)",
                          f"{start.isoformat()} + 3 jaar -> {verjaart_op.isoformat()}"))

    if datum_stuiting:
        u.stappen.append(Stap("Schriftelijke aanspraak stuit de termijn (lid 2)",
                              datum_stuiting.isoformat()))
        u.grondslag.append("BW:7:942:2")

    if datum_afwijzing:
        nieuw_start = _dag_erna(datum_afwijzing)
        verjaart_op = _plus_jaren(nieuw_start, 3)
        u.stappen.append(Stap(
            "Na ondubbelzinnige afwijzing loopt een NIEUWE termijn van drie jaar (lid 2); "
            "deze vervangt de oorspronkelijke termijn",
            f"{nieuw_start.isoformat()} + 3 jaar -> {verjaart_op.isoformat()}"))
        if "BW:7:942:2" not in u.grondslag:
            u.grondslag.append("BW:7:942:2")

    verjaard = peil > verjaart_op
    dagen = (verjaart_op - peil).days
    u.toelichting = (
        f"Op peildatum {peil.isoformat()} is de vordering "
        f"{'VERJAARD' if verjaard else 'nog niet verjaard'}; de termijn "
        f"{'verliep' if verjaard else 'verloopt'} op {verjaart_op.isoformat()} "
        f"({abs(dagen)} dagen {'geleden' if verjaard else 'resterend'}).")
    u.volgende_stap = (
        "Stuit de verjaring per aangetekende brief met een ondubbelzinnige aanspraak op "
        "uitkering, ruim voor de einddatum, en bewaar het verzendbewijs."
        if not verjaard else
        "Ga na of er eerder rechtsgeldig is gestuit; zonder stuiting is de vordering niet "
        "meer afdwingbaar. Onderzoek subsidiair of de adviseur zelf aansprakelijk is voor "
        "het laten verlopen van de termijn.")
    if not verjaard and dagen < 90:
        u.waarschuwingen.append(f"Nog maar {dagen} dagen tot verjaring: handel met spoed.")
    u.waarschuwingen.append(
        "Bij aansprakelijkheidsverzekering geldt een afwijkende stuitingsregel: "
        "iedere onderhandeling stuit de termijn (art. 7:942 lid 3).")
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

def provisie_toets(producttype: str, jaarpremie=0, provisiepercentage=0,
                   directe_beloning=0) -> Uitkomst:
    """
    Toetst of beloning via provisie is toegestaan.

    Voor 'complexe producten' en enkele impactvolle producten geldt sinds 2013 een
    provisieverbod: de adviseur wordt rechtstreeks door de klant betaald.
    De precieze productafbakening staat in het BGfo en wordt tegen het corpus
    gevalideerd; is die validatie niet rond, dan toont de app dit als NIET-ONDERBOUWD.
    """
    VERBOD = {
        "hypothecair krediet", "levensverzekering", "overlijdensrisicoverzekering",
        "arbeidsongeschiktheidsverzekering", "uitvaartverzekering",
        "betalingsbeschermer", "complex product", "beleggingsverzekering",
    }
    pt = (producttype or "").strip().lower()
    u = Uitkomst(onderwerp="Provisietoets", bedrag=None)
    u.grondslag = ["BGfo:86c"]

    if pt in VERBOD:
        u.toelichting = (
            f"Voor '{producttype}' geldt het provisieverbod. Beloning loopt via een "
            "rechtstreeks met de klant overeengekomen bedrag, niet via de aanbieder.")
        u.bedrag = _eur(directe_beloning)
        u.stappen.append(Stap("Toegestane beloning", "directe beloning door klant",
                              Decimal(str(directe_beloning))))
        if provisiepercentage and Decimal(str(provisiepercentage)) > 0:
            u.waarschuwingen.append(
                "Er is een provisiepercentage ingevuld voor een product onder het "
                "provisieverbod. Dit is een compliance-signaal, geen rekenfout.")
        u.volgende_stap = (
            "Leg de directe beloning vast in het dienstverleningsdocument en laat de klant "
            "daar vooraf mee instemmen. Controleer of het bedrag aantoonbaar in verhouding "
            "staat tot de verrichte werkzaamheden.")
    else:
        prov = Decimal(str(jaarpremie)) * Decimal(str(provisiepercentage)) / Decimal("100")
        u.bedrag = prov
        u.stappen.append(Stap("Provisie over jaarpremie",
                              f"{_eur(jaarpremie)} x {provisiepercentage}%", prov))
        u.toelichting = (
            f"Voor '{producttype}' is provisiebeloning toegestaan (schadeverzekering "
            "buiten het provisieverbod).")
        u.volgende_stap = (
            "Vermeld de aard en hoogte van de beloning in het dienstverleningsdocument; "
            "transparantie is ook zonder provisieverbod verplicht.")
        u.waarschuwingen.append(
            "Productclassificatie is hier op naam bepaald. Controleer de wettelijke "
            "kwalificatie voordat je hierop adviseert.")
    return u


REKENFUNCTIES = {
    "evenredigheidsbeginsel": evenredigheidsbeginsel,
    "verjaring": verjaring_schadeclaim,
    "nieuwwaarde_dagwaarde": nieuwwaarde_of_dagwaarde,
    "provisie": provisie_toets,
}
