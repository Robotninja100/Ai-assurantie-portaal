# AI-portaal voor Nederlandse assurantieprofessionals

Lees eerst `state.json`: daar staat wat er is, wat is geprobeerd en afgewezen, en waarom.

## Het uitgangspunt

Het model is hier niet de kennisbron. Het corpus levert de feiten, deterministische code
levert de cijfers, en het model levert alleen de Nederlandse formulering. Dat is geen
stijlkeuze maar een constructie-eis: zo zijn "verzonnen feit" en "niet-citeerbare bron"
mechanisch uitgesloten in plaats van hoopvol vermeden.

Vier lagen dwingen dat af:

1. **`backend/retrieval.py`** weigert elk corpusrecord waarvan de bron niet is bevestigd,
   ook als de inhoud zou kloppen.
2. **`backend/grounding.py`** controleert ná generatie elke verwijzing die het model uitspreekt
   (wetsartikel bij de juiste wet, uitspraak, clausule), elk bedrag, percentage en elke datum tegen
   de berekening, de invoer en de bronnen, en elke aanhaling tussen aanhalingstekens: die moet
   woordelijk in de invoer of de bronnen staan. Wat daar niet in staat, wordt op elke plek zichtbaar
   gemarkeerd, niet stil weggefilterd: dan ziet de adviseur het niet.
   Grens: de controle toont dat een verwijzing bestaat en een getal uit de berekening komt, niet dat
   de redenering eromheen klopt of dat een getal op de juiste plek staat. Daarom herschrijft het model
   waar de uitkomst uit code komt de uitleg uit die code (`Uitkomst.uitleg`) en bedenkt het geen redenen:
   een echte run met een klein lokaal model liet goede bedragen zien met een verzonnen uitleg eromheen.
3. **`scripts/valideer_grondslagen.py`** past dezelfde regel toe op onze eigen code en faalt
   als de rekenkern naar een artikel verwijst dat niet in het corpus staat.
4. **`tests/`**: de wettekst in het corpus is de bron van de verwachte waarden, niet de uitvoer
   van de code. Zo vond ronde 1 al fouten in de eigen rekenkern (zie `state.json`).

## Corpus

| Bron | Records | Verificatie |
|---|---|---|
| Wft, BGfo, BW Boek 7 titel 17 | 53 artikelen | officiële BWB-XML; alle 53 HTTP-geverifieerd |
| Kifid-uitspraken | 42 bruikbaar (5 geweigerd) | uitspraaknummer letterlijk teruggelezen uit de bron-PDF |
| Polisvoorwaarden | 119 clausules, 10 producten, 5 verzekeraars | sha256 per brondocument; elke tekst letterlijk uit de PDF gesneden |

Alles reproduceerbaar via de scrapers in `scripts/`. Het Kifid-corpus is klein, scheef naar 2026 en
naar afwijzingen, en alleen Geschillencommissie: nooit gebruiken voor uitspraken over slagingskansen.

## Opnamen voor de blinde meetlat

De meetlat legt onze schermen blind naast echte interfaces. Wat daarvoor op schijf staat, ligt in
`renders/`; de PNG's staan **niet** in git en zijn te herleiden met de scripts.

| Map | Inhoud | Script | Manifestvorm |
|---|---|---|---|
| `renders/comps/` | internationale echte interfaces en marketingpagina's | `capture_comps.py` | lijst van opnamerecords |
| `renders/comps_nl/` | Nederlandse financiële en administratieve pagina's | `capture_comps_nl.py` | object met `comps` en `overgeslagen` |
| `renders/decoy/` | vier zelfgemaakte assurantie-backofficeschermen (`zeer_zwak` tot `redelijk`) | `maak_decoy.py` | object met `decoys` en `bestanden` |
| `renders/anker/` | plafondanker: echte UI van uitzonderlijke kwaliteit (positieve controle) | `capture_anker.py` | object met `ankers` en `bestanden` |

**Schema van een opnamerecord** (volledig in de docstring van `scripts/capture_controle.py`): `bestand`,
`bron_naam`, `viewport_naam` (`desktop`/`mobile`), `klasse` (`product_ui` | `marketing` | `decoy` |
`anker`), `soort_scherm` (bijvoorbeeld `app`, `dashboard`, `zoekresultaten`, `docs`, `productpagina`),
`domein` (`nl_financieel` | `internationaal` | `decoy` | `anker`), `taal` (`nl` | `en`),
`geladen_ok` (bool), `afkeurredenen`, `controle` (de meetwaarden), `wat_het_toont`, en bij decoys
`kwaliteit` en `bewuste_zwaktes`. Alle vier de manifesten delen dit record; een lezer gebruikt
`lees_opnames(pad)` uit `capture_controle.py` en filtert op `geladen_ok`.

