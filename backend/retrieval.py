"""
Retrieval over het corpus. BM25, met de hand geschreven.

Waarom BM25 en geen embeddings: juridische en polisteksten draaien om EXACTE termen
('evenredigheid', 'eigen risico', 'art. 4:23', 'opzicht'). Lexicale matching is daar
sterker en volledig deterministisch - en een deterministische retriever is
controleerbaar door een criticus, een embedding-ruimte niet.
"""
import json, math, re, os, unicodedata
from collections import Counter
from typing import List, Dict, Tuple

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "..", "corpus")

# Nederlandse stopwoorden; bewust zonder juridisch relevante woorden als 'niet' en 'geen',
# want die dragen in dekkingsvragen juist betekenis.
STOP = set("""de het een en of van in op te dat die deze dit is zijn was waren wordt worden
werd als bij voor met aan er om ook naar uit over door tot dan maar nog al we ze je u hij zij
men hun haar hem ons onze mijn heeft hebben had hadden kan kunnen kon zou zouden moet moeten
mag mogen wel dus want omdat indien""".split())

_WORD = re.compile(r"[a-z0-9]+(?::[0-9]+[a-z]?)*")


def _vouw(t: str) -> str:
    """Kleine letters zonder accenten: 'Univé' en 'unive', 'geïnformeerd' en 'geinformeerd' zijn hetzelfde woord."""
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# Spreektaal en werkwoordsvormen die een adviseur of klant typt, naar de term waarmee het corpus over
# hetzelfde spreekt. 'Er is ingebroken' moet de clausules over inbraak vinden, 'gestolen' die over
# diefstal. De sleutel is de term in het corpus; de lijst is bewust kort en alleen verzekeringstaal.
# Werkt aan beide kanten (index en vraag), dus 'gestolen' in een clausule en 'diefstal' in een vraag vinden elkaar.
_GROEPEN = {
    "inbraak": "inbraken ingebroken inbreken inbreker inbrekers inbrak inbreekt",
    "diefstal": "gestolen stelen steelt stal dief dieven diefstallen beroofd beroving gejat",
    "lekkage": "lek lekt gelekt lekken lekkages lekkend doorgelekt",
    "storm": "stormt gestormd stormen",
    "brand": "brandt gebrand afgebrand branden",
    "ruit": "ruiten voorruit achterruit zijruit autoruit ruitbreuk steenslag",
    "fiets": "fietsen fietser fietsers",
    "aanrijding": "aanrijdingen botsing botsingen aangereden aanrijden",
    "ongeval": "ongevallen ongeluk ongelukken",
    "bliksem": "blikseminslag",
    "hagel": "hagelstenen hagelt",
    "vandalisme": "vandaal vandalen vernield vernieling vernielingen vernielen",
    "overstroming": "overstromingen overstroomd wateroverlast",
    "beschadig": "beschadigd beschadigde beschadigen beschadiging beschadigingen kapot",
    "onderverzekering": "onderverzekerd",
    "verjaring": "verjaard verjaren verjaringstermijn",
    "afwijzing": "afgewezen afwijzen afwijzingen geweigerd weigert",
    "klacht": "klachten klagen geklaagd",
    "auto": "wagen personenauto",
    "arbeidsongeschiktheid": "aov arbeidsongeschikt arbeidsongeschikte wia",
    "aansprakelijkheid": "avp",
}
_SYNONIEM = {vorm: kern for kern, vormen in _GROEPEN.items() for vorm in vormen.split()}

# Samenstellingen worden gesplitst als beide delen bekende verzekeringswoorden zijn: 'fietsdiefstal' is
# ook 'fiets' en 'diefstal', 'waterschade' ook 'water'. 'brandstof' niet, want 'stof' is geen deel.
_DELEN = set("""fiets auto diefstal inbraak storm brand water lekkage glas ruit hagel bliksem vandalisme bagage
inboedel opstal woon woning huis reis rechtsbijstand aansprakelijkheid overstroming aanrijding schade verzekering
polis dekking claim uitkering ongeval brommer scooter motor telefoon laptop sieraden juwelen verbouwing bouw
onderhoud riool leiding dak vocht schimmel aardbeving eigen risico arbeidsongeschiktheid uitvaart""".split())
_SPLITS = {"eigenrisico": ["eigen", "risico"]}


