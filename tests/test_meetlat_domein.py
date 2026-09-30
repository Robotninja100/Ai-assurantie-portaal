"""
Manifestcontract (klasse, domein, taal, geladen_ok, kwaliteit), domeinfilter en ankers
(audit-punten 5 en 6), plus de dynamische verboden-woordenlijst uit de manifesten.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from test_meetlat_hulp import blind_ab, bouw_bronnen, draai, lees_sleutel


def _png(pad: Path, w=40, h=40):
    pad.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (200, 200, 200)).save(pad)


def _manifest(map_: Path, data) -> None:
    map_.mkdir(parents=True, exist_ok=True)
    (map_ / "manifest.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------- manifest lezen: alle vormen
def test_manifest_lijstvorm_zoals_renders_comps(tmp_path):
    _manifest(tmp_path, [
        {"id": "stripe_api_docs", "bron_naam": "Stripe", "bestand": "s_1440.png", "wat_het_toont": "Docs",
         "klasse": "product_ui", "domein": "internationaal", "taal": "en", "geladen_ok": True},
        {"id": "kapot", "bron_naam": "Kapot", "bestand": "k_1440.png", "geladen_ok": False, "fout": "HTTP 500"}])
    m = blind_ab._lees_manifest(tmp_path)
    assert m["s_1440.png"]["bron_naam"] == "Stripe" and m["s_1440.png"]["omschrijving"] == "Docs"
    assert (m["s_1440.png"]["klasse"], m["s_1440.png"]["domein"], m["s_1440.png"]["taal"]) == \
        ("product_ui", "internationaal", "en")
    assert m["s_1440.png"]["geladen_ok"] is True and m["k_1440.png"]["geladen_ok"] is False


def test_manifest_bestandenmap_zoals_renders_comps_nl_met_overerving(tmp_path):
    _manifest(tmp_path, {"set": "comps_nl", "overgeslagen": [{"slug": "weg", "reden": "x"}], "comps": [
        {"slug": "independer", "naam": "Independer - test", "klasse": "product_ui", "domein": "nl_financieel",
         "taal": "nl", "interface_elementen": "formulier",
         "bestanden": {"desktop": {"file": "i-desktop.png"},
                       "mobile": {"file": "i-mobile.png", "geladen_ok": False}}}]})
    m = blind_ab._lees_manifest(tmp_path)
    assert set(m) == {"i-desktop.png", "i-mobile.png"}               # 'overgeslagen' telt niet mee
    assert m["i-desktop.png"]["bron_naam"] == "Independer - test"     # naam wint van slug (oud gedrag)
    assert m["i-desktop.png"]["omschrijving"] == "formulier"
    assert m["i-desktop.png"]["domein"] == "nl_financieel" and m["i-desktop.png"].get("geladen_ok") is None
    assert m["i-mobile.png"]["geladen_ok"] is False and m["i-mobile.png"]["klasse"] == "product_ui"
    assert m["i-mobile.png"]["viewport_manifest"] == "mobile"


def test_manifest_decoyvorm_met_kwaliteit_per_bestand_of_voor_alles(tmp_path):
    _manifest(tmp_path, {"set": "decoy", "kwaliteit": "matig", "klasse": "decoy", "bestanden": [
        {"viewport": "desktop", "bestand": "a-desktop.png"},
        {"viewport": "mobile", "bestand": "a-mobile.png", "kwaliteit": "zeer_zwak"}]})
    m = blind_ab._lees_manifest(tmp_path)
    assert m["a-desktop.png"]["kwaliteit"] == "matig" and m["a-desktop.png"]["klasse"] == "decoy"
    assert m["a-mobile.png"]["kwaliteit"] == "zeer_zwak"                 # het meest specifieke wint


def test_manifest_varianten_decoys_ankers_items(tmp_path):
    _manifest(tmp_path, {"decoys": [{"id": "d1", "kwaliteit": "zwak", "bestanden": [
        {"bestand": "d1-desktop.png"}, "d1-mobile.png"]}],
        "ankers": [{"id": "linear", "klasse": "anker", "bestand": "l-desktop.png"}]})
    m = blind_ab._lees_manifest(tmp_path)
    assert set(m) == {"d1-desktop.png", "d1-mobile.png", "l-desktop.png"}
    assert m["d1-mobile.png"]["kwaliteit"] == "zwak" and m["l-desktop.png"]["klasse"] == "anker"


def test_onleesbaar_manifest_geeft_melding_en_geen_crash(tmp_path):
    (tmp_path / "manifest.json").write_text("{ dit is geen json", encoding="utf-8")
    data, meldingen = blind_ab.lees_manifest_met_meldingen(tmp_path)
    assert data == {} and any("onleesbaar" in x for x in meldingen)
    _png(tmp_path / "x-desktop.png")
    bron = blind_ab.verzamel_bronnen([tmp_path], "comp")[0]
    assert bron.klasse == "product_ui" and any("onleesbaar" in x for x in bron.meldingen)


def test_onbekende_waarden_worden_genegeerd_met_melding(tmp_path):
    _manifest(tmp_path, [{"bestand": "a_1440.png", "klasse": "fantasie", "domein": "mars", "taal": "de",
                          "kwaliteit": "prachtig", "geladen_ok": "misschien"}])
    m, meldingen = blind_ab.lees_manifest_met_meldingen(tmp_path)
    rec = m["a_1440.png"]
    for veld in ("klasse", "domein", "taal", "kwaliteit", "geladen_ok"):
        assert veld not in rec or rec[veld] in (None, "")
    assert len(meldingen) == 5


@pytest.mark.parametrize("waarde,verwacht", [(True, True), (False, False), ("false", False), ("nee", False),
                                             ("true", True), (0, False), (1, True)])
def test_geladen_ok_accepteert_meerdere_schrijfwijzen(tmp_path, waarde, verwacht):
    _manifest(tmp_path, [{"bestand": "a_1440.png", "geladen_ok": waarde}])
    assert blind_ab._lees_manifest(tmp_path)["a_1440.png"]["geladen_ok"] is verwacht


def test_geladen_ok_false_op_hoger_niveau_geldt_voor_alle_bestanden_eronder(tmp_path):
    _manifest(tmp_path, {"comps": [{"slug": "x", "geladen_ok": False, "bestanden": {
        "desktop": {"file": "x-d.png", "geladen_ok": True}, "mobile": {"file": "x-m.png"}}}]})
    m = blind_ab._lees_manifest(tmp_path)
    assert m["x-d.png"]["geladen_ok"] is False and m["x-m.png"]["geladen_ok"] is False


# ---------------------------------------------------------------- veilige standaardwaarden
def test_ontbrekende_classificatie_wordt_product_ui_met_waarschuwing_en_domein_volgens_de_map(tmp_path):
    comps, nl = tmp_path / "comps", tmp_path / "comps_nl"
    _png(comps / "a_1440.png")
    _png(nl / "b-desktop-1440x900.png")
    _manifest(comps, [{"id": "a", "bron_naam": "Aa", "bestand": "a_1440.png"}])
    bronnen = blind_ab.verzamel_bronnen([comps, nl], "comp")
    a = next(b for b in bronnen if b.pad.name == "a_1440.png")
    b = next(b for b in bronnen if b.pad.name.startswith("b-"))
    assert (a.klasse, a.domein, a.taal) == ("product_ui", "internationaal", "en")
    assert (b.klasse, b.domein, b.taal) == ("product_ui", "nl_financieel", "nl")
    assert set(a.ontbrekend) == {"klasse", "domein", "soort_scherm"}
    assert set(b.ontbrekend) == {"klasse", "domein", "soort_scherm"}
    assert a.geladen_ok is None


def test_klasse_in_een_comps_manifest_kan_een_bron_tot_anker_decoy_of_ours_maken(tmp_path):
    for n in ("a", "d", "o", "c"):
        _png(tmp_path / f"{n}_1440.png")
    _manifest(tmp_path, [{"bestand": "a_1440.png", "klasse": "anker"}, {"bestand": "d_1440.png", "klasse": "decoy",
                                                                       "kwaliteit": "matig"},
                         {"bestand": "o_1440.png", "klasse": "ours"},
                         {"bestand": "c_1440.png", "klasse": "marketing"}])
    per = {b.pad.name: b for b in blind_ab.verzamel_bronnen([tmp_path], "comp")}
    assert per["a_1440.png"].soort == "anker" and per["a_1440.png"].domein == "anker"
    assert per["d_1440.png"].soort == "decoy" and per["d_1440.png"].kwaliteit == "matig"
    assert per["o_1440.png"].soort == "ours" and per["o_1440.png"].domein == "ours"
    assert per["c_1440.png"].soort == "comp" and per["c_1440.png"].klasse == "marketing"


def test_de_map_is_leidend_als_het_manifest_er_een_speciale_bron_anders_noemt(tmp_path):
    _png(tmp_path / "d-desktop.png")
    _manifest(tmp_path, [{"bestand": "d-desktop.png", "klasse": "product_ui"}])
    bron = blind_ab.verzamel_bronnen([tmp_path], "decoy")[0]
    assert bron.soort == "decoy" and bron.klasse == "product_ui"
    assert any("is leidend" in m for m in bron.meldingen)


def test_viewport_uit_het_manifest_als_de_bestandsnaam_het_niet_zegt(tmp_path):
    _png(tmp_path / "scherm-a.png")
    _manifest(tmp_path, [{"bestand": "scherm-a.png", "viewport": "390x844@2x"}])
    assert blind_ab.verzamel_bronnen([tmp_path], "ours")[0].viewport == "mobile"
    assert blind_ab.viewport_uit_tekst("1440x900@2x") == "desktop"
    assert blind_ab.viewport_uit_tekst("900x900") == "onbekend"


def test_kwaliteit_wordt_alleen_voor_decoys_overgenomen(tmp_path):
    _png(tmp_path / "x_1440.png")
    _manifest(tmp_path, [{"bestand": "x_1440.png", "kwaliteit": "zwak"}])
    assert blind_ab.verzamel_bronnen([tmp_path], "comp")[0].kwaliteit == ""


# ---------------------------------------------------------------- filters
def _bronnen_voor_filter(tmp_path):
    comps, nl, dec, ours, ank = (tmp_path / n for n in ("comps", "comps_nl", "decoy", "ours", "anker"))
    for d, n in ((comps, "intl"), (comps, "markt"), (comps, "kapot"), (comps, "onbekend"), (nl, "nl"),
                 (dec, "dec"), (ours, "ons"), (ank, "top")):
        _png(d / f"{n}_desktop_1440.png")
    _manifest(comps, [
        {"bestand": "intl_desktop_1440.png", "bron_naam": "Intl", "klasse": "product_ui", "domein": "internationaal"},
        {"bestand": "markt_desktop_1440.png", "bron_naam": "Markt", "klasse": "marketing", "domein": "internationaal"},
        {"bestand": "kapot_desktop_1440.png", "bron_naam": "Kapot", "klasse": "product_ui",
         "domein": "internationaal", "geladen_ok": False},
        {"bestand": "onbekend_desktop_1440.png", "bron_naam": "Onbekend", "klasse": "product_ui"}])
    _manifest(nl, {"comps": [{"slug": "nl", "naam": "Nl", "klasse": "product_ui", "domein": "nl_financieel",
                              "bestanden": {"desktop": {"file": "nl_desktop_1440.png"}}}]})
    _manifest(dec, {"bestanden": [{"bestand": "dec_desktop_1440.png", "klasse": "decoy", "kwaliteit": "zwak"}]})
    _manifest(ank, {"bestanden": [{"bestand": "top_desktop_1440.png", "klasse": "anker"}]})
    return (blind_ab.verzamel_bronnen([comps, nl], "comp") + blind_ab.verzamel_bronnen([ours], "ours")
            + blind_ab.verzamel_bronnen([dec], "decoy") + blind_ab.verzamel_bronnen([ank], "anker"))


def _namen(bronnen):
    return sorted(b.bron_naam for b in bronnen)


def test_domeinfilter_nl_financieel_houdt_alleen_nl_comps_plus_decoy_anker_en_ons(tmp_path):
    alle = _bronnen_voor_filter(tmp_path)
    behouden, uitgesloten = blind_ab.filter_bronnen(alle, "nl_financieel")
    assert _namen(behouden) == ["Nl", "dec_desktop_1440", "ons_desktop_1440", "top_desktop_1440"]
    redenen = {u["bron_naam"]: u["reden"] for u in uitgesloten}
    assert "domein=internationaal" in redenen["Intl"]
    assert "klasse=marketing" in redenen["Markt"]
    assert "geladen_ok=false" in redenen["Kapot"]
    assert "domein=onbekend" in redenen["Onbekend"] or "domein=internationaal" in redenen["Onbekend"]


def test_domeinfilter_internationaal_houdt_alleen_internationale_comps(tmp_path):
    behouden, _ = blind_ab.filter_bronnen(_bronnen_voor_filter(tmp_path), "internationaal")
    comps = [b.bron_naam for b in behouden if b.soort == "comp"]
    assert sorted(comps) == ["Intl", "Onbekend"]          # 'Onbekend': domein volgens de map (comps -> internationaal)
    assert {b.soort for b in behouden} == {"comp", "decoy", "anker", "ours"}


def test_domeinfilter_alles_mengt_maar_sluit_marketing_en_kapotte_opnames_uit(tmp_path):
    behouden, uitgesloten = blind_ab.filter_bronnen(_bronnen_voor_filter(tmp_path), "alles")
    assert "Nl" in _namen(behouden) and "Intl" in _namen(behouden)
    assert sorted(u["bron_naam"] for u in uitgesloten) == ["Kapot", "Markt"]


def test_inclusief_marketing_neemt_marketing_mee_maar_geladen_ok_false_nooit(tmp_path):
    behouden, uitgesloten = blind_ab.filter_bronnen(_bronnen_voor_filter(tmp_path), "alles", inclusief_marketing=True)
    assert "Markt" in _namen(behouden) and "Kapot" not in _namen(behouden)
    assert [u["bron_naam"] for u in uitgesloten] == ["Kapot"]


def test_speciale_bronnen_vallen_nooit_buiten_het_domeinfilter(tmp_path):
    alle = _bronnen_voor_filter(tmp_path)
    for domein in ("nl_financieel", "internationaal"):
        behouden, _ = blind_ab.filter_bronnen(alle, domein)
        assert {"ours", "decoy", "anker"} <= {b.soort for b in behouden}


def test_onbekend_domeinfilter_is_een_fout():
    with pytest.raises(ValueError):
        blind_ab.filter_bronnen([], "mars")


# ---------------------------------------------------------------- hele rondes per domein
def _items(sleutel):
    return [i for d in sleutel["viewports"].values() for i in d["items"]]


def test_ronde_nl_financieel_bevat_alleen_nl_comps_plus_decoy_anker_en_ons(tmp_path):
    m = bouw_bronnen(tmp_path)
    assert draai(tmp_path, m, "--domein", "nl_financieel") == 0
    s = lees_sleutel(tmp_path)
    assert s["meetlat"]["domein_filter"] == "nl_financieel"
    comps = [i for i in _items(s) if i["soort"] == "comp"]
    assert comps and all(i["domein"] == "nl_financieel" for i in comps)
    assert {i["soort"] for i in _items(s)} == {"comp", "ours", "decoy", "anker"}
    assert not any(i["bron_naam"].startswith("Internationaal") for i in _items(s))
    assert any("domein=internationaal" in u["reden"] for u in s["uitgesloten"])
    assert not any("gemengde ronde" in w for w in s["waarschuwingen"])


def test_ronde_internationaal_bevat_alleen_internationale_comps(tmp_path):
    m = bouw_bronnen(tmp_path)
    assert draai(tmp_path, m, "--domein", "internationaal") == 0
    s = lees_sleutel(tmp_path)
    comps = [i for i in _items(s) if i["soort"] == "comp"]
    assert comps and all(i["domein"] == "internationaal" for i in comps)
    assert not any(i["bron_naam"].startswith("Nederlands") for i in _items(s))
    assert s["meetlat"]["domein_filter"] == "internationaal"


def test_ronde_alles_is_gemengd_en_dat_staat_in_de_sleutel(tmp_path, capsys):
    m = bouw_bronnen(tmp_path)
    assert draai(tmp_path, m) == 0
    s = lees_sleutel(tmp_path)
    assert s["meetlat"]["domein_filter"] == "alles"
    assert {i["domein"] for i in _items(s) if i["soort"] == "comp"} == {"internationaal", "nl_financieel"}
    assert any("gemengde ronde" in w for w in s["waarschuwingen"])
    assert "gemengde ronde" in capsys.readouterr().out


def test_kapotte_opnames_en_marketing_komen_niet_in_een_ronde(tmp_path):
    m = bouw_bronnen(tmp_path, mobiel=False)
    lijst = json.loads((m["comps"] / "manifest.json").read_text())
    lijst[0]["geladen_ok"] = False                                    # intl0 is mislukt
    lijst[1]["klasse"] = "marketing"                                  # intl1 is een marketingpagina
    (m["comps"] / "manifest.json").write_text(json.dumps(lijst))
    assert draai(tmp_path, m) == 0
    namen = {i["bron_naam"] for i in _items(lees_sleutel(tmp_path))}
    assert "Internationaal 0" not in namen and "Internationaal 1" not in namen and "Internationaal 2" in namen
    # ook met --inclusief-marketing komt een geladen_ok=false-opname er nooit in
    assert draai(tmp_path, m, "--inclusief-marketing", ronde="r2") == 0
    namen2 = {i["bron_naam"] for i in _items(lees_sleutel(tmp_path, "r2"))}
    assert "Internationaal 1" in namen2 and "Internationaal 0" not in namen2
    s = lees_sleutel(tmp_path, "r2")
    assert [u["bron_naam"] for u in s["uitgesloten"]] == ["Internationaal 0"]


def test_sleutel_meldt_ontbrekende_classificatie(tmp_path):
    m = bouw_bronnen(tmp_path, mobiel=False)
    lijst = json.loads((m["comps"] / "manifest.json").read_text())
    for e in lijst:
        e.pop("klasse", None)
        e.pop("domein", None)
    (m["comps"] / "manifest.json").write_text(json.dumps(lijst))
    assert draai(tmp_path, m) == 0
    s = lees_sleutel(tmp_path)
    assert any("classificatie ontbreekt" in w for w in s["waarschuwingen"])
    assert any("soort_scherm ontbreekt bij 6 beelden" in w for w in s["waarschuwingen"])   # 3 comps + ons + 2 nl-comps
    assert len([x for x in s["classificatie_ontbreekt"] if "klasse" in x["ontbrekend"]]) == 3
    assert {i["klasse"] for i in _items(s) if i["bron_naam"].startswith("Internationaal")} == {"product_ui"}
    assert {i["domein"] for i in _items(s) if i["bron_naam"].startswith("Internationaal")} == {"internationaal"}


# ---------------------------------------------------------------- ankers (positieve controle)
def test_anker_is_gemarkeerd_en_ook_zonder_map_via_klasse_in_een_manifest(tmp_path):
    m = bouw_bronnen(tmp_path, anker=False, mobiel=False)
    # geen anker: waarschuwing, en de sleutel zegt het
    assert draai(tmp_path, m) == 0
    s = lees_sleutel(tmp_path)
    assert s["meetlat"]["heeft_anker"] is False and not any(i["is_anker"] for i in _items(s))
    assert any("GEEN ANKER" in w for w in s["waarschuwingen"])
    # een comp met klasse anker in het comps-manifest telt ook
    lijst = json.loads((m["comps"] / "manifest.json").read_text())
    lijst[0]["klasse"] = "anker"
    (m["comps"] / "manifest.json").write_text(json.dumps(lijst))
    assert draai(tmp_path, m, ronde="r2") == 0
    s2 = lees_sleutel(tmp_path, "r2")
    ankers = [i for i in _items(s2) if i["is_anker"]]
    assert s2["meetlat"]["heeft_anker"] is True and len(ankers) == 1
    assert ankers[0]["soort"] == "anker" and ankers[0]["bron_naam"] == "Internationaal 0"


def test_ankers_doen_altijd_mee_ook_bij_een_domeinfilter(tmp_path):
    m = bouw_bronnen(tmp_path, mobiel=False)
    assert draai(tmp_path, m, "--domein", "nl_financieel") == 0
    assert sum(1 for i in _items(lees_sleutel(tmp_path)) if i["is_anker"]) == 1


def test_decoykwaliteit_komt_in_de_sleutel(tmp_path):
    m = bouw_bronnen(tmp_path, decoys=(("zeer_zwak", 600), ("redelijk", 900)), mobiel=False)
    assert draai(tmp_path, m) == 0
    kw = {i["bron_naam"]: i["kwaliteit"] for i in _items(lees_sleutel(tmp_path)) if i["is_decoy"]}
    assert kw == {"decoy0": "zeer_zwak", "decoy1": "redelijk"}


# ---------------------------------------------------------------- dynamische verboden woorden
def test_verboden_woorden_worden_uit_de_manifesten_gelezen(tmp_path):
    comps, nl, dec = tmp_path / "comps", tmp_path / "comps_nl", tmp_path / "decoy"
    _manifest(comps, [
        {"id": "afas_insite", "bron_naam": "AFAS Software", "bestand": "a.png", "url": "https://www.afasgroep.nl/insite"},
        {"id": "cal_com_booking", "bron_naam": "Cal.com", "bestand": "c.png", "url": "https://cal.com/rick"},
        {"id": "grafana_play_dashboard", "bron_naam": "Grafana Play", "bestand": "g.png",
         "url": "https://play.grafana.org/d/x"}])
    _manifest(nl, {"comps": [
        {"slug": "zilverreiger-loonrun", "naam": "Zilverreiger - loonrun starten",
         "bron_url": "https://www.zilverreiger.nl/inloggen",
         "bestanden": {"desktop": {"file": "n.png"}}},
        {"slug": "geld-nl-autoverzekering", "naam": "Geld.nl - autoverzekering", "bron_url": "https://www.geld.nl/x",
         "bestanden": {"desktop": {"file": "g.png"}}}]})
    _manifest(dec, {"merknamen": ["Zebraboom"], "bestanden": [{"bestand": "d.png"}]})
    termen = blind_ab.bouw_verboden_termen([comps, nl, dec])
    vormen = {t.vorm for t in termen.alle}
    for verwacht in ("Nmbrs", "Zilverreiger", "afasgroep", "AFAS", "calcom", "cal", "grafana", "geldnl", "Zebraboom",
                     "PolisBeheer", "Interpolis"):                   # dynamisch + vast
        assert blind_ab.vouw(verwacht) in vormen, verwacht
    for gewoon in ("docs", "dashboard", "eigen", "exact", "geld", "play", "portaal", "verzekering", "online"):
        assert blind_ab.vouw(gewoon) not in vormen, f"{gewoon} is een gewoon woord en geen merk"
    herkomst = {t.vorm: t.bron for t in termen.alle}
    assert herkomst[blind_ab.vouw("Zebraboom")].startswith("manifest:decoy")
    assert herkomst[blind_ab.vouw("Zilverreiger")].startswith("manifest:comps_nl")     # niet in de vaste lijst
    assert herkomst[blind_ab.vouw("afasgroep")].startswith("manifest:comps")               # uit de url van een comp


def test_korte_en_dubbelzinnige_termen_gelden_alleen_als_heel_woord():
    termen = blind_ab.bouw_verboden_termen()
    modus = {t.vorm: t.modus for t in termen.alle}
    for kort in ("cal", "dub", "ramp", "stripe", "linear", "notion", "kvk", "anwb", "asr"):
        assert modus[blind_ab.vouw(kort)] == "woord", kort
    for lang in ("interpolis", "polisbeheer", "moneybird", "klaverblad", "artifation", "vercel"):
        assert modus[blind_ab.vouw(lang)] == "sub", lang


def test_gewone_woorden_uit_slugs_zijn_geen_verboden_merk(tmp_path):
    """Echte manifesten: slug data-overheid-datasets en wetten-overheid-wft. 'data' en 'wetten' zijn gewoon
    Nederlands en werden overal in de pagina's weggemaskeerd ("Data eigenaar"); de domeinnaam blijft verboden."""
    nl = tmp_path / "comps_nl"
    _manifest(nl, {"comps": [
        {"slug": "data-overheid-datasets", "naam": "data.overheid.nl - datasets zoeken",
         "bron_url": "https://data.overheid.nl/datasets", "bestanden": {"desktop": {"file": "a.png"}}},
        {"slug": "wetten-overheid-wft", "naam": "wetten.overheid.nl - Wet op het financieel toezicht",
         "bron_url": "https://wetten.overheid.nl/BWBR0020368/", "bestanden": {"desktop": {"file": "b.png"}}}]})
    vormen = {t.vorm for t in blind_ab.bouw_verboden_termen([nl]).alle}
    for gewoon in ("data", "wetten", "overheid", "datasets"):
        assert blind_ab.vouw(gewoon) not in vormen, gewoon
    for merk in ("data.overheid.nl", "wetten.overheid.nl"):
        assert blind_ab.vouw(merk) in vormen, merk


