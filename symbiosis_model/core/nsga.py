"""NSGA-II over the exchange network (pymoo).

Encoding (every candidate is feasible by construction, so no constraint handling is needed).
For each (lane, source) row i the chromosome holds three genes in [0, 1]:
    u_i    fraction of the source's supply to place
    p_i    priority key; sources with higher p claim receiver capacity first
    rho_i  reach; maximum haul radius = 50 km + (R_max - 50 km) * rho_i^2
The decoder fills receivers nearest-first within the radius until the placed tonnes are used up or
the capacity of reachable receivers is exhausted (remaining tonnes stay unplaced).
"""
from __future__ import annotations
import numpy as np
from pymoo.core.problem import Problem
from pymoo.core.sampling import Sampling
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.optimize import minimize
from .model import Network, objectives, to_min

G = 3  # genes per source row


class _Decoder:
    def __init__(self, net: Network):
        self.net = net
        self.rows = net.src_rows
        self.supply = net.b_src
        self.rec_cap = {k: b for k, b in zip(net.rec_rows, net.b_rec)}
        self.rmax = float(net.arc_km.max())
        self.arcs = []
        for (li, s) in self.rows:
            idx = np.nonzero((net.arc_lane == li) & (net.arc_s == s))[0]
            self.arcs.append(idx[np.argsort(net.arc_km[idx], kind="stable")])
        self.n_var = len(self.rows) * G

    def decode(self, z: np.ndarray) -> np.ndarray:
        net = self.net
        x = np.zeros(len(net.arc_km))
        left = dict(self.rec_cap)
        z = z.reshape(len(self.rows), G)
        for i in np.argsort(-z[:, 1], kind="stable"):
            amt = z[i, 0] * self.supply[i]
            if amt <= 0:
                continue
            radius = 50.0 + (self.rmax - 50.0) * z[i, 2] ** 2
            li = self.rows[i][0]
            for a in self.arcs[i]:
                if net.arc_km[a] > radius or amt <= 1e-9:
                    break
                r = (li, net.arc_r[a])
                q = min(amt, left[r])
                if q > 0:
                    x[a] += q; left[r] -= q; amt -= q
        return x


class _Sampling(Sampling):
    """Biased start: most sources place most of their supply (u near 1); reach is spread across the range."""
    def __init__(self, n_rows, seed=1):
        super().__init__(); self.n_rows, self.seed = n_rows, seed

    def _do(self, problem, n_samples, **kwargs):
        rng = np.random.default_rng(self.seed)
        X = rng.random((n_samples, self.n_rows, G))
        mix = rng.random((n_samples, 1))
        X[:, :, 0] = np.clip(X[:, :, 0] * (1 - mix) + mix * (1 - 0.15 * rng.random((n_samples, self.n_rows))), 0, 1)
        return X.reshape(n_samples, -1)


class _Prob(Problem):
    def __init__(self, dec: _Decoder, ideal, nadir):
        super().__init__(n_var=dec.n_var, n_obj=4, xl=0.0, xu=1.0)
        self.dec, self.ideal, self.nadir = dec, ideal, nadir

    def _evaluate(self, X, out, *a, **k):
        F = np.empty((len(X), 4))
        for j, z in enumerate(X):
            F[j] = (to_min(objectives(self.dec.net, self.dec.decode(z))) - self.ideal) / (self.nadir - self.ideal)
        out["F"] = F


def run_nsga2(net: Network, ideal, nadir, pop: int = 120, gens: int = 150, seed: int = 1):
    """Returns (list of flow vectors, normalised objective matrix). Deterministic for a given seed."""
    dec = _Decoder(net)
    prob = _Prob(dec, ideal, nadir)
    algo = NSGA2(pop_size=pop, sampling=_Sampling(len(dec.rows), seed), crossover=SBX(prob=0.9, eta=15),
                 mutation=PM(eta=20), eliminate_duplicates=True)
    res = minimize(prob, algo, ("n_gen", gens), seed=seed, verbose=False)
    X = np.atleast_2d(res.X)
    return [dec.decode(z) for z in X], np.atleast_2d(res.F)
