// De uitkomst van de deterministische code, per functie op een eigen manier weergegeven.
// Alles wat hier staat komt uit backend/rekenkern.py; het taalmodel rekent nooit mee.
import { h, icoon } from "./dom.js";
import { aantal, dagenTussen, datum, eur, grondslagLabel, grondslagSleutel, korteDatum, meervoud, pct, vandaagIso } from "./format.js";

// ---------------------------------------------------------------- bouwstenen

export function grondslagChips(grondslag, opKlik) {
  if (!grondslag || !grondslag.length) return null;
  return h("div", null,
    h("div", { class: "chips-kop" }, "Wettelijke grondslag"),
    h("div", { class: "chips" }, ...grondslag.map((g) =>
      h("a", { class: "chip", href: "#", title: "Toon dit artikel in de bronnen",
        onClick: (e) => { e.preventDefault(); opKlik && opKlik({ verwijzing: grondslagSleutel(g) }); } }, grondslagLabel(g)))));
}

export function meldingen(lijst) {
  if (!lijst || !lijst.length) return null;
  return h("div", { class: "meldingen" }, ...lijst.map((t) =>
    h("div", { class: "melding" }, icoon("waarschuwing", 18), h("div", null, t))));
}

export function vervolgstap(tekst) {
  return tekst ? h("div", { class: "vervolg" }, h("h4", null, "Vervolgstap"), h("p", null, tekst)) : null;
}

function waarde(stap) {
  if (stap.uitkomst == null) return "";
  return stap.eenheid === "%" ? pct(stap.uitkomst) : eur(stap.uitkomst);
}

/** De rekenstappen zoals een adviseur ze op papier zou narekenen. */
export function grootboek(stappen, { slot = null, kop = "Rekenstappen" } = {}) {
  if (!stappen || !stappen.length) return null;
  const heeftBedragen = stappen.some((s) => s.uitkomst != null);
  const rijen = stappen.map((s, i) => h("tr", null,
    h("td", { class: "nr" }, String(i + 1)),
    h("td", null, s.omschrijving, s.formule ? h("span", { class: "formule" }, s.formule) : null),
    heeftBedragen ? h("td", { class: "uitkomst num" }, waarde(s)) : null));
  if (slot) rijen.push(h("tr", { class: "slot" }, h("td", { class: "nr" }), h("td", null, h("b", null, slot.omschrijving)),
    h("td", { class: "uitkomst num" }, slot.waarde)));
  return h("table", { class: "grootboek" },
    h("caption", null, kop),
    h("tbody", null, ...rijen));
}

function held(label, getal, onder, zij = null) {
  return h("div", { class: "held" },
    h("div", null, h("div", { class: "held-label" }, label), h("div", { class: "held-getal" }, getal),
      onder ? h("p", { class: "held-onder" }, onder) : null),
    zij ? h("div", { class: "held-zij" }, h("div", { class: "held-label" }, zij[0]), h("div", { class: "held-getal" }, zij[1])) : null);
}

/** De uitkomst in gewone zinnen, uit code: wat het taalmodel herschrijft en niet zelf bedenkt. */
function uitlegBlok(uitleg) {
  return uitleg && uitleg.length
    ? h("div", { class: "uitleg" }, h("h4", null, "In gewone woorden"), ...uitleg.map((t) => h("p", null, t)))
    : null;
}

function afsluiting(b, opKlik) {
  return [grondslagChips(b.grondslag, opKlik), meldingen(b.waarschuwingen), vervolgstap(b.volgende_stap)];
}

// ---------------------------------------------------------------- schadeberekening

/** De rekenkern kon niet rekenen (een sleutelfeit ontbreekt): geen heldgetal met een streepje maar de reden. */
function nietTeBerekenen(b, opKlik) {
  return h("div", null,
    h("div", { class: "oordeel let" },
      h("div", { class: "oordeel-icoon" }, icoon("waarschuwing", 22)),
      h("div", null, h("h4", null, "Niet te berekenen"),
        h("p", null, (b.waarschuwingen && b.waarschuwingen[0]) || "Er ontbreekt een gegeven om de berekening uit te voeren."))),
    b.waarschuwingen && b.waarschuwingen.length > 1 ? meldingen(b.waarschuwingen.slice(1)) : null,
    vervolgstap(b.volgende_stap));
}

