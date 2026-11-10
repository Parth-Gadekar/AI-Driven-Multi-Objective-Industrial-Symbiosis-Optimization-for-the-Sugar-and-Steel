"""Load the real datasets and turn them into a state-level exchange network.

Nodes are the 22 hub states in state_hub_coordinates_approx.csv. Sugar data are reported by
ISMA "regions" (e.g. "North Bihar", "Madhya Pradesh & Chhattisgarh"); each region is assigned
to ONE hub node (REGION_TO_NODE below). Steel-slag states with no hub are folded into the
nearest hub (STEEL_STATE_TO_NODE). These mappings are modelling choices, not source facts.

Everything is state-level and distances are hub-to-hub road estimates, so every result
is a pipeline test until plant coordinates and real prices replace them.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"

REGION_TO_NODE = {
    "Andhra Pradesh": "Andhra Pradesh", "North Bihar": "Bihar", "Gujarat": "Gujarat",
    "Haryana": "Haryana", "Karnataka": "Karnataka", "Kerala & Goa": "Kerala",
    "Madhya Pradesh & Chhattisgarh": "Madhya Pradesh", "Maharashtra": "Maharashtra",
    "Punjab": "Punjab", "Rajasthan": "Rajasthan", "Telangana": "Telangana",
    "Tamil Nadu & Puducherry": "Tamil Nadu", "Uttar Pradesh": "Uttar Pradesh",
    "Uttarakhand": "Uttarakhand",
    "Others (Assam, Odisha, Nagaland, West Bengal)": "West Bengal",
}
STEEL_STATE_TO_NODE = {
    "Goa": "Maharashtra", "Dadra and Nagar Haveli": "Gujarat", "Daman and Diu": "Gujarat",
    "Delhi": "Haryana", "Tripura": "Assam", "Arunachal Pradesh": "Assam",
    "Puducherry": "Tamil Nadu", "Jammu and Kashmir": "Jammu & Kashmir",
}
INTRASTATE_KM = 50.0  # haul distance when source and receiver are in the same state (assumption)

SEASONS = ["2023-24", "2024-25", "2025-26"]
CASES = ["low", "base", "high"]


@dataclass
class Params:
    """Parameter table with low/base/high columns; `case` picks which column is active."""
    table: pd.DataFrame

    @classmethod
    def load(cls) -> "Params":
        return cls(pd.read_csv(DATA / "model_parameters.csv").set_index("parameter"))

    def get(self, name: str, case: str = "base") -> float:
        return float(self.table.loc[name, case])

    def status(self, name: str) -> str:
        return str(self.table.loc[name, "status"])


def load_nodes() -> pd.DataFrame:
    return pd.read_csv(DATA / "state_hub_coordinates_approx.csv")[["state", "hub_city", "lat", "lon"]]


def load_distance(nodes: list[str]) -> np.ndarray:
    d = pd.read_csv(DATA / "state_distance_matrix_approx.csv")
    m = d.pivot(index="from_state", columns="to_state", values="est_road_km").loc[nodes, nodes].to_numpy(float).copy()
    np.fill_diagonal(m, INTRASTATE_KM)
    return m


def load_sugar(season: str) -> pd.DataFrame:
    a = pd.read_csv(DATA / "derived_statewise_sugar_byproducts_2023_24.csv")
    b = pd.read_csv(DATA / "derived_statewise_sugar_byproducts_2024_25_2025_26.csv")
    df = pd.concat([a, b], ignore_index=True)
    return df[df.season == season].copy()


def sugar_by_node(season: str, nodes: list[str], case: str) -> dict[str, np.ndarray]:
    """Bagasse and molasses supply (tonnes) per node for the chosen case (min/mid/max)."""
    col = {"low": "min", "base": "mid", "high": "max"}[case]
    df = load_sugar(season)
    out = {k: np.zeros(len(nodes)) for k in ("bagasse", "molasses")}
    for _, r in df.iterrows():
        node = REGION_TO_NODE[r["state"]]
        i = nodes.index(node)
        for k in out:
            v = r[f"{k}_tonnes_{col}"]
            out[k][i] += 0.0 if pd.isna(v) else float(v)
    return out


def steel_slag_by_node(nodes: list[str], case: str, scale: float = 1.0) -> np.ndarray:
    col = {"low": "low", "base": "mid", "high": "high"}[case]
    df = pd.read_csv(DATA / "steel_slag_estimate_by_state_2020_21.csv")
    out = np.zeros(len(nodes))
    for _, r in df.iterrows():
        node = STEEL_STATE_TO_NODE.get(r["state"], r["state"])
        out[nodes.index(node)] += float(r[f"steelmaking_slag_t_{col}"]) * scale
    return out


def steel_scale_2024_25() -> float:
    """Uniform scale: national crude steel 2024-25 (152.18 Mt, Ministry of Steel) over the 2020-21 state sum."""
    df = pd.read_csv(DATA / "steel_slag_estimate_by_state_2020_21.csv")
    return 152.18e3 / float(df.crude_steel_kt_2020_21.sum())


def cement_capacity_by_node(nodes: list[str]) -> np.ndarray:
    df = pd.read_csv(DATA / "cement_receiver_capacity_by_state.csv").set_index("state")
    return np.array([float(df.capacity_mt.get(n, 0.0)) * 1e6 for n in nodes])  # tonnes cement per year


def distillery_weights(nodes: list[str]) -> np.ndarray:
    """Share of national distillery molasses demand per node, from DFPD sanctioned molasses-only capacity.
    (The table is a capacity ceiling, so only its geographic distribution is used, not its level.)"""
    df = pd.read_csv(DATA / "molasses_demand_by_state_dfpd_sanctioned_2018_22.csv")
    w = np.zeros(len(nodes))
    for _, r in df.iterrows():
        reg = r["state_region"]
        if reg in REGION_TO_NODE:
            w[nodes.index(REGION_TO_NODE[reg])] += float(r["ceiling_molasses_req_t_yr_low"])
    return w / w.sum()


def compat_scores() -> dict[str, float]:
    s = pd.read_csv(DATA / "compatibility_scores.csv").set_index("lane_id").score_base
    return {
        "STEEL_RAW": float((s["LD_RAW"] + s["EAF_RAW"]) / 2),   # steelmaking slag treated as LD/EAF mix
        "ASH_POZ": float(s["BA_POZ"]),
        "MOL_DIST": float(s["MOL_DIST"]),
    }
