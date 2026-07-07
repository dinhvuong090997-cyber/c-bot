# Backtest maker-fill — thiết kế

Ngày: 2026-07-07. Trạng thái: đã duyệt.

## Mục tiêu

Trả lời go/no-go: sau khi mô phỏng khớp lệnh maker thực tế (limit có thể
không khớp, phí 2bps maker / 5.5bps taker tùy loại thoát lệnh), chiến lược
còn edge ròng không?

Bối cảnh: sweep 216 config cho edge gộp tốt nhất ~6–8bps/lệnh ở các config
có mẫu đủ lớn — thấp hơn phí taker vòng lệnh (~11bps). Maker execution là
đường sống duy nhất còn lại trước khi nghĩ đến feature tốt hơn.

So sánh 2 model dưới cùng giả định:

| Model | horizon | width_mult | hidden | dropout | Nguồn |
|---|---|---|---|---|---|
| `model_final.pt` (sẵn có) | 80 | 1.0 | (64,32) | 0.1 | phiên trước chọn — edge tăng đơn điệu theo confidence |
| `model_final_wm07.pt` (train mới) | 80 | 0.7 | (256,128,64) | 0.3 | phân tích sweep 07/07 — edge 5.7bps trên 16,206 lệnh test @conf 0.50 |

## Kiến trúc

Module mới `backtest/fills.py`; `backtest/engine.py` v1 (taker, khớp 100%)
giữ nguyên làm baseline so sánh.

Điểm mấu chốt: khi entry khớp trễ ở bar i+j thay vì bar i, không thể tái
dùng return từ label triple-barrier nữa — phải mô phỏng lại đường đi của
lệnh trên OHLC của dollar bars.

### `backtest/fills.py`

```python
@dataclass
class FillConfig:
    entry_wait_bars: int = 3      # k: số bar tối đa chờ limit entry khớp
    maker_fee: float = 0.0002     # Bybit perp maker 0.02%
    taker_fee: float = 0.00055    # Bybit perp taker 0.055%

def simulate_trades(bars, signals, label_cfg, fill_cfg) -> pd.DataFrame
```

`signals`: mỗi tín hiệu = (bar index i, direction ±1, confidence) — lấy từ
prediction của model trên test set, đã lọc pred != ngang.

Với mỗi tín hiệu:

1. **Entry**: limit đặt tại `close[i]`. Quét bar `i+1..i+k`:
   long khớp nếu `low <= limit`, short nếu `high >= limit`.
   Quá k bar không khớp → tín hiệu bị bỏ (đếm vào `fill_rate`).
2. **Barriers** (sau khi khớp tại bar f): width tính đúng như label —
   `vol[i] * sqrt(horizon) * width_mult` — nhưng neo quanh **giá entry
   thực**; vertical barrier = `f + horizon` bars.
3. **Exit**: quét bar `f+1..f+horizon`:
   - TP chỉ tính khớp maker khi giá **vượt qua** barrier
     (`high > tp` với long, `low < tp` với short — không chỉ chạm);
   - SL chạm là dính (`low <= sl` với long) → thoát taker tại giá SL;
   - bar chạm cả TP lẫn SL → tính SL (conservative);
   - hết horizon → thoát taker tại `close` bar cuối.
4. Output mỗi lệnh: giá vào/ra, exit type (tp/sl/vertical), gross log-ret,
   phí (entry maker + exit maker/taker theo loại), net ret,
   t_entry/t_exit.

### `backtest/engine.py` — thêm `evaluate_maker(...)`

Bảng theo confidence threshold: `n_signals, fill_rate, n_trades, win_rate,
mean_net_ret, sharpe, max_drawdown, total_return` + breakdown số lệnh theo
exit type. Sharpe annualize theo thời gian thực giữa lệnh đầu/cuối (như v1).

Giữ giả định v1: mỗi event là 1 lệnh độc lập 100% vốn (không concurrent
bet sizing) — để so sánh táo-với-táo với baseline taker.

### `backtest/run_backtest.py`

Thêm `--mode maker|taker` (mặc định maker) và `--entry-wait-bars`.
Cùng checkpoint chạy được cả 2 mode để so trực tiếp.

## Model thứ hai (Kaggle)

Sửa config trong `kernel_train_final/cbot_train_final.py`:
`HIDDEN=(256,128,64), WIDTH_MULT=0.7, DROPOUT=0.3, LR=1e-3, WD=1e-4`
(horizon giữ 80). Output đổi tên `model_final_wm07.pt`. Push kernel chạy
song song trong lúc build backtest local; tải về chạy cùng pipeline.

## Testing

Pytest cho `fills.py` với bars tổng hợp nhỏ:

- entry khớp ngay / khớp trễ / không khớp trong k bar;
- TP vượt barrier khớp, TP chỉ chạm (high == tp) → KHÔNG khớp;
- SL chạm → thoát taker đúng giá;
- bar chạm cả 2 barrier → tính SL;
- vertical barrier → thoát taker tại close;
- phí đúng theo từng loại exit;
- short đối xứng với long.

Sanity check runtime: cảnh báo nếu `fill_rate < 20%` (nghi logic sai);
giữ check norm_mean khớp checkpoint như run_backtest hiện có.

## Ngoài phạm vi (YAGNI)

- Tick-level fill replay / ước lượng queue position — chỉ làm nếu bar-level
  cho kết quả dương đáng kể.
- Concurrent bet sizing kiểu AFML.
- Funding rate của perp (nhỏ so với spread edge đang xét, ghi nhận để sau).
