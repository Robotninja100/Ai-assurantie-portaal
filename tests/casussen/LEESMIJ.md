# Casussen voor de criticusronde

Per functie één bestand `<functie>.json`: een lijst van tien ROMMELIGE casussen zoals een assurantieadviseur
ze in de praktijk aanlevert (typefouten, ontbrekende feiten, tegenstrijdigheden, verkeerd product, grensdata,
te lang, buiten het corpus, een poging het model te sturen). Formaat per casus:

```json
{
  "id": "dekkingscheck-01",
  "functie": "dekkingscheck",
  "titel": "korte omschrijving van wat deze casus test",
  "rommeligheid": ["typefouten", "ontbrekende feiten"],
  "invoer": {"situatie": "...", "product": "..."},
  "verwachting": {
    "moet": ["toetsbare eigenschappen van een goed antwoord, in gewone taal"],
    "mag_niet": ["valkuilen; elke overtreding is een fout"],
    "harde_checks": {"berekening.bedrag": "43500.00"}
  },
  "bron_van_waarheid": "welk wetsartikel of welke clausule in het corpus deze verwachting draagt, of 'buiten corpus'"
}
```

`invoer` gebruikt EXACT de parameternamen van de functie in `backend/features.py`.
`harde_checks` zijn machine-toetsbaar op het API-resultaat (alleen voor de deterministische delen); sleutels
zijn paden in het `berekening`-object van de API (bijv. `bedrag`, `details.status`), `geweigerd: true` voor
een casus waar het portaal moet weigeren (geen bronnen, of onbepaalde uitkomst).