def _delen(w: str, diepte: int = 0) -> List[str]:
    """['fiets', 'diefstal'] voor 'fietsdiefstal'; [] als het geen samenstelling van bekende delen is."""
    if w in _SPLITS:
        return _SPLITS[w]
    if len(w) < 7 or diepte > 2:
        return []
    for i in range(3, len(w) - 2):
        a, rest = w[:i], w[i:]
        if a in _DELEN:
            if rest in _DELEN:
                return [a, rest]
            verder = _delen(rest, diepte + 1)
            if verder:
                return [a] + verder
    return []


def _stam(w: str) -> str:
    """Het stamwoord waaronder een woord in de index staat: spreektaalvorm naar corpusterm, lichte uitgangen eraf."""
    w = _SYNONIEM.get(w, w)
    # lichte Nederlandse suffixstripping; conservatief zodat 'verzekering' en
    # 'verzekeringen' matchen zonder 'uitsluiting' kapot te maken
    for suf in ("ingen", "heden", "en", "er", "s"):
        if len(w) > 6 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return _SYNONIEM.get(w, w)


def tokenize(t: str) -> List[str]:
    toks = []
    for w in _WORD.findall(_vouw(t)):
        if w in STOP or len(w) < 2:
            continue
        w = _stam(w)
        toks.append(w)
        toks.extend(_delen(w))
    return toks


def _typo_achtig(t: str, c: str) -> bool:
    """
    Ziet het verschil tussen een onbekend woord `t` en een corpuswoord `c` (één fout) eruit als een typefout? Een uitgang
    ('bijgebouwd' / 'bijgebouw', 'definitieve' / 'definitie'), een andere eerste letter ('voordeel' / 'oordeel') en
    een ander, wel geldig woord zijn dat niet. Dat een woord niet in ons kleine corpus staat, maakt het nog geen typefout.
    """
    if t[0] != c[0]:                                      # een typefout zit zelden in de eerste letter
        return False
    if len(t) == len(c):                                  # een letter vervangen of twee naast elkaar verwisseld
        return True
    korter, langer = sorted((t, c), key=len)
    eerste = next((i for i in range(len(korter)) if korter[i] != langer[i]), len(korter))
    return eerste < len(korter)                           # een letter erbij of eraf, niet aan het eind (dat is een uitgang)


def _afstand(a: str, b: str, maximaal: int) -> int:
    """Damerau-Levenshtein (een verwisseling telt als één fout), afgebroken zodra de grens is overschreden."""
    if abs(len(a) - len(b)) > maximaal:
        return maximaal + 1
    vorige2, vorige = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        huidig = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            huidig[j] = min(huidig[j - 1] + 1, vorige[j] + 1, vorige[j - 1] + (ca != cb))
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                huidig[j] = min(huidig[j], vorige2[j - 2] + 1)
        if min(huidig) > maximaal:
            return maximaal + 1
        vorige2, vorige = vorige, huidig
    return vorige[-1]