function schade(b, opKlik) {
  if (b.bedrag == null) return nietTeBerekenen(b, opKlik);
  const d = b.details || {};
  const verzekerd = Number(d.verzekerd_pct ?? 100), onder = Number(d.onderverzekering_pct ?? 0);
  return h("div", null,
    held("Uitkering", eur(b.bedrag), b.toelichting),
    d.onderverzekerd ? h("div", { class: "balk-blok" },
      h("div", { class: "balk-kop" }, h("span", null, "Verzekerd deel van de waarde"), h("b", { class: "num" }, pct(verzekerd))),
      h("div", { class: "balk", role: "img", "aria-label": `${pct(verzekerd)} verzekerd, ${pct(onder)} onderverzekerd` },
        h("span", { class: "kleur-1", stijl: `width:${verzekerd}%` }), h("span", { class: "kleur-3", stijl: `width:${onder}%` })),
      h("ul", { class: "legenda" },
        h("li", null, h("i", { class: "kleur-1" }), "Verzekerd ", h("b", null, pct(verzekerd))),
        h("li", null, h("i", { class: "kleur-3" }), "Onderverzekering, voor rekening van de verzekerde ", h("b", null, pct(onder))))) : null,
    uitlegBlok(b.uitleg),
    grootboek(b.stappen, { slot: { omschrijving: "Uitkering", waarde: eur(b.bedrag) } }),
    ...afsluiting(b, opKlik));
}

// ---------------------------------------------------------------- waardetoets

function waardetoets(b, opKlik) {
  if (b.bedrag == null) return nietTeBerekenen(b, opKlik);
  const d = b.details || {};
  const dag = Number(d.dagwaarde_pct ?? 0), drempel = Number(d.drempel_pct ?? 0);
  const dagwaarde = d.toegepast === "dagwaarde";
  return h("div", null,
    held(dagwaarde ? "Vergoeding op dagwaarde" : "Vergoeding op nieuwwaarde", eur(b.bedrag), b.toelichting,
      ["Dagwaarde", eur(d.dagwaarde)]),
    h("div", { class: "balk-blok" },
      h("div", { class: "balk-kop" }, h("span", null, "Dagwaarde als deel van de nieuwwaarde"), h("b", { class: "num" }, pct(dag))),
      h("div", { class: "meter", role: "img", "aria-label": `Dagwaarde ${pct(dag)} van de nieuwwaarde, drempel ${pct(drempel)}` },
        h("span", { class: "meter-vul", stijl: `width:${Math.min(dag, 100)}%` }),
        h("span", { class: "meter-streep", stijl: `left:${Math.min(drempel, 100)}%` }),
        h("span", { class: "meter-etiket", stijl: `left:${Math.min(Math.max(drempel, 8), 92)}%` }, "Polisdrempel ", h("b", { class: "num" }, pct(drempel)))),
      h("div", { class: "meter-as" }, h("span", null, "0%"), h("span", null, "100% nieuwwaarde"))),
    uitlegBlok(b.uitleg),
    grootboek(b.stappen, { slot: { omschrijving: dagwaarde ? "Vergoeding (dagwaarde)" : "Vergoeding (nieuwwaarde)", waarde: eur(b.bedrag) } }),
    ...afsluiting(b, opKlik));
}

// ---------------------------------------------------------------- provisietoets

const PROVISIE = {
  VERBODEN: { toon: "fout", icoon: "kruis", titel: "Provisieverbod van toepassing", bedrag: "Opgegeven directe beloning, rechtstreeks door de klant betaald" },
  TOEGESTAAN_MET_TRANSPARANTIE: { toon: "ok", icoon: "vink", titel: "Provisie toegestaan, mits gemeld", bedrag: "Provisie over de jaarpremie" },
  ONBEPAALD: { toon: "let", icoon: "waarschuwing", titel: "Niet vast te stellen", bedrag: null },
};

function provisie(b, opKlik) {
  const d = b.details || {};
  const p = PROVISIE[d.status] || PROVISIE.ONBEPAALD;
  return h("div", null,
    h("div", { class: `oordeel ${p.toon}` },
      h("div", { class: "oordeel-icoon" }, icoon(p.icoon, 22)),
      h("div", null, h("h4", null, p.titel), h("p", null, b.toelichting))),
    b.bedrag != null && p.bedrag ? h("div", { stijl: "margin-top:24px" }, held(p.bedrag, eur(b.bedrag))) : null,
    grootboek(b.stappen),
    ...afsluiting(b, opKlik));
}

// ---------------------------------------------------------------- verjaringstoets

const VERJARING = {
  LOOPT: { toon: "ok", icoon: "klok", titel: "Nog niet verjaard" },
  GESTUIT: { toon: "info", icoon: "info", titel: "Verjaring gestuit: er loopt nu geen termijn" },
  VERJAARD: { toon: "fout", icoon: "kruis", titel: "Verjaard" },
  ONZEKER: { toon: "let", icoon: "waarschuwing", titel: "Niet vast te stellen zonder één feit" },
};

const KORT = { bekendheid: "Bekend", stuiting: "Aanspraak", reactie: "Reactie", einde_hoofdtermijn: "Einde hoofdtermijn",
  einde_nieuwe_termijn: "Einde nieuwe termijn", nu: "Peildatum", klacht: "Klacht", bevestiging: "Bevestiging uiterlijk",
  zes_weken: "6 wkn na bevestiging", acht_weken: "8 wkn na indienen", verzoek: "Verzoek om info", ontvangen: "Info ontvangen",
  verlengd: "Na verlenging" };
