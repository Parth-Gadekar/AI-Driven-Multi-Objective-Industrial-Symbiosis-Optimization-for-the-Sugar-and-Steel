"""User-mode advice: for one plant (a state + a by-product) list where the material can go, or where it can come from.

There is no priority to choose. All four model objectives (money, waste reused, haul distance, CO2) are combined into ONE
answer by compromise programming: among the candidate national plans, take the one whose normalised objective vector is
closest to the ideal point (the best each objective can reach on its own). Candidates are the exact LP weighted-sum
front plus the NSGA-II compromise stored in results/ (when present); whichever is closest to the ideal wins. This is the
same rule Developer mode uses for its "NSGA-II (compromise point)" row.

  * plan    : that single national plan. It accounts for receivers filling up, so it is where the material is sent when
              every producer is served at once.
  * options : every possible partner state with per-tonne economics, distance, mode and CO2, ranked by a match score
              (0-100) built like the original prototype's: compatibility 30%, economic 25%, CO2 25%, utilization 20%,
              each a 0-1 factor shown separately. Utilization is the share of the state's material the combined plan sends
              to that partner. Cost ranges come from the low / base / high cost cases.

Technical fit (compatibility score) is a gate: routes below the threshold are removed before anything is combined, and
the score is shown with the result. Everything is state-level and inherits the model's placeholders; the response lists
which ones matter for the chosen material so the UI can say so.
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
from . import data as D, model as M, solvers as S

# direction "out": the user produces the material; "in": the user receives it.
ROLES = {
    "sugar_mill":   {"label": "Sugar mill",   "blurb": "I produce bagasse ash and molasses", "direction": "out", "materials": ["ASH_POZ", "MOL_DIST"]},
    "steel_plant":  {"label": "Steel plant",  "blurb": "I produce steelmaking slag (LD / EAF)", "direction": "out", "materials": ["STEEL_RAW"]},
    "cement_plant": {"label": "Cement plant", "blurb": "I can use slag or bagasse ash", "direction": "in", "materials": ["STEEL_RAW", "ASH_POZ"]},
    "distillery":   {"label": "Distillery",   "blurb": "I buy molasses for ethanol", "direction": "in", "materials": ["MOL_DIST"]},
}

LANE_INFO = {
    "STEEL_RAW": {
        "name": "Steel slag", "short": "slag", "use": "a limestone (CaO) substitute in cement raw meal",
        "partner": "cement plants",
        "params": ["steel_slag_cement_share", "cement_utilisation", "steel_slag_value_inr_per_t", "steel_slag_processing_inr_per_t"],
        "questions": [
            "What limits does the plant's raw-mix design set on MgO and FeO in the slag?",
            "Do they take LD slag, EAF slag, or both?",
            "Does the slag need metal recovery, ageing or crushing first, and to what size?",
            "Who pays for loading, transport and storage?",
        ]},
    "ASH_POZ": {
        "name": "Bagasse ash", "short": "ash", "use": "a pozzolan that replaces part of the cement",
        "partner": "cement plants",
        "params": ["bagasse_ash_cement_share", "cement_utilisation", "bagasse_ash_value_inr_per_t", "bagasse_ash_processing_inr_per_t"],
        "questions": [
            "What limits do they set on loss on ignition (unburnt carbon) and silica content?",
            "Do they take the ash as it comes, or does it need drying or grinding?",
            "Is the ash from bagasse only, or mixed with other fuels?",
            "Who pays for loading, transport and storage?",
        ]},
    "MOL_DIST": {
        "name": "Molasses", "short": "molasses", "use": "feedstock for fuel-ethanol distilleries",
        "partner": "distilleries",
        "params": ["distillery_offtake_share"],
        "value_note": "The molasses price itself is not counted: it is paid between mill and distillery. The figures show only extra haul cost.",
        "questions": [
            "Does the distillery buy by contract or on the spot, and what sugar content (TRS) does it expect?",
            "Does it have storage capacity for molasses this season?",
            "Who pays for tankers, loading and storage?",
        ]},
}

PLAIN = {
    "steel_slag_cement_share": ("Steel slag a cement plant can take", "% of its cement output", 100),
    "bagasse_ash_cement_share": ("Bagasse ash a cement plant can take", "% of its cement output", 100),
    "cement_utilisation": ("How much of cement capacity is in use", "%", 100),
    "steel_slag_value_inr_per_t": ("Value of slag to the cement plant", "INR per tonne", 1),
    "steel_slag_processing_inr_per_t": ("Cost to crush, age or sort slag", "INR per tonne", 1),
    "bagasse_ash_value_inr_per_t": ("Value of ash to the cement plant", "INR per tonne", 1),
    "bagasse_ash_processing_inr_per_t": ("Cost to dry or grind ash", "INR per tonne", 1),
    "distillery_offtake_share": ("Share of molasses that distilleries buy", "%", 100),
}

# Which places are folded into each hub state (see core/data.py REGION_TO_NODE / STEEL_STATE_TO_NODE). Keep in sync.
SUGAR_NOTES = {
    "Bihar": "Sugar data covers North Bihar.",
    "Madhya Pradesh": "Sugar data for Madhya Pradesh and Chhattisgarh is counted here.",
    "Kerala": "Sugar data for Kerala and Goa is counted here.",
    "Tamil Nadu": "Includes Puducherry.",
    "West Bengal": "Sugar data for Assam, Odisha, Nagaland and West Bengal is counted here.",
}
STEEL_NOTES = {
    "Maharashtra": "Steel data for Goa is counted here.",
    "Gujarat": "Steel data for Dadra & Nagar Haveli and Daman & Diu is counted here.",
    "Haryana": "Steel data for Delhi is counted here.",
    "Assam": "Steel data for Tripura and Arunachal Pradesh is counted here.",
    "Tamil Nadu": "Includes Puducherry.",
}


def _notes(material: str, direction: str) -> dict:
    """Folding notes that apply to this material and side. Cement receivers are reported by state, so none apply."""
    if material == "STEEL_RAW":
        return STEEL_NOTES if direction == "out" else {}
    return SUGAR_NOTES        # ash supply and molasses supply/demand come from the sugar-region tables


@lru_cache(maxsize=32)
def _net(season: str, case: str, cost_case: str) -> M.Network:
    return M.build(season, case, cost_case)


@lru_cache(maxsize=32)
def _index(season: str, case: str, cost_case: str) -> dict:
    n = _net(season, case, cost_case)
    return {(int(l), int(s), int(r)): i for i, (l, s, r) in enumerate(zip(n.arc_lane, n.arc_s, n.arc_r))}


RESULTS = Path(__file__).resolve().parent.parent / "results"
# Match score = weighted sum of four 0-1 factors, with the weights of the original prototype (ml/rules.py DEFAULT_WEIGHTS).
# A factor that does not apply to a material (no CO2 saving counted for molasses) is left out and the rest re-weighted.
MATCH_WEIGHTS = {"compatibility": 0.30, "economic": 0.25, "co2": 0.25, "utilization": 0.20}
_clip01 = lambda x: max(0.0, min(1.0, float(x)))


def _gross_value(net: M.Network, lane, cost_only: bool) -> float:
    """What a tonne is worth to the receiver, before handling and haul (INR/t). Molasses is a zero-value transfer in the
    system model, but its price is the right basis for a plant's own economics, so the price is used for the score only."""
    if cost_only:
        P = net.params
        return float(P.get("molasses_price_usd_per_t") * P.get("inr_per_usd"))
    return float(lane.value_inr_t)