def test_een_losse_slugsectie_telt_alleen_als_heel_woord(tmp_path):
    nl = tmp_path / "comps_nl"
    _manifest(nl, {"comps": [{"slug": "zilverreiger-loonrun", "bestanden": {"desktop": {"file": "a.png"}}}]})
    termen = blind_ab.bouw_verboden_termen([nl])
    term = next(x for x in termen.alle if x.vorm == blind_ab.vouw("zilverreiger"))
    assert term.modus == "woord" and term.bron.endswith(":zwak") and not term.fuzzy

    def treffers(tekst):
        regel = blind_ab._regel_uit_woorden([(tekst, (0.0, 0.0, 200.0, 20.0))], 0.9, "t")
        return blind_ab.vind_lekken([regel], termen)

    assert treffers("Zilverreiger") and not treffers("Zilverreigerverzekeringen")


def test_eigen_namen_extra_woorden_en_bestand_komen_in_de_lijst(tmp_path):
    termen = blind_ab.bouw_verboden_termen(extra=["Kwartelkoning"], eigen_namen=["Zilvermeeuw Portaal"])
    vormen = {t.vorm: t.bron for t in termen.alle}
    assert vormen[blind_ab.vouw("Kwartelkoning")] == "operator"
    assert vormen[blind_ab.vouw("Zilvermeeuw Portaal")] == "eigen_naam"
    # via de commandoregel
    m = bouw_bronnen(tmp_path, mobiel=False)
    lijst = tmp_path / "verboden.txt"
    lijst.write_text("# commentaar\nBlauwvoet\n\nRoodborst\n", encoding="utf-8")
    assert draai(tmp_path, m, "--verboden-bestand", str(lijst), "--eigen-namen", "Zilvermeeuw") == 0
    s = lees_sleutel(tmp_path)
    assert not any("geen eigen productnaam" in w for w in s["waarschuwingen"])
    assert draai(tmp_path, m, "--verboden-bestand", str(tmp_path / "bestaat_niet.txt"), ronde="r2") == 2


