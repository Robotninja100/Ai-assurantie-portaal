"""
scripts/blind_ab_rapport.py: het rapport moet een ronde ONGELDIG kunnen noemen (en dan geen winst
melden). Elke ongeldigheidsregel heeft een test waarin de ronde precies daarom ongeldig is, en de
gezonde ronde is de tegenproef die aantoont dat de regels niet altijd afslaan.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_meetlat_hulp import blind_ab_rapport as rapport, bouw_bronnen, draai, lees_sleutel

KOP = ["label", "hierarchie_1_5", "typografie_1_5", "ritme_witruimte_1_5", "consistentie_1_5",
       "totaalindruk_1_5", "opmerking"]


def item(label, naam, soort, kwaliteit="", soort_scherm="", vorm="lijst"):
    return {"label": label, "bron_naam": naam, "soort": soort, "kwaliteit": kwaliteit,
            "soort_scherm": soort_scherm, "manifest_vorm": vorm,
            "is_decoy": soort == "decoy", "is_ons": soort == "ours", "is_anker": soort == "anker"}


# ons scherm en vijf comps zijn werkschermen; Foxtrot is documentatie en hoort niet in de vergelijking
SCHERM = {"Alfa": "app/dashboard", "Bravo": "app/dashboard", "Charlie": "app/dashboard", "Delta": "app/dashboard",
          "Echo": "formulier", "Foxtrot": "docs"}


def basis_items():
    items = [item("A", "Ankerbron", "anker", soort_scherm="app/dashboard", vorm="object.bestanden[bestandsnaam-map]"),
             item("B", "Ons scherm", "ours", soort_scherm="app/dashboard", vorm="geen manifest")]
    for k, naam in enumerate(("Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot")):
        items.append(item(chr(ord("C") + k), naam, "comp", soort_scherm=SCHERM[naam],
                          vorm="lijst" if k % 2 == 0 else "object.comps[lijst].bestanden[viewportmap]"))
    items += [item("I", "Decoy zeer zwak", "decoy", "zeer_zwak", "app/dashboard", "object.bestanden[bestandsnaam-map]"),
              item("J", "Decoy matig", "decoy", "matig", "app/dashboard", "object.bestanden[bestandsnaam-map]")]
    return items


def maak_sleutel(items=None, viewports=("desktop",), meetlat=None, **extra):
    m = {"bruikbaar_voor_oordeel": True, "status": "BRUIKBAAR", "domein_filter": "nl_financieel"}
    m.update(meetlat or {})
    s = {"script_versie": "2.0.0", "meetlat": m,
         "hoogte_eigenschap": {vp: {"unieke_hoogtes": 1} for vp in viewports},
         "viewports": {vp: {"items": items if items is not None else basis_items()} for vp in viewports}}
    s.update(extra)
    return s


def rij(v):
    return (v,) * 5


GOED = {"A": rij(5), "B": rij(4), "C": (4, 4, 3, 4, 4), "D": (3, 4, 3, 3, 3), "E": rij(4), "F": (3, 3, 3, 3, 3),
        "G": (2, 3, 3, 3, 3), "H": (3, 2, 3, 3, 3), "I": rij(1), "J": (2, 2, 2, 2, 2)}


def schrijf_csv(pad: Path, waarden, opmerkingen=None, delim=",", bom=False, extra_rijen=()):
    regels = [delim.join(KOP)]
    for l, w in waarden.items():
        cellen = [l] + ([""] * 5 if w is None else [str(x) for x in w]) + [(opmerkingen or {}).get(l, "")]
        regels.append(delim.join(cellen))
    regels += [delim.join(r) for r in extra_rijen]
    pad.write_text(("﻿" if bom else "") + "\n".join(regels) + "\n", encoding="utf-8")
    return pad


def beoordeel(tmp_path, waarden, sleutel=None, **kw):
    csv = schrijf_csv(tmp_path / "b.csv", waarden, **kw)
    return rapport.beoordeel_ronde(sleutel or maak_sleutel(), {"desktop": csv})


def controle(res, naam, vp="desktop"):
    return next(c for c in res["viewports"][vp]["controles"] if c["naam"] == naam)


def geen_winst(res):
    assert res["geldig"] is False and res["verdict"] != "GELDIG"
    assert not any(res["winst_boven_decoys"].values())
    assert all(v["conclusie"] == {} for v in res["viewports"].values())
    tekst = rapport.maak_tekst(res, "r")
    assert "Er wordt geen winst gemeld" in tekst and "eindigt BOVEN" not in tekst and "eindigt ONDER" not in tekst
    assert "Uitkomst (geldig)" not in tekst


# ---------------------------------------------------------------- de gezonde ronde (tegenproef)
def test_gezonde_ronde_is_geldig_en_meldt_de_uitkomsten(tmp_path):
    res = beoordeel(tmp_path, GOED)
    assert res["verdict"] == "GELDIG" and res["geldig"] and res["redenen_ongeldig"] == []
    c = res["viewports"]["desktop"]["conclusie"]
    assert c["boven_decoys"] is True and c["marge_op_beste_decoy"] == pytest.approx(2.0)
    assert c["ons_gemiddelde"] == pytest.approx(4.0) and c["beste_anker"]["naam"] == "Ankerbron"
    assert c["rang_onder_comps"] >= 1 and c["aantal_comps"] == 5          # Foxtrot (docs) telt niet mee
    assert res["winst_boven_decoys"] == {"desktop": True}
    for naam in ("cellen", "spreiding", "anker", "anker_boven_decoys", "bodem", "decoyvolgorde", "consistentie"):
        assert controle(res, naam)["ok"] is True, naam
    tekst = rapport.maak_tekst(res, "r")
    assert "OORDEEL: GELDIG" in tekst and "eindigt BOVEN de decoys" in tekst
    assert "de decoys staan in hun bedoelde kwaliteitsvolgorde" in tekst


def test_gemiddelden_per_bron_en_per_criterium_en_de_rangorde(tmp_path):
    res = beoordeel(tmp_path, GOED)
    bronnen = res["viewports"]["desktop"]["bronnen"]
    assert [b["naam"] for b in bronnen][0] == "Ankerbron" and bronnen[0]["gemiddelde"] == 5.0
    assert bronnen[-1]["naam"] == "Decoy zeer zwak" and bronnen[-1]["gemiddelde"] == 1.0
    alfa = next(b for b in bronnen if b["naam"] == "Alfa")
    assert alfa["per_criterium"]["ritme_witruimte_1_5"] == 3.0 and alfa["gemiddelde"] == pytest.approx(3.8)
    totaal = res["viewports"]["desktop"]["per_criterium_totaal"]
    assert set(totaal) == set(rapport.CRITERIA) and totaal["hierarchie_1_5"] == pytest.approx(3.1)
    gem = [b["gemiddelde"] for b in bronnen]
    assert gem == sorted(gem, reverse=True)


def test_meerdere_beelden_van_een_bron_worden_gemiddeld(tmp_path):
    items = basis_items() + [item("K", "Alfa", "comp", soort_scherm="app/dashboard")]
    waarden = dict(GOED, K=rij(5))
    res = beoordeel(tmp_path, waarden, sleutel=maak_sleutel(items))
    alfa = next(b for b in res["viewports"]["desktop"]["bronnen"] if b["naam"] == "Alfa")
    assert alfa["aantal_beelden"] == 2 and alfa["gemiddelde"] == pytest.approx((3.8 + 5.0) / 2)


# ---------------------------------------------------------------- ongeldig: alle scores gelijk
def test_alle_scores_gelijk_is_ongeldig_en_meldt_geen_winst(tmp_path):
    res = beoordeel(tmp_path, {l: rij(3) for l in GOED})
    assert res["verdict"] == "ONGELDIG" and controle(res, "spreiding")["ok"] is False
    assert "(bijna) gelijk" in res["redenen_ongeldig"][0] or any("(bijna) gelijk" in r for r in res["redenen_ongeldig"])
    geen_winst(res)


def test_bijna_alle_scores_gelijk_is_ook_ongeldig(tmp_path):
    waarden = {l: rij(3) for l in GOED}
    waarden["A"] = rij(5)                                            # een afwijker van tien beelden: 90% gelijk
    res = beoordeel(tmp_path, waarden)
    assert controle(res, "spreiding")["ok"] is False
    geen_winst(res)


# ---------------------------------------------------------------- ongeldig: anker niet bovenaan
def test_anker_onderaan_is_ongeldig(tmp_path):
    res = beoordeel(tmp_path, dict(GOED, A=rij(1)))
    assert controle(res, "anker")["ok"] is False and "niet bovenaan" in controle(res, "anker")["tekst"]
    geen_winst(res)


def test_anker_binnen_de_tolerantie_onder_de_top_blijft_geldig_erbuiten_niet(tmp_path):
    waarden = dict(GOED, A=(5, 5, 5, 4, 4), E=rij(5))               # anker 4,6 tegen beste comp 5,0: verschil 0,4
    assert controle(beoordeel(tmp_path, waarden), "anker")["ok"] is False
    waarden = dict(GOED, A=(5, 5, 5, 5, 4), E=(5, 5, 5, 5, 4), C=(5, 5, 5, 4, 4))       # anker 4,8, beste 4,8
    assert controle(beoordeel(tmp_path, waarden), "anker")["ok"] is True


def test_als_ons_scherm_boven_het_anker_uitkomt_is_de_ronde_ongeldig_en_wordt_dat_gezegd(tmp_path):
    res = beoordeel(tmp_path, dict(GOED, A=rij(3), B=rij(5)))
    c = controle(res, "anker")
    assert c["ok"] is False and "ONS SCHERM" in c["tekst"]
    geen_winst(res)


def test_een_anker_dat_niet_boven_alle_decoys_scoort_is_ongeldig(tmp_path):
    items = basis_items() + [item("K", "Tweede anker", "anker")]
    waarden = dict(GOED, K=rij(2), J=rij(3), A=(5, 5, 5, 5, 5))
    res = beoordeel(tmp_path, waarden, sleutel=maak_sleutel(items))
    assert controle(res, "anker_boven_decoys")["ok"] is False
    assert res["verdict"] == "ONGELDIG"


# ---------------------------------------------------------------- ongeldig: zwakste decoy niet onderaan
def test_zwakste_decoy_niet_onderaan_is_ongeldig(tmp_path):
    res = beoordeel(tmp_path, dict(GOED, G=rij(1), H=rij(1)))       # twee comps onder de zwakste decoy (1,0 -> 1,0 gelijk)
    assert controle(res, "bodem")["ok"] is True                      # gelijk aan de bodem is niet eronder
    res = beoordeel(tmp_path, dict(GOED, I=rij(3), J=rij(3), G=rij(1)))     # zwakste decoy 3,0; comp G scoort 1,0
    c = controle(res, "bodem")
    assert c["ok"] is False and "staat niet onderaan" in c["tekst"] and "Golf" not in c["tekst"]
    geen_winst(res)


def test_ons_scherm_onder_de_zwakste_decoy_is_ongeldig_met_een_duidelijke_melding(tmp_path):
    res = beoordeel(tmp_path, dict(GOED, B=rij(1), I=rij(2), J=rij(3)))
    c = controle(res, "bodem")
    assert c["ok"] is False and "ONS SCHERM" in c["tekst"] and "schaal van de beoordelaar" in c["tekst"]
    geen_winst(res)


def test_zwakste_decoy_volgens_kwaliteit_niet_de_laagst_scorende(tmp_path):
    """De bedoelde zwakste decoy (zeer_zwak) moet onderaan staan, niet zomaar een decoy."""
    res = beoordeel(tmp_path, dict(GOED, I=rij(3), J=rij(1)))        # 'matig' scoort lager dan 'zeer_zwak'
    assert controle(res, "decoyvolgorde")["ok"] is False
    geen_winst(res)


# ---------------------------------------------------------------- ongeldig: decoyvolgorde
def test_decoys_in_de_verkeerde_volgorde_zijn_ongeldig(tmp_path):
    waarden = dict(GOED, I=rij(2), J=rij(1))                         # zeer_zwak (2,0) hoger dan matig (1,0)
    res = beoordeel(tmp_path, waarden)
    c = controle(res, "decoyvolgorde")
    assert c["ok"] is False and "niet in hun bedoelde kwaliteitsvolgorde" in c["tekst"]
    geen_winst(res)


def test_kleine_afwijking_in_de_decoyvolgorde_is_ruis_en_geen_reden_tot_ongeldig(tmp_path):
    items = [i if i["soort"] != "decoy" else dict(i, kwaliteit="zwak" if i["label"] == "I" else "matig")
             for i in basis_items()]
    res = beoordeel(tmp_path, dict(GOED, I=(2, 2, 2, 2, 2), J=(2, 2, 2, 2, 1)), sleutel=maak_sleutel(items))
    assert controle(res, "decoyvolgorde")["ok"] is True


def test_zonder_decoykwaliteit_wordt_de_volgordecontrole_overgeslagen_en_dat_gemeld(tmp_path):
    items = [dict(i, kwaliteit="") for i in basis_items()]
    res = beoordeel(tmp_path, GOED, sleutel=maak_sleutel(items))
    c = controle(res, "decoyvolgorde")
    assert c["ok"] is None and "NIET gecontroleerd" in c["tekst"]
    assert res["verdict"] == "GELDIG"                                 # overslaan is geen ongeldigheid...
    assert any("geen decoykwaliteit" in w for w in res["viewports"]["desktop"]["waarschuwingen"])   # ...maar wel gemeld
    assert "n.v.t" in rapport.maak_tekst(res, "r")


# ---------------------------------------------------------------- ongeldig: ontbrekende of foute cellen
def test_ontbrekende_cellen_zijn_ongeldig(tmp_path):
    for waarden in (dict(GOED, C=None),                                # hele rij leeg
                    dict(GOED, C=(4, 4, "", 4, 4)),                    # een cel leeg
                    {l: w for l, w in GOED.items() if l != "H"}):      # label ontbreekt
        res = beoordeel(tmp_path, waarden)
        c = controle(res, "cellen")
        assert c["ok"] is False and "onvolledige of ongeldige beoordeling" in c["tekst"], waarden
        geen_winst(res)
    assert "1 lege cellen" in controle(beoordeel(tmp_path, dict(GOED, C=(4, 4, "", 4, 4))), "cellen")["tekst"]


@pytest.mark.parametrize("waarde", ["6", "0", "3.5", "abc", "-1"])
def test_celwaarden_buiten_1_tot_5_of_geen_geheel_getal_zijn_ongeldig(tmp_path, waarde):
    res = beoordeel(tmp_path, dict(GOED, C=(4, 4, waarde, 4, 4)))
    assert controle(res, "cellen")["ok"] is False and "geen geheel getal van 1 tot 5" in controle(res, "cellen")["tekst"]


def test_nederlandse_csv_met_puntkomma_decimale_komma_en_bom_wordt_gelezen(tmp_path):
    res = beoordeel(tmp_path, dict(GOED, C=("4,0", "4,0", "3,0", "4", "4.0")), delim=";", bom=True)
    assert res["verdict"] == "GELDIG"


def test_onbekende_en_dubbele_labels_zijn_ongeldig(tmp_path):
    res = beoordeel(tmp_path, GOED, extra_rijen=[["Z", "3", "3", "3", "3", "3", ""]])
    assert "onbekende labels" in controle(res, "cellen")["tekst"] and not res["geldig"]
    res = beoordeel(tmp_path, GOED, extra_rijen=[["C", "3", "3", "3", "3", "3", ""]])
    assert "dubbele labels" in controle(res, "cellen")["tekst"] and not res["geldig"]


def test_ontbrekende_kolommen_zijn_een_invoerfout(tmp_path):
    pad = tmp_path / "b.csv"
    pad.write_text("label,hierarchie_1_5\nA,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="kolommen ontbreken"):
        rapport.lees_csv(pad)


def test_een_viewport_zonder_ingevulde_csv_is_ongeldig(tmp_path):
    csv = schrijf_csv(tmp_path / "d.csv", GOED)
    res = rapport.beoordeel_ronde(maak_sleutel(viewports=("desktop", "mobile")), {"desktop": csv, "mobile": None})
    assert res["viewports"]["desktop"]["geldig"] is True and res["viewports"]["mobile"]["geldig"] is False
    assert res["verdict"] == "ONGELDIG" and not any(res["winst_boven_decoys"].values())
    assert any("geen ingevulde beoordeling.csv" in r for r in res["redenen_ongeldig"])


# ---------------------------------------------------------------- ongeldig: geen controlegroepen
def test_zonder_anker_of_zonder_decoy_is_er_geen_controle_en_dus_geen_geldige_ronde(tmp_path):
    zonder_anker = [i for i in basis_items() if i["soort"] != "anker"]
    res = beoordeel(tmp_path, {l: w for l, w in GOED.items() if l != "A"}, sleutel=maak_sleutel(zonder_anker))
    assert controle(res, "anker")["ok"] is False and "geen anker" in controle(res, "anker")["tekst"]
    geen_winst(res)
    zonder_decoy = [i for i in basis_items() if i["soort"] != "decoy"]
    res = beoordeel(tmp_path, {l: w for l, w in GOED.items() if l not in "IJ"}, sleutel=maak_sleutel(zonder_decoy))
    assert controle(res, "bodem")["ok"] is False and "geen decoy" in controle(res, "bodem")["tekst"]
    geen_winst(res)


# ---------------------------------------------------------------- ongeldig: interne inconsistentie
def test_willekeurige_invulling_waarbij_het_totaal_de_deelcijfers_niet_volgt_is_ongeldig(tmp_path):
    waarden = {}
    for l, w in GOED.items():
        deel = w[0]
        waarden[l] = (deel, deel, deel, deel, 6 - deel)               # totaalindruk omgekeerd
    res = beoordeel(tmp_path, waarden)
    c = controle(res, "consistentie")
    assert c["ok"] is False and "volgt de deelcijfers niet" in c["tekst"] and "willekeurig" in c["tekst"]
    geen_winst(res)


def test_bij_weinig_beelden_wordt_de_consistentie_niet_beoordeeld_maar_gemeld(tmp_path):
    items = [item("A", "Anker", "anker"), item("B", "Ons", "ours"), item("C", "Alfa", "comp"),
             item("D", "Decoy", "decoy", "zwak")]
    res = beoordeel(tmp_path, {"A": rij(5), "B": rij(4), "C": (3, 4, 3, 3, 3), "D": rij(1)},
                    sleutel=maak_sleutel(items))
    assert controle(res, "consistentie")["ok"] is None and "niet beoordeeld" in controle(res, "consistentie")["tekst"]
    assert res["verdict"] == "GELDIG"


def test_spearman():
    assert rapport.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert rapport.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert rapport.spearman([1, 2, 3], [5, 5, 5]) is None
    assert rapport.spearman([1, 1, 2, 3], [1, 1, 2, 3]) == pytest.approx(1.0)      # gelijke waarden krijgen een gemiddelde rang


# ---------------------------------------------------------------- de sleutel zelf
def test_een_testronde_zonder_eigen_schermen_is_niet_bruikbaar_voor_oordeel(tmp_path):
    items = [i for i in basis_items() if i["soort"] != "ours"]
    sleutel = maak_sleutel(items, meetlat={"bruikbaar_voor_oordeel": False, "status": "NIET-BRUIKBAAR-VOOR-OORDEEL",
                                           "redenen_niet_bruikbaar": ["de ronde bevat geen enkel eigen scherm (bewuste testronde)"]})
    res = beoordeel(tmp_path, {l: w for l, w in GOED.items() if l != "B"}, sleutel=sleutel)
    assert res["verdict"] == "NIET-BRUIKBAAR-VOOR-OORDEEL" and res["geldig"] is False
    assert "geen enkel eigen scherm" in res["redenen_ongeldig"][0]
    geen_winst(res)


def test_een_sleutel_van_het_oude_harnas_is_ongeldig(tmp_path):
    oud = {"script_versie": "1.0.0", "viewports": maak_sleutel()["viewports"]}
    res = beoordeel(tmp_path, GOED, sleutel=oud)
    assert res["verdict"] == "ONGELDIG" and "van voor versie 2" in res["redenen_ongeldig"][0]
    geen_winst(res)


def test_een_hoogte_die_een_vingerafdruk_is_maakt_de_ronde_ongeldig(tmp_path):
    sleutel = maak_sleutel()
    sleutel["hoogte_eigenschap"]["desktop"]["unieke_hoogtes"] = 7
    res = beoordeel(tmp_path, GOED, sleutel=sleutel)
    assert res["verdict"] == "ONGELDIG" and "vingerafdruk" in res["redenen_ongeldig"][0]
    geen_winst(res)


def test_waarschuwingen_uit_de_sleutel_en_de_beoordelaar_komen_in_het_rapport(tmp_path):
    sleutel = maak_sleutel(meetlat={"domein_filter": "alles"}, waarschuwingen=["classificatie ontbreekt in het manifest (klasse: 3 beelden)"],
                           ocr={"dekking": "OCR-dekking: gecontroleerd op 812 woorden in 10 beelden, 31 kaders gemaskeerd",
                                "beelden_met_lage_dekking": ["desktop/D"]})
    res = beoordeel(tmp_path, GOED, sleutel=sleutel, opmerkingen={"C": "Dit lijkt op Alfa, of is het de decoy?"})
    w = " | ".join(res["waarschuwingen"] + res["viewports"]["desktop"]["waarschuwingen"])
    assert "gemengde ronde" in w and "classificatie ontbreekt" in w and "desktop/D" in w
    assert "noemt zelf een bron" in w and "C" in w
    assert res["verdict"] == "GELDIG"                                # waarschuwingen maken niet ongeldig
    assert "OCR-dekking: gecontroleerd op 812 woorden" in rapport.maak_tekst(res, "r")


# ---------------------------------------------------------------- commandoregel
def _ronde_op_schijf(tmp_path, waarden, sleutel=None):
    uit = tmp_path / "ab"
    (uit / "r" / "desktop").mkdir(parents=True)
    (uit / "_sleutel.json").write_text(json.dumps({"rondes": {"r": sleutel or maak_sleutel()}}), encoding="utf-8")
    schrijf_csv(uit / "r" / "desktop" / "beoordeling.csv", waarden)
    return uit


def test_cli_exitcodes_en_json(tmp_path, capsys):
    uit = _ronde_op_schijf(tmp_path, GOED)
    assert rapport.main(["--ronde", "r", "--uit", str(uit), "--json", str(tmp_path / "r.json")]) == 0
    assert "OORDEEL: GELDIG" in capsys.readouterr().out
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["verdict"] == "GELDIG" and data["drempels"]["marge_boven"] == rapport.DREMPELS["marge_boven"]
    assert "_uitslagen" not in data
    uit2 = _ronde_op_schijf(tmp_path / "x", {l: rij(3) for l in GOED})
    assert rapport.main(["--ronde", "r", "--uit", str(uit2)]) == 1
    assert "OORDEEL: ONGELDIG" in capsys.readouterr().out
    assert rapport.main(["--ronde", "bestaat_niet", "--uit", str(uit)]) == 2
    assert rapport.main(["--ronde", "r", "--uit", str(tmp_path / "leeg")]) == 2
    (uit / "r" / "desktop" / "beoordeling.csv").unlink()
    assert rapport.main(["--ronde", "r", "--uit", str(uit)]) == 2
    csv = schrijf_csv(tmp_path / "elders.csv", GOED)
    assert rapport.main(["--ronde", "r", "--uit", str(uit), "--beoordeling", f"desktop={csv}"]) == 0


def test_de_eigen_zelftest_van_het_rapport_slaagt(capsys):
    assert rapport.zelftest() == 0
    assert "ZELFTEST: ok" in capsys.readouterr().out


# ---------------------------------------------------------------- harnas en rapport samen
def _vul_in(tmp_path, ronde, beoordelaar):
    """Vult de beoordeling.csv van elke viewport in met een beoordelaar (functie van het sleutelitem)."""
    sleutel = lees_sleutel(tmp_path, ronde)
    for vp, d in sleutel["viewports"].items():
        waarden = {i["label"]: beoordelaar(i) for i in d["items"]}
        schrijf_csv(tmp_path / "ab" / ronde / vp / "beoordeling.csv", waarden)


def ideale_beoordelaar(i):
    kw = {"zeer_zwak": 1, "zwak": 2, "matig": 2, "redelijk": 3}
    basis = 5 if i["is_anker"] else 4 if i["is_ons"] else kw[i["kwaliteit"]] if i["is_decoy"] else 3 + (len(i["bron_naam"]) % 2)
    return (basis, basis, max(1, basis - 1), basis, basis)


def test_harnas_en_rapport_samen_geldig_bij_een_beoordelaar_met_smaak_ongeldig_bij_luiheid_of_onzin(tmp_path):
    m = bouw_bronnen(tmp_path, decoys=(("zeer_zwak", 600), ("matig", 900)))
    assert draai(tmp_path, m) == 0                                    # 5 comps, ons, 2 decoys, anker per viewport
    sleutel = lees_sleutel(tmp_path)
    assert all(len(d["items"]) == 9 for d in sleutel["viewports"].values())
    uit = str(tmp_path / "ab")
    _vul_in(tmp_path, "r", ideale_beoordelaar)
    assert rapport.main(["--ronde", "r", "--uit", uit]) == 0

    def rapport_uitslag():
        return rapport.beoordeel_ronde(lees_sleutel(tmp_path), {vp: tmp_path / "ab" / "r" / vp / "beoordeling.csv"
                                                                 for vp in sleutel["viewports"]})

    ok = rapport_uitslag()
    assert ok["verdict"] == "GELDIG" and all(ok["winst_boven_decoys"].values()) and len(ok["winst_boven_decoys"]) == 2

    _vul_in(tmp_path, "r", lambda i: rij(3))                          # de luie beoordelaar
    res = rapport_uitslag()
    assert res["verdict"] == "ONGELDIG" and not any(res["winst_boven_decoys"].values())

    _vul_in(tmp_path, "r", lambda i: rij(5 if i["is_decoy"] else 1 if i["is_anker"] else 3))     # smaak omgekeerd
    res = rapport_uitslag()
    assert res["verdict"] == "ONGELDIG" and not any(res["winst_boven_decoys"].values())
    assert any("anker" in r for r in res["redenen_ongeldig"])

    # ons scherm onder de (hoger gewaardeerde) bodem van de decoys
    def onder_de_bodem(i):
        if i["is_ons"]:
            return rij(1)
        if i["is_decoy"]:
            return rij(3 if i["kwaliteit"] == "zeer_zwak" else 4)
        return ideale_beoordelaar(i)

    _vul_in(tmp_path, "r", onder_de_bodem)
    res = rapport_uitslag()
    assert res["verdict"] == "ONGELDIG" and any("ONS SCHERM" in r for r in res["redenen_ongeldig"])
    assert rapport.main(["--ronde", "r", "--uit", uit]) == 1

    # een deels ingevulde beoordeling (een viewport leeg gelaten) is ook ongeldig
    _vul_in(tmp_path, "r", ideale_beoordelaar)
    leeg = tmp_path / "ab" / "r" / "mobile" / "beoordeling.csv"
    leeg.write_text(leeg.read_text(encoding="utf-8").split("\n")[0] + "\n" + "".join(
        f"{i['label']},,,,,,\n" for i in sleutel["viewports"]["mobile"]["items"]), encoding="utf-8")
    res = rapport_uitslag()
    assert res["verdict"] == "ONGELDIG" and res["viewports"]["desktop"]["geldig"] is True
    assert not any(res["winst_boven_decoys"].values())


# ---------------------------------------------------------------- vergelijkbare soorten scherm
def _label_van(naam):
    return next(i["label"] for i in basis_items() if i["bron_naam"] == naam)


def test_ons_scherm_wordt_alleen_met_vergelijkbare_comps_vergeleken(tmp_path):
    """Foxtrot (docs) scoort 5 en zou de mediaan omhoog trekken; zij hoort niet in de vergelijking."""
    res = beoordeel(tmp_path, dict(GOED, **{_label_van("Foxtrot"): rij(5)}))
    c = res["viewports"]["desktop"]["conclusie"]
    e = c["vergelijking_met_comps"][0]
    assert e["ons_soort"] == "app/dashboard" and e["familie"] == "werkscherm"
    assert e["aantal_comps"] == 5 and e["buiten_vergelijking"] == {"docs": 1}
    assert e["soorten_vergelijkbaar"] == ["app/dashboard", "formulier"]        # formulier is ook een werkscherm
    import statistics
    bronnen = res["viewports"]["desktop"]["bronnen"]
    werk = [b["gemiddelde"] for b in bronnen if b["soort"] == "comp" and b["soort_scherm"] != "docs"]
    alle = [b["gemiddelde"] for b in bronnen if b["soort"] == "comp"]
    assert e["comps_mediaan"] == pytest.approx(statistics.median(werk))
    assert statistics.median(alle) != e["comps_mediaan"]
    tekst = rapport.maak_tekst(res, "r")
    assert "vergelijkbare comps (werkscherm: app/dashboard, formulier; 5 bronnen)" in tekst
    assert "buiten de vergelijking gelaten: docs 1x" in tekst


def test_niveau_ten_opzichte_van_de_comps_hangt_alleen_van_vergelijkbare_soorten_af(tmp_path):
    """Ons scherm 3,0; de werkschermen scoren 4,0 (ons ligt daar onder), de docs-comp 2,0 (ons zou erboven liggen)."""
    waarden = {"A": rij(5), "B": rij(3), "I": rij(1), "J": rij(2)}
    for it in basis_items():
        if it["soort"] == "comp":
            waarden[it["label"]] = rij(2) if it["soort_scherm"] == "docs" else rij(4)
    waarden["C"], waarden["D"] = (4, 4, 4, 4, 5), (4, 4, 4, 4, 3)     # een beetje spreiding tegen 'alles gelijk'
    res = beoordeel(tmp_path, waarden)
    assert res["verdict"] == "GELDIG"
    e = res["viewports"]["desktop"]["conclusie"]["vergelijking_met_comps"][0]
    assert e["op_niveau"] is False and e["rang"] == 6              # onder alle vijf de werkschermen
    assert res["viewports"]["desktop"]["conclusie"]["op_niveau_van_comps"] is False
    assert "ONDER het niveau van die comps" in rapport.maak_tekst(res, "r")


def test_onbekende_soort_van_ons_scherm_geeft_geen_uitspraak_over_de_comps_wel_over_de_decoys(tmp_path):
    items = [dict(i, soort_scherm="") if i["soort"] == "ours" else i for i in basis_items()]
    res = beoordeel(tmp_path, GOED, sleutel=maak_sleutel(items))
    assert res["verdict"] == "GELDIG"
    c = res["viewports"]["desktop"]["conclusie"]
    e = c["vergelijking_met_comps"][0]
    assert e["ons_soort"] == "onbekend" and e["op_niveau"] is None and "onbekend" in e["reden"]
    assert c["op_niveau_van_comps"] is None and "rang_onder_comps" not in c
    assert c["boven_decoys"] is True                                # de decoys blijven vergelijkbaar
    assert any("soort_scherm van ons scherm is onbekend" in w for w in res["viewports"]["desktop"]["waarschuwingen"])
    tekst = rapport.maak_tekst(res, "r")
    assert "t.o.v. de comps: GEEN uitspraak" in tekst and "eindigt BOVEN de decoys" in tekst


def test_comps_zonder_soort_scherm_tellen_niet_als_vergelijkbaar(tmp_path):
    items = [dict(i, soort_scherm="") if i["soort"] == "comp" and i["bron_naam"] in ("Alfa", "Bravo") else i
             for i in basis_items()]
    res = beoordeel(tmp_path, GOED, sleutel=maak_sleutel(items))
    e = res["viewports"]["desktop"]["conclusie"]["vergelijking_met_comps"][0]
    assert e["aantal_comps"] == 3                                   # Charlie, Delta en Echo
    assert e["buiten_vergelijking"] == {"docs": 1, "onbekend": 2}
    assert any("2 comps hebben geen soort_scherm" in w for w in res["viewports"]["desktop"]["waarschuwingen"])
    assert any("slechts 3 vergelijkbare comps" in w for w in res["viewports"]["desktop"]["waarschuwingen"])


def test_geen_enkele_vergelijkbare_comp_geeft_geen_uitspraak(tmp_path):
    items = [dict(i, soort_scherm="docs") if i["soort"] == "comp" else i for i in basis_items()]
    res = beoordeel(tmp_path, GOED, sleutel=maak_sleutel(items))
    e = res["viewports"]["desktop"]["conclusie"]["vergelijking_met_comps"][0]
    assert e["aantal_vergelijkbaar"] == 0 and e["op_niveau"] is None
    assert "geen comps van een vergelijkbare soort" in e["reden"]
    assert res["verdict"] == "GELDIG"                               # de controles zelf hangen er niet van af


def test_meerdere_soorten_eigen_schermen_worden_elk_met_hun_eigen_soort_vergeleken(tmp_path):
    items = basis_items() + [item("K", "Ons formulier", "ours", soort_scherm="docs")]
    res = beoordeel(tmp_path, dict(GOED, K=rij(4)), sleutel=maak_sleutel(items))
    soorten = {e["ons_soort"]: e for e in res["viewports"]["desktop"]["conclusie"]["vergelijking_met_comps"]}
    assert set(soorten) == {"app/dashboard", "docs"}
    assert soorten["docs"]["familie"] == "documentatie" and soorten["docs"]["aantal_comps"] == 1      # alleen Foxtrot
    assert soorten["app/dashboard"]["aantal_comps"] == 5


def test_scores_per_soort_scherm_staan_in_het_rapport(tmp_path):
    res = beoordeel(tmp_path, GOED)
    per = {p["soort_scherm"]: p for p in res["viewports"]["desktop"]["per_soort_scherm"]}
    assert set(per) == {"app/dashboard", "formulier", "docs"}
    assert per["app/dashboard"]["familie"] == "werkscherm" and per["docs"]["familie"] == "documentatie"
    rollen = per["app/dashboard"]["rollen"]
    assert rollen["comp"]["aantal_bronnen"] == 4 and rollen["ours"]["aantal_bronnen"] == 1
    assert rollen["decoy"]["aantal_bronnen"] == 2 and rollen["anker"]["gemiddelde"] == 5.0
    assert per["docs"]["rollen"]["comp"]["gemiddelde"] == pytest.approx(2.8)      # Foxtrot = label H
    tekst = rapport.maak_tekst(res, "r")
    assert "Per soort scherm" in tekst and "app/dashboard [werkscherm]" in tekst and "docs [documentatie]" in tekst
    assert res["soort_scherm_familie"]["formulier"] == "werkscherm"


def test_familie_en_normalisatie_van_soort_scherm():
    assert rapport.familie("App / Dashboard") == "werkscherm" == rapport.familie("formulier") == rapport.familie("register")
    assert rapport.familie("docs") == "documentatie" != rapport.familie("app/dashboard")
    assert rapport.familie("iets nieuws") == "iets nieuws"          # onbekende soort: alleen met zichzelf vergelijkbaar
    assert rapport.familie("") == "onbekend"


@pytest.mark.parametrize("soort,verwacht", [
    # de waarden die de opnamescripts nu echt schrijven
    ("app", "werkscherm"), ("dashboard", "werkscherm"), ("dataviewer", "werkscherm"),
    ("boekingsflow", "werkscherm"), ("formulierstap", "werkscherm"), ("formulier", "werkscherm"),
    ("lijstweergave", "werkscherm"), ("zoekscherm", "werkscherm"), ("zoekresultaten", "werkscherm"),
    ("register_zoekresultaten", "werkscherm"),
    ("docs", "documentatie"), ("informatiepagina", "documentatie"), ("document_lezer", "documentatie"),
    ("marketing_home", "marketing"), ("productpagina", "marketing"), ("galerij_landing", "marketing"),
    ("prijzenpagina", "marketing"), ("vergelijker_landing", "marketing"), ("organisatie_homepage", "marketing"),
    ("inlogpoort", "toegang"),
    # samengestelde waarde: het eerste bekende deel telt; onbekend blijft een eigen familie
    ("formulier_landing", "werkscherm"), ("nieuw_type", "nieuw_type"),
])
def test_de_soorten_scherm_uit_de_echte_manifesten_hebben_een_familie(soort, verwacht):
    assert rapport.familie(soort) == verwacht


def test_werkschermen_en_documentatie_of_marketing_zijn_nooit_onderling_vergelijkbaar():
    werk = {rapport.familie(x) for x in ("app", "dashboard", "dataviewer", "formulierstap", "zoekscherm")}
    assert werk == {"werkscherm"}
    for anders in ("docs", "informatiepagina", "productpagina", "marketing_home", "inlogpoort"):
        assert rapport.familie(anders) != "werkscherm"


# ---------------------------------------------------------------- manifestvormen in het rapport
def test_het_rapport_meldt_welke_bron_uit_welke_manifestvorm_kwam(tmp_path):
    res = beoordeel(tmp_path, GOED)
    vormen = res["manifestvormen"]
    assert set(vormen["object.bestanden[bestandsnaam-map]"]) == {"Ankerbron (ANKER)", "Decoy matig (decoy)",
                                                                 "Decoy zeer zwak (decoy)"}
    assert set(vormen["geen manifest"]) == {"Ons scherm (ONS)"}
    assert {"Alfa (comp)", "Charlie (comp)", "Echo (comp)"} <= set(vormen["lijst"])
    assert {"Bravo (comp)", "Delta (comp)", "Foxtrot (comp)"} <= set(vormen["object.comps[lijst].bestanden[viewportmap]"])
    tekst = rapport.maak_tekst(res, "r")
    assert "Manifestvormen (uit welke vorm elke bron kwam):" in tekst
    assert "object.bestanden[bestandsnaam-map]: " in tekst and "geen manifest: Ons scherm (ONS)" in tekst
    for b in res["viewports"]["desktop"]["bronnen"]:
        assert b["manifest_vorm"] != "onbekend"


def test_een_sleutel_zonder_vormveld_wordt_als_onbekend_gemeld(tmp_path):
    items = [{k: v for k, v in i.items() if k not in ("manifest_vorm", "soort_scherm")} for i in basis_items()]
    res = beoordeel(tmp_path, GOED, sleutel=maak_sleutel(items))
    assert list(res["manifestvormen"]) == ["onbekend (sleutel zonder vormveld)"]


# ---------------------------------------------------------------- een masker is zelf een signaal
def _met_maskers(per_label):
    return maak_sleutel([dict(i, ocr={"kaders_gemaskeerd": per_label[i["label"]]}) for i in basis_items()])


def test_score_die_meeloopt_met_het_aantal_maskers_geeft_een_waarschuwing_maar_geen_ongeldigheid(tmp_path):
    maskers = {l: 6 - GOED[l][4] for l in GOED}                      # laag totaalcijfer <-> veel maskers
    res = beoordeel(tmp_path, GOED, sleutel=_met_maskers(maskers))
    v = res["viewports"]["desktop"]
    assert res["verdict"] == "GELDIG"                                # een waarschuwing, geen ongeldigheid
    assert v["maskers_vs_score"]["rho"] < -0.8 and v["maskers_vs_score"]["n"] == 10
    assert any("gemaskeerde kaders" in w and "lager" in w for w in v["waarschuwingen"])
    assert "gemaskeerde kaders per beeld" in rapport.maak_tekst(res, "r")
    omgekeerd = {l: GOED[l][4] for l in GOED}                        # hoog cijfer <-> veel maskers
    res2 = beoordeel(tmp_path, GOED, sleutel=_met_maskers(omgekeerd))
    assert any("gemaskeerde kaders" in w and "hoger" in w for w in res2["viewports"]["desktop"]["waarschuwingen"])


def test_scores_die_niet_met_de_maskers_meelopen_geven_geen_waarschuwing(tmp_path):
    maskers = dict(zip("ABCDEFGHIJ", (3, 1, 0, 2, 3, 0, 1, 3, 0, 2)))
    res = beoordeel(tmp_path, GOED, sleutel=_met_maskers(maskers))
    v = res["viewports"]["desktop"]
    assert abs(v["maskers_vs_score"]["rho"]) < rapport.DREMPELS["masker_samenhang"]
    assert not any("gemaskeerde kaders" in w for w in v["waarschuwingen"])


def test_zonder_maskerverschil_of_zonder_maskergegevens_is_er_niets_te_melden(tmp_path):
    gelijk = _met_maskers({l: 2 for l in GOED})                      # overal evenveel: niets om te correleren
    v = beoordeel(tmp_path, GOED, sleutel=gelijk)["viewports"]["desktop"]
    assert v["maskers_vs_score"] == {} and not any("gemaskeerde kaders" in w for w in v["waarschuwingen"])
    v2 = beoordeel(tmp_path, GOED)["viewports"]["desktop"]           # sleutel zonder ocr-gegevens per beeld
    assert v2["maskers_vs_score"] == {}
