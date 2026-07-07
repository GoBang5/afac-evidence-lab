# Progress Index

Use this file as the short navigation index. Detailed handoff notes live in daily files under `1-progress/`.

- [2026-07-07 current state](1-progress/progreess-2026-07-07.md#current-state): Workspace, env, data/output locations, model policy, and GitHub remote.
- [2026-07-07 data and environment](1-progress/progreess-2026-07-07.md#data-and-environment): `znh-AFAC2026` created with Python 3.12.13; Group A has 100 questions across 5 domains; raw data has 190 PDFs.
- [2026-07-07 design decisions](1-progress/progreess-2026-07-07.md#design-decisions): Deterministic preprocessing plus rule/BM25 retrieval and option-level evidence; GLM allowed for dev/eval, Qwen requires explicit permission.
- [2026-07-07 preprocessing](1-progress/progreess-2026-07-07.md#preprocessing): MinerU + DocPreprocess completed for 68 selected docs; final corpus has 66,894 chunks and 6,957 tables with strict audit clean.
- [2026-07-07 evidence and drafts](1-progress/progreess-2026-07-07.md#evidence-seed-and-draft-answers): Full Group A draft answers generated; 87 supported and 13 needs-review.
- [2026-07-07 second-pass review](1-progress/progreess-2026-07-07.md#second-pass-review): Reviewed the 13 hard cases; only `fc_a_012` changed from `ACD` to `AC`; `fc_a_015` and `ins_a_020` retain caveats.
- [2026-07-07 Git and GitHub](1-progress/progreess-2026-07-07.md#git-and-github): Git initialized on `main`, large data ignored, repository deploy key configured, SSH auth succeeds for `AFAC2026-4/4`.
- [2026-07-07 next actions](1-progress/progreess-2026-07-07.md#next-actions): Push condensed progress, rerun retrieval on full MinerU corpus, add dependency file, optionally run GLM dev/eval, ask before Qwen.
