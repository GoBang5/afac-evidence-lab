#!/usr/bin/env python3
"""Build a half-question evidence seed set for agent-style QA annotation.

This is a sidecar data-prep tool.  It does not call any model.  It selects a
balanced half of Group A questions, prepares searchable evidence candidates from
the existing selector view plus raw-document fallbacks, and writes annotation
skeletons that can be filled by human/agent judges.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


PUNCT_RE = re.compile(r"[\s\t\r\n\f\v，。、“”‘’：:；;（）()【】\[\]《》<>？?！!,.·/\\|+\-=*_#`~^$@]+")
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%/-]*|[\u4e00-\u9fff]{2,}")
NUMBER_RE = re.compile(r"(?<![\dA-Za-z])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?")
YEAR_RE = re.compile(r"(?:19|20)\d{2}")


class TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self.skip_depth += 1
        if tag.lower() in {"p", "br", "div", "section", "article", "tr", "li", "h1", "h2", "h3", "h4", "td"}:
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


@dataclass
class Candidate:
    candidate_id: str
    unit_id: str
    doc_id: str
    source: str
    source_path: str
    page_id: int | None
    section_title: str
    unit_type: str
    text: str
    locator: dict[str, Any]


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
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


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in materialized) + ("\n" if materialized else ""),
        encoding="utf-8",
    )
    return len(materialized)


def clean_text(text: str) -> str:
    text = html.unescape(text or "").replace("\ufeff", "")
    text = re.sub(r"[ \t\r\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_html(raw: str) -> str:
    parser = TextHTMLParser()
    parser.feed(raw or "")
    return clean_text(parser.text())


def normalize_for_match(text: str) -> str:
    return PUNCT_RE.sub("", (text or "").lower())


def numbers(text: str) -> list[str]:
    return NUMBER_RE.findall(text or "")[:80]


def years(text: str) -> list[str]:
    return sorted(set(YEAR_RE.findall(text or "")))


def char_ngrams(text: str, n: int) -> set[str]:
    norm = normalize_for_match(text)
    if len(norm) < n:
        return {norm} if norm else set()
    return {norm[i : i + n] for i in range(len(norm) - n + 1)}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in WORD_RE.finditer(text or ""):
        token = match.group(0).lower()
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) <= 6:
                tokens.append(token)
            for n in (2, 3, 4):
                if len(token) >= n:
                    tokens.extend(token[i : i + n] for i in range(len(token) - n + 1))
        else:
            tokens.append(token)
    tokens.extend(num.lower() for num in numbers(text))
    return [tok for tok in tokens if tok and len(tok) >= 2]


def keyphrases(text: str) -> list[str]:
    phrases: list[str] = []
    for match in WORD_RE.finditer(text or ""):
        token = match.group(0).strip()
        if len(token) >= 3:
            phrases.append(token)
    for num in numbers(text):
        phrases.append(num)
    seen: set[str] = set()
    out: list[str] = []
    for phrase in phrases:
        key = phrase.lower()
        if key not in seen:
            seen.add(key)
            out.append(phrase)
    return out[:40]


def read_questions(questions_dir: Path, per_domain: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(questions_dir.glob("*_questions.json")):
        questions = json.loads(path.read_text(encoding="utf-8"))
        for index, question in enumerate(questions[:per_domain], 1):
            rows.append(
                {
                    **question,
                    "selection": {
                        "strategy": "balanced_first_n_per_domain",
                        "per_domain": per_domain,
                        "domain_rank": index,
                        "question_file": path.name,
                    },
                }
            )
    return rows


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    return {str(row.get("doc_id")): row for row in iter_jsonl(path) or []}


def selector_candidates(path: Path, selected_doc_ids: set[str], max_text_chars: int) -> dict[str, list[Candidate]]:
    by_doc: dict[str, list[Candidate]] = defaultdict(list)
    for row in iter_jsonl(path) or []:
        doc_id = str(row.get("doc_id") or "")
        if doc_id not in selected_doc_ids:
            continue
        text = clean_text(str(row.get("text") or ""))
        if not text:
            continue
        locator = dict(row.get("locator") or {})
        cand = Candidate(
            candidate_id=str(row.get("candidate_id") or row.get("unit_id") or row.get("chunk_id")),
            unit_id=str(row.get("unit_id") or row.get("chunk_id") or row.get("candidate_id")),
            doc_id=doc_id,
            source="selector",
            source_path=str(locator.get("source_path") or ""),
            page_id=row.get("page_id"),
            section_title=str(row.get("section_title") or ""),
            unit_type=str(row.get("unit_type") or row.get("modality") or "text"),
            text=text[:max_text_chars],
            locator=locator,
        )
        by_doc[doc_id].append(cand)
    return by_doc


def extract_pdf_pages(path: Path) -> list[tuple[int, str]]:
    proc = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return []
    pages = proc.stdout.split("\f")
    return [(index, clean_text(page)) for index, page in enumerate(pages, 1) if clean_text(page)]


def split_text(text: str, max_chars: int, overlap: int) -> list[tuple[int, int, str]]:
    text = clean_text(text)
    if not text:
        return []
    paras: list[tuple[int, int, str]] = []
    for match in re.finditer(r"\S.*?(?=\n\s*\n|\Z)", text, flags=re.DOTALL):
        raw = match.group(0)
        para = raw.strip()
        if not para:
            continue
        start = match.start() + (len(raw) - len(raw.lstrip()))
        end = match.end() - (len(raw) - len(raw.rstrip()))
        paras.append((start, end, para))
    if not paras:
        paras = [(0, len(text), text)]

    spans: list[tuple[int, int, str]] = []
    cur: list[tuple[int, int, str]] = []
    cur_len = 0
    for start, end, para in paras:
        if len(para) > max_chars:
            if cur:
                spans.append((cur[0][0], cur[-1][1], "\n\n".join(item[2] for item in cur)))
                cur = []
                cur_len = 0
            step = max(1, max_chars - overlap)
            cursor = 0
            while cursor < len(para):
                piece = para[cursor : cursor + max_chars].strip()
                if piece:
                    spans.append((start + cursor, min(end, start + cursor + len(piece)), piece))
                if cursor + max_chars >= len(para):
                    break
                cursor += step
            continue
        candidate_len = cur_len + (2 if cur else 0) + len(para)
        if cur and candidate_len > max_chars:
            spans.append((cur[0][0], cur[-1][1], "\n\n".join(item[2] for item in cur)))
            cur = []
            cur_len = 0
        cur.append((start, end, para))
        cur_len += (2 if cur_len else 0) + len(para)
    if cur:
        spans.append((cur[0][0], cur[-1][1], "\n\n".join(item[2] for item in cur)))
    return spans


def raw_fallback_candidates(
    manifest_row: dict[str, Any], max_text_chars: int, overlap: int
) -> list[Candidate]:
    doc_id = str(manifest_row.get("doc_id") or "")
    source_path = Path(str(manifest_row.get("source_path") or ""))
    if not source_path.exists():
        return []
    suffix = source_path.suffix.lower()
    source_kind = str(manifest_row.get("source_kind") or "raw")
    raw_units: list[tuple[int | None, int, int, str]] = []
    if suffix == ".pdf":
        for page_id, page_text in extract_pdf_pages(source_path):
            for start, end, text in split_text(page_text, max_chars=max_text_chars, overlap=overlap):
                raw_units.append((page_id, start, end, text))
    elif suffix in {".txt", ".md"}:
        text = clean_text(source_path.read_text(encoding="utf-8", errors="ignore"))
        for start, end, span in split_text(text, max_chars=max_text_chars, overlap=overlap):
            raw_units.append((None, start, end, span))
    elif suffix in {".html", ".htm"}:
        text = strip_html(source_path.read_text(encoding="utf-8", errors="ignore"))
        for start, end, span in split_text(text, max_chars=max_text_chars, overlap=overlap):
            raw_units.append((None, start, end, span))

    out: list[Candidate] = []
    for index, (page_id, start, end, text) in enumerate(raw_units, 1):
        text = clean_text(text)
        if not text:
            continue
        unit_id = f"{doc_id}::raw::{index:06d}"
        digest = hashlib.sha1(f"{doc_id}:{page_id}:{start}:{end}:{text[:200]}".encode("utf-8")).hexdigest()[:12]
        out.append(
            Candidate(
                candidate_id=f"{unit_id}:{digest}",
                unit_id=unit_id,
                doc_id=doc_id,
                source=f"raw_text_fallback:{source_kind}",
                source_path=str(source_path),
                page_id=page_id,
                section_title="",
                unit_type="raw_text",
                text=text[:max_text_chars],
                locator={
                    "doc_id": doc_id,
                    "source_type": "raw_text_fallback",
                    "source_path": str(source_path),
                    "page_id": page_id,
                    "char_start": start,
                    "char_end": end,
                },
            )
        )
    return out


def build_corpus(
    questions: list[dict[str, Any]],
    manifest: dict[str, dict[str, Any]],
    selector_path: Path,
    max_text_chars: int,
    overlap: int,
    prefer_selector: bool,
) -> tuple[dict[str, list[Candidate]], dict[str, Any]]:
    selected_doc_ids = {str(doc_id) for q in questions for doc_id in (q.get("doc_ids") or [])}
    by_doc = selector_candidates(selector_path, selected_doc_ids, max_text_chars=max_text_chars)
    report: dict[str, Any] = {
        "selected_doc_ids": len(selected_doc_ids),
        "docs_with_selector": sum(1 for doc_id in selected_doc_ids if by_doc.get(doc_id)),
        "raw_fallback_docs": [],
        "missing_docs": [],
    }
    for doc_id in sorted(selected_doc_ids):
        if prefer_selector and by_doc.get(doc_id):
            continue
        row = manifest.get(doc_id)
        if not row:
            report["missing_docs"].append({"doc_id": doc_id, "reason": "not_in_manifest"})
            continue
        fallback = raw_fallback_candidates(row, max_text_chars=max_text_chars, overlap=overlap)
        if fallback:
            if prefer_selector:
                by_doc[doc_id] = fallback
            else:
                by_doc[doc_id].extend(fallback)
            report["raw_fallback_docs"].append(
                {
                    "doc_id": doc_id,
                    "source_path": row.get("source_path"),
                    "source_kind": row.get("source_kind"),
                    "units": len(fallback),
                }
            )
        elif not by_doc.get(doc_id):
            report["missing_docs"].append({"doc_id": doc_id, "reason": "no_selector_or_fallback_text"})
    report["docs_with_candidates"] = sum(1 for doc_id in selected_doc_ids if by_doc.get(doc_id))
    report["candidate_units"] = sum(len(rows) for rows in by_doc.values())
    return by_doc, report


def score_candidate(
    candidate: Candidate,
    query: str,
    idf: dict[str, float],
    option_text: str = "",
) -> tuple[float, dict[str, Any]]:
    q_tokens = tokenize(query)
    q_counts = Counter(q_tokens)
    text_tokens = Counter(tokenize(candidate.text))
    token_score = 0.0
    matched_tokens: list[str] = []
    for token, q_count in q_counts.items():
        if text_tokens.get(token):
            matched_tokens.append(token)
            token_score += (1.0 + math.log1p(text_tokens[token])) * idf.get(token, 1.0) * min(q_count, 3)

    q_bigrams = char_ngrams(query, 2)
    t_bigrams = char_ngrams(candidate.text, 2)
    bigram_overlap = len(q_bigrams & t_bigrams)
    bigram_score = bigram_overlap / max(8, len(q_bigrams)) * 8.0

    q_numbers = set(numbers(query))
    t_numbers = set(numbers(candidate.text))
    num_hits = sorted(q_numbers & t_numbers)
    number_score = 2.5 * len(num_hits)

    option_norm = normalize_for_match(option_text)
    cand_norm = normalize_for_match(candidate.text)
    literal_score = 0.0
    if option_norm and len(option_norm) >= 6 and option_norm in cand_norm:
        literal_score += 12.0

    short_phrases = [phrase for phrase in keyphrases(option_text) if len(normalize_for_match(phrase)) >= 3]
    phrase_hits = [phrase for phrase in short_phrases if normalize_for_match(phrase) in cand_norm]
    phrase_score = 1.5 * len(phrase_hits)

    source_bonus = 0.5 if candidate.source == "selector" else 0.0
    score = token_score + bigram_score + number_score + literal_score + phrase_score + source_bonus
    return score, {
        "token_score": round(token_score, 4),
        "bigram_score": round(bigram_score, 4),
        "number_score": round(number_score, 4),
        "literal_score": round(literal_score, 4),
        "phrase_score": round(phrase_score, 4),
        "matched_tokens": matched_tokens[:30],
        "matched_numbers": num_hits,
        "matched_option_phrases": phrase_hits[:20],
    }


def build_idf(candidates: list[Candidate]) -> dict[str, float]:
    df: Counter[str] = Counter()
    for cand in candidates:
        df.update(set(tokenize(cand.text)))
    n = max(1, len(candidates))
    return {token: math.log((n + 1) / (count + 0.5)) + 1.0 for token, count in df.items()}


def evidence_row(candidate: Candidate, score: float, features: dict[str, Any], max_quote_chars: int) -> dict[str, Any]:
    text = clean_text(candidate.text)
    return {
        "candidate_id": candidate.candidate_id,
        "unit_id": candidate.unit_id,
        "doc_id": candidate.doc_id,
        "source": candidate.source,
        "page_id": candidate.page_id,
        "section_title": candidate.section_title,
        "unit_type": candidate.unit_type,
        "score": round(score, 4),
        "score_features": features,
        "text": text[:max_quote_chars],
        "text_char_count": len(text),
        "locator": candidate.locator,
    }


def domain_search_playbook(domain: str, answer_format: str) -> list[str]:
    base = [
        "先限制在题目给定 doc_ids 内，不做跨文档开放检索。",
        "把题干拆成实体/指标/年份/金额/比例/条款号，再把每个选项作为单独 query。",
        "每个选项至少找一条支持或反驳证据；多选题按选项独立判断，判断题优先找题干关键谓词。",
    ]
    domain_steps = {
        "financial_contracts": [
            "合同/募集说明书题优先搜发行人、发行规模、评级、担保、承销商、受托管理人、回售/赎回/违约等字段。",
            "如果选项涉及两份文档比较，先分别抽取字段值，再做大小、是否一致或是否出现的判断。",
        ],
        "financial_reports": [
            "财报题优先搜公司年度、主要会计数据、利润、现金流、研发投入、分红、资产负债等表格字段。",
            "跨年比较先建立 year->metric value 小表，再判断增长/下降/占比变化。",
        ],
        "insurance": [
            "保险题优先搜产品名称、保险责任、身故/满期/年金给付、现金价值、已交保费、责任免除等条款。",
            "涉及计算时先抄出公式和年龄/比例/领取前后条件，再代入题干假设。",
        ],
        "regulatory": [
            "法规题优先搜条号、施行日期、过渡期、监管义务、不得/应当/可以等规范动词。",
            "比较两部法规时分别定位施行日期和对应条款，再判定早晚或义务差异。",
        ],
        "research": [
            "研报题优先搜公司/行业名、指标名、年份、预测值、同比/复合增速、图表标题和结论段。",
            "如果证据来自图表，保留图表标题和邻近解释文本，避免只截单个数字。",
        ],
    }
    tail = [f"答案格式为 {answer_format}，最终只允许输出合法大写选项；无充分证据时标注 partial/needs_review。"]
    return base + domain_steps.get(domain, []) + tail


def annotate_questions(
    questions: list[dict[str, Any]],
    by_doc: dict[str, list[Candidate]],
    option_top_k: int,
    question_top_k: int,
    max_quote_chars: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for question in questions:
        qid = str(question.get("qid"))
        doc_ids = [str(doc_id) for doc_id in question.get("doc_ids") or []]
        candidates = [cand for doc_id in doc_ids for cand in by_doc.get(doc_id, [])]
        idf = build_idf(candidates)
        question_text = str(question.get("question") or "")
        options = {str(k): str(v) for k, v in (question.get("options") or {}).items()}
        source_docs = sorted({cand.doc_id for cand in candidates})
        missing_docs = [doc_id for doc_id in doc_ids if doc_id not in source_docs]

        option_evidence: dict[str, list[dict[str, Any]]] = {}
        all_scored: dict[str, tuple[Candidate, float, dict[str, Any]]] = {}
        for label, option_text in sorted(options.items()):
            query = f"{question_text}\n{label}. {option_text}"
            scored: list[tuple[float, Candidate, dict[str, Any]]] = []
            for cand in candidates:
                score, features = score_candidate(cand, query, idf=idf, option_text=option_text)
                if score > 0:
                    scored.append((score, cand, features))
            scored.sort(key=lambda item: item[0], reverse=True)
            picked: list[dict[str, Any]] = []
            seen_docs: set[str] = set()
            for score, cand, features in scored:
                key = cand.candidate_id
                if key not in all_scored or score > all_scored[key][1]:
                    all_scored[key] = (cand, score, features)
                picked.append(evidence_row(cand, score, features, max_quote_chars=max_quote_chars))
                seen_docs.add(cand.doc_id)
                if len(picked) >= option_top_k and len(seen_docs) >= min(2, len(doc_ids)):
                    break
                if len(picked) >= option_top_k + 2:
                    break
            option_evidence[label] = picked[:option_top_k]

        q_scored: list[tuple[float, Candidate, dict[str, Any]]] = []
        for cand in candidates:
            score, features = score_candidate(cand, question_text, idf=idf)
            if score > 0:
                q_scored.append((score, cand, features))
        for cand, score, features in all_scored.values():
            q_scored.append((score, cand, features))
        q_scored.sort(key=lambda item: item[0], reverse=True)
        question_evidence: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for score, cand, features in q_scored:
            if cand.candidate_id in seen_ids:
                continue
            seen_ids.add(cand.candidate_id)
            question_evidence.append(evidence_row(cand, score, features, max_quote_chars=max_quote_chars))
            if len(question_evidence) >= question_top_k:
                break

        status = "candidates_ready" if question_evidence and not missing_docs else "partial_candidates"
        if not question_evidence:
            status = "no_candidates"
        rows.append(
            {
                "schema_version": "agent_evidence_seed_v1",
                "qid": qid,
                "domain": question.get("domain"),
                "split": question.get("split"),
                "type": question.get("type"),
                "answer_format": question.get("answer_format"),
                "question": question_text,
                "options": options,
                "doc_ids": doc_ids,
                "selection": question.get("selection"),
                "search_plan": domain_search_playbook(str(question.get("domain")), str(question.get("answer_format"))),
                "retrieval_query_terms": {
                    "question_keyphrases": keyphrases(question_text),
                    "option_keyphrases": {label: keyphrases(text) for label, text in options.items()},
                    "numbers": sorted(set(numbers(question_text + "\n" + "\n".join(options.values())))),
                    "years": sorted(set(years(question_text + "\n" + "\n".join(options.values())))),
                },
                "candidate_source_docs": source_docs,
                "missing_candidate_docs": missing_docs,
                "support_status": status,
                "answer_draft": None,
                "answer_source": "needs_agent_or_llm_judge",
                "reasoning_trace_template": [
                    "1. 逐 doc_id 定位与选项字段最贴近的证据段。",
                    "2. 为每个选项记录 support/refute/insufficient 及对应 unit_id/page。",
                    "3. 对比较/计算题先抽取结构化数值，再做比较或代入公式。",
                    "4. 最终答案只由被标为 support 的选项组成；证据不足则打 needs_review。",
                ],
                "option_evidence": option_evidence,
                "question_evidence": question_evidence,
                "annotation_todo": {
                    "fill_fields": [
                        "answer_draft",
                        "option_judgement.<A-D>.label",
                        "option_judgement.<A-D>.rationale",
                        "option_judgement.<A-D>.evidence_unit_ids",
                        "confidence",
                    ],
                    "labels": ["support", "refute", "insufficient"],
                },
            }
        )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions-dir", default="data/questions/group_a")
    parser.add_argument("--manifest", default="processed_data/manifests/group_a_question_docs.jsonl")
    parser.add_argument("--nonpdf-manifest", default="processed_data/manifests/group_a_question_nonpdf.jsonl")
    parser.add_argument("--selector", default="processed_data/selector/group_a_selector_search.jsonl")
    parser.add_argument("--output-dir", default="processed_data/agent_evidence_seed")
    parser.add_argument("--output-prefix", default="group_a_half")
    parser.add_argument("--per-domain", type=int, default=10)
    parser.add_argument("--max-text-chars", type=int, default=1400)
    parser.add_argument("--overlap", type=int, default=180)
    parser.add_argument("--option-top-k", type=int, default=6)
    parser.add_argument("--question-top-k", type=int, default=14)
    parser.add_argument("--max-quote-chars", type=int, default=900)
    parser.add_argument(
        "--append-fallback",
        action="store_true",
        help="Append raw fallback candidates even when selector candidates already exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    questions = read_questions(Path(args.questions_dir), per_domain=args.per_domain)
    manifest = load_manifest(Path(args.manifest))
    manifest.update(load_manifest(Path(args.nonpdf_manifest)))
    by_doc, corpus_report = build_corpus(
        questions,
        manifest=manifest,
        selector_path=Path(args.selector),
        max_text_chars=args.max_text_chars,
        overlap=args.overlap,
        prefer_selector=not args.append_fallback,
    )
    annotations = annotate_questions(
        questions,
        by_doc,
        option_top_k=args.option_top_k,
        question_top_k=args.question_top_k,
        max_quote_chars=args.max_quote_chars,
    )

    out_dir = Path(args.output_dir)
    prefix = args.output_prefix
    selected_path = out_dir / f"{prefix}_questions.jsonl"
    annotation_path = out_dir / f"{prefix}_agent_annotations.jsonl"
    report_path = out_dir / f"{prefix}_agent_evidence_report.json"
    report_md_path = out_dir / f"{prefix}_agent_evidence_report.md"

    selected_rows = [
        {
            "qid": q.get("qid"),
            "domain": q.get("domain"),
            "split": q.get("split"),
            "type": q.get("type"),
            "answer_format": q.get("answer_format"),
            "question": q.get("question"),
            "options": q.get("options"),
            "doc_ids": q.get("doc_ids"),
            "selection": q.get("selection"),
        }
        for q in questions
    ]
    selected_count = write_jsonl(selected_path, selected_rows)
    annotation_count = write_jsonl(annotation_path, annotations)

    by_domain = Counter(str(q.get("domain")) for q in questions)
    by_status = Counter(str(row.get("support_status")) for row in annotations)
    missing_by_qid = {
        row["qid"]: row["missing_candidate_docs"]
        for row in annotations
        if row.get("missing_candidate_docs")
    }
    report = {
        "tool": "06_build_agent_evidence_seed.py",
        "selection": {
            "strategy": "balanced_first_n_per_domain",
            "per_domain": args.per_domain,
            "questions": selected_count,
            "by_domain": dict(sorted(by_domain.items())),
        },
        "settings": {
            "max_text_chars": args.max_text_chars,
            "overlap": args.overlap,
            "option_top_k": args.option_top_k,
            "question_top_k": args.question_top_k,
            "max_quote_chars": args.max_quote_chars,
            "append_fallback": args.append_fallback,
        },
        "corpus": corpus_report,
        "annotations": {
            "rows": annotation_count,
            "by_support_status": dict(sorted(by_status.items())),
            "missing_candidate_docs_by_qid": missing_by_qid,
        },
        "outputs": {
            "selected_questions": str(selected_path.resolve()),
            "agent_annotations": str(annotation_path.resolve()),
            "report": str(report_path.resolve()),
            "markdown": str(report_md_path.resolve()),
        },
    }
    write_json(report_path, report)

    md_lines = [
        "# Group A Half-Question Agent Evidence Seed",
        "",
        f"- Selected questions: {selected_count}",
        f"- Selection: first {args.per_domain} per domain, balanced across {len(by_domain)} domains",
        f"- Candidate docs: {corpus_report['docs_with_candidates']}/{corpus_report['selected_doc_ids']}",
        f"- Candidate units: {corpus_report['candidate_units']}",
        f"- Support status: {dict(sorted(by_status.items()))}",
        "",
        "Outputs:",
        "",
        f"- `{selected_path}`",
        f"- `{annotation_path}`",
        f"- `{report_path}`",
        "",
        "Annotation schema:",
        "",
        "- `answer_draft` is intentionally empty until an agent/LLM judge verifies option evidence.",
        "- `option_evidence` stores top evidence candidates per option with `doc_id`, `unit_id`, `page_id`, text, score, score features, and locator.",
        "- `question_evidence` is a compact merged evidence pack for answer judging.",
        "- `search_plan` records the reusable evidence-seeking playbook for the domain.",
        "",
    ]
    if missing_by_qid:
        md_lines.extend(["Questions with missing candidate docs:", ""])
        for qid, doc_ids in sorted(missing_by_qid.items()):
            md_lines.append(f"- `{qid}`: {', '.join(doc_ids)}")
    report_md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(json.dumps({"selected": selected_count, "annotations": annotation_count, "status": dict(by_status)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
