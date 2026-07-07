"""Vòng lặp demo-live: WS trades -> dollar bars -> features -> model -> lệnh.

Hai chế độ:
  --dry-run : không cần API key. Fill giả tại giá limit, TP/SL check bằng
              high/low bar — chỉ để xem pipeline chạy, PnL không có ý nghĩa
              fill thật (không có queue position, không adverse selection).
  mặc định  : gửi lệnh THẬT lên Bybit DEMO (api-demo.bybit.com, tiền ảo).
              Cần env BYBIT_DEMO_API_KEY / BYBIT_DEMO_API_SECRET
              (tạo trong Demo Trading trên bybit.com).

Warmup: cần 51 bars (~2-4h với threshold $10M) trước tín hiệu đầu tiên —
cứ để chạy. Mọi event ghi JSONL vào out/demo/ để phân tích fill-rate sau.

Dùng:
    python -m live.run_demo --ckpt out/train_final/model_final.pt \
        --threshold 0.45 --qty 0.001 [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd

from bars.pipeline import Config
from data.bybit_api import fetch_funding_history, fetch_oi_history
from execution.bybit_client import DEMO_URL, BybitClient
from execution.order_manager import ExecConfig, TradeManager
from live.bar_stream import LiveBarFeed, run_ws
from live.features_live import ALL_FEATURE_COLS, WARMUP_BARS, latest_features
from live.signal import engine_from_mlp_checkpoint
from risk.rules import RiskConfig, RiskManager

_H = 3_600_000


class DryRunExchange:
    """Fill giả: entry khớp ngay tại giá limit; TP/SL xét bằng high/low bar.
    Chỉ để chạy thử pipeline — không mô phỏng queue/adverse selection."""

    def __init__(self, log=print):
        self._log = log
        self._pos: dict = {}
        self._tp = self._sl = 0.0

    def place_order(self, order: dict) -> dict:
        self._log(f"[dry] lệnh: {order}")
        if order.get("reduceOnly"):
            self._pos = {}
        else:
            self._pos = {"size": order["qty"], "side": order["side"],
                         "avgPrice": order["price"]}
            self._tp, self._sl = float(order["takeProfit"]), float(order["stopLoss"])
        return {"orderId": "dry", "orderLinkId": order.get("orderLinkId", "")}

    def cancel_order(self, symbol: str, order_link_id: str) -> None:
        self._log(f"[dry] hủy {order_link_id}")

    def position(self, symbol: str) -> dict:
        return self._pos

    def check_barriers(self, bar: dict) -> None:
        if not self._pos:
            return
        hi, lo = float(bar["high"]), float(bar["low"])
        buy = self._pos["side"] == "Buy"
        tp_hit = hi >= self._tp if buy else lo <= self._tp
        sl_hit = lo <= self._sl if buy else hi >= self._sl
        if tp_hit or sl_hit:
            self._pos = {}


class DemoRunner:
    def __init__(self, engine, tm: TradeManager, rm: RiskManager,
                 journal_dir: Path, symbol: str, dry_ex: DryRunExchange | None):
        self.engine, self.tm, self.rm = engine, tm, rm
        self.symbol = symbol
        self.dry_ex = dry_ex
        self.bars = pd.DataFrame()
        self.funding = pd.DataFrame({"ts": [], "funding_rate": []})
        self.oi = pd.DataFrame({"ts": [], "oi": []})
        self._last_fund_fetch = 0.0
        self._last_oi_fetch = 0.0
        journal_dir.mkdir(parents=True, exist_ok=True)
        self._journal = open(journal_dir / "journal.jsonl", "a")
        self._bar_log = open(journal_dir / "bars.jsonl", "a")

    def _jlog(self, kind: str, payload: dict) -> None:
        rec = {"kind": kind, "wall_ms": int(time.time() * 1000), **payload}
        self._journal.write(json.dumps(rec) + "\n")
        self._journal.flush()

    def refresh_aux(self) -> None:
        """Funding mỗi giờ, OI mỗi 5 phút (đúng granularity nguồn)."""
        now = time.time()
        end = int(now * 1000)
        if now - self._last_fund_fetch > 3600:
            self.funding = fetch_funding_history(self.symbol, end - 5 * 24 * _H, end)
            self._last_fund_fetch = now
        if now - self._last_oi_fetch > 300:
            self.oi = fetch_oi_history(self.symbol, end - 30 * _H, end,
                                       log_every=0)
            self._last_oi_fetch = now

    def on_bars(self, new_bars: pd.DataFrame) -> None:
        for _, bar in new_bars.iterrows():
            self._step(bar.to_dict())

    def _step(self, bar: dict) -> None:
        self.bars = pd.concat([self.bars, pd.DataFrame([bar])],
                              ignore_index=True).tail(WARMUP_BARS + 10)
        self._bar_log.write(json.dumps(
            {k: bar[k] for k in ("t_close", "open", "high", "low", "close",
                                 "vol_dollar", "ofi", "n_trades")},
            default=str) + "\n")
        self._bar_log.flush()

        if self.dry_ex is not None:
            self.dry_ex.check_barriers(bar)

        # 1) tick state machine + báo risk
        for ev in self.tm.on_bar(bar):
            self._jlog("exec", ev)
            print(f"  >> {ev}")
            if ev["event"] in ("exited", "time_exit"):
                self.rm.on_exit(int(bar["t_close"]), ev["pnl_approx"])
            elif ev["event"] == "entry_cancelled":
                self.rm.on_exit(int(bar["t_close"]), 0.0)  # giải phóng slot

        n = len(self.bars)
        if n < WARMUP_BARS:
            if n % 5 == 0 or n == 1:
                print(f"warmup {n}/{WARMUP_BARS} bars "
                      f"(close={bar['close']:.1f})")
            return
        if self.tm.state != "IDLE":
            return

        # 2) features + tín hiệu
        self.refresh_aux()
        feat = latest_features(self.bars, self.funding, self.oi)
        if feat[ALL_FEATURE_COLS].isna().any():
            miss = [c for c in ALL_FEATURE_COLS if pd.isna(feat[c])]
            print(f"bar {int(bar['t_close'])}: thiếu features {miss} — bỏ qua")
            return
        sig = self.engine.decide(feat)
        if sig is None:
            return
        self._jlog("signal", vars(sig))

        # 3) risk gate + đặt lệnh
        ok, reason = self.rm.allow_entry(int(bar["t_close"]))
        if not ok:
            print(f"tín hiệu {sig.side} conf={sig.conf:.2f} bị chặn: {reason}")
            self._jlog("blocked", {"reason": reason, "side": sig.side})
            return
        if self.tm.submit(sig):
            self.rm.on_entry(int(bar["t_close"]))
            print(f"ĐẶT {sig.side} conf={sig.conf:.2f} @ {sig.entry_ref:.1f} "
                  f"TP {sig.tp_price:.1f} / SL {sig.sl_price:.1f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", default="out/train_final/model_final.pt")
    p.add_argument("--threshold", type=float, default=0.45)
    p.add_argument("--qty", type=float, default=0.001)
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--journal-dir", default="out/demo")
    p.add_argument("--max-trades-per-day", type=int, default=30)
    p.add_argument("--daily-loss-limit", type=float, default=0.02)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    engine = engine_from_mlp_checkpoint(a.ckpt, conf_threshold=a.threshold)
    print(f"model: {a.ckpt} | horizon={engine.cfg.horizon} "
          f"width_mult={engine.cfg.width_mult} threshold={a.threshold}")

    if a.dry_run:
        exchange: object = DryRunExchange()
        print("chế độ DRY-RUN — không gửi lệnh thật")
    else:
        key = os.environ.get("BYBIT_DEMO_API_KEY", "")
        secret = os.environ.get("BYBIT_DEMO_API_SECRET", "")
        if not key or not secret:
            raise SystemExit("cần env BYBIT_DEMO_API_KEY / BYBIT_DEMO_API_SECRET "
                             "(hoặc chạy --dry-run)")
        exchange = BybitClient(key, secret, base_url=DEMO_URL)
        print(f"demo API: {DEMO_URL} | equity={exchange.wallet_equity():,.0f} USDT")

    tm = TradeManager(exchange, ExecConfig(symbol=a.symbol, qty=a.qty))
    rm = RiskManager(RiskConfig(max_trades_per_day=a.max_trades_per_day,
                                daily_loss_limit=a.daily_loss_limit))
    runner = DemoRunner(engine, tm, rm, Path(a.journal_dir), a.symbol,
                        exchange if a.dry_run else None)
    runner.refresh_aux()
    print(f"funding: {len(runner.funding)} kỳ | OI: {len(runner.oi)} snapshots")

    feed = LiveBarFeed(Config(), on_bar=runner.on_bars)
    print(f"stream {a.symbol}, chờ warmup {WARMUP_BARS} bars "
          f"(~2-4h với bar $10M)...")
    run_ws(feed, symbol=a.symbol)


if __name__ == "__main__":
    main()