- **`klasse` is streng.** `product_ui` is een scherm waarin je iets opzoekt of doet met echte bediening
  (app, dashboard, dataviewer, register met zoekveld, filters en resultaten). `marketing` is een pagina om
  te informeren, te verkopen of naar een login te leiden (homepage, prijzen, productpagina, vergelijker-
  landing met invulwidget, inlogpoort), ook als er een mockup, screenshot of zoekveld in zit: een mockup
  is een illustratie en geen bruikbare interface. Documentatie-interfaces zijn echte UI maar geen
  bedieningsscherm; ze staan als `product_ui` met `soort_scherm: "docs"`, zodat een strikte ronde ze kan
  uitsluiten.

- **Vier manifestvormen, één leesfunctie.** `comps`: een lijst opnamerecords. `comps_nl`: een object met
  `comps` (per bron `bestanden.desktop` en `bestanden.mobile`, met de oude alias `file`) en `overgeslagen`
  (bronnen zonder PNG, met reden). `decoy` en `anker`: een object met `bestanden` (lijst opnamerecords) en
  beschrijvende velden (`decoys`, `ankers`, `motivatie`). Wie niet zelf wil uitpakken:
  ```python
  import sys; sys.path.insert(0, "scripts")
  from capture_controle import lees_opnames
  records = [r for r in lees_opnames("renders/decoy/manifest.json") if r["geladen_ok"] and r["bestand"]]
  ```
  De object-manifesten dragen dezelfde leeswijzer in het veld `leesvoorbeeld`.
- **`geladen_ok` volgt uit een meting, niet uit de bedoeling van de opnemer.** Elke PNG wordt na afloop
  gecontroleerd op te weinig inkt of tekst, grote lege banden, een cookiewall of modal (in het beeld én in
  de DOM), foutpagina's, botmuren en captcha's. Afgekeurde PNG's staan in `<map>/_afgekeurd/` en blijven
  met reden in het manifest.
- **`wat_het_toont` beschrijft wat is vastgelegd, niet wat het bedrijf verkoopt.** Het is het oordeel van de
  opnemer na inspectie (`geinspecteerd_op`). Een bewering over cookies staat alleen in `controle.cookies`
  en alleen als de overlay daarna gemeten weg was.
- **Er is geen echte vertegenwoordiger van een ingelogd Nederlands assurantie-backoffice.** Dat soort
  software zit achter een login of demo-aanvraag. Het veld `dekking_categorie` zegt dat in elk manifest.
- `python3 scripts/capture_controle.py --zelftest --met-browser` test de controle op synthetische en
  Chromium-fixtures; `--valideer renders/*/manifest.json` controleert het schema; `--controleer <map>`
  toont de meetwaarden per PNG. De capture-scripts hebben `--alleen-manifest` om het manifest zonder
  netwerk te herberekenen.

## Draaien

```bash
pip install -r requirements.txt
uvicorn api:app --app-dir backend --port 8000     # daarna http://127.0.0.1:8000
```

**Taalmodel.** Zet `OPENROUTER_API_KEY` in de omgeving of in `.env` (staat in `.gitignore`): gratis
modellen via OpenRouter met een terugvalketen, meestal een paar seconden per antwoord. Zonder sleutel
valt het portaal zichtbaar terug op een lokaal model, als dat in `models/qwen3-4b.gguf` staat (of
`ASSURANTIE_MODEL_PATH`): draait zonder netwerk maar duurt minuten per antwoord.

Gratis modellen komen en gaan: op 30 september 2026 bestonden drie van de vijf modellen uit de eerste keten niet
meer als gratis variant. Het portaal leest daarom bij gebruik de openbare modellenlijst van OpenRouter (geen
sleutel nodig, een uur onthouden) en probeert alleen modellen die er nog zijn; is de lijst niet te lezen, dan
geldt de ingestelde keten. Zet je zelf `ASSURANTIE_MODELLEN`, dan wordt die keten nooit aangepast, alleen gemeld.
Het begin van elk antwoord wordt vastgehouden tot het beoordeeld is: een model dat met uitgelekte redeneerstappen
of in het Engels begint wordt overgeslagen voordat de adviseur er iets van ziet. Welke modellen ooit zijn gemeten
en welke niet, staat bij `GEMETEN_GOED`, `ONGEMETEN` en `GEMETEN_LEKT` in `backend/llm.py`; de statusbalk toont
amber als het eerste model nog niet is gemeten. Met een sleutel meet `python3 scripts/probe_llm.py --live` de
gratis modellen van nu en stelt een keten voor (een rooktest met één opdracht, geen kwaliteitsmeting).

```bash
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
mkdir -p models && curl -L -o models/qwen3-4b.gguf \
  https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf
```

