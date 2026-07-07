# 2026-07-07 AFAC2026-4 Progress

## AFAC2026-4 preparation v0

### 任务

为 `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4` 做准备工作：

1. 创建 conda 环境 `znh-AFAC2026`。
2. 将本机 `/Users/hanyuhe/Downloads/public_dataset_a.zip` 上传到服务器。
3. 解压后重命名为本 workspace 内 `data` 文件夹。

### 环境

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- conda root: `/public/home/zhangfanjin/miniconda3`
- target env: `/public/home/zhangfanjin/miniconda3/envs/znh-AFAC2026`
- timezone/date: Asia/Shanghai, 2026-07-07
- filesystem: `/public` 解压前可用空间约 298G，但整体使用率已接近满载

### 超参数 / 配置

- conda create command: `conda create -y -n znh-AFAC2026 python=3.12`
- Python version: 3.12.13
- 未安装训练/推理额外依赖；当前 workspace 尚无 `environment.yml`、`requirements.txt` 或 `pyproject.toml` 可用于自动补齐依赖
- 未 clone 现有 `znh` 或 `znh-sglang0510-cu12` 环境，避免在 `/public` 空间紧张时复制重环境

### 结果

已完成：

- `znh-AFAC2026` 创建成功。
- `conda run -n znh-AFAC2026 python -V` 验证通过，输出 `Python 3.12.13`。
- `conda env list` 可见 `znh-AFAC2026`。
- `public_dataset_a.zip` 已上传到 workspace 根目录，大小 274M。
- `unzip -l public_dataset_a.zip` 确认顶层目录为 `public_dataset_upload/`。
- 已执行 `unzip -q public_dataset_a.zip && mv public_dataset_upload data`，最终数据目录为 `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4/data`。

数据验证：

- `data` 大小：343M。
- `data` 总文件数：578。
- `data/questions/group_a` 下 5 个题目 JSON 均可解析，每类 20 题，共 100 题：
  - `financial_contracts_questions.json`: 20。
  - `financial_reports_questions.json`: 20。
  - `insurance_questions.json`: 20。
  - `regulatory_questions.json`: 20。
  - `research_questions.json`: 20。
- `data/raw` 下 PDF 共 190 个：
  - `financial_contracts`: 14。
  - `financial_reports`: 10。
  - `insurance`: 16。
  - `regulatory`: 130。
  - `research`: 20。

### 下一步

可以基于 `data/questions/group_a/*.json` 与 `data/raw/*` 开始构建读取、预处理、baseline 或提交格式相关脚本。压缩包 `public_dataset_a.zip` 目前保留在 workspace 根目录，便于后续核验或重新解压。

## AFAC2026-4 agent design v0

### 任务

基于赛题说明、当前 A 榜数据结构和用户给出的参考建议，设计可完成金融长文档选择题任务的 Agent 流程与自进化框架。

重点目标：

1. 明确正式答题链路，避免使用 embedding、非 Qwen rerank 或非 Qwen 语义摘要。
2. 设计 A/B 榜均可复用的规则检索 + Qwen 判题流程。
3. 设计日志驱动的自进化框架，用于持续优化切分、检索、证据 pack、prompt、自检和修复策略。
4. 将设计沉淀到 workspace 根目录 `design.md`。

### 环境

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell: bash
- date/timezone: 2026-07-07 Asia/Shanghai
- planned env: `znh-AFAC2026`
- 当前操作类型：文档设计，无模型调用、无 benchmark 运行、无数据改写

### 超参数 / 配置

本次没有执行训练或测评，记录的是拟采用的工程配置：

- 主框架：自研 deterministic pipeline，LangGraph 仅作为轻量状态机。
- 正式推理模型：Qwen 系列，建议主判题使用 `qwen3.6-plus` 或同等 Qwen API。
- 禁用：embedding 检索、非 Qwen rerank、非 Qwen 答案投票、非 Qwen 预生成语义摘要参与正式作答。
- 检索：BM25 + 精确词匹配 + 标题/章节匹配 + 条款号匹配 + 数字/年份/金额/比例匹配 + 选项级证据召回。
- 证据 top-k 初始建议：
  - B 榜 doc-level 候选：top 3-5。
  - 每选项 chunk 候选：top 6。
  - 最终 evidence pack：最多约 18 条。
- token 档位初始建议：
  - L1 低成本题：6k-12k token/题。
  - L2 标准题：12k-22k token/题。
  - L3 修复题：22k-35k token/题。
- 修复轮数：默认最多 1 轮，避免 token 失控。

