#!/usr/bin/env python3
"""
Đánh giá retrieval đơn giản — before/after khi pipeline đổi dữ liệu embed.

Không bắt buộc LLM: chỉ kiểm tra top-k chunk có chứa keyword kỳ vọng hay không
(tiếp nối tinh thần Day 08/09 nhưng tập trung data layer).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent

EMBEDDING_BATCH_SIZE = 512


# ---------------------------------------------------------------------------
# Embedding resolution (giống etl_pipeline.py)
# ---------------------------------------------------------------------------

def _try_sentence_transformer():
    """Trả về (query_fn, chroma_ef)."""
    from sentence_transformers import SentenceTransformer
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    model_name = os.environ.get("ST_MODEL", "all-MiniLM-L6-v2")
    _model = SentenceTransformer(model_name)
    chroma_ef = SentenceTransformerEmbeddingFunction(model_name=model_name)

    def query_fn(texts: list[str]) -> list[list[float]]:
        return _model.encode(texts, show_progress_bar=False).tolist()

    print(f"[eval] embed_backend=SentenceTransformer model={model_name}")
    return query_fn, chroma_ef


def _try_openai():
    """Trả về (query_fn, None)."""
    from openai import OpenAI

    client = OpenAI()
    model_name = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    client.embeddings.create(model=model_name, input=["ping"])

    def query_fn(texts: list[str]) -> list[list[float]]:
        all_emb: list[list[float]] = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[i : i + EMBEDDING_BATCH_SIZE]
            resp = client.embeddings.create(model=model_name, input=batch)
            all_emb.extend([d.embedding for d in resp.data])
        return all_emb

    print(f"[eval] embed_backend=OpenAI model={model_name}")
    return query_fn, None


def resolve_embedding():
    """SentenceTransformer → OpenAI fallback. Returns (query_fn, chroma_ef | None)."""
    try:
        return _try_sentence_transformer()
    except Exception as e:
        print(f"[eval] SentenceTransformer không khả dụng ({type(e).__name__}: {e}), thử OpenAI...")

    try:
        return _try_openai()
    except Exception as e:
        print(f"[eval] OpenAI cũng thất bại ({type(e).__name__}: {e})", file=sys.stderr)
        raise RuntimeError(
            "Không thể khởi tạo embedding backend. "
            "Cài sentence-transformers hoặc set OPENAI_API_KEY."
        ) from e


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--questions",
        default=str(ROOT / "data" / "test_questions.json"),
        help="JSON danh sách câu hỏi golden (retrieval)",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "artifacts" / "eval" / "before_after_eval.csv"),
        help="CSV kết quả",
    )
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    try:
        import chromadb
    except ImportError:
        print("Install: pip install chromadb", file=sys.stderr)
        return 1

    qpath = Path(args.questions)
    if not qpath.is_file():
        print(f"questions not found: {qpath}", file=sys.stderr)
        return 1

    questions = json.loads(qpath.read_text(encoding="utf-8-sig"))
    db_path = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
    collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")

    # --- Resolve embedding backend ---
    try:
        query_fn, chroma_ef = resolve_embedding()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    client = chromadb.PersistentClient(path=db_path)

    try:
        if chroma_ef is not None:
            col = client.get_collection(name=collection_name, embedding_function=chroma_ef)
        else:
            col = client.get_collection(name=collection_name)
    except Exception as e:
        print(f"Collection error: {e}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "question_id",
        "question",
        "top1_doc_id",
        "top1_preview",
        "contains_expected",
        "hits_forbidden",
        "top1_doc_expected",
        "top_k_used",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=fieldnames)
        w.writeheader()
        for q in questions:
            text = q["question"]

            if chroma_ef is not None:
                # SentenceTransformer: ChromaDB tự embed query
                res = col.query(query_texts=[text], n_results=args.top_k)
            else:
                # OpenAI: tự embed query rồi truyền query_embeddings
                q_emb = query_fn([text])
                res = col.query(query_embeddings=q_emb, n_results=args.top_k)

            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            top_doc = (metas[0] or {}).get("doc_id", "") if metas else ""
            preview = (docs[0] or "")[:180].replace("\n", " ") if docs else ""
            blob = " ".join(docs).lower()
            must_any = [x.lower() for x in q.get("must_contain_any", [])]
            forbidden = [x.lower() for x in q.get("must_not_contain", [])]
            ok_any = any(m in blob for m in must_any) if must_any else True
            bad_forb = any(m in blob for m in forbidden) if forbidden else False
            want_top1 = (q.get("expect_top1_doc_id") or "").strip()
            top1_expected = ""
            if want_top1:
                top1_expected = "yes" if top_doc == want_top1 else "no"
            w.writerow(
                {
                    "question_id": q.get("id", ""),
                    "question": text,
                    "top1_doc_id": top_doc,
                    "top1_preview": preview,
                    "contains_expected": "yes" if ok_any else "no",
                    "hits_forbidden": "yes" if bad_forb else "no",
                    "top1_doc_expected": top1_expected,
                    "top_k_used": args.top_k,
                }
            )

    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())