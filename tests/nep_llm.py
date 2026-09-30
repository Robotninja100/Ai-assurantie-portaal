"""
TESTDOUBLE voor het taalmodel, alleen bedoeld voor tests van de keten UI -> API -> streaming -> citeerbewaker.

Het bootst OpenRouter's server-sent-events-formaat na en schrijft een vast opgemaakt antwoord dat
verwijst naar bronnen die het uit de meegestuurde systeemprompt haalt, plus één bewust verzonnen
verwijzing (art. 7:999) om de weergave van een ongefundeerde verwijzing te kunnen toetsen.
Het zegt NIETS over de kwaliteit van een echt model; daarvoor is de criticusronde.
"""
import http.server
import json
import re
import threading
import time


def antwoord_voor(systeem: str) -> str:
    wet = re.findall(r"\[(?:BW|Wft|BGfo) art\. ([\w:]+)\]", systeem)
    kifid = re.findall(r"\[Kifid (\d{4}-\d{3,5})\]", systeem)
    clausule = re.findall(r"\[[^\]]*? art\. (\d+(?:\.\d+)+)[^\]]*\]", systeem)
    artikel = wet[0] if wet else "7:942"
    delen = [
        f"**Kort antwoord.** Op grond van art. {artikel} wordt de situatie beoordeeld zoals hieronder beschreven.\n\n",
        "1. **Wat de bronnen zeggen.** ",
    ]
    if kifid:
        delen.append(f"In uitspraak {kifid[0]} beoordeelde de commissie een vergelijkbare situatie. ")
    if clausule:
        delen.append(f"Clausule art. {clausule[0]} regelt hetzelfde punt in de polisvoorwaarden. ")
    delen.append("\n\n2. **Wat ontbreekt.** Het is niet bekend wanneer de schade is gemeld.\n\n")
    delen.append("3. **Risico.** Een beroep op art. 7:999 lid 2 zou hier niet slagen.\n\n")
    delen.append("**Vervolgstap:** vraag de meldingsbevestiging op en leg die vast in het dossier.")
    return "".join(delen)


class NepLLM:
    def __init__(self, poort: int = 0, vertraging: float = 0.0, einde: str = "stop", knip: int = 0,
                 stukvertraging: float = 0.0):
        nep = self
        self.verzoeken = []
        self.onderbroken = threading.Event()   # de client (ons portaal) heeft de verbinding voortijdig gesloten
        self.stukken = 0                       # zoveel stukken zijn er daadwerkelijk geschreven
        self.stukvertraging = stukvertraging   # pauze tussen twee stukken: een model dat echt 'denkt'
        self.vertraging = vertraging
        self.einde = einde          # 'length' bootst een model na dat tegen max_tokens aanliep
        self.knip = knip            # bij 'length': na zoveel tekens stoppen

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def stuur(self, tekst):
                data = tekst.encode()
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                nep.verzoeken.append(body)
                tekst = antwoord_voor(body["messages"][0]["content"])
                if nep.einde == "length" and nep.knip:
                    tekst = tekst[:nep.knip]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    self.stuur(": OPENROUTER PROCESSING\n\n")
                    time.sleep(nep.vertraging)
                    for i in range(0, len(tekst), 16):
                        self.stuur("data: " + json.dumps({"choices": [{"delta": {"content": tekst[i:i + 16]}}]}) + "\n\n")
                        nep.stukken += 1
                        time.sleep(nep.stukvertraging)
                    self.stuur("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": nep.einde}]}) + "\n\n")
                    self.stuur("data: [DONE]\n\n")
                    self.wfile.write(b"0\r\n\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    nep.onderbroken.set()

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", poort), Handler)
        self.poort = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.poort}/v1/chat/completions"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