Zonder enig taalmodel toont het portaal nog steeds de bronnen en de berekening, en meldt het
eerlijk dat er geen antwoord kwam. Waar berekening, uitleg en vervolgstap volledig uit code komen
(schadeberekening, verjaringstoets, waardetoets, provisietoets, klachtroute met datum) schrijft het
kleine lokale model niets: een echte proef liet zien dat het daar redenen verzint. `ASSURANTIE_MODEL_ALTIJD=1`
dwingt het af, bijvoorbeeld voor onderzoek; een sterker model via OpenRouter herschrijft de uitleg wel.

## Privacy en klantgegevens

Wat je in een tekstveld invult (een schadesituatie, een dossier, een brief) gaat naar het taalmodel. Met OpenRouter is dat een
externe aanbieder: de tekst verlaat je computer, en gratis modellen kunnen invoer bewaren en gebruiken. Er is geen
verwerkersovereenkomst met die aanbieders. Vul daarom geen namen, adressen, BSN of medische gegevens van klanten in;
anonimiseer eerst. De interface zegt dat bij elk tekstveld. Het portaal zelf slaat niets op: geen database, geen cache, geen
logboek van invoer. Wie wel klantgegevens wil verwerken, gebruikt het lokale model (de tekst blijft op de machine) of een
aanbieder met een verwerkersovereenkomst, en legt dat voor aan de eigen functionaris gegevensbescherming.

## Testen

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests                      # unit-tests en browsertests (Chromium via Playwright), ruim 650 stuks
python3 scripts/valideer_grondslagen.py      # elke wetsverwijzing van de rekenkern staat in het corpus
python3 scripts/valideer_polisvoorwaarden.py # bronnen bereikbaar, hashes kloppen, tekst letterlijk uit de bron
python3 scripts/criticus_ronde.py deterministisch   # de rommelige casussen door bronnen en berekening
```

De browsertests doorlopen de hele keten (pagina, API, streaming, citeerbewaker). Daarin is alleen het
taalmodel een gemarkeerde testdouble (`tests/nep_llm.py`); die zegt niets over de kwaliteit van een echt model.

## Indeling

```
backend/    api.py (FastAPI + SSE), features.py (de twaalf functies), rekenkern.py, grounding.py,
            retrieval.py (BM25), llm.py (providers, echte streaming, modelketen)
frontend/   index.html, app.css (ontwerpsysteem), ES-modules zonder buildstap, Inter zelf gehost
corpus/     wetgeving, Kifid, polisvoorwaarden (JSON)
scripts/    scrapers en validatoren, de blinde A/B-meetlat, de criticusronde
tests/      unit-tests, browsertests, tests/casussen/ (rommelige casussen per functie)
```

## Meetlat (blinde A/B)

`scripts/blind_ab.py` bouwt een geblindeerde ronde (eigen schermen, comps, decoys en een anker) en
`scripts/blind_ab_rapport.py` leest de ingevulde beoordelingen. Het harnas weigert liever dan dat het
schijnbaar meet: exitcode 2 zonder eigen schermen (tenzij bewust `--zonder-eigen-schermen`; die ronde is
dan NIET-BRUIKBAAR-VOOR-OORDEEL), 3 als een merknaam na automatisch maskeren nog in de pixels leesbaar
is (OCR), 4 zonder werkende OCR-engine, 5 als de beeldhoogte of de lege ruimte onderaan de bron
verraadt; `--secties auto` (standaard) kiest daarom het aantal uitsneden (1-3) dat elk beeld helemaal
vult. Het rapport noemt een ronde ONGELDIG, en meldt dan geen winst, als het anker niet bovenaan of de
zwakste decoy niet onderaan staat, de decoys in de verkeerde kwaliteitsvolgorde staan, alle scores
(bijna) gelijk zijn of er cellen ontbreken. OCR is niet volledig (logo's zonder tekst leest hij niet):
bekijk de eindbeelden voordat ze naar de beoordelaar gaan. Het manifestcontract staat in de docstring
van `blind_ab.py`.

```bash
pip install -r requirements-dev.txt        # o.a. rapidocr-onnxruntime (OCR, geen GPU)
sudo apt-get install -y tesseract-ocr tesseract-ocr-nld tesseract-ocr-eng   # tweede mening, aanbevolen
python3 scripts/blind_ab.py --domein nl_financieel --ronde nl1 --seed 7 --eigen-namen "<productnaam>"
python3 scripts/blind_ab_rapport.py --ronde nl1
python3 scripts/blind_ab.py --zelftest && python3 -m pytest tests/test_meetlat_*.py
```

## Wat er nog niet is

De volledige lijst staat in `state.json` onder `openstaand_volgende_sessie`.
