# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** XYZ  
**Thành viên:**

| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| `[TÊN_1]` | Ingestion / Raw Owner | `[EMAIL]` |
| `[TÊN_2]` | Cleaning & Quality Owner | `[EMAIL]` |
| `[TÊN_3]` | Embed & Idempotency Owner | `[EMAIL]` |
| `[TÊN_4]` | Monitoring / Docs Owner | `[EMAIL]` |

**Ngày nộp:** 2026-04-15  
**Repo:** `[REPO_URL]`

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

| Rule / Expectation | Trước (inject) | Sau (clean) | Chứng cứ |
|---------------------|----------------|-------------|----------|
| `refund_no_stale_14d_window` | FAIL (chunk chứa "14 ngày") | OK (violations=0) | `run_inject-bad.log`: expectation FAIL, `after_inject_bad.csv`: hits_forbidden=yes |
| `hr_leave_no_stale_10d_annual` | OK (không bắt "15 ngày") | OK | `after_inject_leave.csv`: hits_forbidden=yes (phát hiện qua eval, không qua expectation) |
| Eval `q_refund_window` hits_forbidden | yes | no | `after_inject_bad.csv` vs `after_clean.csv` |
| Eval `q_leave_version` contains_expected | no | yes | `after_inject_leave.csv` vs `after_clean_leave.csv` |

**Ví dụ expectation fail:**

Khi chạy `--no-refund-fix`, expectation `refund_no_stale_14d_window` báo FAIL (halt). Pipeline in `PIPELINE_HALT` và exit code 2. Để demo inject Sprint 3, nhóm thêm `--skip-validate` để bypass halt — dữ liệu bẩn được embed vào ChromaDB, eval cho thấy retrieval trả kết quả sai.

---

## 3. Before / after ảnh hưởng retrieval

### Kịch bản inject 1: Refund window (`q_refund_window`)

Chạy `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`. Flag `--no-refund-fix` tắt cleaning rule sửa cửa sổ refund. Kết quả: chunk `policy_refund_v4` vẫn chứa "14 ngày làm việc" (dữ liệu cũ từ policy-v3). Eval cho `hits_forbidden=yes` — retrieval trả chunk đúng doc_id nhưng sai nội dung. Sau khi chạy pipeline chuẩn (không có flag), chunk được sửa về "7 ngày", eval trở lại `hits_forbidden=no`.

### Kịch bản inject 2: Leave policy (`q_leave_version`) — Merit

Sửa trực tiếp CSV: replace "12 ngày phép năm" → "15 ngày phép năm", lưu thành `policy_export_dirty_leave_inject.csv`. Chạy pipeline với `--raw` trỏ file inject + `--skip-validate`. Eval cho `contains_expected=no` (không chứa "12 ngày") + `hits_forbidden=yes` (chứa "15 ngày"). Chạy lại pipeline với CSV gốc → eval trở về `contains_expected=yes`, `hits_forbidden=no`.

**Kết quả định lượng:**

| Câu hỏi | Metric | Inject | Clean |
|---------|--------|--------|-------|
| q_refund_window | hits_forbidden | yes | no |
| q_leave_version | contains_expected | no | yes |
| q_leave_version | hits_forbidden | yes | no |

File eval: `artifacts/eval/after_inject_bad.csv`, `after_clean.csv`, `after_inject_leave.csv`, `after_clean_leave.csv`.

---

## 4. Freshness & monitoring

SLA được chọn: **24 giờ** (mặc định trong `.env`, override qua `FRESHNESS_SLA_HOURS`). Manifest ghi `latest_exported_at` từ cột `exported_at` của cleaned data. Freshness check so sánh khoảng cách giữa `latest_exported_at` và thời điểm chạy pipeline. Với data mẫu (`exported_at: 2026-04-10T08:00:00`), kết quả luôn là FAIL (`age_hours: ~120h`, vượt xa SLA 24h). Trong production, `exported_at` sẽ được cập nhật tự động từ DB/API nguồn. Ba mức: PASS (≤ SLA), WARN (> SLA nhưng < 2×SLA), FAIL (≥ 2×SLA). Chi tiết xử lý từng mức xem `docs/runbook.md`.

---

## 5. Liên hệ Day 09

Dữ liệu sau embed phục vụ lại multi-agent Day 09 qua cùng ChromaDB collection `day09_docs`. Agent Day 09 query collection này và nhận được dữ liệu đã được clean, validate bởi pipeline Day 10. Không tách collection vì mục đích là làm mới corpus cho cùng hệ thống RAG. Điểm cần chú ý: embedding backend phải nhất quán giữa Day 10 pipeline (index) và Day 09 agent (query).

---

## 6. Rủi ro còn lại & việc chưa làm

- Expectation `hr_leave_no_stale_10d_annual` không bắt được inject "15 ngày" — cần chuyển sang allowlist thay vì blocklist.
- Chưa có alert tự động khi freshness FAIL — cần tích hợp Slack/email notification.
- Eval chỉ dùng keyword matching — chưa có LLM judge đánh giá chất lượng câu trả lời end-to-end.
- Pipeline chưa hỗ trợ batch ingest nhiều CSV hoặc incremental update.
- Chưa có locking mechanism cho concurrent pipeline runs — last-write-wins có thể gây mất dữ liệu.
