# PA event path audit — 2026-11-14

**Kết luận:** với quy tắc PA hiện tại, việc giá có thể chạy xa sau tín hiệu không đồng nghĩa lệnh sống tới mục tiêu. Các mẫu range3 đủ điều kiện cơ bản trên dữ liệu May–Jun mới chỉ11/98tới3R trướcSL trong30phút;65SL trước,22timeout. Chưa chứng minh lợi thế hoặc đưa ra chiến lược có lãi.

## Phép đo đã chốt trước khi đọc kết quả

Toàn bộ xác nhận cung–cầu PA range2/3/5 được giữ lại, kể cả trước đây bị gate chặn. Freeze swing/regime tại confirmation; entry quan sát tại quote đầu tiên từ+1sđến+6s, actualAsk/Bid+slip0.10; zonebuffer=max(spread,0.1range), SLmin3USD làm tròn outward. Hai horizon5/30phút. Mục tiêu giả định3R chỉ dùng outcome audit, KHÔNG thay nearest-swing target của strategy. Không sizing, không tiền P&L, không commission/swap/exit slippage được giả định như kết quả net.

First touch dùng quote thực thi (Bid khiBUYexit/Ask khiSELLexit), không suy thứ tự từ OHLC. Gap>60s trước endpoint censors outcome chưabiết; nếu barrier đã chạm trướcgap thì kết quả firsttouch vẫn biết, nhưng MAE/MFE fullhorizon không hoàn chỉnh. Timeout chỉ dùng dữ liệu tới endpoint và lastquote trong60s; thiếu entry/tail riêng. Không đọc quote sau horizon để tạo fill.

Chọn Jan–Feb khám phá, Mar–Apr đã xem trước, May–Jun vừa tải là đánh giá mới với protocol cố định. Sau khi báo cáo này được đọc, May–Jun không còn là holdout chưa nhìn cho lần chỉnh sửa tiếp. Warmup tối đa4ngày, đọc thêm30phút+6s sau end nếufilecó. Ledger2,052events /4,104horizonpaths; các horizon vàrange có phụ thuộc, không coi là4,104mẫu độc lập.

## Range3,30phút: mẫu đủ điều kiện cơ bản

BASIC=đã có entry, spread<=0.2range, tín hiệu còn trong vùng validity lúc entry và phiên của signal khôngClosed. Chưa lọc regime/nearest-targetRR, chưa áp đặt1position/once-minute; đây không phải tập lệnh backtest có thể khớp đồng thời.

| Kỳ | Mẫu | 3R trước SL | SL trước | Hết thời gian | Tỉ lệ3R | Ngày có mẫu | Mẫu có window chồng lấn |
|---|---:|---:|---:|---:|---:|---:|---:|
| Jan–Feb | 193 | 44 | 128 | 21 | 22.8% | 38 | 79 |
| Mar–Apr | 157 | 23 | 120 | 14 | 14.6% | 37 | 41 |
| May–Jun (mới) | 98 | 11 | 65 | 22 | 11.2% | 38 | 17 |

Nhóm này không có censored outcome, nhưng Jan–Feb có1firsttouch đã biết trước gap nên chỉ192/193fullhorizon excursions hoàn chỉnh. Các tín hiệu chưa có entry/censored khác vẫn nằm trong ledgerALL, không bị âm thầm xóa. Tỉ lệ3R tính trên outcomeđãbiết (3R/SL/timeout), không loại timeout để tăng hitrate. Đây KHÔNG phải winrate/PF của chiến lược hiện tại.

## Mức nhạy theo horizon và cỡ range

