"""Tính 29 features cho bar MỚI NHẤT từ cửa sổ bars gần đây.

Tái dùng nguyên các hàm batch (features/bar_features.py + aux_features.py)
trên cửa sổ WARMUP_BARS bar cuối rồi lấy hàng chót — mọi rolling window dài
nhất là 50 nên 51 bar là đủ để hàng chót giống hệt chạy trên toàn bộ lịch sử
(được khóa bằng golden test trong tests/test_features_live.py).

funding/oi: bảng lịch sử như data/bybit_api.py trả về; asof backward nên chỉ
bản ghi ts <= t_close được dùng (point-in-time). Cần >= 10 kỳ funding
(fund_sum_9 + diff) và >= 24h OI để không NaN.
"""
from __future__ import annotations

import pandas as pd

from features.aux_features import (FUNDING_FEATURE_COLS, OI_FEATURE_COLS,
                                   add_funding_features, add_oi_features)
from features.bar_features import FEATURE_COLS, compute_bar_features

# rolling(50) trên logret_1 cần 51 close
WARMUP_BARS = 51

ALL_FEATURE_COLS = FEATURE_COLS + FUNDING_FEATURE_COLS + OI_FEATURE_COLS


def latest_features(bars_window: pd.DataFrame, funding: pd.DataFrame,
                    oi: pd.DataFrame) -> pd.Series:
    """bars_window: >= WARMUP_BARS bar cuối (schema DollarBarBuilder).
    Trả về Series: t_close, close + ALL_FEATURE_COLS của bar chót."""
    if len(bars_window) < WARMUP_BARS:
        raise ValueError(
            f"cần >= {WARMUP_BARS} bars warmup, chỉ có {len(bars_window)}")
    window = bars_window.tail(WARMUP_BARS).reset_index(drop=True)
    f = compute_bar_features(window)
    f = add_funding_features(f, funding)
    f = add_oi_features(f, oi)
    return f.iloc[-1]
