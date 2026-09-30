// De twee soorten pagina's: het overzicht en de werkplek van één functie.
import { bouwFormulier } from "./formulier.js";
import { h, icoon, leeg } from "./dom.js";
import { aantal, meervoud } from "./format.js";
import { GROEPEN, HEEFT_BEREKENING, REGISTER } from "./registry.js";
import { Uitvoering } from "./uitvoering.js";

const PRINCIPES = [
  ["01", "Bronnen eerst", "Bij elk antwoord ziet u eerst welke wetsartikelen, uitspraken en clausules zijn opgehaald. Een verwijzing die daar niet in staat, wordt gemarkeerd."],
  ["02", "Cijfers uit code", "Bedragen, termijnen en classificaties komen uit code die u kunt narekenen, met de wettelijke grondslag erbij. Het taalmodel rekent niet."],
  ["03", "Citeer of weiger", "Is er geen bron, dan geeft het portaal geen inhoudelijk antwoord. Het zegt wat er ontbreekt en wat u kunt opvragen."],
];

export function renderOverzicht(ctx) {
  const wortel = h("div");
  wortel.append(h("section", { class: "kop" },
    h("p", { class: "kruimel" }, "Overzicht"),
    h("h1", null, "Antwoorden met een bron erbij"),
    h("p", { class: "lead" }, "Het portaal beantwoordt geen vraag zonder bron. Wetsartikelen, Kifid-uitspraken en polisclausules komen uit een geverifieerd corpus, bedragen en termijnen uit deterministische code, en het taalmodel formuleert alleen.")));
  wortel.append(h("section", { class: "principes", "aria-labelledby": "principes-titel" },
    h("h2", { id: "principes-titel", class: "alleen-lezers" }, "Drie uitgangspunten"),
    ...PRINCIPES.map(([nr, titel, tekst]) =>
    h("article", { class: "principe" }, h("span", { class: "principe-nr" }, nr), h("h3", null, titel), h("p", null, tekst)))));
  for (const groep of GROEPEN) {
    const lijst = ctx.functies.filter((f) => f.groep === groep);
    if (!lijst.length) continue;
    wortel.append(h("section", { class: "groep" }, h("h2", { class: "groep-titel" }, groep),
      h("div", { class: "kaartenrij" }, ...lijst.map((f) =>
        h("a", { class: "functiekaart", href: `#/f/${f.id}` },
          h("span", { class: "ico" }, icoon(REGISTER[f.id]?.icoon || "boek", 20)),
          h("span", null, h("b", null, f.naam), h("span", null, f.omschrijving)))))));
  }
  const s = ctx.status;
  const aantalVerzekeraars = new Set((ctx.producten || []).flatMap((p) => (p.varianten || []).map((v) => v.verzekeraar))).size;
  if (s) {
    const c = s.corpus || {};
    const blok = (titel, n, tekst) => h("div", { class: "corpusblok" }, h("h3", null, titel), h("div", { class: "cijfer" }, aantal(n)), h("p", null, tekst));
    wortel.append(h("section", { class: "groep" }, h("h2", { class: "groep-titel" }, "Wat er in het corpus zit"),
      h("div", { class: "kaart" }, h("div", { class: "kaart-body" }, h("div", { class: "corpusrij" },
        blok("Wetgeving", c.wetgeving?.records || 0, "artikelen uit de Wft, het BGfo en Boek 7 titel 17 BW, uit de officiële wetgevingsbron."),
        blok("Kifid-uitspraken", c.kifid?.records || 0, `Geschillencommissie, scheef naar 2026 en naar afwijzingen. ${c.kifid?.geweigerd_onbevestigde_bron || 0} records zijn geweigerd omdat hun bron niet klopte. Niet geschikt voor slagingspercentages.`),
        blok("Polisclausules", c.polisvoorwaarden?.records || 0,
          `letterlijk uit de openbare voorwaarden van ${aantalVerzekeraars ? meervoud(aantalVerzekeraars, "verzekeraar", "verzekeraars") : "verzekeraars"}, elk met de hash van het brondocument.`))))));
  }
  return wortel;
}