# ---------------------------------------------------------------- manifestvormen (opnameagent) en soort_scherm
def test_bestanden_als_map_met_bestandsnamen_als_sleutel_wordt_gelezen(tmp_path):
    """De 'bestanden'-objectvorm van de opnameagent: een object met `bestanden`, sleutel = bestandsnaam."""
    _manifest(tmp_path, {"set": "decoy", "doel": "test", "bestanden": {
        "dec-a-desktop-1440.png": {"klasse": "decoy", "domein": "decoy", "kwaliteit": "zwak",
                                   "soort_scherm": "App / Dashboard", "bron_naam": "Decoy A"},
        "dec-a-mobile-390.png": {"klasse": "decoy", "kwaliteit": "zwak", "geladen_ok": False}}})
    m = blind_ab._lees_manifest(tmp_path)
    assert set(m) == {"dec-a-desktop-1440.png", "dec-a-mobile-390.png"}
    rec = m["dec-a-desktop-1440.png"]
    assert (rec["klasse"], rec["kwaliteit"], rec["bron_naam"]) == ("decoy", "zwak", "Decoy A")
    assert rec["soort_scherm"] == "app/dashboard"                      # genormaliseerd
    assert rec["manifest_vorm"] == "object.bestanden[bestandsnaam-map]"
    assert m["dec-a-mobile-390.png"]["geladen_ok"] is False


