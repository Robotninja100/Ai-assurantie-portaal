# Instructie voor de blinde beoordelaar

Je beoordeelt schermen van webinterfaces op vormgeving. Je krijgt een map met genummerde beelden (A.png, B.png, ...)
en per viewport een `beoordeling.csv`. De beelden zijn geneutraliseerd: kleur is verwijderd (grijswaarden), logo's en
merknamen zijn onherkenbaar gemaakt, alle beelden zijn even breed. Je weet niet welk scherm van wie is en dat is de
bedoeling. **Raad niet en zoek niets op.** Als je denkt te herkennen om welk product het gaat, negeer dat en beoordeel
alleen wat je ziet. Kijk uitsluitend in de map die je is gegeven; open geen andere bestanden.

## Wat je beoordeelt

Vijf criteria, elk 1 tot en met 5. Gebruik de hele schaal. Een beoordeling waarin alles 3 is, is een mislukte beoordeling.

**hierarchie** - Weet je binnen twee seconden wat het belangrijkste is, wat daarna komt en wat bijzaak is?
1 = alles even zwaar, geen ingang. 3 = een duidelijk kopniveau maar de rest is vlak. 5 = onmiskenbare lees- en
prioriteitsvolgorde; de ogen weten waar te beginnen en waar te eindigen.

**typografie** - Maatvoering, gewicht, regelafstand, regellengte, cijfers en uitlijning.
1 = willekeurige maten en gewichten, onleesbare regels. 3 = leesbaar maar zonder herkenbare schaal. 5 = een
consistente schaal met weinig maten, rustige regellengte, cijfers netjes onder elkaar, koppen die echt koppen zijn.

**ritme en witruimte** - Afstanden tussen en binnen blokken, dichtheid, uitlijning op een raster.
1 = krap en rommelig of leeg en verloren, geen vast maatsysteem. 3 = grotendeels prettig maar met onverklaarbare
sprongen. 5 = herkenbaar maatsysteem, ruimte die groepeert, dichtheid die past bij de taak.

**consistentie** - Doen gelijke dingen er gelijk uit? Zelfde soort element, zelfde behandeling.
1 = elk blok een eigen stijl. 3 = meestal gelijk met uitzonderingen. 5 = een herkenbaar systeem van componenten
dat zichzelf herhaalt (kaarten, tabellen, knoppen, labels) zonder verrassingen.

**totaalindruk** - Zou je dit vertrouwen en willen gebruiken voor serieus werk?
1 = amateuristisch of afstotend. 3 = degelijk maar onopvallend. 5 = professioneel, rustig en zelfverzekerd.

## Wat je NIET meeweegt

De inhoud (of de tekst klopt), de bekendheid van het merk, kleur (die is weg), en of het scherm "mooi" is in de zin
van decoratie. Een druk scherm dat goed geordend is scoort hoger dan een leeg scherm zonder orde. Een marketingpagina
en een werkscherm beoordeel je op dezelfde criteria, maar houd rekening met wat het scherm probeert te zijn.

## Hoe je invult

1. Open elk beeld en kijk er echt naar (het hele beeld, ook onderaan).
2. Vul `beoordeling.csv` in: de kolommen `hierarchie_1_5, typografie_1_5, ritme_witruimte_1_5, consistentie_1_5,
   totaalindruk_1_5` met gehele getallen 1 tot en met 5, en `opmerking` met een korte zin over wat je scoorde
   (maximaal 20 woorden, zonder een vermoeden over de herkomst).
3. Beoordeel eerst alle beelden vluchtig om je schaal te ijken, en vul daarna pas in. Verander je schaal halverwege,
   ga dan terug en pas eerdere scores aan.
4. Laat geen cel leeg. Kun je een beeld niet beoordelen (onleesbaar, kapot), schrijf dat in `opmerking` en geef alle
   criteria 1.
5. Schrijf geen andere bestanden. Lever alleen de ingevulde CSV's af.
