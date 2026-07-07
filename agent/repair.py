"""One-round supplementary retrieval for low-confidence evidence packs."""

from __future__ import annotations

from typing import Any

from .schema import Question, QuestionFeatures, ScoredEvidence
from .verify import valid_letters

REPAIRABLE_PREFIXES = (
    "selected_option_without_retrieved_evidence",
    "missing_number_in_packed_evidence",
    "missing_year_in_packed_evidence",
    "doc_imbalance_for_cross_document_question",
    "unknown_heavy",
    "answer_empty",
)


def is_repairable(needs_review: list[str], warnings: list[str]) -> bool:
    labels = set(needs_review) | set(warnings)
    return any(any(label.startswith(prefix) for prefix in REPAIRABLE_PREFIXES) for label in labels)


def target_options(
    question: Question,
    answer_norm: str,
    needs_review: list[str],
    judge_option_judgement: dict[str, dict[str, Any]],
) -> list[str]:
    explicit: set[str] = set()
    for reason in needs_review:
        if reason.startswith("selected_option_without_retrieved_evidence:"):
            label = reason.split(":", 1)[1].strip().upper()
            if label in question.options:
                explicit.add(label)
    if explicit:
        return sorted(explicit)

    selected = [label for label in valid_letters(answer_norm) if label in question.options]
    if selected:
        return sorted(set(selected))

    unknown = [
        label
        for label, item in sorted(judge_option_judgement.items())
        if str(item.get("verdict") or "").upper() == "UNKNOWN" and label in question.options
    ]
    if unknown:
        return unknown
    return sorted(question.options)


def build_repair_queries(
    question: Question,
    features: QuestionFeatures,
    option_queries: dict[str, str],
    answer_norm: str,
    needs_review: list[str],
    warnings: list[str],
    judge_option_judgement: dict[str, dict[str, Any]],
) -> dict[str, str]:
    labels = target_options(question, answer_norm, needs_review, judge_option_judgement)
    reasons = set(needs_review) | set(warnings)
    common_terms: list[str] = [
        "补充检索",
        "最小充分证据",
        "原始数值",
        "单位",
        "口径",
        "公式",
        "条款",
        "支持或反驳",
    ]
    if "missing_number_in_packed_evidence" in reasons:
        common_terms.extend(["金额", "比例", "数值", "阈值", "计算", *features.numbers, *features.numbers])
    if "missing_year_in_packed_evidence" in reasons:
        common_terms.extend(["年度", "日期", "期间", *features.years, *features.years])
    if "doc_imbalance_for_cross_document_question" in reasons:
        common_terms.extend(["第一份", "第二份", "两份", "分别", "均", "对比"])
    if features.clauses:
        common_terms.extend(["条款号", *features.clauses, *features.clauses])
    if features.domain_terms:
        common_terms.extend(features.domain_terms)

    repair_queries: dict[str, str] = {}
    suffix = "\n".join(common_terms)
    for label in labels:
        option_text = question.options.get(label, "")
        repair_queries[label] = "\n".join(
            part
            for part in [
                option_queries.get(label, ""),
                f"{label}. {option_text}",
                suffix,
            ]
            if part
        )
    return repair_queries


def merge_option_evidence(
    original: dict[str, list[ScoredEvidence]],
    extra: dict[str, list[ScoredEvidence]],
    per_option_limit: int,
) -> dict[str, list[ScoredEvidence]]:
    merged: dict[str, list[ScoredEvidence]] = {}
    labels = sorted(set(original) | set(extra))
    for label in labels:
        by_id: dict[str, ScoredEvidence] = {}
        for item in original.get(label, []) + extra.get(label, []):
            cid = item.candidate.candidate_id
            old = by_id.get(cid)
            if old is None or item.score > old.score:
                by_id[cid] = item
        rows = sorted(by_id.values(), key=lambda item: item.score, reverse=True)
        merged[label] = rows[:per_option_limit]
    return merged