### 结果

已完成：

- 阅读并综合：
  - `introduction.md` 赛题规则、数据格式、评分和限制。
  - `data/questions/group_a/*.json` 的样例题，确认 A 榜每个领域 20 题，共 100 题。
  - 用户附件中的框架建议，重点采纳“自研规则检索流水线 + LangGraph 轻量编排”。
- 写入 `design.md`，内容包括：
  - 总体架构。
  - 预处理产物 schema。
  - LangGraph/状态机节点设计。
  - 五个领域的切分、检索和自检策略。
  - BM25 + 规则检索打分。
  - Qwen 证据约束判题 prompt。
  - token 分档策略。
  - 日志驱动自进化闭环。
  - evidence.json 设计。
  - V0-V3 实施路线图。
- 修正 `progress.md` 中历史进展链接，将不存在的 `10-progress/...` 改为实际存在的 `1-progress/...`。
- 在 `progress.md` 中新增本次设计任务索引。

### 下一步

建议按 `design.md` 的 V0 路线开始实现：

1. 先建立 `processed_data/docs.jsonl/chunks.jsonl/tables.jsonl`。
2. 实现 A 榜使用给定 `doc_ids` 的 option-level BM25/规则检索。
3. 接入 `llm_judge` JSON 判题和本地答案规范化；开发期默认 GLM/指定模型，官方 Qwen 链路需用户许可。
4. 生成 `answer.csv/evidence.json/logs`，再根据日志做第一轮自进化。

## AFAC2026-4 model policy v1

### 任务

根据用户补充要求，修订 `design.md` 中的模型使用策略：

1. 允许使用 GLM 作为开发期效果验证模型。
2. 未经用户明确允许，不调用 Qwen 模型。
3. 自进化阶段使用 GLM 和用户指定的其他模型。
4. 模型配置来源记录为 `/public/home/zhangfanjin/zhangnianhao/.env`。

### 环境

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- model config path: `/public/home/zhangfanjin/zhangnianhao/.env`
- `.env` 状态：文件存在，仅做存在性检查，未读取或输出密钥内容
- 当前操作类型：文档策略修订，无模型调用、无 benchmark 运行、无数据改写

### 超参数 / 配置

本次没有执行训练或测评，记录的是新的默认策略：

- 默认链路：`dev/eval`。
- 默认判题/验证模型：GLM 或 `.env` 指定模型。
- Qwen 开关：默认 `qwen_enabled: false`。
- Qwen 使用条件：必须获得用户明确授权后，才可用于官方提交链路。
- 自进化模型：GLM + 用户在 `.env` 中指定的其他模型。
- 合规边界：GLM/非 Qwen 运行时结果不得混入官方提交用 `answer.csv/evidence.json`。

### 结果

已完成：

- 在 `design.md` 增加 `1.3 模型使用策略`：
  - 区分 `dev/eval` 与 `official` 两条链路。
  - 明确默认不调用 Qwen。
  - 明确 `.env` 只作为配置来源，不打印密钥。
- 将流程节点从 `qwen_judge/qwen_verify` 改为 `llm_judge/llm_verify`。
- 将配置示例改为：
  - `mode: dev_eval`
  - `judge_provider: glm`
  - `judge_model_env: GLM_MODEL`
  - `qwen_enabled: false`
- 更新自进化框架：
  - 开发期允许 GLM/指定模型做错误诊断、效果验证和修改建议。
  - 官方提交链路仍需按赛题约束使用 Qwen，且必须先得到用户许可。
- 在 `progress.md` 增加本次模型策略修订索引。

### 下一步

实现代码时应先做配置加载层：

1. 从 `/public/home/zhangfanjin/zhangnianhao/.env` 读取 GLM/指定模型配置。
2. 默认拒绝 Qwen 调用，除非显式配置 `qwen_enabled: true` 且用户当轮确认。
3. 日志中只记录模型名、provider、token，不记录 API key。

## AFAC2026-4 half-question agent evidence seed v1

### 任务

在 MinerU 等 PDF 解析方案仍在推进时，先用多 agent/高模型能力从 Group A 数据中挑选一半问题，自行搜寻答案、沉淀找证据与回答问题的思路，并标注 evidence。

本次具体目标：

1. 每个领域抽取前 10 题，共 50 题，保证 financial_contracts、financial_reports、insurance、regulatory、research 均衡覆盖。
2. 复用现有 `processed_data/selector/group_a_selector_search.jsonl` 和 `processed_data/evidence_units/group_a_evidence_units.jsonl`。
3. 对 selector 缺失的财报、法规 txt、部分合同 PDF 使用 `pdftotext` 文本回退，补齐候选证据。
4. 分多个子 agent 分片完成答案草标和关键证据核验。
5. 产出可复核、可 join、可进一步转 SFT 的 JSONL 种子数据和 evidence 搜寻 playbook。

