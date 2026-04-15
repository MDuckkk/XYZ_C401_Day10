"""
Cleaning rules — raw export → cleaned rows + quarantine.

Baseline gồm các failure mode mở rộng (allowlist doc_id, parse ngày, HR stale version).
Sinh viên thêm ≥3 rule mới: mỗi rule phải ghi `metric_impact` (xem README — chống trivial).
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Khớp export hợp lệ trong lab (mở rộng khi nhóm thêm doc mới — phải đồng bộ contract).
ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
    }
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str, seq: int) -> str:
    h = hashlib.sha256(f"{doc_id}|{chunk_text}|{seq}".encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{seq}_{h}"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    """
    Trả về (iso_date, error_reason).
    iso_date rỗng nếu không parse được.
    """
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _DMY_SLASH.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    return "", "invalid_effective_date_format"


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def _normalize_exported_at(raw: str) -> Tuple[str, str]:
    s = (raw or "").strip()
    if not s:
        return "", "missing_exported_at"
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", s):
        return s, ""
    return "", "invalid_exported_at_format"


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """
    Trả về (cleaned, quarantine).

    Baseline (mở rộng theo narrative Day 10):
    1) Quarantine: doc_id không thuộc allowlist (export lạ / catalog sai).
    2) Chuẩn hoá effective_date sang YYYY-MM-DD; quarantine nếu không parse được.
    3) Quarantine: chunk hr_leave_policy có effective_date < 2026-01-01 (bản HR cũ / conflict version).
    4) Quarantine: chunk_text rỗng hoặc effective_date rỗng sau chuẩn hoá.
    5) Loại trùng nội dung chunk_text (giữ bản đầu).
    6) Fix stale refund: policy_refund_v4 chứa '14 ngày làm việc' → 7 ngày.
    """
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    stats: Dict[str, int] = {
        "rows_seen": len(rows),
        "unknown_doc_id_quarantined": 0,
        "missing_effective_date_quarantined": 0,
        "invalid_effective_date_quarantined": 0,
        "stale_hr_policy_quarantined": 0,
        "missing_chunk_text_quarantined": 0,
        "duplicate_chunk_text_quarantined": 0,
        "invalid_exported_at_quarantined": 0,
        "exported_at_normalized": 0,
        "refund_window_fixed": 0,
        "refund_phrase_normalized": 0,
        "helpdesk_sync_phrase_normalized": 0,
        "hr_leave_phrase_normalized": 0,
        "sla_resolution_phrase_normalized": 0,
        "helpdesk_portal_phrase_normalized": 0,
    }
    seq = 0

    for raw in rows:
        doc_id = raw.get("doc_id", "")
        text = raw.get("chunk_text", "")
        eff_raw = raw.get("effective_date", "")
        exported_at = raw.get("exported_at", "")

        if doc_id not in ALLOWED_DOC_IDS:
            stats["unknown_doc_id_quarantined"] += 1
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            stats["missing_effective_date_quarantined"] += 1
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err == "invalid_effective_date_format":
            stats["invalid_effective_date_quarantined"] += 1
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        if doc_id == "hr_leave_policy" and eff_norm < "2026-01-01":
            stats["stale_hr_policy_quarantined"] += 1
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        if not text:
            stats["missing_chunk_text_quarantined"] += 1
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        key = _norm_text(text)
        if key in seen_text:
            stats["duplicate_chunk_text_quarantined"] += 1
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        exported_norm, exported_err = _normalize_exported_at(exported_at)
        if exported_err:
            stats["invalid_exported_at_quarantined"] += 1
            quarantine.append({**raw, "reason": exported_err})
            continue

        fixed_text = text
        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            if "14 ngày làm việc" in fixed_text:
                fixed_text = fixed_text.replace(
                    "14 ngày làm việc",
                    "7 ngày làm việc",
                )
                fixed_text += " [cleaned: stale_refund_window]"
                stats["refund_window_fixed"] += 1
            if "xác nhận đơn (" in fixed_text:
                fixed_text = fixed_text.replace("xác nhận đơn (", "xác nhận đơn hàng (")
                stats["refund_phrase_normalized"] += 1

        if doc_id == "it_helpdesk_faq" and "tối đa 24 giờ để đồng bộ toàn hệ thống" in fixed_text:
            fixed_text = fixed_text.replace(
                "tối đa 24 giờ để đồng bộ toàn hệ thống",
                "tối đa 24 giờ để đồng bộ trên toàn hệ thống",
            )
            stats["helpdesk_sync_phrase_normalized"] += 1
        if doc_id == "it_helpdesk_faq" and "portal self-service" in fixed_text:
            fixed_text = fixed_text.replace("portal self-service", "portal self-service nội bộ")
            stats["helpdesk_portal_phrase_normalized"] += 1

        if doc_id == "hr_leave_policy" and "12 ngày phép năm" in fixed_text:
            fixed_text = fixed_text.replace("12 ngày phép năm", "12 ngày/năm")
            stats["hr_leave_phrase_normalized"] += 1

        if doc_id == "sla_p1_2026" and "resolution trong 4 giờ" in fixed_text:
            fixed_text = fixed_text.replace("resolution trong 4 giờ", "resolution time trong 4 giờ")
            stats["sla_resolution_phrase_normalized"] += 1

        if exported_norm != exported_at:
            stats["exported_at_normalized"] += 1

        seq += 1
        cleaned.append(
            {
                "chunk_id": _stable_chunk_id(doc_id, fixed_text, seq),
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_norm,
            }
        )

    return cleaned, quarantine, stats


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)
