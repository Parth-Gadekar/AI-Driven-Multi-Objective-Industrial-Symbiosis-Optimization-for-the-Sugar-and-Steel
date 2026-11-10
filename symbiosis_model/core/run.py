"""Run one scenario: baselines + LP reference front + NSGA-II, and package results for the API."""
from __future__ import annotations
import time
import numpy as np
from . import model as M, solvers as S

METHODS = ["nearest_feasible", "rule_based", "economic_only", "weighted_sum", "nsga2_compromise"]
LABELS = {"nearest_feasible": "Nearest feasible match", "rule_based": "Rule-based (largest receiver in reach)",
          "economic_only": "Economic-only optimisation", "weighted_sum": "Weighted-sum optimisation",
          "nsga2_compromise": "NSGA-II (compromise point)"}


def summarize(net: M.Network, x: np.ndarray) -> dict:
    f = M.objectives(net, x)
    supply_total = sum(l.supply.sum() for l in net.lanes if l.eligible)
    t = float(f[1])
    by_lane = {}
    for li, l in enumerate(net.lanes):
        if not l.eligible:
            continue
        m = net.arc_lane == li
        q = float(x[m].sum())
        by_lane[l.lane_id] = {"material": l.material, "supply_t": float(l.supply.sum()), "cap_t": float(l.cap.sum()),
                              "moved_t": q, "utilisation_pct": 100 * q / max(l.supply.sum(), 1e-9),
                              "net_benefit_inr": float(net.C[0][m] @ x[m]), "net_co2_t": float(net.C[3][m] @ x[m])}
    return {"net_benefit_inr": float(f[0]), "utilised_t": t, "utilised_pct_of_supply": 100 * t / max(supply_total, 1e-9),
            "transport_work_tkm": float(f[2]), "mean_haul_km": float(f[2] / t) if t > 0 else 0.0,
            "net_co2_t": float(f[3]), "by_lane": by_lane}


def flows(net: M.Network, x: np.ndarray, min_t: float = 1.0) -> list[dict]:
    rows = []
    for a in np.nonzero(x > min_t)[0]:
        l = net.lanes[net.arc_lane[a]]
        q = float(x[a])
        s, r = net.arc_s[a], net.arc_r[a]
        rows.append({
            "lane": l.lane_id, "material": l.material, "receiver_type": l.receiver,
            "from": net.nodes[s], "to": net.nodes[r],
            "from_ll": [float(net.lat[s]), float(net.lon[s])], "to_ll": [float(net.lat[r]), float(net.lon[r])],
            "tonnes": q, "km": float(net.arc_km[a]), "mode": net.arc_mode[a], "compatibility": round(l.compat, 3),
            "value_inr": q * (l.value_inr_t - l.processing_inr_t), "transport_cost_inr": q * float(net.arc_transport_cost[a]),
            "net_benefit_inr": q * float(net.C[0][a]), "co2_avoided_t": q * l.co2_avoided_t_per_t,
            "co2_transport_t": q * float(net.arc_transport_co2[a]), "net_co2_t": q * float(net.C[3][a]),
            "share_of_source_pct": 100 * q / max(l.supply[s], 1e-9)})
    rows.sort(key=lambda r: -r["tonnes"])
    return rows


def hypervolume(Fn: np.ndarray, ref: float = 1.1) -> float:
    from pymoo.indicators.hv import HV      # imported here so the app still runs without pymoo (user mode, precomputed results)
    Fn = np.atleast_2d(Fn)
    Fn = Fn[(Fn <= ref).all(axis=1)]
    return float(HV(ref_point=np.full(Fn.shape[1], ref))(Fn)) if len(Fn) else 0.0


def compromise(Fn: np.ndarray) -> int:
    """Index of the point closest to the ideal (origin) in normalised objective space."""
    return int(np.argmin(np.linalg.norm(Fn, axis=1)))


def run_scenario(season="2024-25", case="base", cost_case="base", steel_year="2020-21", threshold=None,
                 weights=None, nsga_pop=120, nsga_gens=150, seed=1, do_nsga=True) -> dict:
    t0 = time.time()
    net = M.build(season, case, cost_case, steel_year, threshold)
    w = np.array(weights if weights is not None else S.DEFAULT_WEIGHTS, float)
    w = w / w.sum()
    ideal, nadir, _ = S.payoff(net)
    sol = {"nearest_feasible": S.nearest_feasible(net), "rule_based": S.rule_based(net),
           "economic_only": S.economic_only(net), "weighted_sum": S.weighted_sum(net, w, ideal, nadir)}
    lp_flows = S.pareto_front_lp(net, ideal, nadir, step=0.1)
    lp_F = np.array([S.normalise(M.to_min(M.objectives(net, x)), ideal, nadir) for x in lp_flows])
    out = {"scenario": {"season": season, "case": case, "cost_case": cost_case, "steel_year": steel_year,
                        "threshold": net.params.get("compat_threshold") if threshold is None else threshold,
                        "weights": dict(zip(["economic", "utilisation", "transport_work", "co2"], w.round(4).tolist()))},
           "lanes": [{"lane_id": l.lane_id, "material": l.material, "receiver": l.receiver, "compat": round(l.compat, 3),
                      "eligible": bool(l.eligible), "supply_t": float(l.supply.sum()), "cap_t": float(l.cap.sum()),
                      "note": l.note} for l in net.lanes],
           "not_modelled": net.not_modelled, "n_arcs": int(len(net.arc_km))}
    front = {"lp": lp_F.tolist()}
    nsga_info = None
    if do_nsga:
        from . import nsga
        nf, nF = nsga.run_nsga2(net, ideal, nadir, pop=nsga_pop, gens=nsga_gens, seed=seed)
        ci = compromise(nF)
        sol["nsga2_compromise"] = nf[ci]
        hv_n, hv_l = hypervolume(nF), hypervolume(lp_F)
        nsga_info = {"front_size": int(len(nF)), "hypervolume": hv_n, "lp_reference_hypervolume": hv_l,
                     "hv_ratio_vs_lp": hv_n / hv_l if hv_l > 0 else None, "pop": nsga_pop, "gens": nsga_gens}
        front["nsga2"] = nF.tolist()
        front["nsga2_natural"] = [M.objectives(net, x).tolist() for x in nf]
    front["lp_natural"] = [M.objectives(net, x).tolist() for x in lp_flows]
    out["front"], out["nsga2"] = front, nsga_info
    out["methods"] = {}
    for k in METHODS:
        if k in sol:
            chk = M.check_feasible(net, sol[k])
            out["methods"][k] = {"label": LABELS[k], "summary": summarize(net, sol[k]), "feasible": chk["ok"],
                                 "flows": flows(net, sol[k])}
    out["objective_names"] = M.OBJ_NAMES
    out["ideal"], out["nadir"] = ideal.tolist(), nadir.tolist()
    out["runtime_s"] = round(time.time() - t0, 1)
    return out
