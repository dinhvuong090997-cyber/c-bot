"""Tests cho Bybit API parsers + funding/OI features.

Điểm sống còn: point-in-time — tại t_close của bar chỉ được dùng
funding/OI đã công bố TRƯỚC HOẶC BẰNG t_close.
"""
import numpy as np
import pandas as pd
import pytest

from data.bybit_api import parse_funding, parse_oi
from features.aux_features import (
    FUNDING_FEATURE_COLS,
    OI_FEATURE_COLS,
    add_funding_features,
    add_oi_features,
)

H = 3_600_000  # 1 giờ tính bằng ms


# ---------- parsers (shape thật từ API v5, list newest-first) ----------

FUNDING_JSON = {
    "retCode": 0,
    "result": {"category": "linear", "list": [
        {"symbol": "BTCUSDT", "fundingRate": "-0.00000755", "fundingRateTimestamp": "1783324800000"},
        {"symbol": "BTCUSDT", "fundingRate": "0.00005565", "fundingRateTimestamp": "1783296000000"},
    ]},
}

OI_JSON = {
    "retCode": 0,
    "result": {"symbol": "BTCUSDT", "list": [
        {"openInterest": "58324.309", "timestamp": "1783349700000"},
        {"openInterest": "58339.835", "timestamp": "1783349400000"},
    ], "nextPageCursor": "abc"},
}


class TestParsers:
    def test_parse_funding_ascending_floats(self):
        df = parse_funding(FUNDING_JSON)
        assert list(df.columns) == ["ts", "funding_rate"]
        assert df["ts"].tolist() == [1783296000000, 1783324800000]  # tăng dần
        assert df["funding_rate"].tolist() == pytest.approx([0.00005565, -0.00000755])
        assert df["ts"].dtype == np.int64

    def test_parse_oi_ascending_floats(self):
        df = parse_oi(OI_JSON)
        assert list(df.columns) == ["ts", "oi"]
        assert df["ts"].tolist() == [1783349400000, 1783349700000]
        assert df["oi"].tolist() == pytest.approx([58339.835, 58324.309])


# ---------- funding features ----------

@pytest.fixture
def funding():
    # 12 kỳ funding cách nhau 8h, rate = 0.0001 * (i+1)
    t0 = pd.Timestamp("2026-01-01 00:00:00", tz="UTC").value // 1_000_000
    return pd.DataFrame({
        "ts": np.int64(t0) + np.arange(12, dtype=np.int64) * 8 * H,
        "funding_rate": 0.0001 * np.arange(1, 13),
    })


def _feats_at(ts_list):
    return pd.DataFrame({
        "t_close": np.array(ts_list, dtype=np.int64),
        "close": 100.0,
    })


class TestFundingFeatures:
    def test_uses_last_announced_rate(self, funding):
        t0 = funding["ts"].iloc[0]
        f = add_funding_features(_feats_at([t0 + 1 * H, t0 + 9 * H]), funding)
        # bar tại t0+1h: kỳ gần nhất là t0 (rate 0.0001); t0+9h: kỳ t0+8h (0.0002)
        assert f["fund_rate"].tolist() == pytest.approx([0.0001, 0.0002])

    def test_no_lookahead_before_first_event(self, funding):
        t0 = funding["ts"].iloc[0]
        f = add_funding_features(_feats_at([t0 - 1 * H]), funding)
        assert np.isnan(f["fund_rate"].iloc[0])

    def test_fund_chg_is_delta_vs_previous_period(self, funding):
        t0 = funding["ts"].iloc[0]
        f = add_funding_features(_feats_at([t0 + 9 * H]), funding)
        assert f["fund_chg"].iloc[0] == pytest.approx(0.0002 - 0.0001)

    def test_fund_sum_9_covers_3_days(self, funding):
        t0 = funding["ts"].iloc[0]
        f = add_funding_features(_feats_at([t0 + 11 * 8 * H]), funding)  # sau kỳ 12
        assert f["fund_sum_9"].iloc[0] == pytest.approx(0.0001 * sum(range(4, 13)))

    def test_hrs_to_funding(self, funding):
        ts = pd.Timestamp("2026-01-01 06:00:00", tz="UTC").value // 1_000_000
        f = add_funding_features(_feats_at([ts]), funding)
        assert f["hrs_to_funding"].iloc[0] == pytest.approx(2.0)  # kỳ tới 08:00

    def test_appends_exactly_funding_cols(self, funding):
        t0 = funding["ts"].iloc[0]
        f = add_funding_features(_feats_at([t0 + 1 * H]), funding)
        assert list(f.columns) == ["t_close", "close"] + FUNDING_FEATURE_COLS


# ---------- OI features ----------

@pytest.fixture
def oi():
    # snapshot 5 phút trong 48h, OI tăng tuyến tính 1000/h từ 50000
    t0 = pd.Timestamp("2026-01-01 00:00:00", tz="UTC").value // 1_000_000
    ts = np.int64(t0) + np.arange(48 * 12, dtype=np.int64) * 5 * 60_000
    return pd.DataFrame({"ts": ts, "oi": 50_000.0 + np.arange(48 * 12) * (1000 / 12)})


class TestOIFeatures:
    def test_oi_chg_1h(self, oi):
        t = oi["ts"].iloc[0] + 30 * H
        f = add_oi_features(_feats_at([t]), oi)
        now, ago = 50_000 + 30 * 1000, 50_000 + 29 * 1000
        assert f["oi_chg_1h"].iloc[0] == pytest.approx(now / ago - 1)

    def test_oi_chg_24h(self, oi):
        t = oi["ts"].iloc[0] + 30 * H
        f = add_oi_features(_feats_at([t]), oi)
        now, ago = 50_000 + 30 * 1000, 50_000 + 6 * 1000
        assert f["oi_chg_24h"].iloc[0] == pytest.approx(now / ago - 1)

    def test_no_lookahead_uses_snapshot_at_or_before_bar(self, oi):
        # bar giữa 2 snapshot → phải lấy snapshot TRƯỚC, không phải sau
        t = oi["ts"].iloc[0] + 30 * H + 2 * 60_000  # lệch +2 phút
        f = add_oi_features(_feats_at([t]), oi)
        now, ago = 50_000 + 30 * 1000, 50_000 + 29 * 1000  # vẫn snapshot :00
        assert f["oi_chg_1h"].iloc[0] == pytest.approx(now / ago - 1)

    def test_nan_when_history_missing(self, oi):
        t = oi["ts"].iloc[0] + 30 * 60_000  # mới 30 phút dữ liệu → thiếu mốc 1h
        f = add_oi_features(_feats_at([t]), oi)
        assert np.isnan(f["oi_chg_1h"].iloc[0])

    def test_oi_price_div_4h_sign(self, oi):
        # OI tăng, giá giảm qua 4h → divergence âm
        t = oi["ts"].iloc[0] + 30 * H
        feats = pd.DataFrame({
            "t_close": np.array([t - 4 * H, t], dtype=np.int64),
            "close": [110.0, 100.0],
        })
        f = add_oi_features(feats, oi)
        oi_chg_4h = f["oi_chg_4h"].iloc[1]
        assert oi_chg_4h > 0
        assert f["oi_price_div_4h"].iloc[1] == pytest.approx(-oi_chg_4h)

    def test_appends_exactly_oi_cols(self, oi):
        t = oi["ts"].iloc[0] + 30 * H
        f = add_oi_features(_feats_at([t]), oi)
        assert list(f.columns) == ["t_close", "close"] + OI_FEATURE_COLS
