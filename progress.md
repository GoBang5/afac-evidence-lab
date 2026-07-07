# Progress Index

- [2026-07-07 AFAC2026-4 preparation v0](1-progress/progreess-2026-07-07.md#afac2026-4-preparation-v0): 创建并验证 conda 环境 `znh-AFAC2026`，Python 3.12.13；`public_dataset_a.zip` 已上传到本 workspace，解压顶层 `public_dataset_upload/` 并重命名为 `data/`，完成题目 JSON 与 PDF 数量检查。
- [2026-07-07 AFAC2026-4 agent design v0](1-progress/progreess-2026-07-07.md#afac2026-4-agent-design-v0): 完成“自研规则检索流水线 + LangGraph 轻量编排 + Qwen 证据判题 + 日志自进化”的方案设计，并写入 `design.md`。
- [2026-07-07 AFAC2026-4 model policy v1](1-progress/progreess-2026-07-07.md#afac2026-4-model-policy-v1): 明确开发期允许 GLM/`.env` 指定模型做效果验证和自进化，默认不调用 Qwen，官方 Qwen 链路需用户显式许可。
- [2026-07-07 AFAC2026-4 half-question agent evidence seed v1](1-progress/progreess-2026-07-07.md#afac2026-4-half-question-agent-evidence-seed-v1): 每领域抽前 10 题共 50 题，生成候选 evidence pack、多 agent 草标、reviewed JSONL 和 evidence 搜寻 playbook；44 题 supported，6 题 needs_review。
- [2026-07-07 AFAC2026-4 full-question agent answer drafts v1](1-progress/progreess-2026-07-07.md#afac2026-4-full-question-agent-answer-drafts-v1): 扩展到 Group A 全量 100 题，生成全量 candidate evidence、agent drafts、reviewed JSONL 和答案 CSV；87 题 supported，13 题 needs_review。
- [2026-07-07 AFAC2026-4 MinerU full preprocessing v1](1-progress/progreess-2026-07-07.md#afac2026-4-mineru-full-preprocessing-v1): 完成 59/59 问题相关 PDF 的 MinerU 解析与 DocPreprocess IR/export，长 PDF 改用 `page_ranges + --no-auto-split` 避免 200MB 限制；最终产出 68 docs、66,894 chunks、6,957 tables，严格审计 warnings 为空，100/100 问题有文档证据覆盖。
- [2026-07-07 AFAC2026-4 multi-subagent second-pass review v1](1-progress/progreess-2026-07-07.md#afac2026-4-multi-subagent-second-pass-review-v1): 对首轮 13 道 `needs_review` 题做多 subagent 模拟人工复查；二轮仅修正 `fc_a_012: ACD -> AC`，保留 `fc_a_015` 单选题型冲突和 `ins_a_020` 无完全正确选项标记。
- [2026-07-07 AFAC2026-4 git repository initialization v1](1-progress/progreess-2026-07-07.md#afac2026-4-git-repository-initialization-v1): 在 AFAC2026-4 根目录初始化本地 Git 仓库，主分支为 `main`；尚未创建首次提交，需先规划 `.gitignore` 以避免纳入大文件和中间数据。
- [2026-07-07 AFAC2026-4 gitignore and initial commit v1](1-progress/progreess-2026-07-07.md#afac2026-4-gitignore-and-initial-commit-v1): 新增 `.gitignore` 并验证 `data/`、`processed_data/`、`public_dataset_a.zip`、Python cache 被忽略；首次提交范围限定为轻量源码、文档和进度记录。
