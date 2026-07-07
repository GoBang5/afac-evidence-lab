# 2026-07-07 AFAC2026-4 Progress

This file keeps only handoff-useful facts: environment, data shape, key decisions, scripts, outputs, known risks, and next actions.

## Current State

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- primary env: `znh-AFAC2026`, Python 3.12.13
- data root: `data/`, ignored by Git
- generated outputs: `processed_data/`, ignored by Git
- Git branch: `main`
- GitHub remote: `git@github-afac2026-4:AFAC2026-4/4.git`
- GitHub tracking: local `main` tracks `origin/main`
- SSH auth: deploy key alias `github-afac2026-4`; private key is local only and not tracked
- model policy: default dev/eval may use GLM or user-specified models from `/public/home/zhangfanjin/zhangnianhao/.env`; do not call Qwen unless the user explicitly authorizes it

## Data And Environment

Task:

- Prepare AFAC2026-4 workspace, Python env, and public dataset.

Environment:

- conda root: `/public/home/zhangfanjin/miniconda3`
- env path: `/public/home/zhangfanjin/miniconda3/envs/znh-AFAC2026`
- dataset archive: `public_dataset_a.zip`, ignored by Git

Configuration:

- created env with Python 3.12
- no dependency lockfile exists yet
- raw archive was unpacked and renamed from `public_dataset_upload/` to `data/`

Results:

- `data/questions/group_a`: 5 domains x 20 questions = 100 questions
- `data/raw`: 190 PDFs
  - financial contracts: 14
  - financial reports: 10
  - insurance: 16
  - regulatory: 130
  - research: 20
- useful next step: add a dependency file once the final runtime stack is fixed

## Design Decisions

Task:

- Design a long-context QA pipeline for financial multiple-choice questions.

Key decisions:

- Main approach: deterministic preprocessing + rule/BM25 retrieval + option-level evidence pack + LLM judge/verify.
- LangGraph may be used as a light state machine, not as the core retrieval engine.
- Official answer path must obey the competition model constraint; Qwen use requires explicit user approval.
- Dev/eval path may use GLM or other user-configured models for verification, self-evolution, and error diagnosis.
- Do not mix non-Qwen dev/eval outputs into an official Qwen-only submission without a separate official run.

Important document:

- `design.md` contains architecture, data schemas, retrieval strategy, prompts, token tiers, self-evolution loop, and implementation roadmap.

## Preprocessing

Task:

- Parse all Group A question-related documents and export a structured corpus.

Environment:

- MinerU key is expected in `/public/home/zhangfanjin/zhangnianhao/.env` as `MINERU_API_KEY`; key value was never printed.
- Reference code:
  - `/public/home/zhangfanjin/zhangnianhao/01-projects/UniDoc-RL/tools/mineru_parse_folder.py`
  - `/public/home/zhangfanjin/zhangnianhao/01-projects/DocPreprocess/scripts`

Configuration:

- selected docs: 68
- selected PDFs: 59
- selected non-PDF docs: 9
- missing docs: 0
- total selected PDF pages: 7,923
- PDFs <= 200 pages: 38
- PDFs > 200 pages: 21
- long-PDF strategy: upload original PDF and use MinerU `page_ranges`; do not physically split into huge PDFs
- long-PDF runner: `script/02_run_mineru_range_jobs.py --no-auto-split --chunk-size 1 --timeout 7200`

Scripts:

- `script/01_prepare_question_sources.py`: build doc manifests and stage question PDFs.
- `script/02_plan_mineru_jobs.py`: plan under-200 and long-PDF range jobs.
- `script/02_run_mineru_question_pdfs.py`: run under-200 PDF MinerU jobs.
- `script/02_run_mineru_range_jobs.py`: run long PDF page-range jobs and synthesize parent outputs.
- `script/03_build_mineru_ir.py`: build DocPreprocess IR from MinerU output.
- `script/04_export_preprocessed_corpus.py`: export docs/chunks/tables and clean non-PDF text.
- `script/05_audit_preprocessed_outputs.py`: strict corpus audit.

Results:

- PDF IR built: 59/59
- final docs: 68
- chunks: 66,894
- tables: 6,957
- evidence units: 73,911
- selector rows: 66,512
- question coverage: 100/100
- strict audit: no warnings, missing PDF IR = 0, orphan chunks/tables = 0
- asset paths checked: 8,038, missing = 0

