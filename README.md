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
