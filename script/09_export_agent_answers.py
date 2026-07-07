#!/usr/bin/env python3
"""Export compact answer tables from agent reviewed annotations."""

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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed", default="processed_data/agent_evidence_seed/group_a_all_agent_reviewed.jsonl")
    parser.add_argument("--answers-csv", default="processed_data/agent_evidence_seed/group_a_all_agent_answers.csv")
    parser.add_argument("--needs-review", default="processed_data/agent_evidence_seed/group_a_all_needs_review.jsonl")
    parser.add_argument("--report", default="processed_data/agent_evidence_seed/group_a_all_agent_answers_report.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = list(iter_jsonl(Path(args.reviewed)))
    answer_rows: list[dict[str, str]] = []
    needs_review: list[dict[str, Any]] = []
    single_format_multi_answers: list[dict[str, str]] = []
    for row in rows:
        draft = row.get("agent_draft") or {}
        answer = str(row.get("answer_draft") or "")
        status = str(draft.get("status") or "")
        answer_row = {
            "qid": str(row.get("qid") or ""),
            "domain": str(row.get("domain") or ""),
            "answer_draft": answer,
            "answer_format": str(row.get("answer_format") or ""),
            "confidence": str(draft.get("confidence") or ""),
            "status": status,
            "method": str(draft.get("method") or ""),
        }
        answer_rows.append(answer_row)
        if status != "agent_supported":
            needs_review.append(
                {
                    **answer_row,
                    "evidence_notes": draft.get("evidence_notes") or [],
                }
            )
        if answer_row["answer_format"] in {"mcq", "tf"} and len(answer) > 1:
            single_format_multi_answers.append(answer_row)

    Path(args.answers_csv).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.answers_csv).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["qid", "domain", "answer_draft", "answer_format", "confidence", "status", "method"],
        )
        writer.writeheader()
        writer.writerows(answer_rows)
    write_jsonl(Path(args.needs_review), needs_review)
    report = {
        "tool": "09_export_agent_answers.py",
        "rows": len(rows),
        "answer_rows": len(answer_rows),
        "needs_review_rows": len(needs_review),
        "single_format_multi_answers": single_format_multi_answers,
        "outputs": {
            "answers_csv": str(Path(args.answers_csv).resolve()),
            "needs_review": str(Path(args.needs_review).resolve()),
            "report": str(Path(args.report).resolve()),
        },
    }
    write_json(Path(args.report), report)
    print(json.dumps({"answers": len(answer_rows), "needs_review": len(needs_review)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
