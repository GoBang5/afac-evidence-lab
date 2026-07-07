"""Deterministic lexical retrieval for AFAC2026-4.

The official competition path forbids embedding retrieval.  This module keeps
retrieval auditable: token overlap, exact phrases, numbers, clauses, sections,
quality metadata, and document-position hints.
"""

from __future__ import annotations

import math
import re
import hashlib
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .domain_rules import profile_for
from .io_utils import iter_jsonl
from .schema import Candidate, Question, QuestionFeatures, ScoredEvidence
from .text import char_ngrams, clauses, clean_text, keyphrases, normalize_for_match, numbers, token_counts, tokenize, years


FIRST_DOC_RE = re.compile(r"第一份|首份|前一份|第一[个家]")
SECOND_DOC_RE = re.compile(r"第二份|后一份|另一份|第二[个家]")


class CandidateIndex:
    def __init__(
        self,
        candidates_by_doc: dict[str, list[Candidate]],
        docs_by_id: dict[str, dict[str, Any]],
    ) -> None:
        self.candidates_by_doc = candidates_by_doc
        self.docs_by_id = docs_by_id
        self.doc_domain = {
            doc_id: str(meta.get("domain") or "")
            for doc_id, meta in docs_by_id.items()
        }
        for doc_id, candidates in candidates_by_doc.items():
            if doc_id not in self.doc_domain and candidates:
                self.doc_domain[doc_id] = candidates[0].locator.get("domain", "")
        self._token_cache: dict[str, Counter[str]] = {}
        self._norm_cache: dict[str, str] = {}
        self._bigram_cache: dict[str, set[str]] = {}
        self._doc_reprs: dict[str, str] = {}
        self._doc_token_cache: dict[str, Counter[str]] = {}

    @classmethod
    def from_paths(
        cls,
        selector_path: str | Path,
        docs_path: str | Path,
        include_tables: bool = True,
        enable_raw_fallback: bool = True,
        raw_max_chars: int = 1400,
        raw_overlap: int = 180,
    ) -> "CandidateIndex":
        docs_by_id = {
            str(row.get("doc_id") or ""): row
            for row in iter_jsonl(docs_path)
            if row.get("doc_id")
        }
        candidates_by_doc: dict[str, list[Candidate]] = defaultdict(list)
        for row in iter_jsonl(selector_path):
            cand = Candidate.from_selector_row(row)
            cand.text = clean_text(cand.text)
            if not cand.doc_id or not cand.text:
                continue
            if not include_tables and cand.unit_type == "table":
                continue
            candidates_by_doc[cand.doc_id].append(cand)
        if enable_raw_fallback:
            for doc_id, row in docs_by_id.items():
                if candidates_by_doc.get(doc_id):
                    continue
                for cand in raw_fallback_candidates(row, max_chars=raw_max_chars, overlap=raw_overlap):
                    candidates_by_doc[doc_id].append(cand)
        for doc_id in list(candidates_by_doc):
            candidates_by_doc[doc_id].sort(
                key=lambda item: (
                    item.page_id if item.page_id is not None else 10**9,
                    item.reading_order if item.reading_order is not None else 10**9,
                    item.candidate_id,
                )
            )
        return cls(dict(candidates_by_doc), docs_by_id)

    def candidate_count(self) -> int:
        return sum(len(rows) for rows in self.candidates_by_doc.values())

    def docs(self) -> list[str]:
        return sorted(self.candidates_by_doc)

    def get_candidates(self, doc_ids: list[str]) -> list[Candidate]:
        return [cand for doc_id in doc_ids for cand in self.candidates_by_doc.get(doc_id, [])]

    def route_docs(self, question: Question, top_k: int) -> tuple[list[str], list[str]]:
        if question.doc_ids:
            missing = [doc_id for doc_id in question.doc_ids if doc_id not in self.candidates_by_doc]
            return question.doc_ids, missing

        query = "\n".join([question.question, *question.options.values()])
        query_tokens = token_counts(query)
        scores: list[tuple[float, str]] = []
        for doc_id in self.docs():
            if question.domain and self.doc_domain.get(doc_id) and self.doc_domain.get(doc_id) != question.domain:
                continue
            doc_text = self.doc_repr(doc_id)
            doc_counts = self.doc_token_counts(doc_id)
            score = 0.0
            for token, q_count in query_tokens.items():
                if doc_counts.get(token):
                    score += min(q_count, 3) * (1.0 + math.log1p(doc_counts[token]))
            doc_norm = normalize_for_match(doc_text)
            for phrase in keyphrases(query, limit=30):
                if normalize_for_match(phrase) in doc_norm:
                    score += 2.0
            if score > 0:
                scores.append((score, doc_id))
        scores.sort(reverse=True)
        return [doc_id for _, doc_id in scores[:top_k]], []

    def doc_repr(self, doc_id: str) -> str:
        if doc_id in self._doc_reprs:
            return self._doc_reprs[doc_id]
        meta = self.docs_by_id.get(doc_id, {})
        parts = [
            str(meta.get("doc_id") or ""),
            " ".join(doc_aliases(doc_id, str(meta.get("domain") or ""))),
            str(meta.get("domain") or ""),
            str(meta.get("source_title") or ""),
            str(meta.get("source_kind") or ""),
        ]
        seen_sections: set[str] = set()
        for cand in self.candidates_by_doc.get(doc_id, [])[:200]:
            if cand.section_title and cand.section_title not in seen_sections:
                seen_sections.add(cand.section_title)
                parts.append(cand.section_title)
            if len(" ".join(parts)) < 6000:
                parts.append(cand.text[:300])
        value = clean_text("\n".join(parts))
        self._doc_reprs[doc_id] = value
        return value

    def doc_token_counts(self, doc_id: str) -> Counter[str]:
        cached = self._doc_token_cache.get(doc_id)
        if cached is not None:
            return cached
        meta = self.docs_by_id.get(doc_id, {})
        counts = token_counts(
            "\n".join(
                [
                    str(meta.get("doc_id") or ""),
                    " ".join(doc_aliases(doc_id, str(meta.get("domain") or ""))),
                    str(meta.get("domain") or ""),
                    str(meta.get("source_title") or ""),
                    str(meta.get("source_kind") or ""),
                    str(meta.get("source_path") or ""),
                ]
            )
        )
        for cand in self.candidates_by_doc.get(doc_id, []):
            counts.update(self.token_counts_for(cand))
        self._doc_token_cache[doc_id] = counts
        return counts

    def token_counts_for(self, cand: Candidate) -> Counter[str]:
        cached = self._token_cache.get(cand.candidate_id)
        if cached is not None:
            return cached
        counts = token_counts("\n".join([cand.section_title, cand.text]))
        self._token_cache[cand.candidate_id] = counts
        return counts

    def norm_for(self, cand: Candidate) -> str:
        cached = self._norm_cache.get(cand.candidate_id)
        if cached is not None:
            return cached
        value = normalize_for_match(cand.text)
        self._norm_cache[cand.candidate_id] = value
        return value

    def bigrams_for(self, cand: Candidate) -> set[str]:
        cached = self._bigram_cache.get(cand.candidate_id)
        if cached is not None:
            return cached
        value = char_ngrams(cand.text, 2)
        self._bigram_cache[cand.candidate_id] = value
        return value


