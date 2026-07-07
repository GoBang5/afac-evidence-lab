#!/usr/bin/env python3
"""Prepare question-linked source manifests and a MinerU PDF input folder.

The A split questions reference stable `doc_ids`. This script resolves those
ids to files under `data/raw`, writes auditable manifests, and stages only the
PDF files that are actually used by questions into one folder for MinerU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any


PDF_SUFFIXES = {".pdf"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("._-")
    if not text:
        text = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return text[:160]


def first_existing(candidates: list[Path]) -> Path | None:
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def case_insensitive_lookup(folder: Path, stem: str) -> Path | None:
    if not folder.exists():
        return None
    wanted = stem.lower()
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.stem.lower() == wanted:
            return path
    return None


def resolve_source(raw_root: Path, domain: str, doc_id: str) -> tuple[Path | None, str]:
    if domain == "insurance":
        path = raw_root / "insurance" / f"{doc_id}.pdf"
        return (path if path.exists() else None), "insurance_pdf"
    if domain == "financial_contracts":
        path = raw_root / "financial_contracts" / f"{doc_id}.pdf"
        return (path if path.exists() else None), "financial_contract_pdf"
    if domain == "research":
        path = raw_root / "research" / f"{doc_id}.pdf"
        return (path if path.exists() else None), "research_pdf"
    if domain == "financial_reports":
        folder = raw_root / "financial_reports"
        path = first_existing(
            [
                folder / f"{doc_id}.pdf",
                folder / f"{doc_id}.PDF",
            ]
        )
        return (path or case_insensitive_lookup(folder, doc_id)), "financial_report_pdf"
    if domain == "regulatory":
        if doc_id.startswith("strict_v3_"):
            path = raw_root / "regulatory" / "txt" / f"{doc_id}.txt"
            return (path if path.exists() else None), "regulatory_txt"
        if re.search(r"_att\d+$", doc_id):
            path = raw_root / "regulatory" / "attachments" / f"{doc_id}.pdf"
            return (path if path.exists() else None), "regulatory_attachment_pdf"
        path = raw_root / "regulatory" / "html" / f"{doc_id}.html"
        return (path if path.exists() else None), "regulatory_html"
    return None, "unknown"


def load_question_refs(questions_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    refs: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(questions_dir.glob("*_questions.json")):
        questions = read_json(path)
        for q in questions:
            domain = str(q.get("domain") or "")
            qid = str(q.get("qid") or "")
            for doc_id in q.get("doc_ids") or []:
                key = (domain, str(doc_id))
                row = refs.setdefault(
                    key,
                    {
                        "domain": domain,
                        "doc_id": str(doc_id),
                        "question_ids": [],
                        "question_types": [],
                        "answer_formats": [],
                        "question_files": [],
                    },
                )
                row["question_ids"].append(qid)
                row["question_types"].append(q.get("type") or "")
                row["answer_formats"].append(q.get("answer_format") or "")
                row["question_files"].append(path.name)
    for row in refs.values():
        for key in ("question_ids", "question_types", "answer_formats", "question_files"):
            row[key] = sorted(set(str(item) for item in row[key] if item is not None))
        row["question_count"] = len(row["question_ids"])
    return refs


def stage_pdf(source: Path, target: Path, copy: bool, force: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if not force:
            return
        target.unlink()
    if copy:
        shutil.copy2(source, target)
    else:
        os.symlink(source.resolve(), target)


def make_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    raw_root = Path(args.raw_root).expanduser().resolve()
    refs = load_question_refs(Path(args.questions_dir).expanduser().resolve())
    pdf_stage_dir = Path(args.pdf_stage_dir).expanduser().resolve()
    manifest_rows: list[dict[str, Any]] = []
    pdf_rows: list[dict[str, Any]] = []
    non_pdf_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    used_stage_names: set[str] = set()

    for (domain, doc_id), ref in sorted(refs.items()):
        source, source_kind = resolve_source(raw_root, domain, doc_id)
        base = {
            **ref,
            "source_kind": source_kind,
            "source_path": str(source) if source else "",
            "source_exists": bool(source),
        }
        if not source:
            missing_rows.append(base)
            manifest_rows.append({**base, "is_pdf": False, "staged_pdf_path": ""})
            continue

        suffix = source.suffix.lower()
        size = source.stat().st_size
        row = {
            **base,
            "source_suffix": suffix,
            "file_size": size,
            "is_pdf": suffix in PDF_SUFFIXES,
        }
        if args.hash:
            row["sha256"] = sha256_file(source)

        if row["is_pdf"]:
            safe_doc = safe_name(doc_id)
            stage_name = f"{domain}__{safe_doc}.pdf"
            if stage_name in used_stage_names:
                stage_name = f"{domain}__{safe_doc}__{hashlib.sha1(doc_id.encode()).hexdigest()[:8]}.pdf"
            used_stage_names.add(stage_name)
            stage_path = pdf_stage_dir / stage_name
            stage_pdf(source, stage_path, copy=args.copy, force=args.force)
            row.update(
                {
                    "staged_pdf_name": stage_name,
                    "staged_pdf_path": str(stage_path),
                    "mineru_result_dir": str(pdf_stage_dir.parent / "mineru" / stage_path.stem),
                }
            )
            pdf_rows.append(row)
        else:
            row["staged_pdf_path"] = ""
            non_pdf_rows.append(row)
        manifest_rows.append(row)

    return manifest_rows, pdf_rows, non_pdf_rows, missing_rows


def write_markdown(path: Path, summary: dict[str, Any], missing_rows: list[dict[str, Any]]) -> None:
    lines = [
        "# AFAC Question Source Preparation",
        "",
        f"- Documents referenced by questions: {summary['docs_total']}",
        f"- PDF documents staged for MinerU: {summary['pdf_docs']}",
        f"- Non-PDF documents: {summary['non_pdf_docs']}",
        f"- Missing documents: {summary['missing_docs']}",
        f"- PDF stage dir: `{summary['pdf_stage_dir']}`",
        "",
        "By domain:",
        "",
    ]
    for domain, row in sorted(summary["by_domain"].items()):
        lines.append(f"- `{domain}`: total={row['total']} pdf={row['pdf']} non_pdf={row['non_pdf']} missing={row['missing']}")
    if missing_rows:
        lines.extend(["", "Missing:", ""])
        for row in missing_rows:
            lines.append(f"- `{row['domain']}` `{row['doc_id']}` kind={row['source_kind']}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions-dir", default="data/questions/group_a")
    parser.add_argument("--raw-root", default="data/raw")
    parser.add_argument("--out-dir", default="processed_data/manifests")
    parser.add_argument("--pdf-stage-dir", default="processed_data/mineru_input/group_a_question_pdfs")
    parser.add_argument("--split-name", default="group_a")
    parser.add_argument("--copy", action="store_true", help="Copy PDFs instead of creating symlinks.")
    parser.add_argument("--force", action="store_true", help="Replace existing staged files/symlinks.")
    parser.add_argument("--hash", action="store_true", help="Compute SHA256 for source files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    pdf_stage_dir = Path(args.pdf_stage_dir).expanduser().resolve()
    manifest_rows, pdf_rows, non_pdf_rows, missing_rows = make_rows(args)

    prefix = args.split_name
    write_jsonl(out_dir / f"{prefix}_question_docs.jsonl", manifest_rows)
    write_jsonl(out_dir / f"{prefix}_question_pdfs.jsonl", pdf_rows)
    write_jsonl(out_dir / f"{prefix}_question_nonpdf.jsonl", non_pdf_rows)
    write_jsonl(out_dir / f"{prefix}_question_missing.jsonl", missing_rows)

    by_domain: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "pdf": 0, "non_pdf": 0, "missing": 0})
    for row in manifest_rows:
        dom = row["domain"]
        by_domain[dom]["total"] += 1
        if not row["source_exists"]:
            by_domain[dom]["missing"] += 1
        elif row["is_pdf"]:
            by_domain[dom]["pdf"] += 1
        else:
            by_domain[dom]["non_pdf"] += 1

    summary = {
        "split_name": args.split_name,
        "docs_total": len(manifest_rows),
        "pdf_docs": len(pdf_rows),
        "non_pdf_docs": len(non_pdf_rows),
        "missing_docs": len(missing_rows),
        "pdf_stage_dir": str(pdf_stage_dir),
        "stage_mode": "copy" if args.copy else "symlink",
        "by_domain": dict(by_domain),
        "outputs": {
            "question_docs": str(out_dir / f"{prefix}_question_docs.jsonl"),
            "question_pdfs": str(out_dir / f"{prefix}_question_pdfs.jsonl"),
            "question_nonpdf": str(out_dir / f"{prefix}_question_nonpdf.jsonl"),
            "question_missing": str(out_dir / f"{prefix}_question_missing.jsonl"),
        },
    }
    write_json(out_dir / f"{prefix}_question_sources_summary.json", summary)
    write_markdown(out_dir / f"{prefix}_question_sources_summary.md", summary, missing_rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not missing_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
