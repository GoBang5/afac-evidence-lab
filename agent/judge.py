"""Judgement nodes.

V0 ships model-free judges only.  Qwen/GLM integrations should be added here
with explicit caller authorization and token accounting.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .model_client import OpenAICompatibleClient, load_env_file, resolve_env
from .prompting import build_judge_messages
from .schema import AgentConfig, JudgeOutput, Question
from .verify import valid_letters


class BaseJudge:
    mode = "base"

    def judge(self, question: Question, packed_evidence: list[dict[str, Any]]) -> JudgeOutput:
        raise NotImplementedError


class NoModelJudge(BaseJudge):
    mode = "none"

    def judge(self, question: Question, packed_evidence: list[dict[str, Any]]) -> JudgeOutput:
        option_judgement = {
            label: {
                "verdict": "UNKNOWN",
                "evidence_ids": [],
                "reason": "V0 none judge only builds evidence; model judgement was not run.",
            }
            for label in sorted(question.options)
        }
        return JudgeOutput(
            mode=self.mode,
            answer_raw="",
            option_judgement=option_judgement,
            confidence="none",
            status="needs_model_judge",
            warnings=["model_judge_not_run"],
        )


class PriorCsvJudge(BaseJudge):
    mode = "prior_csv"

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers

    def judge(self, question: Question, packed_evidence: list[dict[str, Any]]) -> JudgeOutput:
        answer = self.answers.get(question.qid, "")
        selected = set(valid_letters(answer))
        option_judgement: dict[str, dict[str, Any]] = {}
        for label in sorted(question.options):
            evidence_ids = [
                int(row["evidence_id"])
                for row in packed_evidence
                if label in (row.get("support_options") or row.get("retrieval_options") or [])
            ][:3]
            verdict = "TRUE" if label in selected else "FALSE"
            option_judgement[label] = {
                "verdict": verdict,
                "evidence_ids": evidence_ids,
                "reason": "Imported from prior answer CSV; evidence ids are retrieval candidates, not a fresh model proof.",
            }
        return JudgeOutput(
            mode=self.mode,
            answer_raw=answer,
            option_judgement=option_judgement,
            confidence="prior",
            status="prior_answer_imported",
            warnings=["prior_answer_not_official_judgement"],
        )


class ModelJudge(BaseJudge):
    def __init__(self, mode: str, config: AgentConfig) -> None:
        self.mode = mode
        self.config = config
        if mode == "qwen" and not config.allow_qwen:
            raise RuntimeError("Qwen judge requires --allow-qwen after explicit user authorization.")
        env_values = load_env_file(config.env_file)
        base_url = config.llm_base_url or default_base_url(mode, env_values)
        api_key_env = config.llm_api_key_env or default_api_key_env(mode)
        model_env = config.llm_model_env or default_model_env(mode)
        api_key = resolve_env(api_key_env, env_values)
        model = config.llm_model or resolve_env(model_env, env_values) or default_model_name(mode)
        missing: list[str] = []
        if not base_url:
            missing.append("llm_base_url")
        if not api_key:
            missing.append(f"api key env {api_key_env}")
        if not model:
            missing.append(f"model or model env {model_env}")
        if missing:
            raise RuntimeError("missing model judge configuration: " + ", ".join(missing))
        self.client = OpenAICompatibleClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=config.llm_timeout,
        )

    def judge(self, question: Question, packed_evidence: list[dict[str, Any]]) -> JudgeOutput:
        messages = build_judge_messages(question, packed_evidence)
        response = self.client.chat(
            messages=messages,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
        )
        parsed, parse_warnings = parse_json_object(response.text)
        if parsed is None:
            return JudgeOutput(
                mode=self.mode,
                answer_raw="",
                option_judgement=unknown_judgements(question, "Model response was not valid JSON."),
                confidence="low",
                status="judge_json_invalid",
                model=response.model,
                raw_response=response.text,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                warnings=["judge_json_invalid", *parse_warnings],
            )

        option_judgement = normalize_option_judgement(question, parsed.get("option_judgement"))
        answer = str(parsed.get("answer") or "")
        confidence = str(parsed.get("confidence") or "medium")
        warnings = [str(item) for item in parsed.get("warnings") or [] if str(item)]
        warnings.extend(parse_warnings)
        if response.usage.total_tokens <= 0:
            warnings.append("token_usage_missing")
        return JudgeOutput(
            mode=self.mode,
            answer_raw=answer,
            option_judgement=option_judgement,
            confidence=confidence,
            status="model_judged",
            model=response.model,
            raw_response=response.text,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            warnings=warnings,
        )


def default_base_url(mode: str, env_values: dict[str, str]) -> str | None:
    if mode == "qwen":
        return (
            resolve_env("QWEN_BASE_URL", env_values)
            or resolve_env("QWEN_API_URL", env_values)
            or resolve_env("DASHSCOPE_BASE_URL", env_values)
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    if mode == "glm":
        return (
            resolve_env("GLM_BASE_URL", env_values)
            or resolve_env("GLM_API_URL", env_values)
            or resolve_env("ZHIPU_BASE_URL", env_values)
            or "https://open.bigmodel.cn/api/paas/v4"
        )
    return resolve_env("OPENAI_COMPATIBLE_BASE_URL", env_values)


def default_api_key_env(mode: str) -> str:
    if mode == "qwen":
        return "QWEN_API_KEY"
    if mode == "glm":
        return "GLM_API_KEY"
    return "OPENAI_COMPATIBLE_API_KEY"


def default_model_env(mode: str) -> str:
    if mode == "qwen":
        return "QWEN_MODEL"
    if mode == "glm":
        return "GLM_MODEL"
    return "OPENAI_COMPATIBLE_MODEL"


def default_model_name(mode: str) -> str | None:
    if mode == "glm":
        return "GLM-5V-Turbo"
    return None


def unknown_judgements(question: Question, reason: str) -> dict[str, dict[str, Any]]:
    return {
        label: {"verdict": "UNKNOWN", "evidence_ids": [], "reason": reason}
        for label in sorted(question.options)
    }


def normalize_option_judgement(question: Question, raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return unknown_judgements(question, "Missing option_judgement object.")
    out: dict[str, dict[str, Any]] = {}
    for label in sorted(question.options):
        item = raw.get(label)
        if not isinstance(item, dict):
            out[label] = {"verdict": "UNKNOWN", "evidence_ids": [], "reason": "Missing judgement for option."}
            continue
        verdict = str(item.get("verdict") or "UNKNOWN").upper()
        if verdict not in {"TRUE", "FALSE", "UNKNOWN"}:
            verdict = "UNKNOWN"
        evidence_ids: list[int] = []
        for value in item.get("evidence_ids") or []:
            try:
                evidence_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        out[label] = {
            "verdict": verdict,
            "evidence_ids": evidence_ids,
            "reason": str(item.get("reason") or "")[:500],
        }
    return out


def parse_json_object(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    raw = (text or "").strip()
    if not raw:
        return None, ["judge_response_empty"]
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None, []
    except json.JSONDecodeError:
        warnings.append("judge_response_required_json_extraction")
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return None, warnings
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, warnings
    return parsed if isinstance(parsed, dict) else None, warnings


def make_judge(
    mode: str,
    prior_answers: dict[str, str] | None = None,
    config: AgentConfig | None = None,
) -> BaseJudge:
    if mode == "none":
        return NoModelJudge()
    if mode == "prior_csv":
        return PriorCsvJudge(prior_answers or {})
    if mode in {"qwen", "glm", "openai_compatible"}:
        if config is None:
            raise RuntimeError("model judge requires AgentConfig")
        return ModelJudge(mode, config)
    raise ValueError(f"unknown judge mode: {mode}")
