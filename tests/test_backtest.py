"""Tests cho backtest/engine.py — lọc lệnh theo confidence, trừ phí,
Sharpe/drawdown/turnover.
"""
import numpy as np
import pytest

from backtest.engine import (
    BacktestConfig, select_trades, net_returns, equity_curve,
    max_drawdown, sharpe_ratio, evaluate_thresholds,
)

DAY = 86_400_000


class TestSelectTrades:
    def test_drops_neutral_predictions(self):
        pred = np.array([0, 1, 2, 1])
        prob = np.array([0.9, 0.9, 0.9, 0.9])
        ret = np.array([0.01, 0.01, 0.01, 0.01])
        t = np.arange(4) * DAY
        sel = select_trades(pred, prob, ret, t, conf_threshold=0.0)
        assert len(sel["gross_ret"]) == 2  # bỏ 2 event pred==1 (ngang)

    def test_filters_by_confidence(self):
        pred = np.array([0, 2, 2])
        prob = np.array([0.3, 0.5, 0.9])
        ret = np.array([0.01, 0.01, 0.01])
        t = np.arange(3) * DAY
        sel = select_trades(pred, prob, ret, t, conf_threshold=0.4)
        assert len(sel["gross_ret"]) == 2

    def test_direction_flips_return_for_down_prediction(self):
        # model đoán XUỐNG (0) và giá thực giảm (ret âm) -> gross return dương
        pred = np.array([0])
        prob = np.array([0.9])
        ret = np.array([-0.02])
        t = np.array([0])
        sel = select_trades(pred, prob, ret, t, conf_threshold=0.0)
        assert sel["gross_ret"][0] == pytest.approx(0.02)

    def test_direction_up_keeps_sign(self):
        pred = np.array([2])
        prob = np.array([0.9])
        ret = np.array([0.02])
        t = np.array([0])
        sel = select_trades(pred, prob, ret, t, conf_threshold=0.0)
        assert sel["gross_ret"][0] == pytest.approx(0.02)

    def test_sorted_by_time(self):
        pred = np.array([2, 2, 2])
        prob = np.array([0.9, 0.9, 0.9])
        ret = np.array([0.03, 0.01, 0.02])
        t = np.array([2, 0, 1]) * DAY
        sel = select_trades(pred, prob, ret, t, conf_threshold=0.0)
        assert np.all(np.diff(sel["t"]) >= 0)


class TestNetReturns:
    def test_fee_subtracted(self):
        gross = np.array([0.01, -0.01])
        net = net_returns(gross, fee_round_trip=0.001)
        assert net[0] == pytest.approx(0.009)
        assert net[1] == pytest.approx(-0.011)


class TestEquityCurve:
    def test_cumulative_matches_manual_calc(self):
        net = np.array([0.0, 0.0, 0.0])
        eq = equity_curve(net)
        assert eq == pytest.approx([1.0, 1.0, 1.0])

    def test_growth_compounds(self):
        net = np.log([1.1, 1.1])  # +10% mỗi lệnh (log-return)
        eq = equity_curve(net)
        assert eq[-1] == pytest.approx(1.1 * 1.1)


class TestMaxDrawdown:
    def test_no_drawdown_when_monotonic_up(self):
        eq = np.array([1.0, 1.1, 1.2])
        assert max_drawdown(eq) == pytest.approx(0.0)

    def test_detects_known_dip(self):
        eq = np.array([1.0, 1.2, 0.6, 0.9])
        # đỉnh 1.2 -> đáy 0.6 => dd = (0.6-1.2)/1.2 = -0.5
        assert max_drawdown(eq) == pytest.approx(-0.5)


class TestSharpeRatio:
    def test_zero_std_returns_nan(self):
        net = np.array([0.01, 0.01, 0.01])
        t = np.array([0, 1, 2]) * DAY
        assert np.isnan(sharpe_ratio(net, t))

    def test_positive_mean_gives_positive_sharpe(self):
        rng = np.random.default_rng(0)
        net = rng.normal(0.001, 0.01, 500)
        t = np.arange(500) * DAY
        sr = sharpe_ratio(net, t)
        assert sr > 0

    def test_too_few_trades_is_nan(self):
        assert np.isnan(sharpe_ratio(np.array([0.01]), np.array([0])))


class TestEvaluateThresholds:
    def test_higher_threshold_means_fewer_or_equal_trades(self):
        rng = np.random.default_rng(1)
        n = 2000
        pred = rng.choice([0, 1, 2], n, p=[0.3, 0.4, 0.3])
        prob = rng.uniform(0.33, 1.0, n)
        ret = rng.normal(0, 0.01, n)
        t = np.arange(n) * (DAY // 100)
        cfg = BacktestConfig(conf_thresholds=(0.0, 0.4, 0.6, 0.8))
        df = evaluate_thresholds(pred, prob, ret, t, cfg)
        assert list(df["n_trades"]) == sorted(df["n_trades"], reverse=True)

    def test_high_fee_makes_all_trades_losers_on_average(self):
        rng = np.random.default_rng(2)
        n = 500
        pred = rng.choice([0, 2], n)
        prob = np.full(n, 0.9)
        ret = rng.normal(0.0001, 0.001, n)  # edge rất nhỏ
        t = np.arange(n) * (DAY // 10)
        cfg = BacktestConfig(fee_round_trip=0.05, conf_thresholds=(0.0,))
        df = evaluate_thresholds(pred, prob, ret, t, cfg)
        assert df.iloc[0]["mean_net_ret"] < 0
        assert df.iloc[0]["total_return"] < 0

    def test_empty_selection_handled(self):
        pred = np.array([1, 1, 1])
        prob = np.array([0.9, 0.9, 0.9])
        ret = np.array([0.01, 0.01, 0.01])
        t = np.arange(3) * DAY
        cfg = BacktestConfig(conf_thresholds=(0.0,))
        df = evaluate_thresholds(pred, prob, ret, t, cfg)
        assert df.iloc[0]["n_trades"] == 0
        assert np.isnan(df.iloc[0]["sharpe"])
