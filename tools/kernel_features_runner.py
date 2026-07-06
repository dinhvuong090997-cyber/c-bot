# ===== Kaggle runner (được nối vào cuối bundle bởi build_features_kernel.sh) =====
import os as _os

def _load_or_fetch(path, fetch, name):
    if _os.path.exists(path):
        print(f"  {name}: dùng cache {path}")
        return pd.read_parquet(path)
    print(f"  {name}: fetch từ Bybit API...")
    return fetch()


if __name__ == "__main__":
    _H = 3_600_000
    IN = _os.environ.get("CBOT_IN", "/kaggle/input/cbot-btcusdt-dollar-bars")
    OUT = _os.environ.get("CBOT_OUT", "/kaggle/working")

    bars = pd.read_parquet(f"{IN}/dollar_bars.parquet")
    t0, t1 = int(bars["t_close"].iloc[0]), int(bars["t_close"].iloc[-1])
    print(f"bars: {len(bars):,} | {pd.Timestamp(t0, unit='ms', tz='UTC')} -> "
          f"{pd.Timestamp(t1, unit='ms', tz='UTC')}")

    print("1) bar features...")
    feats = compute_bar_features(bars)

    print("2) funding...")
    funding = _load_or_fetch(
        f"{IN}/funding.parquet",
        lambda: fetch_funding_history("BTCUSDT", t0 - 4 * 24 * _H, t1), "funding")
    print(f"  {len(funding):,} kỳ funding")
    feats = add_funding_features(feats, funding)

    print("3) open interest...")
    oi = _load_or_fetch(
        f"{IN}/oi.parquet",
        lambda: fetch_oi_history("BTCUSDT", t0 - 26 * _H, t1), "OI")
    print(f"  {len(oi):,} snapshots OI")
    feats = add_oi_features(feats, oi)

    cols = FEATURE_COLS + FUNDING_FEATURE_COLS + OI_FEATURE_COLS
    n0 = len(feats)
    feats = feats.dropna(subset=cols).reset_index(drop=True)
    print(f"4) drop warmup/NaN: {n0:,} -> {len(feats):,} hàng, {len(cols)} features")

    feats.to_parquet(f"{OUT}/features.parquet", index=False)
    # lưu kèm funding/OI để làm cache cho lần chạy sau / stage sau
    funding.to_parquet(f"{OUT}/funding.parquet", index=False)
    oi.to_parquet(f"{OUT}/oi.parquet", index=False)
    print(f"-> {OUT}/features.parquet")
