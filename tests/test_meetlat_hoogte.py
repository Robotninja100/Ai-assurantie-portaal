"""
Hoogte is geen vingerafdruk (audit-punt 3) en de mobiele ronde toont meer dan de bovenkant
(audit-punt 4): eigenschap van de ronde, getoetst met synthetische pagina's.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from test_meetlat_hulp import (BREEDTE_DESKTOP, BREEDTE_MOBIEL, blind_ab, bouw_bronnen, draai,
                               lees_sleutel, maak_pagina)


def _pagina(pad, breedte, hoogte, kleur=(240, 240, 240), balken=()):
    im = Image.new("RGB", (breedte, hoogte), kleur)
    d = ImageDraw.Draw(im)
    for y0, y1 in balken:
        d.rectangle([0, y0, breedte, y1], fill=(0, 0, 0))
    im.save(pad)


# ---------------------------------------------------------------- positiebepaling
@pytest.mark.parametrize("hoogte", [1800, 1875, 2500, 9000, 33333])
def test_lange_pagina_secties_liggen_boven_midden_onder_en_overlappen_nooit(hoogte):
    spec = blind_ab.SectieSpec(aantal=3, hoogte=600)
    ys = blind_ab.sectie_posities(hoogte, spec)
    assert ys[0] == 0 and ys[-1] == hoogte - spec.hoogte            # bovenaan en onderaan
    assert abs(ys[1] - (hoogte - spec.hoogte) / 2) <= 1              # ertussen in het midden
    assert all(b - a >= spec.hoogte for a, b in zip(ys, ys[1:]))    # geen herhaalde inhoud


def test_sectiepositie_is_continu_op_de_overgang_van_korte_naar_lange_pagina():
    spec = blind_ab.SectieSpec(aantal=3, hoogte=600)
    assert blind_ab.sectie_posities(1800, spec) == [0, 600, 1200]           # precies drie secties
    assert blind_ab.sectie_posities(1799, spec) == [0, 600, 1200]           # korter: aansluitend vanaf boven
    assert blind_ab.sectie_posities(1802, spec) == [0, 601, 1202]           # langer: uit elkaar
    assert blind_ab.sectie_posities(50, spec) == [0, 600, 1200]
    assert blind_ab.sectie_posities(5000, blind_ab.SectieSpec(aantal=1, hoogte=600)) == [0]


# ---------------------------------------------------------------- afmetingen
@pytest.mark.parametrize("hoogte", [1, 60, 187, 188, 300, 563, 564, 565, 2000, 9000])
def test_elk_beeld_heeft_dezelfde_afmetingen_wat_de_paginahoogte_ook_is(tmp_path, hoogte):
    spec = blind_ab.SectieSpec(aantal=3, hoogte=188, scheiding=40)
    p = tmp_path / "p.png"
    _pagina(p, 300, hoogte)
    img, log = blind_ab.neutraliseer(p, "desktop", 300, 3.0, "zacht", None, True, 0.5, secties=spec)
    assert img.size == (300, spec.totale_hoogte) == (300, 644)
    assert log.secties["paginahoogte_px"] == hoogte
    assert log.secties["korte_pagina"] == (hoogte < 3 * 188)


def test_de_oude_hoogtekap_maakte_van_de_hoogte_een_vingerafdruk_en_de_toets_vangt_dat(tmp_path):
    """Tegenproef: zonder secties (oud gedrag) hangt de hoogte van de bron af, en
    controleer_hoogte_eigenschap slaat daarop aan. Met secties: nooit."""
    oud, nieuw = [], []
    spec = blind_ab.SectieSpec(aantal=3, hoogte=188, scheiding=40)
    for i, h in enumerate((400, 900, 1300, 2500)):
        p = tmp_path / f"p{i}.png"
        _pagina(p, 300, h)
        a, _ = blind_ab.neutraliseer(p, "desktop", 300, 3.0, "zacht", None, False, 0.5)
        b, _ = blind_ab.neutraliseer(p, "desktop", 300, 3.0, "zacht", None, False, 0.5, secties=spec)
        oud.append(a.size)
        nieuw.append(b.size)
    assert len(set(oud)) > 1
    assert blind_ab.controleer_hoogte_eigenschap({"desktop": oud})
    assert len(set(nieuw)) == 1
    assert blind_ab.controleer_hoogte_eigenschap({"desktop": nieuw}) == []


def test_controleer_hoogte_eigenschap_telt_per_viewport():
    assert blind_ab.controleer_hoogte_eigenschap({"desktop": [(300, 5), (300, 5)], "mobile": [(200, 9)]}) == []
    fouten = blind_ab.controleer_hoogte_eigenschap({"desktop": [(300, 5), (300, 6), (300, 7)],
                                                    "mobile": [(200, 9), (200, 9)]})
    assert len(fouten) == 1 and fouten[0].startswith("desktop: 3 unieke hoogtes")
    assert blind_ab.controleer_hoogte_eigenschap({"desktop": [(300, 5), (310, 5)]})    # ook breedte


# ---------------------------------------------------------------- wat er in beeld staat
def test_korte_pagina_toont_elke_rij_precies_een_keer_en_de_rest_is_opvulling():
    """Geen herhaalde inhoud (overlap) bij een pagina die korter is dan de secties."""
    breedte, hoogte = 40, 500
    rijen = np.zeros((hoogte, breedte, 3), dtype=np.uint8)
    for y in range(hoogte):
        rijen[y, :, 0], rijen[y, :, 1], rijen[y, :, 2] = y % 256, y // 256, 7
    pagina = Image.fromarray(rijen, "RGB")
    spec = blind_ab.SectieSpec(aantal=3, hoogte=200, scheiding=10)
    doek, meta = blind_ab.snij_secties(pagina, spec)
    assert doek.size == (40, spec.totale_hoogte) and meta["korte_pagina"] and meta["opvulling_px"] == 100
    gaten = {y for a, b in meta["scheidingsrijen"] for y in range(a, b)}
    a = np.asarray(doek)
    echte = [tuple(a[y, 0]) for y in range(doek.height) if y not in gaten and y < meta["inhoud_einde_y"]]
    assert len(echte) == hoogte and len(set(echte)) == hoogte
    # de opvulling heeft de achtergrondkleur van de pagina, niet een herhaling van de inhoud
    pad_rij = tuple(a[doek.height - 1, 0])
    assert pad_rij == tuple(meta["achtergrond_rgb"])


def test_lange_pagina_toont_boven_midden_en_onder(tmp_path):
    spec = blind_ab.SectieSpec(aantal=3, hoogte=200, scheiding=20)
    p = tmp_path / "lang.png"
    _pagina(p, 300, 3000, balken=[(10, 90), (1450, 1550), (2900, 2990)])
    img, _ = blind_ab.neutraliseer(p, "desktop", 300, 3.0, "uit", None, False, 0.5, secties=spec)
    a = np.asarray(img)
    zichtbaar = [bool((a[i * 220:i * 220 + 200] < 60).any()) for i in range(3)]
    assert zichtbaar == [True, True, True]
    # en de balken tussen de secties zijn effen en identiek van kleur
    for i in range(2):
        assert set(np.unique(a[i * 220 + 200:i * 220 + 220])) == {spec.grijs}


def test_mobiele_ronde_toont_meer_dan_de_bovenkant_de_oude_kap_deed_dat_niet(tmp_path):
    """Audit-punt 4: de oude hoogtekap gooide 90-94% van de mobiele pagina weg."""
    breedte = BREEDTE_MOBIEL
    p = tmp_path / "mobiel.png"
    _pagina(p, breedte, 6000, balken=[(100, 160), (3000, 3060), (5900, 5960)])
    spec = blind_ab.standaard_sectiespec("mobile", breedte)
    nieuw, _ = blind_ab.neutraliseer(p, "mobile", breedte, 3.0, "uit", None, False, 0.5, secties=spec)
    oud, _ = blind_ab.neutraliseer(p, "mobile", breedte, 3.0, "uit", None, False, 0.5)
    stap = spec.hoogte + spec.scheiding
    a = np.asarray(nieuw)
    assert [bool((a[i * stap:i * stap + spec.hoogte] < 60).any()) for i in range(3)] == [True, True, True]
    # oud: 3 x de breedte = 600 px van de 6000: alleen de bovenste balk overleeft
    assert oud.height == 3 * breedte
    b = np.asarray(oud)
    assert (b < 60).any() and not (b[170:] < 60).any()                            # niets onder de eerste balk


def test_footermasker_volgt_het_einde_van_een_korte_pagina(tmp_path):
    spec = blind_ab.SectieSpec(aantal=3, hoogte=188, scheiding=40)
    kort, lang = tmp_path / "kort.png", tmp_path / "lang.png"
    _pagina(kort, 300, 300)
    _pagina(lang, 300, 5000)
    _i, log_kort = blind_ab.neutraliseer(kort, "desktop", 300, 3.0, "uit", None, True, 0.5, secties=spec)
    _i, log_lang = blind_ab.neutraliseer(lang, "desktop", 300, 3.0, "uit", None, True, 0.5, secties=spec)
    f_kort = next(r for r in log_kort.gemaskeerde_regios if r["naam"] == "footer-links")["kader"]
    f_lang = next(r for r in log_lang.gemaskeerde_regios if r["naam"] == "footer-links")["kader"]
    assert f_kort[3] == log_kort.secties["inhoud_einde_y"] < spec.totale_hoogte     # eindigt waar de pagina eindigt
    assert f_lang[3] == spec.totale_hoogte                                          # lange pagina: onderaan


# ---------------------------------------------------------------- de hele ronde
def test_hele_ronde_heeft_per_viewport_een_unieke_hoogte_bij_zeer_verschillende_bronnen(tmp_path):
    m = bouw_bronnen(tmp_path, comp_hoogtes=(330, 1500, 9000), comps_nl_hoogtes=(700, 4100))
    assert draai(tmp_path, m) == 0
    s = lees_sleutel(tmp_path)
    for vp, breedte in (("desktop", BREEDTE_DESKTOP), ("mobile", BREEDTE_MOBIEL)):
        maten = {Image.open(p).size for p in (tmp_path / "ab" / "r" / vp).glob("*.png")}
        assert len(maten) == 1, f"{vp}: {maten}"
        assert next(iter(maten))[0] == breedte
        assert s["hoogte_eigenschap"][vp]["unieke_hoogtes"] == 1
    # de bronnen zelf waren wel verschillend hoog (anders bewijst deze test niets)
    hoogtes = {Image.open(p).height for p in m["comps"].glob("*_desktop_*.png")}
    assert len(hoogtes) == 3


def test_secties_en_hoogte_zijn_instelbaar(tmp_path):
    m = bouw_bronnen(tmp_path, mobiel=False)
    assert draai(tmp_path, m, "--secties", "2", "--sectie-hoogte", "150", "--scheiding", "10") == 0
    s = lees_sleutel(tmp_path)
    assert s["viewports"]["desktop"]["hoogte_px"] == 2 * 150 + 10
    assert s["viewports"]["desktop"]["secties"]["aantal"] == 2
    m2 = bouw_bronnen(tmp_path / "een", mobiel=False)
    assert draai(tmp_path / "een", m2, "--secties", "1", "--sectie-hoogte", "200") == 0
    assert lees_sleutel(tmp_path / "een")["viewports"]["desktop"]["hoogte_px"] == 200


def test_de_verouderde_max_hoogte_ratio_wordt_de_totale_hoogte_van_de_secties(tmp_path):
    # de vlag legt drie secties vast (geen auto): dan moeten alle pagina's hoog genoeg zijn om die te vullen
    m = bouw_bronnen(tmp_path, mobiel=False, comp_hoogtes=(1400, 2000, 3400), comps_nl_hoogtes=(1500, 2300),
                     decoys=(("zwak", 1500),))
    assert draai(tmp_path, m, "--max-hoogte-ratio", "2") == 0
    spec = lees_sleutel(tmp_path)["viewports"]["desktop"]["secties"]
    assert spec["hoogte"] * spec["aantal"] == pytest.approx(2 * BREEDTE_DESKTOP, abs=3)


# ---------------------------------------------------------------- lege ruimte is ook een vingerafdruk
class NooitLezen:
    """Een engine waarbij elke aanroep faalt: bewijst dat er geweigerd wordt VOOR het OCR-werk."""
    naam = "nooit-lezen"

    def lees_beeld(self, img, gebieden=None):
        raise AssertionError("er mag niet gelezen worden")

    def beschrijving(self):
        return {"naam": self.naam, "versie": "test"}


@pytest.mark.parametrize("kortste_bron_px,verwacht", [(1300, 3), (830, 2), (526, 1)])
def test_secties_auto_kiest_het_grootste_aantal_dat_elk_beeld_vult(tmp_path, kortste_bron_px, verwacht):
    """Bronbreedte 600 -> beeldbreedte 300 (factor 0,5); een sectie is 188 px. De kortste pagina bepaalt het aantal."""
    m = bouw_bronnen(tmp_path, mobiel=False, comp_hoogtes=(kortste_bron_px, 2500, 3400),
                     comps_nl_hoogtes=(1400, 2300), decoys=(("zwak", 1500),))
    assert draai(tmp_path, m) == 0
    s = lees_sleutel(tmp_path)
    keuze = s["secties_keuze"]["desktop"]
    assert keuze["modus"] == "auto" and keuze["gekozen"] == verwacht
    spec = s["viewports"]["desktop"]["secties"]
    assert spec["aantal"] == verwacht
    assert s["viewports"]["desktop"]["hoogte_px"] == verwacht * spec["hoogte"] + (verwacht - 1) * spec["scheiding"]
    assert keuze["kortste_pagina_secties"] == pytest.approx(min(kortste_bron_px * 0.5, 550) / 188, abs=0.03)
    for it in s["viewports"]["desktop"]["items"]:           # niemand is (noemenswaardig) opgevuld
        assert it["neutralisatie"]["secties"]["opvulling_px"] <= 0.15 * spec["hoogte"] + 1


def test_auto_meldt_waarom_er_minder_secties_zijn_gekozen(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, mobiel=False, comp_hoogtes=(526, 2500, 3400), comps_nl_hoogtes=(1400, 2300),
                     decoys=(("zwak", 1500),))
    assert draai(tmp_path, m) == 0
    uit = capsys.readouterr().out
    assert "Secties   : desktop 1 (auto)" in uit
    assert "WAARSCHUWING: desktop: --secties auto koos 1 van de maximaal 3 secties" in uit
    s = lees_sleutel(tmp_path)
    assert any("--secties auto koos 1" in w for w in s["waarschuwingen"])
    assert "Internationaal" in s["secties_keuze"]["desktop"]["kortste_bron"]       # de operator ziet welke bron beperkt
    leesmij = (tmp_path / "ab" / "r" / "LEESMIJ.md").read_text(encoding="utf-8")
    assert "desktop (300 px breed, 1 uitsnede)" in leesmij


def test_vaste_secties_met_klassegebonden_lege_ruimte_worden_geweigerd_voor_het_ocr_werk(tmp_path, capsys):
    m = bouw_bronnen(tmp_path, mobiel=False, comp_hoogtes=(1300, 2500, 3400), comps_nl_hoogtes=(1400, 2300),
                     decoys=(("zwak", 700),))                   # de decoy is 1,9 sectie hoog, de rest minstens 2,9
    code = draai(tmp_path, m, "--secties", "3", engines=[NooitLezen()])
    uit = capsys.readouterr().out
    assert code == 5 and "lege ruimte" in uit and "--secties auto" in uit
    assert not (tmp_path / "ab" / "r").exists() and not list((tmp_path / "ab").glob(".bouw_*"))
    # tegenproef: precies dezelfde bronnen met de standaard (auto) worden wel gebouwd
    assert draai(tmp_path, m, ronde="r2") == 0
    assert lees_sleutel(tmp_path, "r2")["secties_keuze"]["desktop"]["gekozen"] == 2


def test_lege_ruimte_die_bij_alle_klassen_gelijk_is_mag_wel(tmp_path):
    m = bouw_bronnen(tmp_path, mobiel=False, anker=False, comp_hoogtes=(700, 700, 700), comps_nl_hoogtes=(700, 700),
                     decoys=(("zwak", 700),))
    maak_pagina(m["ours"] / "portaal-desktop-1440x900.png", 600, 700, zaad=91)      # ook ons scherm is even kort
    assert draai(tmp_path, m, "--secties", "3") == 0
    vulling = lees_sleutel(tmp_path)["vulling_per_klasse"]["desktop"]
    assert {k: v["gem_leeg_aandeel"] for k, v in vulling.items()} == {"comp": 0.379, "ours": 0.379, "decoy": 0.379}


def test_vullingsprofiel_weigert_een_klassegebonden_verschil_en_laat_gelijke_lege_ruimte_toe():
    stats, fouten = blind_ab.vullingsprofiel({"desktop": {"comp": [0.0, 0.05], "ours": [0.6], "decoy": [0.5, 0.7]}})
    assert stats["desktop"]["ours"]["gem_leeg_aandeel"] == 0.6 and len(fouten) == 1 and "eigen schermen" in fouten[0]
    assert blind_ab.vullingsprofiel({"desktop": {"comp": [0.5, 0.6], "ours": [0.55]}})[1] == []     # overal even leeg
    assert blind_ab.vullingsprofiel({"desktop": {"comp": [0.9]}})[1] == []                         # een klasse: niets te vergelijken
    assert blind_ab.vullingsprofiel({})[1] == []


def test_inhoudshoogte_volgt_het_schalen_naar_de_uitvoerbreedte(tmp_path):
    p = tmp_path / "p.png"
    _pagina(p, 600, 1500)
    assert blind_ab.inhoudshoogte_px(p, 300) == 750


def test_footermasker_alleen_als_de_voet_van_de_pagina_in_beeld_is(tmp_path):
    lang, kort = tmp_path / "lang.png", tmp_path / "kort.png"
    _pagina(lang, 300, 3000)
    _pagina(kort, 300, 150)
    een = blind_ab.SectieSpec(aantal=1, hoogte=188, scheiding=40)
    drie = blind_ab.SectieSpec(aantal=3, hoogte=188, scheiding=40)

    def namen(pad, spec):
        _i, log = blind_ab.neutraliseer(pad, "desktop", 300, 3.0, "uit", None, True, 0.5, secties=spec)
        return {r["naam"] for r in log.gemaskeerde_regios}

    assert "footer-links" not in namen(lang, een)        # alleen het bovenste scherm: de voet ligt buiten beeld
    assert "footer-links" in namen(lang, drie)           # de onderste uitsnede toont de voet
    assert "footer-links" in namen(kort, een)            # korte pagina: de voet is het einde van de inhoud


def test_secties_accepteert_auto_of_een_positief_getal():
    p = blind_ab._bouw_parser()
    assert p.parse_args([]).secties == "auto" and p.parse_args(["--secties", "2"]).secties == 2
    assert p.parse_args(["--secties", "AUTO"]).secties == "auto"
    for fout in ("0", "-1", "drie"):
        with pytest.raises(SystemExit):
            p.parse_args(["--secties", fout])
