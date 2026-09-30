import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _geen_netwerk_voor_de_modelketen(monkeypatch):
    """
    De tests raken de openbare modellenlijst van OpenRouter niet (geen netwerk, en de uitkomst hangt af van de dag).
    Wie de live-controle van de keten toetst, zet LIVE_KETEN zelf aan tegen een nepserver.
    """
    import llm
    monkeypatch.setattr(llm, "LIVE_KETEN", False)
    monkeypatch.setattr(llm, "_KETEN_EXPLICIET", False)
    monkeypatch.setitem(llm._live, "ids", None)
    monkeypatch.setitem(llm._live, "tijd", 0.0)
    monkeypatch.setitem(llm._live, "mislukt_tot", 0.0)
    monkeypatch.setitem(llm._live, "bezig", False)
