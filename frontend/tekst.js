// Zet het antwoord van het taalmodel om in DOM-knopen: alinea's, (geneste) genummerde lijsten en
// opsommingen, tabellen, citaten, **vet**, *cursief*, `code`, en de verwijzingen die de citeerbewaker
// heeft gecontroleerd als klikbare chips. Alles gaat via tekstknopen; het model kan hier geen markup
// in de pagina krijgen.
import { h } from "./dom.js";

const KOP = /^\s{0,3}#{1,4}\s+(.*)$/;
const LIJST = /^(\s*)(?:([-*•])|(\d{1,2})[.)])\s+(.*)$/;      // een jaartal als "2024. Tekst" is geen lijstnummer
const CITAAT = /^\s{0,3}>\s?(.*)$/;
const TABELRIJ = /^\s*\|(.+)\|\s*$/;
const TABELSCHEIDING = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/;
const GETAL = new Set(["bedrag", "percentage", "datum"]);

const cellen = (r) => r.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

/** Een platte reeks lijstregels (met inspringing) wordt een boom van lijsten. */
function boom(items) {
  const wortel = { soort: items[0].soort, items: [] };
  const stapel = [{ indent: items[0].indent, lijst: wortel }];
  for (const r of items) {
    let top = stapel.at(-1);
    if (r.indent > top.indent && top.lijst.items.length) {           // dieper: sublijst onder het laatste punt
      const sub = { soort: r.soort, items: [] };
      top.lijst.items.at(-1).kinderen.push(sub);
      stapel.push({ indent: r.indent, lijst: sub });
    } else {
      while (stapel.length > 1 && r.indent < stapel.at(-1).indent) stapel.pop();
    }
    stapel.at(-1).lijst.items.push({ nr: r.nr, tekst: r.tekst, kinderen: [] });
  }
  return wortel;
}

function blokken(tekst) {
  const regels = tekst.replace(/\r/g, "").split("\n");
  const uit = [];
  let alinea = null;
  const sluit = () => { if (alinea) { uit.push(alinea); alinea = null; } };
  let i = 0;
  while (i < regels.length) {
    const r = regels[i];
    if (!r.trim()) { sluit(); i++; continue; }
    let m;
    if ((m = r.match(KOP))) { sluit(); uit.push({ t: "kop", tekst: m[1] }); i++; continue; }
    if (TABELRIJ.test(r) && i + 1 < regels.length && TABELSCHEIDING.test(regels[i + 1])) {
      sluit();
      const kop = cellen(r);
      i += 2;
      const rijen = [];
      while (i < regels.length && TABELRIJ.test(regels[i])) { rijen.push(cellen(regels[i])); i++; }
      uit.push({ t: "tabel", kop, rijen });
      continue;
    }
    if (CITAAT.test(r)) {
      sluit();
      const stuk = [];
      while (i < regels.length && CITAAT.test(regels[i])) { stuk.push(regels[i].match(CITAAT)[1]); i++; }
      uit.push({ t: "citaat", regels: stuk });
      continue;
    }
    if (LIJST.test(r)) {
      sluit();
      const items = [];
      while (i < regels.length) {
        const l = regels[i];
        const lm = l.match(LIJST);
        if (lm) {
          items.push({ indent: lm[1].replace(/\t/g, "    ").length, soort: lm[2] ? "ul" : "ol",
            nr: lm[3] ? Number(lm[3]) : null, tekst: lm[4] });
          i++;
          continue;
        }
        if (!l.trim()) {           // modellen zetten vaak een lege regel tussen genummerde punten: dat blijft één lijst
          let j = i;
          while (j < regels.length && !regels[j].trim()) j++;
          if (j < regels.length && j - i <= 2 && LIJST.test(regels[j])) { i = j; continue; }
          break;
        }
        if (KOP.test(l) || TABELRIJ.test(l) || CITAAT.test(l)) break;
        items.at(-1).tekst += " " + l.trim();           // voortzetting van het vorige punt
        i++;
      }
      uit.push({ t: "lijst", lijst: boom(items) });
      continue;
    }
    if (!alinea) alinea = { t: "p", regels: [] };
    alinea.regels.push(r.trim());
    i++;
  }
  sluit();
  return uit;
}

