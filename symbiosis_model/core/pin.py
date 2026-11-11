"""Pin-to-pin analysis (Maharashtra pilot): one exporter location and one importer location, both dropped on a map.

No plant register is needed: the user supplies the two points. For that single pair this module gives the same kind of
answer as the state-level advice: distance and mode, per-tonne economics with a low/high cost range, CO2, a 0-100
match score built like the original prototype's (fit 30, economics 25, CO2 25, use of waste 20), the break-even
distance, a net-versus-distance curve and the assumptions behind the numbers.

Rules are the model's own (core/model.py `_transport`: road, or rail when the haul is long and rail is cheaper) and
the prices, shares and CO2 factors come from the same parameter table. Road distance is a straight line x 1.3
circuity (the same assumption as data/state_distance_matrix_approx.csv) unless the browser supplies a routed road
distance. The Maharashtra limit is an approximate bounding box, not the state border.
"""
from __future__ import annotations
import math
import numpy as np
from . import advise as A, data as D, model as M

# lat_min, lat_max, lon_min, lon_max: approximate bounding box of Maharashtra (it also covers slivers of neighbouring states)
MH_BBOX = (15.6, 22.1, 72.6, 80.9)
CIRCUITY = 1.3
MH = "Maharashtra"

MATERIALS = {
    "ASH_POZ":   {"exporter": "Sugar mill", "importer": "Cement plant"},
    "MOL_DIST":  {"exporter": "Sugar mill", "importer": "Distillery"},
    "STEEL_RAW": {"exporter": "Steel plant", "importer": "Cement plant"},
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def meta() -> dict:
    return {"bbox": MH_BBOX, "circuity": CIRCUITY, "materials": [
        {"id": m, "name": A.LANE_INFO[m]["name"], **v} for m, v in MATERIALS.items()],
        "seasons": D.SEASONS, "cases": D.CASES}


def _point(name: str, p) -> tuple[float, float]:
    try:
        lat, lon = float(p[0]), float(p[1])
    except (TypeError, ValueError, IndexError):
        raise ValueError(f"{name} location is missing or not a number")
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError(f"{name} location is not a number")
    la0, la1, lo0, lo1 = MH_BBOX
    if not (la0 <= lat <= la1 and lo0 <= lon <= lo1):
        raise ValueError(f"The {name} pin is outside the Maharashtra pilot area. Drop it inside Maharashtra.")
    return lat, lon


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def analyse(material: str, exporter, importer, tonnes: float | None = None, importer_capacity_t: float | None = None,
            road_km: float | None = None, season: str = "2024-25", case: str = "base") -> dict:
    if material not in MATERIALS:
        raise ValueError(f"unknown material '{material}'")
    if season not in D.SEASONS or case not in D.CASES:
        raise ValueError("bad season or case")
    for nm, v in (("tonnes", tonnes), ("importer capacity", importer_capacity_t)):
        if v is not None and (not math.isfinite(v) or v <= 0):
            raise ValueError(f"{nm} must be a positive number")
    e_lat, e_lon = _point("exporter", exporter)
    i_lat, i_lon = _point("importer", importer)

    straight = haversine_km(e_lat, e_lon, i_lat, i_lon)
    est = straight * CIRCUITY
    km, source = est, "estimate"
    if road_km is not None and math.isfinite(road_km) and 0.98 * straight <= road_km <= 3 * straight + 20:
        km, source = float(road_km), "routed"

    info = A.LANE_INFO[material]
    nets = {cc: A._net(season, case, cc) for cc in D.CASES}
    base = nets["base"]
    li = next(i for i, l in enumerate(base.lanes) if l.lane_id == material)
    lane = base.lanes[li]
    if not lane.eligible:
        raise ValueError(f"The {info['name'].lower()} route is switched off at the current compatibility threshold.")
    cost_only = abs(lane.value_inr_t - lane.processing_inr_t) < 1e-9

    def per_tonne(kms: np.ndarray, cc: str):
        l = nets[cc].lanes[li]
        cost, co2, rail = M._transport(np.asarray(kms, float), nets[cc].params, cc)
        return (l.value_inr_t - l.processing_inr_t) - cost, cost, co2, rail

    net_b, cost_b, co2_b, rail_b = (float(x[0]) for x in per_tonne([km], "base"))
    rng = [float(per_tonne([km], cc)[0][0]) for cc in D.CASES]
    avoided = float(lane.co2_avoided_t_per_t)
    co2_net = avoided - co2_b
    gross = A._gross_value(base, lane, cost_only)

    # ---- match score: same four factors and weights as state-level advice ----
    compat = float(lane.compat)
    util = None
    if tonnes and importer_capacity_t:
        util = _clip01(_clip01(importer_capacity_t / tonnes) * compat + (1 - compat) * 0.1)
    f = {"compatibility": compat,
         "economic": _clip01((gross - lane.processing_inr_t - cost_b) / gross) if gross > 0 else None,
         "co2": _clip01(co2_net / avoided) if avoided > 0 else None,
         "utilization": util}
    used = {k: v for k, v in f.items() if v is not None}
    score = 100 * sum(A.MATCH_WEIGHTS[k] * v for k, v in used.items()) / sum(A.MATCH_WEIGHTS[k] for k in used)

    # ---- verdict, break-even distance and the net-versus-distance curve ----
    grid = np.arange(0, max(900.0, 1.6 * km) + 1, 5.0)
    gn, gc, _, gr = per_tonne(grid, "base")
    curve = [{"km": float(k), "value": float(c if cost_only else n), "mode": "rail" if r else "road"}
             for k, n, c, r in zip(grid, gn, gc, gr)]
    break_even = None
    if not cost_only:
        fine = np.arange(0, 5001, 1.0)
        fn = per_tonne(fine, "base")[0]
        neg = np.nonzero(fn <= 0)[0]
        break_even = float(fine[neg[0]]) if len(neg) else None
        top = lane.value_inr_t - lane.processing_inr_t
        verdict = "pays" if net_b > 0.25 * top else "marginal" if net_b > 0 else "loses"
    else:
        share = cost_b / gross
        verdict = "pays" if share < 0.05 else "marginal" if share < 0.15 else "loses"

    assumptions, n_ph, confidence = A.assumptions_block(base.params, info)
    si = base.nodes.index(MH)
    out = {
        "request": {"material": material, "tonnes": tonnes, "importer_capacity_t": importer_capacity_t, "season": season, "case": case},
        "material": {"id": material, "name": info["name"], "short": info["short"], "use": info["use"], "partner": info["partner"],
                     "value_note": info.get("value_note"), "cost_only": cost_only, **MATERIALS[material]},
        "exporter": {"lat": e_lat, "lon": e_lon}, "importer": {"lat": i_lat, "lon": i_lon},
        "distance": {"km": km, "source": source, "straight_km": straight, "estimate_km": est, "mode": "rail" if rail_b else "road"},
        "per_tonne": {"gross_value_inr": gross, "value_after_handling_inr": float(lane.value_inr_t - lane.processing_inr_t),
                      "transport_inr": cost_b, "net_inr": net_b, "net_inr_range": [min(rng), max(rng)],
                      "co2_avoided_t": avoided, "co2_transport_t": co2_b, "co2_net_t": co2_net},
        "compatibility": round(compat, 3), "factors": {k: (round(v, 3) if v is not None else None) for k, v in f.items()},
        "score": round(score, 1), "verdict": verdict, "break_even_km": break_even, "curve": curve,
        "maharashtra": {"supply_t": float(lane.supply[si]), "receiver_capacity_t": float(lane.cap[si])},
        "confidence": {"level": confidence, "placeholders": n_ph, "assumptions": assumptions},
        "questions": info["questions"],
    }
    if tonnes:
        out["annual"] = {"tonnes": tonnes, "net_inr": tonnes * net_b, "net_inr_range": [tonnes * min(rng), tonnes * max(rng)],
                         "transport_inr": tonnes * cost_b, "co2_t": tonnes * co2_net,
                         "fits_capacity": (importer_capacity_t >= tonnes) if importer_capacity_t else None}
    return out
