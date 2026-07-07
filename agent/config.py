"""CLI configuration for the AFAC2026-4 agent."""

from __future__ import annotations

import argparse
from datetime import datetime

from .schema import AgentConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AFAC2026-4 Agent V0.")
    parser.add_argument("--selector", default=AgentConfig.selector_path)
    parser.add_argument("--docs", default=AgentConfig.docs_path)
    parser.add_argument("--questions", default=AgentConfig.questions_path)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--judge-mode", choices=["none", "prior_csv", "glm", "qwen", "openai_compatible"], default="none")
    parser.add_argument("--prior-answers-csv", default=None)
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--llm-base-url", default=None)
    parser.add_argument("--llm-api-key-env", default=None)
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--llm-model-env", default=None)
    parser.add_argument("--llm-temperature", type=float, default=0.0)
    parser.add_argument("--llm-max-tokens", type=int, default=AgentConfig.llm_max_tokens)
    parser.add_argument("--llm-timeout", type=int, default=120)
    parser.add_argument(
        "--allow-qwen",
        action="store_true",
        help="Allow qwen judge calls. Use only after explicit user authorization.",
    )
    parser.add_argument("--split", default=None)
    parser.add_argument("--qid", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--doc-top-k-b", type=int, default=AgentConfig.doc_top_k_b)
    parser.add_argument("--option-top-k", type=int, default=6)
    parser.add_argument("--question-top-k", type=int, default=14)
    parser.add_argument("--final-evidence-max", type=int, default=18)
    parser.add_argument("--min-evidence-per-option", type=int, default=2)
    parser.add_argument("--max-repair-rounds", type=int, default=1)
    parser.add_argument("--repair-top-k", type=int, default=4)
    parser.add_argument("--max-quote-chars", type=int, default=900)
    parser.add_argument("--no-tables", action="store_true")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> AgentConfig:
    run_id = args.run_id or f"agent_v0_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = args.output_dir or f"runs/{run_id}"
    return AgentConfig(
        selector_path=args.selector,
        docs_path=args.docs,
        questions_path=args.questions,
        output_dir=output_dir,
        judge_mode=args.judge_mode,
        prior_answers_csv=args.prior_answers_csv,
        env_file=args.env_file,
        llm_base_url=args.llm_base_url,
        llm_api_key_env=args.llm_api_key_env,
        llm_model=args.llm_model,
        llm_model_env=args.llm_model_env,
        llm_temperature=args.llm_temperature,
        llm_max_tokens=args.llm_max_tokens,
        llm_timeout=args.llm_timeout,
        allow_qwen=args.allow_qwen,
        split=args.split,
        qids=args.qid,
        limit=args.limit,
        doc_top_k_b=args.doc_top_k_b,
        option_top_k=args.option_top_k,
        question_top_k=args.question_top_k,
        final_evidence_max=args.final_evidence_max,
        min_evidence_per_option=args.min_evidence_per_option,
        max_repair_rounds=args.max_repair_rounds,
        repair_top_k=args.repair_top_k,
        max_quote_chars=args.max_quote_chars,
        include_tables=not args.no_tables,
        run_id=run_id,
    )