Main generated outputs:

- `processed_data/docs.jsonl`
- `processed_data/chunks.jsonl`
- `processed_data/tables.jsonl`
- `processed_data/evidence_units/group_a_evidence_units.jsonl`
- `processed_data/selector/group_a_selector_search.jsonl`
- `processed_data/reports/group_a_preprocessed_audit.md`

Useful warnings:

- Earlier failed physical split cache for `financial_contracts__text01` was removed because it wasted about 4.6G.
- Many table quality rejects are due to missing caption/asset quality flags; text/table HTML can still be useful for retrieval.
- Future retrieval should use the full MinerU corpus rather than earlier partial fallback evidence.

## Evidence Seed And Draft Answers

Task:

- Build evidence packs and agent-drafted answers for Group A.

Configuration:

- half run: first 10 questions per domain = 50 questions
- full run: 20 questions per domain = 100 questions
- retrieval settings:
  - `max_text_chars`: 1400
  - `overlap`: 180
  - `option_top_k`: 6
  - `question_top_k`: 14
  - `max_quote_chars`: 900
- no Qwen call and no external web search in these draft-answer passes

Scripts:

- `script/06_build_agent_evidence_seed.py`: build sampled/full candidate evidence packs.
- `script/07_merge_agent_drafts.py`: merge agent drafts with evidence packs.
- `script/08_build_all_agent_drafts.py`: combine half-run and tail drafts into full 100-question drafts.
- `script/09_export_agent_answers.py`: export answer CSV and needs-review rows.

Full-run results:

- reviewed rows: 100
- answer nulls: 0
- status:
  - `agent_supported`: 87
  - `agent_supported_needs_review`: 13
- confidence:
  - high: 83
  - medium: 16
  - low: 1

Main generated outputs:

- `processed_data/agent_evidence_seed/group_a_all_agent_reviewed.jsonl`
- `processed_data/agent_evidence_seed/group_a_all_agent_answers.csv`
- `processed_data/agent_evidence_seed/group_a_all_needs_review.jsonl`
- `processed_data/agent_evidence_seed/group_a_all_agent_summary.md`

Needs-review qids from first pass:

- `fc_a_012`, `fc_a_015`
- `fin_a_008`, `fin_a_015`
- `ins_a_007`, `ins_a_010`, `ins_a_014`, `ins_a_020`
- `reg_a_006`, `reg_a_016`, `reg_a_017`
- `res_a_002`, `res_a_004`

## Second-Pass Review

Task:

- Recheck the 13 first-pass `needs_review` questions with conservative answer changes only when evidence consensus is clear.

Configuration:

- review target: 13/100 questions
- answer-change rule: concrete evidence-level consensus required
- model/API calls: no Qwen official inference; no external web search

Script:

- `script/10_apply_second_pass_review.py`

Results:

- rows: 100
- second-pass reviewed rows: 13
- changed answers: 1
- unchanged rows: 99
- changed answer:
  - `fc_a_012`: `ACD -> AC`
- structural caveats:
  - `fc_a_015`: keep `AB`, but mark `uncertain_question_conflict`; metadata says `mcq`, evidence supports A and B.
  - `ins_a_020`: keep `D`, but mark `uncertain_no_full_correct_option`; D is closest under forced choice.
- caveat confirmations:
  - `fin_a_008 = B`: annual cash dividend basis, excluding special dividend.
  - `fin_a_015 = A`: annual cash dividend basis.
  - `reg_a_016 = ABCD`: C depends on including unpaid business income that was obtained or not proven unobtainable.

Main generated outputs:

- `processed_data/agent_evidence_seed/group_a_needs_review_second_pass.jsonl`
- `processed_data/agent_evidence_seed/group_a_needs_review_second_pass.csv`
- `processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass.csv`
- `processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass_report.json`
- `processed_data/agent_evidence_seed/group_a_second_pass_review_summary.md`

Validation:

- `python script/10_apply_second_pass_review.py` returned `{"rows": 100, "changed": 1}`.
- `python -m py_compile` passed for scripts `06` through `10`.

## Answering Strategy

Task:

- Create an intro-style, pure problem-solving guide for different financial document types and question types.
- Keep the scope strictly on reading, evidence finding, option judgement, and answer formatting.
- Do not include SFT, training, trace construction, or model fine-tuning content.

Environment:

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- reference documents:
  - `introduction.md`
  - `processed_data/agent_evidence_seed/evidence_search_playbook.md`
  - `processed_data/agent_evidence_seed/group_a_all_questions.jsonl`
  - `processed_data/agent_evidence_seed/group_a_second_pass_review_summary.md`
- no model/API run for this task

Configuration:

- style: Chinese intro/playbook prose
- covered document types:
  - insurance
  - regulatory
  - financial_contracts
  - financial_reports
  - research
- covered question types:
  - single-document fact lookup
  - multi-document comparison
  - numeric calculation
  - clause applicability
  - true/false
  - multi-select
  - single-select

Results:

- Added `answering_strategy.md`.
- The document records:
  - a general solving flow: confirm format, limit docs, parse question, judge each option, preserve minimal sufficient evidence.
  - domain-specific evidence routes and common pitfalls for five financial document types.
  - question-type-specific solving methods.
  - evidence annotation norms.
  - a common error checklist.
  - a reusable manual-answer template.

Validation:

- Confirmed `answering_strategy.md` explicitly limits itself to problem solving and excludes SFT/training.
- Updated `progress.md` index.

## Task Brief Review

Task:

- Read and internalize the project introduction, task requirements, design document, answering strategy, and current progress before further implementation.

Environment:

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell env: no conda activation required for this read-only review
- primary project env noted from docs: `znh-AFAC2026`, Python 3.12.13

Configuration:

- files reviewed:
  - `AGENTS.md`
  - `introduction.md`
  - `design.md`
  - `answering_strategy.md`
  - `progress.md`
  - `1-progress/progreess-2026-07-07.md`
- discovery commands: `rg --files`, `find`, `sed`, `wc`, and `rg`
- model/API calls: none
- hyperparameters: not applicable; no retrieval, parsing, or answer-generation run was executed

Results:

- Confirmed there is no local `instructions.md`; the effective task brief is captured in `introduction.md`, `design.md`, `answering_strategy.md`, and progress notes.
- Confirmed official answering must use Qwen series models or deterministic rules; Qwen calls still require explicit user permission.
- Confirmed official retrieval/inference must not use embedding models, non-Qwen rerank, non-Qwen answer voting, or non-Qwen runtime summaries.
- Confirmed current project state: Group A preprocessing is complete for 68 selected docs; final corpus has 66,894 chunks and 6,957 tables; full Group A draft answers exist with a second-pass CSV.
- Confirmed current next priorities: rerun retrieval/evidence pack generation on the full MinerU corpus, add a dependency file, optionally run GLM dev/eval verification, and ask before any Qwen official-chain run.

Validation:

- No files in `data/`, `processed_data/`, scripts, or model outputs were modified.
- Updated `progress.md` index for this review.

## Agent V0 Framework

Task:

- Convert the guidance in `answering_strategy.md` into a concrete, runnable Agent V0 framework.
- Keep the framework evidence-first and option-centred: parse question, route documents, retrieve per option, pack evidence, judge, normalize, verify, and write outputs.
- Preserve official-chain boundaries: no Qwen call without explicit user approval, no embedding retrieval, no non-Qwen runtime result as official answer.

Environment:

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell Python used for implementation checks: `/public/home/zhangfanjin/miniconda3/bin/python`, Python 3.13.9
- project env noted for final runtime: `znh-AFAC2026`, Python 3.12.13
- model/API calls: none

Configuration:

- source guidance:
  - `answering_strategy.md`
  - `design.md`
  - `introduction.md`
- core inputs:
  - `processed_data/agent_evidence_seed/group_a_all_questions.jsonl`
  - `processed_data/selector/group_a_selector_search.jsonl`
  - `processed_data/docs.jsonl`
  - optional prior answer file for continuity test: `processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass.csv`
- V0 retrieval settings:
  - `doc_top_k_b`: 5
  - `option_top_k`: 6
  - `question_top_k`: 14
  - `final_evidence_max`: 18
  - `min_evidence_per_option`: 2
  - `max_quote_chars`: 900
  - `raw_fallback_max_chars`: 1400
  - `raw_fallback_overlap`: 180
