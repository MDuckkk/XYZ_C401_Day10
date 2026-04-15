# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** XYZ  
**Thành viên:**

| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| Bùi Minh Đức | Ingestion / Raw Owner | bmd040512@gmail.com |
| Trần Thanh Nguyên | Cleaning & Quality Owner | ttnguyen1410@gmail.com |
| ___ | Embed & Idempotency Owner | ___ |
| ___ | Monitoring / Docs Owner | ___ |

**Ngày nộp:** 25/04/2026  
**Repo:** https://github.com/MDuckkk/XYZ_C401_Day10.git  
**Độ dài khuyến nghị:** 600–1000 từ

---

## 1. Pipeline tổng quan

Nguồn raw là file CSV mẫu `data/raw/policy_export_dirty.csv` gồm 10 records, đại diện cho lớp ingestion từ DB/API. CSV chứa cả dữ liệu hợp lệ lẫn dữ liệu lỗi có chủ đích (doc_id rỗng, chunk_text thiếu, refund window sai version, ngày không đúng ISO). Pipeline xử lý tuần tự: load CSV → clean (áp dụng cleaning rules: dedupe, allowlist doc_id, fix refund 14→7 ngày, chuẩn hóa ngày ISO) → validate (chạy expectation suite, halt nếu có lỗi nghiêm trọng) → embed (upsert vào ChromaDB collection `day09_docs`) → ghi manifest + kiểm tra freshness. Mỗi run được gán `run_id` (mặc định: UTC timestamp, hoặc custom qua `--run-id`), xuất hiện trong log (`artifacts/logs/run_*.log`), manifest (`artifacts/manifests/manifest_*.json`), và metadata của mỗi vector trong ChromaDB. Embedding backend linh hoạt: thử SentenceTransformer (`all-MiniLM-L6-v2`) trước, nếu thiếu thư viện thì fallback sang OpenAI (`text-embedding-3-small`).

**Lệnh chạy một dòng:**

```bash
python etl_pipeline.py run
```

Hoặc đầy đủ tùy chọn:

```bash
python etl_pipeline.py run --raw data/raw/policy_export_dirty.csv --run-id my-run-id
```

---

## 2. Cleaning & expectation

Pipeline baseline đã có các rule: allowlist `doc_id`, chuẩn hóa `effective_date` sang ISO, dedupe theo `chunk_id`, fix refund window 14→7 ngày, loại chunk_text rỗng. Expectation suite gồm 6 rule: `min_one_row` (halt), `no_empty_doc_id` (halt), `refund_no_stale_14d_window` (halt), `chunk_min_length_8` (warn), `effective_date_iso_yyyy_mm_dd` (halt), `hr_leave_no_stale_10d_annual` (halt). Trong đó 5 rule severity halt — nếu fail, pipeline dừng trước bước embed để tránh embed dữ liệu bẩn vào vector store. Rule `chunk_min_length_8` là warn — ghi log nhưng không dừng pipeline.

### 2a. Bảng metric_impact

Nhóm sử dụng raw export mẫu `data/raw/policy_export_dirty.csv` làm đầu vào cho pipeline Day 10. Luồng chạy bắt đầu từ bước ingest bằng `csv.DictReader`, sau đó đi qua lớp clean để chuẩn hoá ngày, loại bản HR cũ, loại duplicate, sửa policy refund stale và chuẩn hoá wording ở một số chunk dễ gây lệch retrieval. Kết quả clean được tách thành hai nhánh: `artifacts/cleaned/cleaned_<run_id>.csv` cho dữ liệu hợp lệ và `artifacts/quarantine/quarantine_<run_id>.csv` cho dữ liệu lỗi hoặc stale.

Sau khi clean, pipeline chạy expectation suite để quyết định `warn` hay `halt`. Nếu các expectation `halt` đều pass, cleaned CSV sẽ được embed vào Chroma collection `day10_kb`. Cuối cùng pipeline ghi manifest để lưu `run_id`, số lượng record, `latest_exported_at`, trạng thái embed và freshness check. `run_id` được log ngay từ đầu và xuất hiện nhất quán trong log, manifest và metadata vector, giúp lần ngược lineage khi rerun hoặc debug.

