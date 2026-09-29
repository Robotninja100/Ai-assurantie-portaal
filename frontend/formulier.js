// Bouwt het invoerformulier uit de definitie in registry.js en leest het weer uit.
import { h, icoon } from "./dom.js";
import { leesGetal } from "./format.js";
import { PRODUCT_SUGGESTIES } from "./registry.js";

let teller = 0;

function veldBlok(v, control, extra = []) {
  const id = control.id || control.querySelector("input, select, textarea").id;
  return h("div", { class: "veld" },
    h("label", { for: id }, v.label, v.optioneel ? h("span", { class: "opt" }, "(optioneel)") : null),
    control, ...extra,
    v.hint ? h("p", { class: "hint", id: `${id}-hint` }, v.hint) : null,
    h("p", { class: "veld-fout", id: `${id}-fout`, role: "alert", hidden: true }));
}

function bouwEen(v, producten) {
  const id = `f-${v.id}-${++teller}`;
  const uit = { v, id, blok: null, el: null };
  const beschrijving = v.hint ? `${id}-hint` : null;

  if (v.type === "lang") {
    const ta = h("textarea", { id, rows: v.rijen || 6, name: v.id, "aria-describedby": beschrijving });
    let teller_ = null;
    if (v.max) {
      teller_ = h("span", { class: "teller", "aria-live": "off" }, `0 / ${v.max.toLocaleString("nl-NL")}`);
      ta.addEventListener("input", () => {
        const n = ta.value.length;
        teller_.textContent = `${n.toLocaleString("nl-NL")} / ${v.max.toLocaleString("nl-NL")}`;
        teller_.classList.toggle("over", n > v.max);
        teller_.textContent += n > v.max ? " · de rest wordt niet gelezen" : "";
      });
    }
    uit.el = ta;
    uit.blok = veldBlok(v, ta, teller_ ? [teller_] : []);
    uit.lees = () => ta.value.trim();
    uit.zet = (x) => { ta.value = x ?? ""; ta.dispatchEvent(new Event("input")); };
  } else if (v.type === "tekst") {
    const inp = h("input", { id, type: "text", name: v.id, autocomplete: "off", "aria-describedby": beschrijving });
    uit.el = inp; uit.blok = veldBlok(v, inp);
    uit.lees = () => inp.value.trim();
    uit.zet = (x) => { inp.value = x ?? ""; };
  } else if (v.type === "invoerkeuze") {
    const lijstId = `${id}-lijst`;
    const inp = h("input", { id, type: "text", name: v.id, list: lijstId, autocomplete: "off", "aria-describedby": beschrijving });
    const lijst = h("datalist", { id: lijstId }, ...PRODUCT_SUGGESTIES.map((p) => h("option", { value: p })));
    uit.el = inp; uit.blok = veldBlok(v, inp, [lijst]);
    uit.lees = () => inp.value.trim();
    uit.zet = (x) => { inp.value = x ?? ""; };
  } else if (v.type === "bedrag" || v.type === "getal") {
    const eenheid = v.type === "bedrag" ? "€" : v.eenheid;
    const inp = h("input", { id, type: "text", inputmode: "decimal", name: v.id, autocomplete: "off",
      "aria-describedby": beschrijving, placeholder: v.standaard ? String(v.standaard) : "" });
    const kader = h("div", { class: `met-eenheid${v.achter ? " achter" : ""}` }, inp, eenheid ? h("span", { class: "eenheid" }, eenheid) : null);
    uit.el = inp;
    uit.blok = veldBlok(v, kader);
    uit.lees = () => inp.value.trim();
    uit.zet = (x) => { inp.value = x ?? ""; };
    uit.numeriek = true;
  } else if (v.type === "datum") {
    const inp = h("input", { id, type: "date", name: v.id, "aria-describedby": beschrijving });
    uit.el = inp; uit.blok = veldBlok(v, inp);
    uit.lees = () => inp.value;
    uit.zet = (x) => { inp.value = x ?? ""; };
  } else if (v.type === "keuze") {
    // Een vergelijking gaat over het aanbod van één verzekeraar: dan kiest u product én verzekeraar.
    const opties = v.bron === "varianten"
      ? (producten || []).filter((p) => (p.varianten || []).length).map((p) =>
        h("optgroup", { label: p.product }, ...p.varianten.map((x) =>
          h("option", { value: x.waarde }, `${x.verzekeraar} (${x.clausules} clausules)`))))
      : (producten || []).map((p) => h("option", { value: p.product }, p.product));
    const sel = h("select", { id, name: v.id, "aria-describedby": beschrijving },
      v.leeg ? h("option", { value: "" }, v.leeg) : h("option", { value: "", disabled: true },
        v.bron === "varianten" ? "Kies een product en verzekeraar" : "Kies een product"),
      ...opties);
    uit.el = sel; uit.blok = veldBlok(v, sel);
    uit.lees = () => sel.value;
    uit.zet = (x) => { sel.value = x ?? ""; };
  } else if (v.type === "schakelaar") {
    const inp = h("input", { id, type: "checkbox", name: v.id });
    uit.el = inp;
    uit.blok = h("div", { class: "veld" },
      h("label", { class: "schakelaar", for: id }, inp, h("span", { class: "spoor" }),
        h("span", { class: "schakelaar-tekst" }, h("b", null, v.label), v.hint ? h("span", null, v.hint) : null)));
    uit.lees = () => inp.checked;
    uit.zet = (x) => { inp.checked = !!x; };
  }
  uit.toonFout = (tekst) => {
    const f = uit.blok.querySelector(".veld-fout");
    if (!f) return;
    f.hidden = !tekst;
    f.textContent = tekst || "";
    if (uit.el) uit.el.setAttribute("aria-invalid", tekst ? "true" : "false");
  };
  return uit;
}

