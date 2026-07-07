#!/usr/bin/env python3
"""Build the full 100-question agent draft file from half drafts and add-ons."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_no}: {exc}") from exc
            if isinstance(row, dict):
                yield row


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def answer_to_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "".join(str(item) for item in value)
    return str(value).replace(",", "").replace(" ", "")


def normalize_draft(row: dict[str, Any], source_file: str) -> dict[str, Any]:
    evidence_notes = row.get("evidence_notes")
    if evidence_notes is None and isinstance(row.get("evidence"), list):
        evidence_notes = []
        for item in row["evidence"]:
            if isinstance(item, dict):
                doc_id = item.get("doc_id")
                page = item.get("page")
                unit_id = item.get("unit_id")
                text = item.get("text")
                evidence_notes.append(f"{doc_id} p{page} {unit_id}: {text}")
            else:
                evidence_notes.append(str(item))
    status = str(row.get("status") or "agent_supported")
    if status == "answered":
        status = "agent_supported"
    elif status == "supported":
        status = "agent_supported"
    elif status == "supported_with_caveat":
        status = "agent_supported_needs_review"
    return {
        "schema_version": "agent_answer_draft_v1",
        "qid": str(row.get("qid")),
        "domain": str(row.get("domain") or "").strip() or str(row.get("qid", "")).split("_a_")[0],
        "answer_draft": answer_to_string(row.get("answer_draft") if "answer_draft" in row else row.get("answer")),
        "confidence": str(row.get("confidence") or "medium"),
        "status": status,
        "method": str(row.get("method") or row.get("logic") or row.get("strategy") or ""),
        "evidence_notes": evidence_notes or [],
        "source_agent": str(row.get("source_agent") or source_file),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-drafts", default="processed_data/agent_evidence_seed/group_a_half_agent_drafts.jsonl")
    parser.add_argument("--additions", nargs="+", default=[])
    parser.add_argument("--all-questions", default="processed_data/agent_evidence_seed/group_a_all_questions.jsonl")
    parser.add_argument("--output", default="processed_data/agent_evidence_seed/group_a_all_agent_drafts.jsonl")
    parser.add_argument("--report", default="processed_data/agent_evidence_seed/group_a_all_agent_drafts_report.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    all_qids = [str(row["qid"]) for row in iter_jsonl(Path(args.all_questions))]
    drafts: dict[str, dict[str, Any]] = {}
    sources: dict[str, str] = {}
    for path_text in [args.base_drafts, *args.additions]:
        path = Path(path_text)
        for row in iter_jsonl(path):
            draft = normalize_draft(row, source_file=path.name)
            qid = draft["qid"]
            drafts[qid] = draft
            sources[qid] = path.name

    rows = [drafts[qid] for qid in all_qids if qid in drafts]
    missing = [qid for qid in all_qids if qid not in drafts]
    extra = sorted(set(drafts) - set(all_qids))
    by_domain = Counter(row["domain"] for row in rows)
    by_status = Counter(row["status"] for row in rows)
    by_confidence = Counter(row["confidence"] for row in rows)
    report = {
        "tool": "08_build_all_agent_drafts.py",
        "rows": len(rows),
        "all_questions": len(all_qids),
        "missing_qids": missing,
        "extra_qids": extra,
        "by_domain": dict(sorted(by_domain.items())),
        "by_status": dict(sorted(by_status.items())),
        "by_confidence": dict(sorted(by_confidence.items())),
        "sources": dict(sorted(Counter(sources.values()).items())),
        "outputs": {
            "drafts": str(Path(args.output).resolve()),
            "report": str(Path(args.report).resolve()),
        },
    }
    write_jsonl(Path(args.output), rows)
    write_json(Path(args.report), report)
    print(json.dumps({"rows": len(rows), "missing": len(missing), "extra": len(extra)}, ensure_ascii=False, indent=2))
    return 1 if missing or extra else 0


if __name__ == "__main__":
    raise SystemExit(main())
