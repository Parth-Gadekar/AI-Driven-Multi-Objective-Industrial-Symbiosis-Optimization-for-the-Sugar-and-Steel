"""
app.py — Flask API + frontend server for the Industrial Symbiosis
Recommendation System prototype.

Routes:
  GET  /                    -> serves the demo UI
  GET  /api/materials       -> list of materials (id, name, source industry)
  POST /api/recommend       -> given {material_id, quantity_tonnes, distance_km},
                                returns ranked recommendations across that
                                material's compatible industries, each with a
                                full explainable score breakdown plus the
                                ML model's own prediction for comparison.

This stands in for the synopsis's Node/Express + Python ML-via-Flask split:
in the full stack, an Express `/recommend` endpoint would call this Flask
`/api/recommend` internally instead of a browser calling it directly.
"""

import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from flask import Flask, jsonify, render_template, request

sys.path.insert(0, str(Path(__file__).resolve().parent / "ml"))
import rules  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "materials.json"
MODEL_PATH = BASE_DIR / "ml" / "model.joblib"

app = Flask(__name__)

with open(DATA_PATH) as f:
    MATERIALS = json.load(f)["materials"]
MATERIALS_BY_ID = {m["id"]: m for m in MATERIALS}

_model_bundle = None
if MODEL_PATH.exists():
    _model_bundle = joblib.load(MODEL_PATH)


def ml_predict(material_id: str, industry: str, compatibility_score: float,
                quantity: float, distance: float):
    """Returns the RF model's predicted final_score, or None if untrained/unseen."""
    if _model_bundle is None:
        return None
    try:
        material_enc = _model_bundle["material_encoder"].transform([material_id])[0]
        industry_enc = _model_bundle["industry_encoder"].transform([industry])[0]
    except ValueError:
        # Model has never seen this material/industry label (e.g. added to
        # materials.json after the model was last trained).
        return None

    row = pd.DataFrame(
        [[material_enc, industry_enc, compatibility_score, quantity, distance]],
        columns=_model_bundle["feature_columns"],
    )
    pred = _model_bundle["model"].predict(row)[0]
    return round(float(pred), 4)


@app.route("/")
def index():
    return render_template("index.html", materials=MATERIALS)


@app.route("/api/materials")
def api_materials():
    return jsonify(
        [
            {
                "id": m["id"],
                "name": m["name"],
                "source_industry": m["source_industry"],
                "description": m["description"],
                "typical_ratio": m["typical_ratio"],
            }
            for m in MATERIALS
        ]
    )


@app.route("/api/recommend", methods=["POST"])
def api_recommend():
    payload = request.get_json(force=True, silent=True) or {}

    material_id = payload.get("material_id")
    quantity = payload.get("quantity_tonnes")
    distance = payload.get("distance_km")

    if material_id not in MATERIALS_BY_ID:
        return jsonify({"error": f"Unknown material_id '{material_id}'"}), 400
    try:
        quantity = float(quantity)
        distance = float(distance)
        if quantity <= 0 or distance < 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "quantity_tonnes must be > 0 and distance_km must be >= 0"}), 400

    material = MATERIALS_BY_ID[material_id]
    results = []

    for pair in material["compatible_industries"]:
        industry = pair["industry"]
        compat = pair["compatibility_score"]
        reuse_type = pair.get("reuse_type", "")

        breakdown = rules.compute_score(
            material_id=material_id,
            industry=industry,
            compatibility_score=compat,
            quantity=quantity,
            distance_km=distance,
            reuse_type=reuse_type,
        )
        result = breakdown.to_dict()
        result["ml_predicted_score"] = ml_predict(
            material_id, industry, compat, quantity, distance
        )
        results.append(result)

    results.sort(key=lambda r: r["final_score"], reverse=True)
    for rank, r in enumerate(results, start=1):
        r["rank"] = rank

    return jsonify(
        {
            "material": {
                "id": material["id"],
                "name": material["name"],
                "source_industry": material["source_industry"],
            },
            "quantity_tonnes": quantity,
            "distance_km": distance,
            "weights": rules.DEFAULT_WEIGHTS,
            "recommendations": results,
            "model_loaded": _model_bundle is not None,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
