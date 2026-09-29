// De bronnenlijst: wat er is opgehaald, VOORDAT het antwoord er is. Compacte rijen die uitklappen
// naar het letterlijke fragment en een link naar de originele bron.
import { h, icoon } from "./dom.js";
import { datum, meervoud } from "./format.js";

const SOORT = {
  wetgeving: { titel: "Wetgeving", volgorde: 0 },
  kifid: { titel: "Kifid-uitspraken", volgorde: 1 },
  polis: { titel: "Polisvoorwaarden", volgorde: 2 },
};
const TYPE_NAAM = {
  "dekking": "Dekking", "uitsluiting": "Uitsluiting", "eigen risico": "Eigen risico",
  "verplichting verzekerde": "Verplichting", "schaderegeling": "Schaderegeling", "verjaring": "Termijn",
};
const TYPE_VOLGORDE = ["dekking", "uitsluiting", "eigen risico", "verplichting verzekerde", "schaderegeling", "verjaring"];

/** Het deel van een bron waarmee het antwoord naar haar kan verwijzen: '7:942', '2026-0566', '3.6.2'. */
export function sleutels(b) {
  if (b.soort === "wetgeving") return [String(b.artikel).toLowerCase()];
  if (b.soort === "kifid") return [b.label.replace(/^Kifid\s+/, "").toLowerCase()];
  const m = (b.clausule || "").match(/(\d+(?:\.\d+)+)/);
  return m ? [m[1]] : [];
}

function tags(b) {
  if (b.soort === "polis" && b.type) return [h("span", { class: `tag ${b.type.replace(/\s+/g, "-")}` }, TYPE_NAAM[b.type] || b.type)];
  if (b.soort === "kifid" && b.uitkomst) return [h("span", { class: "tag zacht" }, b.uitkomst.charAt(0).toUpperCase() + b.uitkomst.slice(1))];
  return [];
}

function meta(b) {
  const delen = [];
  if (b.soort === "polis") {
    if (b.verzekeraar) delen.push(h("span", null, b.verzekeraar));
    if (b.document) delen.push(h("span", null, b.document));
  } else if (b.soort === "kifid") {
    if (b.verweerder) delen.push(h("span", null, `Verweerder: ${b.verweerder}`));
    if (b.datum) delen.push(h("span", null, datum(b.datum)));
  } else if (b.geldig_op) {
    delen.push(h("span", null, `Tekst per ${datum(b.geldig_op)}`));
  }
  if (b.url) {
    delen.push(h("a", { href: b.url, target: "_blank", rel: "noopener noreferrer" },
      "Open de bron ", icoon("extern", 12)));
  }
  return h("div", { class: "bron-meta" }, ...delen);
}

function rij(b) {
  const el = h("div", { class: "bron", dataset: { open: "false", soort: b.soort, sleutels: sleutels(b).join(" ") } });
  const knop = h("button", { class: "bron-rij", type: "button", "aria-expanded": "false",
    onClick: () => zet(el, el.dataset.open !== "true") },
    h("span", { class: "bron-tekst" },
      b.soort === "polis" && b.clausule
        ? h("span", { class: "bron-label" }, h("b", null, b.clausule), h("span", { class: "bron-sub" }, b.product))
        : h("span", { class: "bron-label" }, h("b", null, b.label)),
      b.titel ? h("span", { class: "bron-titel" }, b.titel) : null),
    h("span", { class: "bron-tags" }, ...tags(b)),
    h("span", { class: "bron-pijl" }, icoon("chevron", 16)));
  el.append(knop, h("div", { class: "bron-detail" },
    h("blockquote", { class: "bron-citaat", tabindex: "0", "aria-label": `Tekst van ${b.label}` }, b.fragment || "(geen fragment)"), meta(b)));
  return el;
}

function zet(el, open) {
  el.dataset.open = String(open);
  el.querySelector(".bron-rij").setAttribute("aria-expanded", String(open));
}

function groepen(bronnen) {
  const per = new Map();
  for (const b of bronnen) {
    if (!per.has(b.soort)) per.set(b.soort, []);
    per.get(b.soort).push(b);
  }
  return [...per.entries()].sort((a, b) => (SOORT[a[0]]?.volgorde ?? 9) - (SOORT[b[0]]?.volgorde ?? 9));
}

function sorteer(lijst) {
  return [...lijst].sort((a, b) => {
    const ia = TYPE_VOLGORDE.indexOf(a.type), ib = TYPE_VOLGORDE.indexOf(b.type);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
}

export function renderBronnen(bronnen, { tweeKanten = null } = {}) {
  const wortel = h("div");
  if (!bronnen.length) {
    wortel.append(h("div", { class: "sectie-body" },
      h("div", { class: "melding info" }, icoon("info", 18),
        h("div", null, h("b", null, "Geen bronnen gevonden. "), "Het portaal geeft dan geen inhoudelijk antwoord."))));
    return { el: wortel, alles: () => {} };
  }
  if (tweeKanten) {
    const kolom = (kant, naam) => {
      const lijst = bronnen.filter((b) => b.kant === kant);
      return h("div", null,
        h("div", { class: "kant-kop" }, `Variant ${kant}`, h("small", null, `${naam} · ${meervoud(lijst.length, "clausule", "clausules")}`)),
        lijst.length ? lijst.map(rij) : h("div", { class: "sectie-body" }, h("p", { class: "hint" }, "Geen clausules van dit product in het corpus. Er wordt niets aangevuld.")));
    };
    wortel.append(h("div", { class: "twee-kanten" }, kolom("A", tweeKanten[0]), kolom("B", tweeKanten[1])));
  } else {
    for (const [soort, lijst] of groepen(bronnen)) {
      wortel.append(h("div", { class: "bron-groep" },
        h("div", { class: "bron-groep-kop" }, SOORT[soort]?.titel || soort, h("span", null, `· ${lijst.length}`)),
        (soort === "polis" ? sorteer(lijst) : lijst).map(rij)));
    }
  }
  const alles = (open) => wortel.querySelectorAll(".bron").forEach((el) => zet(el, open));
  const voet = h("div", { class: "bronnen-voet" },
    h("span", null, "Alleen bevestigde bronnen worden opgehaald."),
    h("button", { class: "tekstknop", type: "button", onClick: () => alles(!wortel.querySelector('.bron[data-open="true"]')) }, "Alles uit-/inklappen"));
  wortel.append(voet);
  return { el: wortel, alles };
}

/** Scrollt naar de bron waarnaar een verwijzing in het antwoord wijst en klapt haar open. */
export function toonBron(container, verwijzing) {
  const sleutel = verwijzing.verwijzing.toLowerCase();
  const doel = [...container.querySelectorAll(".bron")].find((el) => el.dataset.sleutels.split(" ").includes(sleutel));
  if (!doel) return false;
  zet(doel, true);
  doel.scrollIntoView({ behavior: "smooth", block: "center" });
  doel.classList.remove("geraakt");
  void doel.offsetWidth;
  doel.classList.add("geraakt");
  return true;
}