def test_elke_manifestvorm_krijgt_een_eigen_vormnaam(tmp_path):
    vormen = {}
    for naam, data, bestand in (
            ("lijst", [{"bestand": "a.png"}], "a.png"),
            ("comps", {"comps": [{"slug": "x", "bestanden": {"desktop": {"file": "b.png"}}}]}, "b.png"),
            ("lijstbestanden", {"bestanden": [{"bestand": "c.png"}]}, "c.png"),
            ("naammap", {"bestanden": {"d.png": {"klasse": "anker"}}}, "d.png"),
            ("decoys", {"decoys": [{"id": "d", "bestanden": [{"bestand": "e.png"}]}]}, "e.png"),
            ("enkel", {"bestand": "f.png", "klasse": "anker"}, "f.png")):
        _manifest(tmp_path / naam, data)
        vormen[naam] = blind_ab._lees_manifest(tmp_path / naam)[bestand]["manifest_vorm"]
    assert vormen == {
        "lijst": "lijst",
        "comps": "object.comps[lijst].bestanden[viewportmap]",
        "lijstbestanden": "object.bestanden[lijst]",
        "naammap": "object.bestanden[bestandsnaam-map]",
        "decoys": "object.decoys[lijst].bestanden[lijst]",
        "enkel": "object",
    }


