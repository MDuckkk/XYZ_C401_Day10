# Quality report — Lab Day 10 (nhóm)

**run_id:** `clean-leave` (chuẩn) / `inject-bad` + `inject-leave` (inject)  
**Ngày:** 2026-04-15

---

## 1. Tóm tắt số liệu

| Chỉ số | Inject (bad) | Clean | Ghi chú |
|--------|-------------|-------|---------|
| raw_records | 10 | 10 | Cùng nguồn CSV, inject chỉ sửa nội dung chunk |
| cleaned_records | 6 | 6 | Số lượng không đổi — lỗi nằm ở nội dung, không phải format |
| quarantine_records | 4 | 4 | Các row bị loại do thiếu doc_id / chunk_text rỗng |
| Expectation halt? | Có (bị bypass bởi `--skip-validate`) | Không | `--no-refund-fix` → expectation `refund_no_stale_14d_window` FAIL nhưng pipeline vẫn tiếp tục embed |

---

## 2. Before / after retrieval (bắt buộc)

> File eval: `artifacts/eval/after_inject_bad.csv` và `artifacts/eval/after_clean.csv`

### Câu hỏi then chốt: refund window (`q_refund_window`)

**Trước (inject-bad, `--no-refund-fix --skip-validate`):**

| Cột | Giá trị |
|-----|---------|
| top1_doc_id | policy_refund_v4 |
| top1_preview | Yêu cầu hoàn tiền được chấp nhận trong vòng **14 ngày** làm việc kể từ xác nhận đơn (ghi chú: bản sync cũ policy-v3 — lỗi migration). |
| contains_expected | yes |
| hits_forbidden | **yes** |

**Sau (clean):**

| Cột | Giá trị |
|-----|---------|
| top1_doc_id | policy_refund_v4 |
| top1_preview | Yêu cầu được gửi trong vòng **7 ngày** làm việc kể từ thời điểm xác nhận đơn hàng. |
| contains_expected | yes |
| hits_forbidden | **no** |

**Phân tích:** Khi không áp dụng refund fix, chunk vẫn chứa dữ liệu cũ từ policy-v3 (14 ngày thay vì 7 ngày). Retrieval trả về chunk đúng (`policy_refund_v4`) nhưng nội dung sai — đây là dạng lỗi nguy hiểm nhất vì chatbot sẽ trả lời sai mà vẫn tự tin, người dùng không có cách nhận biết.

---

### Merit: versioning HR — `q_leave_version`

> File eval: `artifacts/eval/after_inject_leave.csv` và `artifacts/eval/after_clean_leave.csv`

**Trước (inject-leave, sửa CSV 12→15 ngày phép):**

| Cột | Giá trị |
|-----|---------|
| top1_doc_id | hr_leave_policy |
| top1_preview | Nhân viên dưới 3 năm kinh nghiệm được **15 ngày** phép năm theo chính sách 2026. |
| contains_expected | **no** (không chứa "12 ngày") |
| hits_forbidden | **yes** (chứa "15 ngày") |
| top1_doc_expected | yes |

**Sau (clean-leave):**

| Cột | Giá trị |
|-----|---------|
| top1_doc_id | hr_leave_policy |
| top1_preview | Nhân viên dưới 3 năm kinh nghiệm được **12 ngày** phép năm theo chính sách 2026. |
| contains_expected | **yes** |
| hits_forbidden | **no** |
| top1_doc_expected | yes |

**Phân tích:** Inject trực tiếp vào CSV raw (sửa "12 ngày" → "15 ngày") khiến retrieval trả đúng doc_id nhưng sai thông tin. Eval phát hiện qua cả hai metric: `contains_expected=no` và `hits_forbidden=yes`. Sau khi chạy lại pipeline với CSV gốc, cả hai metric trở về bình thường.

---

## 3. Freshness & monitor

Kết quả `freshness_check` khi chạy pipeline:

```
freshness_check=FAIL {"latest_exported_at": "2026-04-10T08:00:00", "age_hours": 120.226, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```

- **Status:** FAIL — dữ liệu export cuối cùng cách thời điểm chạy pipeline hơn 120 giờ (5 ngày), vượt SLA 24 giờ.
- **SLA được chọn:** 24 giờ (mặc định trong `.env`, có thể override qua `FRESHNESS_SLA_HOURS`).
- **Ý nghĩa:** Trong production, FAIL nghĩa là vector store đang phục vụ dữ liệu cũ — cần trigger re-export từ DB/API nguồn. Pipeline vẫn chạy thành công (PIPELINE_OK) vì freshness check là cảnh báo, không phải halt condition.
- **Các mức:** PASS (age ≤ SLA), WARN (age > SLA nhưng < 2×SLA), FAIL (age ≥ 2×SLA).

---

## 4. Corruption inject (Sprint 3)

### Kịch bản 1: Bỏ refund fix (`--no-refund-fix`)

- **Cách làm:** Chạy `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`. Flag `--no-refund-fix` tắt cleaning rule sửa cửa sổ refund 14→7 ngày. Flag `--skip-validate` bypass expectation halt để pipeline vẫn embed dữ liệu lỗi.
- **Phát hiện:** Expectation `refund_no_stale_14d_window` báo FAIL (severity: halt). Eval retrieval cho `hits_forbidden=yes` ở câu `q_refund_window`.

### Kịch bản 2: Sửa trực tiếp CSV (`q_leave_version`)

- **Cách làm:** Dùng PowerShell replace "12 ngày phép năm" → "15 ngày phép năm" trong CSV, lưu thành `policy_export_dirty_leave_inject.csv`. Chạy pipeline với `--raw` trỏ đến file inject + `--skip-validate`.
- **Phát hiện:** Eval retrieval cho `contains_expected=no` + `hits_forbidden=yes` ở câu `q_leave_version`. Expectation `hr_leave_no_stale_10d_annual` không bắt được lỗi này vì rule chỉ check "10 ngày" — đây là điểm cần cải thiện (thêm expectation check "15 ngày" hoặc tổng quát hơn).

---

## 5. Hạn chế & việc chưa làm

- Expectation suite chưa đủ phủ: `hr_leave_no_stale_10d_annual` chỉ bắt giá trị "10 ngày" cũ, không phát hiện "15 ngày" — cần rule tổng quát hơn (ví dụ: regex check giá trị phép năm phải nằm trong khoảng [12, 14]).
- Freshness check luôn FAIL với data mẫu vì `exported_at` cố định trong CSV — trong production cần cập nhật timestamp từ DB/API nguồn.
- Chưa có alert tự động khi freshness FAIL (chỉ log). Cần tích hợp notification (Slack/email) trong production.
- Eval chỉ dùng keyword matching (`must_contain_any`, `must_not_contain`) — chưa đánh giá chất lượng câu trả lời end-to-end qua LLM judge.
- SentenceTransformer không khả dụng trong môi trường hiện tại → fallback sang OpenAI embedding (`text-embedding-3-small`). Cần đảm bảo embedding backend nhất quán giữa index và query.