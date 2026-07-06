"""Features funding + open interest, ghép vào bảng features theo t_close.

Point-in-time: tại t_close chỉ dùng bản ghi có ts <= t_close (asof backward).
Funding settle mỗi 8h tại 00/08/16 UTC; OI là snapshot 5 phút.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FUNDING_FEATURE_COLS = ["fund_rate", "fund_chg", "fund_sum_9", "hrs_to_funding"]
OI_FEATURE_COLS = ["oi_chg_1h", "oi_chg_4h", "oi_chg_24h", "oi_price_div_4h"]

_H = 3_600_000  # ms


def _asof(ts_query: np.ndarray, ts_ref: np.ndarray, val_ref: np.ndarray) -> np.ndarray:
    """Giá trị val_ref tại bản ghi ts_ref gần nhất <= ts_query; NaN nếu chưa có."""
    idx = np.searchsorted(ts_ref, ts_query, side="right") - 1
    out = np.full(len(ts_query), np.nan)
    ok = idx >= 0
    out[ok] = val_ref[idx[ok]]
    return out


def add_funding_features(feats: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    """feats cần cột t_close (ms, tăng dần); funding = [ts, funding_rate] tăng dần."""
    out = feats.copy()
    f = funding.sort_values("ts", ignore_index=True)
    fund_chg = f["funding_rate"].diff()
    fund_sum_9 = f["funding_rate"].rolling(9).sum()  # 9 kỳ x 8h = 3 ngày

    t = out["t_close"].to_numpy(dtype=np.int64)
    ts_ref = f["ts"].to_numpy(dtype=np.int64)
    out["fund_rate"] = _asof(t, ts_ref, f["funding_rate"].to_numpy())
    out["fund_chg"] = _asof(t, ts_ref, fund_chg.to_numpy())
    out["fund_sum_9"] = _asof(t, ts_ref, fund_sum_9.to_numpy())
    # kỳ funding tới luôn ở mốc 8h kế tiếp (00/08/16 UTC)
    out["hrs_to_funding"] = 8.0 - (t % (8 * _H)) / _H
    return out


def add_oi_features(feats: pd.DataFrame, oi: pd.DataFrame) -> pd.DataFrame:
    """feats cần t_close + close; oi = [ts, oi] tăng dần."""
    out = feats.copy()
    o = oi.sort_values("ts", ignore_index=True)
    ts_ref = o["ts"].to_numpy(dtype=np.int64)
    oi_val = o["oi"].to_numpy()

    t = out["t_close"].to_numpy(dtype=np.int64)
    now = _asof(t, ts_ref, oi_val)
    for h in (1, 4, 24):
        ago = _asof(t - h * _H, ts_ref, oi_val)
        out[f"oi_chg_{h}h"] = now / ago - 1.0

    # phân kỳ OI–giá: OI tăng khi giá giảm = short mới vào (âm), v.v.
    close_ago_4h = _asof(t - 4 * _H, t, out["close"].to_numpy())
    price_dir = np.sign(out["close"].to_numpy() - close_ago_4h)
    out["oi_price_div_4h"] = out["oi_chg_4h"] * price_dir
    return out
