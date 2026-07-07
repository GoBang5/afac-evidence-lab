# 2026-07-07 AFAC2026-4 Progress

This file keeps only handoff-useful facts: environment, data shape, key decisions, scripts, outputs, known risks, and next actions.

## Current State

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- primary env: `znh-AFAC2026`, Python 3.12.13
- data root: `data/`, ignored by Git
- generated outputs: `processed_data/`, ignored by Git
- Git branch: `main`
- GitHub remote: `git@github-afac2026-4:AFAC2026-4/4.git`
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
- SSH authentication now succeeds as repository `AFAC2026-4/4`.
- Remote heads were empty before the first push attempt.

Security note:

- This is a repository deploy key, not the user's personal GitHub key.
- The private key is outside the repository and was not printed.
- A Linux root user or someone with access to the same Unix account could still use local keys; revoke the deploy key from GitHub if the machine/user account is no longer trusted.

## Next Actions

- Push local `main` to GitHub after this condensed progress update is committed.
- Re-run retrieval/evidence pack generation on the full MinerU corpus, replacing earlier fallback-heavy draft evidence.
- Add a dependency file for the final runtime stack.
- Decide whether to run GLM dev/eval verification on 100 questions.
- Ask explicit permission before any Qwen official-chain run.