def build_local_idf(candidates: list[Candidate], index: CandidateIndex) -> dict[str, float]:
    df: Counter[str] = Counter()
    for cand in candidates:
        df.update(set(index.token_counts_for(cand)))
    n = max(1, len(candidates))
    return {token: math.log((n + 1) / (count + 0.5)) + 1.0 for token, count in df.items()}


def doc_aliases(doc_id: str, domain: str) -> list[str]:
    aliases = {doc_id}
    match = re.fullmatch(r"text0*(\d+)", doc_id)
    if match:
        number = int(match.group(1))
        aliases.update({f"text{number}", f"text{number:02d}", f"text{number:03d}"})
        if domain == "financial_contracts":
            aliases.update(
                {
                    f"fc_text_{number}",
                    f"fc_text_{number:02d}",
                    f"fc_text_{number:03d}",
                    f"financial_contracts_text_{number:03d}",
                }
            )
    if doc_id.isdigit():
        number = int(doc_id)
        aliases.update({str(number), f"{number:02d}", f"{number:03d}"})
        if domain == "insurance":
            aliases.update({f"ins_{number}", f"insurance_{number}", f"保险{number}"})
    return sorted(aliases)


def _doc_position_bonus(question: Question, option_text: str, cand: Candidate) -> float:
    if not question.doc_ids:
        return 0.0
    if FIRST_DOC_RE.search(option_text):
        return 6.0 if cand.doc_id == question.doc_ids[0] else -1.5
    if SECOND_DOC_RE.search(option_text) and len(question.doc_ids) >= 2:
        return 6.0 if cand.doc_id == question.doc_ids[1] else -1.5
    return 0.0


