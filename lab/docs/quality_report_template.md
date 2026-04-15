# Quality report — Lab Day 10

**run_id:** `after_clean` / `inject-bad` / `inject-leave`  
**Ngày:** 15-04-2026

---

## 1. Tóm tắt số liệu

| Chỉ số | Inject (bad) | Clean | Ghi chú |
|--------|-------------|-------|---------|
| raw_records | 10 | 10 | Cùng nguồn CSV, inject chỉ sửa nội dung chunk |
| cleaned_records | 6 | 6 | Số lượng không đổi, lỗi nằm ở nội dung |
| quarantine_records | 4 | 4 | Các row lỗi schema/doc_id vẫn bị cô lập |
| Expectation halt? | Có | Không | `--no-refund-fix` làm `refund_no_stale_14d_window` fail |

---

## 2. Before / after retrieval

### Refund window — `q_refund_window`

File eval:
- `artifacts/eval/after_inject_bad.csv`
- `artifacts/eval/after_clean.csv`

Trước khi fix:
- `top1_doc_id=policy_refund_v4`
- `contains_expected=yes`
- `hits_forbidden=yes`
- top preview vẫn chứa `14 ngày`

Sau khi fix:
- `top1_doc_id=policy_refund_v4`
- `contains_expected=yes`
- `hits_forbidden=no`
- top preview quay về `7 ngày`

Ý nghĩa: retrieval trả đúng tài liệu nhưng sai nội dung nghiệp vụ nếu chunk stale lọt qua pipeline.

### Leave version — `q_leave_version`

File eval:
- `artifacts/eval/after_inject_leave.csv`
- `artifacts/eval/after_clean_leave.csv`

Trước khi fix:
- `top1_doc_id=hr_leave_policy`
- `contains_expected=no`
- `hits_forbidden=yes`
- top preview chứa `15 ngày`

Sau khi fix:
- `top1_doc_id=hr_leave_policy`
- `contains_expected=yes`
- `hits_forbidden=no`
- top preview quay về `12 ngày`

Ý nghĩa: inject trực tiếp vào CSV raw đủ để làm retrieval sai dù doc_id vẫn đúng.

---

## 3. Freshness & monitor

Ví dụ ở run sạch:

```text
freshness_check=FAIL {"latest_exported_at": "2026-04-10T08:00:00", "age_hours": 120.908, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```

- Status: `FAIL`
- SLA đang dùng: `24` giờ
- Diễn giải: data snapshot cũ hơn SLA, nhưng đây là hành vi đúng với dữ liệu mẫu của lab

Trong production, FAIL phải kéo theo re-export từ nguồn và rerun pipeline.

---

## 4. Corruption inject

### Kịch bản 1: `--no-refund-fix`

Lệnh:

```bash
python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
```

Phát hiện:
- expectation `refund_no_stale_14d_window` fail
- eval `q_refund_window` cho `hits_forbidden=yes`

### Kịch bản 2: sửa trực tiếp leave policy trong raw CSV

Cách làm:
- thay `12 ngày phép năm` thành `15 ngày phép năm`
- chạy pipeline với file inject qua `--raw`

Phát hiện:
- eval `q_leave_version` cho `contains_expected=no`
- eval `q_leave_version` cho `hits_forbidden=yes`

---

## 5. Hạn chế còn lại

- Expectation leave policy vẫn chưa đủ tổng quát để bắt mọi biến thể sai
- Freshness hiện mới dừng ở log/manifest, chưa có alert tự động
- Eval hiện là keyword-based, chưa phải đánh giá end-to-end bằng LLM judge
