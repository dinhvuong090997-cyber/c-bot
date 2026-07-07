"""Lớp LLM veto — nằm giữa SignalEngine và TradeManager.

Kiến trúc khóa từ đầu: model MLP quyết định hướng, LLM CHỈ được veto —
không bao giờ tự phát tín hiệu hay đảo hướng. Baseline đã backtest là
model chạy một mình có edge dương, nên:
  - LLM mặc định approve; chỉ veto khi thấy điều kiện bất thường CỤ THỂ
    trong data đưa vào (không đoán mò macro/news ngoài context).
  - Lỗi API / JSON hỏng / timeout -> FAIL-OPEN (approve) kèm reason,
    vì chặn nhầm phá edge nhiều hơn là cho qua.

Gọi Claude qua SDK anthropic, structured output (json_schema) để parse
chắc chắn, effort=low + không thinking cho latency thấp (bar dollar đóng
vài phút một lần nên 1-2s là thoải mái).
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from llm.anomaly import AnomalyConfig, anomaly_flags, sanity_errors

SYSTEM_PROMPT = """\
You are the risk-control VETO layer of an automated BTCUSDT perpetual \
trading bot on Bybit. A neural network trained on dollar-bar features has \
just issued a trade signal. The model's backtested edge IS the baseline: \
your only job is to veto the trade when the provided data shows a concrete, \
abnormal condition where that model is likely unreliable — never to \
second-guess its directional call in normal conditions.

Veto ONLY for observable evidence in the data, such as:
- extreme one-sided move already in progress (large chg_50_bars_pct with \
very short span_50_bars_min = panic/cascade regime the model rarely saw)
- funding extremely stretched against the trade direction, or a funding \
settlement within ~0.5h combined with stretched funding
- open interest collapsing or exploding abnormally (liquidation cascade)
- internally inconsistent data (e.g. non-finite numbers, TP/SL on the \
wrong side of entry)

Do NOT veto because confidence seems low, the trade seems risky in \
general, or you would have traded differently. Unnecessary vetoes destroy \
the edge. When in doubt: approve.

