// Opmaak in Nederlandse conventies: 1.234,56 en 10 maart 2027.
const EUR = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" });
const GETAL = new Intl.NumberFormat("nl-NL");
const PCT = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const DATUM = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "long", year: "numeric" });
const KORT = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short", year: "numeric" });

export const eur = (x) => (x == null || x === "" ? "—" : EUR.format(Number(x)));
export const pct = (x) => `${PCT.format(Number(x))}%`;
export const aantal = (n) => GETAL.format(n);
const naarDatum = (iso) => new Date(`${iso}T12:00:00`);      // middag: geen dagverschuiving door tijdzones
export const datum = (iso) => (iso ? DATUM.format(naarDatum(iso)) : "—");
export const korteDatum = (iso) => (iso ? KORT.format(naarDatum(iso)) : "—");
export const dagenTussen = (a, b) => Math.round((naarDatum(b) - naarDatum(a)) / 86400000);
export const vandaagIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export function meervoud(n, een, veel) {
  return `${GETAL.format(n)} ${n === 1 ? een : veel}`;
}

/**
 * Leest een bedrag zoals een Nederlander het typt: "250.000", "1.250,50", "€ 5000", "0,5".
 * Geeft null bij leeg, NaN bij onleesbaar. Een punt met precies drie cijfers erachter is een
 * duizendtalscheiding, anders een decimaalteken.
 */
export function leesGetal(tekst) {
  let t = String(tekst ?? "").replace(/[€\s]/g, "");
  if (t === "") return null;
  if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
  else if (/^\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, "");
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : NaN;
}

/** 'BW:7:958:5' -> 'art. 7:958 lid 5 BW';  'BGfo:86d:1' -> 'art. 86d lid 1 BGfo' */
export function grondslagLabel(g) {
  const d = g.split(":");
  const wet = d[0];
  const artikel = wet === "BW" || wet === "Wft" ? d.slice(1, 3).join(":") : d[1];
  const lid = wet === "BW" || wet === "Wft" ? d[3] : d[2];
  return `art. ${artikel}${lid ? ` lid ${lid}` : ""} ${wet}`;
}
export function grondslagSleutel(g) {
  const d = g.split(":");
  return d[0] === "BW" || d[0] === "Wft" ? d.slice(1, 3).join(":") : d[1];
}
