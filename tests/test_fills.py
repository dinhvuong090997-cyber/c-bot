"""Tests cho backtest/fills.py — mô phỏng khớp lệnh maker mức OHLC bar.

Entry: limit tại close[i] của bar tín hiệu, chờ tối đa k bar (i+1..i+k):
long khớp nếu low <= limit, short nếu high >= limit. Không khớp -> bỏ.

Barriers neo quanh GIÁ ENTRY THỰC, width lấy tại bar tín hiệu i:
  long : tp = entry*exp(+w), sl = entry*exp(-w)
  short: tp = entry*exp(-w), sl = entry*exp(+w)
Vertical = fill bar f + horizon.

Exit quét f..f+horizon (bar f chỉ xét SL — giá vừa rơi xuyên limit có thể
xuyên luôn stop, conservative):
  TP khớp maker chỉ khi giá VƯỢT QUA barrier (không chỉ chạm);
  SL chạm là dính, thoát taker tại giá barrier;
  1 bar dính cả 2 -> tính SL;
  hết horizon -> thoát taker tại close.
"""
import numpy as np
import pandas as pd
import pytest

from backtest.fills import FillConfig, simulate_trades
from model.labels import LabelConfig

MAKER = 0.0002
TAKER = 0.00055
W = 0.01  # width cố định 1%: tp/sl = entry * exp(±0.01)

LCFG = LabelConfig(horizon=5, width_mult=1.0)
FCFG = FillConfig(entry_wait_bars=2, maker_fee=MAKER, taker_fee=TAKER)


def make_bars(closes, highs=None, lows=None):
    c = np.asarray(closes, dtype=np.float64)
    h = np.asarray(highs, dtype=np.float64) if highs is not None else c
    l = np.asarray(lows, dtype=np.float64) if lows is not None else c
    return pd.DataFrame({
        "t_close": np.arange(len(c), dtype=np.int64) * 60_000,
        "close": c, "high": np.maximum(h, c), "low": np.minimum(l, c),
    })


def sig(bar_idx, direction, confidence=0.6):
    return pd.DataFrame({"bar_idx": [bar_idx], "direction": [direction],
                         "confidence": [confidence]})


def run(bars, signals, lcfg=LCFG, fcfg=FCFG):
    return simulate_trades(bars, signals, lcfg, fcfg,
                           width=np.full(len(bars), W))


FLAT = [100.0] * 12  # đủ dài cho k=2 + horizon=5


class TestEntryFill:
    def test_fills_on_first_bar_touch(self):
        # long limit @100; bar 1 low=99.9 chạm -> khớp tại 100
        bars = make_bars(FLAT, lows=[100, 99.9] + [100] * 10)
        out = run(bars, sig(0, +1))
        assert out["filled"].iloc[0]
        assert out["fill_idx"].iloc[0] == 1
        assert out["entry_price"].iloc[0] == pytest.approx(100.0)

    def test_fills_late_within_k_bars(self):
        # bar 1 không chạm, bar 2 chạm (k=2)
        bars = make_bars(FLAT, lows=[100, 100.5, 99.9] + [100] * 9)
        bars.loc[1, "low"] = 100.5
        bars.loc[1, "close"] = 100.5  # giữ low<=close hợp lệ
        out = run(bars, sig(0, +1))
        assert out["filled"].iloc[0]
        assert out["fill_idx"].iloc[0] == 2

    def test_not_filled_within_k_bars_is_missed(self):
        # giá bay lên luôn, không quay lại limit trong k=2 bar
        closes = [100, 101, 102, 103, 104, 105] + [105] * 6
        bars = make_bars(closes, lows=closes)
        out = run(bars, sig(0, +1))
        assert not out["filled"].iloc[0]

    def test_short_fills_when_high_touches(self):
        bars = make_bars(FLAT, highs=[100, 100.1] + [100] * 10)
        out = run(bars, sig(0, -1))
        assert out["filled"].iloc[0]
        assert out["fill_idx"].iloc[0] == 1


