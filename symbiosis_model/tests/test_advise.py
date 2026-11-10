"""User-mode advice layer. Runs under pytest; has no pymoo dependency."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from core import advise as A


def test_options_cover_every_role_and_state_lists_are_nonempty():
    o = A.options()
    assert set(o["roles"]) == set(A.ROLES)
    for r in o["roles"].values():
        for m in r["materials"]:
            assert m["states"], (r["label"], m["id"])


def test_every_listed_state_gives_a_result():
    o = A.options()
    for rid, r in o["roles"].items():
        for m in r["materials"]:
            for st in m["states"][:4]:
                out = A.advise(rid, st, m["id"], tonnes=1000)
                assert out["options"] and out["options"][0]["rank"] == 1
                top = out["options"][0]
                assert top["score"] == max(x["score"] for x in out["options"])


def test_plan_never_exceeds_supply_or_capacity():
    a = A.advise("sugar_mill", "Maharashtra", "ASH_POZ")
    assert a["summary"]["placed_t"] <= a["summary"]["own_total_t"] * (1 + 1e-9)
    for o in a["options"]:
        assert o["plan_t"] <= o["partner_size_t"] * (1 + 1e-9)


def test_range_brackets_base_and_same_state_is_50km():
    a = A.advise("steel_plant", "Kerala")
    for o in a["options"]:
        lo, hi = o["net_inr_t_range"]
        assert lo - 1e-6 <= o["net_inr_t"] <= hi + 1e-6
    assert any(o["same_state"] and o["km"] == 50 for o in a["options"])


def test_molasses_is_cost_only_and_still_places_tonnes():
    a = A.advise("sugar_mill", "Maharashtra", "MOL_DIST")
    assert a["material"]["cost_only"] and a["summary"]["placed_t"] > 0


def test_receiver_shortfall_is_reported():
    a = A.advise("cement_plant", "Rajasthan", "ASH_POZ", tonnes=5000)
    an = a["summary"]["annual"]
    assert an["moved_t"] <= 5000 and abs(an["moved_t"] + an["shortfall_t"] - 5000) < 1e-6


def test_confidence_reflects_placeholders():
    assert A.advise("steel_plant", "Odisha")["confidence"]["level"] == "low"
    assert A.advise("distillery", "Uttar Pradesh")["confidence"]["level"] == "medium"


def test_bad_input_is_rejected():
    for kw in (dict(role="nope", state="Kerala"), dict(role="steel_plant", state="Atlantis"),
               dict(role="sugar_mill", state="Kerala", material="STEEL_RAW"), dict(role="steel_plant", state="Kerala", tonnes=-5), dict(role="sugar_mill", state="Himachal Pradesh", material="ASH_POZ")):
        try:
            A.advise(**kw)
        except ValueError:
            continue
        raise AssertionError(kw)


def test_single_combined_plan_is_closest_to_ideal_and_feasible():
    """The plan is one fixed national arrangement: same for every plant, independent of any user choice,
    feasible, and at least as close to the ideal point as every LP front candidate."""
    from core import model as M, solvers as S
    net = A._net("2024-25", "base", "base")
    x, method, norm, obj = A._plan("2024-25", "base")
    assert method in ("LP front", "NSGA-II") and M.check_feasible(net, x)["ok"]
    ideal, nadir, _ = S.payoff(net)
    for y in S.pareto_front_lp(net, ideal, nadir, step=0.2):
        assert np.linalg.norm(norm) <= np.linalg.norm(S.normalise(M.to_min(M.objectives(net, y)), ideal, nadir)) + 1e-9
    a, b = A.advise("steel_plant", "Odisha"), A.advise("sugar_mill", "Maharashtra", "ASH_POZ")
    assert a["combined"] == b["combined"]


def test_match_score_is_the_prototype_style_weighted_sum_of_four_factors():
    """0-100 score = 0.30 fit + 0.25 economics + 0.25 CO2 + 0.20 utilisation, each 0-1; a factor that does not apply
    (CO2 for molasses) is dropped and the remaining weights are rescaled."""
    assert abs(sum(A.MATCH_WEIGHTS.values()) - 1) < 1e-12
    assert A.MATCH_WEIGHTS == {"compatibility": 0.30, "economic": 0.25, "co2": 0.25, "utilization": 0.20}
    for args in (("sugar_mill", "Maharashtra", "ASH_POZ"), ("steel_plant", "Odisha", "STEEL_RAW"),
                 ("sugar_mill", "Uttar Pradesh", "MOL_DIST"), ("cement_plant", "Rajasthan", "ASH_POZ")):
        a = A.advise(*args, tonnes=5000)
        scores = [o["score"] for o in a["options"]]
        assert scores == sorted(scores, reverse=True)
        for o in a["options"]:
            used = {k: v for k, v in o["factors"].items() if v is not None}
            assert all(0 <= v <= 1 for v in used.values()) and 0 <= o["score"] <= 100
            want = 100 * sum(A.MATCH_WEIGHTS[k] * v for k, v in used.items()) / sum(A.MATCH_WEIGHTS[k] for k in used)
            assert abs(o["score"] - want) < 0.15            # score is rounded to 1 dp, factors to 3 dp
            assert o["factors"]["compatibility"] == a["compatibility"]
    mol = A.advise("sugar_mill", "Uttar Pradesh", "MOL_DIST")
    assert all(o["factors"]["co2"] is None for o in mol["options"])


def test_far_partners_lose_economics_and_in_state_partner_keeps_it():
    a = A.advise("sugar_mill", "Maharashtra", "ASH_POZ")
    near = next(o for o in a["options"] if o["same_state"])
    far = [o for o in a["options"] if not o["same_state"]]
    assert near["factors"]["economic"] > 0 and all(o["factors"]["economic"] <= near["factors"]["economic"] for o in far)
    assert a["options"][0]["same_state"]
