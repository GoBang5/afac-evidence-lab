#!/usr/bin/env python3
"""Merge agent answer drafts into evidence candidate annotations."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", default="processed_data/agent_evidence_seed/group_a_half_agent_annotations.jsonl")
    parser.add_argument("--drafts", default="processed_data/agent_evidence_seed/group_a_half_agent_drafts.jsonl")
    parser.add_argument("--output", default="processed_data/agent_evidence_seed/group_a_half_agent_reviewed.jsonl")
    parser.add_argument("--report", default="processed_data/agent_evidence_seed/group_a_half_agent_reviewed_report.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    annotation_path = Path(args.annotations)
    draft_path = Path(args.drafts)
    output_path = Path(args.output)
    report_path = Path(args.report)

    drafts = {str(row["qid"]): row for row in iter_jsonl(draft_path)}
    rows: list[dict[str, Any]] = []
    missing_drafts: list[str] = []
    for row in iter_jsonl(annotation_path):
        qid = str(row.get("qid"))
        draft = drafts.get(qid)
        if not draft:
            missing_drafts.append(qid)
            rows.append(row)
            continue
        merged = dict(row)
        merged["schema_version"] = "agent_evidence_reviewed_v1"
        merged["answer_draft"] = draft.get("answer_draft")
        merged["answer_source"] = "multi_agent_draft"
        merged["agent_draft"] = {
            "confidence": draft.get("confidence"),
            "status": draft.get("status"),
            "method": draft.get("method"),
            "evidence_notes": draft.get("evidence_notes") or [],
            "source_agent": draft.get("source_agent"),
        }
        rows.append(merged)

    extra_drafts = sorted(set(drafts) - {str(row.get("qid")) for row in rows})
    by_domain = Counter(str(row.get("domain")) for row in rows)
    by_status = Counter(str((row.get("agent_draft") or {}).get("status", "missing_draft")) for row in rows)
    by_confidence = Counter(str((row.get("agent_draft") or {}).get("confidence", "missing_draft")) for row in rows)
    report = {
        "tool": "07_merge_agent_drafts.py",
        "inputs": {
            "annotations": str(annotation_path.resolve()),
            "drafts": str(draft_path.resolve()),
        },
        "outputs": {
            "reviewed": str(output_path.resolve()),
            "report": str(report_path.resolve()),
        },
        "rows": len(rows),
        "drafts": len(drafts),
        "missing_drafts": missing_drafts,
        "extra_drafts": extra_drafts,
        "by_domain": dict(sorted(by_domain.items())),
        "by_status": dict(sorted(by_status.items())),
        "by_confidence": dict(sorted(by_confidence.items())),
    }
    write_jsonl(output_path, rows)
    write_json(report_path, report)
    print(json.dumps({"rows": len(rows), "missing_drafts": len(missing_drafts), "extra_drafts": len(extra_drafts)}, ensure_ascii=False, indent=2))
    return 1 if missing_drafts or extra_drafts else 0


if __name__ == "__main__":
    raise SystemExit(main())
