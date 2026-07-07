#!/usr/bin/env python3
"""Plan MinerU jobs for question-linked PDFs.

The reference MinerU wrapper auto-splits PDFs over 200 pages by physically
creating part PDFs. Some AFAC PDFs expand from a few MB to >1GB after physical
splitting, which violates MinerU's 200MB upload limit. This planner keeps the
simple path for PDFs with <=200 pages and creates logical page-range jobs for
long PDFs so they can be submitted with MinerU's `page_ranges` parameter.
"""

from __future__ import annotations

import argparse
import json
import os
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


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def stage_link(source: Path, target: Path, force: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if not force:
            return
        target.unlink()
    os.symlink(source.resolve(), target)


def clear_stage(stage_dir: Path) -> None:
    if not stage_dir.exists():
        return
    for path in stage_dir.iterdir():
        if path.is_file() or path.is_symlink():
            path.unlink()


def load_page_counts(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path) or []:
        out[str(row.get("staged_pdf_name") or "")] = row
    return out


def range_rows(row: dict[str, Any], pages: int, max_pages: int) -> list[dict[str, Any]]:
    staged_name = str(row.get("staged_pdf_name") or Path(str(row.get("staged_pdf_path") or "")).name)
    stem = Path(staged_name).stem
    rows: list[dict[str, Any]] = []
    for index, start in enumerate(range(1, pages + 1, max_pages), start=1):
        end = min(start + max_pages - 1, pages)
        part_stem = f"{stem}_part{index:03d}_p{start:03d}-{end:03d}"
        rows.append(
            {
                "domain": row.get("domain"),
                "doc_id": row.get("doc_id"),
                "staged_pdf_name": staged_name,
                "staged_pdf_path": row.get("staged_pdf_path"),
                "mineru_result_dir": row.get("mineru_result_dir"),
                "pages": pages,
                "range_start": start,
                "range_end": end,
                "page_ranges": f"{start}-{end}",
                "part_index": index,
                "part_stem": part_stem,
                "part_pdf_name": f"{part_stem}.pdf",
                "expected_result_dir": str(Path(str(row.get("mineru_result_dir") or "")).parent / part_stem),
            }
        )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-manifest", default="processed_data/manifests/group_a_question_pdfs.jsonl")
    parser.add_argument("--page-counts", default="processed_data/reports/group_a_pdf_page_counts.jsonl")
    parser.add_argument("--under200-stage-dir", default="processed_data/mineru_input/group_a_question_pdfs_under200")
    parser.add_argument("--smoke-stage-dir", default="processed_data/mineru_input/group_a_question_pdfs_smoke")
    parser.add_argument("--out-dir", default="processed_data/manifests")
    parser.add_argument("--split-name", default="group_a")
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--smoke-count", type=int, default=3)
    parser.add_argument("--force", action="store_true", help="Replace staged symlinks.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pdf_manifest = Path(args.pdf_manifest).expanduser().resolve()
    page_counts_path = Path(args.page_counts).expanduser().resolve()
    under_stage = Path(args.under200_stage_dir).expanduser().resolve()
    smoke_stage = Path(args.smoke_stage_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    pdf_rows = list(iter_jsonl(pdf_manifest) or [])
    page_counts = load_page_counts(page_counts_path)
    direct_rows: list[dict[str, Any]] = []
    range_job_rows: list[dict[str, Any]] = []
    missing_page_counts: list[dict[str, Any]] = []

    if args.force:
        clear_stage(under_stage)
        clear_stage(smoke_stage)

    for row in pdf_rows:
        staged_path = Path(str(row.get("staged_pdf_path") or "")).expanduser()
        staged_name = str(row.get("staged_pdf_name") or staged_path.name)
        page_row = page_counts.get(staged_name)
        if not page_row:
            missing_page_counts.append(row)
            continue
        pages = int(page_row.get("pages") or 0)
        merged = {**row, **page_row, "pages": pages}
        if pages <= args.max_pages:
            direct_rows.append(merged)
            stage_link(staged_path, under_stage / staged_name, force=args.force)
        else:
            range_job_rows.extend(range_rows(merged, pages, args.max_pages))

    for row in sorted(direct_rows, key=lambda item: (int(item.get("pages") or 0), str(item.get("staged_pdf_name"))))[: args.smoke_count]:
        staged_path = Path(str(row.get("staged_pdf_path") or "")).expanduser()
        stage_link(staged_path, smoke_stage / str(row.get("staged_pdf_name")), force=args.force)

    prefix = args.split_name
    direct_manifest = out_dir / f"{prefix}_mineru_direct_under200.jsonl"
    range_manifest = out_dir / f"{prefix}_mineru_range_jobs.jsonl"
    missing_manifest = out_dir / f"{prefix}_mineru_missing_page_counts.jsonl"
    write_jsonl(direct_manifest, direct_rows)
    write_jsonl(range_manifest, range_job_rows)
    write_jsonl(missing_manifest, missing_page_counts)

    summary = {
        "tool": "02_plan_mineru_jobs.py",
        "pdf_manifest": str(pdf_manifest),
        "page_counts": str(page_counts_path),
        "max_pages": args.max_pages,
        "pdf_docs": len(pdf_rows),
        "direct_under200_docs": len(direct_rows),
        "direct_under200_pages": sum(int(row.get("pages") or 0) for row in direct_rows),
        "range_docs": len({(row.get("domain"), row.get("doc_id")) for row in range_job_rows}),
        "range_jobs": len(range_job_rows),
        "range_pages": sum(int(row.get("range_end") or 0) - int(row.get("range_start") or 0) + 1 for row in range_job_rows),
        "missing_page_count_docs": len(missing_page_counts),
        "under200_stage_dir": str(under_stage),
        "smoke_stage_dir": str(smoke_stage),
        "outputs": {
            "direct_under200": str(direct_manifest),
            "range_jobs": str(range_manifest),
            "missing_page_counts": str(missing_manifest),
            "summary": str(out_dir / f"{prefix}_mineru_job_plan_summary.json"),
        },
        "recommended_commands": {
            "smoke": f"python script/02_run_mineru_question_pdfs.py --pdf-folder {smoke_stage} --chunk-size 1 --timeout 3600",
            "under200": f"python script/02_run_mineru_question_pdfs.py --pdf-folder {under_stage} --chunk-size 5 --timeout 7200",
            "range_one_doc": f"python script/02_run_mineru_range_jobs.py --only-doc <doc_id> --limit 1",
        },
    }
    write_json(out_dir / f"{prefix}_mineru_job_plan_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not missing_page_counts else 1


if __name__ == "__main__":
    raise SystemExit(main())
