# Ghi chú hai cheatsheet Quantt — 2026-11-14

Đã đọc4trang Mathematics và4trang Finance do người dùng gửi; trích xuất văn bản và kiểm tra ảnh render phần stochastic calculus/microstructure để tránh mất ký hiệu. Bản gốc giữ riêng trong ignored audit/quantt-pdfs; đây là ghi chú để tham chiếu trong dự án, không phải cập nhật trọng số hay huấn luyện model.

## Những nguyên tắc áp dụng cho Aurum

| Nguồn | Cách dùng trong nghiên cứu bot | Trạng thái |
|---|---|---|
| Maths p2: conditional probability/Bayes | Đo xác suất kết quả PA theo trạng thái có sẵn tại entry; báo số mẫu/base rate. Tín hiệu nghe mạnh không đồng nghĩa xác suất thắng cao. | Đề xuất đo, chưa triển khai |
| Maths p2: dependence, block bootstrap | Các tín hiệu dùng chung nhịp giá không độc lập; nếu ước lượng uncertainty phải giữ phụ thuộc thời gian, không shuffle từng tick/lệnh rồi gọi là bằng chứng độc lập. | Chưa triển khai bootstrap |
| Maths p2: multiple testing/holdout | Lưu mọi thử nghiệm và giữ dữ liệu tương lai chưa dùng để thiết kế; chọn mẫu thắng từ nhiều cấu hình không chứng minh edge. | Đã lưu scenarios; chưa có holdout dài mới |
| Maths p4: log vs simple returns/units | Không cộng phần trăm của các kỳ reset vốn; phân biệt giờ/phút/tick và biến động theo clock-time với range-event time. Không dùng sqrt-time như quy luật vô điều kiện. | Đã tách return các kỳ; vol study còn đề xuất |
| Finance p4: lagged EWMA/GARCH | Có thể dùng volatility trailing không ML như một mô tả regime; tham số0.94 ghi trong tài liệu là ví dụ daily, không tự lấy cho tick/range bars. | Chưa thêm vào chiến lược |
| Finance p4: microstructure/markout | Đánh giá đường giá sau tín hiệu/fill và costs; quote updates không phải tradevolume, không tự tính VWAP/orderflow từ tickcount. | Có raw Bid/Ask và costs; markout/MAE/MFE còn đề xuất |
| Finance p2/p4: risk/Kelly | Edge phải là kỳ vọng sau costs, không chỉ winrate hay geometricRR. Công thức Kelly2p−1 chỉ cho even-money, không áp thẳng cho5R/RRbiến đổi hoặc edge chưa chứng minh. | Không đổi risk/sizing demo |
| Finance p4: research→production | Tách research, shadow/demo và activation; không tự áp dụng mô hình mới vì đọc tài liệu. | Worker/config không đổi |

Định nghĩa làm việc: trước hết xem mean(net P&L), phân phối thắng/thua, thời gian giữ, DD và tỉ lệ chạm3R trướcSL theo sự kiện. Nếu net P&L đã gồm phí thì không trừ phí lần hai. Future path dùng để gắn outcome/evaluate, tuyệt đối không đi vào feature/zone/entry tại thời điểm tín hiệu.

## Phần cần đọc có điều kiện

- Mathematics p3: bảng CIR/Heston có dòng viết tắt, không phải phương trình đầy đủ để chép thành code. Risk-neutral pricing dướiQ phục vụ định giá theo giả định, không phải trực tiếp dự báo xác suất giá vàng tăng ngoài đời.
- Finance p1: options/parity/Greeks không tự thành chiến lược spot-CFD PA. Đoạn parity-arbitrage là sketch; phải dựng cashflows và kiểm tra nguồn chính thức trước khi triển khai bất kỳ giao dịch nào.
- Finance p2: công thức ES viết dạng conditional tail cần xử lý khối xác suất tại quantile khi dùng mẫu rời rạc; không coi VaR là mức lỗ tối đa chắc chắn.
- Finance p4: câu regime switching thường vượt globalGARCH không phải kết luận phổ quát choXAUUSD; cần bằng chứng trên dữ liệu/chi phí của chính bot. Không cài/training HMM, không tự chọn model theo cheatsheet.

Đây là tài liệu nhắc kiến thức, không xác nhận toàn bộ claims/code, không phải bằng chứng chiến lược có lãi. Những phép kiểm định/estimator mới phải có đặc tả, nguồn chính thức và tests riêng trước khi dùng.