- judge modes implemented:
  - `none`: build evidence only; all options stay `UNKNOWN`
  - `prior_csv`: import an existing answer CSV as a non-official prior and mark it as such
- official Qwen judge: intentionally not wired yet; must be added with explicit authorization and token logging

Implementation:

- Added `agent_design_from_strategy.md`, mapping solving-strategy guidance to engineering modules.
- Added `agent/` package:
  - `schema.py`: dataclasses for config, question, candidates, features, scored evidence, judge output, and result logs.
  - `text.py`: Chinese/financial lexical normalization, tokenization, number/year/clause extraction.
  - `domain_rules.py`: five-domain retrieval plans and task flags derived from `answering_strategy.md`.
  - `retrieval.py`: deterministic lexical/rule retrieval, A-split doc restriction, B-style doc routing scaffold, option-level scoring, and raw fallback.
  - `packer.py`: option evidence rows plus compact packed evidence with stable `evidence_id`.
  - `judge.py`: model-free `none` and `prior_csv` judges; Qwen/GLM paths deliberately guarded.
  - `verify.py`: answer normalization and audit flags for empty answers, single-answer conflicts, all-options answers, doc imbalance, and missing numbers/years.
  - `runner.py`: end-to-end orchestration and output writing.
  - `config.py` / `main.py`: CLI.
- Added `script/11_run_agent_v0.py` as the numbered reproducible wrapper.
- Added raw fallback for the 9 regulatory non-PDF docs missing from selector/evidence-units, so the Agent index covers all 68 docs from `docs.jsonl`.

Results:

- Static compile passed:
  - `python -m py_compile agent/*.py script/11_run_agent_v0.py`
- Selector-only gap identified:
  - selector docs: 59
  - docs manifest: 68
  - missing docs: 9 regulatory txt/html docs
- After raw fallback:
  - index docs: 68/68
  - candidate units: 66,607
  - missing docs: 0
  - example fallback docs:
    - `strict_v3_017_中华人民共和国反洗钱法`: 10 raw units
    - `csrc_0262`: 12 raw units
- Smoke runs:
  - `python -m agent.main --limit 5 --run-id smoke_none --output-dir runs/smoke_none --judge-mode none`
  - `python -m agent.main --limit 5 --run-id smoke_prior_v2 --output-dir runs/smoke_prior_v2 --judge-mode prior_csv --prior-answers-csv processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass.csv`
  - `python -m agent.main --qid reg_a_001 --run-id smoke_reg_raw --output-dir runs/smoke_reg_raw --judge-mode none`
- Full Group A prior-mode continuity run:
  - command: `python -m agent.main --run-id group_a_prior_v0 --output-dir runs/group_a_prior_v0 --judge-mode prior_csv --prior-answers-csv processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass.csv`
  - questions: 100
  - domains: 20 each for `financial_contracts`, `financial_reports`, `insurance`, `regulatory`, `research`
  - candidate docs: 68
  - candidate units: 66,607
  - token usage: 0 prompt, 0 completion, 0 total
  - statuses:
    - `prior_answer_imported`: 84
    - `needs_review`: 16
  - top audit warnings:
    - `prior_answer_not_official_judgement`: 100
    - `missing_number_in_packed_evidence`: 9
    - `answer_suspicious_all_options`: 5
    - `missing_year_in_packed_evidence`: 3
    - `doc_imbalance_for_cross_document_question`: 2
    - `format_conflict_multiple_letters_for_single_answer`: 1

Outputs:

- `runs/group_a_prior_v0/answer.csv`
- `runs/group_a_prior_v0/evidence.json`
- `runs/group_a_prior_v0/questions.jsonl`
- `runs/group_a_prior_v0/needs_review.jsonl`
- `runs/group_a_prior_v0/summary.json`

Validation:

- `answer.csv` contains 102 physical lines: header, summary, and 100 question rows.
- `questions.jsonl` contains 100 rows.
- `evidence.json` contains 100 qids.
- `needs_review.jsonl` contains 16 rows.
- `reg_a_001` smoke confirmed raw regulatory fallback evidence is retrieved from both specified txt documents.
- `script/11_run_agent_v0.py --qid reg_a_001 --judge-mode none` runs successfully after adding the repository root to `sys.path`.
- `fc_a_015` prior answer `AB` was normalized to `A` for single-answer format while preserving `format_conflict_multiple_letters_for_single_answer`, matching the strategy rule that single-select conflicts must be surfaced instead of silently hidden.
- No Qwen, GLM, embedding, rerank, web, or external model call was made.

Known risks:

- `prior_csv` is only a continuity/import mode and is not a fresh evidence-grounded model judgement.
- V0 still needs a real Qwen judge node and prompt/token logger before official submission.
- Current verifier flags are intentionally conservative; `missing_number_in_packed_evidence` and `answer_suspicious_all_options` require manual triage rather than automatic answer changes.

## Model Judge Interface

Task:

- Add the model-judge implementation shell needed to turn evidence packs into fresh option judgements.
- Keep Qwen official-chain calls blocked unless explicitly authorized.
- Add dependency documentation for the current Agent V0 runtime.

Environment:

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell Python used for checks: `/public/home/zhangfanjin/miniconda3/bin/python`, Python 3.13.9
- model/API calls: none

Configuration:

- judge modes now accepted by CLI:
  - `none`
  - `prior_csv`
  - `glm`
  - `qwen`
  - `openai_compatible`
- model configuration flags:
  - `--env-file`
  - `--llm-base-url`
  - `--llm-api-key-env`
  - `--llm-model`
  - `--llm-model-env`
  - `--llm-temperature`
  - `--llm-max-tokens`
  - `--llm-timeout`
  - `--allow-qwen`
- Qwen default base URL is OpenAI-compatible DashScope: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- Qwen mode requires `--allow-qwen`; without it the CLI exits before any remote call attempt.

Implementation:

- Added `agent/model_client.py`: dependency-free OpenAI-compatible chat client with env-file loading and usage-token capture.
- Added `agent/prompting.py`: strict JSON financial option-judgement prompt builder using compact `evidence_id/doc_id/page/section/text` evidence.
- Extended `agent/judge.py`:
  - model judge for `glm`, `qwen`, and `openai_compatible`
  - strict Qwen authorization gate
  - JSON parsing and fallback extraction
  - normalized `TRUE/FALSE/UNKNOWN` option judgements
  - token usage and raw response capture in logs
- Extended `agent/config.py`, `agent/schema.py`, and `agent/runner.py` to carry model settings, judge model name, raw response, and token usage.
- Added `requirements.txt`; current Agent V0 and repository scripts use Python standard-library modules only.

Results:

- Static compile passed:
  - `python -m py_compile agent/*.py script/11_run_agent_v0.py`
- No-model regression passed:
  - `python script/11_run_agent_v0.py --qid reg_a_001 --run-id smoke_none_modeliter --output-dir runs/smoke_none_modeliter --judge-mode none`
- Prior regression passed:
  - `python script/11_run_agent_v0.py --limit 2 --run-id smoke_prior_modeliter --output-dir runs/smoke_prior_modeliter --judge-mode prior_csv --prior-answers-csv processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass.csv`
- Qwen guard test passed:
  - command without `--allow-qwen` exits with code 2
  - message: `error: Qwen judge requires --allow-qwen after explicit user authorization.`
  - no model/network call was made
- Full Group A prior regression after model-interface changes:
  - command: `python script/11_run_agent_v0.py --run-id group_a_prior_modeliter --output-dir runs/group_a_prior_modeliter --judge-mode prior_csv --prior-answers-csv processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass.csv`
  - questions: 100
  - candidate docs: 68
  - candidate units: 66,607
  - statuses:
    - `prior_answer_imported`: 84
    - `needs_review`: 16
  - token usage: 0 prompt, 0 completion, 0 total
  - output row counts:
    - `answer.csv`: 102 physical lines
    - `questions.jsonl`: 100 rows
    - `needs_review.jsonl`: 16 rows
    - `evidence.json`: 100 qids

Validation:

- Existing model-free and prior-import flows still work after adding model plumbing.
- The official Qwen path cannot run accidentally because `--allow-qwen` is required before client configuration or remote request.
- Token usage fields are propagated into `answer.csv`, `evidence.json`, `questions.jsonl`, and `summary.json`.
- Secrets are read only from env/env-file names and are not printed.

