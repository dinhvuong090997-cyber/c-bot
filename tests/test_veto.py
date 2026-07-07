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


def make_bars(n=60, start=100.0, step=0.01):
    """n bar, close tăng đều step/bar, mỗi bar 1 phút.
    step mặc định nhỏ để không tự bật cờ cascade/sharp-move."""
    closes = start + step * np.arange(n)
    return pd.DataFrame({
        "t_close": T0 + MS * np.arange(n),
        "open": closes - step, "high": closes + 1.0, "low": closes - 1.0,
        "close": closes, "vol_dollar": 10e6, "ofi": 0.1, "n_trades": 1000,
    })


def make_feat(anomalous=False, **over):
    """anomalous=True bật cờ OI sốc để ép đi qua nhánh LLM (không auto)."""
    base = {"close": 129.5, "t_close": T0 + MS * 59, "vol_50": 0.002,
            "ofi": 0.3, "ofi_sum_50": 2.5, "range_pct": 0.001,
            "fund_rate": 1e-4, "fund_sum_9": 9e-4, "hrs_to_funding": 3.0,
            "oi_chg_1h": 0.01, "oi_chg_4h": 0.02, "oi_chg_24h": -0.05}
    if anomalous:
        base["oi_chg_1h"] = 0.05
    base.update(over)
    return pd.Series(base)