const KADER_BREEDTE = 620;           // aanname voor de botsingsberekening; labels hebben een vaste pixelbreedte

/**
 * Tijdlijn met een spoor en labels in rijen. Labels die elkaar zouden raken gaan naar een andere
 * rij (twee boven, twee onder het spoor) in plaats van over elkaar te schrijven.
 */
function tijdlijn(d) {
  const punten = (d.gebeurtenissen || []).map((e) => ({ ...e }));
  if (d.peildatum) punten.push({ datum: d.peildatum, soort: "nu", label: "Peildatum" });
  const tijden = punten.map((p) => Date.parse(`${p.datum}T12:00:00`));
  const min = Math.min(...tijden), max = Math.max(...tijden);
  const span = Math.max(max - min, 86400000 * 30);
  const pos = (iso) => 5 + ((Date.parse(`${iso}T12:00:00`) - min) / span) * 90;      // 5..95%
  const gesorteerd = punten.sort((a, b) => a.datum.localeCompare(b.datum));

  const RIJEN = [{ zijde: "boven", rij: 0 }, { zijde: "onder", rij: 0 }, { zijde: "boven", rij: 1 }, { zijde: "onder", rij: 1 }];
  const bezet = RIJEN.map(() => []);
  const plaats = (x, breedte) => {
    for (let i = 0; i < RIJEN.length; i++) {
      if (bezet[i].every(([lo, hi]) => x + breedte / 2 + 8 < lo || x - breedte / 2 - 8 > hi)) {
        bezet[i].push([x - breedte / 2, x + breedte / 2]);
        return RIJEN[i];
      }
    }
    return RIJEN[RIJEN.length - 1];
  };

  const kader = h("div", { class: "spoor-kader", "aria-hidden": "true" }, h("div", { class: "spoor-lijn" }));
  if (d.laatste_dag && d.status !== "GESTUIT") {
    // Na een geldige reactie loopt de NIEUWE termijn vanaf die reactie; anders loopt de hoofdtermijn vanaf de bekendheid.
    const geb = d.gebeurtenissen || [];
    const start = geb.some((e) => e.soort === "einde_nieuwe_termijn")
      ? geb.find((e) => e.soort === "reactie") : geb.find((e) => e.soort === "bekendheid");
    const van = start ? pos(start.datum) : 5;
    kader.append(h("div", { class: "spoor-loop", stijl: `left:${van}%;width:${Math.max(pos(d.laatste_dag) - van, 0)}%` }));
  }
  for (const p of gesorteerd) {
    const soort = p.soort === "nu" ? "nu" : p.soort.startsWith("einde") ? "einde" : p.soort === "stuiting" ? "stuit" : "";
    const naam = KORT[p.soort] || p.label;
    const tekst = korteDatum(p.datum);
    const breedte = Math.max(naam.length, tekst.length) * 6.6 + 8;
    const x = (pos(p.datum) / 100) * KADER_BREEDTE;
    const lane = plaats(x, breedte);
    const links = Math.min(Math.max(pos(p.datum), (breedte / 2 / KADER_BREEDTE) * 100), 100 - (breedte / 2 / KADER_BREEDTE) * 100);
    kader.append(h("div", { class: `spoor-punt ${soort}`, stijl: `left:${pos(p.datum)}%`, title: `${p.label}: ${datum(p.datum)}` }),
      h("div", { class: `spoor-etiket ${lane.zijde} rij-${lane.rij}`, stijl: `left:${links}%` }, h("b", null, naam), tekst));
  }
  return h("div", { class: "tijdlijn" }, kader,
    h("ol", { class: "gebeurtenissen" }, ...gesorteerd.map((p) =>
      h("li", null, h("time", { datetime: p.datum }, datum(p.datum)), h("span", null, p.label)))));
}

function verjaring(b, opKlik) {
  const d = b.details || {};
  const v = VERJARING[d.status] || VERJARING.ONZEKER;
  const dagen = d.dagen_resterend;
  const kop = d.status === "LOOPT" && dagen != null && dagen < 90 ? "let" : v.toon;
  return h("div", null,
    h("div", { class: `oordeel ${kop}` },
      h("div", { class: "oordeel-icoon" }, icoon(v.icoon, 22)),
      h("div", null, h("h4", null, v.titel), h("p", null, b.toelichting))),
    d.laatste_dag ? h("div", { stijl: "margin-top:24px" }, held("Laatste dag om te stuiten", datum(d.laatste_dag),
      d.status === "LOOPT" ? (dagen === 0 ? "Dat is vandaag." : `Nog ${meervoud(dagen, "dag", "dagen")}. Vanaf ${datum(d.eerste_verjaarde_dag)} is de vordering verjaard.`)
        : d.status === "VERJAARD" ? `Vanaf ${datum(d.eerste_verjaarde_dag)} is de vordering verjaard.` : null)) : null,
    d.voorwaardelijk_alternatief ? h("div", { class: "melding info", stijl: "margin-top:16px" }, icoon("info", 18),
      h("div", null, h("b", null, "Voorwaardelijk: "), d.voorwaardelijk_alternatief.voorwaarde)) : null,
    tijdlijn(d),
    grootboek(b.stappen, { kop: "Hoe deze data zijn bepaald" }),
    ...afsluiting(b, opKlik));
}

