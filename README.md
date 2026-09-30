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

## Draaien

```bash
pip install -r requirements.txt
uvicorn api:app --app-dir backend --port 8000     # daarna http://127.0.0.1:8000
```

**Taalmodel.** Zet `OPENROUTER_API_KEY` in de omgeving of in `.env` (staat in `.gitignore`): gratis
modellen via OpenRouter met een terugvalketen, meestal een paar seconden per antwoord. Zonder sleutel
valt het portaal zichtbaar terug op een lokaal model, als dat in `models/qwen3-4b.gguf` staat (of
`ASSURANTIE_MODEL_PATH`): draait zonder netwerk maar duurt minuten per antwoord.

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

## Testen

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests                      # unit-tests en browsertests (Chromium via Playwright), ruim 270 stuks
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
