// Opstarten: functielijst en status ophalen, zijbalk bouwen, en de pagina kiezen op basis van de URL.
import { haalJson } from "./api.js";
import { h, icoon, leeg } from "./dom.js";
import { aantal } from "./format.js";
import { GROEPEN, REGISTER } from "./registry.js";
import { renderFunctie, renderOverzicht } from "./views.js";

const ctx = { functies: [], producten: [], status: null, opKlaar: () => verversStatus() };
const zij = document.getElementById("zij");
const inhoud = document.getElementById("inhoud");
const menuknop = document.getElementById("menuknop");
menuknop.append(icoon("menu", 20));
let huidig = null;

function statusBlok() {
  const s = ctx.status;
  if (!s) return h("div", { class: "zij-status" }, h("h2", null, "Systeem"), h("div", { class: "status-regel" }, h("i", { class: "stip fout" }), h("span", null, "Geen verbinding met de server.")));
  const rt = s.runtime;
  const toon = !rt.beschikbaar ? "fout" : rt.provider === "local" ? "let" : "ok";
  const naam = { local: "Lokaal model", openrouter: "OpenRouter", anthropic: "Anthropic" }[rt.provider] || rt.provider;
  const c = s.corpus || {};
  return h("div", { class: "zij-status" }, h("h2", null, "Systeem"),
    h("div", { class: "status-regel", title: rt.opmerking }, h("i", { class: `stip ${toon}` }),
      h("span", null, h("b", null, "Taalmodel"), rt.beschikbaar ? `${naam} · ${rt.model}${rt.snelheid === "traag" ? " (traag)" : ""}` : "Niet beschikbaar")),
    h("div", { class: "status-regel" }, h("i", { class: `stip ${s.corpus_totaal > 0 ? "ok" : "fout"}` }),
      h("span", null, h("b", null, "Corpus"),
        `${aantal(c.wetgeving?.records || 0)} artikelen · ${aantal(c.kifid?.records || 0)} uitspraken · ${aantal(c.polisvoorwaarden?.records || 0)} clausules`)));
}

function bouwZijbalk(route) {
  leeg(zij);
  const binnen = h("div", { class: "zij-binnen" });
  zij.append(binnen);
  binnen.append(h("a", { class: "merk", href: "#/" },
    h("span", { class: "merk-teken", "aria-hidden": "true" }, "§"),
    h("span", { class: "merk-tekst" }, h("b", null, "Assurantieportaal"), h("small", null, "AI met bronvermelding"))));
  const nav = h("nav", { class: "nav", "aria-label": "Functies" },
    h("div", null, h("a", { class: "nav-item", href: "#/", "aria-current": route.type === "home" ? "page" : null }, icoon("schild", 18), "Overzicht")));
  for (const groep of GROEPEN) {
    const lijst = ctx.functies.filter((f) => f.groep === groep);
    if (!lijst.length) continue;
    nav.append(h("div", null, h("div", { class: "nav-groep-titel" }, groep),
      ...lijst.map((f) => h("a", { class: "nav-item", href: `#/f/${f.id}`, "aria-current": route.type === "functie" && route.id === f.id ? "page" : null },
        icoon(REGISTER[f.id]?.icoon || "boek", 18), f.naam))));
  }
  binnen.append(nav, statusBlok());
}

function lees() {
  const m = location.hash.match(/^#\/f\/([\w-]+)/);
  return m ? { type: "functie", id: m[1] } : { type: "home" };
}

function toon() {
  const route = lees();
  if (huidig && huidig.destroy) huidig.destroy();
  bouwZijbalk(route);
  leeg(inhoud);
  if (route.type === "functie") {
    huidig = renderFunctie(route.id, ctx);
    const f = ctx.functies.find((x) => x.id === route.id);
    document.title = `${f ? f.naam : "Functie"} · Assurantieportaal`;
  } else {
    huidig = renderOverzicht(ctx);
    document.title = "Assurantieportaal";
  }
  inhoud.append(huidig);
  sluitMenu();
  window.scrollTo({ top: 0 });
}

function sluitMenu() { zij.dataset.open = "false"; menuknop.setAttribute("aria-expanded", "false"); }
menuknop.addEventListener("click", () => {
  const open = zij.dataset.open !== "true";
  zij.dataset.open = String(open);
  menuknop.setAttribute("aria-expanded", String(open));
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") sluitMenu(); });
zij.addEventListener("click", (e) => { if (e.target === zij) sluitMenu(); });

async function verversStatus() {
  try { ctx.status = await haalJson("/api/status"); } catch { ctx.status = null; }
  const blok = zij.querySelector(".zij-status");
  if (blok) blok.replaceWith(statusBlok());
}

async function start() {
  try {
    const [functies, producten, status] = await Promise.all([
      haalJson("/api/functies"), haalJson("/api/producten"), haalJson("/api/status")]);
    ctx.functies = functies; ctx.producten = producten; ctx.status = status;
  } catch (e) {
    inhoud.append(h("div", { class: "melding fout" }, icoon("waarschuwing", 18),
      h("div", null, h("b", null, "De server antwoordt niet. "), String(e.message || e))));
    return;
  }
  window.addEventListener("hashchange", toon);
  toon();
}
start();
