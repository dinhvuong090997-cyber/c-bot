# ===== Kaggle runner (nối vào cuối bundle bởi build_bars_kernel.sh) =====
# Tải trade data Bybit theo ngày (public.bybit.com), xử lý streaming qua
# process_stream (bars/pipeline.py), lưu dollar_bars.parquet + reports.
# START_DATE/END_DATE do build_bars_kernel.sh thay vào lúc build.
import json
import os
import time
import urllib.request
from datetime import date, timedelta

SYMBOL = "BTCUSDT"
START_DATE = date.fromisoformat("__START_DATE__")
END_DATE = date.fromisoformat("__END_DATE__")
TMP_DIR = "/kaggle/tmp" if os.path.isdir("/kaggle") else "./tmp_dl"
OUT_DIR = "/kaggle/working" if os.path.isdir("/kaggle") else "."


def download(url: str, dest: str, retries: int = 3) -> bool:
    """Tải 1 file, retry với backoff. Trả False nếu 404 (ngày không có)."""
    for attempt in range(retries):
        try:
            urllib.request.urlretrieve(url, dest)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    return False


def bybit_day_chunks(symbol: str, days: list[date]):
    """Generator: tải từng file ngày -> yield DataFrame raw -> xóa file.
    Mỗi thời điểm chỉ có 1 ngày data trong RAM/disk."""
    os.makedirs(TMP_DIR, exist_ok=True)
    for d in days:
        fname = f"{symbol}{d.isoformat()}.csv.gz"
        url = f"https://public.bybit.com/trading/{symbol}/{fname}"
        dest = os.path.join(TMP_DIR, fname)
        t0 = time.time()
        if not download(url, dest):
            print(f"   [WARN] {d}: file không tồn tại (404), bỏ qua", flush=True)
            continue
        df = load_bybit_csv(dest)
        os.remove(dest)
        print(f"   {d}: {len(df):,} trades "
              f"({time.time() - t0:.0f}s)", flush=True)
        yield df


if __name__ == "__main__":
    cfg = Config()
    n_days = (END_DATE - START_DATE).days + 1
    days = [START_DATE + timedelta(days=i) for i in range(n_days)]
    print(f"1) Xử lý {SYMBOL} {days[0]} -> {days[-1]} "
          f"({len(days)} ngày), threshold=${cfg.DOLLAR_THRESHOLD:,.0f}", flush=True)

    t_start = time.time()
    bars, reports = process_stream(bybit_day_chunks(SYMBOL, days), cfg)
    print(f"\n2) Xong sau {(time.time() - t_start) / 60:.1f} phút. "
          f"bars: {len(bars):,}", flush=True)

    print("\n3) Verify chất lượng bar:", flush=True)
    stats = verify_bars(bars)
    for k, v in stats.items():
        print(f"   {k}: {v}", flush=True)

    total_flagged = sum(r.get("outliers_flagged", 0) for r in reports)
    total_gaps = sum(r.get("gaps_over_threshold", 0) for r in reports)
    print(f"\n   outliers_flagged tổng: {total_flagged}", flush=True)
    print(f"   gaps tổng: {total_gaps}", flush=True)

    bars.to_parquet(os.path.join(OUT_DIR, "dollar_bars.parquet"), index=False)
    with open(os.path.join(OUT_DIR, "clean_reports.json"), "w") as f:
        json.dump(reports, f, ensure_ascii=False, indent=1, default=str)
    with open(os.path.join(OUT_DIR, "verify_stats.json"), "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nĐã lưu dollar_bars.parquet + reports vào {OUT_DIR}", flush=True)
