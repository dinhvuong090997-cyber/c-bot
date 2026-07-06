"""Client tối giản cho Bybit v5 public market API (không cần key).

Dùng cho funding rate history + open interest history. Parsers tách riêng
(pure function) để test được bằng fixture JSON; fetch loop chỉ là pagination.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import requests

BASE_URL = "https://api.bybit.com"
_PAUSE = 0.15  # lịch sự với rate limit public


def parse_funding(payload: dict) -> pd.DataFrame:
    """result.list (mới nhất trước) -> DataFrame [ts int64 ms, funding_rate f64] tăng dần."""
    rows = payload["result"]["list"]
    df = pd.DataFrame({
        "ts": np.array([int(r["fundingRateTimestamp"]) for r in rows], dtype=np.int64),
        "funding_rate": np.array([float(r["fundingRate"]) for r in rows], dtype=np.float64),
    })
    return df.sort_values("ts", ignore_index=True)


def parse_oi(payload: dict) -> pd.DataFrame:
    """result.list (mới nhất trước) -> DataFrame [ts int64 ms, oi f64] tăng dần."""
    rows = payload["result"]["list"]
    df = pd.DataFrame({
        "ts": np.array([int(r["timestamp"]) for r in rows], dtype=np.int64),
        "oi": np.array([float(r["openInterest"]) for r in rows], dtype=np.float64),
    })
    return df.sort_values("ts", ignore_index=True)


def _get(path: str, params: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            r = requests.get(BASE_URL + path, params=params, timeout=20)
            r.raise_for_status()
            j = r.json()
            if j.get("retCode") != 0:
                raise RuntimeError(f"Bybit retCode={j.get('retCode')}: {j.get('retMsg')}")
            return j
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def fetch_funding_history(symbol: str, start_ms: int, end_ms: int,
                          category: str = "linear") -> pd.DataFrame:
    """Toàn bộ kỳ funding trong [start_ms, end_ms]. API trả tối đa 200 kỳ
    mới nhất mỗi lần → lùi endTime về quá khứ cho tới khi phủ hết."""
    chunks = []
    end = end_ms
    while end > start_ms:
        j = _get("/v5/market/funding/history", {
            "category": category, "symbol": symbol,
            "startTime": start_ms, "endTime": end, "limit": 200,
        })
        df = parse_funding(j)
        if df.empty:
            break
        chunks.append(df)
        oldest = int(df["ts"].iloc[0])
        if oldest <= start_ms:
            break
        end = oldest - 1
        time.sleep(_PAUSE)
    if not chunks:
        return pd.DataFrame({"ts": pd.Series(dtype=np.int64),
                             "funding_rate": pd.Series(dtype=np.float64)})
    out = pd.concat(chunks, ignore_index=True).drop_duplicates("ts")
    out = out[out["ts"] >= start_ms]
    return out.sort_values("ts", ignore_index=True)


def fetch_oi_history(symbol: str, start_ms: int, end_ms: int,
                     interval: str = "5min", category: str = "linear",
                     log_every: int = 200) -> pd.DataFrame:
    """Open interest snapshots trong [start_ms, end_ms], phân trang bằng cursor."""
    chunks = []
    cursor = None
    page = 0
    while True:
        params = {
            "category": category, "symbol": symbol, "intervalTime": interval,
            "startTime": start_ms, "endTime": end_ms, "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        j = _get("/v5/market/open-interest", params)
        df = parse_oi(j)
        if df.empty:
            break
        chunks.append(df)
        page += 1
        if log_every and page % log_every == 0:
            print(f"  OI page {page}, tới {pd.Timestamp(int(df['ts'].iloc[0]), unit='ms', tz='UTC')}")
        cursor = j["result"].get("nextPageCursor")
        if not cursor:
            break
        time.sleep(_PAUSE)
    if not chunks:
        return pd.DataFrame({"ts": pd.Series(dtype=np.int64),
                             "oi": pd.Series(dtype=np.float64)})
    out = pd.concat(chunks, ignore_index=True).drop_duplicates("ts")
    return out.sort_values("ts", ignore_index=True)
