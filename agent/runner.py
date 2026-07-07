"""Agent runner that wires parsing, retrieval, packing, judgement, and audit."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .domain_rules import build_option_queries, build_search_plan, extract_question_features
from .io_utils import read_jsonl, read_prior_answers, write_answer_csv, write_json, write_jsonl
from .judge import make_judge
from .packer import pack_evidence
from .repair import build_repair_queries, is_repairable, merge_option_evidence
from .retrieval import CandidateIndex, retrieve_option_evidence, retrieve_question_evidence
from .schema import AgentConfig, AgentResult, Question
from .verify import normalize_answer, verify_result


class AgentRunner:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.index = CandidateIndex.from_paths(
            selector_path=config.selector_path,
            docs_path=config.docs_path,
            include_tables=config.include_tables,
        )
        prior_answers = read_prior_answers(config.prior_answers_csv) if config.prior_answers_csv else {}
        self.judge = make_judge(config.judge_mode, prior_answers=prior_answers, config=config)

    def load_questions(self) -> list[Question]:
        questions = [Question.from_row(row) for row in read_jsonl(self.config.questions_path)]
        if self.config.split:
            questions = [q for q in questions if q.split == self.config.split]
        if self.config.qids:
            wanted = set(self.config.qids)
            questions = [q for q in questions if q.qid in wanted]
        if self.config.limit is not None:
            questions = questions[: self.config.limit]
        return questions

    def run_question(self, question: Question) -> AgentResult:
        features = extract_question_features(question)
        candidate_docs, missing_docs = self.index.route_docs(question, self.config.doc_top_k_b)
        if missing_docs:
            features.warnings.append("missing_candidate_docs:" + ",".join(missing_docs))

        search_plan = build_search_plan(question, features)
        option_queries = build_option_queries(question, features)
        option_evidence = retrieve_option_evidence(
            index=self.index,
            question=question,
            features=features,
            candidate_docs=candidate_docs,
            option_queries=option_queries,
            option_top_k=self.config.option_top_k,
        )
        question_query = "\n".join([question.question, " ".join(features.keyphrases), " ".join(features.domain_terms)])
        question_evidence = retrieve_question_evidence(
            index=self.index,
            question=question,
            features=features,
            candidate_docs=candidate_docs,
            query=question_query,
            question_top_k=self.config.question_top_k,
        )
        option_rows, packed = pack_evidence(option_evidence, question_evidence, self.config)
        judge_output = self.judge.judge(question, packed)
        answer_norm, norm_warnings = normalize_answer(judge_output.answer_raw, question.answer_format)
        judge_output.warnings.extend(norm_warnings)
        cumulative_prompt_tokens = judge_output.prompt_tokens
        cumulative_completion_tokens = judge_output.completion_tokens
        cumulative_total_tokens = judge_output.total_tokens
        status, warnings, needs_review = verify_result(
            question=question,
            features=features,
            judge=judge_output,
            answer_norm=answer_norm,
            packed_evidence=packed,
            candidate_docs=candidate_docs,
        )
        repair_log: list[dict[str, Any]] = []
        for repair_round in range(1, self.config.max_repair_rounds + 1):
            if self.config.judge_mode == "none" or not is_repairable(needs_review, warnings):
                break
            repair_queries = build_repair_queries(
                question=question,
                features=features,
                option_queries=option_queries,
                answer_norm=answer_norm,
                needs_review=needs_review,
                warnings=warnings,
                judge_option_judgement=judge_output.option_judgement,
            )
            if not repair_queries:
                break
            before = {
                "status": status,
                "needs_review": list(needs_review),
                "warnings": list(warnings),
                "packed_evidence": len(packed),
            }
            extra_option_evidence = retrieve_option_evidence(
                index=self.index,
                question=question,
                features=features,
                candidate_docs=candidate_docs,
                option_queries=repair_queries,
                option_top_k=self.config.option_top_k + self.config.repair_top_k,
            )
            option_evidence = merge_option_evidence(
                original=option_evidence,
                extra=extra_option_evidence,
                per_option_limit=self.config.option_top_k + self.config.repair_top_k,
            )
            extra_question_query = "\n".join(repair_queries.values())
            extra_question_evidence = retrieve_question_evidence(
                index=self.index,
                question=question,
                features=features,
                candidate_docs=candidate_docs,
                query=extra_question_query,
                question_top_k=self.config.question_top_k + self.config.repair_top_k,
            )
            question_evidence = merge_scored_evidence(
                question_evidence + extra_question_evidence,
                limit=self.config.question_top_k + self.config.repair_top_k,
            )
            option_rows, packed = pack_evidence(option_evidence, question_evidence, self.config)
            judge_output = self.judge.judge(question, packed)
            cumulative_prompt_tokens += judge_output.prompt_tokens
            cumulative_completion_tokens += judge_output.completion_tokens
            cumulative_total_tokens += judge_output.total_tokens
            judge_output.prompt_tokens = cumulative_prompt_tokens
            judge_output.completion_tokens = cumulative_completion_tokens
            judge_output.total_tokens = cumulative_total_tokens
            answer_norm, norm_warnings = normalize_answer(judge_output.answer_raw, question.answer_format)
            judge_output.warnings.extend(norm_warnings)
            status, warnings, needs_review = verify_result(
                question=question,
                features=features,
                judge=judge_output,
                answer_norm=answer_norm,
                packed_evidence=packed,
                candidate_docs=candidate_docs,
            )
            repair_log.append(
                {
                    "round": repair_round,
                    "target_options": sorted(repair_queries),
                    "before": before,
                    "after": {
                        "status": status,
                        "needs_review": list(needs_review),
                        "warnings": list(warnings),
                        "packed_evidence": len(packed),
                    },
                    "repair_query_count": len(repair_queries),
                }
            )
            if not needs_review:
                break
        tokens = {
            "prompt_tokens": judge_output.prompt_tokens,
            "completion_tokens": judge_output.completion_tokens,
            "total_tokens": judge_output.total_tokens,
        }
        return AgentResult(
            run_id=self.config.run_id,
            qid=question.qid,
            domain=question.domain,
            split=question.split,
            answer_format=question.answer_format,
            question=question.question,
            options=question.options,
            doc_ids=question.doc_ids,
            candidate_docs=candidate_docs,
            question_features=features,
            search_plan=search_plan,
            option_queries=option_queries,
            option_evidence=option_rows,
            packed_evidence=packed,
            judge=judge_output,
            answer_raw=judge_output.answer_raw,
            answer_norm=answer_norm,
            confidence=judge_output.confidence,
            status=status,
            warnings=warnings,
            needs_review_reason=needs_review,
            tokens=tokens,
            repair_log=repair_log,
        )

    def run(self) -> dict[str, Any]:
        questions = self.load_questions()
        results = [self.run_question(question) for question in questions]
        self.write_outputs(results)
        return self.summary(results)

    def summary(self, results: list[AgentResult]) -> dict[str, Any]:
        status = Counter(result.status for result in results)
        domains = Counter(result.domain for result in results)
        warnings = Counter(warning for result in results for warning in result.warnings)
        repairs = Counter("repaired" if result.repair_log else "not_repaired" for result in results)
        token_summary = {
            "prompt_tokens": sum(result.tokens["prompt_tokens"] for result in results),
            "completion_tokens": sum(result.tokens["completion_tokens"] for result in results),
            "total_tokens": sum(result.tokens["total_tokens"] for result in results),
        }
        return {
            "run_id": self.config.run_id,
            "questions": len(results),
            "judge_mode": self.config.judge_mode,
            "selector_path": self.config.selector_path,
            "docs_path": self.config.docs_path,
            "candidate_docs": len(self.index.docs()),
            "candidate_units": self.index.candidate_count(),
            "by_status": dict(sorted(status.items())),
            "by_domain": dict(sorted(domains.items())),
            "top_warnings": dict(warnings.most_common(30)),
            "repairs": dict(sorted(repairs.items())),
            "tokens": token_summary,
            "outputs": {
                "answer_csv": str(Path(self.config.output_dir) / "answer.csv"),
                "evidence_json": str(Path(self.config.output_dir) / "evidence.json"),
                "questions_jsonl": str(Path(self.config.output_dir) / "questions.jsonl"),
                "needs_review_jsonl": str(Path(self.config.output_dir) / "needs_review.jsonl"),
                "summary_json": str(Path(self.config.output_dir) / "summary.json"),
            },
        }

    def write_outputs(self, results: list[AgentResult]) -> None:
        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        result_dicts = [result.to_dict() for result in results]
        write_jsonl(out_dir / "questions.jsonl", result_dicts)
        write_jsonl(
            out_dir / "needs_review.jsonl",
            [row for row in result_dicts if row.get("needs_review_reason")],
        )
        evidence_json = {
            result.qid: {
                "answer": result.answer_norm,
                "answer_raw": result.answer_raw,
                "judge_mode": result.judge.mode,
                "judge_model": result.judge.model,
                "status": result.status,
                "evidence": result.packed_evidence,
                "option_judgement": result.judge.option_judgement,
                "warnings": result.warnings,
                "repair_log": result.repair_log,
                "tokens": result.tokens,
            }
            for result in results
        }
        write_json(out_dir / "evidence.json", evidence_json)
        token_summary = {
            "prompt_tokens": sum(result.tokens["prompt_tokens"] for result in results),
            "completion_tokens": sum(result.tokens["completion_tokens"] for result in results),
            "total_tokens": sum(result.tokens["total_tokens"] for result in results),
        }
        write_answer_csv(
            out_dir / "answer.csv",
            [
                {
                    "qid": result.qid,
                    "answer": result.answer_norm,
                    **result.tokens,
                }
                for result in results
            ],
            token_summary,
        )
        write_json(out_dir / "summary.json", self.summary(results))


def merge_scored_evidence(rows: list[Any], limit: int) -> list[Any]:
    by_id: dict[str, Any] = {}
    for item in rows:
        cid = item.candidate.candidate_id
        old = by_id.get(cid)
        if old is None or item.score > old.score:
            by_id[cid] = item
    return sorted(by_id.values(), key=lambda item: item.score, reverse=True)[:limit]
