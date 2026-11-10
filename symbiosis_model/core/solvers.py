"""Exact LP reference solutions and the four non-NSGA baselines.

Because every objective and constraint is linear in the flows, a weighted-sum scalarisation is a
plain LP that HiGHS solves exactly. That gives (a) the "economic-only" and "weighted-sum" baselines,
(b) a reference Pareto front (supported points) to benchmark NSGA-II against.
"""
from __future__ import annotations
import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from .model import Network, OBJ_SIGN, objectives, to_min

DEFAULT_WEIGHTS = np.array([0.30, 0.30, 0.15, 0.25])   # economic, utilisation, transport work, CO2


def _solve(net: Network, c: np.ndarray) -> np.ndarray:
    A = sparse.vstack([net.A_src, net.A_rec]).tocsr()
    b = np.concatenate([net.b_src, net.b_rec])
    c = c / np.abs(c).max()          # HiGHS ignores cost coefficients below ~1e-7, so rescale to O(1)
    # constraint rows are in tonnes (up to 1e7); scaling them keeps the LP well conditioned
    sc = np.maximum(b, 1.0)
    A = sparse.diags(1.0 / sc) @ A
    res = linprog(c, A_ub=A, b_ub=b / sc, bounds=(0, None), method="highs")
    if res.status != 0:
        raise RuntimeError(f"LP failed: {res.message}")
    return res.x


def payoff(net: Network):
    """Ideal and nadir (minimise form) from single-objective optima."""
    xs, F = [], []
    for k in range(4):
        c = OBJ_SIGN[k] * net.C[k]
        if k != 2:   # lexicographic tie-break: among equally good solutions prefer shorter hauls
            c = c + 1e-5 * np.abs(c).max() * net.arc_km / net.arc_km.max()
        x = _solve(net, c)
        xs.append(x); F.append(to_min(objectives(net, x)))
    F = np.array(F)
    ideal = F.diagonal().copy()
    nadir = F.max(axis=0)
    nadir = np.where(nadir - ideal < 1e-9, ideal + 1.0, nadir)
    return ideal, nadir, xs


def normalise(fmin: np.ndarray, ideal: np.ndarray, nadir: np.ndarray) -> np.ndarray:
    return (fmin - ideal) / (nadir - ideal)


def weighted_sum(net: Network, w: np.ndarray, ideal: np.ndarray, nadir: np.ndarray) -> np.ndarray:
    c = ((w * OBJ_SIGN / (nadir - ideal))[:, None] * net.C).sum(axis=0)
    return _solve(net, c)


def economic_only(net: Network) -> np.ndarray:
    return _solve(net, -net.C[0])


def pareto_front_lp(net: Network, ideal, nadir, step: float = 0.1):
    """Enumerate weights on the 4-simplex; return unique non-dominated flow vectors."""
    n = int(round(1 / step))
    sols, seen = [], set()
    for a in range(n + 1):
        for b in range(n + 1 - a):
            for c in range(n + 1 - a - b):
                d = n - a - b - c
                w = np.array([a, b, c, d], float) / n
                if w.sum() == 0:
                    continue
                x = weighted_sum(net, w, ideal, nadir)
                key = tuple(np.round(objectives(net, x), 0))
                if key not in seen:
                    seen.add(key); sols.append(x)
    return sols


# ----------------------------- heuristic baselines -----------------------------

def nearest_feasible(net: Network) -> np.ndarray:
    """Global nearest-first: shortest arcs get filled first, limited by supply and receiver capacity."""
    x = np.zeros(len(net.arc_km))
    s_left = {k: b for k, b in zip(net.src_rows, net.b_src)}
    r_left = {k: b for k, b in zip(net.rec_rows, net.b_rec)}
    for a in np.argsort(net.arc_km, kind="stable"):
        li, s, r = net.arc_lane[a], net.arc_s[a], net.arc_r[a]
        q = min(s_left[(li, s)], r_left[(li, r)])
        if q > 0:
            x[a] = q; s_left[(li, s)] -= q; r_left[(li, r)] -= q
    return x


def rule_based(net: Network, radius_km: float = 600.0) -> np.ndarray:
    """Plain business rule: biggest sources first; send to the receiver with the most spare capacity within
    `radius_km`; if none in reach, fall back to the nearest receiver with capacity."""
    x = np.zeros(len(net.arc_km))
    s_left = {k: b for k, b in zip(net.src_rows, net.b_src)}
    r_left = {k: b for k, b in zip(net.rec_rows, net.b_rec)}
    by_src: dict = {}
    for a in range(len(x)):
        by_src.setdefault((net.arc_lane[a], net.arc_s[a]), []).append(a)
    for key in sorted(by_src, key=lambda k: -s_left[k]):
        li = key[0]
        while s_left[key] > 1e-9:
            cand = [a for a in by_src[key] if r_left[(li, net.arc_r[a])] > 1e-9]
            if not cand:
                break
            near = [a for a in cand if net.arc_km[a] <= radius_km]
            a = (max(near, key=lambda a: r_left[(li, net.arc_r[a])]) if near
                 else min(cand, key=lambda a: net.arc_km[a]))
            q = min(s_left[key], r_left[(li, net.arc_r[a])])
            x[a] += q; s_left[key] -= q; r_left[(li, net.arc_r[a])] -= q
    return x