def _nsga_compromise(net: M.Network, season: str, case: str):
    """Flow vector of the stored NSGA-II compromise for this scenario, or None if unavailable or not feasible."""
    p = RESULTS / f"{season}_{case}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        sc = d["scenario"]
        if sc["cost_case"] != "base" or sc["steel_year"] != "2020-21" or abs(sc["threshold"] - net.params.get("compat_threshold")) > 1e-9:
            return None
        lane_ix = {l.lane_id: i for i, l in enumerate(net.lanes)}
        idx = _index(season, case, "base")
        x = np.zeros(len(net.arc_km))
        for f in d["methods"]["nsga2_compromise"]["flows"]:
            x[idx[(lane_ix[f["lane"]], net.nodes.index(f["from"]), net.nodes.index(f["to"]))]] += f["tonnes"]
        return x if M.check_feasible(net, x)["ok"] else None
    except (KeyError, ValueError, OSError):
        return None


@lru_cache(maxsize=16)
def _plan(season: str, case: str):
    """The single combined national plan. Returns (flows, method label, normalised objectives, natural objectives)."""
    net = _net(season, case, "base")
    ideal, nadir, _ = S.payoff(net)
    cands = [(x, "LP front") for x in S.pareto_front_lp(net, ideal, nadir, step=0.1)]
    nx = _nsga_compromise(net, season, case)
    if nx is not None:
        cands.append((nx, "NSGA-II"))
    F = np.array([S.normalise(M.to_min(M.objectives(net, x)), ideal, nadir) for x, _ in cands])
    i = int(np.argmin(np.linalg.norm(F, axis=1)))
    x = cands[i][0]
    return x, cands[i][1], F[i], M.objectives(net, x)


