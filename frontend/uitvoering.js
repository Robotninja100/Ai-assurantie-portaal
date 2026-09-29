// Eén vraag aan het portaal, van invoer tot controle. Bouwt de resultaatkolom op naarmate de
// gebeurtenissen binnenkomen, in de vaste volgorde: bronnen, berekening, toelichting, controle.
import { stelVraag } from "./api.js";
import { renderBerekening } from "./berekening.js";
import { renderBronnen, toonBron } from "./bronnen.js";
import { h, icoon, leeg, voegToe } from "./dom.js";
import { aantal, meervoud } from "./format.js";
import { heeftBerekening } from "./registry.js";
import { renderAntwoord } from "./tekst.js";

const BEREKENING_TITEL = {
  schadeberekening: "Berekening", verjaringstoets: "Termijn", provisietoets: "Toets",
  waardetoets: "Waardebepaling", precedentzoeker: "Verdeling", klachtroute: "Termijnen",
};
const BRONNEN_DICHT = new Set(["schadeberekening", "verjaringstoets", "provisietoets", "waardetoets"]);
const SOORT_NAAM = { wetsartikel: "Wetsartikel", kifid: "Kifid-uitspraak", polisclausule: "Polisclausule",
  bedrag: "Bedrag", percentage: "Percentage", datum: "Datum", citaat: "Citaat", uitspraak: "Uitspraak (ECLI)" };
const GETALSOORT = new Set(["bedrag", "percentage", "datum"]);

const OORDEEL = {
  GEFUNDEERD: { toon: "ok", icoon: "vink", titel: "Alles wat het antwoord noemt staat in de bronnen of de berekening",
    uitleg: "Elke wet, uitspraak of clausule is teruggevonden in de opgehaalde bronnen, en elk bedrag, percentage en elke datum komt uit de berekening, de invoer of de bronnen." },
  ONGEFUNDEERD: { toon: "fout", icoon: "waarschuwing",
    uitleg: "Deze punten zijn in het antwoord gemarkeerd. Het model noemde ze zonder dat ze zijn opgehaald, berekend of woordelijk uit de invoer of de bronnen komen. Gebruik ze niet zonder ze zelf te controleren." },
  GEEN_VERWIJZINGEN: { toon: "let", icoon: "info", titel: "Het antwoord noemt geen wet, uitspraak of clausule",
    uitleg: "Zonder verwijzing naar een wetsartikel, uitspraak of clausule is het antwoord niet te controleren. Lees het als samenvatting, niet als onderbouwing." },
  GEWEIGERD_GEEN_BRONNEN: { toon: "info", icoon: "info", titel: "Geen bronnen, dus geen inhoudelijk antwoord",
    uitleg: "Er zijn geen bronnen gevonden die deze vraag kunnen onderbouwen. Het portaal geeft daarom geen inhoudelijk antwoord." },
};

const tijd = (ms) => `${(ms / 1000).toFixed(1).replace(".", ",")} s`;

function sectie(nr, titel, body, { meta = "", klapbaar = false, dicht = false, acties = [] } = {}) {
  const metaEl = h("span", { class: "sectie-meta" }, meta);
  const bodyEl = h("div", { class: "sectie-body los" });
  voegToe(bodyEl, [body]);
  const el = h("section", { class: "sectie", dataset: { dicht: String(dicht) } });
  // Uitklappen gaat via een echte knop in de kop (toetsenbord en schermlezer); een klik elders in de kop werkt ook.
  const knop = klapbaar ? h("button", { class: "sectie-knop", type: "button", "aria-expanded": String(!dicht) }, titel) : null;
  const kop = h("header", { class: "sectie-kop" }, h("span", { class: "sectie-nr" }, String(nr)),
    h("h3", null, knop || titel), metaEl, ...acties);
  el.append(kop, bodyEl);
  const zet = (d) => { el.dataset.dicht = String(d); bodyEl.hidden = d; if (knop) knop.setAttribute("aria-expanded", String(!d)); };
  if (klapbaar) {
    kop.style.cursor = "pointer";
    const wissel = () => zet(el.dataset.dicht !== "true");
    kop.addEventListener("click", (e) => { if (e.target === knop || !e.target.closest("button, a")) wissel(); });
    metaEl.append(" ", h("span", { class: "tag zacht" }, "uitklappen"));
  }
  zet(dicht);
  return { el, body: bodyEl, meta: (t) => { metaEl.textContent = t; }, open: () => zet(false), zet };
}

