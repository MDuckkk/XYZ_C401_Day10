# Báo cáo cá nhân — mẫu GV (reference)

**Họ và tên:** GV Reference  
**Vai trò:** Cleaning & Quality  
**Độ dài:** ~450 từ (mẫu)

---

## 1. Phụ trách

Tôi triển khai `transform/cleaning_rules.py` (rule 7–9) và `quality/expectations.py` (E7–E9). Kết nối với embed owner qua manifest `cleaned_csv` và log `cleaned_records`.

**Bằng chứng:** commit/file trong repo reference `day10-lab-reference-solution`.

---

## 2. Quyết định kỹ thuật

**Halt vs warn:** `exported_at` sai format → **quarantine + cleaning** (không để vào cleaned) thay vì warn, vì sai clock làm sai freshness downstream. Còn `exported_at` rỗng trên cleaned → **warn** (E9): vẫn cho publish nhưng log để backlog.

**Idempotency:** ủng hộ prune vector id không còn trong batch — tránh top-k còn “14 ngày” sau inject.

---

## 3. Sự cố / anomaly

Khi thử bỏ prune, `grading_run.jsonl` báo `hits_forbidden=true` dù cleaned đã sạch — nguyên nhân vector cũ. Fix: prune trong `etl_pipeline.py` sau khi so sánh `prev_ids` vs `ids`.

---

## 4. Before/after

**Log:** `expectation[refund_no_stale_14d_window] OK (halt)` sau run chuẩn; trước đó với `--no-refund-fix` expectation FAIL.

**CSV:** dòng `q_refund_window` có `hits_forbidden=no` trong `artifacts/eval/before_after_eval.csv`.

---

## 5. Cải tiến thêm 2 giờ

Đọc cutoff HR `2026-01-01` từ `contracts/data_contract.yaml` thay vì hard-code trong Python (hướng Distinction d).
