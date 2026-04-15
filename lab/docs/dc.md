# Data contract — Lab Day 10

> Bắt đầu từ `contracts/data_contract.yaml` — mở rộng và đồng bộ file này.

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `policy_export_dirty.csv` | Load CSV trực tiếp (`load_raw_csv`) | File không tồn tại, encoding sai, cột thiếu | Pipeline exit code 1, log `ERROR: raw file not found` |
| Day 09 `data/docs/*.md` | Corpus tĩnh (không qua pipeline Day 10) | File bị xóa hoặc format hỏng | Không có alert tự động — phát hiện qua eval retrieval |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| chunk_id | string | Có | Format `{doc_id}_chunk_{n}`, dùng làm key upsert trong ChromaDB |
| doc_id | string | Có | ID tài liệu gốc (vd: `policy_refund_v4`, `hr_leave_policy`). Không được rỗng — expectation `no_empty_doc_id` (halt) |
| chunk_text | string | Có | Nội dung chunk đã clean. Tối thiểu 8 ký tự — expectation `chunk_min_length_8` (warn) |
| effective_date | date (ISO) | Có | Format `YYYY-MM-DD`. Expectation `effective_date_iso_yyyy_mm_dd` (halt) kiểm tra |
| exported_at | datetime (ISO) | Có | Thời điểm export từ nguồn. Dùng cho freshness check |

**Metadata embed vào ChromaDB:**

| Field | Nguồn | Mục đích |
|-------|-------|----------|
| doc_id | Cột `doc_id` | Filter retrieval theo tài liệu |
| effective_date | Cột `effective_date` | Xác định version policy |
| run_id | Argument pipeline | Traceability — biết chunk được embed ở run nào |

---

## 3. Quy tắc quarantine vs drop

| Loại lỗi | Xử lý | Lý do |
|-----------|--------|-------|
| `doc_id` rỗng | Quarantine | Không thể xác định tài liệu gốc, nhưng có thể recover nếu biết nguồn |
| `chunk_text` rỗng hoặc < 8 ký tự | Quarantine | Chunk không có giá trị embed, nhưng giữ lại để audit |
| `effective_date` không đúng ISO | Quarantine | Có thể sửa thủ công (vd: `15/03/2026` → `2026-03-15`) |
| Duplicate `chunk_id` | Dedupe (giữ bản cuối) | Tự động trong cleaning, không cần quarantine |
| Refund window sai (14 ngày thay vì 7) | Sửa tự động nếu `--no-refund-fix` không được set | Rule `apply_refund_window_fix` trong `cleaning_rules.py` |

**Ai approve merge quarantine lại?** Trong lab: nhóm tự review file `artifacts/quarantine/*.csv` và quyết định. Trong production: data owner review + tạo PR merge vào cleaned.

---

## 4. Phiên bản & canonical

| Policy | Source of truth | Version hiện tại | Ghi chú |
|--------|----------------|------------------|---------|
| Refund window | `policy_refund_v4` | 7 ngày làm việc | v3 cũ (14 ngày) là lỗi migration — cleaning rule tự sửa |
| HR leave | `hr_leave_policy` | 12 ngày phép/năm (< 3 năm KN) | Theo chính sách 2026 |
| SLA P1 | `sla_p1_2026` | 15 phút first response, 4 giờ resolution | — |
| IT lockout | `it_helpdesk_faq` | 5 lần đăng nhập sai → khóa | — |

Khi có version mới của policy, cần cập nhật CSV raw export và chạy lại pipeline. Expectation suite sẽ bắt nếu dữ liệu cũ còn sót.
