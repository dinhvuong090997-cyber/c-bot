"""Tests cho live/features_live.py — tính features cho bar MỚI NHẤT.

Yêu cầu cốt lõi: giá trị live phải GIỐNG HỆT pipeline batch
(compute_bar_features + add_funding_features + add_oi_features) tại cùng bar
— nếu lệch thì model nhận input khác lúc train, mọi backtest vô nghĩa.
"""
import numpy as np
import pandas as pd
import pytest

from features.aux_features import add_funding_features, add_oi_features
from features.bar_features import compute_bar_features
from live.features_live import ALL_FEATURE_COLS, WARMUP_BARS, latest_features

_H = 3_600_000
T0 = 1_700_000_000_000


def make_bars(n=120, seed=7):
    rng = np.random.default_rng(seed)
    t_close = T0 + np.cumsum(rng.integers(60_000, 600_000, n))
    t_open = t_close - rng.integers(30_000, 300_000, n)
    close = 60_000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    spread = np.abs(rng.normal(0, 0.001, n)) * close
    return pd.DataFrame({
        "t_open": t_open.astype(np.int64),
        "t_close": t_close.astype(np.int64),
        "open": close * (1 + rng.normal(0, 0.0005, n)),
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "vol_dollar": rng.uniform(9e6, 1.2e7, n),
        "n_trades": rng.integers(1000, 9000, n).astype(np.int64),
        "ofi": rng.uniform(-0.5, 0.5, n),
    })


def make_funding(t_end, n=20):
    ts = np.array([t_end - i * 8 * _H for i in range(n)][::-1], dtype=np.int64)
    rng = np.random.default_rng(1)
    return pd.DataFrame({"ts": ts, "funding_rate": rng.normal(1e-4, 5e-5, n)})


def make_oi(t_start, t_end):
    ts = np.arange(t_start - 26 * _H, t_end + 1, 5 * 60_000, dtype=np.int64)
    rng = np.random.default_rng(2)
    return pd.DataFrame({"ts": ts, "oi": 50_000 + np.cumsum(rng.normal(0, 30, len(ts)))})


@pytest.fixture
def data():
    bars = make_bars()
    funding = make_funding(int(bars["t_close"].iloc[-1]) + 1)
    oi = make_oi(int(bars["t_close"].iloc[0]), int(bars["t_close"].iloc[-1]) + 1)
    return bars, funding, oi


def batch_features(bars, funding, oi):
    f = compute_bar_features(bars)
    f = add_funding_features(f, funding)
    return add_oi_features(f, oi)


class TestMatchesBatch:
    def test_last_row_identical_to_batch(self, data):
        bars, funding, oi = data
        batch = batch_features(bars, funding, oi)
        for i in (WARMUP_BARS - 1, 80, len(bars) - 1):
            window = bars.iloc[: i + 1].tail(WARMUP_BARS).reset_index(drop=True)
            live = latest_features(window, funding, oi)
            for col in ALL_FEATURE_COLS:
                assert live[col] == pytest.approx(batch[col].iloc[i], rel=1e-12), \
                    f"lệch batch tại bar {i}, cột {col}"

    def test_includes_close_and_t_close(self, data):
        bars, funding, oi = data
        live = latest_features(bars.tail(WARMUP_BARS), funding, oi)
        assert live["close"] == bars["close"].iloc[-1]
        assert live["t_close"] == bars["t_close"].iloc[-1]

    def test_no_nan_after_warmup(self, data):
        bars, funding, oi = data
        live = latest_features(bars.tail(WARMUP_BARS), funding, oi)
        assert not live[ALL_FEATURE_COLS].isna().any()


class TestGuards:
    def test_rejects_short_window(self, data):
        bars, funding, oi = data
        with pytest.raises(ValueError, match="warmup"):
            latest_features(bars.tail(WARMUP_BARS - 1), funding, oi)
