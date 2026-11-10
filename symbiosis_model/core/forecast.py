"""Forecasting with a rolling-origin backtest against a naive baseline.

Only cane crushed and crude steel are forecast (by-products are cane x ratio, so they are never
predicted directly). Models: naive (last value), drift, Holt linear exponential smoothing,
and OLS linear trend. A model is only reported if it beats naive on the backtest; with fewer than
MIN_POINTS observations the module returns status "insufficient_history" instead of numbers.

Input: data/history_<series>.csv with columns year,value (one row per season, numeric year = season start).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
MIN_POINTS = 10          # need enough points for >= 3 backtest origins after a 6-point warm-up


def naive(y, h):  return np.full(h, y[-1])
def drift(y, h):
    slope = (y[-1] - y[0]) / (len(y) - 1)
    return y[-1] + slope * np.arange(1, h + 1)
def linear(y, h):
    t = np.arange(len(y)); b, a = np.polyfit(t, y, 1)
    return a + b * np.arange(len(y), len(y) + h)
def holt(y, h, alpha=0.5, beta=0.2):
    l, b = y[0], y[1] - y[0]
    for v in y[1:]:
        l_new = alpha * v + (1 - alpha) * (l + b)
        b = beta * (l_new - l) + (1 - beta) * b
        l = l_new
    return l + b * np.arange(1, h + 1)

MODELS = {"naive": naive, "drift": drift, "linear": linear, "holt": holt}


def backtest(y: np.ndarray, horizon: int = 1, warmup: int = 6) -> pd.DataFrame:
    """Rolling-origin: fit on y[:t], forecast y[t+horizon-1]. Returns MAE and MASE-style ratio vs naive."""
    errs = {m: [] for m in MODELS}
    for t in range(warmup, len(y) - horizon + 1):
        actual = y[t + horizon - 1]
        for m, f in MODELS.items():
            errs[m].append(abs(f(y[:t], horizon)[-1] - actual))
    mae = {m: float(np.mean(e)) for m, e in errs.items()}
    return pd.DataFrame({"mae": mae, "mae_vs_naive": {m: mae[m] / mae["naive"] for m in mae}, "n_origins": len(errs["naive"])})


def forecast_series(name: str, horizon: int = 2) -> dict:
    p = DATA / f"history_{name}.csv"
    if not p.exists():
        return {"series": name, "status": "no_history_file"}
    df = pd.read_csv(p).dropna(subset=["value"]).sort_values("year")
    y = df.value.to_numpy(float)
    if len(y) < MIN_POINTS:
        return {"series": name, "status": "insufficient_history", "n_points": int(len(y)), "needed": MIN_POINTS}
    bt = backtest(y)
    best = bt["mae_vs_naive"].drop("naive").idxmin()
    ok = bool(bt.loc[best, "mae_vs_naive"] < 1.0)
    use = best if ok else "naive"
    fc = MODELS[use](y, horizon)
    return {"series": name, "status": "ok", "n_points": int(len(y)), "backtest": bt.round(4).to_dict(), "model_used": use,
            "beats_naive": ok, "last_year": int(df.year.iloc[-1]), "forecast": [float(v) for v in fc]}