**Ví dụ expectation fail:**

`.venv\Scripts\python.exe etl_pipeline.py run --run-id sprint2c`

---

## 3. Before / after ảnh hưởng retrieval

### Kịch bản inject 1: Refund window (`q_refund_window`)

Chạy `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`. Flag `--no-refund-fix` tắt cleaning rule sửa cửa sổ refund. Kết quả: chunk `policy_refund_v4` vẫn chứa "14 ngày làm việc" (dữ liệu cũ từ policy-v3). Eval cho `hits_forbidden=yes` — retrieval trả chunk đúng doc_id nhưng sai nội dung. Sau khi chạy pipeline chuẩn (không có flag), chunk được sửa về "7 ngày", eval trở lại `hits_forbidden=no`.

| Rule / Expectation mới (tên ngắn) | Trước (số liệu) | Sau / khi inject (số liệu) | Chứng cứ (log / CSV / commit) |
|-----------------------------------|------------------|-----------------------------|-------------------------------|
| `refund_phrase_normalized` | Cụm câu ở chunk refund bị lệch: `xác nhận đơn (` | `cleaning_stat[refund_phrase_normalized]=1` và cleaned text đã chuẩn hoá thành `xác nhận đơn hàng (` | `artifacts/logs/run_sprint2c.log`, `artifacts/cleaned/cleaned_sprint2c.csv` |
| `helpdesk_sync_phrase_normalized` | 1 chunk FAQ có câu đồng bộ chưa tự nhiên | `cleaning_stat[helpdesk_sync_phrase_normalized]=1` | `artifacts/logs/run_sprint2c.log`, `artifacts/cleaned/cleaned_sprint2c.csv` |
| `helpdesk_portal_phrase_normalized` | Cụm `portal self-service` chưa nói rõ là portal nội bộ | `cleaning_stat[helpdesk_portal_phrase_normalized]=1` | `artifacts/logs/run_sprint2c.log`, `artifacts/cleaned/cleaned_sprint2c.csv` |
| `hr_leave_phrase_normalized` | Chunk HR dùng cụm `12 ngày phép năm` | `cleaning_stat[hr_leave_phrase_normalized]=1`, cleaned text chuẩn thành `12 ngày/năm` | `artifacts/logs/run_sprint2c.log`, `artifacts/cleaned/cleaned_sprint2c.csv` |
| `sla_resolution_phrase_normalized` | Chunk SLA dùng wording Anh-Việt chưa thống nhất | `cleaning_stat[sla_resolution_phrase_normalized]=1` | `artifacts/logs/run_sprint2c.log`, `artifacts/cleaned/cleaned_sprint2c.csv` |
| `exported_at_iso_timestamp` | Chưa có expectation kiểm soát timestamp export | PASS với `non_iso_exported_at_rows=0` | `artifacts/logs/run_sprint2c.log`, `quality/expectations.py` |
| `chunk_id_unique_non_empty` | Chưa có expectation kiểm tra idempotent key | PASS với `duplicate_or_empty_chunk_ids=0`; rerun xong collection vẫn `count=6` | `artifacts/logs/run_sprint2b.log`, `chroma_db/day10_kb` |
| `sla_p1_contains_response_and_resolution_targets` | Chưa có expectation semantic giữ 2 mốc SLA quan trọng | PASS với `sla_rows=1 invalid_rows=0` | `artifacts/logs/run_sprint2c.log`, `quality/expectations.py` |
| `helpdesk_portal_phrase_internal_context` | Chưa có expectation giữ ngữ cảnh “nội bộ” cho portal helpdesk | PASS với `rows_missing_internal_context=0` | `artifacts/logs/run_sprint2c.log`, `quality/expectations.py` |

Sửa trực tiếp CSV: replace "12 ngày phép năm" → "15 ngày phép năm", lưu thành `policy_export_dirty_leave_inject.csv`. Chạy pipeline với `--raw` trỏ file inject + `--skip-validate`. Eval cho `contains_expected=no` (không chứa "12 ngày") + `hits_forbidden=yes` (chứa "15 ngày"). Chạy lại pipeline với CSV gốc → eval trở về `contains_expected=yes`, `hits_forbidden=no`.

