#!/usr/bin/env python3
"""
Lab Day 10 — ETL entrypoint: ingest → clean → validate → embed.

Tiếp nối Day 09: cùng corpus docs trong data/docs/; pipeline này xử lý *export* raw (CSV)
đại diện cho lớp ingestion từ DB/API trước khi embed lại vector store.

Chạy nhanh:
  pip install -r requirements.txt
  cp .env.example .env
  python etl_pipeline.py run

Chế độ inject (Sprint 3 — bỏ fix refund để expectation fail / eval xấu):
  python etl_pipeline.py run --no-refund-fix --skip-validate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from monitoring.freshness_check import check_manifest_freshness
from quality.expectations import run_expectations
from transform.cleaning_rules import clean_rows, load_raw_csv, write_cleaned_csv, write_quarantine_csv

load_dotenv()

ROOT = Path(__file__).resolve().parent
RAW_DEFAULT = ROOT / "data" / "raw" / "policy_export_dirty.csv"
ART = ROOT / "artifacts"
LOG_DIR = ART / "logs"
MAN_DIR = ART / "manifests"
QUAR_DIR = ART / "quarantine"
CLEAN_DIR = ART / "cleaned"

EMBEDDING_BATCH_SIZE = 512


# ---------------------------------------------------------------------------
# Embedding strategy: SentenceTransformer → OpenAI fallback
# ---------------------------------------------------------------------------

def _try_sentence_transformer(log: Callable[[str], None]):
    """Thử khởi tạo SentenceTransformer. Trả về (embed_fn, chroma_ef) hoặc raise."""
    from sentence_transformers import SentenceTransformer
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    model_name = os.environ.get("ST_MODEL", "all-MiniLM-L6-v2")
    # Warm-up: load model để chắc chắn tải được
    _model = SentenceTransformer(model_name)

    chroma_ef = SentenceTransformerEmbeddingFunction(model_name=model_name)

    def embed_fn(texts: list[str]) -> list[list[float]]:
        return _model.encode(texts, show_progress_bar=False).tolist()

    log(f"embed_backend=SentenceTransformer model={model_name}")
    return embed_fn, chroma_ef


def _try_openai(log: Callable[[str], None]):
    """Khởi tạo OpenAI embeddings. Trả về (embed_fn, None) — không có chroma_ef."""
    from openai import OpenAI

    client = OpenAI()  # cần OPENAI_API_KEY trong env
    model_name = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    # Ping nhanh để fail-fast nếu key sai / quota hết
    client.embeddings.create(model=model_name, input=["ping"])

    def embed_fn(texts: list[str]) -> list[list[float]]:
        all_emb: list[list[float]] = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[i : i + EMBEDDING_BATCH_SIZE]
            resp = client.embeddings.create(model=model_name, input=batch)
            all_emb.extend([d.embedding for d in resp.data])
        return all_emb

    log(f"embed_backend=OpenAI model={model_name}")
    return embed_fn, None


def resolve_embedding_backend(log: Callable[[str], None]):
    """
    Thử SentenceTransformer trước, nếu fail (thiếu lib / lỗi model) thì
    fallback sang OpenAI.

    Returns:
        (embed_fn, chroma_ef | None)
        - embed_fn(texts) -> list[list[float]]
        - chroma_ef: truyền cho get_or_create_collection nếu có,
          None nếu dùng OpenAI (tự truyền embeddings).
    """
    # --- Attempt 1: SentenceTransformer ---
    try:
        return _try_sentence_transformer(log)
    except Exception as e:
        log(f"INFO: SentenceTransformer không khả dụng ({type(e).__name__}: {e}), thử OpenAI...")

    # --- Attempt 2: OpenAI ---
    try:
        return _try_openai(log)
    except Exception as e:
        log(f"ERROR: OpenAI embedding cũng thất bại ({type(e).__name__}: {e})")
        raise RuntimeError(
            "Không thể khởi tạo embedding backend nào. "
            "Cài sentence-transformers hoặc set OPENAI_API_KEY."
        ) from e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%MZ")
    raw_path = Path(args.raw)
    if not raw_path.is_file():
        print(f"ERROR: raw file not found: {raw_path}", file=sys.stderr)
        return 1

    log_path = LOG_DIR / f"run_{run_id.replace(':', '-')}.log"
    for p in (LOG_DIR, MAN_DIR, QUAR_DIR, CLEAN_DIR):
        p.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        print(msg)
        _log(log_path, msg)

    rows = load_raw_csv(raw_path)
    raw_count = len(rows)
    log(f"run_id={run_id}")
    log(f"raw_records={raw_count}")

    cleaned, quarantine = clean_rows(
        rows,
        apply_refund_window_fix=not args.no_refund_fix,
    )
    cleaned_path = CLEAN_DIR / f"cleaned_{run_id.replace(':', '-')}.csv"
    quar_path = QUAR_DIR / f"quarantine_{run_id.replace(':', '-')}.csv"
    write_cleaned_csv(cleaned_path, cleaned)
    write_quarantine_csv(quar_path, quarantine)

    log(f"cleaned_records={len(cleaned)}")
    log(f"quarantine_records={len(quarantine)}")
    log(f"cleaned_csv={cleaned_path.relative_to(ROOT)}")
    log(f"quarantine_csv={quar_path.relative_to(ROOT)}")

    results, halt = run_expectations(cleaned)
    for r in results:
        sym = "OK" if r.passed else "FAIL"
        log(f"expectation[{r.name}] {sym} ({r.severity}) :: {r.detail}")
    if halt and not args.skip_validate:
        log("PIPELINE_HALT: expectation suite failed (halt).")
        return 2
    if halt and args.skip_validate:
        log("WARN: expectation failed but --skip-validate → tiếp tục embed (chỉ dùng cho demo Sprint 3).")

    # Embed
    embed_ok = cmd_embed_internal(
        cleaned_path,
        run_id=run_id,
        log=log,
    )
    if not embed_ok:
        return 3

    latest_exported = ""
    if cleaned:
        latest_exported = max((r.get("exported_at") or "" for r in cleaned), default="")

    manifest = {
        "run_id": run_id,
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_path": str(raw_path.relative_to(ROOT)),
        "raw_records": raw_count,
        "cleaned_records": len(cleaned),
        "quarantine_records": len(quarantine),
        "latest_exported_at": latest_exported,
        "no_refund_fix": bool(args.no_refund_fix),
        "skipped_validate": bool(args.skip_validate and halt),
        "cleaned_csv": str(cleaned_path.relative_to(ROOT)),
        "chroma_path": os.environ.get("CHROMA_DB_PATH", "./chroma_db"),
        "chroma_collection": os.environ.get("CHROMA_COLLECTION", "day10_kb"),
    }
    man_path = MAN_DIR / f"manifest_{run_id.replace(':', '-')}.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"manifest_written={man_path.relative_to(ROOT)}")

    status, fdetail = check_manifest_freshness(man_path, sla_hours=float(os.environ.get("FRESHNESS_SLA_HOURS", "24")))
    log(f"freshness_check={status} {json.dumps(fdetail, ensure_ascii=False)}")

    log("PIPELINE_OK")
    return 0


def cmd_embed_internal(cleaned_csv: Path, *, run_id: str, log) -> bool:
    try:
        import chromadb
    except ImportError:
        log("ERROR: chromadb chưa cài. pip install -r requirements.txt")
        return False

    db_path = os.environ.get("CHROMA_DB_PATH", str(ROOT / "chroma_db"))
    collection_name = os.environ.get("CHROMA_COLLECTION", "day10_kb")

    from transform.cleaning_rules import load_raw_csv as load_csv

    rows = load_csv(cleaned_csv)
    if not rows:
        log("WARN: cleaned CSV rỗng — không embed.")
        return True

    # --- Resolve embedding backend ---
    try:
        embed_fn, chroma_ef = resolve_embedding_backend(log)
    except RuntimeError as e:
        log(str(e))
        return False

    client = chromadb.PersistentClient(path=db_path)

    # Nếu có chroma_ef (SentenceTransformer) → ChromaDB tự embed
    # Nếu không (OpenAI) → ta truyền embeddings thủ công
    if chroma_ef is not None:
        col = client.get_or_create_collection(
            name=collection_name, embedding_function=chroma_ef
        )
    else:
        col = client.get_or_create_collection(name=collection_name)

    ids = [r["chunk_id"] for r in rows]

    # Tránh "mồi cũ" trong top-k: xóa id không còn trong cleaned run này
    try:
        prev = col.get(include=[])
        prev_ids = set(prev.get("ids") or [])
        drop = sorted(prev_ids - set(ids))
        if drop:
            col.delete(ids=drop)
            log(f"embed_prune_removed={len(drop)}")
    except Exception as e:
        log(f"WARN: embed prune skip: {e}")

    documents = [r["chunk_text"] for r in rows]
    metadatas = [
        {
            "doc_id": r.get("doc_id", ""),
            "effective_date": r.get("effective_date", ""),
            "run_id": run_id,
        }
        for r in rows
    ]

    log(f"embed_start chunks={len(documents)}")

    if chroma_ef is not None:
        # SentenceTransformer: ChromaDB tự gọi embed qua embedding_function
        col.upsert(ids=ids, documents=documents, metadatas=metadatas)
    else:
        # OpenAI: tự tính embeddings rồi truyền vào
        try:
            embeddings = embed_fn(documents)
        except Exception as e:
            log(f"ERROR: embedding failed: {e}")
            return False
        col.upsert(
            ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas
        )

    log(f"embed_upsert count={len(ids)} collection={collection_name}")
    return True


def cmd_freshness(args: argparse.Namespace) -> int:
    p = Path(args.manifest)
    if not p.is_file():
        print(f"manifest not found: {p}", file=sys.stderr)
        return 1
    sla = float(os.environ.get("FRESHNESS_SLA_HOURS", "24"))
    status, detail = check_manifest_freshness(p, sla_hours=sla)
    print(status, json.dumps(detail, ensure_ascii=False))
    return 0 if status != "FAIL" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Day 10 ETL pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="ingest → clean → validate → embed")
    p_run.add_argument("--raw", default=str(RAW_DEFAULT), help="Đường dẫn CSV raw export")
    p_run.add_argument("--run-id", default="", help="ID run (mặc định: UTC timestamp)")
    p_run.add_argument(
        "--no-refund-fix",
        action="store_true",
        help="Không áp dụng rule fix cửa sổ 14→7 ngày (dùng cho inject corruption / before).",
    )
    p_run.add_argument(
        "--skip-validate",
        action="store_true",
        help="Vẫn embed khi expectation halt (chỉ phục vụ demo có chủ đích).",
    )
    p_run.set_defaults(func=cmd_run)

    p_fr = sub.add_parser("freshness", help="Đọc manifest và kiểm tra SLA freshness")
    p_fr.add_argument("--manifest", required=True)
    p_fr.set_defaults(func=cmd_freshness)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())