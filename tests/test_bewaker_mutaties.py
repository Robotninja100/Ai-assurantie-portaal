"""De bewaker ziet elke ingebouwde fout (de kleine versie van scripts/bewaker_mutaties.py, op echte bronnen)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import api                       # noqa: E402
import features                  # noqa: E402
import bewaker_mutaties as bm    # noqa: E402


def _opdracht_en_antwoord():
    o = features.dekkingscheck("Waterschade door een gesprongen leiding in de badkamer, klant heeft een Univé woonverzekering.")
    wet = next(d for d in o["opgehaald"]["wetgeving"] if d["wet"] == "BW")
    pol = o["opgehaald"]["polisvoorwaarden"][0]
    antwoord = (f"Volgens art. {wet['artikel']} lid 1 BW geldt de wet. De polis regelt dit in {pol['clausule_id']}. "
                "Vervolgstap: bel de verzekeraar.")
    return o, antwoord


def test_het_uitgangsantwoord_is_gefundeerd():
    o, antwoord = _opdracht_en_antwoord()
    assert api.beoordeel_antwoord(o, antwoord)[0]["oordeel"] == "GEFUNDEERD"


def test_de_bewaker_wijst_elke_ingebouwde_fout_aan_en_laat_de_herhaling_van_een_gefundeerde_verwijzing_met_rust():
    o, antwoord = _opdracht_en_antwoord()
    controle = api.beoordeel_antwoord(o, antwoord)[0]
    gezien = set()
    for naam, nieuw, marker in bm.maak_mutaties(o, antwoord, controle):
        gezien.add(naam)
        if naam.startswith("CONTROLE"):
            assert api.beoordeel_antwoord(o, nieuw)[0]["oordeel"] == "GEFUNDEERD", naam
        else:
            assert bm._aangewezen(o, nieuw, marker), naam
    assert {"wetsartikel_verzonnen", "kifid_verzonnen", "bedrag_verzonnen", "citaat_verzonnen", "datum_verzonnen",
            "percentage_verzonnen", "ecli_verzonnen", "lid_bestaat_niet", "wet_verwisseld",
            "CONTROLE_herhaalde_gefundeerde_verwijzing"} <= gezien
