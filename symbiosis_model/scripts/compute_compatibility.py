"""Step 1 - rule-based compatibility scoring for industrial symbiosis lanes.
Score = weighted sum of 4 criteria in [0,1], behind hard feasibility gates.
Weights from AHP (consistency-checked) with Dirichlet sensitivity.
Inputs read from material_properties_compatibility_inputs.csv where numeric.
Run: python3 -I compatibility.py <props_csv> <outdir>
"""
import sys, csv, json
import numpy as np

props_csv, outdir = sys.argv[1], sys.argv[2]

# ---------- helpers ----------
def rng(s):
    a, b = s.replace('~', '').split('-')
    return float(a), float(b)

def trap(x, zero_lo, one_lo, one_hi, zero_hi):
    """Trapezoid membership: 0 below zero_lo, 1 on [one_lo, one_hi], 0 above zero_hi."""
    if x <= zero_lo or x >= zero_hi: return 0.0
    if x < one_lo: return (x - zero_lo) / (one_lo - zero_lo)
    if x <= one_hi: return 1.0
    return (zero_hi - x) / (zero_hi - one_hi)

# ---------- read measured property ranges ----------
P = {}
with open(props_csv, newline='', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        P[(r['material'], r['property'])] = r['value']
ld_cao, ld_sio2, ld_mgo = (rng(P[('BOF/LD steel slag', k)]) for k in ('CaO', 'SiO2', 'MgO'))
eaf_cao, eaf_sio2 = rng(P[('EAF steel slag', 'CaO')]), rng(P[('EAF steel slag', 'SiO2')])
bf_cao, bf_sio2 = rng(P[('Blast furnace slag', 'CaO')]), rng(P[('Blast furnace slag', 'SiO2')])
pm_oc, pm_n = rng(P[('Press mud', 'Organic carbon')]), rng(P[('Press mud', 'Nitrogen')])
ba_sio2 = float(P[('Bagasse fly ash', 'SiO2')].replace('~', ''))

# ---------- numeric chemical-fit indicators (lo, mid, hi) ----------
def basicity_fit(cao, sio2):
    """CaO/SiO2 basicity vs a hydraulic-slag window (analyst threshold; verify vs IS 12089)."""
    vals = []
    for c, s in ((cao[0], sio2[1]), (np.mean(cao), np.mean(sio2)), (cao[1], sio2[0])):
        vals.append(trap(c / s, 0.5, 0.9, 1.4, 3.0))
    return sorted(vals)

def rawfeed_fit(cao, mgo=None):
    """Raw-meal CaO source: CaO >=45 ideal (limestone ~56% CaO); MgO capped (clinker MgO limit ~6%, IS 269; verify)."""
    f = []
    for c in (cao[0], np.mean(cao), cao[1]):
        v = trap(c, 25, 45, 100, 101)
        f.append(v)
    f = sorted(f)
    if mgo:
        m = sorted(trap(x, 0, 0, 3, 10) for x in (mgo[0], np.mean(mgo), mgo[1]))
        m = [m[0], m[1], m[2]]
        f = [(a + b) / 2 for a, b in zip(f, sorted(m))]
    return f

def poz_fit(sio2):
    v = trap(sio2, 35, 60, 100, 101)
    return [v, v, v]

def compost_fit():
    # approx FCO minimums: organic C >=14 %, N >=0.8 % (verify against FCO schedule)
    oc = sorted(trap(x, 8, 14, 100, 101) for x in (pm_oc[0], np.mean(pm_oc), pm_oc[1]))
    n = sorted(trap(x, 0.4, 0.8, 10, 11) for x in (pm_n[0], np.mean(pm_n), pm_n[1]))
    return [(a + b) / 2 for a, b in zip(oc, n)]

# ---------- lanes: (id, material, receiver, use, chem_fit(lo,mid,hi), standards, processing, evidence, notes) ----------
# standards   : 1 = Indian standard explicitly covers this use; 0.5 = adjacent standard/pilot; 0.3 = no standard, case-by-case
# processing  : 1 = use as-is; 0.8 = grind/granulate (routine); 0.5 = ageing/treatment/quality control needed; 0.3 = substantial
# evidence    : 1 = Indian primary data; 0.7 = published range + standard; 0.5 = secondary/global range; 0.3 = single figure
L = [
 ("BF_PSC",  "Blast furnace slag (granulated)", "Cement", "Portland slag cement blending",
   [1.0,1.0,1.0] if False else basicity_fit(bf_cao, bf_sio2), 1.0, 0.8, 0.7,
   "IS 455 allows 25-70% granulated slag. Supply already >90% absorbed (P14) so spare volume is small."),
 ("LD_RAW",  "BOF/LD steel slag", "Cement", "Clinker raw-meal CaO source",
   rawfeed_fit(ld_cao, ld_mgo), 0.3, 0.5, 0.5,
   "CaO good, but MgO 3-13% and FeO 7-20% limit substitution; free CaO/MgO need ageing. No IS route for bulk use."),
 ("LD_SCM",  "BOF/LD steel slag", "Cement", "Cementitious additive in blended cement",
   basicity_fit(ld_cao, ld_sio2), 0.3, 0.5, 0.5,
   "Basicity far above hydraulic-slag window; volume instability. Not covered by IS 455 (granulated BF slag only)."),
 ("EAF_RAW", "EAF steel slag", "Cement", "Clinker raw-meal CaO source",
   rawfeed_fit(eaf_cao), 0.3, 0.5, 0.5,
   "CaO 30-50% only partly meets the raw-meal window; MgO and FeO not in the properties file (data gap)."),
 ("EAF_SCM", "EAF steel slag", "Cement", "Cementitious additive in blended cement",
   basicity_fit(eaf_cao, eaf_sio2), 0.3, 0.5, 0.5,
   "Basicity above hydraulic window; no standard route."),
 ("BA_POZ",  "Bagasse fly ash", "Cement", "Pozzolanic cement replacement",
   poz_fit(ba_sio2), 0.5, 0.5, 0.3,
   "One reported SiO2 (~65%) only. Unburnt carbon / LOI varies by boiler; needs plant sample. Al2O3, Fe2O3, LOI missing."),
 ("MOL_DIST","Molasses", "Distillery", "Ethanol feedstock",
   [1.0,1.0,1.0], 1.0, 1.0, 0.6,
   "Established route. Yields (220-225 and 290-320 L/t) come from secondary sources. Capacity limit handled by offtake share P01."),
 ("PM_COMP", "Press mud", "Compost / organic manure", "Compost or manure feedstock",
   compost_fit(), 0.7, 0.8, 0.6,
   "Nutrient ranges clear approx FCO minimums (verify). Receiver demand data NOT collected, so lane is score-only for now."),
]

# hard gates: pairs that must score 0 regardless of weights
GATES = [
 ("Molasses", "Cement", "No technical route"),
 ("Press mud", "Steel plant", "Sugar by-products do not go directly to steel plants (project context file)"),
 ("Bagasse fly ash", "Steel plant", "Sugar by-products do not go directly to steel plants (project context file)"),
 ("Molasses", "Steel plant", "Sugar by-products do not go directly to steel plants (project context file)"),
 ("BOF/LD steel slag", "Distillery", "No technical route"),
]

# ---------- AHP weights ----------
crit = ["chemical_fit", "standards_acceptance", "processing_readiness", "evidence_strength"]
A = np.array([[1, 2, 3, 3],
              [1/2, 1, 2, 2],
              [1/3, 1/2, 1, 1],
              [1/3, 1/2, 1, 1]], float)
vals, vecs = np.linalg.eig(A)
k = np.argmax(vals.real)
w = np.abs(vecs[:, k].real); w /= w.sum()
lam = vals[k].real; n = len(A)
CI = (lam - n) / (n - 1); CR = CI / 0.90   # Saaty RI(n=4)=0.90

# ---------- scoring ----------
rows = []
rs = np.random.default_rng(42)
W = rs.dirichlet(w * 40, 5000)                    # weight uncertainty
for (lid, mat, rec, use, fit, std, proc, ev, note) in L:
    lo, mid, hi = fit
    crit_mid = np.array([mid, std, proc, ev])
    score = float(w @ crit_mid)
    s_lo = float(w @ np.array([lo, std, proc, ev]))
    s_hi = float(w @ np.array([hi, std, proc, ev]))
    sims = W @ crit_mid
    tier = "high" if score >= 0.75 else ("conditional" if score >= 0.50 else "low")
    rows.append(dict(lane_id=lid, material=mat, receiver=rec, use_route=use,
        chemical_fit_lo=round(lo,3), chemical_fit_mid=round(mid,3), chemical_fit_hi=round(hi,3),
        standards_acceptance=std, processing_readiness=proc, evidence_strength=ev,
        score_base=round(score,3), score_composition_lo=round(s_lo,3), score_composition_hi=round(s_hi,3),
        score_weights_p5=round(float(np.percentile(sims,5)),3), score_weights_p95=round(float(np.percentile(sims,95)),3),
        tier=tier, eligible_threshold_0_50=int(score >= 0.50), notes=note))
rows.sort(key=lambda r: -r["score_base"])

# rank stability under weight uncertainty
scores_sim = np.array([[W[i] @ np.array([r_fit[1], r_std, r_proc, r_ev]) for (_, _, _, _, r_fit, r_std, r_proc, r_ev, _) in L] for i in range(2000)])
ids = [l[0] for l in L]
order = np.argsort(-scores_sim, axis=1)
top = {ids[j]: float(np.mean(order[:, 0] == j)) for j in range(len(ids))}

import os
os.makedirs(outdir, exist_ok=True)
with open(f"{outdir}/compatibility_scores.csv", "w", newline="", encoding="utf-8") as f:
    wr = csv.DictWriter(f, fieldnames=list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
with open(f"{outdir}/compatibility_gates.csv", "w", newline="", encoding="utf-8") as f:
    wr = csv.writer(f); wr.writerow(["material", "receiver_type", "score", "reason"])
    for m, r, why in GATES: wr.writerow([m, r, 0, why])
with open(f"{outdir}/compatibility_weights.csv", "w", newline="", encoding="utf-8") as f:
    wr = csv.writer(f); wr.writerow(["criterion", "ahp_weight"])
    for c, x in zip(crit, w): wr.writerow([c, round(float(x), 4)])
    wr.writerow(["lambda_max", round(lam, 4)]); wr.writerow(["consistency_ratio", round(CR, 4)])
print("weights", dict(zip(crit, np.round(w, 3))), "CR", round(CR, 3))
for r in rows:
    print(f"{r['lane_id']:9s} {r['score_base']:.3f}  comp[{r['score_composition_lo']:.2f},{r['score_composition_hi']:.2f}] w[{r['score_weights_p5']:.2f},{r['score_weights_p95']:.2f}] fit mid {r['chemical_fit_mid']:.2f} {r['tier']}")
print("P(top rank) under weight sampling", {k: round(v, 2) for k, v in top.items() if v > 0})
