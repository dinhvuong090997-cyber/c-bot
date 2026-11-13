# Aurum — XAUUSD execution and research

Linux dashboard and independent C# execution worker for FxPro cTrader Open API. The English desktop UI includes Live price/position monitoring, backtest equity/drawdown, historical candle charts and recorded-bar replay.

## Run locally

Requires rootless Podman. The wrapper builds with the pinned .NET 8 SDK image.

```bash
cd openapi
./api setup
./api start
./api ui
```

Configure the cTrader app at http://localhost:8787/ and open the dashboard at http://localhost:8788/. Apply a reviewed backtest config and explicitly press Start to enable execution. Restarting the dashboard does not restart the separate worker.

Credentials live only in `~/.config/fxpro-openapi/`. Broker tick data, account reports, logs, build outputs and private QA screenshots are excluded from Git. Download/export data locally before running a backtest. Setup and verification: [openapi/README.md](openapi/README.md).

`cbot/AsiaSession.cs` supplies the shared strategy rules; `cbot/` also contains the earlier cTrader Automate variant. The Python scripts and notes below are historical research and need the separate `../xauusd-news` tick dataset where documented.

---

# Nghiên cứu hệ thống XAUUSD cho vốn 50.000–100.000 USD

## Kết quả hiện tại

### Opening range London

Dùng tick bid/ask công khai cho 2024–2025. Lấy vùng 08:00–08:15 giờ London. Tín hiệu đầu tiên vượt vùng thêm 5% chiều rộng trước 09:00 và có spread không vượt 1,5 lần trung vị của vùng. So hai luật vào lệnh theo và ngược breakout. Tối đa một lệnh/ngày, stop cách nửa chiều rộng vùng với mức tối thiểu 1 USD/oz, target 1,5R, thoát chậm nhất 10:00. Lệnh stop khớp theo tick với độ trễ và phần trượt giá của kịch bản, target khớp tại giá giới hạn nếu quote có thể thực hiện chạm mức đó.

Khối lượng làm tròn xuống theo 1 oz. Rủi ro dự kiến tối đa 0,25% vốn/lệnh (125 hoặc 250 USD lúc khởi tạo), notional tối đa bằng vốn hiện tại. Dừng sau khi drawdown theo vốn đã đóng chạm 5%. Stop có thể khớp vượt ngưỡng, nên drawdown thực tế có thể vượt 5%. Commission 0,07 USD/oz hai chiều. Kịch bản cơ sở thêm trễ 1 giây và trượt 0,10 USD/oz mỗi lượt market. Kịch bản stress dùng 3 giây và 0,25 USD/oz.

| Năm | Luật | 50.000 USD | 100.000 USD |
|---|---|---:|---:|
| 2024 | Theo breakout | −2.513,00 | −5.020,52 |
| 2024 | Ngược breakout | −2.386,68 | −4.809,27 |
| 2025 | Theo breakout | −2.082,85 | −4.175,86 |
| 2025 | Ngược breakout | −2.513,92 | −5.003,40 |

Cả tám lượt cơ sở chạm ngưỡng dừng. Số lệnh và kịch bản có hoặc không bật ngưỡng dừng nằm trong `capital.csv`. Mỗi năm và mức vốn là một mô phỏng độc lập. Kết quả này loại hai luật London đã thử khỏi danh sách để xác minh trên broker.

### CPI, đánh ngược cú chạy đầu tiên

Kiểm tra trên năm công bố CPI đầu năm 2026, khóa quy tắc từ lần xem dữ liệu 2025. Cùng ngưỡng spread và cách vào lệnh như nghiên cứu trước. Giữ 15 phút. Lãi bình quân sau spread và commission: +2,518 USD/oz khi khớp tick tiếp theo, +2,795 với trễ 1 giây, +2,357 với trễ 3 giây. Bốn ngày đối chứng có tick cho trung bình −3,574 USD/oz ở tick tiếp theo, một ngày thiếu tick. Mẫu gồm năm giao dịch, chưa dùng để suy ra khả năng scale vốn. Bài test CPI này chưa áp dụng stop, giới hạn kích thước hoặc mô hình khớp ở các mức khối lượng.

