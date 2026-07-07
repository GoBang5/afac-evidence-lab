#!/usr/bin/env python3
"""Audit AFAC preprocessed outputs for coverage and retrieval readiness."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
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
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_no}: {exc}") from exc
            if isinstance(obj, dict):
                yield obj


def read_questions(questions_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(questions_dir.glob("*_questions.json")):
        questions = json.loads(path.read_text(encoding="utf-8"))
        for q in questions:
            rows.append({**q, "_question_file": path.name})
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# AFAC Preprocessed Output Audit",
        "",
        f"- Docs: {report['docs']['count']}",
        f"- Chunks: {report['chunks']['count']}",
        f"- Tables: {report['tables']['count']}",
        f"- PDF docs expected/missing IR: {report['pdf_ir']['expected']}/{report['pdf_ir']['missing_count']}",
        f"- Question coverage: {report['question_coverage']['covered_questions']}/{report['question_coverage']['total_questions']}",
        f"- Orphan chunks/tables: {report['chunks']['orphan_count']}/{report['tables']['orphan_count']}",
        f"- Negative number tokens: {report['chunks']['negative_number_token_count']}",
        f"- Suspicious negative number tokens: {report['chunks']['suspicious_negative_number_token_count']}",
        "",
        "By domain:",
        "",
    ]
    for domain, row in sorted(report["by_domain"].items()):
        lines.append(
            f"- `{domain}` docs={row['docs']} chunks={row['chunks']} tables={row['tables']} "
            f"questions={row['questions']} covered={row['covered_questions']}"
        )
    if report["pdf_ir"]["missing_doc_ids"]:
        lines.extend(["", "Missing PDF IR doc_ids:", ""])
        for doc_id in report["pdf_ir"]["missing_doc_ids"][:120]:
            lines.append(f"- `{doc_id}`")
    if report["warnings"]:
        lines.extend(["", "Warnings:", ""])
        for warning in report["warnings"]:
            lines.append(f"- {warning}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-root", default="processed_data")
    parser.add_argument("--questions-dir", default="data/questions/group_a")
    parser.add_argument("--manifest", default="processed_data/manifests/group_a_question_docs.jsonl")
    parser.add_argument("--output", default="processed_data/reports/group_a_preprocessed_audit.json")
    parser.add_argument("--markdown", default="processed_data/reports/group_a_preprocessed_audit.md")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if critical warnings exist.")
    return parser.parse_args()


def suspicious_negative_token(row: dict[str, Any], token: str) -> bool:
    text = str(row.get("text") or "")
    index = text.find(token)
    if index < 0:
        return True
    prefix = text[:index].rstrip()
    return bool(re.search(r"\d\s*[^，,。；;：:\s]{0,8}$", prefix))


def main() -> int:
    args = parse_args()
    root = Path(args.processed_root).expanduser().resolve()
    docs = list(iter_jsonl(root / "docs.jsonl") or [])
    chunks = list(iter_jsonl(root / "chunks.jsonl") or [])
    tables = list(iter_jsonl(root / "tables.jsonl") or [])
    manifest = list(iter_jsonl(Path(args.manifest).expanduser().resolve()) or [])
    questions = read_questions(Path(args.questions_dir).expanduser().resolve())

    doc_ids = {str(row.get("doc_id")) for row in docs}
    chunk_doc_ids = {str(row.get("doc_id")) for row in chunks}
    table_doc_ids = {str(row.get("doc_id")) for row in tables}
    manifest_by_doc = {str(row.get("doc_id")): row for row in manifest}
    pdf_doc_ids = sorted(doc_id for doc_id, row in manifest_by_doc.items() if row.get("is_pdf"))
    docs_missing_ir = sorted(
        doc_id
        for doc_id in pdf_doc_ids
        if not next((row for row in docs if str(row.get("doc_id")) == doc_id and row.get("parser") != "missing_ir"), None)
    )

    q_doc_ids = {q["qid"]: [str(doc_id) for doc_id in q.get("doc_ids") or []] for q in questions}
    covered_questions = [
        qid
        for qid, refs in q_doc_ids.items()
        if any(doc_id in chunk_doc_ids or doc_id in table_doc_ids for doc_id in refs)
    ]

    by_domain: dict[str, dict[str, int]] = defaultdict(lambda: {"docs": 0, "chunks": 0, "tables": 0, "questions": 0, "covered_questions": 0})
    for row in docs:
        by_domain[str(row.get("domain"))]["docs"] += 1
    for row in chunks:
        by_domain[str(row.get("domain"))]["chunks"] += 1
    for row in tables:
        by_domain[str(row.get("domain"))]["tables"] += 1
    for q in questions:
        domain = str(q.get("domain"))
        by_domain[domain]["questions"] += 1
        if q["qid"] in covered_questions:
            by_domain[domain]["covered_questions"] += 1

    negative_tokens = [
        {"chunk_id": row.get("chunk_id"), "token": token, "suspicious": suspicious_negative_token(row, str(token))}
        for row in chunks
        for token in (row.get("numbers") or [])
        if str(token).startswith("-")
    ]
    suspicious_negative_tokens = [row for row in negative_tokens if row.get("suspicious")]
    orphan_chunks = [row.get("chunk_id") for row in chunks if str(row.get("doc_id")) not in doc_ids]
    orphan_tables = [row.get("table_id") for row in tables if str(row.get("doc_id")) not in doc_ids]

    warnings: list[str] = []
    if docs_missing_ir:
        warnings.append(f"{len(docs_missing_ir)} expected PDF docs still have missing MinerU IR.")
    if pdf_doc_ids and not any(str(row.get("doc_id")) in pdf_doc_ids for row in chunks):
        warnings.append("No PDF chunks are available yet.")
    if pdf_doc_ids and not tables:
        warnings.append("No tables are available yet.")
    if orphan_chunks:
        warnings.append(f"{len(orphan_chunks)} chunks reference doc_ids absent from docs.jsonl.")
    if orphan_tables:
        warnings.append(f"{len(orphan_tables)} tables reference doc_ids absent from docs.jsonl.")
    if suspicious_negative_tokens:
        warnings.append(f"{len(suspicious_negative_tokens)} suspicious negative number tokens found.")

    report = {
        "tool": "05_audit_preprocessed_outputs.py",
        "docs": {
            "count": len(docs),
            "by_parser": dict(Counter(str(row.get("parser")) for row in docs)),
        },
        "chunks": {
            "count": len(chunks),
            "by_source_type": dict(Counter(str(row.get("source_type")) for row in chunks)),
            "by_unit_type": dict(Counter(str(row.get("unit_type")) for row in chunks)),
            "orphan_count": len(orphan_chunks),
            "orphan_samples": orphan_chunks[:20],
            "negative_number_token_count": len(negative_tokens),
            "negative_number_token_samples": negative_tokens[:20],
            "suspicious_negative_number_token_count": len(suspicious_negative_tokens),
            "suspicious_negative_number_token_samples": suspicious_negative_tokens[:20],
        },
        "tables": {
            "count": len(tables),
            "orphan_count": len(orphan_tables),
            "orphan_samples": orphan_tables[:20],
        },
        "pdf_ir": {
            "expected": len(pdf_doc_ids),
            "missing_count": len(docs_missing_ir),
            "missing_doc_ids": docs_missing_ir,
        },
        "question_coverage": {
            "total_questions": len(questions),
            "covered_questions": len(covered_questions),
            "covered_qids": sorted(covered_questions),
        },
        "by_domain": dict(by_domain),
        "warnings": warnings,
    }
    write_json(Path(args.output).expanduser().resolve(), report)
    write_markdown(Path(args.markdown).expanduser().resolve(), report)
    print(json.dumps({"docs": len(docs), "chunks": len(chunks), "tables": len(tables), "warnings": warnings}, ensure_ascii=False, indent=2))
    return 1 if args.strict and warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
