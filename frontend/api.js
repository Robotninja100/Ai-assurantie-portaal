// Praat met de backend. De vraag-eindpunt levert server-sent events; EventSource kan geen POST,
// dus lezen we de stroom zelf.
export async function haalJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

function leesFout(j, status) {
  const d = j && j.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
  return `HTTP ${status}`;
}

export async function stelVraag(functie, invoer, opGebeurtenis, signal) {
  const res = await fetch("/api/vraag", {
    method: "POST", signal,
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ functie, invoer }),
  });
  if (!res.ok) {
    let j = null;
    try { j = await res.json(); } catch { /* geen json */ }
    const e = new Error(leesFout(j, res.status));
    e.invoerfout = res.status === 400 || res.status === 422;
    throw e;
  }
  const lezer = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await lezer.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const blok = buf.slice(0, i);
      buf = buf.slice(i + 2);
      for (const regel of blok.split("\n")) {
        if (!regel.startsWith("data:")) continue;          // ': keepalive' en lege regels
        const data = regel.slice(5).trim();
        if (data === "[DONE]") return;
        try { opGebeurtenis(JSON.parse(data)); } catch (e) { console.error("onleesbare gebeurtenis", data, e); }
      }
    }
  }
}