## Bằng chứng cần cho hệ thống hoàn chỉnh

- Chạy lại ứng viên trên Gold CFD IC Markets trong StrategyTune và lưu báo cáo lệnh. So sánh timestamp, spread và giá khớp với dữ liệu nghiên cứu local.
- Với luật đã khóa, kiểm tra trên các giai đoạn chưa dùng để chọn luật. Báo cáo chi phí theo broker, số lệnh, P&L kỳ vọng, drawdown, độ tập trung vào vài giao dịch và độ nhạy với điều kiện khớp.
- Mô phỏng riêng 50.000 và 100.000 USD, bao gồm cách tính khối lượng, margin theo tài khoản, khả năng khớp theo khối lượng, lệnh bị từ chối và stop trượt. Kiểm tra giả lập trước khi xem xét dùng vốn thật.

## Dữ liệu và chạy lại

`trades.csv` lưu lệnh London, `capital.csv` lưu thống kê vốn, `cpi-holdout-trades.csv` và `cpi-holdout-sessions.csv` lưu bài CPI. Nguồn tick là bộ public CarlosSilva1/xauusd-ticks, báo cáo StrategyTune chưa có. Công bố CPI lấy từ [BLS](https://www.bls.gov/bls/news-release/cpi.htm). Contract size và commission tham chiếu [IC Markets](https://cdn.icmarkets.com/uploads/Commodity-Specification-Sheet-Global.pdf).

`./run` dùng dữ liệu từ `../xauusd-news/ticks`. Để tái lập báo cáo London 2024–2025, chỉ đọc các partition năm 2024–2025.

### CPI với stop và quy mô tài khoản

Mô phỏng 52 kỳ CPI thực tế từ tháng 01/2022 đến 05/2026. Phần 2022–2023 là kiểm tra hồi cứu bổ sung. Quy tắc mới dùng stop cách giá khớp một khoảng bằng biên độ dịch chuyển phút đầu, tối thiểu 2 USD/oz. Khối lượng tính từ quote lúc phát tín hiệu, làm tròn xuống 1 oz, dự kiến rủi ro 0,25% vốn/lệnh và giới hạn notional xấp xỉ 1× vốn. Không sửa khối lượng dựa trên quote tương lai. Thoát sau 15 phút nếu chưa chạm stop. Báo cáo drawdown dựa trên đỉnh vốn đã đóng, có thêm cột kiểm tra giá bất lợi trong lệnh so với đỉnh vốn đã đóng.

| Kịch bản | Lãi/lỗ vốn 50.000 USD | Lãi/lỗ vốn 100.000 USD |
|---|---:|---:|
| Quote tick tiếp theo | −229,69 USD | −513,00 USD |
| Cơ sở, trễ 1 giây và 0,10 USD/oz mỗi chiều | −155,32 USD | −369,31 USD |
| Stress, trễ 3 giây và 0,25 USD/oz mỗi chiều | −426,50 USD | −895,64 USD |

Ở vốn 100.000 USD, kịch bản cơ sở đặt tối đa 57 oz, drawdown theo lệnh đã đóng 1,47% và có hai lệnh lỗ vượt ngân sách dự kiến sau khi khớp stop. Riêng năm 2026, biến thể có stop đạt +1,00 USD/oz trung bình trong kịch bản cơ sở, nhưng khi tính khối lượng theo từng lệnh thì tài khoản 100.000 USD lỗ 159,08 USD. Khối lượng nhỏ ở sự kiện có cú chạy lớn làm lệnh thắng tháng 2 đóng góp ít hơn khoản lỗ tháng 1. Không sử dụng biến thể này để scale vốn. Mô hình quote chưa đo độ sâu hay khả năng khớp thực tế của 57 oz.

Để tái lập, bổ sung dữ liệu tick năm 2022–2023 và tháng 01–05/2026, rồi chạy `./run-cpi`. Dữ liệu ngày trong `cpi-history.csv`, chi tiết khớp theo ounce trong `cpi-sized-fills.csv`, chi tiết từng tài khoản trong `cpi-sized-orders.csv`, thống kê trong `cpi-capital.csv`.

### Momentum từ phiên Á sang châu Âu

Xác định hướng từ midpoint đầu ngày UTC đến tick cuối trước 08:00 UTC. Dùng tick trong phút sau 08:00 khi spread không quá 1,5 lần trung vị 5 phút trước. Stop tối thiểu 2 USD/oz hoặc một nửa biên độ phiên Á, thoát theo giờ lúc 10:00 UTC. Quy mô dự kiến 0,25% vốn/lệnh, giới hạn notional xấp xỉ 1× vốn, tối đa một lệnh mỗi ngày và dừng khi drawdown vốn đã đóng chạm 5%. Bản local so thêm đảo chiều, luôn long và luôn short.

| Mẫu tick public | Vốn 50.000, cơ sở | Vốn 100.000, cơ sở | Vốn 100.000, stress |
|---|---:|---:|---:|
| 2022–2023 | −4,26% | −4,26% | −4,96% |
| 2024–2025 | +3,21% | +3,32% | −0,20% |
| 01–04/2026 | +0,60% | +0,56% | +0,37% |

Mỗi giai đoạn khởi tạo vốn riêng. Giai đoạn 2022–2023 kích hoạt ngưỡng dừng và vì thế chấm dứt cả mô phỏng liên tục. Mô phỏng 100.000 USD cơ sở giai đoạn này có drawdown 5,09%. `./run-session` tạo `session-capital.csv` và `session-trades.csv`.

Đã lưu script TypeScript **XAUUSD Asia to Europe momentum v1** trong StrategyTune và chạy trên Gold CFD IC Markets, 01/05–11/11/2026. Báo cáo dùng chart 1h và script xử lý quote theo `onUpdate`. Script cloud thêm trễ 1 giây khi vào, stop tích hợp và đệm 1% khi tính trần notional. Commission dự kiến được dùng cho sizing. Chưa xác minh cách StrategyTune đưa commission vào P&L và chưa mô phỏng phần trượt giá cố định của kịch bản local trong script cloud.

| Vốn mô phỏng | Net P&L hiển thị | Lệnh | Win rate | Run |
|---|---:|---:|---:|---|
| 50.000 USD | +689,49 USD | 129 | 48,8% | de4c445d-dcb0-4379-ad3d-6f0df400ef53 |
| 100.000 USD | +1.300,33 USD | 129 | 48,8% | b819eb9f-56aa-42e9-b9c5-e27b7ce7d136 |

Kết quả là ứng viên để kiểm tra thêm trên feed IC Markets qua giai đoạn 2022–2023 và với chi phí khớp đã xác minh. Cần lấy báo cáo drawdown và danh sách lệnh cloud để đối chiếu.

### Momentum M1 cả ngày, một vị thế

StrategyTune script **XAUUSD All-day M1 Momentum SL TP v1**. Mỗi nến M1 mới xét hướng của 60 nến đã đóng liên tục. Không lọc theo giờ. Chỉ mở khi vị thế bằng 0 và spread không quá 10% khoảng stop. Stop bằng một nửa biên độ 60 nến, tối thiểu 2 USD/oz. TP 1,5R. Script không thoát theo giờ. Giữ cách tính khối lượng rủi ro dự kiến 0,25% vốn và khóa mở mới khi drawdown vốn đã đóng chạm 5%.

| Vốn | Net P&L StrategyTune | Lệnh | Win rate | Run |
|---|---:|---:|---:|---|
| 50.000 USD | −1.403,13 USD (−2,81%) | 252 | 38,5% | 5171c302-af76-43ee-a50d-308b50ff1c2a |
| 100.000 USD | −2.912,53 USD (−2,91%) | 252 | 38,5% | a80e29ca-773d-40d4-898a-52b15c7c8c5e |

Gold CFD IC Markets, 01/05–11/11/2026. Số lệnh tăng từ 129 lên 252 khi đổi sang biến thể cả ngày với SL/TP. Hai biến thể khác cả cách tạo tín hiệu và cách thoát. P&L là số hiển thị của StrategyTune, chưa đối soát commission.

### Momentum phiên Á, vào lại sau SL/TP

StrategyTune **XAUUSD Asia Momentum Re-entry SL TP v1** giữ hướng 00:00–08:00 UTC, ngưỡng spread từ 5 phút trước 08:00, khoảng stop theo nửa biên độ phiên Á và sizing từ bản gốc. Sau 08:00, nếu đang phẳng và spread đủ hẹp thì được vào theo hướng phiên Á, tối đa một lần thử mỗi phút, trễ 1 giây. TP 1,5R, giữ tối đa một vị thế, không có lệnh thoát theo giờ trong script. Vị thế có thể qua ngày. Script không mở mới trước khi hình thành tín hiệu phiên Á ngày đó.

| Vốn | P&L hiển thị | Lệnh | Win rate | Run |
|---|---:|---:|---:|---|
| 50.000 USD | +218,62 USD (+0,44%) | 351 | 40,5% | 1f52626a-691d-4bd9-87df-7b81654b1cc9 |
| 100.000 USD | +323,35 USD (+0,32%) | 350 | 40,6% | 84e91bbe-6bac-4506-bbab-28e63f9bc971 |

Gold CFD IC Markets, M1, 01/05–11/11/2026. Bản gốc cùng thời đoạn lần lượt +689,49 và +1.300,33 USD với 129 lệnh. Bản vào lại có nhiều lệnh hơn và P&L thấp hơn. Chưa đối soát commission, phí giữ qua ngày hay drawdown trên cloud.

### Cùng momentum phiên Á với RR 1:3

StrategyTune **XAUUSD Asia Momentum Re-entry 3R v1** dùng cùng mã chiến lược với bản 1:1,5 và chỉ đổi `tpRR` từ 1,5 sang 3. Cùng Gold CFD IC Markets, M1, 01/05–11/11/2026 và hai mức vốn mô phỏng.

| Vốn | P&L hiển thị | Lệnh | Win rate | Run |
|---|---:|---:|---:|---|
| 50.000 USD | −976,36 USD (−1,95%) | 153 | 23,5% | 76729b62-4a2a-4022-9142-89f9607556eb |
| 100.000 USD | −2.312,38 USD (−2,31%) | 139 | 23,7% | b5330204-c1f7-4792-a3bc-42a194f696a2 |

P&L là số StrategyTune hiển thị, chưa đối soát commission và phí qua đêm.

### Chỉ mở lệnh phiên Á và New York, RR 1:3

StrategyTune **XAUUSD Asia and New York Momentum 3R v1** chỉ mở lệnh 00:00–08:00 UTC hoặc 08:00–17:00 giờ New York (tự đổi DST). Phiên Á dùng hướng, khoảng stop và ngưỡng spread của phiên Á hoàn tất gần nhất, tối đa bốn ngày trước. Phiên New York dùng phiên Á cùng ngày. Vị thế tối đa một, SL nửa biên độ với mức tối thiểu 2 USD/oz, TP 3R. Script không thoát theo giờ. Rủi ro dự kiến 0,25% vốn và dừng mở lệnh mới khi drawdown vốn đóng chạm 5%.

| Vốn | P&L StrategyTune | Lệnh | Win rate | Run |
|---|---:|---:|---:|---|
| 50.000 USD | −1.102,32 USD (−2,20%) | 175 | 24,0% | 51695726-b418-4c4b-8020-73673a5c83a9 |
| 100.000 USD | −1.978,06 USD (−1,98%) | 169 | 24,3% | 10e9cf6a-b7b0-4595-860b-4fc299644cfe |

Gold CFD IC Markets, M1, 01/05–11/11/2026. P&L hiển thị chưa đối soát commission hoặc phí qua đêm. Cấu hình giờ đồng thời đổi nguồn tín hiệu trong phiên Á, vì vậy kết quả không cô lập tác động của giờ vào lệnh. Hai lượt mở ban đầu đã chọn nhầm script Asia to Europe mặc định, được loại khỏi số liệu trên.

### So sánh RR 1:2 và 1:1,5 trên hai phiên

Cùng script phiên Á và New York, thay riêng `tpRR`. Gold CFD IC Markets, M1, 01/05–11/11/2026.

| RR | Vốn | P&L StrategyTune | Lệnh | Win rate | Run |
|---|---:|---:|---:|---:|---|
| 1:2 | 50.000 USD | +1.129,14 USD | 271 | 35,4% | ed83e63a-3283-4b4a-a9ca-7b9da36c74ea |
| 1:2 | 100.000 USD | +3.009,10 USD | 270 | 35,6% | 6e343412-f825-4ec8-8516-b67f1ef2fb1e |
| 1:1,5 | 50.000 USD | +1.632,82 USD | 342 | 42,1% | 973be0e9-da56-453a-809d-1ca97351a76a |
| 1:1,5 | 100.000 USD | +3.680,31 USD | 342 | 42,1% | 62b8da72-b23f-42f5-809f-b6afd17a6deb |

P&L chưa đối soát commission, phí qua đêm và drawdown cloud. Đây là giai đoạn đã dùng để so nhiều biến thể RR, cần một giai đoạn riêng để xác minh RR đã chọn.

### FxPro Open API tick replay — January–April 2026

Tải đủ 120 ngày UTC (01/01/2026 đến trước 01/05/2026) từ tài khoản FxPro cTrader demo; 21.834.498 snapshot bid/ask sau ghép tick cùng millisecond. Sửa phân trang API bằng chồng lấn 1 ms và loại trùng tại ranh giới; cache data/fxpro-v2 mới được dùng cho kết quả. Đối soát độc lập nến M1 và các phút tải riêng, có ghi nhận ba chênh lệch cực trị nhỏ giữa nến và tick endpoint, tối đa 0,04 USD/oz.

| Vốn | RR | P&L equity liên tục | DD equity tối đa | Lệnh đóng |
|---:|---:|---:|---:|---:|
| 50,000 USD | 1:1.5 | -2,394.92 USD | 5.24% | 62 |
| 50,000 USD | 1:2 | -2,333.17 USD | 5.06% | 39 |
| 100,000 USD | 1:1.5 | -4,809.52 USD | 5.23% | 61 |
| 100,000 USD | 1:2 | -4,719.49 USD | 5.11% | 38 |

Cả hai RR dừng mở lệnh trong tháng 1 do drawdown số dư chạm 5%; vị thế có sẵn vẫn được quản lý đến SL/TP. Tất cả 16 kịch bản liên tục (hai mức vốn, hai RR, hai mức trượt, bật/tắt swap) đều lỗ và chạm ngưỡng dừng. Với các tháng đặt lại vốn 50k độc lập, RR1,5 lần lượt −2.394,92; −1.087,72; +403,30; −1.374,06 USD. Không cộng các lượt đặt lại vốn thành thành tích tài khoản liên tục. Chưa đạt điều kiện để khởi chạy chiến lược này.

Phí commission theo metadata FxPro là 35 USD/triệu USD mỗi chiều; swap hồi chiếu theo mức hiện tại, chưa có lịch swap lịch sử. Không có khớp lệnh thật trong phép thử. 80 lượt được đối soát kế toán, phiên vào lệnh, vị thế đơn, khối lượng và ngưỡng dừng; có kiểm tra riêng SL gap, TP, trượt giá, DST, profile và warm-up. Giai đoạn này nằm ngoài kỳ so RR 05–11/2026, nhưng đã xuất hiện trong nghiên cứu trước, nên không phải holdout hoàn toàn chưa quan sát.

Báo cáo, biểu đồ và CSV: `openapi/reports/fxpro-20260101-20260501/`. Dashboard tiếng Anh local: `http://localhost:8788/`, chạy bằng `openapi/api ui`. Giao diện đọc tài khoản thật được cấp quyền, hiển thị kết quả, lọc lịch sử, xuất CSV và chạy backtest cấu hình mới. Worker giao dịch chạy độc lập; Apply cấu hình và Start là hai thao tác riêng. Chi tiết và giới hạn tại `openapi/README.md`.
