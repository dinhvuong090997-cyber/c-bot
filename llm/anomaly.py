"""Heuristic gate trước LLM veto — chuyển thể từ ý tưởng adverse_score
của pa-model (detector rẻ tiền quyết định KHI NÀO đáng gọi LLM).

Hai tầng:
  - sanity_errors: data hỏng (NaN/inf, barrier sai phía, prob vô lý) ->
    caller chặn thẳng, không cần hỏi LLM. Không trade trên data gãy.
  - anomaly_flags: điều kiện bất thường (cascade, funding căng ngược hướng,
    OI sốc). Không có cờ nào -> regime bình thường, auto-approve không tốn
    API call và triệt tiêu luôn khả năng LLM veto nhầm trong regime mà
    backtest đã xác nhận model có edge. Có cờ -> đưa lên LLM phán, kèm
    danh sách cờ để nó tập trung đúng chỗ.

Ngưỡng mặc định neo theo BTCUSDT perp: funding điển hình ~0.01%/8h (1e-4),
50 bar $10M bình thường trải 2.5-5h.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# các khóa numeric trong ctx của build_market_context (trừ prob tuple)
_NUMERIC_KEYS = (
    "confidence", "entry_price", "tp_pct", "sl_pct",
    "chg_10_bars_pct", "chg_50_bars_pct", "span_50_bars_min",
    "vol_50", "ofi", "ofi_sum_50", "range_pct",
    "fund_rate", "fund_sum_9", "hrs_to_funding",
    "oi_chg_1h", "oi_chg_4h", "oi_chg_24h",
)


@dataclass
class AnomalyConfig:
    # cascade: giá chạy mạnh TRONG thời gian ngắn (bar dollar dồn dập)
    cascade_move_pct: float = 2.0
    cascade_span_min: float = 120.0
    # cú giật ngắn: 10 bar (~$100M) đã chạy quá mức này
    sharp_move_pct: float = 1.5
    # funding căng: |rate| vượt ~5x mức điển hình 1e-4/8h
    funding_stretched: float = 5e-4
    # sát kỳ trả funding + rate đã cao
    settlement_hrs: float = 0.5
    settlement_funding: float = 3e-4
    # OI sốc: thanh lý dây chuyền / build-up bất thường
    oi_shock_1h: float = 0.03
    oi_collapse_4h: float = -0.08


def sanity_errors(ctx: dict) -> list[str]:
    """Data tự mâu thuẫn -> không trade, không cần LLM. [] = sạch."""
    errs = []
    for k in _NUMERIC_KEYS:
        v = ctx.get(k)
        if v is None or not math.isfinite(float(v)):
            errs.append(f"{k} không hữu hạn: {v}")
    if errs:  # số đã gãy thì các check dưới vô nghĩa
        return errs

    buy = ctx["side"] == "Buy"
    if buy and not (ctx["tp_pct"] > 0 > ctx["sl_pct"]):
        errs.append(f"Buy nhưng tp_pct={ctx['tp_pct']} sl_pct={ctx['sl_pct']} "
                    "— barrier sai phía entry")
    if not buy and not (ctx["tp_pct"] < 0 < ctx["sl_pct"]):
        errs.append(f"Sell nhưng tp_pct={ctx['tp_pct']} sl_pct={ctx['sl_pct']} "
                    "— barrier sai phía entry")
    if not 0.0 < ctx["confidence"] <= 1.0:
        errs.append(f"confidence ngoài (0,1]: {ctx['confidence']}")
    return errs


def anomaly_flags(ctx: dict, cfg: AnomalyConfig = AnomalyConfig()) -> list[str]:
    """Danh sách điều kiện bất thường (rỗng = regime bình thường)."""
    flags = []

    if (abs(ctx["chg_50_bars_pct"]) >= cfg.cascade_move_pct
            and ctx["span_50_bars_min"] <= cfg.cascade_span_min):
        flags.append(
            f"cascade: giá {ctx['chg_50_bars_pct']:+.2f}% trong 50 bar chỉ "
            f"{ctx['span_50_bars_min']:.0f} phút (volume dồn dập)")

    if abs(ctx["chg_10_bars_pct"]) >= cfg.sharp_move_pct:
        flags.append(f"sharp move: {ctx['chg_10_bars_pct']:+.2f}% "
                     "chỉ trong 10 bar gần nhất")

    # funding căng NGƯỢC hướng lệnh: rate dương cao = crowded long
    # (long trả phí) -> Buy thêm là đu đỉnh đám đông; ngược lại cho Sell
    fr = ctx["fund_rate"]
    against = fr >= cfg.funding_stretched if ctx["side"] == "Buy" \
        else fr <= -cfg.funding_stretched
    if against:
        flags.append(f"funding căng ngược hướng: rate={fr:+.2e} "
                     f"khi vào {ctx['side']}")

    if (ctx["hrs_to_funding"] <= cfg.settlement_hrs
            and abs(fr) >= cfg.settlement_funding):
        flags.append(f"settlement: còn {ctx['hrs_to_funding']:.1f}h đến kỳ "
                     f"funding với rate={fr:+.2e}")

    if abs(ctx["oi_chg_1h"]) >= cfg.oi_shock_1h:
        flags.append(f"OI sốc: {ctx['oi_chg_1h']:+.1%} trong 1h")
    elif ctx["oi_chg_4h"] <= cfg.oi_collapse_4h:
        flags.append(f"OI sập: {ctx['oi_chg_4h']:+.1%} trong 4h "
                     "(thanh lý dây chuyền?)")

    return flags