### 环境

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell: bash
- date/timezone: 2026-07-07 Asia/Shanghai
- Python: system/miniconda default `python`
- PDF text fallback: `/usr/bin/pdftotext`
- 模型/API：未调用 Qwen；未调用外部网络；使用 Codex 多 sub-agent 做本地只读证据搜寻和草标汇总
- 主要输入：
  - `data/questions/group_a/*.json`
  - `processed_data/selector/group_a_selector_search.jsonl`
  - `processed_data/evidence_units/group_a_evidence_units.jsonl`
  - `processed_data/manifests/group_a_question_docs.jsonl`
  - `processed_data/manifests/group_a_question_nonpdf.jsonl`
  - `data/raw/*`

### 超参数 / 配置

- 抽样策略：`balanced_first_n_per_domain`
- `per_domain`: 10
- 题目总数：50
- 领域分布：
  - `financial_contracts`: 10
  - `financial_reports`: 10
  - `insurance`: 10
  - `regulatory`: 10
  - `research`: 10
- 候选证据生成：
  - `max_text_chars`: 1400
  - `overlap`: 180
  - `option_top_k`: 6
  - `question_top_k`: 14
  - `max_quote_chars`: 900
  - `append_fallback`: false
- 检索特征：
  - 题干/选项关键词
  - 中文 2/3/4-gram
  - 英文/数字 token
  - 年份、金额、比例、明确数值
  - option literal/phrase match
- 草标状态：
  - `agent_supported`
  - `agent_supported_needs_review`
  - `partial_low_confidence`
  - `insufficient_source_text`
- 本轮最终通过 `pdftotext` 回退复核消除了低置信/缺文本状态。

### 结果

新增脚本：

- `script/06_build_agent_evidence_seed.py`
  - 生成 50 题 balanced half selection。
  - 从 selector/evidence_units 读取候选。
  - 对缺失文档用 raw PDF/txt/html 回退抽取。
  - 输出一题一行的 `option_evidence` 与 `question_evidence`。
- `script/07_merge_agent_drafts.py`
  - 将多 agent 草标按 `qid` 合并回候选 evidence pack。
  - 输出 reviewed JSONL 和报告。

新增/更新数据：

- `processed_data/agent_evidence_seed/group_a_half_questions.jsonl`
  - 50 题抽样清单。
- `processed_data/agent_evidence_seed/group_a_half_agent_annotations.jsonl`
  - 50 题候选 evidence pack。
  - 每题包含 4 个选项的候选 evidence，每题合并 14 条 `question_evidence`。
- `processed_data/agent_evidence_seed/group_a_half_agent_drafts.jsonl`
  - 多 agent 草标答案、证据笔记、confidence/status/method。
- `processed_data/agent_evidence_seed/group_a_half_agent_reviewed.jsonl`
  - 已合并候选 evidence 与草标的复核种子。
- `processed_data/agent_evidence_seed/group_a_half_agent_evidence_report.json`
  - 候选生成报告。
- `processed_data/agent_evidence_seed/group_a_half_agent_reviewed_report.json`
  - reviewed 合并报告。
- `processed_data/agent_evidence_seed/evidence_search_playbook.md`
  - 本轮沉淀的证据搜寻流程、领域策略、标注状态和发现。

覆盖与统计：

- selected questions: 50
- selected doc_ids: 46
- docs with candidates: 46/46
- candidate units: 16074
- reviewed rows: 50
- missing drafts: 0
- extra drafts: 0
- reviewed status:
  - `agent_supported`: 44
  - `agent_supported_needs_review`: 6
- reviewed confidence:
  - `high`: 39
  - `medium`: 11
- answer nulls: 0

关键发现：

1. 当前主 selector/evidence_units 对 insurance/research 部分效果较好，但 financial_reports 完全缺主 evidence units，需要 PDF 文本回退或补跑 MinerU。
2. 部分 financial_contracts 文档在主 selector 中缺失或不完整；`pdftotext` 回退补上 `text06/text10/text14` 后，原先低置信的 `fc_a_002/fc_a_005/fc_a_007/fc_a_009/fc_a_010` 均提升为 high confidence。
3. insurance 计算题不能只靠题干全文检索，数字过多会把总述段排前；更适合“产品名 + 责任名/公式名”的二阶段检索。
4. regulatory txt 非常适合按条/行切分，后续应把行号证据转成稳定 raw unit。
5. research 题表格证据较多，应保留 caption 和邻近解释，避免只截孤立数字。

