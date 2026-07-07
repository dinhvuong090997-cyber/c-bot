"""Tests cho backtest.engine.evaluate_maker — tổng hợp kết quả simulate_trades
theo confidence threshold: fill_rate, win_rate, breakdown exit type."""
import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestConfig, evaluate_maker

MS_PER_DAY = 86_400_000


def make_trades():
    """4 tín hiệu: 2 khớp-hoàn-chỉnh (1 tp thắng, 1 sl thua), 1 miss,
    1 khớp nhưng incomplete."""
    return pd.DataFrame({
        "confidence": [0.60, 0.42, 0.60, 0.60],
        "filled":     [True, True, False, True],
        "complete":   [True, True, True, False],
        "exit_type":  ["tp", "sl", None, None],
        "net_ret":    [0.008, -0.011, np.nan, np.nan],
        "t_exit":     [MS_PER_DAY, MS_PER_DAY * 3, -1, -1],
    })


def test_threshold_filters_and_fill_rate():
    cfg = BacktestConfig(conf_thresholds=(0.0, 0.5))
    out = evaluate_maker(make_trades(), cfg).set_index("threshold")
    # th=0.0: 4 tín hiệu, 3 khớp (kể cả incomplete), 2 trade dùng được
    assert out.loc[0.0, "n_signals"] == 4
    assert out.loc[0.0, "fill_rate"] == pytest.approx(3 / 4)
    assert out.loc[0.0, "n_trades"] == 2
    # th=0.5: loại tín hiệu conf 0.42 (trade sl) -> còn 1 trade tp
    assert out.loc[0.5, "n_signals"] == 3
    assert out.loc[0.5, "n_trades"] == 1
    assert out.loc[0.5, "win_rate"] == pytest.approx(1.0)


def test_metrics_and_exit_breakdown():
    cfg = BacktestConfig(conf_thresholds=(0.0,))
    row = evaluate_maker(make_trades(), cfg).iloc[0]
    assert row["mean_net_ret"] == pytest.approx((0.008 - 0.011) / 2)
    assert row["win_rate"] == pytest.approx(0.5)
    assert row["n_tp"] == 1 and row["n_sl"] == 1 and row["n_vertical"] == 0
    assert row["total_return"] == pytest.approx(np.exp(0.008 - 0.011) - 1)


def test_empty_threshold_row_is_nan_not_crash():
    cfg = BacktestConfig(conf_thresholds=(0.99,))
    row = evaluate_maker(make_trades(), cfg).iloc[0]
    assert row["n_trades"] == 0
    assert np.isnan(row["win_rate"])
