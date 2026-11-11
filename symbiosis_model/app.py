"""Flask app for the Industrial Symbiosis optimiser (state-level, real datasets).

  GET  /                      UI
  GET  /api/meta              seasons, cases, lanes, parameter table, items not modelled
  GET  /api/result            precomputed scenario  (?season=2024-25&case=base)
  POST /api/run               run any scenario live (baselines + LP front + NSGA-II)
  GET  /api/sensitivity       one-at-a-time parameter sensitivity table
  GET  /api/forecast          forecast status for cane crushed and crude steel
  GET  /api/user/options      user mode: roles, by-products, states and priorities for the form
  GET  /api/user/advice       user mode: ranked destinations or sources for one plant
                              (?role=&material=&state=&tonnes=&season=&case=)
  GET  /api/pin/meta          pin-to-pin (Maharashtra pilot): materials, bounding box
  GET  /api/pin/analyse       pin-to-pin: one exporter and one importer location
                              (?material=&exp_lat=&exp_lon=&imp_lat=&imp_lon=&tonnes=&capacity=&road_km=)
"""
import json
from functools import lru_cache
from pathlib import Path
from flask import Flask, jsonify, render_template, request
from core import data as D, model as M, run as R, forecast as F, advise as A, pin as PIN

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
app = Flask(__name__)
app.json.sort_keys = False      # keep roles and priorities in the order the form should show them


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/meta")
def meta():
    P = D.Params.load()
    params = [{"parameter": k, "base": float(r.base), "low": float(r.low), "high": float(r.high), "unit": r.unit,
               "status": r.status, "basis": r.basis} for k, r in P.table.iterrows()]
    net = M.build("2024-25", "base")
    return jsonify({"seasons": D.SEASONS, "cases": D.CASES, "params": params, "methods": R.METHODS, "labels": R.LABELS,
                    "lanes": [{"lane_id": l.lane_id, "material": l.material, "receiver": l.receiver, "compat": round(l.compat, 3)}
                              for l in net.lanes],
                    "not_modelled": net.not_modelled,
                    "steel_scale_2024_25": round(D.steel_scale_2024_25(), 3)})


@app.route("/api/result")
def result():
    season, case = request.args.get("season", "2024-25"), request.args.get("case", "base")
    p = RESULTS / f"{season}_{case}.json"
    if not p.exists():
        return jsonify({"error": "no precomputed result; use /api/run"}), 404
    return app.response_class(p.read_text(), mimetype="application/json")


@lru_cache(maxsize=64)
def _run_cached(key: str):
    kw = json.loads(key)
    return R.run_scenario(**kw)


@app.route("/api/run", methods=["POST"])
def run():
    b = request.get_json(force=True, silent=True) or {}
    try:
        season, case, cost_case = b.get("season", "2024-25"), b.get("case", "base"), b.get("cost_case", "base")
        steel_year = b.get("steel_year", "2020-21")
        if season not in D.SEASONS or case not in D.CASES or cost_case not in D.CASES or steel_year not in ("2020-21", "2024-25"):
            raise ValueError("bad season/case/cost_case/steel_year")
        thr = b.get("threshold")
        thr = None if thr is None else float(thr)
        w = b.get("weights")
        if w is not None:
            w = [float(w[k]) for k in ("economic", "utilisation", "transport_work", "co2")]
            if min(w) < 0 or sum(w) <= 0:
                raise ValueError("weights must be >= 0 and not all zero")
        do_nsga = bool(b.get("nsga", True))
        pop, gens = int(min(max(b.get("pop", 100), 20), 200)), int(min(max(b.get("gens", 100), 10), 300))
    except (ValueError, TypeError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    key = json.dumps({"season": season, "case": case, "cost_case": cost_case, "steel_year": steel_year, "threshold": thr,
                      "weights": w, "nsga_pop": pop, "nsga_gens": gens, "do_nsga": do_nsga}, sort_keys=True)
    return jsonify(_run_cached(key))


@app.route("/api/sensitivity")
def sensitivity():
    p = RESULTS / "sensitivity_one_at_a_time.csv"
    if not p.exists():
        return jsonify([])
    import pandas as pd
    return jsonify(pd.read_csv(p).to_dict("records"))


@app.route("/api/user/options")
def user_options():
    return jsonify(A.options())


@app.route("/api/user/advice")
def user_advice():
    a = request.args
    try:
        tonnes = a.get("tonnes")
        tonnes = float(tonnes) if tonnes not in (None, "") else None
        res = A.advise(role=a.get("role", ""), state=a.get("state", ""), material=a.get("material") or None,
                       tonnes=tonnes,
                       season=a.get("season", "2024-25"), case=a.get("case", "base"))
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(res)


@app.route("/api/pin/meta")
def pin_meta():
    return jsonify(PIN.meta())


@app.route("/api/pin/analyse")
def pin_analyse():
    a = request.args
    try:
        num = lambda k: float(a[k]) if a.get(k) not in (None, "") else None
        res = PIN.analyse(a.get("material", ""), (num("exp_lat"), num("exp_lon")), (num("imp_lat"), num("imp_lon")),
                          tonnes=num("tonnes"), importer_capacity_t=num("capacity"), road_km=num("road_km"),
                          season=a.get("season", "2024-25"), case=a.get("case", "base"))
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(res)


@app.route("/api/forecast")
def forecast():
    return jsonify([F.forecast_series("cane_crushed_national_mt"), F.forecast_series("crude_steel_national_mt")])


if __name__ == "__main__":
    A._plan("2024-25", "base")      # warm the default combined plan so the first user request is fast
    app.run(debug=False, port=5000)