验证：

- `python -m py_compile script/06_build_agent_evidence_seed.py script/07_merge_agent_drafts.py` 通过。
- JSONL 解析检查通过：
  - `group_a_half_questions.jsonl`: 50 rows, 0 duplicate qids
  - `group_a_half_agent_annotations.jsonl`: 50 rows, 0 duplicate qids
  - `group_a_half_agent_drafts.jsonl`: 50 rows, 0 duplicate qids
  - `group_a_half_agent_reviewed.jsonl`: 50 rows, 0 duplicate qids
- `script/07_merge_agent_drafts.py` 输出 `missing_drafts=0`、`extra_drafts=0`。

### 下一步

建议继续做三件事：

1. 把 `group_a_half_agent_reviewed.jsonl` 中 6 条 `agent_supported_needs_review` 单独复核，必要时补更精细的 option-level judgement。
2. 将 reviewed 样本转成 SFT 格式：输入为题目 + doc_ids + evidence pack，输出为逐选项 support/refute 和最终答案。
3. 把 `pdftotext` 回退链路正式纳入预处理补充方案，尤其针对 financial_reports 与缺 MinerU IR 的 financial_contracts。

## AFAC2026-4 full-question agent answer drafts v1

### 任务

在上一轮每领域前 10 题半量 evidence seed 的基础上，将同样流程扩展到 Group A 全量 100 题，为每道题标注 agent 草标答案、关键证据、confidence/status，并生成可检索 reviewed 数据和答案 CSV。

### 环境

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell: bash
- date/timezone: 2026-07-07 Asia/Shanghai
- PDF text fallback: `/usr/bin/pdftotext`
- 模型/API：未调用 Qwen；未联网；使用 Codex 多 sub-agent 对 q11-q20 的 50 题做本地只读证据搜寻和答案草标
- 输入：
  - `processed_data/agent_evidence_seed/group_a_half_agent_drafts.jsonl`
  - `data/questions/group_a/*.json`
  - `processed_data/selector/group_a_selector_search.jsonl`
  - `processed_data/evidence_units/group_a_evidence_units.jsonl`
  - `data/raw/*`

### 超参数 / 配置

- 全量候选生成：
  - `script/06_build_agent_evidence_seed.py --per-domain 20 --output-prefix group_a_all`
  - `max_text_chars`: 1400
  - `overlap`: 180
  - `option_top_k`: 6
  - `question_top_k`: 14
  - `max_quote_chars`: 900
- 全量草标构建：
  - `script/08_build_all_agent_drafts.py --additions processed_data/agent_evidence_seed/group_a_tail_agent_drafts.jsonl`
- reviewed 合并：
  - `script/07_merge_agent_drafts.py --annotations group_a_all_agent_annotations.jsonl --drafts group_a_all_agent_drafts.jsonl`
- 答案导出：
  - `script/09_export_agent_answers.py`

### 结果

新增脚本：

- `script/08_build_all_agent_drafts.py`
  - 将半量 50 题 drafts 与后半 50 题 drafts 按全量问题顺序合并，输出 `group_a_all_agent_drafts.jsonl`。
- `script/09_export_agent_answers.py`
  - 从 reviewed JSONL 导出简明答案 CSV、needs-review JSONL 和报告。

新增/更新数据：

- `processed_data/agent_evidence_seed/group_a_all_questions.jsonl`
- `processed_data/agent_evidence_seed/group_a_all_agent_annotations.jsonl`
- `processed_data/agent_evidence_seed/group_a_tail_agent_drafts.jsonl`
- `processed_data/agent_evidence_seed/group_a_all_agent_drafts.jsonl`
- `processed_data/agent_evidence_seed/group_a_all_agent_reviewed.jsonl`
- `processed_data/agent_evidence_seed/group_a_all_agent_answers.csv`
- `processed_data/agent_evidence_seed/group_a_all_needs_review.jsonl`
- `processed_data/agent_evidence_seed/group_a_all_agent_summary.md`
- `processed_data/agent_evidence_seed/group_a_all_*_report.json`

覆盖与统计：

- questions: 100
- domains: 5 x 20
- selected doc_ids: 68
- docs with candidates: 68/68
- candidate units: 22709
- reviewed rows: 100
- missing drafts: 0
- extra drafts: 0
- answer nulls: 0
- status:
  - `agent_supported`: 87
  - `agent_supported_needs_review`: 13