def test_alle_vormen_samen_in_een_ronde_de_sleutel_zegt_welke_bron_uit_welke_vorm_kwam(tmp_path):
    m = bouw_bronnen(tmp_path)
    # decoy en anker in de bestandsnaam-map-vorm, ours zonder manifest
    dec = json.loads((m["decoy"] / "manifest.json").read_text())
    (m["decoy"] / "manifest.json").write_text(json.dumps({"set": "decoy", "bestanden": {
        e["bestand"]: {k: v for k, v in e.items() if k != "bestand"} for e in dec["bestanden"]}}))
    ank = json.loads((m["anker"] / "manifest.json").read_text())
    (m["anker"] / "manifest.json").write_text(json.dumps({"bestanden": {
        e["bestand"]: {k: v for k, v in e.items() if k != "bestand"} for e in ank["bestanden"]}}))
    assert draai(tmp_path, m) == 0
    s = lees_sleutel(tmp_path)
    per_soort = {}
    for it in _items(s):
        per_soort.setdefault(it["soort"], set()).add(it["manifest_vorm"])
    assert per_soort["decoy"] == {"object.bestanden[bestandsnaam-map]"}
    assert per_soort["anker"] == {"object.bestanden[bestandsnaam-map]"}
    assert per_soort["ours"] == {"geen manifest"}
    assert per_soort["comp"] == {"lijst", "object.comps[lijst].bestanden[viewportmap]"}
    assert sum(s["manifestvormen"].values()) == len(_items(s))
    assert s["manifestvormen"]["object.bestanden[bestandsnaam-map]"] == 4          # 2 decoys + 2 ankers
    kwaliteit = {i["kwaliteit"] for i in _items(s) if i["is_decoy"]}
    assert kwaliteit == {"zwak"}                                                    # ook in deze vorm gelezen
    assert sum(1 for i in _items(s) if i["is_anker"]) == 2


