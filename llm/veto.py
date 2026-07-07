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
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

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


@dataclass
class VetoDecision:
    approve: bool
    reason: str
    source: str  # "llm" | "fail_open"


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


def build_prompt(ctx: dict) -> str:
    lines = "\n".join(f"{k}: {v}" for k, v in ctx.items())
    return (f"New signal from the direction model:\n\n{lines}\n\n"
            "Approve or veto this trade. Veto only for a concrete abnormal "
            "condition visible in the data above.")


class LLMVeto:
    """client inject được để test; mặc định anthropic.Anthropic()
    (đọc ANTHROPIC_API_KEY từ env)."""

    def __init__(self, cfg: VetoConfig = VetoConfig(), client=None):
        self.cfg = cfg
        if client is None:
            import anthropic
            client = anthropic.Anthropic(timeout=cfg.timeout_s)
        self.client = client

    def review(self, bars: pd.DataFrame, feat: pd.Series, sig) -> VetoDecision:
        try:
            ctx = build_market_context(bars, feat, sig)
            resp = self.client.messages.create(
                model=self.cfg.model,
                max_tokens=self.cfg.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_prompt(ctx)}],
                output_config={
                    "format": {"type": "json_schema", "schema": VETO_SCHEMA},
                    "effort": "low",
                },
            )
            text = next(b.text for b in resp.content
                        if getattr(b, "type", "") == "text")
            data = json.loads(text)
            return VetoDecision(approve=data["decision"] == "approve",
                                reason=data["reason"], source="llm")
        except Exception as e:  # fail-open: baseline là model chạy một mình
            return VetoDecision(
                approve=True, source="fail_open",
                reason=f"fail-open: {type(e).__name__}: {e}")
