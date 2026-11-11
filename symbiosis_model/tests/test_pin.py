"""Tests for the Maharashtra pin-to-pin analysis (core/pin.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest
from core import pin as P

AHI, PUNE = (19.095, 74.749), (18.52, 73.86)
NASHIK = (19.997, 73.79)


def test_bbox_rejects_outside():
    with pytest.raises(ValueError):
        P.analyse("ASH_POZ", (28.6, 77.2), PUNE)   # Delhi
    with pytest.raises(ValueError):
        P.analyse("ASH_POZ", AHI, (12.97, 77.59))  # Bengaluru


def test_bad_inputs():
    for kw in ({"material": "XX"}, {"tonnes": -1}, {"importer_capacity_t": 0}, {"season": "1999"}):
        args = {"material": "ASH_POZ", "exporter": AHI, "importer": PUNE}; args.update(kw)
        with pytest.raises(ValueError):
            P.analyse(**args)
    with pytest.raises(ValueError):
        P.analyse("ASH_POZ", (None, 1), PUNE)


def test_distance_estimate_and_routed():
    a = P.analyse("ASH_POZ", AHI, PUNE)
    assert a["distance"]["source"] == "estimate"
    assert abs(a["distance"]["km"] - a["distance"]["straight_km"] * 1.3) < 1e-6
    r = P.analyse("ASH_POZ", AHI, PUNE, road_km=165)
    assert r["distance"]["source"] == "routed" and r["distance"]["km"] == 165
    bad = P.analyse("ASH_POZ", AHI, PUNE, road_km=5)   # implausible: shorter than straight line
    assert bad["distance"]["source"] == "estimate"


def test_ash_verdict_and_break_even():
    near = P.analyse("ASH_POZ", AHI, (19.0, 74.6))
    far = P.analyse("ASH_POZ", AHI, (21.15, 79.09))   # Nagpur
    assert near["verdict"] in ("pays", "marginal") and far["verdict"] == "loses"
    be = far["break_even_km"]
    assert be and near["distance"]["km"] < be < far["distance"]["km"]
    assert near["per_tonne"]["net_inr"] > far["per_tonne"]["net_inr"]


def test_range_brackets_base_and_curve():
    a = P.analyse("ASH_POZ", AHI, PUNE)
    lo, hi = a["per_tonne"]["net_inr_range"]
    assert lo <= a["per_tonne"]["net_inr"] <= hi
    assert a["curve"][0]["km"] == 0 and a["curve"][-1]["km"] >= 1.6 * a["distance"]["km"] - 5


def test_rail_kicks_in_for_long_haul():
    far = P.analyse("ASH_POZ", (21.15, 79.09), (16.7, 74.2))   # ~ >500 km
    assert far["distance"]["km"] >= 500 and far["distance"]["mode"] == "rail"
    assert P.analyse("ASH_POZ", AHI, PUNE)["distance"]["mode"] == "road"


def test_molasses_cost_only():
    m = P.analyse("MOL_DIST", AHI, PUNE)
    assert m["material"]["cost_only"] and m["break_even_km"] is None
    assert m["verdict"] in ("pays", "marginal", "loses")


def test_utilization_only_with_both_quantities():
    assert P.analyse("ASH_POZ", AHI, PUNE)["factors"]["utilization"] is None
    assert P.analyse("ASH_POZ", AHI, PUNE, tonnes=1000)["factors"]["utilization"] is None
    full = P.analyse("ASH_POZ", AHI, PUNE, tonnes=1000, importer_capacity_t=5000)
    short = P.analyse("ASH_POZ", AHI, PUNE, tonnes=1000, importer_capacity_t=100)
    assert full["factors"]["utilization"] > short["factors"]["utilization"]
    assert full["annual"]["fits_capacity"] is True and short["annual"]["fits_capacity"] is False


def test_score_matches_weights():
    a = P.analyse("ASH_POZ", AHI, PUNE)
    used = {k: v for k, v in a["factors"].items() if v is not None}
    w = {"compatibility": .30, "economic": .25, "co2": .25, "utilization": .20}
    exp = 100 * sum(w[k] * v for k, v in used.items()) / sum(w[k] for k in used)
    assert abs(a["score"] - exp) < 0.15
    assert 0 <= a["score"] <= 100