function leegResultaat(cfg, functie) {
  const berekend = HEEFT_BEREKENING.has(functie.id);
  return h("div", { class: "kaart leeg" }, h("div", { class: "kaart-body" },
    h("h2", null, "Zo werkt deze toets"),
    h("p", null, "Vul de gegevens in en start de toets. Het resultaat verschijnt hier, stap voor stap."),
    h("ol", { class: "leeg-stappen" },
      h("li", null, h("span", null, h("b", null, "Bronnen"), "Het portaal haalt de wetsartikelen, uitspraken en clausules op die bij uw invoer passen en toont ze vóór het antwoord.")),
      berekend ? h("li", null, h("span", null,
        h("b", null, functie.id === "precedentzoeker" ? "Verdeling" : functie.id === "klachtroute" ? "Termijnen" : "Berekening"),
        functie.id === "precedentzoeker" ? "De uitkomsten worden in het corpus geteld, niet door het model geschat."
          : functie.id === "klachtroute" ? "Vult u een klachtdatum in, dan rekent het portaal de termijnen uit art. 43 BGfo uit, met beide lezingen erbij. Het model rekent niet."
          : "Bedragen en termijnen komen uit code met de wettelijke grondslag erbij. Het model rekent niet.")) : null,
      h("li", null, h("span", null, h("b", null, "Toelichting"), "Het taalmodel formuleert het antwoord uitsluitend op basis van de opgehaalde bronnen.")),
      h("li", null, h("span", null, h("b", null, "Controle"), "Elke verwijzing in het antwoord wordt teruggezocht in de bronnen. Wat er niet in staat, wordt gemarkeerd."))),
    ));
}

/**
 * Wat er met de tekst gebeurt die de adviseur invult, alleen bij velden met vrije tekst: dat is wat naar het taalmodel gaat.
 * Bij een online aanbieder (OpenRouter) verlaat die tekst de computer; gratis modellen kunnen invoer bewaren en gebruiken.
 * Er is geen verwerkersovereenkomst met die aanbieders, dus geen klantgegevens invullen.
 */
function privacyRegel(cfg, rt) {
  const velden = cfg.velden.flatMap((v) => v.rij || [v]);
  if (!rt || !velden.some((v) => v.type === "lang" || v.type === "tekst")) return null;
  const tekst = rt.provider === "local"
    ? "Uw tekst blijft op deze computer: het lokale model draait zonder netwerk."
    : "Voer geen namen, adressen, BSN of medische gegevens van klanten in. Deze tekst gaat naar een externe aanbieder van taalmodellen; "
      + "gratis modellen kunnen invoer bewaren en gebruiken.";
  return h("p", { class: "privacy" }, icoon("slot", 14), h("span", null, tekst));
}

export function renderFunctie(id, ctx) {
  const functie = ctx.functies.find((f) => f.id === id);
  const cfg = REGISTER[id];
  if (!functie || !cfg) return h("div", { class: "melding fout" }, icoon("waarschuwing", 18), h("div", null, `Onbekende functie: ${id}`));
  const formulier = bouwFormulier(cfg, ctx.producten);
  const resultaat = h("div", { class: "resultaat", "aria-label": "Resultaat" }, leegResultaat(cfg, functie));
  let lopend = null;

  const knop = h("button", { class: "knop primair", type: "submit" }, "Toets uitvoeren");
  const stopKnop = h("button", { class: "knop", type: "button", hidden: true, onClick: () => lopend && lopend.stop() }, icoon("stop", 14), "Stop");
  const zetBezig = (bezig) => {
    const hadFocus = document.activeElement === knop || document.activeElement === stopKnop;
    knop.disabled = bezig;
    knop.replaceChildren(...(bezig ? [h("span", { class: "draaier" }), "Bezig…"] : ["Toets uitvoeren"]));
    stopKnop.hidden = !bezig;
    // Een uitgeschakelde of verborgen knop laat het toetsenbordfocus in het niets vallen: geef het door.
    if (hadFocus) (bezig ? stopKnop : knop).focus({ preventScroll: true });
  };

  const form = h("form", { class: "kaart invoer", novalidate: true,
    onSubmit: async (e) => {
      e.preventDefault();
      const gelezen = formulier.lees();
      if (gelezen.fouten) { formulier.eersteFout()?.focus(); return; }
      if (lopend && !lopend.klaar) lopend.stop();
      zetBezig(true);
      const smal = matchMedia("(max-width: 1180px)").matches;
      lopend = new Uitvoering(id, cfg, resultaat, () => { zetBezig(false); ctx.opKlaar && ctx.opKlaar(); }, ctx.status?.runtime);
      if (smal) resultaat.scrollIntoView({ behavior: "smooth", block: "start" });
      lopend.start(gelezen.invoer);
    } },
    h("div", { class: "kaart-kop" }, h("h2", null, "Invoer"),
      h("button", { class: "tekstknop", type: "button", onClick: () => formulier.zet(cfg.voorbeeld) }, "Voorbeeld invullen")),
    h("div", { class: "kaart-body" }, formulier.el, h("div", { class: "acties" }, knop, stopKnop), privacyRegel(cfg, ctx.status?.runtime)));

  const wortel = h("div");
  wortel.append(h("section", { class: "kop" },
    h("p", { class: "kruimel" }, `${functie.groep} · ${functie.naam}`),
    h("h1", null, functie.naam),
    h("p", { class: "lead" }, cfg.lead || functie.omschrijving)));
  wortel.append(h("div", { class: `werk${cfg.breed ? " breed" : ""}` }, form, resultaat));
  formulier.zet({});
  wortel.destroy = () => { if (lopend && !lopend.klaar) lopend.stop(); };
  return wortel;
}
