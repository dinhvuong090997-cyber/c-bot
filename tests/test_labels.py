"""Tests cho model/labels.py — triple-barrier labeling (AFML).

Mỗi bar i là 1 event: entry = close[i], barrier trên/dưới = close[i] * exp(±width[i]),
vertical barrier = i + horizon bars. Label:
  +1 chạm trên trước, -1 chạm dưới trước, 0 hết giờ (vertical).
Chạm barrier xét bằng high/low của các bar SAU i (i+1..i+horizon).
"""
import numpy as np
import pandas as pd
import pytest

from model.labels import LabelConfig, triple_barrier


def make_bars(closes, highs=None, lows=None):
    c = np.asarray(closes, dtype=np.float64)
    h = np.asarray(highs, dtype=np.float64) if highs is not None else c
    l = np.asarray(lows, dtype=np.float64) if lows is not None else c
    return pd.DataFrame({
        "t_close": np.arange(len(c), dtype=np.int64) * 60_000,
        "close": c, "high": np.maximum(h, c), "low": np.minimum(l, c),
    })


# width cố định 1% cho dễ tính: barrier trên = c*e^0.01, dưới = c*e^-0.01
CFG = LabelConfig(horizon=5, width_mult=1.0)
FIXED_W = 0.01


class TestBasicLabels:
    def test_upper_hit_first_is_plus1(self):
        # bar 0: entry 100, barrier trên ~101.005; bar 2 high vượt
        bars = make_bars([100, 100, 100, 100, 100, 100, 100],
                         highs=[100, 100, 102, 100, 100, 100, 100])
        out = triple_barrier(bars, CFG, width=np.full(7, FIXED_W))
        assert out["label"].iloc[0] == 1
        assert out["t_end_idx"].iloc[0] == 2

    def test_lower_hit_first_is_minus1(self):
        bars = make_bars([100, 100, 100, 100, 100, 100, 100],
                         lows=[100, 98, 100, 100, 100, 100, 100])
        out = triple_barrier(bars, CFG, width=np.full(7, FIXED_W))
        assert out["label"].iloc[0] == -1
        assert out["t_end_idx"].iloc[0] == 1

    def test_timeout_is_0_at_vertical(self):
        bars = make_bars([100.0] * 10)
        out = triple_barrier(bars, CFG, width=np.full(10, FIXED_W))
        assert out["label"].iloc[0] == 0
        assert out["t_end_idx"].iloc[0] == 5  # i + horizon

    def test_first_touch_wins_not_biggest(self):
        # dưới chạm ở bar 1, trên chạm ở bar 3 -> -1
        bars = make_bars([100] * 8,
                         highs=[100, 100, 100, 105, 100, 100, 100, 100],
                         lows=[100, 98, 100, 100, 100, 100, 100, 100])
        out = triple_barrier(bars, CFG, width=np.full(8, FIXED_W))
        assert out["label"].iloc[0] == -1

    def test_ambiguous_both_in_same_bar(self):
        # bar 1 vừa vượt trên vừa thủng dưới -> không biết cái nào trước
        bars = make_bars([100] * 8,
                         highs=[100, 103, 100, 100, 100, 100, 100, 100],
                         lows=[100, 97, 100, 100, 100, 100, 100, 100])
        out = triple_barrier(bars, CFG, width=np.full(8, FIXED_W))
        assert bool(out["ambiguous"].iloc[0]) is True
        assert out["label"].iloc[0] == 0  # xử lý bảo thủ

    def test_ret_is_logret_at_event_end(self):
        bars = make_bars([100, 100, 100, 100, 100, 104, 100],
                         highs=[100, 100, 102, 100, 100, 104, 100])
        out = triple_barrier(bars, CFG, width=np.full(7, FIXED_W))
        expected = np.log(bars["close"].iloc[2] / bars["close"].iloc[0])
        assert out["ret"].iloc[0] == pytest.approx(expected)


class TestIncompleteEvents:
    def test_tail_events_marked_incomplete(self):
        # 10 bars, horizon 5: events từ index 5 trở đi không đủ đường chạy
        bars = make_bars([100.0] * 10)
        out = triple_barrier(bars, CFG, width=np.full(10, FIXED_W))
        assert not out["complete"].iloc[5:].any()
        assert out["complete"].iloc[:5].all()

    def test_incomplete_events_label_nan_free_via_filter(self):
        bars = make_bars([100.0] * 10)
        out = triple_barrier(bars, CFG, width=np.full(10, FIXED_W))
        # label của event chưa hoàn tất không được dùng để train
        assert (out.loc[~out["complete"], "label"] == 0).all()  # placeholder 0


class TestDefaultWidth:
    def test_width_from_rolling_vol_when_not_given(self):
        rng = np.random.default_rng(3)
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, 500)))
        bars = make_bars(c)
        out = triple_barrier(bars, LabelConfig(horizon=20, width_mult=1.0, vol_window=50))
        # width = vol_50 * sqrt(horizon) * mult -> event đầu (chưa đủ vol) không complete
        assert len(out) == len(bars)
        assert not out["complete"].iloc[:50].any()
        assert out["complete"].iloc[60:400].all()


class TestAgainstNaiveReference:
    def test_vectorized_matches_naive_loop(self):
        rng = np.random.default_rng(11)
        n = 300
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
        h = c * np.exp(np.abs(rng.normal(0, 0.001, n)))
        l = c * np.exp(-np.abs(rng.normal(0, 0.001, n)))
        bars = make_bars(c, h, l)
        w = np.full(n, 0.003)
        cfg = LabelConfig(horizon=10, width_mult=1.0)
        out = triple_barrier(bars, cfg, width=w)

        # tham chiếu: loop từng event một
        for i in range(0, n - cfg.horizon, 7):
            up, dn = c[i] * np.exp(w[i]), c[i] * np.exp(-w[i])
            lbl, t_end = 0, i + cfg.horizon
            for j in range(i + 1, i + cfg.horizon + 1):
                uh, dh = bars["high"].iloc[j] >= up, bars["low"].iloc[j] <= dn
                if uh and dh:
                    lbl, t_end = 0, j
                    break
                if uh:
                    lbl, t_end = 1, j
                    break
                if dh:
                    lbl, t_end = -1, j
                    break
            assert out["label"].iloc[i] == lbl, f"event {i}"
            assert out["t_end_idx"].iloc[i] == t_end, f"event {i}"
