#!/usr/bin/env python3
"""Normalize MinerU outputs into DocPreprocess IR.

This script imports the shared DocPreprocess `normalize_mineru_result.py`
normalizer. It also handles MinerU split outputs by normalizing each part with
the correct page offset and merging them into one document-level IR.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable


DEFAULT_NORMALIZER = "/public/home/zhangfanjin/zhangnianhao/01-projects/DocPreprocess/scripts/normalize_mineru_result.py"


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


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def load_normalizer(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("docpreprocess_normalize_mineru_result", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import normalizer from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def has_content_list(result_dir: Path) -> bool:
    return bool(list(result_dir.glob("*_content_list.json")) or list(result_dir.glob("*_content_list_v2.json")))


def part_page_offset(part_dir: Path, fallback_index: int) -> int:
    match = re.search(r"_p(\d+)-(\d+)", part_dir.name)
    if not match:
        return 0
    return max(0, int(match.group(1)) - 1)


def augment_document(ir_dir: Path, manifest_row: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    doc_path = ir_dir / "document.json"
    doc = read_json(doc_path)
    doc.update(
        {
            "domain": manifest_row.get("domain"),
            "source_path": manifest_row.get("source_path"),
            "staged_pdf_path": manifest_row.get("staged_pdf_path"),
            "source_kind": manifest_row.get("source_kind"),
            "question_ids": manifest_row.get("question_ids") or [],
            "question_count": manifest_row.get("question_count") or 0,
            "answer_formats": manifest_row.get("answer_formats") or [],
            "competition_split": "group_a",
        }
    )
    if extra:
        doc.update(extra)
    write_json(doc_path, doc)
    return doc


def normalize_single(normalizer: Any, result_dir: Path, ir_dir: Path, doc_id: str, row: dict[str, Any], page_offset: int = 0) -> dict[str, Any]:
    if ir_dir.exists():
        shutil.rmtree(ir_dir)
    normalizer.normalize(result_dir, ir_dir, doc_id=doc_id, page_offset=page_offset)
    return augment_document(ir_dir, row)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path) or [])


def prefix_asset_path(part_name: str, value: Any) -> Any:
    if not value or not isinstance(value, str):
        return value
    if value.startswith("/") or value.startswith("parts/"):
        return value
    return f"parts/{part_name}/{value}"


def rewrite_repair_refs(value: Any, object_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return object_map.get(value, value)
    if isinstance(value, list):
        return [rewrite_repair_refs(item, object_map) for item in value]
    if isinstance(value, dict):
        out = dict(value)
        for key in ("from_id", "to_id", "caption_repaired_from", "caption_repaired_to"):
            if key in out:
                out[key] = rewrite_repair_refs(out[key], object_map)
        return out
    return value


def rewrite_row(
    row: dict[str, Any],
    part_name: str,
    prefix: str,
    block_map: dict[str, str],
    section_map: dict[str, str],
    table_map: dict[str, str] | None = None,
    visual_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    out = dict(row)
    if out.get("block_id") in block_map:
        out["block_id"] = block_map[str(out["block_id"])]
    if out.get("section_id") in section_map:
        out["section_id"] = section_map[str(out["section_id"])]
    if out.get("parent_section_id") in section_map:
        out["parent_section_id"] = section_map[str(out["parent_section_id"])]
    if table_map and out.get("table_id") in table_map:
        out["table_id"] = table_map[str(out["table_id"])]
    if visual_map and out.get("visual_id") in visual_map:
        out["visual_id"] = visual_map[str(out["visual_id"])]
    object_map = {}
    if table_map:
        object_map.update(table_map)
    if visual_map:
        object_map.update(visual_map)
    if object_map:
        for key in ("caption_repaired_from", "caption_repaired_to"):
            if key in out:
                out[key] = rewrite_repair_refs(out[key], object_map)
        if "relation_repairs" in out:
            out["relation_repairs"] = rewrite_repair_refs(out["relation_repairs"], object_map)
    for key in ("asset_path", "image_path"):
        if key in out:
            out[key] = prefix_asset_path(part_name, out.get(key))
    out["split_part"] = part_name
    out["split_prefix"] = prefix
    return out


def merge_split_irs(result_dir: Path, part_ir_dirs: list[tuple[str, Path]], out_ir: Path, row: dict[str, Any]) -> dict[str, Any]:
    if out_ir.exists():
        shutil.rmtree(out_ir)
    out_ir.mkdir(parents=True, exist_ok=True)

    blocks: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    visuals: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    reading_order = 0

    for part_index, (part_name, ir_dir) in enumerate(part_ir_dirs, start=1):
        prefix = f"p{part_index:03d}_"
        part_doc = read_json(ir_dir / "document.json")
        manifests.append(part_doc)

        part_sections = load_jsonl(ir_dir / "sections.jsonl")
        part_blocks = load_jsonl(ir_dir / "blocks.jsonl")
        part_tables = load_jsonl(ir_dir / "tables.jsonl")
        part_visuals = load_jsonl(ir_dir / "visuals.jsonl")

        block_map = {str(item.get("block_id")): prefix + str(item.get("block_id")) for item in part_blocks if item.get("block_id")}
        section_map = {str(item.get("section_id")): prefix + str(item.get("section_id")) for item in part_sections if item.get("section_id")}
        table_map = {str(item.get("table_id")): prefix + str(item.get("table_id")) for item in part_tables if item.get("table_id")}
        visual_map = {str(item.get("visual_id")): prefix + str(item.get("visual_id")) for item in part_visuals if item.get("visual_id")}

        for section in part_sections:
            sections.append(rewrite_row(section, part_name, prefix, block_map, section_map))
        for block in part_blocks:
            reading_order += 1
            rewritten = rewrite_row(block, part_name, prefix, block_map, section_map)
            rewritten["reading_order"] = reading_order
            blocks.append(rewritten)
        for table in part_tables:
            tables.append(rewrite_row(table, part_name, prefix, block_map, section_map, table_map=table_map))
        for visual in part_visuals:
            visuals.append(rewrite_row(visual, part_name, prefix, block_map, section_map, visual_map=visual_map))

    page_ids = sorted({item.get("page_id") for item in blocks if item.get("page_id") is not None})
    doc = {
        "doc_id": row.get("doc_id"),
        "domain": row.get("domain"),
        "source": "mineru",
        "root": str(result_dir),
        "source_path": row.get("source_path"),
        "staged_pdf_path": row.get("staged_pdf_path"),
        "source_kind": row.get("source_kind"),
        "question_ids": row.get("question_ids") or [],
        "question_count": row.get("question_count") or 0,
        "answer_formats": row.get("answer_formats") or [],
        "competition_split": "group_a",
        "split": True,
        "split_part_count": len(part_ir_dirs),
        "split_part_manifests": manifests,
        "page_count_observed": len(page_ids),
        "pages_observed": page_ids,
        "block_count": len(blocks),
        "section_count": len(sections),
        "table_count": len(tables),
        "visual_count": len(visuals),
    }
    write_json(out_ir / "document.json", doc)
    write_jsonl(out_ir / "blocks.jsonl", blocks)
    write_jsonl(out_ir / "sections.jsonl", sections)
    write_jsonl(out_ir / "tables.jsonl", tables)
    write_jsonl(out_ir / "visuals.jsonl", visuals)
    return doc


def normalize_split(normalizer: Any, result_dir: Path, out_ir: Path, doc_id: str, row: dict[str, Any], keep_part_ir: bool) -> dict[str, Any]:
    result = read_json(result_dir / "result.json")
    if result.get("state") != "done":
        raise RuntimeError(f"split parent result is not done: {result_dir} state={result.get('state')}")
    part_records = result.get("parts") or []
    if not part_records:
        raise RuntimeError(f"split result has no parts: {result_dir}")

    part_ir_dirs: list[tuple[str, Path]] = []
    temp_root = out_ir.parent / "_part_ir" / doc_id
    if temp_root.exists() and not keep_part_ir:
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    for index, part in enumerate(part_records, start=1):
        if part.get("state") != "done":
            raise RuntimeError(f"split part is not done for {doc_id}: {part}")
        part_dir = Path(part.get("output") or "").expanduser()
        if not part_dir.is_absolute():
            part_dir = result_dir / "parts" / str(part.get("name") or "")
        part_dir = part_dir.resolve()
        if not has_content_list(part_dir):
            raise FileNotFoundError(f"no content_list JSON for split part: {part_dir}")
        part_name = part_dir.name
        part_ir = temp_root / part_name / "ir"
        if part_ir.exists():
            shutil.rmtree(part_ir)
        normalizer.normalize(part_dir, part_ir, doc_id=doc_id, page_offset=part_page_offset(part_dir, index))
        augment_document(part_ir, row, {"split_part": part_name, "split_parent_result_dir": str(result_dir)})
        part_ir_dirs.append((part_name, part_ir))

    merged = merge_split_irs(result_dir, part_ir_dirs, out_ir, row)
    if not keep_part_ir:
        shutil.rmtree(temp_root, ignore_errors=True)
    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-manifest", default="processed_data/manifests/group_a_question_pdfs.jsonl")
    parser.add_argument("--out-root", default="processed_data/ir/mineru")
    parser.add_argument("--normalizer", default=DEFAULT_NORMALIZER)
    parser.add_argument("--force", action="store_true", help="Rebuild existing IR directories.")
    parser.add_argument("--keep-part-ir", action="store_true", help="Keep temporary normalized split part IRs.")
    parser.add_argument("--report", default="processed_data/reports/mineru_ir_build_report.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    normalizer = load_normalizer(Path(args.normalizer).expanduser().resolve())
    rows = list(iter_jsonl(Path(args.pdf_manifest).expanduser().resolve()) or [])
    out_root = Path(args.out_root).expanduser().resolve()
    summaries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in rows:
        domain = str(row.get("domain") or "unknown")
        doc_id = str(row.get("doc_id") or "")
        result_dir = Path(row.get("mineru_result_dir") or "").expanduser().resolve()
        out_ir = out_root / domain / doc_id / "ir"
        if out_ir.exists() and not args.force:
            skipped.append({"doc_id": doc_id, "domain": domain, "reason": "ir_exists", "ir_dir": str(out_ir)})
            continue
        try:
            if not result_dir.exists():
                skipped.append({"doc_id": doc_id, "domain": domain, "reason": "missing_mineru_result", "result_dir": str(result_dir)})
                continue
            if has_content_list(result_dir):
                doc = normalize_single(normalizer, result_dir, out_ir, doc_id, row)
            else:
                result_path = result_dir / "result.json"
                if not result_path.exists():
                    skipped.append({"doc_id": doc_id, "domain": domain, "reason": "missing_result_json", "result_dir": str(result_dir)})
                    continue
                result = read_json(result_path)
                if result.get("state") and result.get("state") != "done":
                    skipped.append({"doc_id": doc_id, "domain": domain, "reason": f"mineru_state_{result.get('state')}", "result_dir": str(result_dir)})
                    continue
                if result.get("split"):
                    doc = normalize_split(normalizer, result_dir, out_ir, doc_id, row, keep_part_ir=args.keep_part_ir)
                else:
                    skipped.append({"doc_id": doc_id, "domain": domain, "reason": "no_content_list", "result_dir": str(result_dir)})
                    continue
            summaries.append(
                {
                    "doc_id": doc_id,
                    "domain": domain,
                    "ir_dir": str(out_ir),
                    "block_count": doc.get("block_count"),
                    "section_count": doc.get("section_count"),
                    "table_count": doc.get("table_count"),
                    "visual_count": doc.get("visual_count"),
                    "split": bool(doc.get("split")),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"doc_id": doc_id, "domain": domain, "result_dir": str(result_dir), "error": str(exc)})

    report = {
        "tool": "03_build_mineru_ir.py",
        "pdf_manifest": str(Path(args.pdf_manifest).expanduser().resolve()),
        "out_root": str(out_root),
        "input_docs": len(rows),
        "built": len(summaries),
        "skipped": skipped,
        "failures": failures,
        "summaries": summaries,
    }
    write_json(Path(args.report).expanduser().resolve(), report)
    print(json.dumps({"input_docs": len(rows), "built": len(summaries), "skipped": len(skipped), "failures": len(failures)}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
