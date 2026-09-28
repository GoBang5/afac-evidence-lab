# Progress Index

Use this file as the short navigation index. Detailed handoff notes live in daily files under `1-progress/`.

- [2026-09-28 Evidence Lab](1-progress/progreess-2026-09-28.md): 在独立副本增加等价检索缓存、字符预算、引用审计与断点续跑；100题离线检索热缓存约2.30倍，21项测试通过，无真实模型调用。

- [2026-07-07 current state](1-progress/progreess-2026-07-07.md#current-state): Workspace, env, data/output locations, model policy, and GitHub remote/tracking state.
- [2026-07-07 data and environment](1-progress/progreess-2026-07-07.md#data-and-environment): `znh-AFAC2026` created with Python 3.12.13; Group A has 100 questions across 5 domains; raw data has 190 PDFs.
- [2026-07-07 design decisions](1-progress/progreess-2026-07-07.md#design-decisions): Deterministic preprocessing plus rule/BM25 retrieval and option-level evidence; GLM allowed for dev/eval, Qwen requires explicit permission.
- [2026-07-07 preprocessing](1-progress/progreess-2026-07-07.md#preprocessing): MinerU + DocPreprocess completed for 68 selected docs; final corpus has 66,894 chunks and 6,957 tables with strict audit clean.
- [2026-07-07 evidence and drafts](1-progress/progreess-2026-07-07.md#evidence-seed-and-draft-answers): Full Group A draft answers generated; 87 supported and 13 needs-review.
- [2026-07-07 second-pass review](1-progress/progreess-2026-07-07.md#second-pass-review): Reviewed the 13 hard cases; only `fc_a_012` changed from `ACD` to `AC`; `fc_a_015` and `ins_a_020` retain caveats.
- [2026-07-07 answering strategy](1-progress/progreess-2026-07-07.md#answering-strategy): Added `answering_strategy.md`, a pure intro-style problem-solving guide for five document types and seven question types; no SFT/training content.
- [2026-07-07 task brief review](1-progress/progreess-2026-07-07.md#task-brief-review): Re-read introduction, design, answering strategy, and progress notes; confirmed current constraints, pipeline state, and next implementation priorities.
- [2026-07-07 Agent V0 framework](1-progress/progreess-2026-07-07.md#agent-v0-framework): Added an evidence-first `agent/` package mapped from `answering_strategy.md`; Group A prior-mode run produced 100-question answer/evidence/log outputs with 68/68 doc coverage and no model calls.
- [2026-07-07 model judge interface](1-progress/progreess-2026-07-07.md#model-judge-interface): Added strict JSON model judge plumbing, OpenAI-compatible client, token usage capture, explicit Qwen authorization gate, and minimal `requirements.txt`; no model calls were made.
- [2026-07-07 repair retrieval and runbook](1-progress/progreess-2026-07-07.md#repair-retrieval-and-runbook): Added one-round supplementary retrieval, refined numeric audit filtering, and `README.md`; Group A prior+repair v2 reduced `needs_review` to 10 with no model calls.
- [2026-07-07 output audit gate](1-progress/progreess-2026-07-07.md#output-audit-gate): Added `script/12_audit_agent_outputs.py` for answer/evidence/log validation; current prior+repair run passes development audit and fails strict audit for expected prior/review risks.
- [2026-07-07 blind doc routing eval](1-progress/progreess-2026-07-07.md#blind-doc-routing-eval): Added `script/13_evaluate_doc_routing.py`; hiding Group A `doc_ids`, top-16 routing reaches 100% any/all gold-doc recall, so B-style default `doc_top_k_b` is 16.
- [2026-07-07 Git and GitHub](1-progress/progreess-2026-07-07.md#git-and-github): Git initialized on `main`, large data ignored, repository deploy key configured, and first push to `AFAC2026-4/4` succeeded.
- [2026-07-07 framework repository upload](1-progress/progreess-2026-07-07.md#framework-repository-upload): Uploaded Agent framework, preprocessing/agent scripts, README, requirements, strategy docs, and progress records in commit `5c33cf8`; ignored data, processed outputs, runs, and secrets stayed out of Git.
- [2026-07-07 next actions](1-progress/progreess-2026-07-07.md#next-actions): Stabilize GLM smoke notes/defaults, triage 10 needs-review rows, run strict audit before any official candidate, ask before Qwen.