Known risks:

- The model judge client has not yet been exercised against a real GLM or Qwen endpoint in this project.
- Official submission still needs an explicitly authorized Qwen run and review of produced `answer.csv`/`evidence.json`.
- At this point in the log, one-round repair retrieval had not yet been implemented; see the next section for the completed repair pass.

## Repair Retrieval And Runbook

Task:

- Implement the one-round supplementary retrieval described in `design.md` and `answering_strategy.md`.
- Reduce verifier noise while keeping real evidence risks visible.
- Add a reproducible user-facing runbook.

Environment:

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell Python used for checks: `/public/home/zhangfanjin/miniconda3/bin/python`, Python 3.13.9
- model/API calls: none

Configuration:

- new repair defaults:
  - `max_repair_rounds`: 1
  - `repair_top_k`: 4
- repair triggers:
  - `selected_option_without_retrieved_evidence`
  - `missing_number_in_packed_evidence`
  - `missing_year_in_packed_evidence`
  - `doc_imbalance_for_cross_document_question`
  - `unknown_heavy`
  - `answer_empty`
- repair is skipped in `none` mode because there is no judge to re-evaluate the new evidence.
- numeric verifier now ignores document-id-like numbers such as `fc_text_003` and scenario day counts like `第50天` for exact number coverage checks.

Implementation:

- Added `agent/repair.py`:
  - identifies repairable warnings
  - chooses target options from selected answer letters, unknown options, or explicit warning labels
  - builds supplementary queries with numbers, years, clauses, domain terms, and cross-document cues
  - merges original and extra evidence by `candidate_id`
- Updated `agent/runner.py`:
  - runs at most one repair round
  - re-packs evidence after supplementary retrieval
  - re-runs the judge after repair
  - accumulates token counts across judge calls
  - writes `repair_log` into `questions.jsonl` and `evidence.json`
  - adds repair counts to `summary.json`
- Updated `agent/verify.py`:
  - cross-document coverage now checks whether the packed evidence covers multiple docs, not whether only selected-option evidence covers them
  - number/year requirements are based on the question plus selected options, with doc-id and scenario-day filtering
- Added `README.md` with current runtime, compliance boundary, reproduction commands, model judge configuration, package map, and next work.

Results:

- Static compile passed:
  - `python -m py_compile agent/*.py script/11_run_agent_v0.py`
- Targeted repair checks:
  - `fc_a_004`: repair cleared `missing_number_in_packed_evidence`; final status became `prior_answer_imported`
  - `fc_a_015`: single-answer conflict remains and repair is skipped after filtering, as expected
  - `ins_a_004`: doc/scenario numeric noise cleared; final status became `prior_answer_imported`
  - `fc_a_008`: `150%` remains missing after repair and correctly stays `needs_review`
- Full Group A prior+repair v2 run:
  - command: `python script/11_run_agent_v0.py --run-id group_a_prior_repair_v2 --output-dir runs/group_a_prior_repair_v2 --judge-mode prior_csv --prior-answers-csv processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass.csv`
  - questions: 100
  - candidate docs: 68
  - candidate units: 66,607
  - repair counts:
    - `repaired`: 5
    - `not_repaired`: 95
  - statuses:
    - `prior_answer_imported`: 90
    - `needs_review`: 10
  - top warnings:
    - `prior_answer_not_official_judgement`: 100
    - `answer_suspicious_all_options`: 5
    - `missing_number_in_packed_evidence`: 4
    - `missing_year_in_packed_evidence`: 2
    - `format_conflict_multiple_letters_for_single_answer`: 1
  - token usage: 0 prompt, 0 completion, 0 total

Remaining `needs_review` qids:

- `fc_a_005`: all-options answer
- `fc_a_008`: missing `150%` evidence after repair
- `fc_a_015`: metadata says `mcq`, imported answer supports multiple options
- `fc_a_019`: missing number evidence after repair
- `ins_a_005`: all-options answer
- `ins_a_017`: all-options answer
- `ins_a_019`: all-options answer
- `ins_a_020`: missing number/year evidence after repair
- `reg_a_016`: all-options answer
- `reg_a_020`: missing number/year evidence after repair

Outputs:

- `runs/group_a_prior_repair_v2/answer.csv`
- `runs/group_a_prior_repair_v2/evidence.json`
- `runs/group_a_prior_repair_v2/questions.jsonl`
- `runs/group_a_prior_repair_v2/needs_review.jsonl`
- `runs/group_a_prior_repair_v2/summary.json`

Validation:

- `answer.csv`: 102 physical lines
- `questions.jsonl`: 100 rows
- `needs_review.jsonl`: 10 rows
- No Qwen, GLM, embedding, rerank, web, or external model call was made.

Known risks:

- Repair currently adjusts evidence packs only; it does not perform answer changes except through the active judge.
- Remaining `needs_review` rows need a real model judge or manual review.
- `prior_csv` remains non-official and cannot be treated as a competition-compliant fresh judgement.

## Output Audit Gate

Task:

- Add a deterministic pre-submission audit for Agent outputs.
- Validate the `answer.csv` format described in `introduction.md` and cross-check evidence/log consistency.
- Make strict official-style failures explicit instead of relying on manual inspection.

Environment:

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell Python used for checks: `/public/home/zhangfanjin/miniconda3/bin/python`, Python 3.13.9
- model/API calls: none

Configuration:

- audited run: `runs/group_a_prior_repair_v2`
- question bank: `processed_data/agent_evidence_seed/group_a_all_questions.jsonl`
- strict mode:
  - fails on unresolved `needs_review`
  - fails on `prior_csv` because it is not an official fresh judgement
- development mode:
  - `--allow-needs-review`
  - `--allow-prior-csv`

Implementation:

- Added `script/12_audit_agent_outputs.py`.
- Checks implemented:
  - `answer.csv` header equals `qid,answer,prompt_tokens,completion_tokens,total_tokens`
  - summary row exists first
  - answer qids exactly match the question bank
  - no duplicate qids
  - `mcq`/`tf` answers are one legal letter
  - `multi` answers are uppercase sorted unique legal letters
  - per-row and summary token totals are internally consistent
  - `evidence.json` qids match question bank
  - evidence answer matches CSV answer
  - evidence ids are sequential
  - option judgements cover actual question options, including A/B-only true/false questions
  - status/judge-mode/needs-review distributions are reported
- Updated `README.md` with strict and development audit commands.

Results:

- Static compile passed:
  - `python -m py_compile agent/*.py script/11_run_agent_v0.py script/12_audit_agent_outputs.py`
- Strict audit command:
  - `python script/12_audit_agent_outputs.py --run-dir runs/group_a_prior_repair_v2`
  - result: fail
  - expected reason: current run still has development-only `prior_csv` and 10 unresolved `needs_review` qids
- Development audit command:
  - `python script/12_audit_agent_outputs.py --run-dir runs/group_a_prior_repair_v2 --allow-needs-review --allow-prior-csv`
  - result: pass
  - warnings:
    - `summary_total_tokens_non_positive`
    - `needs_review_qids:10`
    - `prior_csv_not_official_judgement`
- Audit report outputs:
  - `runs/group_a_prior_repair_v2/audit_report.json`
  - `runs/group_a_prior_repair_v2/audit_report.md`

Validation:

- Development audit confirms:
  - 100 question answer rows
  - 100 evidence qids
  - 1,661 packed evidence items
  - no answer-format errors
  - no evidence-answer mismatches
  - no empty evidence qids
  - token row sums match summary totals

Known risks:

- Strict audit must pass before treating a future run as official-submission-ready.
- Current pass is development-only because `prior_csv` and unresolved review flags are explicitly allowed.

## Blind Doc Routing Eval

Task:

- Build a deterministic proxy evaluation for B-list blind document routing.
- Hide Group A `doc_ids`, run the Agent's doc router, and measure whether routed candidates recover the original gold documents.
- Tune the default B-style candidate count using empirical recall rather than guesswork.

Environment:

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell Python used for checks: `/public/home/zhangfanjin/miniconda3/bin/python`, Python 3.13.9
- model/API calls: none

Configuration:

- question bank: `processed_data/agent_evidence_seed/group_a_all_questions.jsonl`
- selector: `processed_data/selector/group_a_selector_search.jsonl`
- docs: `processed_data/docs.jsonl`
- top-k values evaluated: 5, 8, 12, 16
- output dir: `runs/doc_routing_eval_v1`