// ---------------------------------------------------------------- klachtroute (art. 43 BGfo)

function klacht(b, opKlik) {
  const d = b.details || {};
  const toon = d.kan_naar_geschilleninstantie ? "ok" : d.afhankelijk_van_de_lezing ? "let" : "info";
  const titel = d.kan_naar_geschilleninstantie ? "Naar de geschilleninstantie kan"
    : d.afhankelijk_van_de_lezing ? "Hangt af van de lezing van art. 43 lid 3" : "Nog niet naar de geschilleninstantie";
  const gebeurtenissen = [
    { datum: d.klacht, soort: "klacht", label: "Klacht ingediend" },
    { datum: d.bevestiging_uiterlijk, soort: "bevestiging", label: "Uiterlijk bevestigen en termijn melden (lid 2)" },
    ...(d.zes_weken_na_bevestiging ? [{ datum: d.zes_weken_na_bevestiging, soort: "zes_weken", label: "Zes weken na de ontvangstbevestiging (lid 3)" }] : []),
    { datum: d.acht_weken_na_indienen, soort: "acht_weken", label: "Acht weken na het indienen van de klacht (lid 3)" },
    ...(d.verzoek ? [{ datum: d.verzoek, soort: "verzoek", label: "De verzekeraar vraagt de klager om nadere informatie (lid 4)" }] : []),
    ...(d.ontvangen ? [{ datum: d.ontvangen, soort: "ontvangen", label: "De gevraagde informatie is ontvangen" }] : []),
    ...(d.verlengde_data || []).map((e) => ({ ...e, soort: "verlengd" })),
  ];
  return h("div", null,
    h("div", { class: `oordeel ${toon}` },
      h("div", { class: "oordeel-icoon" }, icoon(d.kan_naar_geschilleninstantie ? "vink" : "klok", 22)),
      h("div", null, h("h4", null, titel), h("p", null, b.toelichting))),
    tijdlijn({ gebeurtenissen, peildatum: d.peildatum, status: "KLACHT" }),
    grootboek(b.stappen, { kop: "Hoe deze data zijn bepaald" }),
    ...afsluiting(b, opKlik));
}

// ---------------------------------------------------------------- precedentzoeker

const SEGMENT = ["kleur-1", "kleur-a", "kleur-2", "kleur-3"];

function verdeling(b) {
  const telling = Object.entries(b.telling || {}).sort((a, c) => c[1] - a[1]);
  const totaal = b.aantal_uitspraken || telling.reduce((s, [, n]) => s + n, 0);
  if (!totaal) return h("p", { class: "hint" }, "Geen vergelijkbare uitspraken gevonden.");
  return h("div", null,
    held("Gevonden vergelijkbare uitspraken", aantal(totaal), "Verdeling van de uitkomsten zoals Kifid ze zelf formuleert."),
    h("div", { class: "balk-blok" },
      h("div", { class: "balk", role: "img", "aria-label": telling.map(([k, n]) => `${n}× ${k}`).join(", ") },
        ...telling.map(([, n], i) => h("span", { class: SEGMENT[i % SEGMENT.length], stijl: `width:${(n / totaal) * 100}%` }))),
      h("ul", { class: "legenda" }, ...telling.map(([k, n], i) =>
        h("li", null, h("i", { class: SEGMENT[i % SEGMENT.length] }), k.charAt(0).toUpperCase() + k.slice(1), " ", h("b", null, aantal(n)))))),
    b.let_op ? h("div", { class: "melding info", stijl: "margin-top:24px" }, icoon("info", 18), h("div", null, h("b", null, "Let op: "), b.let_op)) : null);
}

// ---------------------------------------------------------------- toegang

export function renderBerekening(functie, b, opKlik) {
  switch (functie) {
    case "schadeberekening": return schade(b, opKlik);
    case "waardetoets": return waardetoets(b, opKlik);
    case "provisietoets": return provisie(b, opKlik);
    case "verjaringstoets": return verjaring(b, opKlik);
    case "precedentzoeker": return verdeling(b);
    case "klachtroute": return klacht(b, opKlik);
    default: return grootboek(b.stappen);
  }
}