class Index:
    def __init__(self, docs: List[Dict], velden: List[str], k1=1.5, b=0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.tf, self.len = [], []
        df = Counter()
        self._vorm: Dict[str, Counter] = {}
        for d in docs:
            tekst = " ".join(str(d.get(v) or "") for v in velden)
            toks = tokenize(tekst)
            c = Counter(toks)
            self.tf.append(c)
            self.len.append(len(toks))
            df.update(c.keys())
            for w in _WORD.findall(_vouw(tekst)):
                if w not in STOP and len(w) >= 2:
                    self._vorm.setdefault(_stam(w), Counter())[w] += 1
        self.df = df
        self.N = max(1, len(docs))
        self.avg = (sum(self.len) / self.N) if self.N else 1
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}
        self._woordenschat = sorted(self.idf)
        # Alle woorden van ALLE bronnen (Corpus zet dit): een woord dat elders in het corpus voorkomt is geen typefout.
        self.bekend = set(self.idf)

    def vorm(self, stam: str) -> str:
        """Het woord zoals het in het corpus meestal geschreven staat ('onderverzekering', niet het stamwoord)."""
        vormen = self._vorm.get(stam)
        return vormen.most_common(1)[0][0] if vormen else stam

    def zoek(self, vraag: str, top=6, waar=None, extra=(), dekking=0.0) -> List[Tuple[float, Dict]]:
        """
        `waar` is een optioneel filter op het document; de BM25-statistiek blijft die van het hele corpus.
        `extra` zijn herstelde termen [(stam van het onbekende woord, corpusterm)] (zie Corpus.herstel): ze tellen mee met
        minder gewicht dan wat de adviseur typte.
        `dekking` (0 tot 1): alleen documenten die minstens dit deel van de zoektermen (naar gewicht) bevatten. Een term die
        het corpus niet kent telt mee als niet gedekt: 'Solvency II kapitaalvereisten voor verzekeraars' vindt dan geen negen
        documenten op het ene woord 'verzekeraar'. Bedoeld voor korte vragen (een begrip), niet voor een uitgeschreven casus.
        """
        vervangen = {onbekend for onbekend, _ in extra}
        termen = [t for t in dict.fromkeys(tokenize(vraag)) if t not in vervangen] + [c for _, c in extra]
        q = [(t, 1.0) for t in tokenize(vraag)] + [(c, 0.6) for _, c in extra]
        if not q or not self.docs:
            return []
        hoogste = max(self.idf.values(), default=1.0)
        gewicht_t = {t: self.idf.get(t, hoogste) for t in termen}
        totaal = sum(gewicht_t.values()) or 1.0
        scores = []
        for i, tf in enumerate(self.tf):
            if waar is not None and not waar(self.docs[i]):
                continue
            if dekking and sum(w for t, w in gewicht_t.items() if t in tf) / totaal < dekking:
                continue
            s = 0.0
            dl = self.len[i] or 1
            for t, gewicht in q:
                f = tf.get(t)
                if not f:
                    continue
                s += gewicht * self.idf.get(t, 0) * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * dl / self.avg))
            if s > 0:
                scores.append((s, self.docs[i]))
        scores.sort(key=lambda x: -x[0])
        return scores[:top]


