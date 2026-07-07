# Agent Design From Answering Strategy

This note turns `answering_strategy.md` into concrete engineering requirements for the AFAC2026-4 agent.

## Core Principle

The agent is an evidence-first option-judgement pipeline, not an open-ended chat agent.

```text
question -> parse -> route docs -> retrieve per option -> pack evidence -> judge options -> verify -> repair/log/output
```

The central object is `option_judgement[A-D]`. The final answer is only a formatting result derived from supported options.

## Strategy To Implementation Mapping

| Strategy guidance | Agent implementation |
| --- | --- |
| Confirm answer format first | `agent.schema.Question.answer_format`, `agent.verify.normalize_answer` |
| Limit document scope | `agent.retrieval.CandidateIndex.route_docs`; A split uses given `doc_ids` |
| Parse subject, indicators, conditions, predicates, numbers | `agent.domain_rules.extract_question_features` |
| Judge A/B/C/D independently | `agent.retrieval.retrieve_option_evidence`, `agent.judge.*Judge` |
| Preserve minimal sufficient evidence | `agent.packer.pack_evidence`, `evidence.json` |
| Domain-specific reading routes | `agent.domain_rules.DOMAIN_PROFILES` |
| Question-type-specific checks | `agent.verify.verify_result` |
| Common mistakes become audit flags | `agent.verify.Warning` values in logs |
| Manual answer template becomes logs | `logs/questions.jsonl` equivalent under run output |

## V0 Scope

V0 intentionally separates evidence construction from model judgement.

- It consumes `processed_data/selector/group_a_selector_search.jsonl` and Group A questions.
- It performs deterministic lexical/rule retrieval only.
- It builds option-level evidence matrices and packed evidence.
- It can run in `none` judge mode, producing `UNKNOWN` option judgements and `needs_review`.
- It can import an existing answer CSV as a prior for continuity, but that is marked as `prior_csv` and is not an official Qwen judgement.
- It does not call Qwen, GLM, embedding models, rerankers, or web services.

## Official Path Boundary

For official submission, the same retrieval and packing code can be reused. The judgement node must be replaced by a Qwen-series judge after explicit user approval, and all model calls must be logged with token usage.

Development priors or GLM diagnostics must not be mixed into an official answer file.