class TestExits:
    def test_tp_requires_crossing_not_touching(self):
        tp = 100.0 * np.exp(W)
        # bar 2 high == tp (chạm đúng) -> KHÔNG khớp maker -> vertical
        highs = [100, 100, tp] + [100] * 9
        bars = make_bars(FLAT, highs=highs, lows=[100, 99.9] + [100] * 10)
        out = run(bars, sig(0, +1))
        assert out["exit_type"].iloc[0] == "vertical"

    def test_tp_crossed_exits_maker_at_barrier(self):
        # fill bar 1; bar 3 high vượt tp -> exit maker tại giá tp
        bars = make_bars(FLAT, highs=[100, 100, 100, 102] + [100] * 8,
                         lows=[100, 99.9] + [100] * 10)
        out = run(bars, sig(0, +1))
        assert out["exit_type"].iloc[0] == "tp"
        assert out["exit_idx"].iloc[0] == 3
        assert out["exit_price"].iloc[0] == pytest.approx(100.0 * np.exp(W))
        assert out["gross_ret"].iloc[0] == pytest.approx(W)
        assert out["net_ret"].iloc[0] == pytest.approx(W - 2 * MAKER)

    def test_sl_touch_exits_taker_at_barrier(self):
        sl = 100.0 * np.exp(-W)
        bars = make_bars(FLAT, lows=[100, 99.9, sl] + [100] * 9)
        out = run(bars, sig(0, +1))
        assert out["exit_type"].iloc[0] == "sl"
        assert out["exit_price"].iloc[0] == pytest.approx(sl)
        assert out["gross_ret"].iloc[0] == pytest.approx(-W)
        assert out["net_ret"].iloc[0] == pytest.approx(-W - MAKER - TAKER)

    def test_both_barriers_same_bar_counts_as_sl(self):
        bars = make_bars(FLAT, highs=[100, 100, 103] + [100] * 9,
                         lows=[100, 99.9, 97] + [100] * 9)
        out = run(bars, sig(0, +1))
        assert out["exit_type"].iloc[0] == "sl"

    def test_vertical_exits_taker_at_close(self):
        closes = [100.0] * 7 + [100.2] + [100.0] * 4
        bars = make_bars(closes, lows=[100, 99.9] + [100.0] * 9 + [100.2])
        bars.loc[7, "low"] = 100.0
        out = run(bars, sig(0, +1))
        # fill bar 1, horizon 5 -> vertical tại bar 6? close[6]=100
        assert out["exit_type"].iloc[0] == "vertical"
        assert out["exit_idx"].iloc[0] == 6
        assert out["exit_price"].iloc[0] == pytest.approx(100.0)
        assert out["net_ret"].iloc[0] == pytest.approx(0.0 - MAKER - TAKER)

    def test_sl_on_fill_bar_itself_is_conservative(self):
        # bar 1 rơi xuyên limit và xuyên luôn sl -> SL ngay bar khớp
        sl = 100.0 * np.exp(-W)
        bars = make_bars(FLAT, lows=[100, sl - 0.5] + [100] * 10)
        out = run(bars, sig(0, +1))
        assert out["filled"].iloc[0]
        assert out["exit_type"].iloc[0] == "sl"
        assert out["exit_idx"].iloc[0] == 1

    def test_short_symmetric_tp(self):
        # short entry 100, tp = 100*exp(-W); giá rơi xuyên tp
        bars = make_bars(FLAT, highs=[100, 100.1] + [100] * 10,
                         lows=[100, 100, 100, 98] + [100] * 8)
        out = run(bars, sig(0, -1))
        assert out["exit_type"].iloc[0] == "tp"
        assert out["gross_ret"].iloc[0] == pytest.approx(W)
        assert out["net_ret"].iloc[0] == pytest.approx(W - 2 * MAKER)


class TestEdges:
    def test_incomplete_path_dropped(self):
        # fill bar quá gần cuối data -> không đủ horizon -> complete=False
        bars = make_bars([100.0] * 4, lows=[100, 99.9, 100, 100])
        out = run(bars, sig(0, +1))
        assert not out["complete"].iloc[0]

    def test_output_carries_signal_metadata(self):
        bars = make_bars(FLAT, lows=[100, 99.9] + [100] * 10)
        out = run(bars, sig(0, +1, confidence=0.71))
        row = out.iloc[0]
        assert row["direction"] == 1
        assert row["confidence"] == pytest.approx(0.71)
        assert row["t_exit"] == bars["t_close"].iloc[int(row["exit_idx"])]
