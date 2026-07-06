"""Tests cho features/bar_features.py — bộ features v1 từ dollar bars.

Nguyên tắc quan trọng nhất: MỌI feature phải causal — giá trị tại bar i
chỉ phụ thuộc bars 0..i. Không nhìn tương lai.
"""
import numpy as np
import pandas as pd
import pytest

from bars.pipeline import Config, make_synthetic_trades, process_stream
from features.bar_features import FEATURE_COLS, compute_bar_features


@pytest.fixture(scope="module")
def bars():
    cfg = Config()
    cfg.DOLLAR_THRESHOLD = 2_000_000.0  # nhỏ để ra nhiều bars từ synthetic
    trades = make_synthetic_trades(n_trades=300_000, seed=7)
    out, _ = process_stream([trades], cfg)
    assert len(out) > 200, "fixture cần đủ bars để qua warmup"
    return out


@pytest.fixture(scope="module")
def feats(bars):
    return compute_bar_features(bars)


WARMUP = 50


class TestSchema:
    def test_returns_all_feature_cols_plus_carry(self, bars, feats):
        # carry t_close + close để join labels sau này
        assert list(feats.columns) == ["t_close", "close"] + FEATURE_COLS

    def test_same_length_and_index_as_input(self, bars, feats):
        assert len(feats) == len(bars)
        assert (feats.index == bars.index).all()

    def test_feature_count_is_21(self):
        assert len(FEATURE_COLS) == 21

    def test_no_nan_after_warmup(self, feats):
        tail = feats.iloc[WARMUP:]
        assert not tail.isna().any().any(), tail.isna().sum()[lambda s: s > 0]


class TestKnownValues:
    def test_logret_1(self, bars, feats):
        i = 100
        expected = np.log(bars["close"].iloc[i] / bars["close"].iloc[i - 1])
        assert feats["logret_1"].iloc[i] == pytest.approx(expected)

    def test_logret_5(self, bars, feats):
        i = 100
        expected = np.log(bars["close"].iloc[i] / bars["close"].iloc[i - 5])
        assert feats["logret_5"].iloc[i] == pytest.approx(expected)

    def test_vol_20_is_rolling_std_of_logret_1(self, bars, feats):
        lr = np.log(bars["close"] / bars["close"].shift(1))
        expected = lr.rolling(20).std()
        pd.testing.assert_series_equal(
            feats["vol_20"].iloc[WARMUP:], expected.iloc[WARMUP:], check_names=False
        )

    def test_zret_1_is_vol_scaled(self, feats):
        i = 100
        expected = feats["logret_1"].iloc[i] / feats["vol_20"].iloc[i]
        assert feats["zret_1"].iloc[i] == pytest.approx(expected)

    def test_ofi_mean_20(self, bars, feats):
        expected = bars["ofi"].rolling(20).mean()
        pd.testing.assert_series_equal(
            feats["ofi_mean_20"].iloc[WARMUP:], expected.iloc[WARMUP:], check_names=False
        )

    def test_range_pct(self, bars, feats):
        i = 100
        b = bars.iloc[i]
        assert feats["range_pct"].iloc[i] == pytest.approx(
            (b["high"] - b["low"]) / b["close"]
        )

    def test_close_pos_bounded_0_1(self, feats):
        cp = feats["close_pos"].iloc[WARMUP:]
        assert (cp >= 0).all() and (cp <= 1).all()

    def test_close_pos_degenerate_bar_is_half(self, bars):
        # bar high == low (1 giá duy nhất) không được ra NaN/inf
        b = bars.iloc[:60].copy()
        b.loc[b.index[55], ["high", "low", "close", "open"]] = 100.0
        f = compute_bar_features(b)
        assert f["close_pos"].iloc[55] == pytest.approx(0.5)


class TestTimeFeatures:
    def test_hour_sin_cos_at_6am_utc(self, bars):
        b = bars.iloc[:60].copy()
        # 2026-01-01 06:00:00 UTC
        ts = pd.Timestamp("2026-01-01 06:00:00", tz="UTC").value // 1_000_000
        b.loc[b.index[55], "t_close"] = ts
        f = compute_bar_features(b)
        assert f["hour_sin"].iloc[55] == pytest.approx(np.sin(2 * np.pi * 6 / 24))
        assert f["hour_cos"].iloc[55] == pytest.approx(np.cos(2 * np.pi * 6 / 24))

    def test_dow_thursday(self, bars):
        b = bars.iloc[:60].copy()
        ts = pd.Timestamp("2026-01-01 06:00:00", tz="UTC").value // 1_000_000  # thứ 5
        b.loc[b.index[55], "t_close"] = ts
        f = compute_bar_features(b)
        assert f["dow_sin"].iloc[55] == pytest.approx(np.sin(2 * np.pi * 3 / 7))
        assert f["dow_cos"].iloc[55] == pytest.approx(np.cos(2 * np.pi * 3 / 7))


class TestCausality:
    """Điều kiện sống còn: cắt bớt tương lai không được đổi quá khứ."""

    def test_truncated_input_gives_identical_prefix(self, bars, feats):
        k = 150
        f_trunc = compute_bar_features(bars.iloc[:k])
        pd.testing.assert_frame_equal(f_trunc, feats.iloc[:k])

    def test_perturbing_future_leaves_past_unchanged(self, bars, feats):
        k = 150
        mutated = bars.copy()
        mutated.loc[mutated.index[k:], ["close", "high", "low", "open", "ofi"]] *= 3.7
        f_mut = compute_bar_features(mutated)
        pd.testing.assert_frame_equal(f_mut.iloc[:k], feats.iloc[:k])
