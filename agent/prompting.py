"""Strict judgement prompt construction."""

from __future__ import annotations

import json
from typing import Any

from .domain_rules import profile_for
from .schema import Question


BASE_SYSTEM_PROMPT = """你是金融长文档选择题判题器。
你只能依据给定证据判断，不能使用常识或外部知识。
逐项判断 A/B/C/D：TRUE 表示证据完整支持，FALSE 表示证据反驳，UNKNOWN 表示证据不足。
多选题只选择 TRUE；单选/判断题若多个选项看似 TRUE，也要在 warnings 中标出冲突。
输出必须是一个 JSON 对象，不要输出 Markdown，不要输出思维链。"""


def compact_evidence(packed_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in packed_evidence:
        rows.append(
            {
                "evidence_id": row.get("evidence_id"),
                "doc_id": row.get("doc_id"),
                "page_id": row.get("page_id"),
                "section_title": row.get("section_title"),
                "unit_type": row.get("unit_type"),
                "support_options": row.get("support_options") or [],
                "text": row.get("text"),
            }
        )
    return rows


def build_judge_messages(question: Question, packed_evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    domain_plan = "\n".join(profile_for(question.domain).evidence_plan)
    payload = {
        "qid": question.qid,
        "domain": question.domain,
        "answer_format": question.answer_format,
        "question": question.question,
        "options": question.options,
        "domain_judgement_notes": domain_plan,
        "evidence": compact_evidence(packed_evidence),
        "required_output_schema": {
            "option_judgement": {
                "A": {"verdict": "TRUE|FALSE|UNKNOWN", "evidence_ids": [1], "reason": "short evidence-grounded reason"},
                "B": {"verdict": "TRUE|FALSE|UNKNOWN", "evidence_ids": [2], "reason": "short evidence-grounded reason"},
                "C": {"verdict": "TRUE|FALSE|UNKNOWN", "evidence_ids": [3], "reason": "short evidence-grounded reason"},
                "D": {"verdict": "TRUE|FALSE|UNKNOWN", "evidence_ids": [4], "reason": "short evidence-grounded reason"},
            },
            "answer": "A|B|C|D or sorted multi letters",
            "confidence": "high|medium|low",
            "warnings": ["optional audit warning"],
        },
    }
    user_prompt = (
        "请基于以下 JSON 负载逐项判题。理由要短，只引用 evidence_id，不能补充外部事实。\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

