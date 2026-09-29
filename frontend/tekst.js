// Zet het antwoord van het taalmodel om in DOM-knopen: alinea's, genummerde lijsten, opsommingen,
// **vet**, `code`, en de verwijzingen die de citeerbewaker heeft gecontroleerd als klikbare chips.
// Alles gaat via tekstknopen; het model kan hier geen markup in de pagina krijgen.
import { h } from "./dom.js";

const KOP = /^\s{0,3}#{1,4}\s+(.*)$/;
const NUMMER = /^\s*(\d+)[.)]\s+(.*)$/;
const PUNT = /^(\s*)[-*•]\s+(.*)$/;
const GETAL = new Set(["bedrag", "percentage", "datum"]);

function blokken(tekst) {
  const uit = [];
  let huidig = null;
  const sluit = () => { if (huidig) { uit.push(huidig); huidig = null; } };
  for (const r of tekst.replace(/\r/g, "").split("\n")) {
    if (!r.trim()) { sluit(); continue; }
    let m;
    if ((m = r.match(KOP))) { sluit(); uit.push({ t: "kop", tekst: m[1] }); continue; }
    if ((m = r.match(NUMMER))) {
      if (!huidig || huidig.t !== "ol") { sluit(); huidig = { t: "ol", items: [] }; }
      huidig.items.push({ nr: Number(m[1]), tekst: m[2], sub: [] });
      continue;
    }
    if ((m = r.match(PUNT))) {
      if (huidig && huidig.t === "ol" && m[1].length >= 2) { huidig.items.at(-1).sub.push(m[2]); continue; }
      if (!huidig || huidig.t !== "ul") { sluit(); huidig = { t: "ul", items: [] }; }
      huidig.items.push({ tekst: m[2], sub: [] });
      continue;
    }
    if (huidig && (huidig.t === "ol" || huidig.t === "ul")) {       // voortzetting van het vorige punt
      const it = huidig.items.at(-1);
      if (it.sub.length) it.sub[it.sub.length - 1] += " " + r.trim(); else it.tekst += " " + r.trim();
      continue;
    }
    if (!huidig || huidig.t !== "p") { sluit(); huidig = { t: "p", regels: [] }; }
    huidig.regels.push(r.trim());
  }
  sluit();
  // Modellen zetten vaak een lege regel tussen genummerde punten: dat blijft één lijst.
  const samen = [];
  for (const b of uit) {
    const vorige = samen.at(-1);
    if (b.t === "ol" && vorige && vorige.t === "ol" && b.items[0].nr === vorige.items.at(-1).nr + 1) vorige.items.push(...b.items);
    else samen.push(b);
  }
  return samen;
}

function regexUit(verwijzingen) {
  const alt = [...new Set(verwijzingen.map((v) => v.verwijzing))]
    .sort((a, b) => b.length - a.length)
    .map((v) => v.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return alt.length ? new RegExp(`(?<![\\w:.-])(${alt.join("|")})(?![\\w:])`, "gi") : null;
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
        : "Staat NIET in de opgehaalde bronnen. Controleer deze verwijzing zelf voordat je haar gebruikt.",
      onClick: () => ctx.opKlik && ctx.opKlik(info),
    }, m[1]));
    laatste = m.index + m[0].length;
  }
  if (laatste < s.length) uit.push(s.slice(laatste));
  return uit;
}

function inline(s, ctx) {
  const uit = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[AAN TE VULLEN[^\]]*\])/g;
  let laatste = 0;
  for (let m; (m = re.exec(s)); ) {
    if (m.index > laatste) uit.push(...metVerwijzingen(s.slice(laatste, m.index), ctx));
    const t = m[0];
    if (t.startsWith("**")) uit.push(h("strong", null, ...metVerwijzingen(t.slice(2, -2), ctx)));
    else if (t.startsWith("`")) uit.push(h("code", null, t.slice(1, -1)));
    else uit.push(h("span", { class: "invulveld" }, t));
    laatste = m.index + t.length;
  }
  if (laatste < s.length) uit.push(...metVerwijzingen(s.slice(laatste), ctx));
  return uit;
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
    else {
      const lijst = h(b.t, null, ...b.items.map((it) => h("li", b.t === "ol" ? { stijl: `counter-set: n ${it.nr}` } : null,
        b.t === "ol"
          ? h("div", null, h("p", null, ...inline(it.tekst, ctx)),
              it.sub.length ? h("ul", null, ...it.sub.map((s) => h("li", null, ...inline(s, ctx)))) : null)
          : [h("p", null, ...inline(it.tekst, ctx)),
             it.sub.length ? h("ul", null, ...it.sub.map((s) => h("li", null, ...inline(s, ctx)))) : null])));
      wortel.append(lijst);
    }
  }
  return wortel;
}
