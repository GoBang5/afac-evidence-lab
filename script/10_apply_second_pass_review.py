#!/usr/bin/env python3
"""Apply second-pass review decisions to compact answer exports."""

from __future__ import annotations

import argparse
import csv
import json
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", default="processed_data/agent_evidence_seed/group_a_all_agent_answers.csv")
    parser.add_argument("--second-pass", default="processed_data/agent_evidence_seed/group_a_needs_review_second_pass.jsonl")
    parser.add_argument("--output", default="processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass.csv")
    parser.add_argument("--report", default="processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass_report.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    second = {row["qid"]: row for row in iter_jsonl(Path(args.second_pass))}
    with Path(args.answers).open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    changed: list[dict[str, str]] = []
    for row in rows:
        review = second.get(row["qid"])
        row["second_pass_status"] = ""
        row["second_pass_note"] = ""
        if not review:
            continue
        original = row["answer_draft"]
        reviewed = str(review.get("reviewed_answer") or "")
        row["answer_draft_second_pass"] = reviewed
        row["second_pass_status"] = str(review.get("review_status") or "")
        row["second_pass_note"] = str(review.get("reason") or "")
        if reviewed != original:
            changed.append(
                {
                    "qid": row["qid"],
                    "original_answer": original,
                    "reviewed_answer": reviewed,
                    "review_status": row["second_pass_status"],
                }
            )
    for row in rows:
        row.setdefault("answer_draft_second_pass", row["answer_draft"])
        row.setdefault("second_pass_status", "")
        row.setdefault("second_pass_note", "")

    fieldnames = [
        "qid",
        "domain",
        "answer_draft",
        "answer_draft_second_pass",
        "answer_format",
        "confidence",
        "status",
        "second_pass_status",
        "method",
        "second_pass_note",
    ]
    with Path(args.output).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{key: row.get(key, "") for key in fieldnames} for row in rows])
    report = {
        "tool": "10_apply_second_pass_review.py",
        "rows": len(rows),
        "second_pass_rows": len(second),
        "changed_answers": changed,
        "outputs": {
            "answers_second_pass": str(Path(args.output).resolve()),
            "report": str(Path(args.report).resolve()),
        },
    }
    write_json(Path(args.report), report)
    print(json.dumps({"rows": len(rows), "changed": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