def make_sig(side="Buy", conf=0.52):
    tp, sl = (131.8, 127.2) if side == "Buy" else (127.2, 131.8)
    return Signal(side=side, conf=conf, entry_ref=129.5,
                  tp_price=tp, sl_price=sl, horizon_bars=80,
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


class TestGate:
    """Heuristic gate (ý tưởng pa-model): bình thường auto-approve không
    gọi LLM; data hỏng chặn thẳng; có cờ bất thường mới hỏi LLM."""

    def test_calm_regime_auto_approves_without_llm_call(self):
        veto, msgs = make_veto({"decision": "veto", "reason": "x"})
        d = veto.review(make_bars(), make_feat(), make_sig())
        assert d.approve is True
        assert d.source == "auto"
        assert msgs.last_kwargs is None  # không có API call

    def test_broken_data_hard_vetoes_without_llm_call(self):
        veto, msgs = make_veto({"decision": "approve", "reason": "x"})
        feat = make_feat(vol_50=float("nan"))
        d = veto.review(make_bars(), feat, make_sig())
        assert d.approve is False
        assert d.source == "sanity"
        assert msgs.last_kwargs is None

    def test_anomaly_flags_reach_llm_prompt(self):
        veto, msgs = make_veto({"decision": "approve", "reason": "ok"})
        veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        user = msgs.last_kwargs["messages"][0]["content"]
        assert "OI" in user  # cờ oi_chg_1h=5% phải nằm trong prompt


class TestReview:
    def test_approve(self):
        veto, _ = make_veto({"decision": "approve", "reason": "bt"})
        d = veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        assert isinstance(d, VetoDecision)
        assert d.approve is True
        assert d.source == "llm"

    def test_veto_with_reason(self):
        veto, _ = make_veto({"decision": "veto", "reason": "funding spike"})
        d = veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        assert d.approve is False
        assert d.reason == "funding spike"
        assert d.source == "llm"

    def test_api_error_fails_open(self):
        veto, _ = make_veto(exc=RuntimeError("boom"))
        d = veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        assert d.approve is True
        assert d.source == "fail_open"
        assert "RuntimeError" in d.reason

    def test_bad_json_fails_open(self):
        veto, _ = make_veto(text="not json at all")
        d = veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        assert d.approve is True
        assert d.source == "fail_open"

    def test_request_uses_opus_and_structured_output(self):
        veto, msgs = make_veto({"decision": "approve", "reason": ""})
        veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        kw = msgs.last_kwargs
        assert kw["model"] == "claude-opus-4-8"
        assert kw["system"] == SYSTEM_PROMPT
        assert kw["output_config"]["format"]["type"] == "json_schema"
        assert kw["output_config"]["format"]["schema"] == VETO_SCHEMA
        assert kw["output_config"]["effort"] == "low"
        assert "thinking" not in kw


class TestSessionMemory:
    """Ý tưởng SessionMemory pa-model, thêm outcome thật: các quyết định
    gần đây + kết quả lệnh được render vào prompt cho call sau."""

    def test_history_rendered_in_next_prompt(self):
        veto, msgs = make_veto({"decision": "veto", "reason": "OI shock"})
        veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        veto.review(make_bars(), make_feat(anomalous=True),
                    make_sig(side="Sell"))
        user = msgs.last_kwargs["messages"][0]["content"]
        assert "OI shock" in user  # quyết định trước xuất hiện trong prompt sau

    def test_outcome_attached_to_last_approved(self):
        veto, msgs = make_veto({"decision": "approve", "reason": "ok"})
        veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        veto.record_outcome(0.0012)
        veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        user = msgs.last_kwargs["messages"][0]["content"]
        assert "+12.0bps" in user

    def test_auto_approvals_also_remembered(self):
        veto, msgs = make_veto({"decision": "approve", "reason": "ok"})
        veto.review(make_bars(), make_feat(), make_sig())          # auto
        veto.record_outcome(-0.002)
        veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        user = msgs.last_kwargs["messages"][0]["content"]
        assert "-20.0bps" in user

    def test_history_bounded(self):
        veto, _ = make_veto({"decision": "approve", "reason": "ok"})
        for _ in range(veto.cfg.history_max + 5):
            veto.review(make_bars(), make_feat(), make_sig())
        assert len(veto.history) == veto.cfg.history_max


class FakeDeepSeek:
    """Giả DeepSeekClient: chỉ cần .complete(system, user, model, max_tokens)."""

    def __init__(self, text):
        self.text = text
        self.last = None

    def complete(self, system, user, model, max_tokens):
        self.last = {"system": system, "user": user, "model": model,
                     "max_tokens": max_tokens}
        return self.text


class TestDeepSeekProvider:
    def make(self, text):
        from llm.veto import VetoConfig
        client = FakeDeepSeek(text)
        return LLMVeto(VetoConfig(provider="deepseek"), client=client), client

    def test_default_model_per_provider(self):
        from llm.veto import VetoConfig
        assert VetoConfig().model == "claude-opus-4-8"
        assert VetoConfig(provider="deepseek").model == "deepseek-chat"

    def test_veto_via_deepseek(self):
        veto, client = self.make('{"decision": "veto", "reason": "OI shock"}')
        d = veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        assert d.approve is False
        assert d.source == "llm"
        assert client.last["model"] == "deepseek-chat"
        assert client.last["system"] == SYSTEM_PROMPT

    def test_fenced_json_parsed(self):
        # deepseek-reasoner hay bọc ```json ...``` hoặc kèm prose
        veto, _ = self.make(
            'Here is my analysis.\n```json\n'
            '{"decision": "approve", "reason": "ok"}\n```')
        d = veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        assert d.approve is True
        assert d.source == "llm"

    def test_invalid_decision_fails_open(self):
        veto, _ = self.make('{"decision": "maybe", "reason": "?"}')
        d = veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        assert d.approve is True
        assert d.source == "fail_open"

    def test_calm_regime_still_auto(self):
        veto, client = self.make('{"decision": "veto", "reason": "x"}')
        d = veto.review(make_bars(), make_feat(), make_sig())
        assert d.source == "auto"
        assert client.last is None


class TestVetoFromEnv:
    def test_deepseek_when_only_deepseek_key(self, monkeypatch):
        from llm.veto import veto_from_env
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        veto = veto_from_env()
        assert veto is not None
        assert veto.cfg.provider == "deepseek"

    def test_anthropic_preferred_when_both(self, monkeypatch):
        from llm.veto import veto_from_env
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        assert veto_from_env().cfg.provider == "anthropic"

    def test_explicit_provider_overrides(self, monkeypatch):
        from llm.veto import veto_from_env
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        assert veto_from_env("deepseek").cfg.provider == "deepseek"

    def test_none_when_no_keys(self, monkeypatch):
        from llm.veto import veto_from_env
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        assert veto_from_env() is None


class TestStats:
    def test_counters(self):
        veto, _ = make_veto({"decision": "veto", "reason": "x"})
        veto.review(make_bars(), make_feat(), make_sig())                # auto
        veto.review(make_bars(), make_feat(anomalous=True), make_sig())  # llm veto
        veto.review(make_bars(), make_feat(vol_50=float("nan")),
                    make_sig())                                          # sanity
        s = veto.stats()
        assert s["n_reviews"] == 3
        assert s["n_auto"] == 1
        assert s["n_llm_veto"] == 1
        assert s["n_sanity"] == 1
        assert s["n_fail_open"] == 0

    def test_fail_open_counted(self):
        veto, _ = make_veto(exc=RuntimeError("boom"))
        veto.review(make_bars(), make_feat(anomalous=True), make_sig())
        assert veto.stats()["n_fail_open"] == 1