- confidence:
  - `high`: 83
  - `medium`: 16
  - `low`: 1

需要复核的 13 题：

- `fc_a_012`: answer `ACD`, medium；违约金/逾期利息表述需复核。
- `fc_a_015`: answer `AB`, high；题型为 `mcq`，但证据同时支持 A 和 B。
- `fin_a_008`: answer `B`, medium；宁德时代年度/特别分红口径需复核。
- `fin_a_015`: answer `A`, medium；年度现金分红 vs 合计分红口径需复核。
- `ins_a_007`: answer `BC`, medium；保单贷款条款需复核。
- `ins_a_010`: answer `AB`, medium；现金价值公式/比例表述需复核。
- `ins_a_014`: answer `AB`, medium；D 依赖事故是否发生在乘坐营运交通工具期间。
- `ins_a_020`: answer `D`, low；家财水管爆裂承保边界不足，需要重点复核。
- `reg_a_006`: answer `A`, medium；跨央行规章和定期报告准则，需复核题意。
- `reg_a_016`: answer `ABCD`, medium；行政处罚案例裁量口径需复核。
- `reg_a_017`: answer `AB`, medium；处罚时效项区分当事人申辩和证监会复核结论。
- `res_a_002`: answer `ABC`, medium；D 来自非本题文档未取。
- `res_a_004`: answer `AB`, medium；韩国银保表述和芯原 IP 排名需复核。

验证：

- `python -m py_compile script/06_build_agent_evidence_seed.py script/07_merge_agent_drafts.py script/08_build_all_agent_drafts.py script/09_export_agent_answers.py` 通过。
- 全量 JSONL 检查通过：
  - `group_a_all_questions.jsonl`: 100 rows, 0 duplicate qids
  - `group_a_all_agent_annotations.jsonl`: 100 rows, 0 duplicate qids
  - `group_a_all_agent_drafts.jsonl`: 100 rows, 0 duplicate qids
  - `group_a_all_agent_reviewed.jsonl`: 100 rows, 0 duplicate qids
- `group_a_all_agent_answers_report.json` 标出一个题型冲突：`fc_a_015` 为 `mcq` 但草标 `AB`。

### 下一步

建议：

1. 优先复核 `group_a_all_needs_review.jsonl` 中 13 题，特别是 `fc_a_015` 和 `ins_a_020`。
2. 将 87 条 `agent_supported` 作为较干净的 SFT seed；13 条暂时作为 hard cases/复核集。
3. 对 `mcq/tf` 强制单答案输出时，先不要直接使用 `fc_a_015=AB`，应人工或 judge model 再判定。

## AFAC2026-4 MinerU full preprocessing v1

### 任务

参考 `/public/home/zhangfanjin/zhangnianhao/01-projects/UniDoc-RL/tools/mineru_parse_folder.py` 使用 MinerU 解析 Group A 问题涉及的 PDF，并参考 `/public/home/zhangfanjin/zhangnianhao/01-projects/DocPreprocess/scripts` 做预处理，产出比赛可用的结构化文档：

1. 解析 100 道 Group A 问题引用的全部文档。
2. 对 PDF 生成 MinerU output、DocPreprocess IR、quality/evidence/selector 产物。
3. 对 HTML/TXT 法规文本做正文清洗、条款级切分与 trace 字段保留。
4. 分派多个 subagent 审计 manifest、schema、当前输出质量并根据审计修复。
5. 严格遵守模型策略：未调用 Qwen；本任务只使用 MinerU API 和本地脚本。

### 环境

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- env/model config: `/public/home/zhangfanjin/zhangnianhao/.env`
- MinerU key: `MINERU_API_KEY` 存在性检查通过，未输出密钥。
- shell: bash
- timezone/date: Asia/Shanghai, 2026-07-07
- reference MinerU wrapper: `/public/home/zhangfanjin/zhangnianhao/01-projects/UniDoc-RL/tools/mineru_parse_folder.py`
- reference batch script: `/public/home/zhangfanjin/zhangnianhao/01-projects/UniDoc-RL/tools/mineru_batch_parse.py`
- DocPreprocess scripts:
  - `normalize_mineru_result.py`
  - `annotate_ir_quality.py`
  - `export_evidence_units.py`
  - `export_selector_view.py`

### 超参数 / 配置

文档准备：

