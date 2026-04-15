# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** `[Trần Thanh Nguyên]`  
**Vai trò:** `[Ingestion / Cleaning / Embed / Monitoring]` — `[mô tả ngắn]`  
**Ngày nộp:** 2026-04-15

---

## 1. Tôi phụ trách phần nào?

**File / module:**

- `etl_pipeline.py` — entrypoint chính, hàm `cmd_run`, `cmd_embed_internal`
- `eval_retrieval.py` — đánh giá retrieval before/after
- `transform/cleaning_rules.py` — cleaning rules (nếu có chỉnh sửa)
- `quality/expectations.py` — expectation suite (nếu có chỉnh sửa)

**Kết nối với thành viên khác:**

Tôi nhận cleaned CSV từ module transform do `[TÊN]` phụ trách, chạy expectation validate, sau đó embed vào ChromaDB. Output manifest được `[TÊN]` sử dụng cho freshness monitoring. Eval retrieval kiểm tra chất lượng toàn pipeline end-to-end.

**Bằng chứng:**

- Commit: `[HASH]` — sửa embedding backend từ SentenceTransformer sang flexible fallback
- File output: `artifacts/eval/after_inject_bad.csv`, `after_clean.csv`, `after_inject_leave.csv`, `after_clean_leave.csv`

---

## 2. Một quyết định kỹ thuật

**Quyết định:** Thiết kế embedding backend linh hoạt — thử SentenceTransformer trước, fallback sang OpenAI.

Lý do: môi trường lab không phải lúc nào cũng cài được `sentence-transformers` (cần PyTorch, nặng ~2GB). Thay vì bắt buộc cài, tôi thiết kế `resolve_embedding_backend()` thử import SentenceTransformer trước — nếu thành công thì dùng (miễn phí, chạy local), nếu fail thì fallback sang OpenAI API (cần key, tốn phí nhưng luôn khả dụng). Hàm này trả về `(embed_fn, chroma_ef)` — nếu có `chroma_ef` (SentenceTransformer) thì ChromaDB tự embed, nếu không (OpenAI) thì pipeline tự tính embedding rồi truyền vào `upsert(embeddings=...)`. Cùng pattern được áp dụng cho cả `eval_retrieval.py` để đảm bảo nhất quán.

---

## 3. Một lỗi hoặc anomaly đã xử lý

**Triệu chứng:** Chạy `eval_retrieval.py` báo lỗi `JSONDecodeError: Unexpected UTF-8 BOM` khi đọc `test_questions.json`.

**Phát hiện:** Error traceback trực tiếp — `json.loads()` không chấp nhận BOM (byte order mark) khi dùng encoding `utf-8`.

**Fix:** Đổi encoding từ `utf-8` sang `utf-8-sig` trong dòng đọc file:

```python
# Trước:
questions = json.loads(qpath.read_text(encoding="utf-8"))
# Sau:
questions = json.loads(qpath.read_text(encoding="utf-8-sig"))
```

Nguyên nhân gốc: PowerShell `Set-Content` mặc định ghi file với BOM. `utf-8-sig` tự động bỏ BOM nếu có, hoặc đọc bình thường nếu không có — tương thích cả hai trường hợp.

---

## 4. Bằng chứng trước / sau

**run_id inject:** `inject-bad` / `inject-leave`  
**run_id clean:** `clean-leave`

Câu `q_refund_window` (từ `after_inject_bad.csv` → `after_clean.csv`):

| Metric | Inject | Clean |
|--------|--------|-------|
| top1_preview | ...14 ngày làm việc... (lỗi migration) | ...7 ngày làm việc... |
| hits_forbidden | yes | no |

Câu `q_leave_version` (từ `after_inject_leave.csv` → `after_clean_leave.csv`):

| Metric | Inject | Clean |
|--------|--------|-------|
| top1_preview | ...15 ngày phép năm... | ...12 ngày phép năm... |
| contains_expected | no | yes |
| hits_forbidden | yes | no |

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ, tôi sẽ thêm LLM judge vào `eval_retrieval.py`: sau khi lấy top-k chunk, gọi LLM sinh câu trả lời rồi so sánh với golden answer bằng semantic similarity. Keyword matching hiện tại chỉ bắt được lỗi rõ ràng (sai con số), nhưng không phát hiện được lỗi ngữ nghĩa phức tạp hơn (vd: chunk đúng keyword nhưng context sai).
