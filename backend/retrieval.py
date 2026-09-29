"""
Retrieval over het corpus. BM25, met de hand geschreven.

Waarom BM25 en geen embeddings: juridische en polisteksten draaien om EXACTE termen
('evenredigheid', 'eigen risico', 'art. 4:23', 'opzicht'). Lexicale matching is daar
sterker en volledig deterministisch - en een deterministische retriever is
controleerbaar door een criticus, een embedding-ruimte niet.
"""
import json, math, re, os
from collections import Counter
from typing import List, Dict, Tuple

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "..", "corpus")

# Nederlandse stopwoorden; bewust zonder juridisch relevante woorden als 'niet' en 'geen',
# want die dragen in dekkingsvragen juist betekenis.
STOP = set("""de het een en of van in op te dat die deze dit is zijn was waren wordt worden
werd als bij voor met aan er om ook naar uit over door tot dan maar nog al we ze je u hij zij
men hun haar hem ons onze mijn heeft hebben had hadden kan kunnen kon zou zouden moet moeten
mag mogen wel dus want omdat indien""".split())

_WORD = re.compile(r"[a-zà-ÿ0-9]+(?::[0-9]+[a-z]?)*", re.I)


def tokenize(t: str) -> List[str]:
    toks = []
    for w in _WORD.findall((t or "").lower()):
        if w in STOP or len(w) < 2:
            continue
        # lichte Nederlandse suffixstripping; conservatief zodat 'verzekering' en
        # 'verzekeringen' matchen zonder 'uitsluiting' kapot te maken
        for suf in ("ingen", "heden", "en", "er", "s"):
            if len(w) > 6 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        toks.append(w)
    return toks


class Index:
    def __init__(self, docs: List[Dict], velden: List[str], k1=1.5, b=0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.tf, self.len = [], []
        df = Counter()
        for d in docs:
            tekst = " ".join(str(d.get(v) or "") for v in velden)
            toks = tokenize(tekst)
            c = Counter(toks)
            self.tf.append(c)
            self.len.append(len(toks))
            df.update(c.keys())
        self.N = max(1, len(docs))
        self.avg = (sum(self.len) / self.N) if self.N else 1
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def zoek(self, vraag: str, top=6, waar=None) -> List[Tuple[float, Dict]]:
        """`waar` is een optioneel filter op het document; de BM25-statistiek blijft die van het hele corpus."""
        q = tokenize(vraag)
        if not q or not self.docs:
            return []
        scores = []
        for i, tf in enumerate(self.tf):
            if waar is not None and not waar(self.docs[i]):
                continue
            s = 0.0
            dl = self.len[i] or 1
            for t in q:
                f = tf.get(t)
                if not f:
                    continue
                s += self.idf.get(t, 0) * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * dl / self.avg))
            if s > 0:
                scores.append((s, self.docs[i]))
        scores.sort(key=lambda x: -x[0])
        return scores[:top]


class Corpus:
    """Laadt de corpusbestanden. Ontbreekt er een, dan is dat zichtbaar - niet stilzwijgend leeg."""

    BESTANDEN = {
        "kifid":            ("kifid.json",            ["uitspraaknummer", "titel", "kern_klacht", "samenvatting", "kernoverweging", "categorie"]),
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
                    "geladen": True, "records": len(rows), "pad": pad,
                    "geweigerd_onbevestigde_bron": len(geweigerd),
                    "geweigerde_ids": [r.get("uitspraaknummer") or r.get("artikel")
                                       or r.get("clausule_id") for r in geweigerd][:10],
                }
            except Exception as e:
                self.data[naam], self.index[naam] = [], Index([], velden)
                self.status[naam] = {"geladen": False, "records": 0, "pad": pad,
                                     "fout": f"{type(e).__name__}: {e}"}

    def zoek(self, bron: str, vraag: str, top=6, waar=None):
        return self.index.get(bron).zoek(vraag, top, waar) if bron in self.index else []

    def zoek_breed(self, vraag: str, per_bron=4):
        return {b: self.zoek(b, vraag, per_bron) for b in self.index}

    def totaal(self) -> int:
        return sum(s["records"] for s in self.status.values())
