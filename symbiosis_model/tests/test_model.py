import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pytest
from core import model as M, solvers as S, run as R, forecast as F, data as D


@pytest.fixture(scope="module")
def net():
    return M.build("2024-25", "base")


def test_supply_matches_source_files(net):
    # steel slag total equals the CSV total; molasses total equals sum of state rows (mid)
    import pandas as pd
    slag = pd.read_csv(D.DATA / "steel_slag_estimate_by_state_2020_21.csv").steelmaking_slag_t_mid.sum()
    assert net.lanes[0].supply.sum() == pytest.approx(slag, rel=1e-9)
    df = D.load_sugar("2024-25")
    assert net.lanes[2].supply.sum() == pytest.approx(df.molasses_tonnes_mid.sum(), rel=1e-9)


def test_all_baselines_feasible(net):
    ideal, nadir, _ = S.payoff(net)
    w = S.DEFAULT_WEIGHTS / S.DEFAULT_WEIGHTS.sum()
    for x in (S.nearest_feasible(net), S.rule_based(net), S.economic_only(net), S.weighted_sum(net, w, ideal, nadir)):
        assert M.check_feasible(net, x)["ok"]


def test_economic_only_is_best_on_economics(net):
    xe = S.economic_only(net)
    for x in (S.nearest_feasible(net), S.rule_based(net)):
        assert M.objectives(net, xe)[0] >= M.objectives(net, x)[0] - 1e-3


def test_no_flow_without_supply_or_capacity(net):
    x = S.economic_only(net)
    for a in np.nonzero(x > 1e-6)[0]:
        l = net.lanes[net.arc_lane[a]]
        assert l.supply[net.arc_s[a]] > 0 and l.cap[net.arc_r[a]] > 0


def test_threshold_removes_lane():
    n = M.build("2024-25", "base", threshold=0.6)
    assert not n.lanes[0].eligible and set(n.arc_lane) == {1, 2}


def test_case_ordering_of_supply_and_utilisation():
    u = {c: R.summarize(M.build("2024-25", c), S.economic_only(M.build("2024-25", c)))["utilised_t"] for c in D.CASES}
    assert u["low"] <= u["base"] <= u["high"]


def test_rail_used_only_beyond_threshold(net):
    for km, mode in zip(net.arc_km, net.arc_mode):
        if mode == "rail":
            assert km >= net.params.get("rail_threshold_km")


def test_nsga_feasible_and_deterministic(net):
    ideal, nadir, _ = S.payoff(net)
    from core import nsga
    f1, F1 = nsga.run_nsga2(net, ideal, nadir, pop=30, gens=10, seed=3)
    f2, F2 = nsga.run_nsga2(net, ideal, nadir, pop=30, gens=10, seed=3)
    assert np.allclose(F1, F2)
    assert all(M.check_feasible(net, x)["ok"] for x in f1)


def test_forecast_refuses_short_history():
    assert F.forecast_series("crude_steel_national_mt")["status"] == "insufficient_history"


def test_forecast_backtest_harness_on_synthetic_trend():
    y = 100 + 5 * np.arange(20) + np.random.default_rng(0).normal(0, 1, 20)
    bt = F.backtest(y)
    assert bt.loc["drift", "mae_vs_naive"] < 1 and bt.loc["linear", "mae_vs_naive"] < 1
