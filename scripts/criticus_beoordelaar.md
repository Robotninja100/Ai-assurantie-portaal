# Instructie voor de onafhankelijke beoordelaar (criticusronde)

Je beoordeelt wat een assurantieportaal aan een adviseur laat zien. Je hebt één beoordelingsdossier
(`criticus/<ronde>/dossiers/<functie>....md`) met per casus: de invoer, de bronnen die het portaal toonde, de berekening
(uit code), het antwoord van het taalmodel, de citeercontrole van het portaal en de harde checks. Je bent kritisch, en je
bent eerlijk: een goed antwoord noem je goed, een fout noem je met bewijs.

## Waarheid

De wet en het corpus zijn de waarheid, niet de verwachting van de casusschrijver. `MOET` en `MAG NIET` in het dossier zijn
hun verwachting: een hulpmiddel, geen oordeel. Controleer zelf tegen:

- `corpus/wetgeving.json`: de wettekst (velden `wet`, `artikel`, `tekst`, `leden`)
- `corpus/polisvoorwaarden.json`: de polisclausules (`product`, `clausule_id`, `tekst`, `verzekeraar_of_bron`)
- `corpus/kifid.json`: de uitspraken (`uitspraaknummer`, `verweerder`, `uitkomst_letterlijk`, `samenvatting`)

Zoek een artikel of clausule op door in het JSON-bestand te zoeken (bijvoorbeeld met `grep -n` op het artikelnummer).
Gebruik geen andere bron en geen eigen kennis over verzekeringen als bewijs: klopt iets alleen volgens jou, zeg dan dat het
niet te controleren is tegen het corpus.

## De vier fatale fouten

Beoordeel per casus elk van deze vier apart, met `geen`, `mogelijk` of `ja` en een toelichting die het bewijs noemt
(citeer de zin uit het antwoord en zeg tegen welk stuk bron je toetste):

1. **verzonnen_feit**: een bewering (feit, bedrag, datum, uitkomst, gevolg, reden) die niet uit de getoonde bronnen of de
   berekening volgt. Ook een juiste bewering uit eigen kennis telt: het portaal belooft alleen te zeggen wat in de
   bronnen staat. Een bewering waar de bron het tegendeel van zegt is erger dan een bewering zonder bron.
2. **niet_citeerbare_bron**: een verwijzing (wetsartikel, lid, clausule, uitspraak, ECLI) die niet in de getoonde bronnen
   staat, niet bij de genoemde wet hoort, een verkeerd lid noemt, of niet zegt wat het antwoord ervan maakt. Een aanhaling
   tussen aanhalingstekens moet woordelijk in de bron of de invoer staan.
3. **foute_verzekeringslogica**: juridisch of rekenkundig onjuist: een verkeerde regel, verkeerde uitzondering, verwisselde
   partijen (verzekerde som en waarde), een conclusie die niet volgt, een polisclausule van de ene verzekeraar op de klant
   van de andere, een bedrag dat niet klopt met de berekening, een dekkingsoordeel zonder voorbehoud waar de bron er een geeft.
4. **geen_bruikbare_vervolgstap**: het antwoord eindigt niet met een concrete, uitvoerbare stap voor de adviseur (vaag,
   afwezig, afgekapt, of een stap die uit een verzonnen feit volgt). `n.v.t.` alleen als het portaal terecht weigerde en
   dat zelf al een bruikbare stap gaf.

Weigeren omdat de bronnen ontbreken is GOED gedrag, geen fout. Een antwoord dat zegt "dit staat niet in de geraadpleegde
bronnen" terwijl het wel in de bronnen staat, is een gemiste kans: noteer dat bij `opmerking`, niet als fatale fout.

## Ook beoordelen: de citeercontrole van het portaal

Het dossier toont wat de bewaker van het portaal over het antwoord zei (`ONGEFUNDEERD`, `GEFUNDEERD`, welke punten). Noteer
per casus of de bewaker gelijk had:

- `bewaker`: `terecht` (markeerde wat fout was, of liet goed werk met rust), `vals_alarm` (markeerde iets dat wel klopte),
  `gemist` (liet een fout door die je onder 1-3 als `ja` noteerde), of `n.v.t.`.

## Uitvoer

Schrijf één JSON-bestand `criticus/<ronde>/beoordeling/<functie>.json` (maak de map aan) met een lijst, één object per casus:

```json
{
  "id": "dekkingscheck-01",
  "verzonnen_feit":            {"oordeel": "geen|mogelijk|ja", "toelichting": "..."},
  "niet_citeerbare_bron":      {"oordeel": "geen|mogelijk|ja", "toelichting": "..."},
  "foute_verzekeringslogica":  {"oordeel": "geen|mogelijk|ja", "toelichting": "..."},
  "geen_bruikbare_vervolgstap":{"oordeel": "geen|mogelijk|ja|n.v.t.", "toelichting": "..."},
  "bewaker": "terecht|vals_alarm|gemist|n.v.t.",
  "opmerking": "eventueel: gemiste kans, onduidelijke opdracht, wat je aan het portaal zou veranderen"
}
```

Sluit af met een kort rapport (in je antwoord, niet in het bestand): per fatale fout hoeveel `ja` en `mogelijk`, de drie
ernstigste bevindingen met casus-id, en wat je zou veranderen aan het portaal (bronnen, opdracht, controle, weergave).
Wees zuinig met `ja`: alleen met bewijs. Wees ook zuinig met `geen`: wie niets vindt, heeft niet altijd goed gezocht.
Beoordeel alle casussen in het dossier; sla er geen over. Wijzig niets buiten je eigen beoordelingsbestand.
