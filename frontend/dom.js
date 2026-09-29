// Minimale DOM-hulp. Bewust GEEN innerHTML: tekst van het model, uit het corpus en van de
// gebruiker (een geplakt dossier) komt altijd als tekstknoop in de pagina, nooit als markup.
const SVG = "http://www.w3.org/2000/svg";
const SVG_TAGS = new Set(["svg", "path", "circle", "rect", "line"]);

export function h(tag, props, ...kinderen) {
  const el = SVG_TAGS.has(tag) ? document.createElementNS(SVG, tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "stijl") el.setAttribute("style", v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  voegToe(el, kinderen);
  return el;
}

export function voegToe(el, kinderen) {
  for (const k of kinderen.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
  return el;
}

export function leeg(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

const ICONEN = {
  schild: ["M12 3l7 3v5c0 5-3 8.5-7 10-4-1.5-7-5-7-10V6l7-3z", "M9 12l2 2 4-4"],
  weegschaal: ["M12 4v16", "M8 20h8", "M5 7h14", "M5 7l-3 6a3 3 0 0 0 6 0L5 7z", "M19 7l-3 6a3 3 0 0 0 6 0l-3-6z"],
  rekenmachine: ["M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z", "M8 7h8",
    "M8.5 12h.01", "M12 12h.01", "M15.5 12h.01", "M8.5 16h.01", "M12 16h.01", "M15.5 16h.01"],
  zandloper: ["M7 3h10", "M7 21h10", "M8 3v4l4 5-4 5v4", "M16 3v4l-4 5 4 5v4"],
  procent: ["M19 5L5 19", ["c", 7.5, 7.5, 2], ["c", 16.5, 16.5, 2]],
  dossier: ["M9 4h6a1 1 0 0 1 1 1v1H8V5a1 1 0 0 1 1-1z", "M8 6H6a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-2", "M9 14l2 2 4-4"],
  kolommen: ["M4 5h7v14H4z", "M13 5h7v14h-7z"],
  bord: ["M12 3v18", "M6 5h11l3 3.5-3 3.5H6z", "M8 21h8"],
  brief: ["M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z", "M14 3v4h4", "M10 12l4 4", "M14 12l-4 4"],
  notitie: ["M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z", "M14 3v4h4", "M9 12h6", "M9 16h6", "M9 8h2"],
  meter: ["M4 17a8 8 0 1 1 16 0", "M12 17l4-5", "M4 17h16"],
  boek: ["M3 5.5C5 4 8 4 12 6c4-2 7-2 9-.5V19c-2-1.5-5-1.5-9 .5-4-2-7-2-9-.5z", "M12 6v13.5"],
  waarschuwing: ["M12 4l9 16H3z", "M12 10v4", "M12 17.2h.01"],
  info: [["c", 12, 12, 9], "M12 11v5", "M12 8h.01"],
  vink: ["M5 12.5l4.5 4.5L19 7.5"],
  kruis: ["M6 6l12 12", "M18 6L6 18"],
  chevron: ["M9 6l6 6-6 6"],
  extern: ["M14 4h6v6", "M20 4l-9 9", "M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"],
  menu: ["M4 7h16", "M4 12h16", "M4 17h16"],
  kopie: ["M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z", "M5 15V5a1 1 0 0 1 1-1h10"],
  stop: ["M7 7h10v10H7z"],
  klok: [["c", 12, 12, 9], "M12 7v5l3 2"],
};

export function icoon(naam, grootte = 18) {
  const svg = h("svg", { viewBox: "0 0 24 24", width: grootte, height: grootte, fill: "none",
    stroke: "currentColor", "stroke-width": "1.7", "stroke-linecap": "round", "stroke-linejoin": "round",
    "aria-hidden": "true", focusable: "false" });
  for (const d of ICONEN[naam] || []) {
    if (Array.isArray(d)) svg.append(h("circle", { cx: d[1], cy: d[2], r: d[3] }));
    else svg.append(h("path", { d }));
  }
  return svg;
}
