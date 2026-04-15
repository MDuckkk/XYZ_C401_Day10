# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Bùi Minh Đức  
**Vai trò:** Sprint 1 / Sprint 2 / Chạy grading  
**Ngày nộp:** 25/04/2026  
**Độ dài yêu cầu:** **400–650 từ**

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- `etl_pipeline.py`
- `transform/cleaning_rules.py`
- `quality/expectations.py`
- `contracts/data_contract.yaml`
- `artifacts/eval/grading_run.jsonl`

**Kết nối với thành viên khác:**

Tôi phụ trách phần Sprint 1 và Sprint 2 nên công việc của tôi là tạo đầu ra cleaned/quarantine ổn định để các phần Sprint 3 và Sprint 4 có thể dùng lại khi inject, eval retrieval, run freshness và viết runbook. Phần tôi làm là lớp dữ liệu nền cho các bước quan sát và báo cáo sau đó.

**Bằng chứng (commit / comment trong code):**

Bằng chứng rõ nhất là các run `sprint1` và `sprint2c`. Ở `artifacts/logs/run_sprint1.log` tôi có `raw_records=10`, `cleaned_records=6`, `quarantine_records=4`. Ở `artifacts/logs/run_sprint2c.log` tôi có thêm các `cleaning_stat[...]`, expectation mới và `embed_upsert count=6`.

---

## 2. Một quyết định kỹ thuật (100–150 từ)

Tôi chọn dùng `chunk_id` ổn định để publish vào vector store thay vì tạo ID ngẫu nhiên theo từng lần chạy. Cách làm này giúp pipeline idempotent: nếu rerun cùng một cleaned snapshot thì `upsert` sẽ ghi đè đúng chunk cũ, không sinh duplicate vector. Tôi kết hợp điều này với bước prune các ID không còn nằm trong cleaned snapshot hiện tại. Nhờ vậy collection luôn phản ánh đúng dữ liệu publish mới nhất. Ở `run_id=sprint2c`, log cho thấy `embed_prune_removed=2` và `embed_upsert count=6`, nghĩa là snapshot mới đã thay thế dữ liệu cũ mà không làm phình collection. Tôi cũng giữ phân biệt `warn` và `halt` trong expectation suite: lỗi ảnh hưởng nghiệp vụ như refund stale, `doc_id` rỗng, `chunk_id` không unique là `halt`, còn các tín hiệu semantic nhẹ hơn như wording/context là `warn`.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

Anomaly lớn nhất tôi gặp là pipeline chạy được đến bước clean/validate nhưng từng không embed được trong môi trường hạn chế ghi đĩa. Triệu chứng là bước publish dừng ở `chromadb.PersistentClient` dù cleaned dataset đã đúng. Tôi kiểm tra riêng và thấy cả `sqlite3` đơn giản cũng bị `disk I/O error`, nên xác định đây là lỗi môi trường chứ không phải lỗi ETL. Sau đó tôi chạy lại pipeline ngoài sandbox và xác nhận embed hoạt động bình thường. Một anomaly khác là freshness luôn FAIL. Sau khi đọc manifest và raw CSV, tôi xác nhận nguyên nhân đến từ `latest_exported_at=2026-04-10T08:00:00`, tức dữ liệu mẫu cố ý cũ hơn SLA 24 giờ. Vì vậy tôi giữ freshness như tín hiệu monitoring thay vì biến nó thành điều kiện halt.

---

## 4. Bằng chứng trước / sau (80–120 từ)

Với phần tôi phụ trách, tôi dùng log Sprint 1 và Sprint 2 làm evidence. Ở `run_id=sprint1`, log ghi:

- `raw_records=10`
- `cleaned_records=6`
- `quarantine_records=4`

Ở `run_id=sprint2c`, log ghi:

- `cleaning_stat[refund_phrase_normalized]=1`
- `cleaning_stat[helpdesk_portal_phrase_normalized]=1`
- `expectation[chunk_id_unique_non_empty] OK (halt)`
- `expectation[sla_p1_contains_response_and_resolution_targets] OK (halt)`

Sau đó tôi chạy grading bằng `grading_run.py` và file `artifacts/eval/grading_run.jsonl` cho thấy `gq_d10_01`, `gq_d10_02`, `gq_d10_03` đều `contains_expected=true`, còn `gq_d10_03` có thêm `top1_doc_matches=true`.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ, tôi sẽ tổng quát hóa expectation cho leave policy. Hiện `hr_leave_no_stale_10d_annual` chỉ chặn giá trị cũ `10 ngày`, nhưng chưa bắt được mọi biến thể sai như `15 ngày`. Tôi muốn thay bằng expectation canonical mạnh hơn: nội dung leave policy 2026 cho nhân viên dưới 3 năm chỉ được phép ra `12 ngày` hoặc `12 ngày/năm`.
