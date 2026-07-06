"""Tests cho ban sua pipeline: stateful bar builder + per-file cleaning."""
import numpy as np
import pandas as pd
import pytest

from bars.pipeline import (
    Config,
    DollarBarBuilder,
    TradeCleaner,
    make_synthetic_trades,
    process_stream,
)


@pytest.fixture(scope="module")
def trades():
    # nho de test nhanh; du de tao vai tram bar
    df = make_synthetic_trades(n_trades=100_000, seed=7)
    cleaner = TradeCleaner(Config())
    out, _ = cleaner.clean(df)
    return out


def split_chunks(df, n):
    """Cat DataFrame thanh n phan KHONG deu nhau (mo phong file ngay)."""
    rng = np.random.default_rng(0)
    cuts = np.sort(rng.choice(np.arange(1, len(df)), size=n - 1, replace=False))
    return [df.iloc[a:b].reset_index(drop=True)
            for a, b in zip([0, *cuts], [*cuts, len(df)])]


# ---------------------------------------------------------------------
# 1. LOI CHINH: chunked phai bang CHINH XAC whole-stream
# ---------------------------------------------------------------------
def test_chunked_equals_whole(trades):
    cfg = Config()
    whole = DollarBarBuilder(cfg).update(trades)

    builder = DollarBarBuilder(cfg)
    parts = [builder.update(c) for c in split_chunks(trades, 9)]
    chunked = pd.concat(parts, ignore_index=True)

    assert len(whole) > 50, "fixture qua nho, test vo nghia"
    pd.testing.assert_frame_equal(chunked, whole)


def test_partial_bar_carried_across_updates(trades):
    """Bar mo dang do o cuoi chunk A phai duoc noi tiep sang chunk B:
    t_open cua bar bac cau phai nam trong chunk A."""
    cfg = Config()
    whole = DollarBarBuilder(cfg).update(trades)

    # cat giua mot bar: lay diem giua t_open va t_close cua bar ~10
    bar = whole.iloc[10]
    cut_ts = (bar["t_open"] + bar["t_close"]) // 2
    a = trades[trades["ts"] <= cut_ts].reset_index(drop=True)
    b = trades[trades["ts"] > cut_ts].reset_index(drop=True)
    assert bar["t_open"] <= a["ts"].iloc[-1] < bar["t_close"], "diem cat phai nam giua bar"

    builder = DollarBarBuilder(cfg)
    bars_a = builder.update(a)
    assert builder.partial_dollar > 0, "phai co bar dang do sau chunk A"
    bars_b = builder.update(b)

    bridged = pd.concat([bars_a, bars_b], ignore_index=True)
    pd.testing.assert_frame_equal(bridged, whole)


def test_leftover_tail_is_reported_not_lost(trades):
    cfg = Config()
    builder = DollarBarBuilder(cfg)
    bars = builder.update(trades)
    total_in = float((trades["price"] * trades["size"]).sum())
    total_bars = float(bars["vol_dollar"].sum())
    assert builder.partial_dollar == pytest.approx(total_in - total_bars)


# ---------------------------------------------------------------------
# 2. Bar invariants (giu nguyen hanh vi dung cua ban cu)
# ---------------------------------------------------------------------
def test_bar_invariants(trades):
    cfg = Config()
    bars = DollarBarBuilder(cfg).update(trades)
    assert (bars["vol_dollar"] >= cfg.DOLLAR_THRESHOLD).all()
    assert (bars["high"] >= bars[["open", "close"]].max(axis=1)).all()
    assert (bars["low"] <= bars[["open", "close"]].min(axis=1)).all()
    assert bars["t_close"].is_monotonic_increasing
    # bar sau mo SAU khi bar truoc dong
    assert (bars["t_open"].to_numpy()[1:] > bars["t_close"].to_numpy()[:-1]).all()
    # ofi trong [-1, 1], khong NaN (moi bar co >=1 trade size>0)
    assert bars["ofi"].between(-1, 1).all()
    assert not bars["ofi"].isna().any()
    # vol_base = buy + sell
    np.testing.assert_allclose(bars["vol_base"], bars["buy_vol"] + bars["sell_vol"])


# ---------------------------------------------------------------------
# 3. Cleaning: dedup xuyen ranh gioi file + memory-lean dtypes
# ---------------------------------------------------------------------
def test_dedup_within_chunk():
    df = make_synthetic_trades(n_trades=5_000, seed=1)  # da chua ~0.1% dup
    cleaner = TradeCleaner(Config())
    out, report = cleaner.clean(df)
    assert report["duplicates_removed"] > 0
    assert out["tid"].is_unique


