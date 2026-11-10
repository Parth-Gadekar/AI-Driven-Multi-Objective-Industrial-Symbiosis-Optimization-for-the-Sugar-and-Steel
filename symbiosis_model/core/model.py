"""Build the optimisation problem: lanes, arcs and per-tonne objective coefficients.

Decision variable: tonnes x[arc] moved from a source node to a receiver node within one lane.
All four objectives and all constraints are linear in x:
  f1  net economic benefit  = value - processing - transport cost        (INR/yr)   maximise
  f2  waste utilised        = tonnes exchanged                           (t/yr)     maximise
  f3  transport work        = tonnes x road km                           (t-km/yr)  minimise
  f4  net CO2 avoided       = avoided by substitution - transport CO2   (t CO2/yr) maximise
Constraints: sum of outflow <= supply at each source, sum of inflow <= absorption cap at each receiver,
and lanes whose compatibility score is below the threshold are removed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from . import data as D

OBJ_NAMES = ["net_economic_benefit_inr", "waste_utilised_t", "transport_work_tkm", "net_co2_avoided_t"]
OBJ_SIGN = np.array([-1.0, -1.0, 1.0, -1.0])      # multiply by sign to get "minimise" form


@dataclass
class Lane:
    lane_id: str
    material: str
    receiver: str
    compat: float
    supply: np.ndarray            # tonnes/yr per node
    cap: np.ndarray               # tonnes/yr per node
    value_inr_t: float
    processing_inr_t: float
    co2_avoided_t_per_t: float
    eligible: bool = True
    note: str = ""


@dataclass
class Network:
    nodes: list[str]
    hub: list[str]
    lat: np.ndarray
    lon: np.ndarray
    dist: np.ndarray
    lanes: list[Lane]
    season: str
    case: str
    # arc arrays (eligible lanes only)
    arc_lane: np.ndarray = field(default=None)
    arc_s: np.ndarray = field(default=None)
    arc_r: np.ndarray = field(default=None)
    arc_km: np.ndarray = field(default=None)
    arc_mode: list = field(default=None)
    arc_transport_cost: np.ndarray = field(default=None)    # INR/t
    arc_transport_co2: np.ndarray = field(default=None)     # t CO2/t
    C: np.ndarray = field(default=None)                     # (4, A) per-tonne objective coefficients (natural sign)
    A_src: object = None                                    # sparse (n_src_rows, A)
    b_src: np.ndarray = None
    A_rec: object = None
    b_rec: np.ndarray = None
    src_rows: list = field(default=None)                    # (lane_idx, node)
    rec_rows: list = field(default=None)
    params: D.Params = None
    not_modelled: list = field(default_factory=list)


def _transport(km: np.ndarray, P: D.Params, c: str):
    road, rail = P.get("road_cost_inr_per_tkm", c), P.get("rail_cost_inr_per_tkm", c)
    thr, flm = P.get("rail_threshold_km", c), P.get("rail_first_last_mile_km", c)
    co2_road, co2_rail = P.get("co2_road_kg_per_tkm", c) / 1000, P.get("co2_rail_kg_per_tkm", c) / 1000
    road_cost = road * km
    rail_cost = rail * km + road * flm
    use_rail = (km >= thr) & (rail_cost < road_cost)
    cost = np.where(use_rail, rail_cost, road_cost)
    co2 = np.where(use_rail, co2_rail * km + co2_road * flm, co2_road * km)
    return cost, co2, use_rail


def build(season: str = "2024-25", case: str = "base", cost_case: str = "base",
          steel_year: str = "2020-21", threshold: float | None = None, params: D.Params | None = None) -> Network:
    """case drives supply and receiver absorption (low/base/high); cost_case drives prices/freight."""
    from scipy import sparse
    P = params or D.Params.load()
    nodes_df = D.load_nodes()
    nodes = nodes_df.state.tolist()
    n = len(nodes)
    dist = D.load_distance(nodes)
    comp = D.compat_scores()
    thr = P.get("compat_threshold") if threshold is None else threshold

    # ---- supplies ----
    sugar = D.sugar_by_node(season, nodes, case)
    scale = D.steel_scale_2024_25() if steel_year == "2024-25" else 1.0
    slag = D.steel_slag_by_node(nodes, case, scale)
    ash = sugar["bagasse"] * P.get("bagasse_burn_fraction", case) * P.get("bagasse_ash_yield", case)
    mol = sugar["molasses"]

    # ---- receiver absorption ----
    cement = D.cement_capacity_by_node(nodes) * P.get("cement_utilisation", case)
    cap_slag = cement * P.get("steel_slag_cement_share", case)
    cap_ash = cement * P.get("bagasse_ash_cement_share", case)
    offtake = P.get("distillery_offtake_share", case) * mol.sum()
    cap_mol = offtake * D.distillery_weights(nodes)

    # ---- per-tonne economics / CO2 for each lane ----
    co2_slag = P.get("steel_slag_cao_fraction", case) * P.get("calcination_co2_per_t_cao", case)
    co2_ash = P.get("opc_co2_t_per_t", case) * P.get("ash_cement_replacement_ratio", case)
    mol_price = P.get("molasses_price_usd_per_t", cost_case) * P.get("inr_per_usd", cost_case)

    lanes = [
        Lane("STEEL_RAW", "Steelmaking slag (LD/EAF)", "Cement plants (raw-meal CaO source)", comp["STEEL_RAW"], slag, cap_slag,
             P.get("steel_slag_value_inr_per_t", cost_case), P.get("steel_slag_processing_inr_per_t", cost_case), co2_slag,
             note="Supply: crude steel x 150-200 kg/t, 2020-21. Cap: cement capacity x utilisation x slag share."),
        Lane("ASH_POZ", "Bagasse fly ash", "Cement plants (pozzolan)", comp["ASH_POZ"], ash, cap_ash,
             P.get("bagasse_ash_value_inr_per_t", cost_case), P.get("bagasse_ash_processing_inr_per_t", cost_case), co2_ash,
             note="Supply: bagasse x burn fraction x ash yield. Cap: cement capacity x utilisation x ash share."),
        Lane("MOL_DIST", "Molasses", "Distilleries (fuel ethanol)", comp["MOL_DIST"], mol, cap_mol,
             0.0, P.get("molasses_processing_inr_per_t", cost_case), 0.0,
             note="Supply: cane x ratio. Demand: national offtake share x state distribution of DFPD molasses-only capacity. "
                  "Price is a mill-to-distillery transfer (reference INR %.0f/t) and counts as zero system benefit." % mol_price),
    ]
    for l in lanes:
        l.eligible = l.compat >= thr

    net = Network(nodes, nodes_df.hub_city.tolist(), nodes_df.lat.to_numpy(), nodes_df.lon.to_numpy(), dist, lanes,
                  season, case, params=P)
    net.not_modelled = [
        {"lane": "Press mud to compost/biogas", "reason": "No receiver demand data collected; compatibility score 0.84 only."},
        {"lane": "Blast-furnace slag to cement", "reason": "No state-wise BF slag supply; >90% already absorbed by cement (P14)."},
        {"lane": "Bagasse to cogeneration / paper", "reason": "Largely in-plant use; no exchange network data."},
    ]

    # ---- arcs ----
    A_lane, A_s, A_r = [], [], []
    for li, l in enumerate(lanes):
        if not l.eligible:
            continue
        for s in np.nonzero(l.supply > 0)[0]:
            for r in np.nonzero(l.cap > 0)[0]:
                A_lane.append(li); A_s.append(s); A_r.append(r)
    net.arc_lane, net.arc_s, net.arc_r = map(np.array, (A_lane, A_s, A_r))
    km = dist[net.arc_s, net.arc_r]
    cost, co2, rail = _transport(km, P, cost_case)
    net.arc_km, net.arc_transport_cost, net.arc_transport_co2 = km, cost, co2
    net.arc_mode = ["rail" if x else "road" for x in rail]
    val = np.array([lanes[i].value_inr_t - lanes[i].processing_inr_t for i in net.arc_lane])
    avoid = np.array([lanes[i].co2_avoided_t_per_t for i in net.arc_lane])
    net.C = np.vstack([val - cost, np.ones_like(km), km, avoid - co2])

    # ---- constraints ----
    src_keys, rec_keys = {}, {}
    ri, ci, ri2, ci2 = [], [], [], []
    for a, (li, s, r) in enumerate(zip(net.arc_lane, net.arc_s, net.arc_r)):
        ks = src_keys.setdefault((li, s), len(src_keys)); ri.append(ks); ci.append(a)
        kr = rec_keys.setdefault((li, r), len(rec_keys)); ri2.append(kr); ci2.append(a)
    A = len(km)
    net.A_src = sparse.csr_matrix((np.ones(A), (ri, ci)), shape=(len(src_keys), A))
    net.A_rec = sparse.csr_matrix((np.ones(A), (ri2, ci2)), shape=(len(rec_keys), A))
    net.src_rows, net.rec_rows = list(src_keys), list(rec_keys)
    net.b_src = np.array([lanes[li].supply[s] for li, s in net.src_rows])
    net.b_rec = np.array([lanes[li].cap[r] for li, r in net.rec_rows])
    return net


def objectives(net: Network, x: np.ndarray) -> np.ndarray:
    """Objective values in natural units: [net benefit INR, utilised t, t-km, net CO2 t]."""
    return net.C @ x


def to_min(f: np.ndarray) -> np.ndarray:
    return f * OBJ_SIGN


def check_feasible(net: Network, x: np.ndarray, tol: float = 1e-6) -> dict:
    s = net.A_src @ x - net.b_src
    r = net.A_rec @ x - net.b_rec
    return {"min_x": float(x.min()), "max_supply_violation": float(max(s.max(), 0)),
            "max_capacity_violation": float(max(r.max(), 0)),
            "ok": bool(x.min() >= -tol and s.max() <= tol * max(1, net.b_src.max()) and r.max() <= tol * max(1, net.b_rec.max()))}
