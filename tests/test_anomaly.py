"""Tests cho llm/anomaly.py — heuristic gate trước LLM veto.

Ý tưởng lấy từ adverse_score của pa-model: chỉ gọi LLM khi detector rẻ tiền
thấy bất thường; regime bình thường auto-approve (không API call, không cơ
hội veto nhầm). sanity_errors = data hỏng thì chặn thẳng không cần LLM.
"""
import math

import pytest

from llm.anomaly import AnomalyConfig, anomaly_flags, sanity_errors


def make_ctx(**over):
    """Ctx bình thường: không cờ nào được bật."""
    base = {
        "side": "Buy", "confidence": 0.5,
        "prob_down_flat_up": (0.2, 0.3, 0.5),
        "entry_price": 100.0, "tp_pct": 1.5, "sl_pct": -1.5,
        "horizon_bars": 80, "time_utc": "2026-07-07T00:00:00+00:00",
        "chg_10_bars_pct": 0.2, "chg_50_bars_pct": 0.8,
        "span_50_bars_min": 240.0, "vol_50": 0.002,
        "ofi": 0.1, "ofi_sum_50": 1.0, "range_pct": 0.001,
        "fund_rate": 1e-4, "fund_sum_9": 9e-4, "hrs_to_funding": 4.0,
        "oi_chg_1h": 0.005, "oi_chg_4h": 0.01, "oi_chg_24h": 0.02,
    }
    base.update(over)
    return base


class TestSanity:
    def test_clean_ctx_no_errors(self):
        assert sanity_errors(make_ctx()) == []

    def test_nan_value_flagged(self):
        errs = sanity_errors(make_ctx(vol_50=float("nan")))
        assert any("vol_50" in e for e in errs)

    def test_inf_value_flagged(self):
        assert sanity_errors(make_ctx(oi_chg_1h=math.inf))

    def test_tp_wrong_side_for_buy(self):
        # Buy mà TP âm (dưới entry) = barrier sai phía
        assert sanity_errors(make_ctx(side="Buy", tp_pct=-1.0, sl_pct=-2.0))

    def test_sl_wrong_side_for_sell(self):
        assert sanity_errors(make_ctx(side="Sell", tp_pct=-1.0, sl_pct=-2.0))

    def test_confidence_out_of_range(self):
        assert sanity_errors(make_ctx(confidence=1.7))


class TestAnomalyFlags:
    def test_calm_regime_no_flags(self):
        assert anomaly_flags(make_ctx()) == []

    def test_cascade_fast_large_move(self):
        # 50 bar (~$500M) trong 60 phút và giá chạy 3% = cascade
        flags = anomaly_flags(make_ctx(chg_50_bars_pct=-3.0,
                                       span_50_bars_min=60.0))
        assert any("cascade" in f for f in flags)

    def test_large_move_slow_span_not_cascade(self):
        # 3% nhưng trải 8 tiếng = trend bình thường
        assert anomaly_flags(make_ctx(chg_50_bars_pct=3.0,
                                      span_50_bars_min=480.0)) == []

    def test_sharp_short_move(self):
        flags = anomaly_flags(make_ctx(chg_10_bars_pct=2.0))
        assert any("sharp" in f for f in flags)

    def test_funding_stretched_against_buy(self):
        # funding dương cao = long trả phí đậm = crowded long, mình lại Buy
        flags = anomaly_flags(make_ctx(side="Buy", fund_rate=6e-4))
        assert any("funding" in f for f in flags)

    def test_funding_stretched_same_side_ok(self):
        # crowded long nhưng mình Sell -> không phải cờ
        assert anomaly_flags(make_ctx(side="Sell", fund_rate=6e-4)) == []

    def test_funding_settlement_soon_and_stretched(self):
        flags = anomaly_flags(make_ctx(hrs_to_funding=0.3, fund_rate=-4e-4))
        assert any("settlement" in f for f in flags)

    def test_settlement_soon_but_normal_funding_ok(self):
        assert anomaly_flags(make_ctx(hrs_to_funding=0.3)) == []

    def test_oi_shock_1h(self):
        flags = anomaly_flags(make_ctx(oi_chg_1h=-0.04))
        assert any("oi" in f.lower() for f in flags)

    def test_oi_collapse_4h(self):
        flags = anomaly_flags(make_ctx(oi_chg_4h=-0.10))
        assert any("oi" in f.lower() for f in flags)

    def test_thresholds_configurable(self):
        cfg = AnomalyConfig(sharp_move_pct=0.1)
        assert anomaly_flags(make_ctx(chg_10_bars_pct=0.2), cfg)
