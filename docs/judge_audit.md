# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt (exit 0) | **dùng** (chỉ cho giọng văn, không cho tiền) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (exit 1) | **loại** |

Ma trận nhầm lẫn (FAIL = lớp dương):
- tone_ok: TP 24 · FP 4 · FN 6 · TN 66. Tỉ lệ FAIL quan sát 0.28 → hiệu chỉnh Rogan-Gladen 0.30 (sens 0.8, spec 66/70 = 0.943).
- helpful: TP 9 · FP 0 · FN 21 · TN 70. Tỉ lệ FAIL quan sát 0.09 → hiệu chỉnh 0.30: judge bỏ sót 2/3 số reply hỏng.

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã với khách khiếu nại. Sửa rubric: thêm quy tắc xưng hô "LogiX ↔ anh/chị", liệt kê "em/bạn/nha/nhé" là FAIL, kèm 1 ví dụ âm. |
| 2 | tone H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge bị đánh lừa bởi "Dạ, vui lòng" ở đầu câu. Sửa rubric: chấm cả câu, câu mệnh lệnh/chặn khách liên hệ ("không cần nhắn thêm") là FAIL dù có kính ngữ. |
| 3 | tone H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | Người | Hứa hẹn ngoài kết quả hệ thống. Đây không phải lỗi giọng văn mà là FM-08 (nói khác ledger): đưa sang grader code `reply_matches_ledger`, rubric tone ghi rõ "không chấm nội dung tiền". |
| 4 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". Sửa rubric: xin lỗi **không bắt buộc** khi đã giải quyết xong; ngắn gọn, lịch sự là PASS. |
| 5 | tone H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | CS LogiX cho phép từ "refund". Sửa rubric: thêm danh sách từ tiếng Anh được phép (refund, ship, voucher). |
| 6 | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Ghi chú CSV: nhãn người sai (đọc nhầm ticket). Hành động: sửa nhãn người trong tập calibration và chạy lại κ, không đổi rubric. |
| 7 | tone H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Emoji cười trong ngữ cảnh khiếu nại. Sửa rubric: emoji là FAIL. |
| 8 | tone H-094 "Da, LogiX da hoan 40.000đ…" (mất dấu) | PASS | FAIL | Người | Văn bản mất dấu tiếng Việt. Sửa rubric: thiếu dấu/dịch máy là FAIL. |
| 9 | helpful HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | Người | Judge không thấy ledger nên không thể biết số tiền sai. 18/21 lỗi bỏ sót của helpful là "sai tiền" (HL-015, 016, 020, 028, 035, 041, 043, 053, 058, 062, 070, 072, 074, 087, 090, 096, 098, 100). Hành động: **không** sửa rubric judge mà chuyển tiêu chí "đúng số tiền" sang grader code `reply_matches_ledger` (FM-08). |
| 10 | helpful HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Sai xưng hô và không nói kết quả (3/21 lỗi bỏ sót, cả HL-091, HL-097). Hành động: phần xưng hô thuộc tone_ok (đã đạt FLOORS); phần "nói rõ kết quả" cần rubric mới + nhãn mới trước khi dùng. |

## Kết luận
- **tone_ok dùng được**: κ 0.757, P 0.857, R 0.8 đều trên FLOORS. Chỉ dùng để chấm giọng văn; lỗi còn lại (6 FN, 4 FP) là quy tắc xưng hô/emoji/mệnh lệnh chưa có trong rubric (case 1–8), sửa như bảng trên rồi calibrate lại.
- **helpful bị loại khỏi gate**: R = 0.3 (TP 9, FN 21) và κ = 0.375 < 0.6. P = 1.0 chỉ vì judge gần như không bao giờ nói FAIL: nó bắt 9/30 reply hỏng, bỏ sót 21. Nếu làm gate, nó cho qua 70% reply sai; tỉ lệ lỗi quan sát 0.09 trong khi hiệu chỉnh Rogan-Gladen là 0.30. Nguyên nhân chính: 18/21 lỗi bỏ sót là **sai số tiền so với ledger**, thứ judge chỉ đọc reply không thể biết. Theo quy tắc "tiền luôn chấm bằng code", tiêu chí này thuộc `reply_matches_ledger` (FM-08), không thuộc judge.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng, có cả nhãn người sai như H-081); cần nhãn người mới để có held-out thật trước khi tin số κ.
