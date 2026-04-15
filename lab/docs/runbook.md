# Runbook — Lab Day 10 (incident tối giản)

**Nhóm:** XYZ — Lớp C401  
**Cập nhật:** 2026-04-15

---

## Freshness check — PASS / WARN / FAIL

Chạy kiểm tra:

```bash
python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_clean-leave.json
```

### Các mức freshness

| Status | Điều kiện | Ý nghĩa | Hành động |
|--------|-----------|----------|-----------|
| PASS | `age_hours` ≤ `sla_hours` (24h) | Dữ liệu trong vector store còn mới, nằm trong SLA | Không cần làm gì |
| WARN | `sla_hours` < `age_hours` < `2 × sla_hours` | Dữ liệu bắt đầu cũ, sắp vượt ngưỡng | Lên lịch re-export từ nguồn, chạy lại pipeline trong vài giờ tới |
| FAIL | `age_hours` ≥ `2 × sla_hours` | Dữ liệu quá cũ, vector store đang phục vụ thông tin có thể outdated | Re-export ngay từ DB/API nguồn, chạy lại pipeline, cân nhắc tạm banner "data stale" cho user |

### Ví dụ thực tế từ lab

```
freshness_check=FAIL {
  "latest_exported_at": "2026-04-10T08:00:00",
  "age_hours": 120.226,
  "sla_hours": 24.0,
  "reason": "freshness_sla_exceeded"
}
```

Giải thích: Dữ liệu export cuối cùng là ngày 10/04, cách thời điểm chạy hơn 120 giờ (5 ngày), vượt xa SLA 24 giờ → FAIL. Trong lab với CSV mẫu cố định, FAIL là bình thường. Trong production, cần cơ chế tự động re-export.

### Cấu hình SLA

Thay đổi SLA qua biến môi trường trong `.env`:

```
FRESHNESS_SLA_HOURS=24
```

---

## Symptom

User hoặc agent trả lời sai thông tin policy. Ví dụ cụ thể:
- Chatbot trả lời "khách hàng có **14 ngày** để yêu cầu hoàn tiền" thay vì 7 ngày (đúng).
- Chatbot trả lời "nhân viên được **15 ngày** phép năm" thay vì 12 ngày (đúng).

Đặc điểm nguy hiểm: retrieval vẫn trả đúng `doc_id`, chunk vẫn liên quan — chỉ sai nội dung bên trong. User không có cách nhận biết.

---

## Detection

| Metric / check | Công cụ | Phát hiện gì |
|----------------|---------|-------------|
| Expectation `refund_no_stale_14d_window` | `quality/expectations.py` | Chunk refund chứa "14 ngày" (dữ liệu cũ) |
| Expectation `hr_leave_no_stale_10d_annual` | `quality/expectations.py` | Chunk leave chứa "10 ngày" (dữ liệu cũ) |
| Eval `hits_forbidden` | `eval_retrieval.py` | Top-k chunk chứa keyword bị cấm |
| Eval `contains_expected` | `eval_retrieval.py` | Top-k chunk không chứa keyword kỳ vọng |
| Freshness FAIL | `monitoring/freshness_check.py` | Dữ liệu quá cũ so với SLA |

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Kiểm tra manifest mới nhất: `cat artifacts/manifests/manifest_*.json` | Xem `run_id`, `no_refund_fix`, `skipped_validate`, `freshness` status |
| 2 | Kiểm tra log: `cat artifacts/logs/run_*.log` | Tìm dòng `expectation[...] FAIL` hoặc `PIPELINE_HALT` |
| 3 | Mở quarantine: `cat artifacts/quarantine/quarantine_*.csv` | Xem có row nào bị loại không đúng, hoặc row lỗi lọt qua |
| 4 | Chạy eval: `python eval_retrieval.py --out artifacts/eval/debug.csv` | Kiểm tra `contains_expected` và `hits_forbidden` cho từng câu hỏi |
| 5 | So sánh với eval chuẩn: diff `after_clean.csv` với `debug.csv` | Xác định câu hỏi nào bị regression |

---

## Mitigation

| Tình huống | Hành động |
|-----------|-----------|
| Dữ liệu bẩn đã embed vào ChromaDB | Chạy lại pipeline với CSV đúng: `python etl_pipeline.py run --run-id hotfix-{timestamp}`. Upsert sẽ ghi đè chunk sai, prune sẽ xóa chunk thừa |
| Expectation FAIL nhưng cần embed gấp | **Không dùng `--skip-validate` trong production.** Sửa data trước, chạy lại pipeline |
| Freshness FAIL | Re-export từ DB/API nguồn, cập nhật CSV, chạy lại pipeline |
| Embedding backend mismatch | Kiểm tra env `ST_MODEL` / `OPENAI_EMBEDDING_MODEL`. Đảm bảo eval dùng cùng backend với pipeline. Nếu đã mismatch → chạy lại pipeline để re-embed toàn bộ |

---

## Prevention

| Biện pháp | Chi tiết |
|-----------|----------|
| Không bypass validate | Tuyệt đối không dùng `--skip-validate` trong production. Flag này chỉ phục vụ demo inject Sprint 3 |
| Thêm expectation | Bổ sung rule kiểm tra giá trị cụ thể (vd: phép năm phải trong khoảng [12, 14]) thay vì chỉ check giá trị cũ |
| Alert tự động | Tích hợp Slack/email notification khi freshness WARN hoặc FAIL |
| Scheduled pipeline | Cron job chạy pipeline định kỳ (vd: mỗi 12 giờ) để đảm bảo dữ liệu luôn fresh |
| Peer review 3 câu hỏi | Xem phần dưới |

---

## Peer review — 3 câu hỏi (Phần E)

**Q1: Nếu freshness check trả FAIL, pipeline có nên dừng embed không? Tại sao nhóm chọn để nó là warning thay vì halt?**

> Freshness FAIL nghĩa là dữ liệu cũ, nhưng dữ liệu cũ vẫn tốt hơn không có dữ liệu. Nếu halt, vector store sẽ không được cập nhật — user vẫn thấy data cũ hơn nữa. Thay vào đó, pipeline vẫn embed và ghi cảnh báo vào manifest để monitoring system xử lý (alert, re-export).

**Q2: Upsert theo `chunk_id` có rủi ro gì khi 2 run chạy đồng thời (concurrent)?**

> ChromaDB dùng last-write-wins — nếu 2 run upsert cùng chunk_id, run nào ghi sau sẽ thắng. Trong lab đây không phải vấn đề (chạy tuần tự). Trong production cần locking mechanism hoặc queue để serialize pipeline runs.

**Q3: Tại sao expectation `hr_leave_no_stale_10d_annual` không bắt được inject "15 ngày"? Nhóm sẽ sửa thế nào?**

> Rule hiện tại chỉ check chuỗi "10 ngày" (giá trị cũ cụ thể). Inject "15 ngày" là giá trị mới không nằm trong blocklist. Cách sửa: thay vì blocklist, dùng allowlist — regex check giá trị phép năm phải là "12 ngày" (canonical), bất kỳ giá trị khác đều FAIL.