def test_soort_scherm_wordt_genormaliseerd_en_ontbreken_wordt_gemeld(tmp_path):
    assert blind_ab.norm_soort_scherm("  App / Dashboard ") == "app/dashboard"
    assert blind_ab.norm_soort_scherm("Docs") == "docs"
    _png(tmp_path / "a_1440.png")
    _png(tmp_path / "b_1440.png")
    _manifest(tmp_path, [{"bestand": "a_1440.png", "soort_scherm": "Formulier"}, {"bestand": "b_1440.png"}])
    per = {b.pad.name: b for b in blind_ab.verzamel_bronnen([tmp_path], "comp")}
    assert per["a_1440.png"].soort_scherm == "formulier" and "soort_scherm" not in per["a_1440.png"].ontbrekend
    assert per["b_1440.png"].soort_scherm == "" and "soort_scherm" in per["b_1440.png"].ontbrekend


def test_soort_scherm_filter_houdt_alleen_gevraagde_comps_plus_de_rest(tmp_path):
    comps = tmp_path / "comps"
    for n in ("dash", "docs", "form", "onbekend"):
        _png(comps / f"{n}_desktop_1440.png")
    _manifest(comps, [
        {"bestand": "dash_desktop_1440.png", "bron_naam": "Dash", "klasse": "product_ui", "soort_scherm": "app/dashboard"},
        {"bestand": "docs_desktop_1440.png", "bron_naam": "Docs", "klasse": "product_ui", "soort_scherm": "docs"},
        {"bestand": "form_desktop_1440.png", "bron_naam": "Form", "klasse": "product_ui", "soort_scherm": "Formulier"},
        {"bestand": "onbekend_desktop_1440.png", "bron_naam": "Onbekend", "klasse": "product_ui"}])
    ons = tmp_path / "ours"
    _png(ons / "ons_desktop_1440.png")
    alle = blind_ab.verzamel_bronnen([comps], "comp") + blind_ab.verzamel_bronnen([ons], "ours")
    behouden, uitgesloten = blind_ab.filter_bronnen(alle, "alles", False, ["app/dashboard", "FORMULIER"])
    assert sorted(b.bron_naam for b in behouden if b.soort == "comp") == ["Dash", "Form"]
    assert any(b.soort == "ours" for b in behouden)                                # ons scherm blijft altijd
    redenen = {u["bron_naam"]: u["reden"] for u in uitgesloten}
    assert "soort_scherm=docs" in redenen["Docs"] and "soort_scherm=onbekend" in redenen["Onbekend"]
    alles, _ = blind_ab.filter_bronnen(alle, "alles")                              # zonder filter: alles
    assert len([b for b in alles if b.soort == "comp"]) == 4


