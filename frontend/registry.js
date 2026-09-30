// Per functie: hoe het formulier eruitziet, welke voorbeeldinvoer er is en welke weergave hoort bij
// het resultaat. De namen en groepen komen van /api/functies; dit bestand voegt de invoer toe.
//
// Veldtypen: lang (tekstvak), tekst, bedrag, getal, datum, keuze (lijst uit het corpus), invoerkeuze
// (tekst met suggesties), schakelaar.

const MAX_TEKENS = 6000;          // zo veel van een dossier of brief leest de backend; dat zeggen we erbij

export const PRODUCT_SUGGESTIES = [
  "betalingsbeschermer", "complex product", "hypothecair krediet",
  "individuele arbeidsongeschiktheidsverzekering", "overlijdensrisicoverzekering",
  "premiepensioenvordering", "uitvaartverzekering", "levensverzekering",
  "arbeidsongeschiktheidsverzekering", "autoverzekering", "opstalverzekering", "inboedelverzekering",
  "aansprakelijkheidsverzekering", "rechtsbijstandverzekering", "reisverzekering",
];

export const GROEPEN = ["Schade", "Geschil", "Compliance", "Advies"];

export const REGISTER = {
  dekkingscheck: {
    icoon: "schild", breed: false, bronnenEerst: true,
    lead: "Toets een schadesituatie tegen de polisclausules. Het portaal laat zien welke clausules raken aan de situatie, of ze wijzen op dekking of uitsluiting, en welke feiten nog ontbreken.",
    velden: [
      { id: "situatie", label: "Schadesituatie", type: "lang", rijen: 7, verplicht: true,
        hint: "Wat is er gebeurd, wanneer, en wat is beschadigd of vermist? Noem ook wat de klant zelf heeft gedaan." },
      { id: "product", label: "Product", type: "keuze", bron: "producten", leeg: "Niet opgegeven",
        hint: "Met een product zoekt het portaal alleen in de voorwaarden van die productsoort." },
      { id: "verzekeraar", label: "Verzekeraar", type: "keuze", bron: "verzekeraars", leeg: "Niet opgegeven", optioneel: true,
        hint: "Met een verzekeraar staan alleen zijn voorwaarden erbij. Noemt de schadesituatie de verzekeraar, dan leest het portaal die zelf." },
    ],
    voorbeeld: {
      situatie: "De klant meldt dat er afgelopen weekend is ingebroken terwijl hij een week op vakantie was. De dader kwam binnen via een openstaand raam op de eerste verdieping en heeft een laptop en sieraden meegenomen.",
      product: "inboedelverzekering", verzekeraar: "Klaverblad",
    },
  },
  precedentzoeker: {
    icoon: "weegschaal", breed: false,
    lead: "Vind vergelijkbare Kifid-uitspraken en zie hoe ze zijn afgelopen. De verdeling wordt geteld in het corpus, niet geschat door het model.",
    velden: [
      { id: "geschil", label: "Geschil", type: "lang", rijen: 7, verplicht: true,
        hint: "Beschrijf waar de verzekeraar en de klant het over oneens zijn." },
    ],
    voorbeeld: {
      geschil: "De verzekeraar weigert de vergoeding van waterschade door een gesprongen leiding. Volgens de verzekeraar had de klant achterstallig onderhoud moeten verhelpen.",
    },
  },
  schadeberekening: {
    icoon: "rekenmachine", breed: false,
    lead: "Bereken de uitkering bij onderverzekering, met eigen risico en bereddingskosten. Elke stap is na te rekenen en heeft zijn wettelijke grondslag.",
    velden: [
      { id: "verzekerde_som", label: "Verzekerde som", type: "bedrag", verplicht: true },
      { id: "werkelijke_waarde", label: "Werkelijke waarde", type: "bedrag", verplicht: true,
        hint: "Herbouw- of vervangingswaarde op het moment van de schade." },
      { id: "schade", label: "Schade", type: "bedrag", verplicht: true },
      { rij: [
        { id: "eigen_risico", label: "Eigen risico", type: "bedrag", optioneel: true },
        { id: "bereddingskosten", label: "Bereddingskosten", type: "bedrag", optioneel: true },
      ] },
    ],
    voorbeeld: { verzekerde_som: "200.000", werkelijke_waarde: "250.000", schade: "50.000", eigen_risico: "500", bereddingskosten: "5.000" },
  },
  verjaringstoets: {
    icoon: "zandloper", breed: false,
    lead: "Loopt de termijn nog, en tot wanneer? Volgens art. 7:942 BW, met de stuiting en de nieuwe termijn die daarop volgt.",
    velden: [
      { id: "datum_bekend", label: "Bekend met de opeisbaarheid", type: "datum", verplicht: true,
        hint: "De dag waarop de gerechtigde wist dat uitkering kon worden gevraagd. Twijfel je, neem dan de vroegste aannemelijke dag." },
      { id: "datum_stuiting", label: "Eerste schriftelijke aanspraak", type: "datum", optioneel: true,
        hint: "Schademelding, brief of e-mail waarin uitkering wordt gevraagd." },
      { id: "datum_reactie", label: "Erkenning of afwijzing door de verzekeraar", type: "datum", optioneel: true },
      { id: "aansprakelijkheid", label: "Aansprakelijkheidsverzekering", type: "schakelaar",
        hint: "Bij een aansprakelijkheidsverzekering stuit iedere onderhandeling (art. 7:942 lid 3)." },
      { id: "peildatum", label: "Peildatum", type: "datum", optioneel: true, hint: "Leeg is vandaag. Vul een datum in voor een wat-als." },
    ],
    voorbeeld: { datum_bekend: "2024-03-10", datum_stuiting: "2024-06-01", datum_reactie: "2024-09-15", aansprakelijkheid: false },
  },
  provisietoets: {
    icoon: "procent", breed: false,
    lead: "Mag dit product op provisiebasis worden beloond? De toets volgt art. 86c en 86d BGfo en zegt het als de classificatie uit het corpus niet is vast te stellen.",
    velden: [
      { id: "producttype", label: "Producttype", type: "invoerkeuze", verplicht: true,
        hint: "Kies uit de lijst of typ zelf, bijvoorbeeld ‘hypotheek’ of ‘AOV’." },
      { id: "jaarpremie", label: "Jaarpremie", type: "bedrag", optioneel: true },
      { rij: [
        { id: "provisiepercentage", label: "Provisie", type: "getal", eenheid: "%", achter: true, optioneel: true },
        { id: "directe_beloning", label: "Directe beloning", type: "bedrag", optioneel: true },
      ] },
    ],
    voorbeeld: { producttype: "opstalverzekering", jaarpremie: "600", provisiepercentage: "15", directe_beloning: "" },
  },
  dossiercheck: {
    icoon: "dossier", breed: true,
    lead: "Toets een adviesdossier op de zorgplichtvereisten. Het belangrijkste deel is wat ontbreekt.",
    velden: [
      { id: "dossiertekst", label: "Adviesdossier", type: "lang", rijen: 14, verplicht: true, max: MAX_TEKENS,
        hint: `Plak de tekst van het dossier. Het portaal leest de eerste ${MAX_TEKENS.toLocaleString("nl-NL")} tekens.` },
    ],
    voorbeeld: {
      dossiertekst: "Klant: echtpaar, beiden 41 jaar, twee kinderen (8 en 11). Woonhuis met hypotheek van 340.000 euro. Klant vraagt om een premievriendelijke arbeidsongeschiktheidsverzekering. Advies: AOV bij Verzekeraar X met een verzekerd bedrag van 30.000 euro per jaar, eigen risicotermijn 30 dagen. Motivatie: de klant wil een lage premie. Advies mondeling besproken op 3 september 2026. Polisvoorwaarden zijn meegestuurd.",
    },
  },
  polisvergelijker: {
    icoon: "kolommen", breed: false, tweeKanten: true,
    lead: "Zet de clausules van twee producten naast elkaar. Waar een kant geen clausule heeft, staat dat er; het gat wordt niet gevuld.",
    velden: [
      { id: "product_a", label: "Variant A", type: "keuze", bron: "varianten", verplicht: true },
      { id: "product_b", label: "Variant B", type: "keuze", bron: "varianten", verplicht: true },
    ],
    voorbeeld: { product_a: "autoverzekering (WA/casco) · Klaverblad", product_b: "autoverzekering (WA/casco) · Interpolis" },
  },
  klachtroute: {
    icoon: "bord", breed: false,
    lead: "Welke stap is nu aan de orde, welke termijnen gelden en wat moet er mee? Een termijn die niet in de bronnen staat wordt niet genoemd.",
    velden: [
      { id: "situatie", label: "Situatie", type: "lang", rijen: 6, verplicht: true },
      { id: "datum_klacht", label: "Datum van de klacht", type: "datum", optioneel: true,
        hint: "Met een datum berekent het portaal de termijnen uit art. 43 BGfo." },
      { id: "datum_bevestiging", label: "Datum van de ontvangstbevestiging", type: "datum", optioneel: true },
      { id: "datum_verzoek", label: "Verzoek om nadere informatie (datum)", type: "datum", optioneel: true,
        hint: "Vroeg de verzekeraar de klager om meer informatie? Dan worden de termijnen verlengd (art. 43 lid 4)." },
      { rij: [
        { id: "termijn_dagen", label: "Termijn om te antwoorden", type: "getal", eenheid: "dagen", achter: true, optioneel: true },
        { id: "datum_ontvangen", label: "Informatie ontvangen op", type: "datum", optioneel: true },
      ] },
      { id: "intern_afgehandeld", label: "Interne klachtprocedure doorlopen", type: "schakelaar",
        hint: "Zet dit aan als de verzekeraar de klacht intern al heeft afgehandeld." },
    ],
    voorbeeld: {
      situatie: "De klant is het niet eens met de afwijzing van een inboedelclaim. De verzekeraar stuurde op 12 augustus 2026 een definitieve afwijzing. Er is nog geen klacht ingediend.",
      datum_klacht: "2026-09-01", datum_bevestiging: "2026-09-10", intern_afgehandeld: false,
    },
  },
  afwijzingsanalyse: {
    icoon: "brief", breed: true,
    lead: "Houdt de afwijzingsgrond van de verzekeraar stand? Het portaal zoekt in de bronnen of de grond wordt gedragen, en zegt het eerlijk als de afwijzing terecht lijkt.",
    velden: [
      { id: "brieftekst", label: "Afwijzingsbrief", type: "lang", rijen: 14, verplicht: true, max: MAX_TEKENS,
        hint: `Plak de tekst van de brief. Het portaal leest de eerste ${MAX_TEKENS.toLocaleString("nl-NL")} tekens.` },
    ],
    voorbeeld: {
      brieftekst: "Geachte heer De Vries,\n\nOp 14 juli 2026 heeft u een schade gemeld aan uw inboedel na een inbraak. Wij hebben uw claim beoordeeld en moeten u helaas meedelen dat wij de schade niet vergoeden. Uit ons onderzoek blijkt dat de woning bij de inbraak niet deugdelijk was afgesloten: het raam op de eerste verdieping stond open. Daarmee heeft u de voorzorgsmaatregelen uit de polisvoorwaarden niet nageleefd.\n\nWij vertrouwen erop u hiermee voldoende te hebben geïnformeerd.\n\nMet vriendelijke groet,\nSchadeafdeling",
    },
  },
  adviesnotitie: {
    icoon: "notitie", breed: true, document: true,
    lead: "Stel een dossiernotitie op met de verplichte elementen. Wat de adviseur niet heeft aangeleverd blijft leeg en wordt gemarkeerd; er wordt niets verzonnen.",
    velden: [
      { id: "klantsituatie", label: "Klantsituatie", type: "lang", rijen: 6, verplicht: true },
      { id: "advies", label: "Gegeven advies", type: "lang", rijen: 5, verplicht: true },
    ],
    voorbeeld: {
      klantsituatie: "Jong gezin met twee kinderen, koopwoning uit 2019, één inkomen als zelfstandige. Vraagt naar dekking bij arbeidsongeschiktheid.",
      advies: "Individuele arbeidsongeschiktheidsverzekering met een eigen risicotermijn van 90 dagen; de klant heeft een buffer van drie maanden.",
    },
  },
  waardetoets: {
    icoon: "meter", breed: false,
    lead: "Nieuwwaarde of dagwaarde? Het portaal rekent de dagwaarde uit en zet die naast de drempel uit de polis. Die drempel staat in de polisvoorwaarden, niet in de wet.",
    velden: [
      { id: "nieuwwaarde", label: "Nieuwwaarde", type: "bedrag", verplicht: true },
      { rij: [
        { id: "ouderdom_jaren", label: "Ouderdom", type: "getal", eenheid: "jaar", achter: true, verplicht: true },
        { id: "levensduur_jaren", label: "Levensduur", type: "getal", eenheid: "jaar", achter: true, verplicht: true },
      ] },
      { id: "drempel_pct", label: "Polisdrempel", type: "getal", eenheid: "%", achter: true, optioneel: true, standaard: "40",
        hint: "Het percentage van de nieuwwaarde waaronder op dagwaarde wordt afgewikkeld. Lees het in de polisvoorwaarden." },
    ],
    voorbeeld: { nieuwwaarde: "2.000", ouderdom_jaren: "8", levensduur_jaren: "10", drempel_pct: "40" },
  },
  begripsuitleg: {
    icoon: "boek", breed: false,
    lead: "Wat zegt de bron letterlijk over dit begrip? Staat het niet in de bronnen, dan legt het portaal het ook niet uit eigen kennis uit.",
    velden: [
      { id: "begrip", label: "Begrip", type: "tekst", verplicht: true, hint: "Bijvoorbeeld ‘onderverzekering’, ‘mededelingsplicht’ of ‘bereddingskosten’." },
    ],
    voorbeeld: { begrip: "onderverzekering" },
  },
};

export const HEEFT_BEREKENING = new Set(["schadeberekening", "verjaringstoets", "provisietoets", "waardetoets", "precedentzoeker", "klachtroute"]);

/** De klachtroute rekent alleen als er een klachtdatum is; de andere functies altijd. */
export const heeftBerekening = (id, invoer) => HEEFT_BEREKENING.has(id) && (id !== "klachtroute" || !!(invoer && invoer.datum_klacht));