| Kỳ | Range | Horizon phút | BASIC events | 3R | SL | Time | Censored |
|---|---:|---:|---:|---:|---:|---:|---:|
| Jan–Feb | 2 | 5 | 276 | 34 | 167 | 75 | 0 |
| Jan–Feb | 3 | 5 | 193 | 24 | 95 | 74 | 0 |
| Jan–Feb | 5 | 5 | 91 | 5 | 43 | 43 | 0 |
| Jan–Feb | 2 | 30 | 276 | 54 | 206 | 16 | 0 |
| Jan–Feb | 3 | 30 | 193 | 44 | 128 | 21 | 0 |
| Jan–Feb | 5 | 30 | 91 | 11 | 62 | 18 | 0 |
| Mar–Apr | 2 | 5 | 314 | 26 | 171 | 116 | 1 |
| Mar–Apr | 3 | 5 | 157 | 7 | 78 | 72 | 0 |
| Mar–Apr | 5 | 5 | 67 | 3 | 18 | 46 | 0 |
| Mar–Apr | 2 | 30 | 314 | 62 | 235 | 16 | 1 |
| Mar–Apr | 3 | 30 | 157 | 23 | 120 | 14 | 0 |
| Mar–Apr | 5 | 30 | 67 | 12 | 39 | 16 | 0 |
| May–Jun (mới) | 2 | 5 | 199 | 11 | 88 | 100 | 0 |
| May–Jun (mới) | 3 | 5 | 98 | 4 | 28 | 66 | 0 |
| May–Jun (mới) | 5 | 5 | 40 | 0 | 7 | 33 | 0 |
| May–Jun (mới) | 2 | 30 | 199 | 32 | 142 | 25 | 0 |
| May–Jun (mới) | 3 | 30 | 98 | 11 | 65 | 22 | 0 |
| May–Jun (mới) | 5 | 30 | 40 | 1 | 19 | 19 | 1 |

## Regime và đường đi

| Kỳ | Range3 BASIC+aligned regime | Tới3R trướcSL (30phút) | Median MFE toàn30phút BASIC | Median MAE toàn30phút BASIC |
|---|---:|---:|---:|---:|
| Jan–Feb | 48 | 13 | 2.63R | 2.13R |
| Mar–Apr | 39 | 6 | 1.92R | 2.38R |
| May–Jun (mới) | 33 | 4 | 1.10R | 1.58R |

Đây là thống kê mô tả, không phải kiểm định ý nghĩa hay bằng chứng causal. Nhóm cùngchiều mới chỉ33mẫu/4touch3R; không có cơ sở tuyên bố regime gate tạo edge. Chưa tính CI vì mẫu chồng lấn và có phụ thuộc; không gắn binomialIID confidence giả. Cần validation temporal blocks/matched null/control trước claimedge.

MFE/MAE đo toàn cửa sổ quan sát kể cả sau SL hoặc TP; vì vậy MFEcao sau mộtSL không cứu được lệnh đã đóng. MedianMFE giảm trên mẫu mới là mô tả theoR, chưa chứng minh nguyên nhân volatility/entry muộn. Tín hiệu điều kiện/horizon khác nhau có censoring và selection khác nhau. Chưa so với random/control entries, chưa chọn tham số mới từ bảng.

## Tái lập và kiểm chứng

`audit-pa-paths START END OUTPUT` tạo paths.json/manifest.json; source/runtime/checks offline dướiignored audit/pa-paths và audit/pa-path-runtime. `python3 summarize_pa_paths.py audit/pa-paths` kiểm tra thời điểm/geometry/horizonconsistency và tạo summary.json/groupregime/session.

- C# tests đạt: delayedentry, spreadMAE, mirroredtouch,SLbeforelaterTP,endpointcausality,gap/endcensor và timeout không dùng quote ngoài horizon.
- Audit4,104paths: targetknown<=signal,entry1–6s,minSL3,hypotheticaltarget3R,khôngfuturefill, outcome5minfirsttouch không bị30minđảo, excursions nhất quán. Raw inventoryJan–Apr khớp exact1,605confirmations trướcđó.
- Build0warnings/errors; existing backtest/SMC/range tests đạt. Không gửi broker order hoặc sửa model/threshold.

Worker/config/runtime gốc và bộ thu thập giữ nguyên. Kết quả chỉ giúp chẩn đoán; không áp dụng3RTP mới, không thay cấu hình demo.
