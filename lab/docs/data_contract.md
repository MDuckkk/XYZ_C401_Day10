# Data contract — Lab Day 10

> Bắt đầu từ `contracts/data_contract.yaml` — mở rộng và đồng bộ file này.

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `data/raw/policy_export_dirty.csv` | Batch CSV export từ hệ nguồn KB/policy, đọc bằng `csv.DictReader` trong `etl_pipeline.py` | Duplicate chunk, thiếu `effective_date`, `doc_id` lạ, ngày không phải ISO | `raw_records`, `cleaned_records`, `quarantine_records`, alert khi `quarantine_records > 0` |
| `data/docs/*.txt` | Canonical reference cho policy/helpdesk docs, dùng để xác định source of truth khi clean và đối chiếu version | Nội dung canonical đổi nhưng export chưa sync, dẫn tới stale chunk trong cleaned/index | `latest_exported_at`, `freshness_check`, alert khi `freshness_check=FAIL` |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| chunk_id | string | Có | ID ổn định sinh từ `doc_id + chunk_text + seq`, dùng để upsert idempotent |
| doc_id | string | Có | Chỉ nhận các giá trị trong allowlist: `policy_refund_v4`, `sla_p1_2026`, `it_helpdesk_faq`, `hr_leave_policy` |
| chunk_text | string | Có | Nội dung chunk sau clean; không được rỗng, không giữ duplicate text |
| effective_date | date | Có | Chuẩn hoá về `YYYY-MM-DD`; giá trị không parse được sẽ vào quarantine |
| exported_at | datetime | Có | Thời điểm export từ nguồn raw, dùng cho freshness check trong manifest |

---

## 3. Quy tắc quarantine vs drop

Record bị flag sẽ được ghi vào `artifacts/quarantine/quarantine_<run_id>.csv`, không bị xoá im lặng.

Các rule clean/quarantine đang áp dụng trong Sprint 2:
- `doc_id_allowlist_only`: chỉ cho phép `policy_refund_v4`, `sla_p1_2026`, `it_helpdesk_faq`, `hr_leave_policy`
- `effective_date_parseable`: ngày hiệu lực phải parse được về `YYYY-MM-DD`
- `hr_leave_min_effective_date`: loại bản HR cũ trước `2026-01-01`
- `no_empty_chunk_text`: chunk rỗng bị quarantine
- `no_duplicate_chunk_text`: chunk trùng sau normalize whitespace/case bị quarantine
- `exported_at_iso_timestamp`: timestamp export phải đúng định dạng `YYYY-MM-DDTHH:MM:SS`
- `no_stale_refund_window`: nội dung refund `14 ngày làm việc` sẽ được sửa về `7 ngày làm việc`
- `refund_phrase_normalized`: chuẩn hoá wording refund về `xác nhận đơn hàng`
- `helpdesk_sync_phrase_normalized`: chuẩn hoá câu đồng bộ trong FAQ helpdesk
- `helpdesk_portal_phrase_normalized`: chuẩn hoá `portal self-service` thành `portal self-service nội bộ`
- `hr_leave_phrase_normalized`: chuẩn hoá annual leave về `12 ngày/năm`
- `sla_resolution_phrase_normalized`: chuẩn hoá wording SLA P1 về `resolution time trong 4 giờ`

Expectation suite của Sprint 2:
- `min_one_row` (`halt`)
- `no_empty_doc_id` (`halt`)
- `refund_no_stale_14d_window` (`halt`)
- `chunk_min_length_8` (`warn`)
- `effective_date_iso_yyyy_mm_dd` (`halt`)
- `hr_leave_no_stale_10d_annual` (`halt`)
- `exported_at_iso_timestamp` (`halt`)
- `chunk_id_unique_non_empty` (`halt`)
- `sla_p1_contains_response_and_resolution_targets` (`halt`)
- `helpdesk_portal_phrase_internal_context` (`warn`)

---

## 4. Phiên bản & canonical

Source of truth cho policy refund là `data/docs/policy_refund_v4.txt` với `doc_id=policy_refund_v4`.

Quy ước version baseline hiện tại:
- Refund window hợp lệ: `7 ngày làm việc`
- HR leave policy hợp lệ: chỉ nhận bản có `effective_date >= 2026-01-01`
- Freshness SLA mặc định đo ở boundary `publish`, `sla_hours=24` theo `contracts/data_contract.yaml`
- `owner_team`: `XYZ Data/AI Team`
- `alert_channel`: `xyz-day10-alerts`
