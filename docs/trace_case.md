# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case đã điền: `seeded_regression C-002@11`

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID `E-seeded_regression-20261118-ab8e` (eval set `ab8ebf0227f5`, item E-002). Cùng lỗi xuất hiện ở baseline `swarm C-002@55` (`E-swarm-20261118-ab8e`). |
| Triệu chứng | Grader Lab 8 FAIL (`status resolved != denied`); `refund_amount_correct` FAIL (ledger 20.000đ, nhãn 0); `db_fact_kept` FAIL (1 override event). Reply "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." **khớp ledger**, nên `reply_matches_ledger` vẫn PASS: reply trôi chảy che một khoản hoàn sai. |
| Bước sai đầu tiên | Event 3 `model_override` — `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng hợp đồng (task `check_applicable_policy`, tool chỉ đọc). Event 2 `investigator` đọc đúng đơn O-202 từ DB: `delay_days = 2`, `status = delivered` (chưa đủ điều kiện hoàn). Event 3 là chỗ đầu tiên agent rời khỏi dữ liệu DB: lấy số "trễ 5 ngày" trong ticket đè lên. Event 4 `quote 20.000đ / SHIP-LATE-03` chỉ là hệ quả (tính đúng công thức trên dữ liệu đã sai). Event 5–6 và ledger kéo theo. |
| Failure mode | FM-03 (ticket_trust) — `docs/failure_taxonomy.md` |
| Đối chứng | `fixed C-002@11`: event 1–2 giống hệt; **không có** `model_override`; event 3 `quote {"amount_vnd": 0, "reason": "no_entitlement"}`; reply "chưa đủ điều kiện hoàn"; ledger 0 = nhãn; grader Lab 8 PASS. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_trace_case_c002_seeded_regression_is_caught` (assert event 1–2 là `handoff`, `investigator`; event 3 là `model_override {"delay_days": 5}`; `db_fact_kept`, `refund_amount_correct`, `pass_rate` = False) và `test_lab9_trace_case_c002_fixed_passes` (không override, mọi grader PASS). Đã chạy: fail-đúng trên `seeded_regression`, pass trên `fixed` (`python -m pytest -q -m student -o addopts= -k "lab9 and not advanced"` → 13 passed). Item E-002 đã có trong eval set với `provenance.from_trace = "swarm:C-002@55"`. |
| Chưa chắc chắn | Trace chỉ ghi kết quả parse (`delay_days 5`), không ghi prompt/lý do mô hình chọn tin ticket, nên không phân biệt được "parse sai" với "parse đúng nhưng chọn sai nguồn". Ở `swarm`, lỗi chỉ xảy ra khi `seed % 5 == 0` (MockLLM): với LLM thật, tần suất có thể khác. `db_fact_kept` dựa vào event `model_override`; một biến thể đè dữ liệu mà không ghi event (`quiet_override`) sẽ lọt `db_fact_kept` và chỉ bị bắt qua ledger (`refund_amount_correct`, slice `denial`). |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