function pijplijn(stappen) {
  // Het live-gebied bevat alleen de stappen; de lopende tijd staat erbuiten (aria-hidden), anders leest
  // een schermlezer vijf keer per seconde een nieuwe tijd voor.
  const el = h("div", { class: "pijplijn", role: "status", "aria-live": "polite" });
  const per = {}, status = {};
  const NAAM = { actief: "bezig", klaar: "klaar", fout: "mislukt", overgeslagen: "overgeslagen" };
  stappen.forEach((s, i) => {
    if (i) el.append(h("span", { class: "pijp-pijl", "aria-hidden": "true" }, icoon("chevron", 14)));
    status[s.id] = h("span", { class: "alleen-lezers" }, "");
    per[s.id] = h("span", { class: "pijp-stap" }, h("i", { class: "punt", "aria-hidden": "true" }), s.naam, status[s.id]);
    el.append(per[s.id]);
  });
  const t = h("span", { class: "pijp-tijd", "aria-hidden": "true" }, "0,0 s");
  el.append(t);
  const api = {
    el, tijd: t,
    zet(id, st) {
      if (!per[id]) return;
      per[id].className = `pijp-stap ${st}`;
      status[id].textContent = NAAM[st] ? `: ${NAAM[st]}` : "";
    },
    /**
     * Het werk stopt hier. Wat nog liep krijgt `actiefStatus` (het is niet gelukt en niet stilzwijgend
     * geslaagd); wat nog moest beginnen is overgeslagen.
     */
    eindig(actiefStatus) {
      for (const id of Object.keys(per)) {
        const klasse = per[id].classList;
        if (klasse.contains("actief")) api.zet(id, actiefStatus);
        else if (!["klaar", "fout", "overgeslagen"].some((k) => klasse.contains(k))) api.zet(id, "overgeslagen");
      }
    },
  };
  return api;
}

export class Uitvoering {
  constructor(id, cfg, doel, opKlaar, runtime = null) {
    this.id = id; this.cfg = cfg; this.doel = doel; this.opKlaar = opKlaar; this.runtime = runtime;
    this.tekst = ""; this.controle = null; this.gemaskeerd = null; this.model = null;
    this.bronnen = []; this.berekening = null; this.fout = null; this.klaar = false;
    this.ac = new AbortController();
  }

  async start(invoer) {
    this.invoer = invoer;
    leeg(this.doel);
    const stappen = [{ id: "bronnen", naam: "Bronnen" }];
    if (heeftBerekening(this.id, invoer)) stappen.push({ id: "berekening", naam: this.id === "precedentzoeker" ? "Verdeling" : this.id === "klachtroute" ? "Termijnen" : "Berekening" });
    stappen.push({ id: "antwoord", naam: "Toelichting" }, { id: "controle", naam: "Controle" });
    this.pijp = pijplijn(stappen);
    this.doel.append(this.pijp.el);
    this.pijp.zet("bronnen", "actief");
    this.t0 = performance.now();
    this.timer = setInterval(() => { this.pijp.tijd.textContent = tijd(performance.now() - this.t0); }, 200);
    try {
      await stelVraag(this.id, invoer, (e) => this.gebeurtenis(e), this.ac.signal);
    } catch (err) {
      if (err.name === "AbortError") this.opGestopt();
      else this.storing(err);
    } finally {
      clearInterval(this.timer);
      this.pijp.tijd.textContent = tijd(performance.now() - this.t0);
      this.klaar = true;
      this.opKlaar(this);
    }
  }

  stop() { this.gestopt = true; this.ac.abort(); }

