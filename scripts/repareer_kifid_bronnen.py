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

De controle is letterlijk: het uitspraaknummer van het record moet als tekenreeks in de
PDF-tekst staan. Er wordt niets genormaliseerd of afgerond. Staat het nummer er wel, maar
anders geschreven (bijvoorbeeld zonder voorloopnul), dan blijft het record geweigerd en
zegt de notitie precies wat de PDF drukt, zodat een mens kan beslissen zonder dat de
controle stilzwijgend versoepelt.

Gebruik:
    python3 scripts/repareer_kifid_bronnen.py                       # alle records
    python3 scripts/repareer_kifid_bronnen.py --alleen 2026-0832    # alleen deze nummers
"""
import argparse, json, os, re, sys, io, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAD = os.path.join(ROOT, "corpus", "kifid.json")
UA = "Ai-assurantie-portaal/1.0 (corpusverificatie; publieke Kifid-bron)"

# Kopregel van elke Kifid-uitspraak: "Uitspraak Geschillencommissie Kifid nr. 2026-0742".
RE_NUMMER_KOP = re.compile(r"Kifid\s+nr\.?\s*(\d{4})\s*-\s*(\d{1,5})")


class NummerAfwijkt(ValueError):
    """Inhoudelijke uitkomst van de controle (geen netwerkfout): opnieuw proberen helpt niet."""


def nummer_letterlijk_in_tekst(nr, tekst):
    """De strenge eis: het nummer staat letterlijk, teken voor teken, in de PDF-tekst."""
    return bool(nr) and nr in tekst


def nummer_gedrukt(tekst):
    """Het nummer zoals de PDF het in de kopregel drukt (bijv. '2026-832'), of None."""
    m = RE_NUMMER_KOP.search(tekst)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def diagnose_nummer(nr, tekst):
    """Verklaart in een zin waarom het nummer niet letterlijk in de PDF-tekst staat.

    Dit is alleen uitleg bij een afwijzing; het oordeel zelf blijft `nummer_letterlijk_in_tekst`.
    """
    if len("".join(tekst.split())) < 200:
        return ("nummer niet in PDF-tekst: de PDF heeft (vrijwel) geen tekstlaag, mogelijk gescand; "
                "OCR is bewust niet toegepast")
    gedrukt = nummer_gedrukt(tekst)
    if gedrukt is None:
        return ("nummer niet in PDF-tekst: in de kop staat geen 'Kifid nr. ...' (afwijkende kop)")
    jaar, volg = (nr or "").partition("-")[::2]
    g_jaar, g_volg = gedrukt.split("-")
    if jaar == g_jaar and volg.isdigit() and int(volg) == int(g_volg):
        return (f"nummer niet letterlijk in PDF-tekst: de PDF drukt 'nr. {gedrukt}' (zonder voorloopnul), "
                f"het register en dit record gebruiken '{nr}'; de letterlijke controle is bewust niet "
                f"versoepeld, dus niet geverifieerd")
    return f"nummer niet in PDF-tekst: de PDF drukt 'nr. {gedrukt}', dit record heeft '{nr}' (ander nummer)"


def haal(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Controleer de PDF-bron van Kifid-records.")
    ap.add_argument("--alleen", nargs="+", metavar="NR",
                    help="controleer alleen deze uitspraaknummers; de overige records blijven onaangeroerd")
    args = ap.parse_args(argv)
    alleen = set(args.alleen or [])

    recs = json.load(open(PAD, encoding="utf-8"))
    onbekend = alleen - {d.get("uitspraaknummer") for d in recs}
    if onbekend:
        print(f"onbekend uitspraaknummer: {', '.join(sorted(onbekend))}", file=sys.stderr)
        return 2
    from pypdf import PdfReader

    ok = mis = verwerkt = 0
    for i, d in enumerate(recs, 1):
        nr, pdf = d.get("uitspraaknummer"), d.get("pdf_url")
        if alleen and nr not in alleen:
            continue
        verwerkt += 1

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
                if nummer_letterlijk_in_tekst(nr, tekst):
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
                    raise NummerAfwijkt(diagnose_nummer(nr, tekst))
                break
            except NummerAfwijkt as e:
                # De PDF is gelezen en het nummer klopt niet: dat verandert bij een nieuwe poging niet.
                d["bron_geverifieerd"] = False
                d["bron_verificatie_notitie"] = str(e)
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
    print(f"\n{ok} van {verwerkt} gecontroleerde uitspraken bevestigd via de PDF-bron", file=sys.stderr)
    if mis:
        print(f"{mis} NIET bevestigd - deze mogen niet als onderbouwing worden getoond",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
