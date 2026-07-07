"""File IO helpers for the AFAC2026-4 agent."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable


def iter_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
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


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))


def write_json(path: str | Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            count += 1
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return count


def read_prior_answers(path: str | Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    out: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            qid = str(row.get("qid") or "").strip()
            if not qid or qid == "summary":
                continue
            answer = (
                row.get("answer")
                or row.get("answer_draft_second_pass")
                or row.get("answer_draft")
                or ""
            )
            out[qid] = str(answer).strip().upper()
    return out


def write_answer_csv(path: str | Path, rows: list[dict[str, Any]], summary: dict[str, int]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "qid": "summary",
                "answer": "",
                "prompt_tokens": summary.get("prompt_tokens", 0),
                "completion_tokens": summary.get("completion_tokens", 0),
                "total_tokens": summary.get("total_tokens", 0),
            }
        )
        for row in rows:
            writer.writerow(
                {
                    "qid": row["qid"],
                    "answer": row.get("answer", ""),
                    "prompt_tokens": row.get("prompt_tokens", 0),
                    "completion_tokens": row.get("completion_tokens", 0),
                    "total_tokens": row.get("total_tokens", 0),
                }
            )