def test_ronde_met_soort_scherm_filter_legt_het_filter_en_de_soort_per_beeld_vast(tmp_path):
    m = bouw_bronnen(tmp_path, mobiel=False)
    lijst = json.loads((m["comps"] / "manifest.json").read_text())
    for e, soort in zip(lijst, ("app/dashboard", "docs", "app/dashboard")):
        e["soort_scherm"] = soort
    (m["comps"] / "manifest.json").write_text(json.dumps(lijst))
    nl = json.loads((m["comps_nl"] / "manifest.json").read_text())
    for c in nl["comps"]:
        c["soort_scherm"] = "formulier"
    (m["comps_nl"] / "manifest.json").write_text(json.dumps(nl))
    assert draai(tmp_path, m, "--soort-scherm", "app/dashboard") == 0
    s = lees_sleutel(tmp_path)
    assert s["meetlat"]["soort_scherm_filter"] == ["app/dashboard"]
    comps = [i for i in _items(s) if i["soort"] == "comp"]
    assert {i["bron_naam"] for i in comps} == {"Internationaal 0", "Internationaal 2"}
    assert {i["soort_scherm"] for i in comps} == {"app/dashboard"}
    assert sum(1 for u in s["uitgesloten"] if "soort_scherm=docs" in u["reden"]) == 1
    assert sum(1 for u in s["uitgesloten"] if "soort_scherm=formulier" in u["reden"]) == 2
