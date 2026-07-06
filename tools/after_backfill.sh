#!/usr/bin/env bash
# Chạy sau khi kernel cbot-dollar-bars (backfill) COMPLETE:
#   1) tải bars từ kernel output
#   2) fetch funding + OI cùng khoảng thời gian (local — Bybit chặn IP US của Kaggle)
#   3) đẩy tất cả lên dataset cbot-btcusdt-dollar-bars (version mới)
#   4) build + push kernel cbot-features (đọc dataset, ghi features.parquet)
set -euo pipefail
cd "$(dirname "$0")/.."
KOUT=data/cache/backfill
mkdir -p "$KOUT"

echo "== 1) Tải output kernel bars =="
uvx kaggle kernels output vuongnguyen0909/cbot-dollar-bars -p "$KOUT"
rm -f "$KOUT/cbot-dollar-bars.log"

echo "== 2) Fetch funding + OI từ Bybit (local) =="
uv run python - <<'PY'
import pandas as pd
from data.bybit_api import fetch_funding_history, fetch_oi_history
H = 3_600_000
bars = pd.read_parquet("data/cache/backfill/dollar_bars.parquet")
t0, t1 = int(bars["t_close"].iloc[0]), int(bars["t_close"].iloc[-1])
print(f"bars: {len(bars):,} | {pd.Timestamp(t0, unit='ms', tz='UTC')} -> {pd.Timestamp(t1, unit='ms', tz='UTC')}")
f = fetch_funding_history("BTCUSDT", t0 - 4 * 24 * H, t1)   # lùi 4 ngày cho fund_sum_9
f.to_parquet("data/cache/backfill/funding.parquet", index=False)
print(f"funding: {len(f):,} kỳ")
o = fetch_oi_history("BTCUSDT", t0 - 26 * H, t1)             # lùi 26h cho oi_chg_24h
o.to_parquet("data/cache/backfill/oi.parquet", index=False)
print(f"OI: {len(o):,} snapshots")
PY

echo "== 3) Update dataset (version mới) =="
cat > "$KOUT/dataset-metadata.json" <<'JSON'
{
  "title": "cbot BTCUSDT dollar bars",
  "id": "vuongnguyen0909/cbot-btcusdt-dollar-bars",
  "licenses": [{"name": "CC0-1.0"}]
}
JSON
uvx kaggle datasets version -p "$KOUT" -m "backfill + funding/OI cache $(date +%F)"
echo "  chờ Kaggle xử lý version mới..."
sleep 90

echo "== 4) Build + push kernel features =="
tools/build_features_kernel.sh
uvx kaggle kernels push -p kernel_features
echo
echo "Theo dõi:   uvx kaggle kernels status vuongnguyen0909/cbot-features"
echo "Lấy output: uvx kaggle kernels output vuongnguyen0909/cbot-features -p <dir>"
