# c-bot workflow

Bot giao dịch BTCUSDT perp (Bybit). Kiến trúc: model NN quyết định hướng,
LLM chỉ lọc/veto (không bao giờ tự quyết). v1 = research + backtest, chưa
có execution/live.

Toàn bộ xử lý nặng chạy trên **Kaggle kernels** (script, có internet),
mỗi kernel ghi output ra **Kaggle dataset** để kernel sau đọc lại — máy
local chỉ giữ code + cache nhỏ để dev/test nhanh.

```
public.bybit.com (raw trades, .csv.gz/ngày)
        │
        ▼
kernel: cbot-dollar-bars          bars/pipeline.py
        │  → dollar_bars.parquet, clean_reports.json, verify_stats.json
        ▼
dataset: cbot-btcusdt-dollar-bars (bars + funding.parquet + oi.parquet)
        │
        ▼
kernel: cbot-features             features/bar_features.py, features/aux_features.py
        │  → features.parquet (29 cột, causal, point-in-time)
        ▼
kernel: cbot-train-sweep          model/labels.py, dataset.py, net.py, train.py, sweep.py
        │  đọc dataset (bars) + kernel_sources (features)
        │  → sweep_results.csv (216 trials, xếp hạng theo edge)
        ▼
(tiếp theo) chọn config tốt nhất → train bản final → backtest/
```

## 1. Dollar bars — kernel `cbot-dollar-bars`

Gom trades tới khi đủ **$10,000,000** giá trị khớp lệnh thì đóng 1 bar
(dollar bars, AFML — phân phối return gần Gaussian hơn time bars).
`TradeCleaner` + `DollarBarBuilder` là class có state, xử lý streaming
từng file/ngày một, chunked == whole bit-exact (test đảm bảo).

```bash
cd ~/projects/c-bot
tools/build_features_kernel.sh   # (nếu sửa code) rebuild bundle trước
uvx kaggle kernels push -p kernel_features  # ví dụ tương tự cho bars nếu cần sửa

# theo dõi
uvx kaggle kernels status vuongnguyen0909/cbot-dollar-bars
```

Đổi số ngày backfill: sửa `N_DAYS` trong
`/tmp/.../scratchpad/cbot-review/kernel/cbot_dollar_bars.py` (kernel bars
hiện chưa dọn vào repo chính thức — TODO nếu cần chạy lại từ đầu).

## 2. Features — kernel `cbot-features`

29 features: 21 từ bar (logret, vol, zret, OFI, tốc độ bar, range/close-pos,
giờ/thứ sin-cos) + 4 funding + 4 OI. Tất cả causal (asof backward, không
lookahead — có test `TestCausality` chống regression).

```bash
tools/build_features_kernel.sh          # gộp source -> kernel_features/cbot_features.py
uvx kaggle kernels push -p kernel_features
uvx kaggle kernels status vuongnguyen0909/cbot-features
uvx kaggle kernels output vuongnguyen0909/cbot-features -p out/
```

**Gotcha quan trọng**: Bybit chặn IP Mỹ của Kaggle nên funding/OI KHÔNG
fetch được trên kernel — phải fetch ở máy local rồi đóng gói kèm bars vào
dataset. Kernel chỉ đọc cache (`funding.parquet`, `oi.parquet` trong
dataset), không gọi API.

## 3. Sau khi backfill xong: `tools/after_backfill.sh`

Script 1 lệnh làm trọn gói khi kernel bars vừa `COMPLETE`:

```bash
tools/after_backfill.sh
```

Các bước bên trong: tải bars → fetch funding/OI local (Bybit v5 public
API, `data/bybit_api.py`) → `kaggle datasets version` (đợi tới khi
`ready` mới đi tiếp — tránh race khiến kernel sau đọc dataset rỗng) →
build + push kernel features.

## 4. Model — `model/`

- `labels.py`: **triple-barrier** (AFML). Barrier trên/dưới = `close *
  exp(±width)`, width mặc định = rolling_vol × √horizon × width_mult;
  vertical barrier = horizon bars. Vectorized, 583k bars label trong ~1.6s.
- `dataset.py`: join features+labels theo `t_close`, split **theo thời
  gian** (train/val/test liên tục, không shuffle) + **purge** (event có
  cửa sổ label thò qua ranh giới split thì bỏ — chống leakage), chuẩn hóa
  z-score fit **chỉ trên train**.
- `net.py`: MLP baseline (`DirectionNet`) — Linear→LayerNorm→ReLU→Dropout
  nhiều tầng, output 3 class (xuống/ngang/lên).
- `train.py`: Adam + CrossEntropy + early stopping theo val loss.
- `sweep.py`: build lưới hyperparameter (horizon × width_mult × hidden ×
  dropout × lr × weight_decay) + chạy **song song trên nhiều GPU**
  (ThreadPoolExecutor, mỗi trial ghim 1 device — model nhỏ nên tận dụng
  GPU bằng cách chạy nhiều trial cùng lúc, không phải chia 1 trial ra
  nhiều GPU).
