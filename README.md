# AI-portaal voor Nederlandse assurantieprofessionals

Status: **fundering af, gebruikersinterface nog niet gebouwd.** Lees eerst `state.json` —
daar staat wat er is, wat is geprobeerd en afgewezen, en waarom.

## Het uitgangspunt

Het model is hier niet de kennisbron. Het corpus levert de feiten, deterministische code
levert de cijfers, en het model levert alleen de Nederlandse formulering. Dat is geen
stijlkeuze maar een constructie-eis: zo zijn "verzonnen feit" en "niet-citeerbare bron"
mechanisch uitgesloten in plaats van hoopvol vermeden.

Drie lagen dwingen dat af:

1. **`backend/retrieval.py`** weigert elk corpusrecord waarvan de bron niet is bevestigd,
   ook als de inhoud zou kloppen.
2. **`backend/grounding.py`** controleert ná generatie elke verwijzing die het model
   uitspreekt tegen de documenten die daadwerkelijk zijn opgehaald. Wat daar niet in staat,
   wordt zichtbaar gemarkeerd — niet stil weggefilterd, want dan ziet de adviseur het niet.
3. **`scripts/valideer_grondslagen.py`** past dezelfde regel toe op onze eigen code en faalt
   als de rekenkern naar een artikel verwijst dat niet in het corpus staat.

Die derde laag vond twee echte fouten in de rekenkern; zie `state.json` →
`eigen_fouten_gevonden_en_hersteld`.

## Corpus

| Bron | Records | Verificatie |
|---|---|---|
| Wft, BGfo, BW Boek 7 titel 17 | 53 artikelen | officiële BWB-XML; alle 53 HTTP-geverifieerd |
| Kifid-uitspraken | 46 bruikbaar (2 geweigerd) | uitspraaknummer letterlijk teruggelezen uit de bron-PDF |
| Polisvoorwaarden | 69 clausules, 9 producten | sha256 per brondocument |

Alles reproduceerbaar via de scrapers in `scripts/`.

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
pip install fastapi 'uvicorn[standard]' lxml pypdf llama-cpp-python
cp .env.voorbeeld .env      # en vul OPENROUTER_API_KEY in
uvicorn api:app --app-dir backend --port 8000
```

Zonder sleutel valt het portaal terug op een lokaal model (`ASSURANTIE_LLM_PROVIDER=local`),
dat draait zonder netwerk maar met RAG-context ongeveer honderd keer trager is.

## Wat er nog niet is

`frontend/` is leeg — `api.py` serveert een `index.html` die nog niet bestaat. De blinde
A/B-harnas en de decoy zijn nog in aanbouw. De criticusronden zijn niet gestart.
De volledige lijst staat in `state.json` → `openstaand_volgende_sessie`.