def build_query_features(query: str, option_text: str) -> dict[str, Any]:
    return {
        "q_counts": token_counts(query),
        "q_bigrams": char_ngrams(query, 2),
        "q_numbers": set(numbers(query)),
        "q_years": set(years(query)),
        "q_clauses": set(clauses(query)),
        "option_norm": normalize_for_match(option_text),
        "option_phrases": [
            phrase
            for phrase in keyphrases(option_text, limit=30)
            if len(normalize_for_match(phrase)) >= 3
        ],
    }


def score_candidate(
    index: CandidateIndex,
    cand: Candidate,
    query: str,
    question: Question,
    features: QuestionFeatures,
    idf: dict[str, float],
    option_text: str,
    query_features: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    query_features = query_features or build_query_features(query, option_text)
    q_counts = query_features["q_counts"]
    c_counts = index.token_counts_for(cand)
    token_score = 0.0
    matched_tokens: list[str] = []
    for token, q_count in q_counts.items():
        tf = c_counts.get(token)
        if tf:
            matched_tokens.append(token)
            token_score += (1.0 + math.log1p(tf)) * idf.get(token, 1.0) * min(q_count, 3)

    q_bigrams = query_features["q_bigrams"]
    c_bigrams = index.bigrams_for(cand)
    bigram_overlap = len(q_bigrams & c_bigrams)
    bigram_score = bigram_overlap / max(8, len(q_bigrams)) * 8.0

    q_numbers = query_features["q_numbers"]
    c_numbers = set(cand.numbers) | set(numbers(cand.text))
    matched_numbers = sorted(q_numbers & c_numbers)
    number_score = 2.5 * len(matched_numbers)

    q_years = query_features["q_years"]
    c_years = set(years(cand.text))
    matched_years = sorted(q_years & c_years)
    year_score = 1.5 * len(matched_years)

    q_clauses = query_features["q_clauses"]
    c_clauses = set(clauses(cand.text))
    matched_clauses = sorted(q_clauses & c_clauses)
    clause_score = 3.0 * len(matched_clauses)

    cand_norm = index.norm_for(cand)
    option_norm = query_features["option_norm"]
    literal_score = 0.0
    if option_norm and len(option_norm) >= 8 and option_norm in cand_norm:
        literal_score += 16.0

    phrase_hits = []
    for phrase in query_features["option_phrases"]:
        phrase_norm = normalize_for_match(phrase)
        if phrase_norm in cand_norm:
            phrase_hits.append(phrase)
    phrase_score = 1.5 * len(phrase_hits)

    section_norm = normalize_for_match(cand.section_title)
    section_hits = [
        term for term in features.domain_terms
        if normalize_for_match(term) and normalize_for_match(term) in section_norm
    ]
    section_score = 1.2 * len(section_hits)

    profile = profile_for(question.domain)
    domain_hits = [
        term for term in profile.keywords
        if normalize_for_match(term) and normalize_for_match(term) in cand_norm
    ]
    domain_score = 0.35 * len(domain_hits)

    unit_bonus = 0.0
    if cand.unit_type == "heading":
        unit_bonus += 0.5
    if cand.unit_type == "table" or cand.modality == "table":
        unit_bonus += 1.2
    if cand.evidence_role == "primary":
        unit_bonus += 0.5

    quality_bonus = max(0.0, min(cand.evidence_weight, 1.0)) * 0.8
    position_bonus = _doc_position_bonus(question, option_text, cand)

    score = (
        token_score
        + bigram_score
        + number_score
        + year_score
        + clause_score
        + literal_score
        + phrase_score
        + section_score
        + domain_score
        + unit_bonus
        + quality_bonus
        + position_bonus
    )
    return score, {
        "token_score": round(token_score, 4),
        "bigram_score": round(bigram_score, 4),
        "number_score": round(number_score, 4),
        "year_score": round(year_score, 4),
        "clause_score": round(clause_score, 4),
        "literal_score": round(literal_score, 4),
        "phrase_score": round(phrase_score, 4),
        "section_score": round(section_score, 4),
        "domain_score": round(domain_score, 4),
        "unit_bonus": round(unit_bonus, 4),
        "quality_bonus": round(quality_bonus, 4),
        "position_bonus": round(position_bonus, 4),
        "matched_tokens": matched_tokens[:35],
        "matched_numbers": matched_numbers,
        "matched_years": matched_years,
        "matched_clauses": matched_clauses,
        "matched_option_phrases": phrase_hits[:25],
        "matched_domain_terms": domain_hits[:25],
    }


def retrieve_option_evidence(
    index: CandidateIndex,
    question: Question,
    features: QuestionFeatures,
    candidate_docs: list[str],
    option_queries: dict[str, str],
    option_top_k: int,
) -> dict[str, list[ScoredEvidence]]:
    candidates = index.get_candidates(candidate_docs)
    idf = build_local_idf(candidates, index)
    out: dict[str, list[ScoredEvidence]] = {}
    for label, query in sorted(option_queries.items()):
        option_text = question.options.get(label, "")
        query_features = build_query_features(query, option_text)
        scored: list[ScoredEvidence] = []
        for cand in candidates:
            score, score_features = score_candidate(
                index=index,
                cand=cand,
                query=query,
                question=question,
                features=features,
                idf=idf,
                option_text=option_text,
                query_features=query_features,
            )
            if score > 0:
                scored.append(ScoredEvidence(cand, score, score_features, option=label))
        scored.sort(key=lambda item: item.score, reverse=True)
        out[label] = diversify_by_doc(scored, option_top_k, len(candidate_docs))
    return out


def retrieve_question_evidence(
    index: CandidateIndex,
    question: Question,
    features: QuestionFeatures,
    candidate_docs: list[str],
    query: str,
    question_top_k: int,
) -> list[ScoredEvidence]:
    candidates = index.get_candidates(candidate_docs)
    idf = build_local_idf(candidates, index)
    scored: list[ScoredEvidence] = []
    query_features = build_query_features(query, "")
    for cand in candidates:
        score, score_features = score_candidate(
            index=index,
            cand=cand,
            query=query,
            question=question,
            features=features,
            idf=idf,
            option_text="",
            query_features=query_features,
        )
        if score > 0:
            scored.append(ScoredEvidence(cand, score, score_features, option=None))
    scored.sort(key=lambda item: item.score, reverse=True)
    return diversify_by_doc(scored, question_top_k, len(candidate_docs))


def diversify_by_doc(scored: list[ScoredEvidence], top_k: int, doc_count: int) -> list[ScoredEvidence]:
    if top_k <= 0:
        return []
    picked: list[ScoredEvidence] = []
    seen_ids: set[str] = set()
    seen_docs: set[str] = set()
    for item in scored:
        cid = item.candidate.candidate_id
        if cid in seen_ids:
            continue
        picked.append(item)
        seen_ids.add(cid)
        seen_docs.add(item.candidate.doc_id)
        if len(picked) >= top_k and len(seen_docs) >= min(2, doc_count):
            return picked[:top_k]
        if len(picked) >= top_k + 2:
            break
    return picked[:top_k]


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
        return clean_text("\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip()))


def strip_html(raw: str) -> str:
    parser = TextHTMLParser()
    parser.feed(raw or "")
    return parser.text()


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


def raw_fallback_candidates(doc_row: dict[str, Any], max_chars: int, overlap: int) -> list[Candidate]:
    doc_id = str(doc_row.get("doc_id") or "")
    source_path = Path(str(doc_row.get("source_path") or ""))
    suffix = source_path.suffix.lower()
    if not doc_id or not source_path.exists() or suffix not in {".txt", ".md", ".html", ".htm"}:
        return []
    raw = source_path.read_text(encoding="utf-8", errors="ignore")
    text = strip_html(raw) if suffix in {".html", ".htm"} else clean_text(raw)
    out: list[Candidate] = []
    for index, (start, end, span) in enumerate(split_text(text, max_chars=max_chars, overlap=overlap), 1):
        digest = hashlib.sha1(f"{doc_id}:{start}:{end}:{span[:200]}".encode("utf-8")).hexdigest()[:12]
        unit_id = f"{doc_id}::raw::{index:06d}"
        out.append(
            Candidate(
                candidate_id=f"{unit_id}:{digest}",
                unit_id=unit_id,
                doc_id=doc_id,
                text=span,
                page_id=None,
                section_title="",
                unit_type="raw_text",
                modality="text",
                evidence_role="primary",
                quality_tier="normal",
                quality_flags=[],
                evidence_weight=1.0,
                numbers=numbers(span),
                locator={
                    "doc_id": doc_id,
                    "domain": doc_row.get("domain"),
                    "source_type": "raw_text_fallback",
                    "source_path": str(source_path),
                    "char_start": start,
                    "char_end": end,
                },
                source_name=f"raw_fallback:{doc_row.get('source_kind') or suffix.lstrip('.')}",
                reading_order=index,
            )
        )
    return out
