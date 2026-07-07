"""Scorecard counterfactual cho LLM veto — veto tiết kiệm hay đốt tiền?

pa-model phải nhờ LLM reflection + trust Laplace vì không biết lệnh bị skip
sẽ ra sao. c-bot thì biết chính xác: journal ghi đủ barrier (entry_ref/
tp_price/sl_price/horizon) và bars.jsonl ghi đủ OHLC, nên replay từng tín
hiệu qua backtest/fills.py (cùng quy tắc conservative với backtest) cho ra
net_ret lệnh ĐÃ CÓ THỂ xảy ra — cả nhóm bị veto lẫn nhóm được duyệt.

veto_value_bps của nhóm approve=False = -mean(net_ret): dương nghĩa là
veto tránh được lỗ (giữ veto), âm nghĩa là veto chặn lệnh thắng (nới gate).

Dùng:
    uv run python -m tools.veto_scorecard --journal-dir out/live
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.fills import FillConfig, simulate_trades
from model.labels import LabelConfig

_BAR_COLS = ("t_close", "open", "high", "low", "close")


def load_bars(path: Path) -> pd.DataFrame:
    """bars.jsonl -> DataFrame numeric, sort theo t_close. Giá trị có thể
    là string (json.dumps default=str với numpy scalar)."""
    rows = [json.loads(x) for x in Path(path).read_text().splitlines() if x]
    bars = pd.DataFrame(rows)
    for c in _BAR_COLS:
        bars[c] = pd.to_numeric(bars[c])
    bars["t_close"] = bars["t_close"].astype("int64")
    return bars.sort_values("t_close", ignore_index=True)


def load_decisions(path: Path) -> pd.DataFrame:
    """journal.jsonl -> mỗi dòng 1 quyết định veto ghép với signal ngay
    trước nó (run_demo ghi signal rồi veto liền kề). Signal không có veto
    (chạy --no-llm) bị bỏ qua."""
    rows = []
    last_sig = None
    for line in Path(path).read_text().splitlines():
        if not line:
            continue
        rec = json.loads(line)
        if rec["kind"] == "signal":
            last_sig = rec
        elif rec["kind"] == "veto" and last_sig is not None:
            rows.append({
                "t_close": int(last_sig["t_close"]),
                "side": last_sig["side"], "conf": float(last_sig["conf"]),
                "entry_ref": float(last_sig["entry_ref"]),
                "tp_price": float(last_sig["tp_price"]),
                "sl_price": float(last_sig["sl_price"]),
                "horizon_bars": int(last_sig["horizon_bars"]),
                "approve": bool(rec["approve"]), "source": rec["source"],
                "reason": rec.get("reason", ""),
            })
            last_sig = None
    return pd.DataFrame(rows)


def replay(bars: pd.DataFrame, decisions: pd.DataFrame,
           fcfg: FillConfig = FillConfig()) -> pd.DataFrame:
    """Chạy từng quyết định qua simulate_trades (width lấy từ barrier đã
    ghi: |ln(tp/entry)| — đúng width labels.py đã dùng lúc phát tín hiệu).
    Gọi từng-signal-một vì mỗi signal có width/horizon riêng."""
    bars_t = bars["t_close"].to_numpy()
    out = []
    for _, d in decisions.iterrows():
        idx = int(np.searchsorted(bars_t, d["t_close"]))
        if idx >= len(bars_t) or bars_t[idx] != d["t_close"]:
            continue  # bar tín hiệu không có trong bars.jsonl
        width = abs(np.log(d["tp_price"] / d["entry_ref"]))
        sig = pd.DataFrame({"bar_idx": [idx],
                            "direction": [1 if d["side"] == "Buy" else -1],
                            "confidence": [d["conf"]]})
        lcfg = LabelConfig(horizon=int(d["horizon_bars"]), width_mult=1.0)
        tr = simulate_trades(bars, sig, lcfg, fcfg,
                             width=np.full(len(bars), width)).iloc[0]
        row = d.to_dict()
        row.update(filled=bool(tr["filled"]), complete=bool(tr["complete"]),
                   exit_type=tr["exit_type"], net_ret=tr["net_ret"])
        out.append(row)
    return pd.DataFrame(out)


def summarize(replayed: pd.DataFrame) -> pd.DataFrame:
    """Tổng hợp theo (source, approve). veto_value_bps chỉ có nghĩa với
    nhóm approve=False: -mean(net_ret) — dương = veto tránh được lỗ."""
    rows = []
    for (source, approve), g in replayed.groupby(["source", "approve"]):
        done = g[g["filled"] & g["complete"]]
        net = done["net_ret"].to_numpy()
        mean_bps = float(net.mean() * 1e4) if len(net) else float("nan")
        rows.append({
            "source": source, "approve": approve, "n": len(g),
            "n_done": len(done),
            "mean_net_ret_bps": mean_bps,
            "total_net_ret_bps": float(net.sum() * 1e4) if len(net) else 0.0,
            "veto_value_bps": -mean_bps if not approve else float("nan"),
        })
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--journal-dir", default="out/live")
    a = p.parse_args()
    d = Path(a.journal_dir)
    decisions = load_decisions(d / "journal.jsonl")
    if decisions.empty:
        print("chưa có quyết định veto nào trong journal")
        return
    bars = load_bars(d / "bars.jsonl")
    rep = replay(bars, decisions)
    pd.set_option("display.width", 200)
    print(summarize(rep).to_string(index=False))
    blocked = rep[~rep["approve"] & rep["filled"] & rep["complete"]]
    if len(blocked):
        saved = -blocked["net_ret"].sum() * 1e4
        print(f"\nTổng giá trị veto: {saved:+.1f}bps "
              f"({'tiết kiệm' if saved > 0 else 'ĐỐT'} so với không veto)")


if __name__ == "__main__":
    main()
