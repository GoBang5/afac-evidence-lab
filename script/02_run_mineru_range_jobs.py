#!/usr/bin/env python3
"""Run long-PDF MinerU page-range jobs.

Each job uploads the original compressed PDF and asks MinerU to parse a logical
page range. This avoids the >200MB files created by physical PDF splitting.
Completed part outputs are summarized into the original document's canonical
MinerU result directory so `03_build_mineru_ir.py` can merge them.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable


DEFAULT_BATCH_SCRIPT = "/public/home/zhangfanjin/zhangnianhao/01-projects/UniDoc-RL/tools/mineru_batch_parse.py"
DEFAULT_ENV = "/public/home/zhangfanjin/zhangnianhao/.env"


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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def env_has_key(path: Path, key: str) -> bool:
    if os.environ.get(key):
        return True
    if not path.exists():
        return False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key and value.strip().strip('"').strip("'"):
            return True
    return False


def has_content_list(result_dir: Path) -> bool:
    return bool(list(result_dir.glob("*_content_list.json")) or list(result_dir.glob("*_content_list_v2.json")))


def part_done(result_dir: Path) -> bool:
    result_path = result_dir / "result.json"
    if not result_path.exists():
        return False
    try:
        result = read_json(result_path)
    except json.JSONDecodeError:
        return False
    return result.get("state") == "done" and has_content_list(result_dir) and (result_dir / "full.md").exists()


def stage_part_input(source_pdf: Path, input_dir: Path, part_pdf_name: str, force: bool) -> Path:
    input_dir.mkdir(parents=True, exist_ok=True)
    target = input_dir / part_pdf_name
    if target.exists() or target.is_symlink():
        if force:
            target.unlink()
        else:
            return target
    os.symlink(source_pdf.resolve(), target)
    return target


def command_for_job(args: argparse.Namespace, input_dir: Path, page_ranges: str) -> list[str]:
    cmd = [
        sys.executable,
        str(Path(args.batch_script).expanduser().resolve()),
        str(input_dir),
        "--env",
        str(Path(args.env).expanduser().resolve()),
        "--chunk-size",
        "1",
        "--language",
        args.language,
        "--page-ranges",
        page_ranges,
        "--no-auto-split",
        "--interval",
        str(args.interval),
        "--timeout",
        str(args.timeout),
    ]
    if args.ocr:
        cmd.append("--ocr")
    if args.force:
        cmd.append("--force")
    return cmd


def grouped_jobs(jobs: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for job in jobs:
        key = (str(job.get("domain") or ""), str(job.get("doc_id") or ""))
        grouped.setdefault(key, []).append(job)
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row.get("part_index") or 0))
    return grouped


def link_parent_part(parent_dir: Path, part_dir: Path) -> None:
    if not part_dir.exists():
        return
    parts_root = parent_dir / "parts"
    parts_root.mkdir(parents=True, exist_ok=True)
    target = parts_root / part_dir.name
    if target.exists() or target.is_symlink():
        try:
            if target.resolve() == part_dir.resolve():
                return
        except FileNotFoundError:
            pass
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    os.symlink(part_dir.resolve(), target, target_is_directory=True)


def synthesize_parent(job_group: list[dict[str, Any]], output_root: Path) -> dict[str, Any]:
    first = job_group[0]
    parent_dir = Path(str(first.get("mineru_result_dir") or "")).expanduser().resolve()
    parent_dir.mkdir(parents=True, exist_ok=True)
    part_records: list[dict[str, Any]] = []
    merged_markdown: list[str] = []

    terminal_count = 0
    failed_count = 0
    done_count = 0
    for job in job_group:
        part_dir = output_root / str(job.get("part_stem"))
        result_path = part_dir / "result.json"
        state = "missing"
        err_msg = ""
        if result_path.exists():
            try:
                result = read_json(result_path)
                state = str(result.get("state") or "unknown")
                err_msg = str(result.get("err_msg") or result.get("error") or "")
            except json.JSONDecodeError as exc:
                state = "failed"
                err_msg = f"bad result.json: {exc}"
        if state in {"done", "failed"}:
            terminal_count += 1
        if state == "failed":
            failed_count += 1
        if state == "done" and has_content_list(part_dir):
            link_parent_part(parent_dir, part_dir)
            done_count += 1
            full_md = part_dir / "full.md"
            if full_md.exists():
                merged_markdown.append(
                    f"\n\n<!-- MinerU page range {job.get('page_ranges')}: {job.get('part_pdf_name')} -->\n\n"
                    + full_md.read_text(encoding="utf-8", errors="replace")
                )
        part_records.append(
            {
                "name": job.get("part_pdf_name"),
                "output": str(part_dir),
                "state": state,
                "page_ranges": job.get("page_ranges"),
                "range_start": job.get("range_start"),
                "range_end": job.get("range_end"),
                "err_msg": err_msg,
            }
        )

    if done_count == len(job_group):
        state = "done"
        (parent_dir / "full.md").write_text("".join(merged_markdown).lstrip(), encoding="utf-8")
    elif failed_count and terminal_count == len(job_group):
        state = "failed"
    else:
        state = "partial"

    result = {
        "state": state,
        "split": True,
        "range_split": True,
        "source_file": first.get("staged_pdf_path"),
        "reason": f"source PDF exceeded page limit; parsed with MinerU page_ranges into {len(job_group)} part(s)",
        "parts": part_records,
    }
    write_json(parent_dir / "result.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", default="processed_data/manifests/group_a_mineru_range_jobs.jsonl")
    parser.add_argument("--env", default=DEFAULT_ENV)
    parser.add_argument("--batch-script", default=DEFAULT_BATCH_SCRIPT)
    parser.add_argument("--input-root", default="processed_data/mineru_input")
    parser.add_argument("--output-root", default="processed_data/mineru_input/mineru")
    parser.add_argument("--language", default="ch")
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--interval", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--limit", type=int, default=0, help="Maximum jobs to submit in this run; 0 means all selected jobs.")
    parser.add_argument("--only-doc", action="append", default=[], help="Restrict to one or more doc_id values.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--clean-input", action="store_true", help="Remove temporary range input folders after successful jobs.")
    parser.add_argument("--synthesize-only", action="store_true", help="Only rebuild parent result.json files from existing part outputs.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    jobs_path = Path(args.jobs).expanduser().resolve()
    input_root = Path(args.input_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    env_path = Path(args.env).expanduser().resolve()
    batch_script = Path(args.batch_script).expanduser().resolve()
    if not jobs_path.exists():
        print(f"missing jobs file: {jobs_path}", file=sys.stderr)
        return 2
    if not batch_script.exists():
        print(f"missing MinerU batch script: {batch_script}", file=sys.stderr)
        return 2
    if not env_has_key(env_path, "MINERU_API_KEY") and not args.dry_run and not args.synthesize_only:
        print("MINERU_API_KEY is missing in environment/.env; not calling MinerU.", file=sys.stderr)
        return 2

    jobs = list(iter_jsonl(jobs_path) or [])
    if args.only_doc:
        wanted = set(args.only_doc)
        jobs = [job for job in jobs if str(job.get("doc_id") or "") in wanted]

    selected: list[dict[str, Any]] = []
    submitted = 0
    skipped = 0
    failed = 0
    for job in jobs:
        part_stem = str(job.get("part_stem") or "")
        part_dir = output_root / part_stem
        if not args.force and part_done(part_dir):
            skipped += 1
            continue
        selected.append(job)
        if args.limit and len(selected) >= args.limit:
            break

    summary = {
        "jobs_file": str(jobs_path),
        "available_jobs": len(jobs),
        "selected_jobs": len(selected),
        "skipped_done": skipped,
        "output_root": str(output_root),
        "dry_run": args.dry_run,
        "synthesize_only": args.synthesize_only,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    if not args.synthesize_only:
        for job in selected:
            source_pdf = Path(str(job.get("staged_pdf_path") or "")).expanduser().resolve()
            if not source_pdf.exists():
                print(f"missing source PDF: {source_pdf}", file=sys.stderr)
                failed += 1
                continue
            part_stem = str(job.get("part_stem") or "")
            input_dir = input_root / f"range_input__{part_stem}"
            stage_part_input(source_pdf, input_dir, str(job.get("part_pdf_name")), force=True)
            cmd = command_for_job(args, input_dir, str(job.get("page_ranges") or ""))
            print(json.dumps({"job": job, "cmd": cmd, "dry_run": args.dry_run}, ensure_ascii=False), flush=True)
            if args.dry_run:
                continue
            code = subprocess.run(cmd, check=False).returncode
            state = "done" if code == 0 and part_done(output_root / part_stem) else "failed"
            if code == 0:
                submitted += 1
            else:
                failed += 1
            append_jsonl(
                output_root / "range_manifest.jsonl",
                {
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "state": state,
                    "returncode": code,
                    "job": job,
                    "input_dir": str(input_dir),
                    "output": str(output_root / part_stem),
                },
            )
            if args.clean_input and state == "done":
                shutil.rmtree(input_dir, ignore_errors=True)

    grouped = grouped_jobs(jobs)
    parent_results: list[dict[str, Any]] = []
    selected_keys = {(str(job.get("domain") or ""), str(job.get("doc_id") or "")) for job in selected}
    only_doc_set = set(args.only_doc)
    for (domain, doc_id), rows in grouped.items():
        if args.dry_run:
            continue
        if args.only_doc and doc_id not in only_doc_set:
            continue
        if not args.synthesize_only and selected_keys and (domain, doc_id) not in selected_keys:
            continue
        if not args.synthesize_only and not selected_keys and not args.only_doc:
            continue
        parent_results.append(
            {
                "domain": rows[0].get("domain"),
                "doc_id": rows[0].get("doc_id"),
                "result": synthesize_parent(rows, output_root),
            }
        )

    final = {
        **summary,
        "submitted_ok": submitted,
        "failed_submissions": failed,
        "parent_results": parent_results,
    }
    print(json.dumps(final, ensure_ascii=False, indent=2), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