Answer with JSON: decision "approve" or "veto", and a one-sentence reason."""

VETO_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "veto"]},
        "reason": {"type": "string"},
    },
    "required": ["decision", "reason"],
    "additionalProperties": False,
}


@dataclass
class VetoConfig:
    model: str = "claude-opus-4-8"
    max_tokens: int = 256
    timeout_s: float = 30.0
    history_max: int = 10  # số quyết định gần nhất nhớ trong prompt
    anomaly: AnomalyConfig = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.anomaly is None:
            self.anomaly = AnomalyConfig()


@dataclass
class VetoDecision:
    approve: bool
    reason: str
    source: str  # "llm" | "fail_open" | "auto" | "sanity"


def build_market_context(bars: pd.DataFrame, feat: pd.Series, sig) -> dict:
    """Gom snapshot thị trường + tín hiệu thành dict phẳng cho prompt.

    bars: cửa sổ bar gần nhất (schema DollarBarBuilder); ít bar hơn cửa sổ
    tham chiếu thì lấy hết những gì có (live luôn >= 51 sau warmup).
    """
    closes = bars["close"].to_numpy(dtype=float)
    t = bars["t_close"].to_numpy(dtype="int64")

    def chg_pct(n: int) -> float:
        k = min(n, len(closes) - 1)
        return float((closes[-1] / closes[-1 - k] - 1) * 100)

    k50 = min(50, len(t) - 1)
    return {
        # tín hiệu
        "side": sig.side,
        "confidence": round(float(sig.conf), 4),
        "prob_down_flat_up": tuple(round(float(p), 4) for p in sig.prob),
        "entry_price": float(sig.entry_ref),
        "tp_pct": float((sig.tp_price / sig.entry_ref - 1) * 100),
        "sl_pct": float((sig.sl_price / sig.entry_ref - 1) * 100),
        "horizon_bars": int(sig.horizon_bars),
        # thị trường
        "time_utc": datetime.fromtimestamp(
            int(feat["t_close"]) / 1000, tz=timezone.utc).isoformat(),
        "chg_10_bars_pct": chg_pct(10),
        "chg_50_bars_pct": chg_pct(50),
        "span_50_bars_min": float((t[-1] - t[-1 - k50]) / 60_000),
        "vol_50": float(feat["vol_50"]),
        "ofi": float(feat["ofi"]),
        "ofi_sum_50": float(feat["ofi_sum_50"]),
        "range_pct": float(feat["range_pct"]),
        "fund_rate": float(feat["fund_rate"]),
        "fund_sum_9": float(feat["fund_sum_9"]),
        "hrs_to_funding": float(feat["hrs_to_funding"]),
        "oi_chg_1h": float(feat["oi_chg_1h"]),
        "oi_chg_4h": float(feat["oi_chg_4h"]),
        "oi_chg_24h": float(feat["oi_chg_24h"]),
    }


def build_prompt(ctx: dict, flags: list[str] | None = None,
                 history: str = "") -> str:
    lines = "\n".join(f"{k}: {v}" for k, v in ctx.items())
    parts = [f"New signal from the direction model:\n\n{lines}"]
    if flags:
        parts.append("Pre-screen flagged these abnormal conditions "
                     "(the reason you are being consulted):\n"
                     + "\n".join(f"- {f}" for f in flags))
    if history:
        parts.append(history)
    parts.append("Approve or veto this trade. Veto only for a concrete "
                 "abnormal condition visible in the data above.")
    return "\n\n".join(parts)


def _render_history(entries) -> str:
    """Working memory kiểu SessionMemory pa-model + outcome thật (bps)."""
    if not entries:
        return ""
    lines = ["Your recent decisions this session (most recent last, "
             "outcome = realized net return of the trade if it closed):"]
    for e in entries:
        row = (f"- {e['side']} conf={e['conf']:.2f} -> "
               f"{'approve' if e['approve'] else 'VETO'} ({e['source']})")
        if e["reason"]:
            row += f": {e['reason']}"
        if e.get("outcome") is not None:
            row += f" -> outcome {e['outcome'] * 1e4:+.1f}bps"
        lines.append(row)
    return "\n".join(lines)


class LLMVeto:
    """client inject được để test; mặc định anthropic.Anthropic()
    (đọc ANTHROPIC_API_KEY từ env).

    Gate 3 tầng trước khi LLM được phán (ý tưởng pa-model, chuyển thể):
      1. sanity_errors -> veto thẳng (data hỏng thì không trade).
      2. không có anomaly_flags -> approve thẳng, KHÔNG gọi API — regime
         bình thường là vùng backtest đã xác nhận edge, veto nhầm ở đây
         là mất tiền vô ích.
      3. có cờ -> hỏi LLM, kèm cờ + lịch sử quyết định gần đây.
    """

    def __init__(self, cfg: VetoConfig = VetoConfig(), client=None):
        self.cfg = cfg
        if client is None:
            import anthropic
            client = anthropic.Anthropic(timeout=cfg.timeout_s)
        self.client = client
        self.history: deque[dict] = deque(maxlen=cfg.history_max)
        self._counts = {"n_reviews": 0, "n_auto": 0, "n_sanity": 0,
                        "n_llm_approve": 0, "n_llm_veto": 0, "n_fail_open": 0}

    def stats(self) -> dict:
        return dict(self._counts)

    def record_outcome(self, net_ret: float) -> None:
        """Gắn kết quả lệnh vừa đóng vào quyết định approve gần nhất chưa
        có outcome (1 vị thế tại một thời điểm nên không nhầm lệnh)."""
        for e in reversed(self.history):
            if e["approve"] and e.get("outcome") is None:
                e["outcome"] = float(net_ret)
                return

    def review(self, bars: pd.DataFrame, feat: pd.Series, sig) -> VetoDecision:
        self._counts["n_reviews"] += 1
        try:
            ctx = build_market_context(bars, feat, sig)
            errs = sanity_errors(ctx)
            if errs:
                self._counts["n_sanity"] += 1
                d = VetoDecision(approve=False, source="sanity",
                                 reason="; ".join(errs))
            else:
                flags = anomaly_flags(ctx, self.cfg.anomaly)
                if not flags:
                    self._counts["n_auto"] += 1
                    d = VetoDecision(approve=True, source="auto",
                                     reason="regime bình thường — không hỏi LLM")
                else:
                    d = self._ask_llm(ctx, flags)
        except Exception as e:  # fail-open: baseline là model chạy một mình
            self._counts["n_fail_open"] += 1
            d = VetoDecision(approve=True, source="fail_open",
                             reason=f"fail-open: {type(e).__name__}: {e}")
        self.history.append({"side": sig.side, "conf": float(sig.conf),
                             "approve": d.approve, "source": d.source,
                             "reason": d.reason, "outcome": None})
        return d

    def _ask_llm(self, ctx: dict, flags: list[str]) -> VetoDecision:
        try:
            resp = self.client.messages.create(
                model=self.cfg.model,
                max_tokens=self.cfg.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_prompt(
                    ctx, flags, _render_history(self.history))}],
                output_config={
                    "format": {"type": "json_schema", "schema": VETO_SCHEMA},
                    "effort": "low",
                },
            )
            text = next(b.text for b in resp.content
                        if getattr(b, "type", "") == "text")
            data = json.loads(text)
            approve = data["decision"] == "approve"
            self._counts["n_llm_approve" if approve else "n_llm_veto"] += 1
            return VetoDecision(approve=approve, reason=data["reason"],
                                source="llm")
        except Exception as e:
            self._counts["n_fail_open"] += 1
            return VetoDecision(approve=True, source="fail_open",
                                reason=f"fail-open: {type(e).__name__}: {e}")