- questions dir: `data/questions/group_a`
- raw root: `data/raw`
- selected docs: 68
- selected PDF docs: 59
- selected non-PDF docs: 9
- missing docs: 0
- PDF total pages: 7923
- PDF over 200 pages: 21
- PDF under/equal 200 pages: 38

MinerU 常规 PDF：

- stage dir: `processed_data/mineru_input/group_a_question_pdfs_under200`
- command: `python script/02_run_mineru_question_pdfs.py --pdf-folder processed_data/mineru_input/group_a_question_pdfs_under200 --chunk-size 5 --timeout 7200`
- language: `ch`
- chunk size: 5
- timeout: 7200s
- result: 38/38 under-200 PDF done

MinerU 长 PDF：

- 初始物理拆分尝试：`mineru_parse_folder.py` 自动将 `financial_contracts__text01.pdf` 拆成 200/111 页两段，但生成 1.5GB/825MB 上传文件，MinerU 返回 `file size exceeds limit (200MB)`。
- 修正策略：不用物理拆分，改为上传原始 PDF，并通过 MinerU `page_ranges` 做逻辑分页。
- runner: `script/02_run_mineru_range_jobs.py`
- key args:
  - `--page-ranges <start-end>`
  - `--no-auto-split`
  - `--chunk-size 1`
  - `--language ch`
  - `--timeout 7200`
- range jobs: 45
- already-done skip: 2 for `text01`
- remaining submitted: 43
- failed submissions: 0
- parent synthesize: done for all 21 long PDFs
- part symlink: parent `parts/<part>` now symlinks to actual range output dirs, so assets resolve.

DocPreprocess/export:

- IR output root: `processed_data/ir/mineru`
- quality:
  - `processed_data/quality/group_a_mineru_quality_report.json`
  - `processed_data/quality/group_a_mineru_object_quality.jsonl`
- evidence units:
  - `processed_data/evidence_units/group_a_evidence_units.jsonl`
- selector:
  - `processed_data/selector/group_a_selector_search.jsonl`
- final corpus:
  - `processed_data/docs.jsonl`
  - `processed_data/chunks.jsonl`
  - `processed_data/tables.jsonl`

### 结果

新增脚本：

- `script/01_prepare_question_sources.py`
  - 解析 Group A 问题引用的 `doc_ids`，生成 PDF/non-PDF/missing manifest，并 staging 问题相关 PDF。
- `script/02_run_mineru_question_pdfs.py`
  - 安全包装 MinerU folder 解析；支持 dry-run，检查 `.env` 中 key 存在但不打印密钥。
- `script/02_plan_mineru_jobs.py`
  - 按页面数生成 under-200 stage、smoke stage、long-PDF page-range jobs。
- `script/02_run_mineru_range_jobs.py`
  - 对长 PDF 使用 `page_ranges + --no-auto-split`，并合成 parent `result.json/full.md/parts`。
- `script/03_build_mineru_ir.py`
  - 调用 DocPreprocess normalizer；支持 split/range split merge、page offset、ID prefix、asset path prefix。
- `script/04_export_preprocessed_corpus.py`
  - 导出 docs/chunks/tables；非 PDF 法规正文清洗与条款级切分；统一 trace 字段、locator、asset path、数字清洗。
- `script/05_audit_preprocessed_outputs.py`
  - 审计 docs/chunks/tables、PDF IR 覆盖、问题覆盖、orphan、可疑负数 token 和 warnings。

主要产物：

- `processed_data/manifests/group_a_question_docs.jsonl`: 68
- `processed_data/manifests/group_a_question_pdfs.jsonl`: 59
- `processed_data/manifests/group_a_question_nonpdf.jsonl`: 9
- `processed_data/manifests/group_a_mineru_direct_under200.jsonl`: 38
- `processed_data/manifests/group_a_mineru_range_jobs.jsonl`: 45
- `processed_data/reports/group_a_pdf_page_counts.jsonl`
- `processed_data/reports/mineru_ir_build_report.json`
- `processed_data/reports/group_a_preprocessed_audit.json`
- `processed_data/reports/group_a_preprocessed_audit.md`
- `processed_data/docs.jsonl`
- `processed_data/chunks.jsonl`
- `processed_data/tables.jsonl`

最终统计：

- MinerU PDF result:
  - expected PDF docs: 59
  - built IR: 59
  - skipped: 0
  - failures: 0
- final corpus:
  - docs: 68
  - chunks: 66,894
  - PDF chunks: 66,512
  - non-PDF chunks: 382
  - tables: 6,957
  - evidence units: 73,911
  - selector rows: 66,512
- question coverage:
  - total questions: 100
  - covered questions: 100
  - every domain covered: 20/20