  /** Na Stop: wat er staat is onvolledig en ongecontroleerd, en zo staat het er ook. */
  opGestopt() {
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = null; }
    if (this.tekst && this.antwoordVak) this.tekenAntwoord(true);
    else if (this.antwoordEl && !this.controle) leeg(this.antwoordEl);          // de wachtspinner weg
    if (this.secTekst && !this.tekst) this.antwoordEl.append(h("p", { class: "hint" }, "Er kwam nog geen antwoord binnen."));
    this.pijp.eindig("overgeslagen");
    this.melding("info", this.tekst && !this.controle
      ? "Gestopt. Wat hierboven staat is onvolledig en niet gecontroleerd; gebruik het niet zonder het zelf na te lezen."
      : "Gestopt door de gebruiker.");
  }

  volgnummer() { return this.doel.querySelectorAll(".sectie").length + 1; }

  voegSectieToe(s) { this.doel.append(s.el); return s; }

  gebeurtenis(e) {
    switch (e.type) {
      case "bronnen": return this.opBronnen(e.bronnen);
      case "berekening": return this.opBerekening(e.berekening);
      case "opmerkingen": return this.opOpmerkingen(e.opmerkingen);
      case "model": return this.opModel(e);
      case "wacht": return this.opWacht(e.sec);
      case "tekst": return this.opTekst(e.tekst);
      case "weigering": return this.opWeigering(e.tekst);
      case "gemaskeerd": this.gemaskeerd = e.tekst; return;
      case "controle": return this.opControle(e.controle);
      case "fout": return this.opFout(e);
      default: return;
    }
  }

  opBronnen(bronnen) {
    this.bronnen = bronnen;
    const kanten = this.cfg.tweeKanten ? [this.invoer.product_a, this.invoer.product_b] : null;
    const { el } = renderBronnen(bronnen, { tweeKanten: kanten });
    const dicht = BRONNEN_DICHT.has(this.id) && bronnen.length > 0;
    this.secBronnen = this.voegSectieToe(sectie(this.volgnummer(), "Bronnen", el, {
      meta: `${meervoud(bronnen.length, "bron", "bronnen")} opgehaald`, klapbaar: dicht, dicht }));
    this.pijp.zet("bronnen", "klaar");
    this.pijp.zet(heeftBerekening(this.id, this.invoer) ? "berekening" : "antwoord", "actief");
  }

  opOpmerkingen(lijst) {
    this.doel.append(h("div", { class: "meldingen", stijl: "margin-top:0" }, ...lijst.map((t) =>
      h("div", { class: "melding" }, icoon("waarschuwing", 18), h("div", null, t)))));
  }

  opBerekening(b) {
    this.berekening = b;
    const inhoud = h("div", { class: "sectie-body" }, renderBerekening(this.id, b, (v) => this.naarBron(v)));
    this.secBer = this.voegSectieToe(sectie(this.volgnummer(), BEREKENING_TITEL[this.id] || "Berekening", inhoud, {
      meta: this.id === "precedentzoeker" ? "geteld in het corpus" : "uit code, niet uit het model" }));
    this.pijp.zet("berekening", "klaar");
    this.pijp.zet("antwoord", "actief");
  }

  ensureToelichting() {
    if (this.secTekst) return this.secTekst;
    this.antwoordEl = h("div", { class: "sectie-body" });
    const acties = [h("button", { class: "knop klein", type: "button", hidden: true, onClick: () => this.kopieer() },
      icoon("kopie", 14), "Kopieer")];
    this.kopieerKnop = acties[0];
    this.secTekst = this.voegSectieToe(sectie(this.volgnummer(), this.cfg.document ? "Concept-notitie" : "Toelichting", this.antwoordEl,
      { meta: "", acties }));
    this.pijp.zet("antwoord", "actief");
    return this.secTekst;
  }

  opWacht(sec) {
    this.ensureToelichting();
    if (this.tekst) return;
    leeg(this.antwoordEl);
    const lokaal = this.runtime && this.runtime.provider === "local";
    const uitleg = lokaal ? (sec >= 15 ? " Het lokale model draait op een CPU en heeft hier enkele minuten voor nodig." : "")
      : (sec >= 20 ? " Gratis modellen staan soms in de wachtrij; het portaal wacht en probeert daarna het volgende model." : "");
    this.antwoordEl.append(h("div", { class: "wacht" }, h("span", { class: "draaier" }),
      h("span", null, `Het taalmodel formuleert het antwoord… ${sec} s`, uitleg)));
  }

  opModel(e) {
    this.ensureToelichting();
    this.model = e;
    this.secTekst.meta(`Geschreven door ${e.model}`);
    if (e.overgeslagen && e.overgeslagen.length) this.secTekst.el.querySelector(".sectie-meta").title = `Overgeslagen: ${e.overgeslagen.join("; ")}`;
    leeg(this.antwoordEl);
    this.antwoordVak = h("div");
    this.antwoordEl.append(this.antwoordVak);
    if (e.overgeslagen && e.overgeslagen.length) {
      this.antwoordEl.append(h("p", { class: "hint", stijl: "margin-top:12px" },
        `Eerdere modellen in de keten waren niet beschikbaar: ${e.overgeslagen.join("; ")}.`));
    }
    if (e.provider === "local") {
      this.antwoordEl.append(h("p", { class: "hint", stijl: "margin-top:12px" },
        "Geschreven door een klein lokaal model. Dat formuleert, maar kan in de uitleg fouten maken: lees de berekening en de bronnen hierboven als leidend."));
    }
  }

  opTekst(stuk) {
    this.ensureToelichting();
    this.tekst += stuk;
    if (!this.antwoordVak) this.opModel({ model: "taalmodel" });
    if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = null; this.tekenAntwoord(false); });
  }

  tekenAntwoord(klaar) {
    if (!this.antwoordVak) return;
    const verw = this.controle ? this.verwijzingen() : [];
    const antw = renderAntwoord(this.tekst, verw, (v) => this.naarBron(v));
    if (!klaar) antw.classList.add("cursor");
    if (this.cfg.document) {
      this.antwoordVak.className = "document";
    }
    leeg(this.antwoordVak).append(antw);
  }

  verwijzingen() {
    const c = this.controle;
    return [...c.gefundeerd.map((v) => ({ ...v, status: "ok" })), ...c.ongefundeerd.map((v) => ({ ...v, status: "slecht" }))];
  }

  opWeigering(tekst) {
    this.ensureToelichting();
    leeg(this.antwoordEl).append(h("div", { class: "melding info" }, icoon("info", 18), h("div", null, ...tekst.split("\n\n").map((p) => h("p", null, p)))));
    this.pijp.zet("antwoord", "overgeslagen");
  }

  opControle(c) {
    this.controle = c;
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = null; }
    const geweigerd = c.oordeel === "GEWEIGERD_GEEN_BRONNEN";
    // Een afgebroken of afgekapt antwoord is niet 'klaar'; een weigering is een uitkomst, geen antwoord.
    this.pijp.zet("antwoord", geweigerd ? "overgeslagen" : (c.afgekapt || this.fout) ? "fout" : "klaar");
    this.tekenAntwoord(true);
    if (this.secTekst) {
      this.secTekst.meta(`${this.model ? this.model.model + " · " : ""}${c.duur_sec != null ? tijd(c.duur_sec * 1000) : ""}`);
      if (this.kopieerKnop) this.kopieerKnop.hidden = false;
    }
    if (c.afgekapt && this.antwoordEl) {
      this.antwoordEl.append(h("div", { class: "melding", stijl: "margin-top:16px" }, icoon("waarschuwing", 18),
        h("div", null, h("b", null, "Het antwoord is afgekapt. "),
          c.einde_reden === "content_filter"
            ? "Het model stopte door een inhoudsfilter van de aanbieder. Wat hierboven staat is onvolledig en de vervolgstap ontbreekt mogelijk."
            : "Het model bereikte de maximale lengte. Wat hierboven staat is onvolledig en de vervolgstap ontbreekt mogelijk.")));
    }
    const uitleg = OORDEEL[c.oordeel] || OORDEEL.GEEN_VERWIJZINGEN;
    const nSlecht = c.ongefundeerd.length;
    const isRef = (v) => !GETALSOORT.has(v.soort) && v.soort !== "citaat";
    const nRefs = c.gefundeerd.filter(isRef).length;
    const nGetallen = c.gefundeerd.filter((v) => GETALSOORT.has(v.soort)).length;
    const nCitaten = [...c.gefundeerd, ...c.ongefundeerd].filter((v) => v.soort === "citaat").length;
    const kort = (v) => (v.soort === "citaat" && v.verwijzing.length > 110 ? `${v.verwijzing.slice(0, 107)}…` : v.verwijzing);
    const titel = uitleg.titel || `${meervoud(nSlecht, "punt staat", "punten staan")} niet in de bronnen of de berekening`;
    const rijen = [...c.ongefundeerd.map((v) => ({ ...v, ok: false })),
      ...c.gefundeerd.filter((v) => !GETALSOORT.has(v.soort)).map((v) => ({ ...v, ok: true }))];
    const b = c.bronnen_beschikbaar || {};
    const lijst = rijen.length ? h("ul", { class: "verwijzingslijst" }, ...rijen.map((v) =>
      h("li", null, h("span", { class: `tag ${v.ok ? "ok" : "fout"}` },
        v.soort === "citaat" ? (v.ok ? "Woordelijk" : "Niet woordelijk")
          : v.ok ? "In de bronnen" : GETALSOORT.has(v.soort) ? "Niet in de berekening" : "Niet in de bronnen"),
        h("b", null, kort(v)), h("span", { class: "soort" }, SOORT_NAAM[v.soort] || v.soort)))) : null;
    const body = h("div", { class: "sectie-body" },
      h("div", { class: "controle-kop" },
        h("div", { class: `oordeel-icoon oordeel ${uitleg.toon}`, stijl: "width:40px;height:40px;padding:0;display:grid;place-items:center;border-radius:10px" }, icoon(uitleg.icoon, 22)),
        h("div", null, h("h4", null, titel), h("p", null, uitleg.uitleg))),
      lijst,
      h("div", { class: "controle-meta" },
        h("span", null, "Gecontroleerd: ", h("b", null, `${meervoud(nRefs + c.ongefundeerd.filter(isRef).length, "verwijzing", "verwijzingen")}${nCitaten ? `, ${meervoud(nCitaten, "citaat", "citaten")}` : ""} en ${meervoud(nGetallen + c.ongefundeerd.filter((v) => GETALSOORT.has(v.soort)).length, "getal", "getallen")}`),
          " tegen ", h("b", null, `${aantal(b.wetgeving || 0)} wetsartikelen, ${aantal(b.kifid || 0)} uitspraken, ${aantal(b.polisclausules || 0)} clausules`), " en de berekening van deze vraag."),
        c.duur_sec != null ? h("span", null, "Totale duur ", h("b", null, tijd(c.duur_sec * 1000))) : null));
    this.voegSectieToe(sectie(this.volgnummer(), "Controle van verwijzingen", body, { meta: "citeer-of-weiger" }));
    this.pijp.zet("controle", c.oordeel === "ONGEFUNDEERD" ? "fout" : geweigerd ? "overgeslagen" : "klaar");
  }

  opFout(e) {
    this.fout = e;
    this.ensureToelichting();
    if (e.afgebroken && this.tekst) this.tekenAntwoord(true);
    else if (!this.tekst) leeg(this.antwoordEl);
    this.antwoordEl.append(h("div", { class: "melding fout", stijl: "margin-top:16px" }, icoon("waarschuwing", 18),
      h("div", null, h("b", null, e.afgebroken ? "Het antwoord is afgebroken. " : "Geen antwoord van het taalmodel. "), e.fout)));
    this.pijp.zet("antwoord", "fout");
    this.pijp.zet("controle", "overgeslagen");
  }

  storing(err) {
    if (err.invoerfout) this.invoerFout = err.message;
    // Ligt er al iets op het scherm (bronnen, berekening, een deel van het antwoord), dan blijft dat
    // staan: het is wel gecontroleerd en wel bruikbaar. Alleen een leeg scherm wordt vervangen.
    const heeftInhoud = !!this.doel.querySelector(".sectie");
    if (!heeftInhoud) leeg(this.doel);
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = null; }
    if (this.tekst && this.antwoordVak && !this.controle) this.tekenAntwoord(true);
    if (this.pijp && !this.doel.contains(this.pijp.el)) this.doel.prepend(this.pijp.el);
    if (this.pijp) this.pijp.eindig("fout");
    this.doel.append(h("div", { class: err.invoerfout ? "melding" : "melding fout", role: "alert" }, icoon("waarschuwing", 18),
      h("div", null, h("b", null, err.invoerfout ? "De invoer klopt niet. " : err.onderbroken ? "Onderbroken. " : "Er ging iets mis. "),
        err.message, heeftInhoud && !err.invoerfout ? " Wat hierboven staat kan onvolledig zijn en is niet compleet gecontroleerd." : "")));
  }

  melding(soort, tekst) {
    this.doel.append(h("div", { class: `melding ${soort}` }, icoon("info", 18), h("div", null, tekst)));
  }

  naarBron(v) {
    if (!this.secBronnen) return;
    this.secBronnen.open();
    toonBron(this.secBronnen.body, v);
  }

  tekstVoorKopie() {
    const regels = [];
    if (this.berekening && this.berekening.onderwerp) regels.push(this.berekening.onderwerp);
    if (this.berekening && this.berekening.toelichting) regels.push(this.berekening.toelichting);
    if (!this.controle) regels.push("ONGECONTROLEERD: de citeercontrole is niet uitgevoerd. Lees dit niet als onderbouwd antwoord.");
    if (this.fout && this.fout.afgebroken) regels.push("AFGEBROKEN: het model viel weg; dit antwoord is onvolledig.");
    if (this.controle && this.controle.afgekapt) regels.push("AFGEKAPT: het antwoord is onvolledig en de vervolgstap ontbreekt mogelijk.");
    regels.push("", this.gemaskeerd || this.tekst, "", "Bronnen:");
    for (const b of this.bronnen) regels.push(`- ${b.label}${b.titel ? ` (${b.titel})` : ""}${b.url ? ` ${b.url}` : ""}`);
    if (this.controle) regels.push("", `Controle van verwijzingen: ${this.controle.oordeel}`);
    return regels.join("\n");
  }

  async kopieer() {
    const t = this.tekstVoorKopie();
    try { await navigator.clipboard.writeText(t); this.kopieerKnop.lastChild.textContent = "Gekopieerd"; }
    catch { this.kopieerKnop.lastChild.textContent = "Kopiëren mislukt"; }
    setTimeout(() => { this.kopieerKnop.lastChild.textContent = "Kopieer"; }, 1800);
  }
}
