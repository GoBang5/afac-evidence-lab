"""Dataclasses shared by the AFAC2026-4 agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AgentConfig:
    selector_path: str = "processed_data/selector/group_a_selector_search.jsonl"
    docs_path: str = "processed_data/docs.jsonl"
    questions_path: str = "processed_data/agent_evidence_seed/group_a_all_questions.jsonl"
    output_dir: str = "runs/agent_v0"
    judge_mode: str = "none"
    prior_answers_csv: str | None = None
    env_file: str | None = None
    llm_base_url: str | None = None
    llm_api_key_env: str | None = None
    llm_model: str | None = None
    llm_model_env: str | None = None
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1536
    llm_timeout: int = 120
    allow_qwen: bool = False
    split: str | None = None
    qids: list[str] = field(default_factory=list)
    limit: int | None = None
    doc_top_k_b: int = 16
    option_top_k: int = 6
    question_top_k: int = 14
    final_evidence_max: int = 18
    min_evidence_per_option: int = 2
    max_repair_rounds: int = 1
    repair_top_k: int = 4
    max_quote_chars: int = 900
    include_tables: bool = True
    run_id: str = "agent_v0"


@dataclass
class Question:
    qid: str
    domain: str
    split: str
    question: str
    options: dict[str, str]
    answer_format: str
    type: str = ""
    doc_ids: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Question":
        return cls(
            qid=str(row.get("qid") or ""),
            domain=str(row.get("domain") or ""),
            split=str(row.get("split") or ""),
            question=str(row.get("question") or ""),
            options={str(k): str(v) for k, v in (row.get("options") or {}).items()},
            answer_format=str(row.get("answer_format") or ""),
            type=str(row.get("type") or ""),
            doc_ids=[str(doc_id) for doc_id in (row.get("doc_ids") or [])],
            raw=row,
        )


@dataclass
class Candidate:
    candidate_id: str
    unit_id: str
    doc_id: str
    text: str
    page_id: int | None
    section_title: str
    unit_type: str
    modality: str
    evidence_role: str
    quality_tier: str
    quality_flags: list[str]
    evidence_weight: float
    numbers: list[str]
    locator: dict[str, Any]
    source_name: str = ""
    reading_order: int | None = None

    @classmethod
    def from_selector_row(cls, row: dict[str, Any]) -> "Candidate":
        def as_int(value: Any) -> int | None:
            if value is None or value == "":
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        weight = row.get("evidence_weight")
        try:
            evidence_weight = float(weight)
        except (TypeError, ValueError):
            evidence_weight = 1.0
        return cls(
            candidate_id=str(row.get("candidate_id") or row.get("unit_id") or ""),
            unit_id=str(row.get("unit_id") or row.get("candidate_id") or ""),
            doc_id=str(row.get("doc_id") or ""),
            text=str(row.get("text") or ""),
            page_id=as_int(row.get("page_id")),
            section_title=str(row.get("section_title") or ""),
            unit_type=str(row.get("unit_type") or ""),
            modality=str(row.get("modality") or ""),
            evidence_role=str(row.get("evidence_role") or ""),
            quality_tier=str(row.get("quality_tier") or ""),
            quality_flags=[str(flag) for flag in (row.get("quality_flags") or [])],
            evidence_weight=evidence_weight,
            numbers=[str(num) for num in (row.get("numbers") or [])],
            locator=dict(row.get("locator") or {}),
            source_name=str(row.get("source_name") or ""),
            reading_order=as_int(row.get("reading_order")),
        )


@dataclass
class QuestionFeatures:
    keyphrases: list[str] = field(default_factory=list)
    option_keyphrases: dict[str, list[str]] = field(default_factory=dict)
    numbers: list[str] = field(default_factory=list)
    years: list[str] = field(default_factory=list)
    clauses: list[str] = field(default_factory=list)
    domain_terms: list[str] = field(default_factory=list)
    task_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ScoredEvidence:
    candidate: Candidate
    score: float
    features: dict[str, Any]
    option: str | None = None

    def to_row(self, max_quote_chars: int) -> dict[str, Any]:
        text = self.candidate.text.strip()
        return {
            "candidate_id": self.candidate.candidate_id,
            "unit_id": self.candidate.unit_id,
            "doc_id": self.candidate.doc_id,
            "page_id": self.candidate.page_id,
            "section_title": self.candidate.section_title,
            "unit_type": self.candidate.unit_type,
            "modality": self.candidate.modality,
            "source_name": self.candidate.source_name,
            "evidence_role": self.candidate.evidence_role,
            "quality_tier": self.candidate.quality_tier,
            "quality_flags": self.candidate.quality_flags,
            "evidence_weight": self.candidate.evidence_weight,
            "score": round(self.score, 4),
            "score_features": self.features,
            "text": text[:max_quote_chars],
            "text_char_count": len(text),
            "locator": self.candidate.locator,
            "retrieval_option": self.option,
        }


@dataclass
class JudgeOutput:
    mode: str
    answer_raw: str
    option_judgement: dict[str, dict[str, Any]]
    confidence: str
    status: str
    model: str = ""
    raw_response: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    run_id: str
    qid: str
    domain: str
    split: str
    answer_format: str
    question: str
    options: dict[str, str]
    doc_ids: list[str]
    candidate_docs: list[str]
    question_features: QuestionFeatures
    search_plan: list[str]
    option_queries: dict[str, str]
    option_evidence: dict[str, list[dict[str, Any]]]
    packed_evidence: list[dict[str, Any]]
    judge: JudgeOutput
    answer_raw: str
    answer_norm: str
    confidence: str
    status: str
    warnings: list[str]
    needs_review_reason: list[str]
    tokens: dict[str, int]
    repair_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
