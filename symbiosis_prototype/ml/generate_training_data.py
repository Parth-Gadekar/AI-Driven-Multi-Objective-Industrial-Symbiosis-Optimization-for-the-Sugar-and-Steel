"""
generate_training_data.py — builds a synthetic training set for the Random
Forest model.

There is no real historical exchange data yet, so this script generates many
(material, industry, quantity, distance) combinations across the compatible
pairs defined in data/materials.json, scores each one with the deterministic
rule engine (rules.py), and writes the result to training_data.csv.

This means the model is learning to approximate the rule engine's scoring
function from (material, industry, quantity, distance) alone — a legitimate
"train on simulated/labelled data" ML component for a prototype, but it is
NOT learning from real outcomes. Be upfront about this distinction if asked
at the review (it's also called out in the README).
"""

import json
import random
from pathlib import Path

import pandas as pd

import rules

random.seed(42)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_PATH = Path(__file__).resolve().parent / "training_data.csv"

SAMPLES_PER_PAIR = 60           # synthetic samples per (material, industry) pair
QUANTITY_RANGE_TONNES = (10, 2000)
DISTANCE_RANGE_KM = (5, 500)


def load_materials():
    with open(DATA_DIR / "materials.json") as f:
        payload = json.load(f)
    return payload["materials"]


def main():
    materials = load_materials()
    rows = []

    for m in materials:
        material_id = m["id"]
        for pair in m["compatible_industries"]:
            industry = pair["industry"]
            compat = pair["compatibility_score"]
            reuse_type = pair.get("reuse_type", "")

            for _ in range(SAMPLES_PER_PAIR):
                quantity = round(random.uniform(*QUANTITY_RANGE_TONNES), 1)
                distance = round(random.uniform(*DISTANCE_RANGE_KM), 1)

                breakdown = rules.compute_score(
                    material_id=material_id,
                    industry=industry,
                    compatibility_score=compat,
                    quantity=quantity,
                    distance_km=distance,
                    reuse_type=reuse_type,
                )

                rows.append(
                    {
                        "material_id": material_id,
                        "industry": industry,
                        "compatibility_score": compat,
                        "quantity_tonnes": quantity,
                        "distance_km": distance,
                        "economic_score": breakdown.economic_score,
                        "co2_score": breakdown.co2_score,
                        "utilization_score": breakdown.utilization_score,
                        "final_score": breakdown.final_score,
                    }
                )

    df = pd.DataFrame(rows)
    df.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(df)} synthetic training rows to {OUT_PATH}")
    print(df["final_score"].describe())


if __name__ == "__main__":
    main()
