"""Answer normalization and local audit rules."""

from __future__ import annotations

import re
from typing import Any

from .schema import JudgeOutput, Question, QuestionFeatures
from .text import numbers, years

LETTER_ORDER = "ABCD"
DOC_ID_NUMBER_RE = re.compile(r"\b(?:[A-Za-z]+(?:[_-][A-Za-z]+)*|fc_text|text|doc|pdf)[_-]?\d+\b", re.IGNORECASE)
SCENARIO_DAY_RE = re.compile(r"第\s*([-+]?\d+(?:,\d{3})*(?:\.\d+)?)\s*天")


def valid_letters(answer: str) -> list[str]:
    return [char for char in (answer or "").upper() if char in LETTER_ORDER]


def normalize_answer(answer: str, answer_format: str) -> tuple[str, list[str]]:
    letters = valid_letters(answer)
    warnings: list[str] = []
    if not letters:
        return "", ["answer_empty"]
    if answer_format == "multi":
        return "".join(sorted(set(letters), key=LETTER_ORDER.index)), warnings
    if answer_format in {"mcq", "tf"}:
        if len(set(letters)) > 1:
            warnings.append("format_conflict_multiple_letters_for_single_answer")
        return letters[0], warnings
    warnings.append("unknown_answer_format")
    return "".join(sorted(set(letters), key=LETTER_ORDER.index)), warnings


def required_numbers_for_verification(text: str) -> list[str]:
    scrubbed = DOC_ID_NUMBER_RE.sub(" ", text or "")
    scenario_days = set(SCENARIO_DAY_RE.findall(scrubbed))
    out: list[str] = []
    for value in numbers(scrubbed):
        if value in scenario_days:
            continue
        out.append(value)
    return out


def verify_result(
    question: Question,
    features: QuestionFeatures,
    judge: JudgeOutput,
    answer_norm: str,
    packed_evidence: list[dict[str, Any]],
    candidate_docs: list[str],
) -> tuple[str, list[str], list[str]]:
    warnings = list(features.warnings) + list(judge.warnings)
    needs_review: list[str] = []
    norm_warnings: list[str]
    _, norm_warnings = normalize_answer(judge.answer_raw, question.answer_format)
    warnings.extend(norm_warnings)

    if not answer_norm:
        needs_review.append("answer_empty")

    selected = set(valid_letters(answer_norm))
    evidence_by_option: dict[str, list[dict[str, Any]]] = {label: [] for label in question.options}
    for row in packed_evidence:
        for label in row.get("support_options") or row.get("retrieval_options") or []:
            evidence_by_option.setdefault(label, []).append(row)

    for label in selected:
        if not evidence_by_option.get(label):
            warnings.append(f"selected_option_without_retrieved_evidence:{label}")
            needs_review.append(f"selected_option_without_retrieved_evidence:{label}")

    unknown_count = sum(
        1
        for item in judge.option_judgement.values()
        if str(item.get("verdict") or "").upper() == "UNKNOWN"
    )
    if unknown_count >= 2:
        warnings.append("unknown_heavy")
        needs_review.append("unknown_heavy")

    if question.answer_format == "multi" and answer_norm == "ABCD":
        warnings.append("answer_suspicious_all_options")
        needs_review.append("answer_suspicious_all_options")

    if "cross_document" in features.task_flags and len(candidate_docs) >= 2:
        packed_doc_ids = {str(row.get("doc_id")) for row in packed_evidence if row.get("doc_id")}
        if len(packed_doc_ids) < min(2, len(candidate_docs)):
            warnings.append("doc_imbalance_for_cross_document_question")
            needs_review.append("doc_imbalance_for_cross_document_question")

    evidence_text = "\n".join(str(row.get("text") or "") for row in packed_evidence)
    required_text = question.question
    if selected:
        required_text += "\n" + "\n".join(question.options.get(label, "") for label in sorted(selected))
    else:
        required_text += "\n" + "\n".join(question.options.values())
    required_years = years(required_text)
    required_numbers = required_numbers_for_verification(required_text)
    if required_years and not (set(required_years) & set(years(evidence_text))):
        warnings.append("missing_year_in_packed_evidence")
        needs_review.append("missing_year_in_packed_evidence")
    if required_numbers and not (set(required_numbers) & set(numbers(evidence_text))):
        warnings.append("missing_number_in_packed_evidence")
        needs_review.append("missing_number_in_packed_evidence")

    if "format_conflict_multiple_letters_for_single_answer" in warnings:
        needs_review.append("format_conflict_multiple_letters_for_single_answer")

    if "model_judge_not_run" in warnings:
        status = "needs_model_judge"
    elif needs_review:
        status = "needs_review"
    else:
        status = judge.status
    return status, sorted(set(warnings)), sorted(set(needs_review))
