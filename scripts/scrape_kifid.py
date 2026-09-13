#!/usr/bin/env python3
"""
Reproduceerbare scraper voor het Kifid-uitsprakenregister -> corpus/kifid.json

HOE DE BRON IS OPGEBOUWD (zelf onderzocht op 2026-09-13)
--------------------------------------------------------
* https://www.kifid.nl/uitspraken/ redirect (301) naar
  https://www.kifid.nl/kifid-kennis-en-uitspraken/uitspraken/ .
* Die pagina is een React-SPA; de lijst staat NIET in de HTML.
  De SPA-bundle /assets/app.tJ7Yte27.min.js bevat:
      axios.create({baseURL:"https://www.kifid.nl/api"})
      SearchDecision = "/Search/SearchDecision"
      GetCategories  = "/Search/GetCategories"
* Werkende call (LET OP de afsluitende slash; zonder slash volgt HTTP 301):
    GET https://www.kifid.nl/api/Search/SearchDecision/
        ?searchTerm=&category=&authority=&targetGroup=
        &startDate=0&endDate=0&page=1&pageSize=25&sort=newest
  Respons: {"decision":{"decisionItemsList":[...]},"totalItems":14732,...}
  Per item o.a.: title, date (.NET ticks), summary (HTML, Kifid's eigen
  samenvatting), category, judgementTags, authority, defendant, url,
  statementLink (PDF) en pdfContent = de VOLLEDIGE uitspraaktekst.
* Facetten: GET /api/Search/GetCategories/?pageType=3&searchTerm=&category=
  &startDate=0&endDate=0&authority=&targetGroup=
  -> categorieen: Bank (3080), Beleggen (1564), Hypotheek (2765),
     Verzekeringen (6497), Kleinzakelijk (11), BKR (737),
     Incassodienstverlening (18), Anders (3).

VERIFICATIE
-----------
De detailpagina (bron_url) is client-side gerenderd: het uitspraaknummer staat
NIET in de ruwe HTML. Daarom wordt op drie manieren geverifieerd:
  1. bron_url moet HTTP 200 geven (volgt redirects);
  2. binding nummer<->URL via een tweede, onafhankelijke API-call
     (searchTerm=<uitspraaknummer>): de teruggegeven url moet identiek zijn;
  3. steekproef: de officiele PDF (statementLink) wordt gedownload en de
     PDF-tekst moet het uitspraaknummer bevatten.

Gebruik:
    python3 scrape_kifid.py                      # volledige run + verificatie
    python3 scrape_kifid.py --per-thema 4
    python3 scrape_kifid.py --pdf-sample 8
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kifid_extract import extract  # noqa: E402

API = "https://www.kifid.nl/api/Search/SearchDecision/"
CATS_API = "https://www.kifid.nl/api/Search/GetCategories/"
UA = "Mozilla/5.0 (compatible; assurantie-corpus-builder/1.0)"

# (zoekterm, eigen thema-label). Het thema-label is ONZE tag voor spreiding;
# Kifid's eigen labels staan in "categorie" en "kifid_onderwerp_tags".
SEARCH_PLAN = [
    ("opstalverzekering", "opstal/woonhuis"),
    ("woonhuisverzekering", "opstal/woonhuis"),
    ("inboedelverzekering", "inboedel"),
    ("autoverzekering", "auto/motorrijtuig"),
    ("cascoverzekering", "auto/motorrijtuig"),
    ("Wet aansprakelijkheidsverzekering motorrijtuigen", "auto/WAM"),
    ("rechtsbijstandverzekering", "rechtsbijstand"),
    ("overlijdensrisicoverzekering", "ORV/leven"),
    ("levensverzekering", "ORV/leven"),
    ("arbeidsongeschiktheidsverzekering", "arbeidsongeschiktheid"),
    ("reisverzekering", "reis"),
    ("annuleringsverzekering", "reis"),
    ("aansprakelijkheidsverzekering particulieren", "AVP"),
    ("zorgplicht adviseur", "zorgplicht adviseur"),
    ("uitvaartverzekering", "uitvaart"),
    ("zorgverzekering", "zorg"),
]


def _open(url, timeout=150, tries=5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            return e
        except Exception as e:
            last = e
            time.sleep(3 + 3 * i)
    raise RuntimeError("verbinding mislukt: %s (%s)" % (url, last))


def get_json(url):
    r = _open(url)
    code = getattr(r, "status", None) or getattr(r, "code", None)
    if code != 200:
        raise RuntimeError("HTTP %s voor %s" % (code, url))
    return json.loads(r.read().decode("utf-8"))


def search(term, page=1, size=25, category="Verzekeringen", sort="newest"):
    q = urllib.parse.urlencode({
        "searchTerm": term, "category": category, "authority": "",
        "targetGroup": "", "startDate": 0, "endDate": 0,
        "page": page, "pageSize": size, "sort": sort})
    return get_json(API + "?" + q)


def url_status(url):
    """HTTP-status van een URL (volgt redirects). None = niet bereikbaar."""
    try:
        r = _open(url, timeout=120)
    except RuntimeError:
        return None, b""
    code = getattr(r, "status", None) or getattr(r, "code", None)
    try:
        body = r.read()
    except Exception:
        body = b""
    return code, body


def verify_binding(nummer, bron_url):
    """Onafhankelijke tweede API-call: hoort dit nummer echt bij deze URL?"""
    try:
        d = search(nummer, size=10, category="")
    except Exception:
        return None
    for it in (d.get("decision") or {}).get("decisionItemsList") or []:
        t = re.sub(r"\s+", "", it.get("title") or "")
        if re.sub(r"\s+", "", nummer) in t:
            return (it.get("url") or "").rstrip("/") == (bron_url or "").rstrip("/")
    return False


def verify_pdf(nummer, pdf_url):
    """Download de officiele PDF en zoek het uitspraaknummer in de tekst."""
    if not pdf_url:
        return {"pdf_http_status": None, "nummer_in_pdf": None}
    code, body = url_status(pdf_url)
    if code != 200 or not body:
        return {"pdf_http_status": code, "nummer_in_pdf": None}
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(body))
        txt = "".join((p.extract_text() or "") for p in reader.pages[:3])
    except Exception as e:
        return {"pdf_http_status": code, "nummer_in_pdf": None,
                "pdf_leesfout": str(e)[:120]}
    flat = re.sub(r"\s+", "", txt)
    return {"pdf_http_status": code,
            "nummer_in_pdf": re.sub(r"\s+", "", nummer) in flat}


def harvest(per_thema=4, pool_per_term=12):
    pool, seen = [], set()
    for term, thema in SEARCH_PLAN:
        try:
            data = search(term, size=pool_per_term)
        except Exception as e:
            print("  ! zoekfout %r: %s" % (term, e), file=sys.stderr)
            continue
        print("  %-48s totaal=%s" % (term, data.get("totalItems")))
        for it in (data.get("decision") or {}).get("decisionItemsList") or []:
            rec = extract(it, thema)
            if not rec or not rec["bron_url"]:
                continue
            if rec["uitspraaknummer"] in seen:
                continue
            seen.add(rec["uitspraaknummer"])
            pool.append(rec)
    # selectie per thema: volledigste records eerst (kern_klacht + oordeel)
    per, chosen = {}, []
    def score(r):
        return (r["kern_klacht"] is not None, r["oordeel"] is not None,
                r["kernoverweging"] is not None, r["bindend"] is not None,
                r["datum"] or "")
    for r in sorted(pool, key=score, reverse=True):
        if r["kern_klacht"] is None:
            continue
        k = r["thema"]
        if per.get(k, 0) >= per_thema:
            continue
        per[k] = per.get(k, 0) + 1
        chosen.append(r)
    return chosen


def verify(records, pdf_sample=0, rng_seed=20260913):
    import random
    print("Verificatie ...", file=sys.stderr)
    ok = []
    for r in records:
        code, body = url_status(r["bron_url"])
        r["bron_url_http_status"] = code
        r["nummer_in_ruwe_html_bronpagina"] = bool(
            body and re.sub(r"\s+", "", r["uitspraaknummer"]).encode()
            in re.sub(rb"\s+", b"", body))
        r["nummer_url_binding_geverifieerd"] = verify_binding(
            r["uitspraaknummer"], r["bron_url"])
        if code == 200:
            ok.append(r)
        else:
            print("  ! %s -> HTTP %s (verwijderd)" % (r["bron_url"], code),
                  file=sys.stderr)
    if pdf_sample:
        rnd = random.Random(rng_seed)
        for r in rnd.sample(ok, min(pdf_sample, len(ok))):
            r.update(verify_pdf(r["uitspraaknummer"], r["pdf_url"]))
            print("  pdf-check %s -> %s" % (r["uitspraaknummer"],
                                            r.get("nummer_in_pdf")),
                  file=sys.stderr)
    ok.sort(key=lambda r: (r["datum"] or "", r["uitspraaknummer"]), reverse=True)
    return ok


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(here, "..", "corpus",
                                                  "kifid.json"))
    ap.add_argument("--per-thema", type=int, default=4)
    ap.add_argument("--pdf-sample", type=int, default=8)
    a = ap.parse_args()

    recs = harvest(per_thema=a.per_thema)
    recs = verify(recs, pdf_sample=a.pdf_sample)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=2)
    print("%d records -> %s" % (len(recs), out))


if __name__ == "__main__":
    main()