class Corpus:
    """Laadt de corpusbestanden. Ontbreekt er een, dan is dat zichtbaar - niet stilzwijgend leeg."""

    BESTANDEN = {
        "kifid":            ("kifid.json",            ["uitspraaknummer", "titel", "kern_klacht", "samenvatting", "kernoverweging", "categorie",
                                                          "thema", "kifid_onderwerp_tags"]),
        "wetgeving":        ("wetgeving.json",        ["wet", "artikel", "titel", "tekst", "onderwerp"]),
        "polisvoorwaarden": ("polisvoorwaarden.json", ["product", "clausule_id", "kop", "tekst", "type", "verzekeraar_of_bron"]),
    }

    def __init__(self):
        self.data, self.index, self.status = {}, {}, {}
        for naam, (bestand, velden) in self.BESTANDEN.items():
            pad = os.path.abspath(os.path.join(CORPUS_DIR, bestand))
            try:
                with open(pad, encoding="utf-8") as f:
                    rows = json.load(f)
                rows = rows.get("records", rows) if isinstance(rows, dict) else rows
                rows = [r for r in rows if isinstance(r, dict)]

                # CITEER-OF-WEIGER OP RETRIEVALNIVEAU.
                # Een record waarvan de bron niet is bevestigd mag nooit als onderbouwing
                # worden opgehaald, ook niet als het inhoudelijk zou kloppen. Records
                # zonder verificatieveld laten we toe (dat veld bestaat niet voor elk
                # corpus), maar een expliciete False sluit het record uit.
                geweigerd = [r for r in rows if r.get("bron_geverifieerd") is False]
                rows = [r for r in rows if r.get("bron_geverifieerd") is not False]

                self.data[naam] = rows
                self.index[naam] = Index(rows, velden)
                self.status[naam] = {
                    "geladen": True, "records": len(rows), "bestand": os.path.basename(pad),
                    "geweigerd_onbevestigde_bron": len(geweigerd),
                    "geweigerde_ids": [r.get("uitspraaknummer") or r.get("artikel")
                                       or r.get("clausule_id") for r in geweigerd][:10],
                }
            except Exception as e:
                self.data[naam], self.index[naam] = [], Index([], velden)
                self.status[naam] = {"geladen": False, "records": 0, "bestand": os.path.basename(pad),
                                     "fout": f"{type(e).__name__}: {str(e).replace(os.path.dirname(pad), '…')}"}

        alles = set().union(*(ix.idf.keys() for ix in self.index.values())) if self.index else set()
        for ix in self.index.values():
            ix.bekend = alles
        self._alle_df = Counter()
        for ix in self.index.values():
            self._alle_df.update(ix.df)
        self._alle_woorden = sorted(alles)

    def herstel(self, vraag: str) -> List[Tuple[str, str, str]]:
        """
        Woorden in de vraag die het portaal als typefout leest: [(zoals getypt, stamwoord in de index, zoals het corpus het
        schrijft)]. Het portaal raadt niet: alleen een woord van negen tekens of meer dat NERGENS in het corpus voorkomt (een
        geldig woord dat alleen in één bron ontbreekt, zoals 'verjaring' in het Kifid-register, blijft ontbreken) en geen
        samenstelling van bekende delen is ('brandschade'); precies één corpuswoord dat op één typefout na gelijk is (zie
        _typo_achtig) en in minstens twee documenten voorkomt. Bij twijfel geen correctie. Geldige woorden die in ons kleine
        corpus toevallig ontbreken ('voordeel', 'verwijst', 'negeer') zijn geen typefout: daarom de ondergrens van negen tekens.
        """
        uit, gezien = [], set()
        for w0 in re.findall(r"[^\W\d_]+", vraag or ""):
            w = _vouw(w0)
            if w in gezien:
                continue
            gezien.add(w)
            t = _stam(w)
            if (len(t) < 9 or t in STOP or t in _SYNONIEM or _delen(t)
                    or any(t in ix.bekend for ix in self.index.values())):
                continue
            kandidaten = [c for c in self._alle_woorden
                          if abs(len(c) - len(t)) <= 1 and c[0] == t[0] and self._alle_df[c] >= 2
                          and _afstand(t, c, 1) == 1 and _typo_achtig(t, c)]
            if len(kandidaten) == 1:
                vormen = max((ix for ix in self.index.values() if kandidaten[0] in ix._vorm), key=lambda ix: ix.df.get(kandidaten[0], 0))
                uit.append((w0.lower(), kandidaten[0], vormen.vorm(kandidaten[0])))
        return uit

    def correcties(self, vraag: str, max_n: int = 4) -> List[Tuple[str, str]]:
        """De melding bij een herstelde spelling: [('onderverzekring', 'onderverzekering')]. Het portaal herstelt niet stilzwijgend."""
        return [(a, c) for a, _, c in self.herstel(vraag)][:max_n]

    def zoek(self, bron: str, vraag: str, top=6, waar=None, dekking=0.0):
        if bron not in self.index:
            return []
        return self.index[bron].zoek(vraag, top, waar, extra=[(_stam(_vouw(a)), t) for a, t, _ in self.herstel(vraag)],
                                     dekking=dekking)

    def zoek_breed(self, vraag: str, per_bron=4):
        return {b: self.zoek(b, vraag, per_bron) for b in self.index}

    def totaal(self) -> int:
        return sum(s["records"] for s in self.status.values())
