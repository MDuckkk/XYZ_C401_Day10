"""
Expectation suite đơn giản (không bắt buộc Great Expectations).

Sinh viên có thể thay bằng GE / pydantic / custom — miễn là có halt có kiểm soát.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass
class ExpectationResult:
    name: str
    passed: bool
    severity: str  # "warn" | "halt"
    detail: str


def run_expectations(cleaned_rows: List[Dict[str, Any]]) -> Tuple[List[ExpectationResult], bool]:
    """
    Trả về (results, should_halt).

    should_halt = True nếu có bất kỳ expectation severity halt nào fail.
    """
    results: List[ExpectationResult] = []

    # E1: có ít nhất 1 dòng sau clean
    ok = len(cleaned_rows) >= 1
    results.append(
        ExpectationResult(
            "min_one_row",
            ok,
            "halt",
            f"cleaned_rows={len(cleaned_rows)}",
        )
    )

    # E2: không doc_id rỗng
    bad_doc = [r for r in cleaned_rows if not (r.get("doc_id") or "").strip()]
    ok2 = len(bad_doc) == 0
    results.append(
        ExpectationResult(
            "no_empty_doc_id",
            ok2,
            "halt",
            f"empty_doc_id_count={len(bad_doc)}",
        )
    )

    # E3: policy refund không được chứa cửa sổ sai 14 ngày (sau khi đã fix)
    bad_refund = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "policy_refund_v4"
        and "14 ngày làm việc" in (r.get("chunk_text") or "")
    ]
    ok3 = len(bad_refund) == 0
    results.append(
        ExpectationResult(
            "refund_no_stale_14d_window",
            ok3,
            "halt",
            f"violations={len(bad_refund)}",
        )
    )

    # E4: chunk_text đủ dài
    short = [r for r in cleaned_rows if len((r.get("chunk_text") or "")) < 8]
    ok4 = len(short) == 0
    results.append(
        ExpectationResult(
            "chunk_min_length_8",
            ok4,
            "warn",
            f"short_chunks={len(short)}",
        )
    )

    # E5: effective_date đúng định dạng ISO sau clean (phát hiện parser lỏng)
    iso_bad = [
        r
        for r in cleaned_rows
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", (r.get("effective_date") or "").strip())
    ]
    ok5 = len(iso_bad) == 0
    results.append(
        ExpectationResult(
            "effective_date_iso_yyyy_mm_dd",
            ok5,
            "halt",
            f"non_iso_rows={len(iso_bad)}",
        )
    )

    # E6: không còn marker phép năm cũ 10 ngày trên doc HR (conflict version sau clean)
    bad_hr_annual = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "hr_leave_policy"
        and "10 ngày phép năm" in (r.get("chunk_text") or "")
    ]
    ok6 = len(bad_hr_annual) == 0
    results.append(
        ExpectationResult(
            "hr_leave_no_stale_10d_annual",
            ok6,
            "halt",
            f"violations={len(bad_hr_annual)}",
        )
    )

    # E7: exported_at phải đúng định dạng timestamp export
    exported_bad = [
        r
        for r in cleaned_rows
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", (r.get("exported_at") or "").strip())
    ]
    ok7 = len(exported_bad) == 0
    results.append(
        ExpectationResult(
            "exported_at_iso_timestamp",
            ok7,
            "halt",
            f"non_iso_exported_at_rows={len(exported_bad)}",
        )
    )

    # E8: chunk_id phải unique để rerun/upsert không tạo duplicate vector
    ids = [(r.get("chunk_id") or "").strip() for r in cleaned_rows]
    duplicate_ids = len(ids) - len(set(ids))
    ok8 = duplicate_ids == 0 and all(ids)
    results.append(
        ExpectationResult(
            "chunk_id_unique_non_empty",
            ok8,
            "halt",
            f"duplicate_or_empty_chunk_ids={0 if ok8 else duplicate_ids or ids.count('')}",
        )
    )

    # E9: SLA P1 phải giữ đủ 2 mốc quan trọng 15 phút và 4 giờ trong cleaned dataset
    sla_p1_rows = [r for r in cleaned_rows if r.get("doc_id") == "sla_p1_2026"]
    bad_sla_p1 = [
        r
        for r in sla_p1_rows
        if "15 phút" not in (r.get("chunk_text") or "") or "4 giờ" not in (r.get("chunk_text") or "")
    ]
    ok9 = len(sla_p1_rows) >= 1 and len(bad_sla_p1) == 0
    results.append(
        ExpectationResult(
            "sla_p1_contains_response_and_resolution_targets",
            ok9,
            "halt",
            f"sla_rows={len(sla_p1_rows)} invalid_rows={len(bad_sla_p1)}",
        )
    )

    # E10: FAQ reset password phải giữ ngữ cảnh portal nội bộ sau clean
    helpdesk_rows = [r for r in cleaned_rows if r.get("doc_id") == "it_helpdesk_faq"]
    bad_helpdesk = [
        r
        for r in helpdesk_rows
        if "portal self-service" in (r.get("chunk_text") or "") and "nội bộ" not in (r.get("chunk_text") or "")
    ]
    ok10 = len(bad_helpdesk) == 0
    results.append(
        ExpectationResult(
            "helpdesk_portal_phrase_internal_context",
            ok10,
            "warn",
            f"rows_missing_internal_context={len(bad_helpdesk)}",
        )
    )

    halt = any(not r.passed and r.severity == "halt" for r in results)
    return results, halt
