"""Bộ features v1 tính từ dollar bars — 21 features, tất cả causal.

Mọi phép tính chỉ dùng rolling/shift nhìn về quá khứ. Giá trị tại bar i
là thứ ta THỰC SỰ biết được tại thời điểm t_close của bar i.

Warmup: 50 bars đầu có NaN (cửa sổ rolling dài nhất = 50) — caller tự drop.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLS = [
    # returns
    "logret_1", "logret_2", "logret_5", "logret_10", "logret_20",
    # volatility + return chuẩn hóa
    "vol_20", "vol_50", "zret_1", "zret_5",
    # order flow imbalance
    "ofi", "ofi_mean_20", "ofi_std_20", "ofi_sum_50",
    # tốc độ bar + cấu trúc bar
    "dur_log_ratio_20", "range_pct", "close_pos", "trade_size_ratio_50",
    # thời gian trong ngày / tuần (chu kỳ)
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
]


def compute_bar_features(bars: pd.DataFrame) -> pd.DataFrame:
    """bars: output của DollarBarBuilder. Trả về DataFrame cùng index,
    cột = [t_close, close] + FEATURE_COLS."""
    c = bars["close"]
    out = pd.DataFrame(index=bars.index)
    out["t_close"] = bars["t_close"]
    out["close"] = c

    # --- returns ---
    logc = np.log(c)
    for k in (1, 2, 5, 10, 20):
        out[f"logret_{k}"] = logc - logc.shift(k)

    # --- volatility ---
    lr1 = out["logret_1"]
    out["vol_20"] = lr1.rolling(20).std()
    out["vol_50"] = lr1.rolling(50).std()
    out["zret_1"] = lr1 / out["vol_20"]
    out["zret_5"] = out["logret_5"] / (out["vol_20"] * np.sqrt(5))

    # --- order flow imbalance ---
    ofi = bars["ofi"]
    out["ofi"] = ofi
    out["ofi_mean_20"] = ofi.rolling(20).mean()
    out["ofi_std_20"] = ofi.rolling(20).std()
    out["ofi_sum_50"] = ofi.rolling(50).sum()

    # --- tốc độ bar: bar đóng nhanh hơn bình thường = hoạt động đang dồn dập ---
    dur = (bars["t_close"] - bars["t_open"]).clip(lower=1).astype("float64")
    out["dur_log_ratio_20"] = np.log(dur / dur.rolling(20).median())

    # --- cấu trúc bar ---
    rng = bars["high"] - bars["low"]
    out["range_pct"] = rng / c
    # bar 1 giá (high==low): close ở "giữa" range
    out["close_pos"] = ((c - bars["low"]) / rng.replace(0.0, np.nan)).fillna(0.5)
    avg_trade = bars["vol_dollar"] / bars["n_trades"]
    out["trade_size_ratio_50"] = avg_trade / avg_trade.rolling(50).median()

    # --- thời gian (UTC, mã hóa chu kỳ để 23h kề 0h) ---
    hour_frac = (bars["t_close"] % 86_400_000) / 3_600_000.0
    out["hour_sin"] = np.sin(2 * np.pi * hour_frac / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour_frac / 24)
    # epoch ngày 0 (1970-01-01) là thứ 5 → dow: 0=Thứ2 như pandas
    dow = ((bars["t_close"] // 86_400_000) + 3) % 7
    out["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    out["dow_cos"] = np.cos(2 * np.pi * dow / 7)

    return out
