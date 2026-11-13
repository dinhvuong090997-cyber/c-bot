# FxPro Gold Momentum cBot

C# cBot thử nghiệm cho tài khoản FxPro cTrader demo bằng USD. Dùng bid/ask tick và một vị thế trên cùng mã vàng. Bản này chặn tài khoản tiền thật khi chạy realtime.

## Luật

- Phiên Á 00:00–08:00 UTC dùng hồ sơ phiên Á hoàn tất gần nhất trong bốn ngày. Phiên Mỹ 08:00–17:00 giờ New York dùng hồ sơ phiên Á cùng ngày. Không gửi lệnh mới cuối tuần hoặc ngoài hai phiên.
- Dùng hướng midpoint đầu–cuối phiên Á. Khoảng SL bằng nửa biên độ, tối thiểu 2 USD/oz, làm tròn lên theo bước giá broker. TP mặc định 1,5R. Vị thế chỉ thoát theo SL/TP trong điều kiện bình thường. Không đóng lệnh khi hết phiên.
- Ngưỡng spread là 1,5 lần trung vị tick trong năm phút cuối phiên Á. Tối đa một lần thử mỗi phút. Chờ 1 giây và kiểm tra lại spread trước khi gửi. Bot tính kích thước từ quote lúc gửi, kiểm tra margin và dùng bước khối lượng broker. Hai kiểm tra lúc gửi và bước giá broker có thể tạo chênh lệch so với StrategyTune.
- Rủi ro dự kiến 0,25% số dư/lệnh. Đệm chi phí 0,17 USD/oz chỉ dùng để sizing, cần đối chiếu phí FxPro. Trần notional dùng đệm giá 1% trước khi gửi. Tạm dừng mở lệnh khi drawdown số dư đóng chạm 5%. Stop thực tế có thể trượt.
- Sau khi khởi động, bot phải quan sát đủ tick của một phiên Á mới có hồ sơ. Nên dùng một instance trên tài khoản demo riêng. Wrapper gắn thư mục runtime vào reports/runtime. Chưa xác minh LocalStorage trên phiên FxPro đã đăng nhập. Không khởi động lại một instance bị dừng vì thiếu SL/TP khi vị thế chưa được xử lý.

## Build và metadata

```bash
./build
./cli metadata
```

File tại `bin/Release/net6.0/FxProGoldMomentum.algo`. SDK .NET 8 dùng để build. Gói cTrader.Automate 1.0.21 tạo artifact với target net6.0. Spotware CLI đọc được metadata. Chạy cBot trên tài khoản vẫn cần xác minh.

## Backtest trên Fedora

Cài Podman và đăng nhập FxPro cTrader demo. Thiết lập biến môi trường `CTID`, `CTRADER_ACCOUNT`, `CTRADER_SYMBOL` và `CTRADER_PASSWORD_FILE`. File mật khẩu ở ngoài dự án, quyền 600. Chọn mã vàng theo ounce trên chính tài khoản FxPro, ví dụ GOLD nếu danh sách symbol của tài khoản dùng tên đó.

```bash
./cli backtest --start="01/01/2025 00:00" --end="01/05/2026 00:00" \
  --balance=50000 --data-mode=ticks --commission-auto --data-dir=/reports/data \
  --report-json=/reports/fxpro-gold-50k-1p5r.json --RewardToRisk=1.5
```

Thay `--balance` và tên report để thử 100.000 USD. Kiểm tra commission trong report và lấy thông số swap theo tài khoản trước khi dùng P&L để kết luận. Bài test dùng giai đoạn khác với giai đoạn đã chọn RR. Sau khi kiểm tra báo cáo, có thể chạy thử `./cli run --RewardToRisk=1.5` trên demo.

Bot xuất dòng `BOT_STATUS` dạng JSON mỗi 5 giây khi realtime. Dashboard có thể dùng timestamp tick cuối để nhận biết dữ liệu cũ. Giao diện và cơ chế áp dụng config qua dashboard chưa được nối với cBot.