def _lane_index(net: M.Network, lane_id: str) -> int:
    return next(i for i, l in enumerate(net.lanes) if l.lane_id == lane_id)


def options(season: str = "2024-25", case: str = "base") -> dict:
    """What the form needs: roles, materials, which states apply to each, presets."""
    net = _net(season, case, "base")
    P = net.params
    roles = {}
    for rid, r in ROLES.items():
        mats = []
        for m in r["materials"]:
            l = net.lanes[_lane_index(net, m)]
            vec = l.supply if r["direction"] == "out" else l.cap
            mats.append({"id": m, "name": LANE_INFO[m]["name"], "eligible": bool(l.eligible), "notes": _notes(m, r["direction"]),
                         "states": [n for n, v in zip(net.nodes, vec) if v > 0]})
        roles[rid] = {"label": r["label"], "blurb": r["blurb"], "direction": r["direction"], "materials": mats}
    return {"roles": roles, "seasons": D.SEASONS, "cases": D.CASES, "compat_threshold": P.get("compat_threshold")}


def assumptions_block(P, info: dict):
    """The key inputs behind a material's numbers, with their status, and an overall confidence level."""
    assumptions = []
    for p in info["params"]:
        label, unit, mult = PLAIN[p]
        assumptions.append({"label": label, "value": round(P.get(p) * mult, 2), "unit": unit, "status": P.status(p),
                            "range": [round(P.get(p, "low") * mult, 2), round(P.get(p, "high") * mult, 2)]})
    n_ph = sum(a["status"] == "PLACEHOLDER" for a in assumptions)
    confidence = "low" if n_ph >= 3 else "medium" if n_ph >= 1 or any(a["status"] == "derived_estimate" for a in assumptions) else "high"
    return assumptions, n_ph, confidence