Implementation:

- Added `script/13_evaluate_doc_routing.py`.
- Enhanced `agent/retrieval.py` doc routing:
  - full-document token counts cached per doc
  - doc aliases such as `text03`, `fc_text_003`, `text3`, and insurance numeric aliases
  - metadata/source-path tokens included in doc-level scoring
- Updated default `doc_top_k_b` from 5 to 16 in `agent/schema.py` and CLI defaults.
- Updated `README.md` with the doc-routing evaluation command and current recall curve.

Results:

- Static compile passed:
  - `python -m py_compile agent/*.py script/11_run_agent_v0.py script/12_audit_agent_outputs.py script/13_evaluate_doc_routing.py`
- Evaluation command:
  - `python script/13_evaluate_doc_routing.py --top-ks 5,8,12,16 --output-dir runs/doc_routing_eval_v1`
- Candidate corpus:
  - docs: 68
  - candidate units: 66,607
- Overall recall:
  - top-5: any-doc recall 1.00, all-doc recall 0.81
  - top-8: any-doc recall 1.00, all-doc recall 0.90
  - top-12: any-doc recall 1.00, all-doc recall 0.96
  - top-16: any-doc recall 1.00, all-doc recall 1.00
- Top-16 domain all-doc recall:
  - `financial_contracts`: 1.00
  - `financial_reports`: 1.00
  - `insurance`: 1.00
  - `regulatory`: 1.00
  - `research`: 1.00

Outputs:

- `runs/doc_routing_eval_v1/doc_routing_summary.json`
- `runs/doc_routing_eval_v1/doc_routing_failures.jsonl`

Validation:

- Development audit of `runs/group_a_prior_repair_v2` still passes after routing changes:
  - `python script/12_audit_agent_outputs.py --run-dir runs/group_a_prior_repair_v2 --allow-needs-review --allow-prior-csv`
  - result: pass, errors 0, warnings 3

Known risks:

- This is a proxy based on A-list questions; B-list document naming and ambiguity may differ.
- Top-16 increases local retrieval compute but does not directly increase prompt tokens because packed evidence remains capped.

## Git And GitHub

Task:

- Create a local Git repository, keep large data out of history, and prepare GitHub push through a repository-scoped SSH deploy key.

Configuration:

- branch: `main`
- `.gitignore` excludes:
  - `data/`
  - `processed_data/`
  - `public_dataset_a.zip`
  - Python caches
  - local env/secrets
  - model/checkpoint artifacts
  - run outputs
- tracked scope: docs, progress, `.gitignore`, and `script/*.py`
- remote: `origin -> git@github-afac2026-4:AFAC2026-4/4.git`
- deploy key:
  - type: ED25519
  - alias: `github-afac2026-4`
  - fingerprint: `SHA256:HS9iH8hFHz5kQBs6XCGQNaNp1/YZ/KUvB4vfEnVGrWk`
  - private key path: `/public/home/zhangfanjin/.ssh/afac2026_4_deploy_ed25519`
  - private key permissions: `600`
  - `IdentitiesOnly yes` is set for the alias

Results:

- initial local commit: `92fea56 Initial project snapshot`
- auth-check commit: `d51cbd1 Record GitHub push auth check`
- deploy-key setup commit: `5153fb5 Configure GitHub SSH deploy key`
- condensed-progress commit: `f17009f Condense progress handoff notes`
- SSH authentication now succeeds as repository `AFAC2026-4/4`.
- Remote heads were empty before the first push.
- First push succeeded and created remote branch `main`.

Security note:

- This is a repository deploy key, not the user's personal GitHub key.
- The private key is outside the repository and was not printed.
- A Linux root user or someone with access to the same Unix account could still use local keys; revoke the deploy key from GitHub if the machine/user account is no longer trusted.

## Next Actions

- Exercise `glm` dev/eval mode on a tiny authorized smoke set if model credentials are available.
- Triage the 10 V0 prior+repair `needs_review` rows.
- Exercise the real model judge on a tiny dev/eval set if credentials are available.
- For any candidate official run, require `script/12_audit_agent_outputs.py` strict mode to pass.
- Ask explicit permission before any Qwen official-chain run.
