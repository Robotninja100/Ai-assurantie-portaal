#!/usr/bin/env python3
"""
Maakt de Kifid-bronverwijzing citeerbaar.

Bevinding bij de eigen steekproef: de HTML-slug
  /kifid-kennis-en-uitspraken/uitspraken/uitspraak-<nr>/
geeft HTTP 200, maar REDIRECT naar het algemene uitsprakenregister. Het
uitspraaknummer staat niet op de geleverde pagina. Zo'n URL is formeel bereikbaar
en materieel niet-citeerbaar - precies waar een criticus op schiet.

De PDF op /media/<hash>/uitspraak-<nr>.pdf is wel de echte, blijvende vindplaats en
bevat het nummer letterlijk. Dit script controleert elke PDF, leest het nummer eruit
terug, en maakt de geverifieerde PDF de primaire bron. Records waarvan de PDF niet
te bevestigen is, worden gemarkeerd - niet stilzwijgend behouden.
"""
import json, os, re, sys, io, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAD = os.path.join(ROOT, "corpus", "kifid.json")
UA = "Ai-assurantie-portaal/1.0 (corpusverificatie; publieke Kifid-bron)"


def haal(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def main():
    recs = json.load(open(PAD, encoding="utf-8"))
    from pypdf import PdfReader

    ok = mis = 0
    for i, d in enumerate(recs, 1):
        nr, pdf = d.get("uitspraaknummer"), d.get("pdf_url")

        # Records die de corpusaudit heeft afgekeurd blijven afgekeurd. Een geslaagde
        # PDF-controle bewijst dat het uitspraaknummer klopt, niet dat de overige velden
        # kloppen - en juist daar zaten de fabricaties.
        if d.get("audit_bevinding"):
            d["bron_geverifieerd"] = False
            print(f"  [{i:>2}/{len(recs)}] {nr} OVERGESLAGEN (afgekeurd door audit)", file=sys.stderr)
            mis += 1
            continue
        d["bron_html_redirect_naar_register"] = True   # vastgestelde eigenschap van de slug
        if not pdf:
            d["bron_geverifieerd"] = False
            d["bron_verificatie_notitie"] = "geen pdf_url beschikbaar"
            mis += 1
            continue
        gelukt = False
        for poging in range(3):
            try:
                status, body = haal(pdf)
                if status != 200 or not body.startswith(b"%PDF"):
                    raise ValueError(f"HTTP {status}, geen PDF")
                tekst = ""
                rdr = PdfReader(io.BytesIO(body))
                for p in rdr.pages[:3]:
                    tekst += p.extract_text() or ""
                if nr and nr in tekst:
                    d["bron_url"] = pdf                     # PDF wordt de primaire citatie
                    d["bron_soort"] = "pdf"
                    d["bron_geverifieerd"] = True
                    d["bron_verificatie_notitie"] = (
                        "uitspraaknummer letterlijk teruggelezen uit de PDF-tekst")
                    d["pdf_bytes"] = len(body)
                    m = re.search(r"Uitkomst\s*(.+)", tekst)
                    if m:
                        d["uitkomst_letterlijk_uit_pdf"] = m.group(1).strip()[:200]
                    ok += 1
                    gelukt = True
                else:
                    raise ValueError("nummer niet in PDF-tekst")
                break
            except Exception as e:
                if poging == 2:
                    d["bron_geverifieerd"] = False
                    d["bron_verificatie_notitie"] = f"{type(e).__name__}: {e}"
                else:
                    time.sleep(2 * (poging + 1))
        if not gelukt and d.get("bron_geverifieerd") is not True:
            mis += 1
        print(f"  [{i:>2}/{len(recs)}] {nr} {'OK' if gelukt else 'NIET BEVESTIGD'}",
              file=sys.stderr)

    json.dump(recs, open(PAD, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n{ok} van {len(recs)} uitspraken bevestigd via de PDF-bron", file=sys.stderr)
    if mis:
        print(f"{mis} NIET bevestigd - deze mogen niet als onderbouwing worden getoond",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
