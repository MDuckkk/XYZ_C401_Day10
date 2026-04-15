# Kiến trúc pipeline — Lab Day 10

**Nhóm:** XYZ  
**Cập nhật:** 2026-04-15

---

## 1. Sơ đồ luồng (bắt buộc có 1 diagram: Mermaid / ASCII)

```
data/raw/policy_export_dirty.csv
  -> ingest bằng csv.DictReader
  -> clean / quarantine trong transform/cleaning_rules.py
  -> validate trong quality/expectations.py
  -> publish cleaned CSV + manifest + log
  -> embed Chroma collection `day10_kb`
  -> serving cho retrieval / agent của Day 08-09

freshness đo ở boundary publish từ manifest.latest_exported_at
run_id xuất hiện ở log, manifest và metadata của vector
quarantine ghi ra artifacts/quarantine/quarantine_<run_id>.csv
```

Sprint 2 dùng một pipeline tuyến tính, nhưng đã có đủ 3 boundary quan trọng để debug:
- boundary ingest: đọc raw CSV và log `raw_records`
- boundary clean/validate: sinh `cleaned_csv`, `quarantine_csv`, `cleaning_stat[...]`, expectation results
- boundary publish/embed: upsert vào Chroma, prune vector cũ, ghi manifest và chạy freshness check

---

## 2. Ranh giới trách nhiệm

| Thành phần | Input | Output | Owner nhóm |
|------------|-------|--------|--------------|
| Ingest | `data/raw/policy_export_dirty.csv` | `raw_records`, `run_id`, log đầu vào | Bùi Minh Đức |
| Transform | Raw rows | `cleaned_<run_id>.csv`, `quarantine_<run_id>.csv` | Trần Thanh Nguyên |
| Quality | Cleaned rows | expectation results, halt/warn decision | Trần Thanh Nguyên |
| Embed | Cleaned CSV | Chroma collection `day10_kb`, metadata `run_id` | XYZ team |
| Monitor | Manifest sau publish | `freshness_check`, `latest_exported_at` | XYZ team |

---

## 3. Idempotency & rerun

Sprint 2 dùng `chunk_id` ổn định tạo từ `doc_id + chunk_text + seq` trong [transform/cleaning_rules.py](/d:/AI_Vin/Lab/assignments/day10/lab/transform/cleaning_rules.py:34).  
Ở bước embed, pipeline:
- lấy toàn bộ `chunk_id` của cleaned CSV
- prune các id không còn tồn tại trong cleaned snapshot
- `upsert` lại theo `chunk_id`

Kết quả rerun:
- `run_id=sprint2a`: `embed_prune_removed=3`, `embed_upsert count=6`
- `run_id=sprint2b`: `embed_upsert count=6`
- sau rerun, collection vẫn có đúng `6` vector, không duplicate

Điều này đáp ứng yêu cầu idempotent publish của Sprint 2.

---

## 4. Liên hệ Day 09

Pipeline này làm lớp dữ liệu trung gian trước khi retriever của Day 09 đọc index.  
`data/docs/*.txt` vẫn là canonical source, còn `data/raw/policy_export_dirty.csv` đóng vai trò export bẩn cần clean trước khi publish lại vào Chroma. Collection `day10_kb` được tách riêng để kiểm tra pipeline mà không làm bẩn collection của Day 09.

---

## 5. Rủi ro đã biết

- `freshness_check=FAIL` là hợp lý trên dữ liệu mẫu vì `exported_at` cũ hơn SLA 24 giờ
- Embed persistent trên máy lab có thể cần chạy ngoài sandbox vì Chroma/SQLite dễ gặp `disk I/O error` trong môi trường hạn chế
- Một số rule Sprint 2 hiện thiên về chuẩn hoá wording; nếu muốn chắc điểm hơn nữa có thể bổ sung thêm rule làm thay đổi quarantine hoặc expectation trên inject scenario