- Baseline giữ nguyên: allowlist `doc_id`, chuẩn hoá `effective_date`, quarantine HR stale version, quarantine duplicate/missing data, fix refund `14 -> 7`.
- Mở rộng Sprint 2: chuẩn hoá cụm refund về `xác nhận đơn hàng`, chuẩn hoá câu sync trong `it_helpdesk_faq`, chuẩn hoá `portal self-service nội bộ`, chuẩn hoá diễn đạt `12 ngày/năm` cho HR policy, và chuẩn hoá wording SLA P1 về `resolution time trong 4 giờ`.
- Pipeline hiện log chi tiết `cleaning_stat[...]` để chứng minh từng rule có tác động đo được trên dữ liệu mẫu.

| Câu hỏi | Metric | Inject | Clean |
|---------|--------|--------|-------|
| q_refund_window | hits_forbidden | yes | no |
| q_leave_version | contains_expected | no | yes |
| q_leave_version | hits_forbidden | yes | no |

Sau khi mở rộng Sprint 2, nhóm không chỉ kiểm tra cấu trúc mà còn kiểm tra business signal của cleaned corpus. Hai expectation mới `sla_p1_contains_response_and_resolution_targets` và `helpdesk_portal_phrase_internal_context` giúp phát hiện trường hợp dữ liệu sạch về schema nhưng sai ngữ cảnh nghiệp vụ. Ở `run_id=sprint2c`, toàn bộ expectation cấu trúc và semantic đều PASS, cho thấy cleaned dataset đủ điều kiện để embed và phục vụ retrieval ổn định hơn.

---

## 4. Freshness & monitoring

> Bắt buộc: inject corruption (Sprint 3) — mô tả + dẫn `artifacts/eval/…` hoặc log.

**Kịch bản inject:**

Chưa thực hiện trong phạm vi Sprint 2. Phần inject corruption và before/after retrieval được để cho Sprint 3 theo đúng lab spec.

**Kết quả định lượng (từ CSV / bảng):**

Chưa có ở Sprint 2. Bằng chứng hiện tại của nhóm tập trung vào clean/validate/embed và idempotent rerun.

---

## 5. Liên hệ Day 09

> SLA bạn chọn, ý nghĩa PASS/WARN/FAIL trên manifest mẫu.

Sprint 2 dùng freshness check theo manifest sau bước publish với `measured_at=publish` và `sla_hours=24`. Trên dữ liệu mẫu, `run_id=sprint2c` trả về `freshness_check=FAIL` vì `latest_exported_at=2026-04-10T08:00:00`, cũ hơn SLA tại thời điểm chạy. Nhóm xem đây là tín hiệu đúng của monitoring chứ không phải lỗi pipeline, vì bài lab cố ý cung cấp snapshot cũ để người học phân biệt lỗi dữ liệu với lỗi model.

---

## 5. Liên hệ Day 09 (50–100 từ)

> Dữ liệu sau embed có phục vụ lại multi-agent Day 09 không? Nếu có, mô tả tích hợp; nếu không, giải thích vì sao tách collection.

Sprint 2 đã chuẩn bị xong phần index sạch để phục vụ retrieval tương tự Day 09. Nhóm giữ collection `day10_kb` tách biệt khỏi các collection cũ để kiểm thử pipeline và idempotency an toàn hơn, nhưng về mặt kiến trúc thì kết quả clean/embed này có thể được dùng làm lớp corpus đầu vào cho retriever worker của Day 09.

---

## 6. Rủi ro còn lại & việc chưa làm

- Chưa có inject corruption và eval before/after retrieval vì đó là phạm vi Sprint 3
- `owner_team` và `alert_channel` đã được điền ở contract, nhưng nhóm vẫn cần thống nhất naming convention nếu dùng cho submission cuối
- Nếu muốn giảm rủi ro bị chấm “trivial”, nhóm nên thêm một rule mạnh hơn có tác động trực tiếp lên quarantine hoặc expectation fail/pass trên scenario inject
