"""
Exitcodes en weigeringen van scripts/blind_ab.py (audit-punt 1 en de lekcontrole-weigering).

Elke controle hier heeft een tegenproef die aantoont dat hij kan falen: het harnas moet
weigeren (2, 3, 4, 5) en mag dan GEEN (halve) ronde achterlaten.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from test_meetlat_hulp import (BREEDTE_DESKTOP, NietsZienEngine, ZietAltijdEenLekEngine,
                               ZietTekstAlsErContrastIsEngine, blind_ab, bouw_bronnen, cli_args,
                               draai, lees_sleutel, maak_pagina)


def _geen_ronde(root: Path, ronde: str = "r") -> bool:
    ab = root / "ab"
    return (not (ab / ronde).exists() and not list(ab.glob(".bouw_*"))) if ab.exists() else True


# ---------------------------------------------------------------- A. exitcode 2 zonder eigen schermen
def test_exit2_als_de_map_met_eigen_schermen_ontbreekt(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, ours=False)
    shutil.rmtree(m["ours"])                                  # de map bestaat niet eens
    assert draai(tmp_path, m) == 2
    uit = capsys.readouterr().out
    assert "exitcode 2" in uit and "GEEN ENKEL eigen scherm" in uit
    assert "map ontbreekt" in uit
    assert _geen_ronde(tmp_path)
    assert not (tmp_path / "ab" / "_sleutel.json").exists()


def test_exit2_als_de_map_met_eigen_schermen_leeg_is(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, ours=False)                    # map bestaat, is leeg
    assert m["ours"].exists() and not list(m["ours"].iterdir())
    assert draai(tmp_path, m) == 2
    assert "exitcode 2" in capsys.readouterr().out
    assert _geen_ronde(tmp_path)


def test_exit2_ook_als_alleen_een_van_de_viewports_geen_eigen_scherm_heeft(tmp_path, capsys):
    """Een mobiele ronde zonder eigen mobiel scherm meet niets over ons; het oude harnas schreef
    haar toch (audit: 'complete, nette, geblindeerde meetronde die niets meet')."""
    m = bouw_bronnen(tmp_path, ours="desktop")
    assert draai(tmp_path, m) == 2
    uit = capsys.readouterr().out
    assert "viewport mobile" in uit
    assert _geen_ronde(tmp_path)
    # tegenproef: vraag alleen om desktop, dan is er niets mis
    assert draai(tmp_path, m, "--viewports", "desktop") == 0


def test_exit2_als_eigen_scherm_door_geladen_ok_false_wegvalt(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, mobiel=False)
    (m["ours"] / "manifest.json").write_text(json.dumps(
        [{"bestand": "portaal-desktop-1440x900.png", "klasse": "ours", "geladen_ok": False}]),
        encoding="utf-8")
    assert draai(tmp_path, m) == 2
    assert "geen bruikbaar beeld" in capsys.readouterr().out
    assert _geen_ronde(tmp_path)


def test_exit2_als_het_eigen_scherm_geen_herkenbare_viewport_in_de_naam_heeft(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, ours=False, mobiel=False)
    Image.new("RGB", (600, 900), (230, 230, 230)).save(m["ours"] / "dashboard.png")
    assert draai(tmp_path, m) == 2
    uit = capsys.readouterr().out
    assert "geen herkenbare viewport" in uit and "geef het 'desktop' of 'mobile'" in uit


def test_exit2_zonder_enig_bronbeeld(tmp_path, capsys):
    leeg = {n: tmp_path / n for n in ("comps", "comps_nl", "ours", "decoy", "anker")}
    for p in leeg.values():
        p.mkdir()
    assert draai(tmp_path, leeg) == 2
    assert "geen enkel bronbeeld" in capsys.readouterr().out


def test_exit2_bij_een_rondenaam_die_de_bron_verraadt(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, mobiel=False)
    assert draai(tmp_path, m, ronde="stripe_test") == 2
    assert "verraadt de bron" in capsys.readouterr().out
    assert _geen_ronde(tmp_path, "stripe_test")


# ---------------------------------------------------------------- A. bewuste testronde
def test_testronde_zonder_eigen_schermen_is_gemarkeerd_in_sleutel_en_leesmij(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, ours=False)
    assert draai(tmp_path, m, "--zonder-eigen-schermen") == 0
    sleutel = lees_sleutel(tmp_path)
    assert sleutel["meetlat"]["status"] == "NIET-BRUIKBAAR-VOOR-OORDEEL"
    assert sleutel["meetlat"]["bruikbaar_voor_oordeel"] is False
    assert sleutel["meetlat"]["zonder_eigen_schermen_vlag"] is True
    assert sleutel["meetlat"]["aantal_eigen"] == 0
    assert all(not i["is_ons"] for d in sleutel["viewports"].values() for i in d["items"])
    leesmij = (tmp_path / "ab" / "r" / "LEESMIJ.md").read_text(encoding="utf-8")
    assert "NIET-BRUIKBAAR-VOOR-OORDEEL" in leesmij
    assert "NIET-BRUIKBAAR-VOOR-OORDEEL" in capsys.readouterr().out


def test_leesmij_van_de_testronde_verklapt_niets(tmp_path):
    """De LEESMIJ gaat naar de beoordelaar. Op de statusregel na moet ze identiek zijn aan die van een
    echte ronde, en de statusregel zelf mag niets over de samenstelling zeggen."""
    test = tmp_path / "test"
    echt = tmp_path / "echt"
    m1 = bouw_bronnen(test, ours=False)
    m2 = bouw_bronnen(echt)
    assert draai(test, m1, "--zonder-eigen-schermen", "--viewports", "desktop") == 0
    assert draai(echt, m2, "--viewports", "desktop") == 0
    t = (test / "ab" / "r" / "LEESMIJ.md").read_text(encoding="utf-8")
    e = (echt / "ab" / "r" / "LEESMIJ.md").read_text(encoding="utf-8")
    assert "Status:" in t and "Status:" not in e
    zonder_status = "\n".join(r for r in t.splitlines() if not r.startswith("Status:"))
    # de lege regel die de statusregel omringt mag verschillen; de inhoud niet
    assert zonder_status.split() == e.split()
    statusregel = next(r for r in t.splitlines() if r.startswith("Status:")).lower()
    for woord in ("eigen", "ours", "decoy", "anker", "comp", "domein", "geen "):
        assert woord not in statusregel


def test_vlag_zonder_eigen_schermen_verlaagt_een_echte_ronde_niet(tmp_path):
    m = bouw_bronnen(tmp_path)
    assert draai(tmp_path, m, "--zonder-eigen-schermen") == 0
    assert lees_sleutel(tmp_path)["meetlat"]["status"] == "BRUIKBAAR"
    leesmij = (tmp_path / "ab" / "r" / "LEESMIJ.md").read_text(encoding="utf-8")
    assert "NIET-BRUIKBAAR" not in leesmij


# ---------------------------------------------------------------- B. exitcode 3: lek dat blijft
def test_exit3_als_een_verboden_woord_na_automask_leesbaar_blijft(tmp_path, capsys):
    m = bouw_bronnen(tmp_path)
    assert draai(tmp_path, m, engines=[ZietAltijdEenLekEngine()]) == 3
    uit = capsys.readouterr().out
    assert "exitcode 3" in uit and "IDENTITEITSLEK" in uit
    assert "Interpolis" in uit                                  # welk woord
    assert "blijft leesbaar na automatisch maskeren" in uit
    assert "beeld A" in uit or "beeld B" in uit                 # welk beeld
    assert _geen_ronde(tmp_path)                                # en er staat niets
    assert not (tmp_path / "ab" / "_sleutel.json").exists()


def test_exit3_noemt_van_elk_lekkend_beeld_de_bron(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, mobiel=False)
    assert draai(tmp_path, m, engines=[ZietAltijdEenLekEngine()]) == 3
    uit = capsys.readouterr().out
    assert "portaal-desktop-1440x900.png" in uit               # het lekkende eigen scherm staat erbij
    assert uit.count("verboden woord") >= 5                    # elk beeld apart, niet alleen het eerste


def test_een_weigering_laat_een_bestaande_ronde_ongemoeid(tmp_path):
    m = bouw_bronnen(tmp_path, mobiel=False)
    assert draai(tmp_path, m) == 0
    voor = {p.name: p.read_bytes() for p in (tmp_path / "ab" / "r" / "desktop").iterdir()}
    assert draai(tmp_path, m, engines=[ZietAltijdEenLekEngine()]) == 3
    na = {p.name: p.read_bytes() for p in (tmp_path / "ab" / "r" / "desktop").iterdir()}
    assert voor == na


def test_automask_verhelpt_een_lek_en_de_definitieve_beelden_zijn_schoon(tmp_path):
    """Happy path van B: lek gevonden -> kader gemaskeerd -> opnieuw gelezen -> schoon -> ronde geschreven.
    Tegenproef: hetzelfde bronbeeld zonder maskeren wordt WEL gelezen (de engine kan dus falen)."""
    m = bouw_bronnen(tmp_path, patroon=True, mobiel=False)
    spec = blind_ab.standaard_sectiespec("desktop", BREEDTE_DESKTOP)
    onbeschermd, _ = blind_ab.neutraliseer(m["comps"] / "intl0_desktop_1440.png", "desktop", BREEDTE_DESKTOP,
                                           3.0, "zacht", None, True, 0.5, secties=spec)
    engine = ZietTekstAlsErContrastIsEngine()
    assert engine.lees_beeld(onbeschermd), "het testbeeld bevat geen leesbaar patroon; de proef zou niets bewijzen"

    assert draai(tmp_path, m, engines=[ZietTekstAlsErContrastIsEngine()]) == 0
    sleutel = lees_sleutel(tmp_path)
    ocr = sleutel["ocr"]
    assert ocr["beelden_met_automask"] >= 5 and ocr["kaders_gemaskeerd"] >= 5
    assert ocr["beelden_met_lek_na_automask"] == 0
    assert "OCR-dekking" in ocr["dekking"] and "kaders gemaskeerd" in ocr["dekking"]
    for d in sleutel["viewports"].values():
        for it in d["items"]:
            if it["soort"] in ("comp", "ours"):                  # bronnen met het patroon
                assert it["ocr"]["doorgangen"] == 2 and it["ocr"]["kaders_gemaskeerd"] >= 1
                assert "interpolis" in [w.lower() for w in it["ocr"]["gemaskeerde_woorden"]]
            else:                                                # decoy en anker hebben geen patroon
                assert it["ocr"]["doorgangen"] == 1 and it["ocr"]["kaders_gemaskeerd"] == 0
    for png in sorted((tmp_path / "ab" / "r" / "desktop").glob("*.png")):
        assert ZietTekstAlsErContrastIsEngine().lees_beeld(Image.open(png)) == [], f"{png.name} lekt nog"


# ---------------------------------------------------------------- B. exitcode 4: geen (werkende) OCR
def test_exit4_zonder_ocr_engine_en_met_installatie_instructie(tmp_path, capsys, monkeypatch):
    m = bouw_bronnen(tmp_path, mobiel=False)
    monkeypatch.setattr(blind_ab.RapidOcrEngine, "beschikbaar", staticmethod(lambda: (False, "test: niet geinstalleerd")))
    monkeypatch.setattr(blind_ab.TesseractEngine, "beschikbaar", staticmethod(lambda: (False, "test: niet geinstalleerd")))
    code = blind_ab.main(cli_args(tmp_path, m))                 # geen geinjecteerde engines: de echte keuze
    uit = capsys.readouterr().out
    assert code == 4
    assert "GEEN WERKENDE OCR-ENGINE" in uit
    assert "rapidocr-onnxruntime" in uit and "tesseract-ocr" in uit   # hoe je het oplost
    assert _geen_ronde(tmp_path) and not (tmp_path / "ab" / "_sleutel.json").exists()


def test_exit4_als_de_engine_de_ijkcontrole_niet_haalt(tmp_path, capsys, monkeypatch):
    """Een engine die draait maar niets leest (kapotte installatie, ontbrekende taaldata) mag geen
    vals gevoel van veiligheid geven: de ijkcontrole leest bekende merkwoorden en keurt hem af."""
    m = bouw_bronnen(tmp_path, mobiel=False)
    monkeypatch.setattr(blind_ab, "beschikbare_ocr_engines", lambda voorkeur="auto": ([NietsZienEngine()], []))
    code = blind_ab.main(cli_args(tmp_path, m))
    uit = capsys.readouterr().out
    assert code == 4
    assert "ijkcontrole" in uit and "niets-zien" in uit
    assert _geen_ronde(tmp_path)


def test_er_is_geen_vlag_om_ocr_over_te_slaan():
    parser = blind_ab._bouw_parser()
    opties = {o for a in parser._actions for o in a.option_strings}
    assert "--ocr-engine" in opties
    for verdacht in ("--geen-ocr", "--zonder-ocr", "--skip-ocr", "--no-ocr", "--ocr-uit"):
        assert verdacht not in opties
        with pytest.raises(SystemExit):
            parser.parse_args([verdacht])
    keuzes = next(a for a in parser._actions if "--ocr-engine" in a.option_strings).choices
    assert set(keuzes) == {"auto", "rapidocr", "tesseract", "beide"}


def test_beide_engines_verplicht_geeft_4_als_er_een_ontbreekt(monkeypatch):
    monkeypatch.setattr(blind_ab.TesseractEngine, "beschikbaar", staticmethod(lambda: (False, "test")))
    with pytest.raises(blind_ab.OcrNietBeschikbaar):
        blind_ab.beschikbare_ocr_engines("beide")


# ---------------------------------------------------------------- C. exitcode 5: hoogte = vingerafdruk
def test_exit5_als_de_hoogte_toch_een_vingerafdruk_is(tmp_path, capsys, monkeypatch):
    m = bouw_bronnen(tmp_path, mobiel=False)
    echte = blind_ab.neutraliseer
    teller = {"n": 0}

    def kapot(*a, **k):
        img, log = echte(*a, **k)
        teller["n"] += 1
        return img.crop((0, 0, img.width, img.height - 3 * teller["n"])), log     # elke hoogte anders

    monkeypatch.setattr(blind_ab, "neutraliseer", kapot)
    assert draai(tmp_path, m) == 5
    uit = capsys.readouterr().out
    assert "exitcode 5" in uit and "unieke hoogtes" in uit
    assert _geen_ronde(tmp_path)


# ---------------------------------------------------------------- 1. een bron die uitvalt is geen stille uitval
def test_exit1_als_een_bronbeeld_zich_niet_laat_verwerken(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, mobiel=False)
    (m["comps"] / "kapot_desktop_1440.png").write_bytes(b"dit is geen png")
    assert draai(tmp_path, m) == 1
    uit = capsys.readouterr().out
    assert "kapot_desktop_1440.png" in uit and "neutralisatie mislukt" in uit
    assert _geen_ronde(tmp_path)


# ---------------------------------------------------------------- hygiene van een geslaagde ronde
def test_geslaagde_ronde_lekt_niets_via_bestanden(tmp_path):
    m = bouw_bronnen(tmp_path)
    assert draai(tmp_path, m, "--domein", "nl_financieel") == 0
    ronde = tmp_path / "ab" / "r"
    for vp in ("desktop", "mobile"):
        pngs = sorted((ronde / vp).glob("*.png"))
        assert len(pngs) == 5
        assert len({p.stat().st_size for p in pngs}) == 1                  # gelijke bytegrootte
        assert len({p.stat().st_mtime for p in pngs}) == 1 and pngs[0].stat().st_mtime == 1735689600
        for p in pngs:
            assert not blind_ab.controleer_naam(p.name)
            ruw = p.read_bytes()
            for chunk in (b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME"):
                assert chunk not in ruw
            with Image.open(p) as im:
                assert im.mode == "L"
    assert not blind_ab.controleer_naam(ronde.name)
    # de rater-map bevat geen sleutel en niets anders dan beelden, csv en LEESMIJ
    toegestaan = {".png", ".csv", ".md"}
    assert {p.suffix for p in ronde.rglob("*") if p.is_file()} <= toegestaan


def test_dezelfde_seed_geeft_dezelfde_labels_en_een_andere_seed_een_andere_volgorde(tmp_path):
    def mapping(uit, seed):
        m = bouw_bronnen(tmp_path / f"b_{uit}")
        args = cli_args(tmp_path / f"b_{uit}", m, uit=uit)
        args[args.index("--seed") + 1] = str(seed)
        assert blind_ab.main(args, ocr_engines=[NietsZienEngine()]) == 0
        s = lees_sleutel(tmp_path / f"b_{uit}", uit=uit)
        return {vp: [(i["label"], i["bron_naam"]) for i in d["items"]] for vp, d in s["viewports"].items()}

    a1, a2, b = mapping("x1", 5), mapping("x2", 5), mapping("x3", 6)
    assert a1 == a2
    assert a1 != b


def test_sleutel_legt_meetlat_eigenschappen_vast(tmp_path):
    m = bouw_bronnen(tmp_path)
    assert draai(tmp_path, m, "--domein", "nl_financieel") == 0
    s = lees_sleutel(tmp_path)
    assert s["script_versie"] == blind_ab.SCRIPT_VERSIE
    assert s["meetlat"]["domein_filter"] == "nl_financieel"
    assert s["meetlat"]["heeft_anker"] is True and s["meetlat"]["aantal_ankers"] == 2
    assert s["meetlat"]["aantal_decoys"] == 2 and s["meetlat"]["aantal_eigen"] == 2
    for vp, h in s["hoogte_eigenschap"].items():
        assert h["unieke_hoogtes"] == 1 and h["unieke_breedtes"] == 1
        assert h["hoogte_px"] == s["viewports"][vp]["hoogte_px"]
    assert s["ocr"]["beelden_gecontroleerd"] == 10
    assert "OCR-dekking: gecontroleerd op" in s["ocr"]["dekking"]
    assert s["ocr"]["engines"][0]["naam"] == "niets-zien"
    ankers = [i for d in s["viewports"].values() for i in d["items"] if i["is_anker"]]
    assert len(ankers) == 2 and all(i["soort"] == "anker" and not i["is_ons"] and not i["is_decoy"] for i in ankers)
    decoys = [i for d in s["viewports"].values() for i in d["items"] if i["is_decoy"]]
    assert {i["kwaliteit"] for i in decoys} == {"zwak"}


# ---------------------------------------------------------------- een masker is zelf een signaal
def test_maskerprofiel_waarschuwt_alleen_bij_een_groot_verschil_tussen_klassen():
    stats, w = blind_ab.maskerprofiel({"comp": [3, 4, 5], "ours": [0, 0], "decoy": [0]})
    assert stats["comp"]["gemiddeld_kaders"] == 4.0 and stats["ours"]["beelden_met_masker"] == 0
    assert w and "comps 4,0" in w and "eigen schermen 0,0" in w
    assert blind_ab.maskerprofiel({"comp": [1, 0, 1], "ours": [0, 1]})[1] is None       # klein verschil
    assert blind_ab.maskerprofiel({"comp": [5, 6]})[1] is None                          # een klasse: niets te vergelijken
    assert blind_ab.maskerprofiel({})[1] is None


def test_sleutel_legt_de_maskers_per_klasse_vast_en_waarschuwt_als_alleen_de_comps_gemaskeerd_zijn(
        tmp_path, capsys, monkeypatch):
    m = bouw_bronnen(tmp_path, patroon=True, mobiel=False)
    maak_pagina(m["ours"] / "portaal-desktop-1440x900.png", 600, 1100, zaad=91, patroon=False)   # ons scherm: schoon
    monkeypatch.setattr(blind_ab, "MASKER_VERSCHIL", 0.5)
    assert draai(tmp_path, m, engines=[ZietTekstAlsErContrastIsEngine()]) == 0
    s = lees_sleutel(tmp_path)
    per = s["ocr"]["maskers_per_klasse"]
    assert per["comp"]["gemiddeld_kaders"] >= 1 and per["comp"]["beelden_met_masker"] == per["comp"]["beelden"]
    assert per["ours"]["gemiddeld_kaders"] == 0 and per["decoy"]["beelden_met_masker"] == 0
    assert any("gemaskeerde kaders per beeld verschillen per klasse" in w for w in s["waarschuwingen"])
    assert "WAARSCHUWING: gemaskeerde kaders per beeld verschillen" in capsys.readouterr().out


def test_geen_maskerwaarschuwing_als_comps_en_eigen_schermen_even_veel_maskers_hebben(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, patroon=True, mobiel=False)                # comps en ours hebben beide het patroon
    assert draai(tmp_path, m, engines=[ZietTekstAlsErContrastIsEngine()]) == 0
    s = lees_sleutel(tmp_path)
    assert s["ocr"]["maskers_per_klasse"]["comp"]["gemiddeld_kaders"] == s["ocr"]["maskers_per_klasse"]["ours"]["gemiddeld_kaders"]
    assert not any("gemaskeerde kaders per beeld" in w for w in s["waarschuwingen"])