- domain stats:
  - `financial_contracts`: docs=13, chunks=33,943, tables=3,630, covered_questions=20
  - `financial_reports`: docs=9, chunks=21,543, tables=2,924, covered_questions=20
  - `insurance`: docs=16, chunks=4,260, tables=133, covered_questions=20
  - `regulatory`: docs=15, chunks=2,241, tables=15, covered_questions=20
  - `research`: docs=15, chunks=4,907, tables=255, covered_questions=20
- strict audit:
  - command: `python script/05_audit_preprocessed_outputs.py --strict`
  - warnings: `[]`
  - missing PDF IR: 0
  - orphan chunks/tables: 0
- asset check:
  - asset paths checked: 8,038
  - missing asset paths: 0
- disk:
  - `processed_data/mineru_input/mineru`: 3.0G
  - `processed_data/ir/mineru`: 106M
  - `processed_data/chunks.jsonl`: 98M
  - `processed_data/tables.jsonl`: 29M
  - removed stale failed physical split cache: `processed_data/mineru_input/mineru/financial_contracts__text01/.split_work` (~4.6G)

Subagent 审计：

- mapping/staging audit:
  - 100 questions, 231 doc mentions, 68 unique doc pairs.
  - 59 PDF symlinks valid, 9 non-PDF docs valid, 0 missing.
- schema/script audit:
  - 修复 missing PDF IR 静默通过问题。
  - 修复 split failed state 被当成 builder failure 的问题。
  - 补充 split part state 检查、qualified IDs、locator/asset trace。
  - 修复 stale IR orphan 风险和负数/年份抽取边界。
- output audit:
  - 先用 smoke PDF 验证 MinerU -> IR -> export -> audit。
  - 再跑 under-200 全量和 page-range 长 PDF 全量。
  - 最终严格审计无 warning。

### 下一步

建议：

1. 在现有 `processed_data/chunks.jsonl/tables.jsonl` 上重跑规则检索和 candidate evidence pack，替换早期基于不完整 corpus 的草标候选。
2. 使用 GLM/用户指定模型做 dev/eval 复核，不调用 Qwen，除非用户明确授权官方链路。
3. 重点查看 quality report 中 `reject` 表格较多的原因；很多是缺 caption/asset 质量标记，但文本/table HTML 仍可用于检索。

## AFAC2026-4 multi-subagent second-pass review v1

### 任务

按“多 subagent 模拟人工复查”的方式，对首轮全量答题中 13 道 `needs_review` 题逐题复核：

1. 让不同 reviewer 从证据、选项排除、题型一致性三个角度交叉检查。
2. 只在证据共识明确时改动答案；题目自身冲突或无完全正确选项时保留标记。
3. 把复查结论沉淀为逐题 JSONL/CSV、二轮答案 CSV 和摘要文档。

### 环境

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- runtime: system Python used for local scripts
- date/timezone: 2026-07-07, Asia/Shanghai
- source answer file: `processed_data/agent_evidence_seed/group_a_all_agent_answers.csv`
- source review set: `processed_data/agent_evidence_seed/group_a_all_needs_review.jsonl`
- second-pass decision file: `processed_data/agent_evidence_seed/group_a_needs_review_second_pass.jsonl`

### 超参数 / 配置

- review target: first-pass `needs_review` only, 13/100 questions
- effective subagents:
  - Turing: financial contracts and financial reports review
  - Lagrange: adversarial review across all 13 `needs_review` rows
  - main agent: merge consensus and apply conservative answer updates
- failed reviewer attempts: two attempted workers hit concurrency errors and were excluded from accepted decisions
- answer-change rule: require concrete evidence-level consensus; otherwise preserve first-pass answer and write status/caveat
- model/API calls: no Qwen official inference; no external web search in this pass

### 结果

新增脚本：

- `script/10_apply_second_pass_review.py`
  - reads first-pass answer CSV and second-pass JSONL
  - writes second-pass compact answer CSV with `answer_draft_second_pass`, `second_pass_status`, `second_pass_note`
  - writes a JSON report with changed-answer list

新增产物：

- `processed_data/agent_evidence_seed/group_a_needs_review_second_pass.jsonl`
- `processed_data/agent_evidence_seed/group_a_needs_review_second_pass.csv`
- `processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass.csv`
- `processed_data/agent_evidence_seed/group_a_all_agent_answers_second_pass_report.json`
- `processed_data/agent_evidence_seed/group_a_second_pass_review_summary.md`

最终统计：

