#!/usr/bin/env python3
"""Export DocPreprocess evidence units and AFAC competition corpus files.

Outputs:
  - processed_data/quality/* object labels and reports
  - processed_data/evidence_units/*.jsonl
  - processed_data/selector/*.jsonl
  - processed_data/docs.jsonl
  - processed_data/chunks.jsonl
  - processed_data/tables.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


DOCPREPROCESS = Path("/public/home/zhangfanjin/zhangnianhao/01-projects/DocPreprocess/scripts")


class TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self.skip_depth += 1
        if tag.lower() in {"p", "br", "div", "section", "article", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1
        if tag.lower() in {"p", "div", "section", "article", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip())


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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def clean_text(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(text or "")).strip()


def strip_html(value: str) -> str:
    parser = TextHTMLParser()
    parser.feed(value or "")
    return clean_text(parser.text())


def meta_content(raw_html: str, name: str) -> str:
    pattern = re.compile(
        rf"<meta\s+[^>]*(?:name|property)=[\"']{re.escape(name)}[\"'][^>]*content=[\"']([^\"']*)[\"'][^>]*>",
        flags=re.IGNORECASE,
    )
    match = pattern.search(raw_html or "")
    return html.unescape(match.group(1)).strip() if match else ""


def extract_html_article(raw_html: str) -> str:
    """Prefer the article body over site navigation for regulatory HTML."""
    title = meta_content(raw_html, "ArticleTitle")
    pub_date = meta_content(raw_html, "PubDate")
    body = ""
    for pattern in (
        r"<div\s+class=[\"']detail-news[\"'][^>]*>(.*?)(?:</div>\s*</div>|<div\s+class=[\"']pages|<script\b)",
        r"<div\s+class=[\"']content[\"'][^>]*>(.*?)(?:</div>\s*</div>\s*<div\s+class=[\"']footer|<div\s+class=[\"']footer|</body>)",
    ):
        match = re.search(pattern, raw_html or "", flags=re.IGNORECASE | re.DOTALL)
        if match:
            body = match.group(1)
            break
    if not body:
        body = raw_html
    prefix = "\n".join(part for part in (title, pub_date) if part)
    return f"{prefix}\n{strip_html(body)}".strip() if prefix else strip_html(body)


def numbers(text: str) -> list[str]:
    out: list[str] = []
    for match in re.finditer(r"(?<![\dA-Za-z])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?", text or ""):
        token = match.group(0)
        if token.startswith("-") or token.startswith("+"):
            prefix = (text or "")[: match.start()].rstrip()
            if token.startswith("-") and re.search(r"\d\s*[^，,。；;：:\s]{0,8}$", prefix):
                token = token[1:]
            elif re.fullmatch(r"[-+](?:19|20)\d{2}", token):
                token = token[1:]
            elif prefix and prefix[-1].isdigit():
                token = token[1:]
        out.append(token)
        if len(out) >= 200:
            break
    return out


def years(text: str) -> list[str]:
    return sorted(set(re.findall(r"(?:19|20)\d{2}", text or "")))


def sha1_span(doc_id: str, start: int | None, end: int | None, text: str) -> str:
    payload = f"{doc_id}:{start}:{end}:{text}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()


def source_title_from_text(text: str, fallback: str) -> str:
    for line in (text or "").splitlines():
        line = clean_text(line)
        if line:
            return line[:200]
    return fallback


def sliding_spans(text: str, start: int, end: int, max_chars: int, overlap: int) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    cursor = start
    step = max(1, max_chars - overlap)
    while cursor < end:
        chunk_end = min(end, cursor + max_chars)
        chunk = text[cursor:chunk_end].strip()
        if chunk:
            leading_ws = len(text[cursor:chunk_end]) - len(text[cursor:chunk_end].lstrip())
            trailing_ws = len(text[cursor:chunk_end]) - len(text[cursor:chunk_end].rstrip())
            spans.append(
                {
                    "text": chunk,
                    "char_start": cursor + leading_ws,
                    "char_end": chunk_end - trailing_ws,
                    "article_no": None,
                }
            )
        if chunk_end >= end:
            break
        cursor += step
    return spans


def split_text_spans(text: str, max_chars: int, overlap: int) -> list[dict[str, Any]]:
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    if not text:
        return []
    spans: list[dict[str, Any]] = []
    matches = list(re.finditer(r"\S.*?(?=\n\s*\n|\Z)", text, flags=re.DOTALL))
    current_parts: list[tuple[int, int, str]] = []
    current_len = 0
    for match in matches:
        para = match.group(0).strip()
        if not para:
            continue
        p_start = match.start() + (len(match.group(0)) - len(match.group(0).lstrip()))
        p_end = match.end() - (len(match.group(0)) - len(match.group(0).rstrip()))
        candidate_len = current_len + (2 if current_parts else 0) + len(para)
        if current_parts and candidate_len > max_chars:
            start = current_parts[0][0]
            end = current_parts[-1][1]
            chunk = "\n\n".join(part[2] for part in current_parts)
            spans.append({"text": chunk, "char_start": start, "char_end": end, "article_no": None})
            current_parts = []
            current_len = 0
        if len(para) > max_chars:
            spans.extend(sliding_spans(text, p_start, p_end, max_chars=max_chars, overlap=overlap))
        else:
            current_parts.append((p_start, p_end, para))
            current_len = current_len + (2 if current_len else 0) + len(para)
    if current_parts:
        spans.append(
            {
                "text": "\n\n".join(part[2] for part in current_parts),
                "char_start": current_parts[0][0],
                "char_end": current_parts[-1][1],
                "article_no": None,
            }
        )
    return spans


def split_regulatory_spans(text: str, max_chars: int, overlap: int) -> list[dict[str, Any]]:
    text = (text or "").replace("\ufeff", "").strip()
    if not text:
        return []
    article_pattern = re.compile(r"(?m)(^|\n)(第[一二三四五六七八九十百千万零〇两0-9]+条)\s*")
    matches = list(article_pattern.finditer(text))
    if not matches:
        return split_text_spans(text, max_chars=max_chars, overlap=overlap)

    spans: list[dict[str, Any]] = []
    first_start = matches[0].start(2)
    if first_start > 0:
        spans.extend(split_text_spans(text[:first_start], max_chars=max_chars, overlap=overlap))
    for index, match in enumerate(matches):
        start = match.start(2)
        end = matches[index + 1].start(2) if index + 1 < len(matches) else len(text)
        article_no = match.group(2)
        if end - start <= max_chars:
            chunk = text[start:end].strip()
            if chunk:
                leading_ws = len(text[start:end]) - len(text[start:end].lstrip())
                trailing_ws = len(text[start:end]) - len(text[start:end].rstrip())
                spans.append(
                    {
                        "text": chunk,
                        "char_start": start + leading_ws,
                        "char_end": end - trailing_ws,
                        "article_no": article_no,
                    }
                )
        else:
            for span in sliding_spans(text, start, end, max_chars=max_chars, overlap=overlap):
                span["article_no"] = article_no
                spans.append(span)
    return spans


def split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    if not text:
        return []
    paras = [para.strip() for para in re.split(r"\n\s*\n", text) if para.strip()]
    chunks: list[str] = []
    current = ""
    for para in paras:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(para) <= max_chars:
            current = para
            continue
        start = 0
        while start < len(para):
            chunks.append(para[start : start + max_chars])
            start += max(1, max_chars - overlap)
        current = ""
    if current:
        chunks.append(current)
    return chunks


def read_source_text(path: Path) -> str:
    if path.suffix.lower() in {".html", ".htm"}:
        return extract_html_article(path.read_text(encoding="utf-8", errors="replace"))
    return path.read_text(encoding="utf-8", errors="replace")


def run_cmd(cmd: list[str], dry_run: bool) -> int:
    print(json.dumps({"cmd": cmd, "dry_run": dry_run}, ensure_ascii=False))
    if dry_run:
        return 0
    return subprocess.run(cmd, check=False).returncode


def ir_dirs(ir_root: Path) -> list[Path]:
    return sorted(path for path in ir_root.glob("*/*/ir") if path.is_dir())


def load_doc_meta(manifest_path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(manifest_path) or []:
        out[str(row.get("doc_id"))] = row
    return out


def load_quality_labels(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    labels: dict[tuple[str, str], dict[str, Any]] = {}
    for row in iter_jsonl(path) or []:
        key = (str(row.get("doc_id")), str(row.get("object_id")))
        labels[key] = row
    return labels


def build_docs_rows(meta: dict[str, dict[str, Any]], ir_root: Path) -> list[dict[str, Any]]:
    ir_doc_by_id: dict[str, dict[str, Any]] = {}
    for ir in ir_dirs(ir_root):
        doc = read_json(ir / "document.json")
        ir_doc_by_id[str(doc.get("doc_id"))] = {**doc, "ir_dir": str(ir)}
    rows: list[dict[str, Any]] = []
    for doc_id, item in sorted(meta.items()):
        ir_doc = ir_doc_by_id.get(doc_id, {})
        rows.append(
            {
                "doc_id": doc_id,
                "domain": item.get("domain"),
                "source_path": item.get("source_path"),
                "source_kind": item.get("source_kind"),
                "source_suffix": item.get("source_suffix"),
                "is_pdf": item.get("is_pdf"),
                "question_ids": item.get("question_ids") or [],
                "question_count": item.get("question_count") or 0,
                "parser": ir_doc.get("source") if ir_doc else ("raw_text" if not item.get("is_pdf") else "missing_ir"),
                "ir_dir": ir_doc.get("ir_dir", ""),
                "page_count_observed": ir_doc.get("page_count_observed"),
                "block_count": ir_doc.get("block_count"),
                "section_count": ir_doc.get("section_count"),
                "table_count": ir_doc.get("table_count"),
                "visual_count": ir_doc.get("visual_count"),
            }
        )
    return rows


def load_ir_documents(ir_root: Path) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for ir in ir_dirs(ir_root):
        doc = read_json(ir / "document.json")
        docs[str(doc.get("doc_id"))] = {**doc, "ir_dir": str(ir)}
    return docs


def qualified_object_id(doc_id: str, raw_id: Any) -> str | None:
    if not raw_id:
        return None
    raw = str(raw_id)
    return raw if raw.startswith(f"{doc_id}::") else f"{doc_id}::{raw}"


def resolve_asset(root: str, asset_path: Any) -> str | None:
    if not root or not asset_path:
        return None
    return str((Path(root) / str(asset_path)).resolve())


def build_pdf_chunks(selector_path: Path, meta: dict[str, dict[str, Any]], ir_root: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    dropped_unknown = 0
    ir_docs = load_ir_documents(ir_root)
    for item in iter_jsonl(selector_path) or []:
        doc_id = str(item.get("doc_id") or "")
        if doc_id not in meta:
            dropped_unknown += 1
            continue
        m = meta.get(doc_id, {})
        section_title = item.get("section_title") or ""
        text = clean_text(str(item.get("text") or ""))
        if not text:
            continue
        locator = item.get("locator") or {}
        root = str((ir_docs.get(doc_id) or {}).get("root") or "")
        raw_table_id = locator.get("table_id")
        raw_visual_id = locator.get("visual_id")
        rows.append(
            {
                "chunk_id": item.get("candidate_id") or item.get("unit_id"),
                "doc_id": doc_id,
                "domain": m.get("domain"),
                "source_type": "pdf_mineru_ir",
                "source_title": source_title_from_text(text, doc_id),
                "page": item.get("page_id"),
                "char_start": None,
                "char_end": None,
                "source_span_hash": sha1_span(doc_id, None, None, text),
                "section_id": item.get("section_id"),
                "section_path": [section_title] if section_title else [],
                "text": text,
                "numbers": numbers(text),
                "years": years(text),
                "modality": item.get("modality"),
                "unit_type": item.get("unit_type"),
                "block_id": item.get("block_id") or locator.get("block_id"),
                "raw_table_id": raw_table_id,
                "table_id": qualified_object_id(doc_id, raw_table_id),
                "raw_visual_id": raw_visual_id,
                "visual_id": qualified_object_id(doc_id, raw_visual_id),
                "reading_order": item.get("reading_order"),
                "bbox": locator.get("bbox"),
                "asset_path": locator.get("asset_path"),
                "asset_abs_path": resolve_asset(root, locator.get("asset_path")),
                "quality_tier": item.get("quality_tier"),
                "quality_flags": item.get("quality_flags") or [],
                "evidence_weight": item.get("evidence_weight"),
                "include_in_search": True,
                "locator": locator,
            }
        )
    return rows, dropped_unknown


def build_nonpdf_chunks(meta: dict[str, dict[str, Any]], max_chars: int, overlap: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc_id, item in sorted(meta.items()):
        if item.get("is_pdf") or not item.get("source_exists"):
            continue
        path = Path(str(item.get("source_path") or ""))
        if not path.exists():
            continue
        text = read_source_text(path).replace("\ufeff", "")
        title = source_title_from_text(text, doc_id)
        span_rows = split_regulatory_spans(text, max_chars=max_chars, overlap=overlap) if item.get("domain") == "regulatory" else split_text_spans(text, max_chars=max_chars, overlap=overlap)
        doc_chunk_rows: list[dict[str, Any]] = []
        for idx, span in enumerate(span_rows, start=1):
            chunk = clean_text(str(span.get("text") or ""))
            if not chunk:
                continue
            chunk_id = f"{doc_id}::raw::{idx:04d}"
            flags = []
            if len(chunk) < 80:
                flags.append("short_chunk")
            if span.get("article_no"):
                unit_type = "regulatory_article"
            else:
                unit_type = "raw_text"
            doc_chunk_rows.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "domain": item.get("domain"),
                    "source_type": item.get("source_kind"),
                    "source_title": title,
                    "page": None,
                    "char_start": span.get("char_start"),
                    "char_end": span.get("char_end"),
                    "source_span_hash": sha1_span(doc_id, span.get("char_start"), span.get("char_end"), chunk),
                    "article_no": span.get("article_no"),
                    "section_id": None,
                    "section_path": [title] if title else [],
                    "text": chunk,
                    "numbers": numbers(chunk),
                    "years": years(chunk),
                    "modality": "text",
                    "unit_type": unit_type,
                    "quality_tier": "normal",
                    "quality_flags": flags,
                    "evidence_weight": 1.0,
                    "include_in_search": True,
                    "prev_chunk_id": None,
                    "next_chunk_id": None,
                    "locator": {
                        "doc_id": doc_id,
                        "source_path": str(path),
                        "source_type": item.get("source_kind"),
                        "char_start": span.get("char_start"),
                        "char_end": span.get("char_end"),
                        "article_no": span.get("article_no"),
                    },
                }
            )
        for idx, row in enumerate(doc_chunk_rows):
            if idx > 0:
                row["prev_chunk_id"] = doc_chunk_rows[idx - 1]["chunk_id"]
            if idx + 1 < len(doc_chunk_rows):
                row["next_chunk_id"] = doc_chunk_rows[idx + 1]["chunk_id"]
        rows.extend(doc_chunk_rows)
    return rows


def table_text(row: dict[str, Any]) -> str:
    parts = []
    if row.get("caption"):
        parts.append(str(row.get("caption")))
    if row.get("html"):
        parts.append(strip_html(str(row.get("html"))))
    if row.get("footnote"):
        parts.append(str(row.get("footnote")))
    return clean_text(" ".join(parts))


def build_tables_rows(ir_root: Path, meta: dict[str, dict[str, Any]], quality_path: Path) -> tuple[list[dict[str, Any]], int]:
    labels = load_quality_labels(quality_path)
    rows: list[dict[str, Any]] = []
    dropped_unknown = 0
    for ir in ir_dirs(ir_root):
        doc = read_json(ir / "document.json")
        doc_id = str(doc.get("doc_id") or "")
        if doc_id not in meta:
            dropped_unknown += 1
            continue
        m = meta.get(doc_id, {})
        root = str(doc.get("root") or "")
        for table in iter_jsonl(ir / "tables.jsonl") or []:
            table_id = str(table.get("table_id") or "")
            text = table_text(table)
            quality = labels.get((doc_id, table_id), {})
            asset_path = table.get("image_path") or table.get("asset_path")
            locator = {
                "doc_id": doc_id,
                "source_type": "table",
                "section_id": table.get("section_id"),
                "page_id": table.get("page_id"),
                "block_id": table.get("block_id"),
                "table_id": table_id,
                "visual_id": None,
                "bbox": table.get("bbox"),
                "asset_path": asset_path,
                "asset_abs_path": resolve_asset(root, asset_path),
                "ir_dir": str(ir),
                "source_path": m.get("source_path") or doc.get("source_path"),
            }
            rows.append(
                {
                    "table_id": qualified_object_id(doc_id, table_id),
                    "raw_table_id": table_id,
                    "doc_id": doc_id,
                    "domain": m.get("domain") or doc.get("domain"),
                    "page": table.get("page_id"),
                    "section_id": table.get("section_id"),
                    "block_id": table.get("block_id"),
                    "reading_order": table.get("reading_order"),
                    "bbox": table.get("bbox"),
                    "caption": table.get("caption") or "",
                    "text": text,
                    "html": table.get("html") or "",
                    "numbers": table.get("numbers") or numbers(text),
                    "years": years(text),
                    "quality_tier": quality.get("quality_tier", "unlabeled"),
                    "quality_flags": quality.get("flags", []),
                    "evidence_weight": quality.get("evidence_weight", 0.5),
                    "asset_path": asset_path,
                    "asset_abs_path": resolve_asset(root, asset_path),
                    "locator": locator,
                    "source_path": m.get("source_path") or doc.get("source_path"),
                    "ir_dir": str(ir),
                }
            )
    return rows, dropped_unknown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ir-root", default="processed_data/ir/mineru")
    parser.add_argument("--manifest", default="processed_data/manifests/group_a_question_docs.jsonl")
    parser.add_argument("--out-root", default="processed_data")
    parser.add_argument("--source-name", default="afac_group_a_mineru")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-docpreprocess-tools", action="store_true")
    parser.add_argument("--nonpdf-max-chars", type=int, default=1600)
    parser.add_argument("--nonpdf-overlap", type=int, default=160)
    parser.add_argument("--allow-missing-pdf-ir", action="store_true")
    parser.add_argument("--allow-empty-pdf-corpus", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ir_root = Path(args.ir_root).expanduser().resolve()
    out_root = Path(args.out_root).expanduser().resolve()
    manifest = Path(args.manifest).expanduser().resolve()
    quality_dir = out_root / "quality"
    evidence_dir = out_root / "evidence_units"
    selector_dir = out_root / "selector"
    report_dir = out_root / "reports"
    quality_json = quality_dir / "group_a_mineru_quality_report.json"
    quality_jsonl = quality_dir / "group_a_mineru_object_quality.jsonl"
    quality_md = quality_dir / "group_a_mineru_quality_report.md"
    evidence_jsonl = evidence_dir / "group_a_evidence_units.jsonl"
    evidence_report = evidence_dir / "group_a_evidence_units_report.json"
    evidence_md = evidence_dir / "group_a_evidence_units_report.md"
    selector_jsonl = selector_dir / "group_a_selector_search.jsonl"
    selector_report = selector_dir / "group_a_selector_search_report.json"
    selector_md = selector_dir / "group_a_selector_search_report.md"

    existing_ir_dirs = ir_dirs(ir_root)
    if not args.skip_docpreprocess_tools and existing_ir_dirs:
        commands = [
            [
                sys.executable,
                str(DOCPREPROCESS / "annotate_ir_quality.py"),
                "--ir-root",
                f"{args.source_name}={ir_root}",
                "--output",
                str(quality_json),
                "--objects-output",
                str(quality_jsonl),
                "--markdown",
                str(quality_md),
                "--image-stats-mode",
                "dims",
            ],
            [
                sys.executable,
                str(DOCPREPROCESS / "export_evidence_units.py"),
                "--ir-root",
                f"{args.source_name}={ir_root}",
                "--quality-objects",
                str(quality_jsonl),
                "--output",
                str(evidence_jsonl),
                "--report",
                str(evidence_report),
                "--markdown",
                str(evidence_md),
                "--max-text-chars",
                "3000",
            ],
            [
                sys.executable,
                str(DOCPREPROCESS / "export_selector_view.py"),
                "--input",
                str(evidence_jsonl),
                "--output",
                str(selector_jsonl),
                "--report",
                str(selector_report),
                "--markdown",
                str(selector_md),
                "--mode",
                "search",
                "--path-mode",
                "keep",
                "--max-text-chars",
                "1800",
            ],
        ]
        for cmd in commands:
            code = run_cmd(cmd, args.dry_run)
            if code != 0:
                return code

    if args.dry_run:
        return 0

    meta = load_doc_meta(manifest)
    expected_pdf_docs = sorted(doc_id for doc_id, row in meta.items() if row.get("is_pdf"))
    ir_doc_ids = {str(read_json(ir / "document.json").get("doc_id") or "") for ir in existing_ir_dirs}
    missing_pdf_ir = [doc_id for doc_id in expected_pdf_docs if doc_id not in ir_doc_ids]
    if missing_pdf_ir and not args.allow_missing_pdf_ir:
        raise SystemExit(
            "missing MinerU IR for PDF docs; run script/02_run_mineru_question_pdfs.py and "
            f"script/03_build_mineru_ir.py first, or pass --allow-missing-pdf-ir. missing={len(missing_pdf_ir)}"
        )
    docs_rows = build_docs_rows(meta, ir_root)
    pdf_chunks, dropped_unknown_pdf_chunks = build_pdf_chunks(selector_jsonl, meta, ir_root) if selector_jsonl.exists() else ([], 0)
    if expected_pdf_docs and not pdf_chunks and not args.allow_empty_pdf_corpus:
        raise SystemExit("PDF docs are expected but pdf_chunks=0; pass --allow-empty-pdf-corpus for scaffold-only runs.")
    nonpdf_chunks = build_nonpdf_chunks(meta, max_chars=args.nonpdf_max_chars, overlap=args.nonpdf_overlap)
    table_rows, dropped_unknown_tables = build_tables_rows(ir_root, meta, quality_jsonl) if quality_jsonl.exists() else ([], 0)
    chunk_rows = sorted(pdf_chunks + nonpdf_chunks, key=lambda row: (str(row.get("domain")), str(row.get("doc_id")), str(row.get("chunk_id"))))

    write_jsonl(out_root / "docs.jsonl", docs_rows)
    write_jsonl(out_root / "chunks.jsonl", chunk_rows)
    write_jsonl(out_root / "tables.jsonl", table_rows)
    summary = {
        "tool": "04_export_preprocessed_corpus.py",
        "ir_root": str(ir_root),
        "manifest": str(manifest),
        "docs": len(docs_rows),
        "chunks": len(chunk_rows),
        "pdf_chunks": len(pdf_chunks),
        "nonpdf_chunks": len(nonpdf_chunks),
        "tables": len(table_rows),
        "missing_pdf_ir": missing_pdf_ir,
        "dropped_unknown_pdf_chunks": dropped_unknown_pdf_chunks,
        "dropped_unknown_tables": dropped_unknown_tables,
        "outputs": {
            "docs": str(out_root / "docs.jsonl"),
            "chunks": str(out_root / "chunks.jsonl"),
            "tables": str(out_root / "tables.jsonl"),
            "quality_report": str(quality_json),
            "evidence_units": str(evidence_jsonl),
            "selector": str(selector_jsonl),
        },
    }
    write_json(report_dir / "group_a_preprocessed_corpus_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