function regexUit(verwijzingen) {
  const alt = [...new Set(verwijzingen.map((v) => v.verwijzing))]
    .sort((a, b) => b.length - a.length)
    .map((v) => v.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  // Niet midden in een ander getal of woord ('12.8.3' bevat '2.8.3' niet), maar wel na 'art.' ('art.7:960').
  return alt.length ? new RegExp(`(?<![\\w:])(?<!\\d[.-])(${alt.join("|")})(?![\\w:])`, "gi") : null;
}

/** Splitst platte tekst in tekst en verwijzingschips. */
function metVerwijzingen(s, ctx) {
  if (!ctx.re) return [s];
  const uit = [];
  let laatste = 0;
  ctx.re.lastIndex = 0;
  for (let m; (m = ctx.re.exec(s)); ) {
    if (m.index > laatste) uit.push(s.slice(laatste, m.index));
    const info = ctx.perTekst.get(m[1].toLowerCase());
    const gefundeerd = info.status === "ok";
    if (info.soort === "citaat") {                     // aangehaalde tekst: woordelijk in de invoer of de bronnen, of niet
      uit.push(h("span", {
        class: `verw citaat ${gefundeerd ? "ok" : "slecht"}`,
        title: gefundeerd ? "Staat woordelijk in de invoer of de bronnen."
          : "Dit citaat staat NIET woordelijk in de invoer of de bronnen. Het model heeft het geparafraseerd of verzonnen; lees het in het origineel.",
      }, m[1]));
      laatste = m.index + m[0].length;
      continue;
    }
    if (GETAL.has(info.soort)) {                       // bedragen, percentages en datums: geen bron om naartoe te gaan
      uit.push(h("span", {
        class: `verw getal ${gefundeerd ? "ok" : "slecht"}`,
        title: gefundeerd ? "Staat in de berekening, de invoer of de bronnen."
          : "Dit getal komt NIET uit de berekening, de invoer of de bronnen. Reken het zelf na voordat je het gebruikt.",
      }, m[1]));
      laatste = m.index + m[0].length;
      continue;
    }
    uit.push(h("button", {
      class: `verw ${gefundeerd ? "ok" : "slecht"}`, type: "button",
      title: gefundeerd ? "Staat in de opgehaalde bronnen. Klik om de bron te tonen."
        : (info.reden ? `${info.reden}. ` : "") + "Staat NIET in de opgehaalde bronnen. Controleer deze verwijzing zelf voordat je haar gebruikt.",
      onClick: () => ctx.opKlik && ctx.opKlik(info),
    }, m[1]));
    laatste = m.index + m[0].length;
  }
  if (laatste < s.length) uit.push(s.slice(laatste));
  return uit;
}

// `code`, **vet** (mag *cursief* bevatten), *cursief*, en de invulvelden van de adviesnotitie.
const INLINE = /(`[^`]+`)|\*\*(?=\S)([\s\S]+?)(?<=\S)\*\*(?!\*)|(?<![*\w])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![*\w])|(\[AAN TE VULLEN[^\]]*\])/g;

function inline(s, ctx) {
  const uit = [];
  const re = new RegExp(INLINE.source, "g");        // een eigen regex per aanroep: strong roept inline() opnieuw aan
  let laatste = 0;
  for (let m; (m = re.exec(s)); ) {
    if (m.index > laatste) uit.push(...metVerwijzingen(s.slice(laatste, m.index), ctx));
    if (m[1]) uit.push(h("code", null, ...metVerwijzingen(m[1].slice(1, -1), ctx)));
    else if (m[2] !== undefined) uit.push(h("strong", null, ...inline(m[2], ctx)));
    else if (m[3] !== undefined) uit.push(h("em", null, ...metVerwijzingen(m[3], ctx)));
    else uit.push(h("span", { class: "invulveld" }, m[4]));
    laatste = m.index + m[0].length;
  }
  if (laatste < s.length) uit.push(...metVerwijzingen(s.slice(laatste), ctx));
  return uit;
}

function lijst(l, ctx) {
  const ol = l.soort === "ol";
  return h(l.soort, null, ...l.items.map((it) => h("li", ol && it.nr != null ? { stijl: `counter-set: n ${it.nr}` } : null,
    ol
      ? h("div", null, h("p", null, ...inline(it.tekst, ctx)), ...it.kinderen.map((k) => lijst(k, ctx)))
      : [h("p", null, ...inline(it.tekst, ctx)), ...it.kinderen.map((k) => lijst(k, ctx))])));
}

/**
 * @param {string} tekst        het antwoord
 * @param {Array}  verwijzingen [{verwijzing, soort, status: 'ok'|'slecht'}] uit de citeercontrole
 * @param {Function} opKlik     wordt aangeroepen met de verwijzing waarop is geklikt
 */
export function renderAntwoord(tekst, verwijzingen = [], opKlik = null) {
  const ctx = { re: regexUit(verwijzingen), opKlik, perTekst: new Map(verwijzingen.map((v) => [v.verwijzing.toLowerCase(), v])) };
  const wortel = h("div", { class: "antwoord" });
  for (const b of blokken(tekst)) {
    if (b.t === "kop") wortel.append(h("h4", null, ...inline(b.tekst, ctx)));
    else if (b.t === "p") wortel.append(h("p", null, ...b.regels.flatMap((r, i) => [i ? " " : null, ...inline(r, ctx)])));
    else if (b.t === "citaat") wortel.append(h("blockquote", null, h("p", null, ...b.regels.flatMap((r, i) => [i ? " " : null, ...inline(r, ctx)]))));
    else if (b.t === "tabel") {
      wortel.append(h("div", { class: "md-tabel" }, h("table", null,
        h("thead", null, h("tr", null, ...b.kop.map((c) => h("th", { scope: "col" }, ...inline(c, ctx))))),
        h("tbody", null, ...b.rijen.map((r) => h("tr", null, ...r.map((c) => h("td", null, ...inline(c, ctx)))))))));
    } else wortel.append(lijst(b.lijst, ctx));
  }
  return wortel;
}
