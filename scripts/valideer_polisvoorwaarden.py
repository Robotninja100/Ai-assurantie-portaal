#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
valideer_polisvoorwaarden.py - onafhankelijke controle op corpus/polisvoorwaarden.json

Controleert, zonder de scraper te vertrouwen:
  1. elke bron_url geeft nu HTTP 200;
  2. de gedownloade PDF heeft de sha256 die in het corpus staat;
  3. elke clausuletekst komt LETTERLIJK voor in de ruwe PDF-tekstextractie.
     Bij (3) wordt alleen op letters, cijfers, € en % vergeleken, zodat
     regelafbreking, afbreekstreepjes en verwijderd paginameubilair
     (paginanummers, kop- en voetregels) geen vals alarm geven. Elk verschil
     tussen corpus en bron wordt getoond: als daar ooit een woord in het corpus
     staat dat niet in de bron staat, is dat hier zichtbaar.

Gebruik: python3 scripts/valideer_polisvoorwaarden.py [pad/naar/corpus.json]
"""

import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pypdf  # noqa: E402
from polisvoorwaarden_lib import fetch_pdf, sha256, verify_200  # noqa: E402

TOEGESTANE_TYPES = {"dekking", "uitsluiting", "eigen risico",
                    "verplichting verzekerde", "schaderegeling", "verjaring"}
VERPLICHTE_VELDEN = {"product", "verzekeraar_of_bron", "document", "clausule_id",
                     "kop", "tekst", "type", "bron_url", "opgehaald_op"}


def letters(x):
    return re.sub(r"[^0-9a-zA-Zà-öø-ÿ€%]", "", x).lower()


def main():
    pad = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "corpus", "polisvoorwaarden.json")
    records = json.load(open(pad, encoding="utf-8"))
    fouten = []

    for r in records:
        ontbreekt = VERPLICHTE_VELDEN - set(r)
        if ontbreekt:
            fouten.append(f"{r.get('clausule_id')}: velden ontbreken {ontbreekt}")
        if r.get("type") not in TOEGESTANE_TYPES:
            fouten.append(f"{r.get('clausule_id')}: onbekend type {r.get('type')!r}")
        if not (r.get("tekst") or "").strip():
            fouten.append(f"{r.get('clausule_id')}: lege tekst")

    ruw = {}
    for url in sorted({r["bron_url"] for r in records}):
        ok, status = verify_200(url)
        if not ok:
            fouten.append(f"{url}: geen 200 maar {status}")
            continue
        path, _ = fetch_pdf(url, use_cache=False)
        digest = sha256(path)
        verwacht = {r.get("bron_pdf_sha256") for r in records if r["bron_url"] == url}
        if verwacht != {digest}:
            fouten.append(f"{url}: sha256 nu {digest}, in corpus {verwacht} "
                          f"(document is bijgewerkt; corpus opnieuw bouwen)")
        reader = pypdf.PdfReader(path)
        ruw[url] = letters("".join(p.extract_text() or "" for p in reader.pages))
        print(f"[200] {url}", file=sys.stderr)

    for r in records:
        bron = ruw.get(r["bron_url"])
        if bron is None:
            continue
        t = letters(r["tekst"])
        if t in bron:
            continue
        sm = difflib.SequenceMatcher(None, t, bron, autojunk=False)
        blokken = [b for b in sm.get_matching_blocks() if b.size > 25]
        extra_in_corpus = []
        for a, b in zip(blokken, blokken[1:]):
            gap = t[a.a + a.size:b.a]
            if gap:
                extra_in_corpus.append(gap)
        if extra_in_corpus or not blokken:
            fouten.append(f"{r['clausule_id']} ({r['bron_url']}): tekst staat NIET "
                          f"letterlijk in de bron; corpus-only fragmenten {extra_in_corpus[:3]}")

    print(f"\n{len(records)} records, {len({r['bron_url'] for r in records})} bron-URL's, "
          f"{len({r['product'] for r in records})} producten, "
          f"{len({r['verzekeraar_of_bron'] for r in records})} verzekeraars", file=sys.stderr)
    if fouten:
        print(f"\n{len(fouten)} PROBLEMEN:", file=sys.stderr)
        for f in fouten:
            print("  " + f, file=sys.stderr)
        return 1
    print("OK: alle bronnen bereikbaar en alle clausuleteksten letterlijk uit de bron.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
