# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** XYZ  
**Thành viên:**

| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| Bùi Minh Đức | Sprint 1 + Sprint 2 | bmd040512@gmail.com |
| Trần Thanh Nguyên | Sprint 3 + Sprint 4 | ttnguyen1410@gmail.com |

**Ngày nộp:** 25/04/2026  
**Repo:** https://github.com/MDuckkk/XYZ_C401_Day10.git

---

## 1. Pipeline tổng quan

Nhóm dùng `data/raw/policy_export_dirty.csv` làm raw export mô phỏng dữ liệu lấy từ DB/API. Pipeline chạy tuần tự theo các bước: ingest CSV bằng `csv.DictReader`, clean bằng `transform/cleaning_rules.py`, validate bằng `quality/expectations.py`, embed vào Chroma collection `day10_kb`, sau đó ghi manifest và chạy freshness check. Mỗi lần chạy đều gắn `run_id` và ghi nhất quán vào log, manifest và metadata của vector để hỗ trợ lineage/debug.

Lệnh chạy chuẩn:

```bash
python etl_pipeline.py run
```

Lệnh nhóm dùng cho run Sprint 2/Sprint 4:

```bash
.venv\Scripts\python.exe etl_pipeline.py run --run-id sprint2c
```

---

## 2. Cleaning & expectation

Baseline của nhóm giữ các rule cốt lõi: allowlist `doc_id`, chuẩn hoá `effective_date`, quarantine bản HR stale, quarantine duplicate/missing, fix refund `14 -> 7`. Sprint 2 mở rộng thêm rule chuẩn hoá wording cho refund/helpdesk/HR/SLA và thêm expectation semantic để dữ liệu sau clean không chỉ đúng schema mà còn đúng ngữ cảnh nghiệp vụ.

### 2a. Bảng metric_impact

| Rule / Expectation mới | Trước | Sau | Chứng cứ |
|------------------------|-------|-----|---------|
| `refund_phrase_normalized` | Chunk refund có cụm `xác nhận đơn (` | `cleaning_stat[refund_phrase_normalized]=1` và cleaned text thành `xác nhận đơn hàng (` | `artifacts/logs/run_sprint2c.log`, `artifacts/cleaned/cleaned_sprint2c.csv` |
| `helpdesk_sync_phrase_normalized` | Chunk FAQ có wording đồng bộ chưa tự nhiên | `cleaning_stat[helpdesk_sync_phrase_normalized]=1` | `artifacts/logs/run_sprint2c.log` |
| `helpdesk_portal_phrase_normalized` | Chunk FAQ chưa nói rõ portal là nội bộ | `cleaning_stat[helpdesk_portal_phrase_normalized]=1` | `artifacts/logs/run_sprint2c.log`, `artifacts/cleaned/cleaned_sprint2c.csv` |
| `hr_leave_phrase_normalized` | Chunk HR dùng cụm `12 ngày phép năm` | `cleaning_stat[hr_leave_phrase_normalized]=1`, cleaned text thành `12 ngày/năm` | `artifacts/logs/run_sprint2c.log`, `artifacts/cleaned/cleaned_sprint2c.csv` |
| `sla_resolution_phrase_normalized` | Chunk SLA dùng wording Anh-Việt chưa thống nhất | `cleaning_stat[sla_resolution_phrase_normalized]=1` | `artifacts/logs/run_sprint2c.log`, `artifacts/cleaned/cleaned_sprint2c.csv` |
| `exported_at_iso_timestamp` | Chưa có expectation timestamp export | PASS với `non_iso_exported_at_rows=0` | `artifacts/logs/run_sprint2c.log` |
| `chunk_id_unique_non_empty` | Chưa có expectation cho idempotent key | PASS với `duplicate_or_empty_chunk_ids=0` | `artifacts/logs/run_sprint2c.log` |
| `sla_p1_contains_response_and_resolution_targets` | Chưa có expectation semantic cho SLA P1 | PASS với `sla_rows=1 invalid_rows=0` | `artifacts/logs/run_sprint2c.log` |
| `helpdesk_portal_phrase_internal_context` | Chưa có expectation giữ ngữ cảnh “nội bộ” | PASS với `rows_missing_internal_context=0` | `artifacts/logs/run_sprint2c.log` |

---

## 3. Before / after ảnh hưởng retrieval

Sprint 3 của nhóm dùng hai kịch bản inject để chứng minh ảnh hưởng của data lỗi lên retrieval.

### Kịch bản 1: Refund window (`q_refund_window`)

- Inject: chạy `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`
- Eval file: `artifacts/eval/after_inject_bad.csv`
- Kết quả: `hits_forbidden=yes`, top preview vẫn chứa `14 ngày`

Sau khi chạy lại pipeline sạch:

- Eval file: `artifacts/eval/after_clean.csv`
- Kết quả: `hits_forbidden=no`, top preview quay về `7 ngày`

### Kịch bản 2: Leave version (`q_leave_version`)

- Inject: sửa trực tiếp CSV, thay `12 ngày phép năm` thành `15 ngày phép năm`, lưu bản inject riêng
- Eval file: `artifacts/eval/after_inject_leave.csv`
- Kết quả: `contains_expected=no`, `hits_forbidden=yes`

Sau khi quay về dữ liệu sạch:

- Eval file: `artifacts/eval/after_clean_leave.csv`
- Kết quả: `contains_expected=yes`, `hits_forbidden=no`

Tóm tắt định lượng:

| Câu hỏi | Metric | Inject | Clean |
|---------|--------|--------|-------|
| `q_refund_window` | `hits_forbidden` | yes | no |
| `q_leave_version` | `contains_expected` | no | yes |
| `q_leave_version` | `hits_forbidden` | yes | no |

Điểm nhóm rút ra là retrieval có thể trả đúng `doc_id` nhưng vẫn sai nội dung nghiệp vụ nếu chunk stale hoặc inject lỗi lọt qua pipeline. Đây là bằng chứng đúng tinh thần Day 10: lỗi nằm ở data layer trước khi nằm ở model.

---

## 4. Freshness & monitoring

Nhóm đo freshness ở boundary `publish` theo manifest sau khi embed. Với dữ liệu mẫu, freshness luôn FAIL vì `latest_exported_at=2026-04-10T08:00:00` cũ hơn SLA 24 giờ tại thời điểm chạy. Nhóm xem đây là tín hiệu monitoring đúng chứ không phải lỗi pipeline.

Ví dụ ở run sạch:

```text
freshness_check=FAIL {"latest_exported_at": "2026-04-10T08:00:00", "age_hours": 120.908, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```

PASS/WARN/FAIL được giải thích chi tiết trong `docs/runbook.md`. Trong production, FAIL phải kéo theo re-export từ nguồn và rerun pipeline; trong lab, FAIL được giữ để minh hoạ data snapshot cũ.

---

## 5. Liên hệ Day 09

Nhóm tách collection `day10_kb` để kiểm thử pipeline và idempotency an toàn hơn, không làm bẩn collection cũ. Tuy vậy, về mặt kiến trúc, output của Sprint 2–4 hoàn toàn có thể cấp ngược lại cho retriever worker của Day 09 vì cùng đi theo flow canonical source -> cleaned corpus -> vector index -> retrieval.

---

## 6. Rủi ro còn lại & việc chưa làm

- Chưa viết individual reports
- `hr_leave_no_stale_10d_annual` vẫn chưa tổng quát, chưa bắt được mọi biến thể sai như `15 ngày`
- Freshness hiện mới là log/manifest, chưa có alert tự động Slack/email
- Eval hiện vẫn dùng keyword-based retrieval, chưa có LLM-judge end-to-end
