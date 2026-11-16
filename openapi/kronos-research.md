# Kronos-small zero-shot pilot — 2026-11-14

## Kết luận

Đã tải và chạy thật Kronos-small24,7M tham số trên CPU, không fine-tune. Dự báo chiều giá8–9h có độ đúng57,24% trong152cửa sổ có nhãn, nhưng bộ lọc đồng hướng làm replay bot RR5 từ+10,01% thành−9,23%. Cùng coverage, đối chứng không dùng hướng model vẫn+8,52%. Chưa nên đưa bộ lọc này vào demo. Đây là kết quả của một checkpoint/quy tắc/horizon, không phải kiểm định mọi Transformer.

## Thiết kế cố định trước kết quả

- Source: quote tick FxPro lưu local, chung `BacktestRunner.ReadQuotes` và luật `AsiaSession`; H1 dựng từ Bid. Không lấy ảnh chart, không upload dữ liệu cho dịch vụ ML.
-1919H1 hợp lệ,11hour thiếu coverage bị loại; cần tick trong1phút đầu/cuối và≥100quotes mỗi bar. Kiểm tra coverage biên không chứng minh mọi gap nội bộ đều đã được phát hiện. Không tạo nến phẳng cho giờ nghỉ/cuối tuần.
-168session cutoffs có Asia profile;154đủ128closed H1 gần nhất và bar cuối kết thúc đúng cutoff. Context có thể gồm khoảng nghỉ thị trường; calendar timestamp được giữ, không ép thành chuỗi24/7 giả.
-Asia: forecast tại00:00UTC, đánh giá sau8h. NewYork:08:00local Mỹ chuyển theo DST, đánh giá sau9h. Mỗi input bar.end≤cutoff; không đưa current candle hoặc actual outcome cho predictor.
-OHLC-only theo API chính thức; volume/amount bỏ trống để upstream điền0, không coi quote count là giao dịch tập trung.
-Kronos-small, tokenizer-base; lookback128, max_context512,9steps generated (Asia dùng step8); T1, top_p0,9,3sample paths lấy trung bình, seed20261114. Không tuning, không đổi seed để chọn kết quả đẹp.
-Mỗi batch≤8windows,4CPU/4GB. Batch inference lớn nhất7,73s; forecast chỉ có hiệu lực từ cutoff+60s, hết khi session đóng. Ngưỡng latency được giữ rộng hơn thời gian batch đo thực.
-Điều kiện lọc: predictedClose của cuối horizon cao/thấp hơn last observed Bid close phải cùng hướng với Asia profile mà bot gốc dùng. Không đảo chiều bot, không thay RR/SL/risk. Forecast tie không cho entry ở agreement mode. Không diễn giải3paths là xác suất thắng đã hiệu chuẩn.
-Full tick replay từ đầu, không xóa dòng trên trade ledger cũ. Ba modes: full baseline; baseline chỉ ở windows có forecast/đã qua60s; coverage+agreement. Vị thế đã mở vẫn theo SL/TP dù qua hết session hoặc signal đổi.
-Config chính xác từ report đang được demo chọn: vốn giả lập50k, RR5/risk1%/balanceDD20%/minSL3/spread1,5/both sessions/swap on. Slip0,1 và stress0,2USD/oz. Đây không phải P&L tài khoản demo đang có số dư khác.

## Chất lượng dự báo

| Nhóm | Có nhãn | Đúng hướng model | Đúng hướng Asia bias | MAE model USD/oz | MAE giữ nguyên giá | MAE tiếp diễn momentum8H |
|---|---:|---:|---:|---:|---:|---:|
| Tất cả | 152 | 57.24% | 51.32% | 49.17 | 48.20 | 61.87 |
| Asia | 75 | 60.00% | 42.67% | 45.53 | 44.36 | 66.89 |
| NewYork | 77 | 54.55% | 59.74% | 52.72 | 51.93 | 56.99 |

MAE là lỗi của forecast close cuối horizon, không phải lỗi mỗi tick.152/154forecast có full H1 bar cuối để chấm; hai missing label không được coi là sai/đúng. Asia bias là hướng được biết đầu session (Asia dùng profile đã hoàn tất trước đó; NewYork dùng Asia cùng ngày). Độ đúng hướng là mô tả trên các phiên có tương quan, không có kiểm định ý nghĩa thống kê ở đây. Model có MAE hơi kém baseline giữ nguyên giá, dù hướng đúng hơn tổng thể.

## Kết quả giao dịch sau chi phí

Equity return gồm mark-to-liquidation của vị thế còn mở. PF/win rate chỉ từ lệnh đã đóng.