def test_dedup_across_chunk_boundary():
    df = make_synthetic_trades(n_trades=5_000, seed=2)
    df = df.drop_duplicates(subset="tid").reset_index(drop=True)
    mid = len(df) // 2
    a = df.iloc[:mid].reset_index(drop=True)
    # chunk B lap lai 50 trade cuoi cua A (mo phong file ngay chong lan)
    b = pd.concat([a.tail(50), df.iloc[mid:]], ignore_index=True)

    cleaner = TradeCleaner(Config())
    out_a, _ = cleaner.clean(a)
    out_b, report_b = cleaner.clean(b)
    assert report_b["duplicates_removed"] == 50
    combined = pd.concat([out_a, out_b], ignore_index=True)
    assert combined["tid"].is_unique


def test_clean_output_dtypes_memory_lean():
    df = make_synthetic_trades(n_trades=2_000, seed=3)
    out, _ = cleaner_clean_once(df)
    assert out["ts"].dtype == np.int64
    assert out["price"].dtype == np.float64
    assert out["size"].dtype == np.float64
    # side object -> is_buy bool (tiet kiem ~60 bytes/row)
    assert "is_buy" in out.columns
    assert out["is_buy"].dtype == np.bool_
    assert "side" not in out.columns


def cleaner_clean_once(df):
    return TradeCleaner(Config()).clean(df)


# ---------------------------------------------------------------------
# 4. Outlier: mac dinh CHI CANH BAO (log-only), khong xoa trade that
# ---------------------------------------------------------------------
def test_outlier_log_only_by_default():
    df = make_synthetic_trades(n_trades=5_000, seed=4)
    df = df.drop_duplicates(subset="tid").reset_index(drop=True)
    n_before = len(df)
    # fat-finger 20% spike don le
    df.loc[2500, "price"] *= 1.20
    cfg = Config()
    assert cfg.REMOVE_OUTLIERS is False
    out, report = TradeCleaner(cfg).clean(df)
    assert report["outliers_flagged"] >= 1
    assert len(out) == n_before, "log-only: khong duoc xoa dong nao"


def test_outlier_removed_when_enabled():
    df = make_synthetic_trades(n_trades=5_000, seed=4)
    df = df.drop_duplicates(subset="tid").reset_index(drop=True)
    spike_tid = df.loc[2500, "tid"]
    df.loc[2500, "price"] *= 1.20
    cfg = Config()
    cfg.REMOVE_OUTLIERS = True
    out, report = TradeCleaner(cfg).clean(df)
    assert report["outliers_flagged"] >= 1
    assert spike_tid not in set(out["tid"])


def test_outlier_filter_is_causal():
    """Median lan chi duoc nhin QUA KHU (trailing) — khong center."""
    n = 3_000
    ts = np.arange(n) * 100 + 1_700_000_000_000
    price = np.full(n, 60_000.0)
    price[1500] = 72_000.0  # spike +20%
    df = pd.DataFrame({"ts": ts, "price": price, "size": np.ones(n),
                       "side": "Buy", "tid": np.arange(n).astype(str)})
    cfg = Config()
    cfg.REMOVE_OUTLIERS = True
    # chunked va whole phai cho cung ket qua (tail buffer duoc carry)
    cleaner_w = TradeCleaner(cfg)
    whole, _ = cleaner_w.clean(df)
    cleaner_c = TradeCleaner(cfg)
    a, _ = cleaner_c.clean(df.iloc[:1400].reset_index(drop=True))
    b, _ = cleaner_c.clean(df.iloc[1400:].reset_index(drop=True))
    chunked = pd.concat([a, b], ignore_index=True)
    pd.testing.assert_frame_equal(chunked, whole)


# ---------------------------------------------------------------------
# 5. Gap check xuyen ranh gioi chunk
# ---------------------------------------------------------------------
def test_gap_detected_across_chunk_boundary():
    ts_a = np.arange(1000) * 100 + 1_700_000_000_000
    # chunk B bat dau sau 10 phut (gap > GAP_WARN_SECONDS)
    ts_b = np.arange(1000) * 100 + ts_a[-1] + 600_000
    mk = lambda ts, off: pd.DataFrame({
        "ts": ts, "price": 60_000.0, "size": 1.0, "side": "Buy",
        "tid": (np.arange(len(ts)) + off).astype(str)})
    cleaner = TradeCleaner(Config())
    _, ra = cleaner.clean(mk(ts_a, 0))
    _, rb = cleaner.clean(mk(ts_b, 10_000))
    assert ra["gaps_over_threshold"] == 0
    assert rb["gaps_over_threshold"] == 1, "gap giua 2 chunk phai duoc phat hien"


# ---------------------------------------------------------------------
# 6. process_stream: driver end-to-end tren iterator cua chunks
# ---------------------------------------------------------------------
def test_process_stream_end_to_end(trades):
    cfg = Config()
    raw = make_synthetic_trades(n_trades=100_000, seed=7)
    chunks = split_chunks(raw, 5)
    bars, reports = process_stream(iter(chunks), cfg)

    # so voi lam sach + build lien mach
    clean_whole, _ = TradeCleaner(cfg).clean(raw)
    whole = DollarBarBuilder(cfg).update(clean_whole)
    pd.testing.assert_frame_equal(bars, whole)
    assert len(reports) == 5


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