- `run_training.py`: CLI train 1 lần với 1 config, in confusion matrix +
  "ret thực khi model nói LÊN/XUỐNG" (đo edge, không chỉ accuracy).

```bash
# train nhanh local (CPU, 1 config) để smoke-test
uv run python -m model.run_training \
    --bars data/cache/backfill/dollar_bars.parquet \
    --features out/features_2y.parquet --out out/model_v1.pt

# sweep 216 configs trên Kaggle (2×T4)
tools/build_train_kernel.sh
uvx kaggle kernels push -p kernel_train
uvx kaggle kernels status vuongnguyen0909/cbot-train-sweep
uvx kaggle kernels output vuongnguyen0909/cbot-train-sweep -p out/sweep/
```

Metric đánh giá không chỉ accuracy (baseline đoán bừa ~33%, đoán toàn
class lớn nhất ~36.5%) mà còn **edge theo ngưỡng confidence**: với mỗi
threshold, lọc dự đoán có `conf >= th`, tính return thực trung bình khi
model nói LÊN (dương là tốt) trừ khi nói XUỐNG. `edge_conf0.40` là cột
dùng để xếp hạng sweep (đủ volume lệnh để thống kê đáng tin, lọc trial có
`n_conf0.40 < 200`).

## 5. Model final — kernel `cbot-train-final`

Chọn từ 216 trials sweep: `horizon=80, width_mult=1.0` là vùng có edge
**thật** (không phải artifact của accuracy cao do barrier hẹp — xem giải
thích ở `sweep.py`/kết quả sweep). Config chốt: `hidden=(64,32),
dropout=0.1, lr=3e-4, weight_decay=1e-3` — đây là dòng duy nhất trong
sweep có edge tăng đơn điệu theo confidence threshold với n vẫn đủ lớn ở
mọi bước (bằng chứng calibration tốt, không phải trúng số 1 điểm dữ liệu).

```bash
tools/build_train_final_kernel.sh        # gộp model/*.py + kernel_train_final_runner.py
uvx kaggle kernels push -p kernel_train_final
uvx kaggle kernels status vuongnguyen0909/cbot-train-final
uvx kaggle kernels output vuongnguyen0909/cbot-train-final -p out/train_final/
```

Output: `model_final.pt` (state_dict + norm_mean/std + feature_cols +
label_config để nạp lại đúng chuẩn hoá) + `metrics_final.json`.

Train local (CPU, 1 config, chậm hơn nhiều — chỉ dùng khi không cần
Kaggle): `model/run_training.py` giờ nhận thêm `--width-mult --hidden
--dropout --lr --weight-decay`.

## 6. Backtest — `backtest/`

`backtest/engine.py`: lọc lệnh theo confidence threshold (bỏ dự đoán
"ngang"), trừ phí round-trip, tính win_rate/mean_net_ret/Sharpe (annualize
theo thời gian thực vì dollar bar không đều)/max_drawdown/trades_per_day.
**Đơn giản hoá v1**: mỗi event coi là 1 lệnh độc lập 100% vốn, KHÔNG có
concurrent bet sizing (AFML) — `equity_curve`/`max_drawdown` chỉ để so
sánh tương đối giữa threshold, không phải equity thật của bot có risk
management. Số đáng tin để đọc: `mean_net_ret`, `sharpe`, `win_rate`.

```bash
uv run python -m backtest.run_backtest \
    --bars data/cache/backfill/dollar_bars.parquet \
    --features out/features_2y.parquet \
    --model out/train_final/model_final.pt
```

**Kết quả model final (test set 2026-01-29→2026-07-05, phí Bybit taker
round-trip 0.11%)**: hoà vốn ở threshold **0.45** (~11.6 lệnh/ngày), edge
dương thật chỉ từ threshold **0.50** (Sharpe ~1.0, win rate 58%, nhưng chỉ
~1.5 lệnh/ngày, n=190 — mẫu còn mỏng, chưa đủ tin cậy để live). Dưới 0.40,
phí ăn hết edge.

## Test

```bash
uv run pytest tests/ -q        # 87 tests, TDD toàn bộ, ~36s
```

## Việc còn lại (chưa làm)

- Backtest hiện chưa có concurrent bet sizing (AFML) — mỗi lệnh đang tính
  độc lập 100% vốn, cần sizing thật trước khi đọc equity curve nghiêm túc
- Cần thêm data/thời gian để n_trades ở threshold 0.50 đủ lớn, hoặc tìm
  cách tăng edge (feature mới, model khác) thay vì chỉ raise threshold
- Dọn kernel `cbot-dollar-bars` vào repo chính thức `bars/` thay vì nằm ở
  scratchpad (hiện tại `bars/pipeline.py` là logic core, nhưng script
  Kaggle runner riêng vẫn ở ngoài repo)
- `llm/`: prompt + parse cho lớp veto
- `risk/`: hard rules (position size, max drawdown, ...)
- `execution/`, `live/`: để sau, ngoài scope v1