| Mode | Slip | Lệnh đóng | Wins | Win rate | Equity return | Max equity DD | PF | Vị thế cuối |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bot gốc toàn kỳ | 0.10 | 87 | 18 | 20.69% | +10.01% | 11.59% | 1.214 | 1 |
| Bot gốc toàn kỳ | 0.20 | 88 | 18 | 20.45% | +9.92% | 11.76% | 1.212 | 1 |
| Gốc cùng coverage | 0.10 | 84 | 16 | 19.05% | +8.52% | 11.40% | 1.212 | 1 |
| Kronos đồng hướng | 0.10 | 47 | 5 | 10.64% | -9.23% | 14.79% | 0.595 | 0 |
| Gốc cùng coverage | 0.20 | 85 | 16 | 18.82% | +8.06% | 11.70% | 1.199 | 1 |
| Kronos đồng hướng | 0.20 | 47 | 5 | 10.64% | -9.29% | 14.84% | 0.593 | 0 |

Full baseline tại slip0,1 khớp tất cả trường kết quả cũ của selected original report (87closed/18wins/net equity5003,290527USD). Agreement chỉ47closed/5wins, net equity−4614,358690USD. Khi tăng slip, net equity−4647,235266USD. Chênh lệch coverage (+8,52% so với full+10,01%) được tách riêng; không nhận công model chỉ do nó không dự báo những phiên đầu thiếu lookback.

Một dự báo đúng chiều ở8–9h không khẳng định giá chạm TP5R trước SL. Lệnh gốc có thể giữ nhiều ngày, và việc bỏ một entry thay đổi exposure/timing của những entry sau. Đây là lý do phải replay toàn bộ thay vì suy luận lợi nhuận từ direction accuracy hoặc lọc87lệnh gốc. Dữ liệu bốn tháng đã từng dùng nghiên cứu; chưa là holdout mới. Không xác minh khả năng trùng dữ liệu pretraining và không thử finetuning. Không có quyền/đề xuất triển khai từ kết quả này.

## Nguồn và môi trường

[Kronos chính thức](https://github.com/shiyu-coder/Kronos), [Kronos-small](https://huggingface.co/NeoQuasar/Kronos-small), [tokenizer-base](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-base). Dùng API dự báo OHLC-only đã công bố, không chép toàn bộ train stack. Tải4files mã/giấy phép, review import/I/O, dùng safetensors; không pickle/trust_remote_code.

Upstream source commit: `67b630e67f6a18c9e9be918d9b4337c960db1e9a`.
Model `NeoQuasar/Kronos-small` revision `901c26c1332695a2a8f243eb2f37243a37bea320`; weights SHA256 `b082dfcbd8e8c142a725c8bbb99781802f38fec81210e13479effb32b3c3e020`.
Model `NeoQuasar/Kronos-Tokenizer-base` revision `0e0117387f39004a9016484a186a908917e22426`; weights SHA256 `59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee`.

Python trong container3.14; torch2.15.0+cpu, numpy2.5.4, pandas3.0.6; einops0.8.1, huggingface_hub0.33.1, safetensors0.6.2. Dùng image freqtrade stable_freqai sẵn có cho Python/deps nền; model chạy riêng, không chạy dịch vụ freqtrade. Dependencies cài bằng pip --target vào audit/kronos/deps, không cài host hoặc worker. Image tag là mutable; manifest nguồn/weights/data được ghim riêng, lần tái lập nên giữ cùng image local. Toàn bộ cache/deps/model/evidence khoảng1,1GB, ignored.

Forecast data SHA256: `b1228b22bb954cf4485c15b3b301ecb820f6d6110f40743a149a50a6d7ecc33e`; replay forecast SHA256: `477387c71c6603a6c21a518e6ca9ded894160acc8825aecebb23503c9dc8349c`. Raw OHLC/session input, profiles source provenance, forecasts/truth, checkpoints và full ledgers đều ở ignored `openapi/audit/kronos/`; chỉ tổng hợp này vào source. Mạng chỉ dùng tải package/model chính thức; inference/backtest dùng --network=none, không mount private config/socket broker.

## Tái lập và kiểm tra

Source export: `export-kronos 2026-01-01 2026-05-01 audit/kronos/data.json` trên DLL build tạm. Predictor: `python kronos_probe.py ROOT` trong container có PYTHONPATH trỏ deps/vendor local. Replay: `backtest 2026-01-01 2026-05-01 --config audit/kronos/config.json --kronos-signals audit/kronos/forecasts.json --output audit/kronos/replay`. Không build đè runtime khi demo đang chạy.

`python3 -B openapi/check_kronos.py`:4causality/data tests pass: future bars không đổi input context, bar thiếu không forward-fill, duplicate/invalidOHLC bị từ chối, missing labels không được chấm. C# check-backtest: availability/expiry, coverage-vs-agreement, direction/session routing, blocking before fees và forecast input cutoff tương lai bị từ chối; existing SMC/range/backtest checks pass. Build0warnings/errors, diff whitespace clean. Không claim đã kiểm định live fill.

Result reports researchOnly, default output ở audit/, execution Apply từ chối; worker không import model hay đọc forecast file. Source integration chỉ là CLI offline. Final read-only check: active/running demo, same config revision, same DLL hash,1position; không Start/Stop/Apply/restart hoặc lệnh thử. Màn hình không bị bật lại bằng tác vụ này.