export function bouwFormulier(cfg, producten) {
  const velden = [];
  const wortel = h("div", { class: "velden" });
  for (const v of cfg.velden) {
    if (v.rij) {
      const kinderen = v.rij.map((x) => bouwEen(x, producten));
      velden.push(...kinderen);
      wortel.append(h("div", { class: "rij-2" }, ...kinderen.map((k) => k.blok)));
    } else {
      const k = bouwEen(v, producten);
      velden.push(k);
      wortel.append(k.blok);
    }
  }
  // Alleen de toelichting van 'polisvergelijker': A en B mogen niet hetzelfde zijn.
  const api = {
    el: wortel,
    zet(waarden) {
      for (const k of velden) if (k.zet) k.zet(waarden[k.v.id] ?? (k.v.standaard ?? ""));
    },
    /** Geeft {invoer} of {fouten} terug; toont de fouten bij de velden. */
    lees() {
      const invoer = {};
      let ok = true;
      for (const k of velden) {
        k.toonFout(null);
        const ruw = k.lees();
        const v = k.v;
        if (v.type === "schakelaar") { invoer[v.id] = !!ruw; continue; }
        if (ruw === "" || ruw == null) {
          if (v.verplicht) { k.toonFout("Vul dit veld in."); ok = false; }
          else if (v.standaard != null && k.numeriek) invoer[v.id] = Number(v.standaard);
          continue;
        }
        if (k.numeriek) {
          const n = leesGetal(ruw);
          if (Number.isNaN(n)) { k.toonFout("Geen geldig getal. Gebruik bijvoorbeeld 250.000 of 1.250,50."); ok = false; continue; }
          invoer[v.id] = n;
        } else invoer[v.id] = ruw;
      }
      if (cfg.velden.some((v) => v.id === "product_a")) {
        const a = velden.find((k) => k.v.id === "product_a"), b = velden.find((k) => k.v.id === "product_b");
        if (a && b && a.lees() && a.lees() === b.lees()) { b.toonFout("Kies een ander product dan bij variant A."); ok = false; }
      }
      return ok ? { invoer } : { fouten: true };
    },
    eersteFout() { return velden.find((k) => k.blok.querySelector('.veld-fout:not([hidden])'))?.el; },
  };
  return api;
}
