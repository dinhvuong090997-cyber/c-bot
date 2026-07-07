"""Tests cho llm/veto.py — lớp LLM veto giữa SignalEngine và TradeManager.

Kiến trúc khóa: model quyết định hướng, LLM CHỈ được veto trong điều kiện
bất thường — mặc định approve, lỗi API thì fail-open (approve) vì baseline
đã backtest là model chạy một mình.
"""
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from live.signal import Signal
from llm.veto import (SYSTEM_PROMPT, VETO_SCHEMA, LLMVeto, VetoConfig,
                      VetoDecision, build_market_context, build_prompt)

T0 = 1_700_000_000_000
MS = 60_000


def make_bars(n=60, start=100.0, step=0.5):
    """n bar, close tăng đều step/bar, mỗi bar 1 phút."""
    closes = start + step * np.arange(n)
    return pd.DataFrame({
        "t_close": T0 + MS * np.arange(n),
        "open": closes - step, "high": closes + 1.0, "low": closes - 1.0,
        "close": closes, "vol_dollar": 10e6, "ofi": 0.1, "n_trades": 1000,
    })


def make_feat(**over):
    base = {"close": 129.5, "t_close": T0 + MS * 59, "vol_50": 0.002,
            "ofi": 0.3, "ofi_sum_50": 2.5, "range_pct": 0.001,
            "fund_rate": 1e-4, "fund_sum_9": 9e-4, "hrs_to_funding": 3.0,
            "oi_chg_1h": 0.01, "oi_chg_4h": 0.02, "oi_chg_24h": -0.05}
    base.update(over)
    return pd.Series(base)


def make_sig(side="Buy", conf=0.52):
    return Signal(side=side, conf=conf, entry_ref=129.5,
                  tp_price=131.8, sl_price=127.2, horizon_bars=80,
                  t_close=T0 + MS * 59, prob=(0.18, 0.30, 0.52))


class FakeMessages:
    def __init__(self, payload=None, exc=None, text=None):
        self.payload, self.exc, self.text = payload, exc, text
        self.last_kwargs = None

    def create(self, **kw):
        self.last_kwargs = kw
        if self.exc is not None:
            raise self.exc
        body = self.text if self.text is not None else json.dumps(self.payload)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=body)],
            stop_reason="end_turn")


def make_veto(payload=None, exc=None, text=None):
    client = SimpleNamespace(messages=FakeMessages(payload, exc, text))
    return LLMVeto(VetoConfig(), client=client), client.messages


class TestMarketContext:
    def test_signal_fields(self):
        ctx = build_market_context(make_bars(), make_feat(), make_sig())
        assert ctx["side"] == "Buy"
        assert ctx["confidence"] == pytest.approx(0.52)
        assert ctx["prob_down_flat_up"] == pytest.approx((0.18, 0.30, 0.52))
        assert ctx["entry_price"] == pytest.approx(129.5)
        assert ctx["tp_pct"] == pytest.approx((131.8 / 129.5 - 1) * 100)
        assert ctx["sl_pct"] == pytest.approx((127.2 / 129.5 - 1) * 100)
        assert ctx["horizon_bars"] == 80

    def test_market_fields_from_bars_and_feat(self):
        bars = make_bars(n=60, start=100.0, step=0.5)
        ctx = build_market_context(bars, make_feat(), make_sig())
        # quy ước shift(N) như logret_N: close hiện tại vs close N bar trước
        assert ctx["chg_10_bars_pct"] == pytest.approx(
            (129.5 / 124.5 - 1) * 100)
        assert ctx["chg_50_bars_pct"] == pytest.approx(
            (129.5 / 104.5 - 1) * 100)
        # 50 khoảng x 1 phút
        assert ctx["span_50_bars_min"] == pytest.approx(50.0)
        assert ctx["vol_50"] == pytest.approx(0.002)
        assert ctx["fund_rate"] == pytest.approx(1e-4)
        assert ctx["oi_chg_24h"] == pytest.approx(-0.05)
        assert "time_utc" in ctx

    def test_short_history_does_not_crash(self):
        ctx = build_market_context(make_bars(n=5), make_feat(), make_sig())
        assert np.isfinite(ctx["chg_10_bars_pct"])


class TestPrompt:
    def test_prompt_contains_signal_and_instructions(self):
        ctx = build_market_context(make_bars(), make_feat(), make_sig())
        prompt = build_prompt(ctx)
        assert "Buy" in prompt
        assert "0.52" in prompt
        assert "veto" in prompt.lower()

    def test_system_prompt_defaults_to_approve(self):
        assert "approve" in SYSTEM_PROMPT.lower()
        assert "veto" in SYSTEM_PROMPT.lower()

    def test_schema_shape(self):
        assert VETO_SCHEMA["properties"]["decision"]["enum"] == [
            "approve", "veto"]
        assert set(VETO_SCHEMA["required"]) == {"decision", "reason"}


class TestReview:
    def test_approve(self):
        veto, _ = make_veto({"decision": "approve", "reason": "bt"})
        d = veto.review(make_bars(), make_feat(), make_sig())
        assert isinstance(d, VetoDecision)
        assert d.approve is True
        assert d.source == "llm"

    def test_veto_with_reason(self):
        veto, _ = make_veto({"decision": "veto", "reason": "funding spike"})
        d = veto.review(make_bars(), make_feat(), make_sig())
        assert d.approve is False
        assert d.reason == "funding spike"
        assert d.source == "llm"

    def test_api_error_fails_open(self):
        veto, _ = make_veto(exc=RuntimeError("boom"))
        d = veto.review(make_bars(), make_feat(), make_sig())
        assert d.approve is True
        assert d.source == "fail_open"
        assert "RuntimeError" in d.reason

    def test_bad_json_fails_open(self):
        veto, _ = make_veto(text="not json at all")
        d = veto.review(make_bars(), make_feat(), make_sig())
        assert d.approve is True
        assert d.source == "fail_open"

    def test_request_uses_opus_and_structured_output(self):
        veto, msgs = make_veto({"decision": "approve", "reason": ""})
        veto.review(make_bars(), make_feat(), make_sig())
        kw = msgs.last_kwargs
        assert kw["model"] == "claude-opus-4-8"
        assert kw["system"] == SYSTEM_PROMPT
        assert kw["output_config"]["format"]["type"] == "json_schema"
        assert kw["output_config"]["format"]["schema"] == VETO_SCHEMA
        assert kw["output_config"]["effort"] == "low"
        assert "thinking" not in kw
