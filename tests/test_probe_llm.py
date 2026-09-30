"""De rooktest voor het taalmodel: welke modellen worden geprobeerd en wanneer telt een uitkomst als geslaagd."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import probe_llm  # noqa: E402


def _m(id, ctx=262144, uit=("text",)):
    return {"id": id, "context_length": ctx, "architecture": {"output_modalities": list(uit)}}


def test_kandidaten_zijn_gratis_tekstmodellen_met_genoeg_context():
    data = [
        _m("inclusionai/ling-3.0-flash-sante:free"),
        _m("inclusionai/ling-3.0-flash-fin"),                       # betaald: geen :free
        _m("openrouter/free"),                                       # de router kiest zelf een model: onvoorspelbaar
        _m("nvidia/nemotron-3.5-content-safety:free", 128000),       # geen schrijver
        _m("google/lyria-3-clip-preview:free", 1048576, ("text", "audio")),
        _m("kleintje/klein-8k:free", 8000),                          # te weinig context voor de bronnen
        _m("cohere/north-mini-code:free", 256000),                   # codemodel
        _m("qwen/qwen3.8-27b:free"),
    ]
    assert probe_llm.kies_kandidaten(data) == ["inclusionai/ling-3.0-flash-sante:free", "qwen/qwen3.8-27b:free"]


def test_eerder_afgewezen_modellen_blijven_weg_tenzij_erom_gevraagd_wordt():
    data = [_m("google/gemma-4-31b-it:free"), _m("qwen/qwen3.8-27b:free"), _m("poolside/laguna-s-2.1:free")]
    assert probe_llm.kies_kandidaten(data) == ["qwen/qwen3.8-27b:free"]
    assert len(probe_llm.kies_kandidaten(data, ook_afgewezen=True)) == 3


def _goed(**extra):
    r = {"ok": True, "einde": "stop", "lekt_redenering": False, "nederlands": True, "noemt_20_000": True,
         "verzint_bedrag_of_artikel": False}
    r.update(extra)
    return r


def test_een_model_slaagt_alleen_als_alles_klopt():
    assert probe_llm.geslaagd(_goed())
    for slecht in ({"ok": False}, {"einde": "length"}, {"lekt_redenering": True}, {"nederlands": False},
                   {"noemt_20_000": False}, {"verzint_bedrag_of_artikel": True}):
        assert not probe_llm.geslaagd(_goed(**slecht)), slecht