def advise(role: str, state: str, material: str | None = None,
           tonnes: float | None = None, season: str = "2024-25", case: str = "base") -> dict:
    if role not in ROLES:
        raise ValueError(f"unknown role '{role}'")
    R = ROLES[role]
    if material is None and len(R["materials"]) == 1:
        material = R["materials"][0]
    if material not in R["materials"]:
        raise ValueError(f"'{material}' is not a material for a {R['label'].lower()}")
    if season not in D.SEASONS or case not in D.CASES:
        raise ValueError("bad season or case")
    if tonnes is not None and (not np.isfinite(tonnes) or tonnes < 0):
        raise ValueError("tonnes must be a positive number")

    net = _net(season, case, "base")
    li = _lane_index(net, material)
    lane, info = net.lanes[li], LANE_INFO[material]
    if not lane.eligible:
        raise ValueError(f"The {info['name'].lower()} route is switched off at the current compatibility threshold.")
    if state not in net.nodes:
        raise ValueError(f"unknown state '{state}'")
    si = net.nodes.index(state)
    out = R["direction"] == "out"
    own_total = float(lane.supply[si] if out else lane.cap[si])
    if own_total <= 0:
        what = "supply of" if out else "demand for"
        raise ValueError(f"No modelled {what} {info['name'].lower()} in {state}.")

    mine = net.arc_s if out else net.arc_r
    sel = np.nonzero((net.arc_lane == li) & (mine == si))[0]
    cost_only = abs(lane.value_inr_t - lane.processing_inr_t) < 1e-9
    x, plan_method, plan_norm, plan_obj = _plan(season, case)
    nets = {cc: _net(season, case, cc) for cc in D.CASES}
    idx = {cc: _index(season, case, cc) for cc in D.CASES}

    rows = []
    for a in sel:
        s, r = int(net.arc_s[a]), int(net.arc_r[a])
        o = r if out else s
        key = (li, s, r)
        nb = [float(nets[cc].C[0][idx[cc][key]]) for cc in D.CASES]
        plan_t = float(x[a])
        rows.append({
            "state": net.nodes[o], "hub_city": net.hub[o], "ll": [float(net.lat[o]), float(net.lon[o])],
            "same_state": o == si, "km": float(net.arc_km[a]), "mode": net.arc_mode[a],
            "value_inr_t": float(lane.value_inr_t - lane.processing_inr_t),
            "transport_inr_t": float(net.arc_transport_cost[a]),
            "net_inr_t": float(net.C[0][a]), "net_inr_t_range": [min(nb), max(nb)],
            "co2_t_per_t": float(net.C[3][a]),
            "partner_size_t": float(lane.cap[o] if out else lane.supply[o]),
            "plan_t": plan_t if plan_t > 1.0 else 0.0,
        })
    if not rows:
        raise ValueError("No partner states found for this selection.")

    placed = sum(r["plan_t"] for r in rows)
    for r in rows:
        r["plan_share_of_own_pct"] = 100 * r["plan_t"] / own_total
        r["plan_share_of_moved_pct"] = 100 * r["plan_t"] / placed if placed > 0 else 0.0

    # ---- match score: four factors, weighted, like the original prototype (see MATCH_WEIGHTS) ----
    gross = _gross_value(net, lane, cost_only)
    avoided = float(lane.co2_avoided_t_per_t)
    compat = float(lane.compat)
    for r in rows:
        f = {"compatibility": compat,
             "economic": _clip01((gross - lane.processing_inr_t - r["transport_inr_t"]) / gross) if gross > 0 else None,
             "co2": _clip01(r["co2_t_per_t"] / avoided) if avoided > 0 else None,
             # how much of the state's material the combined plan routes here, weighted by technical fit
             "utilization": _clip01(_clip01(r["plan_share_of_own_pct"] / 100) * compat + (1 - compat) * 0.1)}
        used = {k: v for k, v in f.items() if v is not None}
        wsum = sum(MATCH_WEIGHTS[k] for k in used)
        r["factors"] = {k: (round(v, 3) if v is not None else None) for k, v in f.items()}
        r["score"] = round(100 * sum(MATCH_WEIGHTS[k] * v for k, v in used.items()) / wsum, 1)
    rows.sort(key=lambda r: (-r["score"], -r["plan_t"], r["km"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    plan = sorted([r for r in rows if r["plan_t"] > 0], key=lambda r: -r["plan_t"])

    summary = {"own_total_t": own_total, "placed_t": placed, "placed_pct": 100 * placed / own_total}
    if placed > 0:
        summary["avg_net_inr_t"] = sum(r["plan_t"] * r["net_inr_t"] for r in plan) / placed
        summary["avg_km"] = sum(r["plan_t"] * r["km"] for r in plan) / placed
        summary["avg_co2_t_per_t"] = sum(r["plan_t"] * r["co2_t_per_t"] for r in plan) / placed
        summary["avg_net_inr_t_range"] = [sum(r["plan_t"] * r["net_inr_t_range"][0] for r in plan) / placed,
                                          sum(r["plan_t"] * r["net_inr_t_range"][1] for r in plan) / placed]
        if tonnes:
            moved = tonnes * summary["placed_pct"] / 100 if out else min(tonnes, placed)
            summary["annual"] = {
                "tonnes": tonnes, "moved_t": moved, "shortfall_t": max(tonnes - placed, 0.0) if not out else 0.0,
                "net_inr": moved * summary["avg_net_inr_t"],
                "net_inr_range": [moved * summary["avg_net_inr_t_range"][0], moved * summary["avg_net_inr_t_range"][1]],
                "co2_t": moved * summary["avg_co2_t_per_t"],
                "split": [{"state": r["state"], "tonnes": moved * r["plan_share_of_moved_pct"] / 100} for r in plan]}

    assumptions, n_ph, confidence = assumptions_block(net.params, info)
    return {
        "request": {"role": role, "state": state, "material": material, "tonnes": tonnes, "season": season, "case": case},
        "direction": R["direction"], "material": {"id": material, "name": info["name"], "short": info["short"], "use": info["use"],
                                                  "partner": info["partner"], "value_note": info.get("value_note"),
                                                  "cost_only": cost_only},
        "compatibility": round(lane.compat, 3),
        "you": {"state": state, "hub_city": net.hub[si], "ll": [float(net.lat[si]), float(net.lon[si])],
                "note": _notes(material, R["direction"]).get(state)},
        "summary": summary, "plan": plan, "options": rows,
        "confidence": {"level": confidence, "placeholders": n_ph, "assumptions": assumptions},
        "questions": info["questions"],
        "combined": {"method": plan_method, "distance_from_ideal": round(float(np.linalg.norm(plan_norm)), 3),
                     "national": {"net_benefit_inr": float(plan_obj[0]), "utilised_t": float(plan_obj[1]),
                                  "transport_work_tkm": float(plan_obj[2]), "net_co2_t": float(plan_obj[3]),
                                  "mean_haul_km": float(plan_obj[2] / plan_obj[1]) if plan_obj[1] > 0 else 0.0}},
    }
