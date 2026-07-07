"""Client Bybit v5 private REST — mặc định trỏ DEMO (api-demo.bybit.com).

Phần thuần để test được: sign_v5 (HMAC-SHA256 theo spec v5), round_to_step
(làm tròn XUỐNG theo tick/step, Decimal để không dính bụi float), và các
builder payload lệnh. Phần HTTP là wrapper mỏng.

Ký v5 (HMAC mode): sign = HMAC_SHA256(secret,
    str(timestamp) + api_key + str(recv_window) + payload)
với payload = queryString (GET) hoặc raw JSON body (POST). Chuỗi gửi đi
phải ĐÚNG BẰNG chuỗi đem ký — client này luôn dùng chung một biến.

Key demo: tạo trong tài khoản Demo Trading trên bybit.com (menu tài khoản
-> Demo Trading -> API), export BYBIT_DEMO_API_KEY / BYBIT_DEMO_API_SECRET.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import ROUND_DOWN, Decimal
from urllib.parse import urlencode

import requests

DEMO_URL = "https://api-demo.bybit.com"

# BTCUSDT linear perp (xác nhận lại bằng get_instrument nếu đổi symbol)
PRICE_TICK = 0.1
QTY_STEP = 0.001


def sign_v5(secret: str, timestamp_ms: int, api_key: str,
            recv_window: int, payload: str) -> str:
    msg = f"{timestamp_ms}{api_key}{recv_window}{payload}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _step_decimal(value: float, step: float) -> Decimal:
    v, s = Decimal(str(value)), Decimal(str(step))
    return (v / s).to_integral_value(rounding=ROUND_DOWN) * s


def round_to_step(value: float, step: float) -> float:
    """Làm tròn XUỐNG theo bội của step (không bao giờ vượt giá trị gốc)."""
    return float(_step_decimal(value, step))


def _fmt(value: float, step: float) -> str:
    """Chuỗi thập phân sạch cho API (không '0.010000000000000002')."""
    return format(_step_decimal(value, step).normalize(), "f")


def build_entry_order(symbol: str, side: str, qty: float, price: float,
                      tp: float, sl: float, link_id: str,
                      price_tick: float = PRICE_TICK,
                      qty_step: float = QTY_STEP) -> dict:
    """Entry: limit post-only (đảm bảo phí maker — bị reject nếu khớp ngay)
    kèm TP/SL sàn tự quản (tpslMode Full, trigger -> market)."""
    return {
        "category": "linear", "symbol": symbol, "side": side,
        "orderType": "Limit", "timeInForce": "PostOnly",
        "qty": _fmt(qty, qty_step), "price": _fmt(price, price_tick),
        "takeProfit": _fmt(tp, price_tick), "stopLoss": _fmt(sl, price_tick),
        "tpslMode": "Full", "tpOrderType": "Market", "slOrderType": "Market",
        "orderLinkId": link_id, "positionIdx": 0,
    }


def build_market_close(symbol: str, position_side: str, qty: float,
                       qty_step: float = QTY_STEP) -> dict:
    """Đóng vị thế bằng market reduce-only (time-exit khi hết horizon)."""
    return {
        "category": "linear", "symbol": symbol,
        "side": "Sell" if position_side == "Buy" else "Buy",
        "orderType": "Market", "qty": _fmt(qty, qty_step),
        "reduceOnly": True, "positionIdx": 0,
    }


class BybitClient:
    def __init__(self, api_key: str, api_secret: str,
                 base_url: str = DEMO_URL, recv_window: int = 5000):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.recv_window = recv_window

    def _request(self, method: str, path: str, params: dict) -> dict:
        ts = int(time.time() * 1000)
        if method == "GET":
            payload = urlencode(params)
            url = f"{self.base_url}{path}?{payload}"
            body = None
        else:
            payload = json.dumps(params)
            url = self.base_url + path
            body = payload
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": str(ts),
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "X-BAPI-SIGN": sign_v5(self.api_secret, ts, self.api_key,
                                   self.recv_window, payload),
            "Content-Type": "application/json",
        }
        r = requests.request(method, url, data=body, headers=headers, timeout=20)
        r.raise_for_status()
        j = r.json()
        if j.get("retCode") != 0:
            raise RuntimeError(f"Bybit retCode={j.get('retCode')}: {j.get('retMsg')} "
                               f"({method} {path})")
        return j["result"]

    # --- lệnh ---
    def place_order(self, order: dict) -> dict:
        return self._request("POST", "/v5/order/create", order)

    def cancel_order(self, symbol: str, order_link_id: str) -> dict:
        return self._request("POST", "/v5/order/cancel", {
            "category": "linear", "symbol": symbol, "orderLinkId": order_link_id})

    def open_orders(self, symbol: str) -> list[dict]:
        return self._request("GET", "/v5/order/realtime", {
            "category": "linear", "symbol": symbol})["list"]

    # --- vị thế / số dư ---
    def position(self, symbol: str) -> dict:
        lst = self._request("GET", "/v5/position/list", {
            "category": "linear", "symbol": symbol})["list"]
        return lst[0] if lst else {}

    def wallet_equity(self) -> float:
        lst = self._request("GET", "/v5/account/wallet-balance",
                            {"accountType": "UNIFIED"})["list"]
        return float(lst[0]["totalEquity"])

    def executions(self, symbol: str, start_ms: int) -> list[dict]:
        return self._request("GET", "/v5/execution/list", {
            "category": "linear", "symbol": symbol,
            "startTime": start_ms, "limit": 100})["list"]
