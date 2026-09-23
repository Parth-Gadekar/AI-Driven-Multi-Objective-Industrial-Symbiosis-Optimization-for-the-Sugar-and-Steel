"""
train_model.py — trains a Random Forest to approximate the rule engine's
final_score from (material_id, industry, compatibility_score, quantity,
distance), and saves it (plus the label encoders) with joblib so app.py can
load it at request time without retraining.

Swap-in for XGBoost (per the synopsis's "XGBoost / Random Forest" line):
    pip install xgboost
    from xgboost import XGBRegressor
    model = XGBRegressor(n_estimators=200, max_depth=5, random_state=42)
Everything else below (feature encoding, save/load, Flask integration) stays
the same, since XGBoost follows the same scikit-learn-style API.
"""

from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

DATA_PATH = Path(__file__).resolve().parent / "training_data.csv"
MODEL_PATH = Path(__file__).resolve().parent / "model.joblib"

FEATURE_COLUMNS = [
    "material_id_enc",
    "industry_enc",
    "compatibility_score",
    "quantity_tonnes",
    "distance_km",
]
TARGET_COLUMN = "final_score"


def main():
    df = pd.read_csv(DATA_PATH)

    material_encoder = LabelEncoder()
    industry_encoder = LabelEncoder()
    df["material_id_enc"] = material_encoder.fit_transform(df["material_id"])
    df["industry_enc"] = industry_encoder.fit_transform(df["industry"])

    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = RandomForestRegressor(
        n_estimators=200,
        max_depth=8,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)
    print(f"Held-out test MAE: {mae:.4f}")
    print(f"Held-out test R^2: {r2:.4f}")

    joblib.dump(
        {
            "model": model,
            "material_encoder": material_encoder,
            "industry_encoder": industry_encoder,
            "feature_columns": FEATURE_COLUMNS,
        },
        MODEL_PATH,
    )
    print(f"Saved model + encoders to {MODEL_PATH}")


if __name__ == "__main__":
    main()