- total answers: 100
- second-pass reviewed rows: 13
- changed answers: 1
- unchanged rows: 99
- status distribution:
  - `unreviewed`: 87
  - `confirm`: 7
  - `confirm_with_caveat`: 3
  - `correct`: 1
  - `uncertain_question_conflict`: 1
  - `uncertain_no_full_correct_option`: 1

答案变更：

- `fc_a_012`: `ACD -> AC`
  - 理由：A/C 有证据支持，B 不成立；D 的 150% 证据对应“违约金”公式，而选项问“违约利息/逾期利息”公式，严格措辞下不选 D。

保留的结构性问题：

- `fc_a_015`: 保留 `AB`，但标记 `uncertain_question_conflict`
  - 事实支持 A 和 B，C/D 不成立；题目元信息为 `mcq`，属于单选题型冲突。
- `ins_a_020`: 保留 `D`，但标记 `uncertain_no_full_correct_option`
  - D 是强制选择下最接近答案；但家财险水管爆裂导致地板损坏缺少正向保障证据，严格看 A-D 无完全正确选项。

带 caveat 的确认：

- `fin_a_008 = B`: 按年度现金分红、不含特别分红口径成立。
- `fin_a_015 = A`: 同样依赖年度现金分红口径。
- `reg_a_016 = ABCD`: C 需要按“已取得和未能证明无法取得的未付业务收入纳入罚没基数”理解。

验证：

- `python script/10_apply_second_pass_review.py`
  - output: `{"rows": 100, "changed": 1}`
- `python -m py_compile script/06_build_agent_evidence_seed.py script/07_merge_agent_drafts.py script/08_build_all_agent_drafts.py script/09_export_agent_answers.py script/10_apply_second_pass_review.py`
  - passed

## AFAC2026-4 git repository initialization v1

### 任务

在当前 AFAC2026-4 workspace 根目录建立本地 Git 仓库，便于后续追踪方案、脚本、数据处理记录和实验进展。

### 环境

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell: `bash`
- date/timezone: 2026-07-07, Asia/Shanghai
- git branch: `main`

### 超参数 / 配置

- repository command: `git init -b main`
- commit policy: 本次只初始化仓库，不创建首次提交，避免将大文件和中间数据未经 `.gitignore` 筛选直接纳入版本控制。
- tracked files: none yet

### 结果

- 已在项目根目录创建 `.git/`。
- 当前仓库处于 empty repository 状态，尚无 commit。
- `git status --short` 显示以下内容仍为 untracked：
  - `1-progress/`
  - `AGENTS.md`
  - `data/`
  - `design.md`
  - `introduction.md`
  - `processed_data/`
  - `progress.md`
  - `public_dataset_a.zip`
  - `script/`

建议下一步先补充 `.gitignore`，至少排除原始压缩包、大体积预处理产物、运行缓存和临时日志，再进行首次提交。

## AFAC2026-4 gitignore and initial commit v1

### 任务

继续完善本地 Git 仓库：补充 `.gitignore`，验证大文件和生成目录不会被纳入版本控制，并准备首次轻量提交。

### 环境

- workspace: `/public/home/zhangfanjin/zhangnianhao/11-competetion/AFAC2026-4`
- shell: `bash`
- date/timezone: 2026-07-07, Asia/Shanghai
- git branch: `main`
- git identity:
  - user.name: `Fanjin Zhang`
  - user.email: `zfjsail@163.com`

### 超参数 / 配置

- `.gitignore` policy:
  - ignore Python cache and local env files
  - ignore secrets such as `.env`
  - ignore raw/reprocessed competition data: `data/`, `processed_data/`, `public_dataset_a.zip`
  - ignore large model/checkpoint artifacts: `checkpoints/`, `models/`, `*.safetensors`, `*.pt`, `*.pth`, `*.ckpt`, `*.bin`
  - ignore common run outputs: `runs/`, `outputs/`, `wandb/`
- first commit scope:
  - include: `.gitignore`, `AGENTS.md`, `design.md`, `introduction.md`, `progress.md`, `1-progress/`, `script/*.py`
  - exclude: raw data, processed data, archives, Python bytecode
- repository size context: workspace total about 6.7G, dominated by dataset/archive/preprocessing outputs.

### 结果

- 已新增 `.gitignore`。
- 已验证以下路径会被 Git 忽略：
  - `public_dataset_a.zip`
  - `data/`
  - `processed_data/`
  - `script/__pycache__/`
- 首次提交前的计划跟踪范围仅包含轻量源码、文档和进度文件，避免把 6.7G 数据资产提交到仓库。
