"""Precompute scenario results (JSON) and a one-at-a-time parameter sensitivity table.
Run from symbiosis_model/:  python scripts/precompute.py [--quick]
"""
import json, sys, copy
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
from core import data as D, model as M, solvers as S, run as R

quick = "--quick" in sys.argv
pop, gens = (60, 40) if quick else (150, 300)
out = ROOT / "results"; out.mkdir(exist_ok=True)

for season in D.SEASONS:
    for case in D.CASES:
        r = R.run_scenario(season, case, nsga_pop=pop, nsga_gens=gens)
        (out / f"{season}_{case}.json").write_text(json.dumps(r))
        print(season, case, "hv/LP", round(r["nsga2"]["hv_ratio_vs_lp"], 3), r["runtime_s"], "s", flush=True)

# ---- one-at-a-time sensitivity on the weighted-sum solution (base scenario) ----
P0 = D.Params.load()
base = R.summarize(*(lambda n: (n, S.weighted_sum(n, S.DEFAULT_WEIGHTS / S.DEFAULT_WEIGHTS.sum(), *S.payoff(n)[:2])))(M.build("2024-25", "base", params=P0)))
rows = []
for name in P0.table.index:
    lo, hi = float(P0.table.loc[name, "low"]), float(P0.table.loc[name, "high"])
    if lo == hi or name in ("steel_scale_2024_25", "compat_threshold"):
        continue
    for tag, v in (("low", lo), ("high", hi)):
        P = D.Params(P0.table.copy()); P.table.loc[name, "base"] = v
        n = M.build("2024-25", "base", params=P)
        i, nd, _ = S.payoff(n)
        s = R.summarize(n, S.weighted_sum(n, S.DEFAULT_WEIGHTS / S.DEFAULT_WEIGHTS.sum(), i, nd))
        rows.append({"parameter": name, "status": P0.status(name), "setting": tag, "value": v,
                     "utilised_pct": s["utilised_pct_of_supply"], "net_benefit_inr": s["net_benefit_inr"],
                     "net_co2_t": s["net_co2_t"], "mean_haul_km": s["mean_haul_km"],
                     "d_util_pct": s["utilised_pct_of_supply"] - base["utilised_pct_of_supply"],
                     "d_benefit_inr": s["net_benefit_inr"] - base["net_benefit_inr"],
                     "d_co2_t": s["net_co2_t"] - base["net_co2_t"]})
import pandas as pd
df = pd.DataFrame(rows)
df.to_csv(out / "sensitivity_one_at_a_time.csv", index=False)
(out / "sensitivity_base.json").write_text(json.dumps(base))
print(df.assign(spread=df.d_util_pct.abs()).sort_values("spread", ascending=False).head(8)[["parameter", "setting", "d_util_pct", "d_benefit_inr", "d_co2_t"]].to_string())
