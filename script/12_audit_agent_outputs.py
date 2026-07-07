#!/usr/bin/env python3
"""Audit AFAC agent run outputs before review or submission.

The audit is deterministic and model-free.  It checks the public submission
shape from `introduction.md` plus evidence/log consistency:

- `answer.csv` schema, summary row, token totals, qid coverage, answer legality
- `evidence.json` qid coverage, answer consistency, evidence ids, judgement shape
- optional `questions.jsonl` and `needs_review.jsonl` risk summary
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

LETTERS = "ABCD"
TOKEN_BUDGET = 5_000_000


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
                rows.append(row)
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def legal_answer(answer: str, answer_format: str) -> tuple[bool, str]:
    answer = (answer or "").strip()
    if not answer:
        return False, "empty_answer"
    if not re.fullmatch(r"[A-D]+", answer):
        return False, "invalid_characters"
    if answer_format in {"mcq", "tf"}:
        if len(answer) != 1:
            return False, "single_answer_has_multiple_letters"
        return True, ""
    if answer_format == "multi":
        if "".join(sorted(set(answer), key=LETTERS.index)) != answer:
            return False, "multi_answer_not_sorted_unique"
        return True, ""
    return False, "unknown_answer_format"


def as_int(value: Any, errors: list[str], label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"invalid_integer:{label}:{value}")
        return 0


def load_questions(path: Path) -> dict[str, dict[str, Any]]:
    rows = iter_jsonl(path)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        qid = str(row.get("qid") or "")
        if qid:
            out[qid] = row
    return out


def audit_answer_csv(
    path: Path,
    questions: dict[str, dict[str, Any]],
    allow_partial: bool,
) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.exists():
        return {}, [f"missing_answer_csv:{path}"], warnings
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        expected = ["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"]
        if fieldnames != expected:
            errors.append(f"answer_csv_bad_header:{fieldnames}")
        rows = list(reader)

    if not rows:
        errors.append("answer_csv_empty")
        return {}, errors, warnings
    summary = rows[0]
    if summary.get("qid") != "summary":
        errors.append("answer_csv_first_row_not_summary")
    answer_rows = [row for row in rows if row.get("qid") != "summary"]
    qids = [str(row.get("qid") or "") for row in answer_rows]
    dupes = sorted(qid for qid, count in Counter(qids).items() if count > 1)
    if dupes:
        errors.append("duplicate_answer_qids:" + ",".join(dupes[:20]))
    expected_qids = set(questions)
    answer_qids = set(qids)
    missing = sorted(expected_qids - answer_qids)
    extra = sorted(answer_qids - expected_qids)
    if missing and not allow_partial:
        errors.append("missing_answer_qids:" + ",".join(missing[:20]))
    elif missing:
        warnings.append(f"partial_answer_qids_missing:{len(missing)}")
    if extra:
        errors.append("extra_answer_qids:" + ",".join(extra[:20]))

    answer_format_errors: list[dict[str, str]] = []
    prompt_sum = 0
    completion_sum = 0
    total_sum = 0
    for row in answer_rows:
        qid = str(row.get("qid") or "")
        q = questions.get(qid) or {}
        answer_format = str(q.get("answer_format") or "")
        ok, reason = legal_answer(str(row.get("answer") or ""), answer_format)
        if not ok:
            answer_format_errors.append({"qid": qid, "answer": str(row.get("answer") or ""), "reason": reason})
        prompt = as_int(row.get("prompt_tokens"), errors, f"{qid}.prompt_tokens")
        completion = as_int(row.get("completion_tokens"), errors, f"{qid}.completion_tokens")
        total = as_int(row.get("total_tokens"), errors, f"{qid}.total_tokens")
        if min(prompt, completion, total) < 0:
            errors.append(f"negative_tokens:{qid}")
        if total != prompt + completion:
            errors.append(f"row_token_total_mismatch:{qid}")
        prompt_sum += prompt
        completion_sum += completion
        total_sum += total

    if answer_format_errors:
        errors.append(f"answer_format_errors:{len(answer_format_errors)}")

    summary_prompt = as_int(summary.get("prompt_tokens"), errors, "summary.prompt_tokens")
    summary_completion = as_int(summary.get("completion_tokens"), errors, "summary.completion_tokens")
    summary_total = as_int(summary.get("total_tokens"), errors, "summary.total_tokens")
    if summary_total != summary_prompt + summary_completion:
        errors.append("summary_token_total_mismatch")
    if (summary_prompt, summary_completion, summary_total) != (prompt_sum, completion_sum, total_sum):
        errors.append("summary_tokens_do_not_match_rows")
    if summary_total <= 0:
        warnings.append("summary_total_tokens_non_positive")

    token_score = max(0.0, min(1.0, (TOKEN_BUDGET - summary_total) / TOKEN_BUDGET))
    return {
        "path": str(path),
        "rows_including_summary": len(rows),
        "question_rows": len(answer_rows),
        "summary_tokens": {
            "prompt_tokens": summary_prompt,
            "completion_tokens": summary_completion,
            "total_tokens": summary_total,
        },
        "row_token_sums": {
            "prompt_tokens": prompt_sum,
            "completion_tokens": completion_sum,
            "total_tokens": total_sum,
        },
        "token_score_if_accuracy_1": token_score,
        "answer_format_errors": answer_format_errors[:100],
    }, errors, warnings


def audit_evidence_json(
    path: Path,
    questions: dict[str, dict[str, Any]],
    answers: dict[str, str],
    allow_partial: bool,
) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.exists():
        return {}, [f"missing_evidence_json:{path}"], warnings
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, [f"invalid_evidence_json:{exc}"], warnings
    if not isinstance(evidence, dict):
        return {}, ["evidence_json_not_object"], warnings

    expected_qids = set(questions)
    evidence_qids = set(str(qid) for qid in evidence)
    missing = sorted(expected_qids - evidence_qids)
    extra = sorted(evidence_qids - expected_qids)
    if missing and not allow_partial:
        errors.append("missing_evidence_qids:" + ",".join(missing[:20]))
    elif missing:
        warnings.append(f"partial_evidence_qids_missing:{len(missing)}")
    if extra:
        errors.append("extra_evidence_qids:" + ",".join(extra[:20]))

    judge_modes = Counter()
    statuses = Counter()
    evidence_count = 0
    empty_evidence_qids: list[str] = []
    answer_mismatches: list[str] = []
    bad_judgement_qids: list[str] = []
    bad_evidence_ids: list[str] = []
    needs_review_qids: list[str] = []

    for qid, row in evidence.items():
        qid = str(qid)
        if not isinstance(row, dict):
            bad_judgement_qids.append(qid)
            continue
        judge_modes[str(row.get("judge_mode") or "")] += 1
        status = str(row.get("status") or "")
        statuses[status] += 1
        if "review" in status:
            needs_review_qids.append(qid)
        if qid in answers and str(row.get("answer") or "") != answers[qid]:
            answer_mismatches.append(qid)
        ev_rows = row.get("evidence") or []
        if not isinstance(ev_rows, list) or not ev_rows:
            empty_evidence_qids.append(qid)
        else:
            evidence_count += len(ev_rows)
            ids = [item.get("evidence_id") for item in ev_rows if isinstance(item, dict)]
            if ids != list(range(1, len(ids) + 1)):
                bad_evidence_ids.append(qid)
        option_judgement = row.get("option_judgement") or {}
        expected_options = set((questions.get(qid) or {}).get("options") or {})
        if not expected_options:
            expected_options = {"A", "B", "C", "D"}
        if not isinstance(option_judgement, dict) or not set(option_judgement).issuperset(expected_options):
            bad_judgement_qids.append(qid)

    if answer_mismatches:
        errors.append("evidence_answer_mismatches:" + ",".join(answer_mismatches[:20]))
    if bad_judgement_qids:
        errors.append("bad_option_judgement:" + ",".join(bad_judgement_qids[:20]))
    if bad_evidence_ids:
        errors.append("bad_evidence_ids:" + ",".join(bad_evidence_ids[:20]))
    if empty_evidence_qids:
        warnings.append("empty_evidence_qids:" + ",".join(empty_evidence_qids[:20]))
    if needs_review_qids:
        warnings.append(f"needs_review_qids:{len(needs_review_qids)}")
    if judge_modes.get("prior_csv"):
        warnings.append("prior_csv_not_official_judgement")

    return {
        "path": str(path),
        "qids": len(evidence_qids),
        "evidence_items": evidence_count,
        "judge_modes": dict(sorted(judge_modes.items())),
        "statuses": dict(sorted(statuses.items())),
        "needs_review_qids": sorted(needs_review_qids),
        "empty_evidence_qids": sorted(empty_evidence_qids),
    }, errors, warnings


def audit_questions_jsonl(path: Path | None) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if path is None or not path.exists():
        return {}, errors, warnings
    rows = iter_jsonl(path)
    statuses = Counter(str(row.get("status") or "") for row in rows)
    warnings_counter = Counter(warning for row in rows for warning in row.get("warnings") or [])
    repair_counter = Counter("repaired" if row.get("repair_log") else "not_repaired" for row in rows)
    return {
        "path": str(path),
        "rows": len(rows),
        "statuses": dict(sorted(statuses.items())),
        "repairs": dict(sorted(repair_counter.items())),
        "top_warnings": dict(warnings_counter.most_common(30)),
    }, errors, warnings


def read_answer_map(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return {
            str(row.get("qid") or ""): str(row.get("answer") or "")
            for row in csv.DictReader(fh)
            if row.get("qid") and row.get("qid") != "summary"
        }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Agent Output Audit",
        "",
        f"- Status: `{report['status']}`",
        f"- Errors: {len(report['errors'])}",
        f"- Warnings: {len(report['warnings'])}",
        "",
        "## Answer CSV",
        "",
        "```json",
        json.dumps(report.get("answer_csv", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Evidence JSON",
        "",
        "```json",
        json.dumps(report.get("evidence_json", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Questions Log",
        "",
        "```json",
        json.dumps(report.get("questions_jsonl", {}), ensure_ascii=False, indent=2),
        "```",
    ]
    if report["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- `{item}`" for item in report["errors"])
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{item}`" for item in report["warnings"])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=None, help="Run directory containing answer/evidence/log files.")
    parser.add_argument("--answer-csv", default=None)
    parser.add_argument("--evidence-json", default=None)
    parser.add_argument("--questions-jsonl", default=None)
    parser.add_argument("--question-bank", default="processed_data/agent_evidence_seed/group_a_all_questions.jsonl")
    parser.add_argument("--report-json", default=None)
    parser.add_argument("--report-md", default=None)
    parser.add_argument("--allow-needs-review", action="store_true")
    parser.add_argument("--allow-prior-csv", action="store_true")
    parser.add_argument("--allow-partial", action="store_true", help="Allow smoke/subset runs that do not cover the full question bank.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else None
    answer_csv = Path(args.answer_csv) if args.answer_csv else (run_dir / "answer.csv" if run_dir else None)
    evidence_json = Path(args.evidence_json) if args.evidence_json else (run_dir / "evidence.json" if run_dir else None)
    questions_jsonl = Path(args.questions_jsonl) if args.questions_jsonl else (run_dir / "questions.jsonl" if run_dir else None)
    if answer_csv is None or evidence_json is None:
        raise SystemExit("--run-dir or both --answer-csv/--evidence-json are required")

    questions = load_questions(Path(args.question_bank))
    errors: list[str] = []
    warnings: list[str] = []
    answer_report, answer_errors, answer_warnings = audit_answer_csv(answer_csv, questions, allow_partial=args.allow_partial)
    errors.extend(answer_errors)
    warnings.extend(answer_warnings)
    answers = read_answer_map(answer_csv) if answer_csv.exists() else {}
    evidence_report, evidence_errors, evidence_warnings = audit_evidence_json(evidence_json, questions, answers, allow_partial=args.allow_partial)
    errors.extend(evidence_errors)
    warnings.extend(evidence_warnings)
    questions_report, q_errors, q_warnings = audit_questions_jsonl(questions_jsonl)
    errors.extend(q_errors)
    warnings.extend(q_warnings)

    if not args.allow_needs_review and any(item.startswith("needs_review_qids:") for item in warnings):
        errors.append("needs_review_present_without_allow_needs_review")
    if not args.allow_prior_csv and "prior_csv_not_official_judgement" in warnings:
        errors.append("prior_csv_present_without_allow_prior_csv")

    report = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "question_bank": str(Path(args.question_bank)),
        "answer_csv": answer_report,
        "evidence_json": evidence_report,
        "questions_jsonl": questions_report,
    }
    report_json = Path(args.report_json) if args.report_json else (run_dir / "audit_report.json" if run_dir else Path("audit_report.json"))
    report_md = Path(args.report_md) if args.report_md else report_json.with_suffix(".md")
    write_json(report_json, report)
    report_md.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "errors": len(errors), "warnings": len(warnings), "report": str(report_json)}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
