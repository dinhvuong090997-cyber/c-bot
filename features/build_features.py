"""CLI stage 2: dollar_bars.parquet -> features.parquet

Ghép 21 bar features + 4 funding + 4 OI = 29 features, rồi drop các hàng
warmup/thiếu dữ liệu (NaN). Funding/OI lấy từ Bybit API và cache ra parquet
để chạy lại không phải fetch.

Dùng:
    python -m features.build_features --bars dollar_bars.parquet --out features.parquet
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

from data.bybit_api import fetch_funding_history, fetch_oi_history
from features.aux_features import (
    FUNDING_FEATURE_COLS, OI_FEATURE_COLS,
    add_funding_features, add_oi_features,
)
from features.bar_features import FEATURE_COLS, compute_bar_features

_H = 3_600_000


def _cached(path: str, fetch_fn):
    if path and os.path.exists(path):
        print(f"  cache hit: {path}")
        return pd.read_parquet(path)
    df = fetch_fn()
    if path:
        df.to_parquet(path, index=False)
    return df


def build(bars_path: str, out_path: str, symbol: str = "BTCUSDT",
          funding_cache: str = "", oi_cache: str = "") -> pd.DataFrame:
    bars = pd.read_parquet(bars_path)
    t0, t1 = int(bars["t_close"].iloc[0]), int(bars["t_close"].iloc[-1])
    print(f"bars: {len(bars):,} | {pd.Timestamp(t0, unit='ms', tz='UTC')} -> "
          f"{pd.Timestamp(t1, unit='ms', tz='UTC')}")

    print("1) bar features...")
    feats = compute_bar_features(bars)

    print("2) funding history...")
    # lùi 4 ngày để fund_sum_9 (9 kỳ x 8h) đủ warmup ngay từ bar đầu
    funding = _cached(funding_cache, lambda: fetch_funding_history(
        symbol, t0 - 4 * 24 * _H, t1))
    print(f"  {len(funding):,} kỳ funding")
    feats = add_funding_features(feats, funding)

    print("3) open interest...")
    oi = _cached(oi_cache, lambda: fetch_oi_history(
        symbol, t0 - 26 * _H, t1))  # lùi 26h cho oi_chg_24h
    print(f"  {len(oi):,} snapshots OI")
    feats = add_oi_features(feats, oi)

    all_cols = FEATURE_COLS + FUNDING_FEATURE_COLS + OI_FEATURE_COLS
    n_before = len(feats)
    feats = feats.dropna(subset=all_cols).reset_index(drop=True)
    print(f"4) drop warmup/NaN: {n_before:,} -> {len(feats):,} hàng, "
          f"{len(all_cols)} features")

    feats.to_parquet(out_path, index=False)
    print(f"-> {out_path}")
    return feats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bars", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--funding-cache", default="")
    p.add_argument("--oi-cache", default="")
    a = p.parse_args()
    build(a.bars, a.out, a.symbol, a.funding_cache, a.oi_cache)


if __name__ == "__main__":
    main()
