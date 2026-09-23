# Industrial Symbiosis Recommendation System — Prototype

A small, working demo for the mid-semester review. Given a waste material and
quantity, it recommends which industries could reuse it, ranked by
compatibility, estimated profitability, CO2 impact, and utilization —
combining a rule-based scoring engine with a trained Random Forest model.

**This is a scoped-down demo, not the final system.** It uses Flask + plain
HTML/JS/Chart.js instead of the full React/Node/MySQL stack from the
synopsis, and a synthetic training set instead of real historical exchange
data. See "What's simplified for this prototype" below before the review.

## Setup

```bash
cd symbiosis_prototype
pip install -r requirements.txt

# (already done once, but if you edit rules.py or materials.json, redo this)
cd ml
python generate_training_data.py
python train_model.py
cd ..

python app.py
```

Then open **http://localhost:5000** in a browser.

## How it works

1. `data/materials.json` — the dataset: 9 materials across sugar, steel, and
   thermal power (fly ash, which connects to cement), each with the
   industries that could plausibly reuse them and a literature-informed
   compatibility score.
2. `ml/rules.py` — the scoring formulas (economic benefit, CO2 avoided,
   utilization). All unit values (₹/tonne, kg CO2/tonne-km, etc.) are
   **placeholder assumptions**, documented inline in that file.
3. `ml/generate_training_data.py` + `ml/train_model.py` — since there's no
   real historical exchange data yet, these generate many synthetic
   (material, industry, quantity, distance) combinations, score them with
   the rules above, and train a Random Forest to approximate/generalize that
   scoring function. This is a legitimate AI/ML component for a prototype,
   but it's learning from rule-derived labels, not real outcomes — be
   upfront about this if asked at the review.
4. `app.py` — Flask API (`/api/materials`, `/api/recommend`) that ties it
   together and serves the frontend.
5. `templates/` + `static/` — the form + results + Chart.js visualization.

## What's simplified for this prototype (and what changes for finals)

- **Stack**: Flask + vanilla JS here, vs. React/Node/Express/MySQL in the
  synopsis. The underlying logic (rules.py, the model, the API shape) can be
  lifted almost as-is into a Node backend calling this same Flask model via
  HTTP, and the same `/api/recommend` response shape can drive a React
  frontend instead of this one.
- **Data**: 9 materials, hand-compiled from literature discussed in chat, not
  a real materials database.
- **Distance**: user enters it manually; no real GIS/geocoding yet.
- **Training data**: synthetic, derived from the rule engine, not from real
  exchange outcomes (none exist yet).
- **Optimization**: this is a weighted-sum ranking, not full multi-objective
  optimization (e.g. NSGA-II / Pareto fronts) — that's flagged as a future
  step in the original project context file, planned for before the final
  review.

## Swapping Random Forest for XGBoost

The synopsis lists both. On a machine with internet access:
```bash
pip install xgboost
```
Then in `ml/train_model.py`, replace the `RandomForestRegressor` import and
instantiation with `from xgboost import XGBRegressor` /
`XGBRegressor(n_estimators=200, max_depth=5, random_state=42)`. Everything
else (feature encoding, save/load, the Flask integration) stays the same
since XGBoost follows the same scikit-learn-style API.
