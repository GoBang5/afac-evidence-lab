# AFAC2026-4 Agent 流程与自进化框架设计

## 0. 设计结论

本任务应采用：

```text
自研规则检索流水线 + LangGraph 轻量状态编排 + 可配置 LLM 证据约束判题 + 日志驱动自进化
```

核心判断：

- 这不是传统开放式多 Agent 对话任务，而是批处理式金融长文档选择题任务。
- 赛题正式提交链路要求使用 Qwen 系列模型，且不得使用 embedding 模型做检索和推理。
- 本项目开发期默认不调用 Qwen；未经用户明确允许，不使用 Qwen API。
- 开发期效果验证和自进化优先使用 GLM，以及用户在 `/public/home/zhangfanjin/zhangnianhao/.env` 指定的其他模型。
- 得分同时受准确率和 token 消耗影响，因此优先级是：证据召回质量 > 答案约束 > token 控制 > Agent 形式感。
- LangGraph 只作为状态机和日志框架，不把 CrewAI/AutoGen/LlamaIndex 默认 RAG 作为主框架。

一句话方案：

```text
先用可审计的 lexical/rule retrieval 把证据找准，再让配置中的判题模型在小而硬的证据包里逐项判定 A/B/C/D，最后用日志和错误分析持续进化切分、检索、pack、prompt 与自检策略。
```

## 1. 约束与目标

### 1.1 赛题硬约束

- 文档类型：insurance、regulatory、financial_contracts、financial_reports、research。
- A 榜：题目提供 `doc_ids`，重点是文档内证据定位与推理。
- B 榜：题目不直接提供 `doc_ids`，需要先做候选文档召回。
- 答案类型：`mcq`、`multi`、`tf`，输出必须是合法大写字母。
- 官方提交阶段：题目理解、文档定位、段落检索、证据判断、答案生成均应使用 Qwen 系列模型或确定性规则。
- 开发验证阶段：允许使用 GLM 做效果验证、自进化建议、prompt/规则评估；也允许使用用户在 `.env` 中指定的其他模型。
- 默认禁止：未经用户明确许可调用 Qwen；embedding 检索；非官方提交链路的模型结果混入官方答题依赖。
- 官方提交仍禁止：embedding 检索、非 Qwen rerank、非 Qwen 答案投票、预生成语义摘要参与正式作答。
- 输出：`answer.csv`，入围后还需要 `evidence.json`、`processed_data/`、`agent/`、`script/`、`logs/` 等可复现材料。

### 1.2 优化目标

主目标：

```text
Accuracy 最大化
```

次目标：

```text
TotalTokens 控制在 3M-4.5M 优先，尽量低于 5M TokenBudget
```

工程目标：

- 每道题必须有可追溯证据。
- 每次模型调用必须记录 prompt/completion/total tokens。
- 每个答案必须能从日志复现。
- 每次规则或 prompt 修改必须有实验配置和 run_id。

### 1.3 模型使用策略

本项目分成两条模型链路：

| 链路 | 默认模型 | 用途 | 是否可进入官方提交 |
| --- | --- | --- | --- |
| dev/eval | GLM 或 `/public/home/zhangfanjin/zhangnianhao/.env` 指定模型 | 效果验证、自进化、prompt/规则诊断、错误分析 | 不直接作为官方提交结果 |
| official | Qwen 系列 | 赛题正式 answer.csv/evidence.json 生成 | 仅在用户明确允许后运行 |

执行规则：

- 默认运行 `dev/eval` 链路，使用 GLM 或用户指定模型。
- 任何 Qwen API 调用都必须先得到用户明确授权。
- `.env` 只读取模型 endpoint、model name、API key 等配置，不在日志、文档和最终回答中打印密钥。
- 自进化可以让 GLM 或指定模型提出规则/prompt/config 修改建议，但最终晋级的内容必须变成可复现的代码、规则、配置或 prompt。
- 官方提交链路不得使用 GLM/其他非 Qwen 模型的运行时答案、rerank、候选过滤或语义摘要。

## 2. 总体架构

```text
data/raw/*
  |
  v
PDF/HTML/TXT 预处理
  |
  v
processed_data/
  docs.jsonl
  chunks.jsonl
  tables.jsonl
  aliases.json
  indices/*
  |
  v
Agent Runtime
  parse_question
  route_candidate_docs
  build_option_queries
  retrieve_evidence
  pack_context
  llm_judge
  local_verify
  repair_if_needed
  write_outputs
  |
  v
answer.csv + evidence.json + logs/run_id/*.jsonl
```

推荐目录：

```text
agent/
  main.py
  config.py
  graph.py
  schema.py
  nodes/
    parse_question.py
    route_docs.py
    build_queries.py
    retrieve_evidence.py
    pack_context.py
    llm_judge.py
    verify_answer.py
    repair.py
    write_outputs.py
  retrieval/
    bm25.py
    lexical.py
    numbers.py
    sections.py
    rank_rules.py
  prompts/
    base_judge.txt
    insurance.txt
    regulatory.txt
    financial_contracts.txt
    financial_reports.txt
    research.txt
  utils/
    answer_parser.py
    token_counter.py
    evidence_writer.py
    logger.py
script/
  01_parse_documents.py
  02_build_chunks.py
  03_build_indices.py
  04_run_agent.py
  05_make_submission.py
experiments/
  configs/
  reports/
logs/
processed_data/
```

## 3. 预处理层

预处理层可以使用 PDF/OCR/版面工具，但产物只能是结构化文本、表格、页码、章节、条款等客观解析结果，不能把非官方链路模型生成的语义摘要、向量、排序结果写入正式答题链路。

### 3.1 产物

`docs.jsonl`：

```json
{
  "doc_id": "annual_byd_2025_report",
  "domain": "financial_reports",
  "title": "比亚迪2025年年度报告",
  "path": "data/raw/financial_reports/annual_byd_2025_report.PDF",
  "source_type": "pdf",
  "pages": 320
}
```

`chunks.jsonl`：

```json
{
  "chunk_id": "annual_byd_2025_report_p37_c02",
  "doc_id": "annual_byd_2025_report",
  "domain": "financial_reports",
  "page": 37,
  "section_path": ["第三节 管理层讨论与分析", "主要会计数据"],
  "text": "...",
  "table_id": null,
  "terms": ["营业收入", "净利润", "研发投入"],
  "numbers": ["2025", "2024", "12.3%", "100万元"],
  "char_len": 780
}
```

`tables.jsonl`：

```json
{
  "table_id": "annual_byd_2025_report_p37_t01",
  "doc_id": "annual_byd_2025_report",
  "page": 37,
  "caption": "主要会计数据和财务指标",
  "text": "指标 | 2025 | 2024 | 同比...",
  "row_headers": ["营业收入", "归母净利润"],
  "col_headers": ["2025", "2024"]
}
```

### 3.2 切分策略

不要统一硬切 500 字。按领域做结构切分，再用滑窗补充。

| 领域 | 主切分单位 | 补充策略 |
| --- | --- | --- |
| insurance | 产品名称、责任条款、给付公式、责任免除、现金价值、退保、领取规则 | 条款相邻段落合并，保留公式上下文 |
| regulatory | 法规名称、章、节、条、款、项 | 条文级 chunk，相邻条文可按引用关系扩展 |
| financial_contracts | 发行人、债券名称、规模、期限、利率、评级、担保、赎回、回售、违约、受托管理人 | 表格字段和正文条款双索引 |
| financial_reports | 公司、年度、主要会计数据、现金流、研发投入、分红、风险、管理层讨论 | 表格转文本，指标同义词归一 |
| research | 行业、公司、指标、预测、结论、竞争格局、风险提示 | 图表标题和正文邻域合并 |

## 4. 正式 Agent 流程

### 4.1 状态结构

```python
class AgentState(TypedDict):
    run_id: str
    qid: str
    domain: str
    split: str
    question: str
    options: dict[str, str]
    answer_format: str
    doc_ids: list[str] | None

    question_features: dict
    candidate_docs: list[dict]
    option_queries: dict[str, list[str]]
    retrieved_by_option: dict[str, list[dict]]
    packed_evidence: list[dict]

    judge_response: dict
    option_judgement: dict
    answer_raw: str
    answer_norm: str
    confidence: float
    repair_count: int

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    logs: list[dict]
```

### 4.2 LangGraph 节点

```text
load_question
  |
  v
parse_question
  |
  v
route_candidate_docs
  |-- A split with doc_ids --> use_given_docs
  |-- B split/no doc_ids ---> retrieve_candidate_docs
  |
  v
build_option_queries
  |
  v
retrieve_evidence_by_option
  |
  v
fuse_and_rerank_evidence
  |
  v
pack_context
  |
  v
llm_judge
  |
  v
normalize_and_verify
  |
  |-- pass --> write_result
  |
  |-- fail/low_confidence --> supplementary_retrieve
                                  |
                                  v
                              llm_verify
                                  |
                                  v
                              write_result
```

### 4.3 节点职责

`parse_question`：

- 提取题型、领域、公司/产品/法规/债券/行业实体。
- 提取年份、日期、金额、比例、阈值、条款号、指标名。
- 判断是否是跨文档比较、计算题、排序题、条件合规题。

`route_candidate_docs`：

- A 榜：严格使用题目给定 `doc_ids`。
- B 榜：先在同 domain 内做 doc-level lexical retrieval，召回 top 3-5 文档。
- 如果题目出现明确标题、公司名、产品名、法规名，规则匹配优先于 BM25。

`build_option_queries`：

- 构造 `question_query` 和 `option_query[A-D]`。
- 多选题必须做选项级检索，不能只用题干检索。
- 每个选项提取独立证据点，例如指标、公式、条款、否定词、比较对象。

`retrieve_evidence_by_option`：

- 在候选文档内做 chunk-level BM25 + 规则打分。
- 每个选项保留 top k 证据，默认 `k=6`。
- 对命中条款号、指标名、年份、金额、百分比、公式词的 chunk 加权。

`fuse_and_rerank_evidence`：

- 合并四个选项证据，去重。
- 保留每个选项至少 2 条候选证据，避免被强势选项挤掉。
- 对表格 chunk 与正文解释 chunk 做配对。

`pack_context`：

- 按选项组织证据，而不是按文档无序堆叠。
- 每条证据保留 `evidence_id/doc_id/page/section/text`。
- 限制单题输入 token，低风险题 6k-10k，中风险 10k-18k，高风险 18k-30k。

`llm_judge`：

- 只让配置中的判题模型做证据约束下的选项真伪判断。
- 开发期默认使用 GLM 或用户指定模型；官方提交前需用户确认后才切换到 Qwen。
- 输出 JSON：每个选项 `TRUE/FALSE/UNKNOWN`、证据 id、短理由、最终答案。
- 禁止自由发挥和常识补全。

`normalize_and_verify`：

- 本地解析答案，单选/判断取首个合法字母，多选去重排序。
- 检查答案是否符合题型。
- 检查证据 id 是否存在。
- 检查异常形态：空答案、全选、全不选、UNKNOWN 过多、选项理由与 verdict 冲突。

`supplementary_retrieve`：

- 只对低置信选项追加检索。
- 最多修复 1 轮，避免 token 失控。
- 修复查询优先使用缺失实体、数字、条款号、否定词。

## 5. 检索框架

### 5.1 不能用 embedding，采用强 lexical retrieval

推荐组合：

```text
BM25
+ 精确关键词匹配
+ 标题/章节匹配
+ 条款号匹配
+ 年份/日期/金额/比例匹配
+ 指标同义词匹配
+ 产品/公司/法规别名匹配
+ 选项级 evidence coverage
+ 邻近 chunk 扩展
```

### 5.2 打分函数

```text
score(chunk, option) =
  1.00 * bm25(question + option, chunk)
+ 0.80 * exact_entity_hit
+ 0.70 * number_year_hit
+ 0.60 * section_title_hit
+ 0.60 * law_article_or_clause_hit
+ 0.50 * table_header_hit
+ 0.40 * domain_keyword_hit
+ 0.30 * neighbor_bonus
- 0.50 * wrong_doc_penalty
- 0.40 * stale_year_penalty
```

权重进入 `experiments/configs/*.yaml`，通过自进化框架调参，而不是写死在代码里。

### 5.3 A/B 榜策略

A 榜：

```text
doc_ids 已知
  -> 只在指定文档内召回
  -> option-level chunk retrieval
  -> llm_judge 判题
```

B 榜：

```text
domain 已知
  -> doc-level retrieval top 3-5
  -> 规则校验候选文档实体
  -> option-level chunk retrieval
  -> 必要时调用配置模型做轻量文档选择
  -> llm_judge 判题
```

B 榜文档选择阶段尽量用规则完成。只有候选文档分数接近、题目实体模糊时，才调用配置模型选择候选文档，并计入 token；官方提交链路的该步骤需使用 Qwen 且提前获得用户许可。

## 6. 分领域策略

### 6.1 Insurance

关键能力：

- 产品别名归一。
- 身故保险金、满期保险金、退保、现金价值、账户价值、已领年金等公式识别。
- 年龄、领取日前/后、等待期、责任免除等条件判断。
- 排序题和计算题本地先计算，再交给配置模型核验。

检索关键词：

```text
身故保险金、给付、现金价值、已交保险费、账户价值、基本保险金额、
领取日前、领取日后、退保、养老年金、责任免除
```

自检规则：

- 选项里出现具体金额时，本地抽取金额并与公式计算结果比对。
- 排序题检查大小关系是否与计算值一致。

### 6.2 Regulatory

关键能力：

- 法规标题和简称匹配。
- 第几条/第几款/第几项精确切分。
- 施行日期、报告时限、比例阈值、处罚/义务主体识别。
- “必须/可以/不得/应当/无需”等规范性词语对齐。

检索关键词：

```text
第.*条、第.*款、应当、不得、可以、工作日、施行、备案、报告、
股东会、特别决议、普通决议、三分之二、过半数
```

自检规则：

- 如果选项引用具体条号但证据未命中该条号，触发补检。
- 如果题目涉及时限/比例而证据缺少数字，触发补检。

### 6.3 Financial Contracts

关键能力：

- 发行人、债券名称、发行规模、期限、票面利率、评级、担保、赎回、回售、违约、受托管理人字段抽取。
- 多份募集说明书横向比较。
- 表格字段和正文条款互证。

检索关键词：

```text
发行人、发行规模、募集资金、主体信用评级、债项评级、
受托管理人、主承销商、担保、赎回、回售、违约
```

自检规则：

- 比较题至少保留每个文档一条证据。
- 如果选项涉及“均为/都/全部”，必须检查所有相关文档。

### 6.4 Financial Reports

关键能力：

- 公司年度识别。
- 财务指标同义词：营业收入/营收，归母净利润/归属于上市公司股东的净利润，经营现金流/经营活动产生的现金流量净额。
- 跨年比较、同比变化、比例计算。
- 表格抽取质量很关键。

检索关键词：

```text
营业收入、归属于上市公司股东的净利润、经营活动产生的现金流量净额、
研发投入、占营业收入比例、分红、现金分红、同比、增长、下降
```

自检规则：

- 跨年比较必须同时命中两个年份。
- 比例题本地计算，配置模型只负责核验证据和解释。

### 6.5 Research

关键能力：

- 行业、公司、指标、市场空间、预测年份、同比/复合增速识别。
- 图表标题、表格数据、正文结论的邻域合并。
- 多研报、多行业比较。

检索关键词：

```text
市场规模、预计、同比、复合增速、CAGR、渗透率、保费、营收、
风险提示、竞争格局、行业趋势
```

自检规则：

- 预测题必须保留预测年份。
- 增速题检查单位：同比、CAGR、复合增速不能混用。

## 7. 判题模型 Prompt

基础模板：

```text
你是金融长文档选择题判题器。
你只能依据给定证据判断，不能使用常识或外部知识。
如果证据不足，必须标记 UNKNOWN，不要猜。

题型：{answer_format}
领域：{domain}
题干：{question}

选项：
A. {A}
B. {B}
C. {C}
D. {D}

证据按选项组织：
{packed_evidence}

请逐项判断每个选项。
输出严格 JSON，不要输出 Markdown：
{
  "option_judgement": {
    "A": {"verdict": "TRUE|FALSE|UNKNOWN", "evidence_ids": [1], "reason": "..."},
    "B": {"verdict": "TRUE|FALSE|UNKNOWN", "evidence_ids": [2], "reason": "..."},
    "C": {"verdict": "TRUE|FALSE|UNKNOWN", "evidence_ids": [3], "reason": "..."},
    "D": {"verdict": "TRUE|FALSE|UNKNOWN", "evidence_ids": [4], "reason": "..."}
  },
  "answer": "按题型输出合法答案字母"
}
```

领域 prompt 只补充该领域的判断要点，不增加长篇解释，避免 token 浪费。

## 8. Token 策略

三档预算：

| 档位 | 触发条件 | 模型调用 | 单题目标 token |
| --- | --- | --- | --- |
| L1 低成本 | A 榜、doc_ids 明确、证据集中、非复杂计算 | 1 次 llm_judge | 6k-12k |
| L2 标准 | 多选、跨文档、跨年、表格/公式题 | 1 次 llm_judge + 更大证据包 | 12k-22k |
| L3 修复 | UNKNOWN 多、证据缺数、答案异常、候选文档冲突 | 2 次模型调用，第二次只看缺失选项 | 22k-35k |

控制原则：

- 不全文输入。
- 不每题固定多轮。
- 不让判题模型读取无关候选文档。
- 优先压缩证据数量，而不是压缩关键字段。
- prompt 中不输出长 CoT，只输出短理由和证据 id。

## 9. 自进化框架

这里的“自进化”指 Agent/检索/配置/prompt 的日志驱动迭代，不是训练或修改基座模型参数。开发期自进化允许使用 GLM 和用户在 `.env` 中指定的其他模型做效果验证、错误诊断和修改建议；正式提交时，所有进化结果必须体现为可复现的代码、规则、配置和 prompt 版本。

### 9.1 自进化闭环

```text
run_agent(config_vN)
  |
  v
collect logs/answers/evidence/tokens
  |
  v
mine_failures
  |
  v
propose_changes
  |
  v
validate_on_dev_or_manual_set
  |
  v
promote_config_vN+1
```

### 9.2 日志字段

每道题写入 `logs/{run_id}/questions.jsonl`：

```json
{
  "run_id": "20260707_rule_glm_eval_v0",
  "qid": "fin_a_001",
  "domain": "financial_reports",
  "answer": "AC",
  "answer_format": "multi",
  "candidate_docs": ["annual_byd_2024_report", "annual_byd_2025_report"],
  "retrieval": {
    "A": [{"chunk_id": "...", "score": 12.3, "features": ["year_hit", "metric_hit"]}]
  },
  "evidence_ids": [1, 2, 3],
  "judge_response_path": "logs/.../fin_a_001.response.json",
  "judge_model": "glm_or_env_model",
  "prompt_tokens": 10000,
  "completion_tokens": 300,
  "total_tokens": 10300,
  "flags": ["multi", "cross_year", "calculation"],
  "warnings": []
}
```

### 9.3 失败类型

自动打标：

- `no_evidence`：某选项没有有效证据。
- `missing_number`：题目/选项有数字，证据无数字。
- `missing_year`：跨年题证据年份不足。
- `doc_imbalance`：多文档题证据只来自一个文档。
- `json_invalid`：模型输出 JSON 不合法。
- `answer_empty`：标准化后答案为空。
- `answer_suspicious_all`：多选题全选或全不选。
- `unknown_heavy`：UNKNOWN >= 2。
- `evidence_answer_conflict`：verdict 与答案字母不一致。
- `token_over_budget`：单题 token 超预算。

人工复核标签：

- `retrieval_miss`
- `parser_error`
- `table_error`
- `prompt_error`
- `reasoning_error`
- `rule_calculation_error`
- `ambiguous_question`

### 9.4 可进化单元

| 单元 | 可调内容 | 验证指标 |
| --- | --- | --- |
| parser | PDF 解析工具、表格格式、页码保留、标题识别 | 文本覆盖率、表格可读性、人工抽检 |
| chunker | chunk 大小、overlap、章节合并、表格邻域 | 证据命中率、平均证据 token |
| doc retriever | B 榜候选文档 top_k、标题权重、实体别名 | 候选 doc recall |
| chunk retriever | BM25 参数、规则权重、选项级 top_k | evidence recall、no_evidence 率 |
| packer | 每选项证据数、总 token 上限、去重策略 | token/题、UNKNOWN 率 |
| prompt | 领域提示、JSON schema、UNKNOWN 策略 | JSON 合法率、答案稳定性 |
| repair | 触发条件、补检 query、二次调用证据规模 | 修复收益/token |
| postprocess | 答案规范化、计算校验、冲突处理 | 非法答案率、异常答案率 |

### 9.5 实验评分

有标准答案或人工标注时：

```text
score = 100 * accuracy * (0.7 + 0.3 * max(0, min(1, (5_000_000 - total_tokens) / 5_000_000)))
```

没有标准答案时使用代理指标，不能代替最终准确率，只用于发现问题：

```text
proxy_score =
  0.25 * json_valid_rate
+ 0.20 * evidence_coverage_rate
+ 0.15 * number_year_coverage_rate
+ 0.15 * answer_stability_rate
+ 0.15 * low_warning_rate
+ 0.10 * token_efficiency
```

其中 `answer_stability_rate` 可以在开发期通过同一证据包下低温重复调用 GLM/指定模型，或比较不同 prompt 版本得到；正式提交 run 不做重复投票，避免 token 增长和合规风险。

### 9.6 变更晋级规则

一个配置从 `candidate` 晋级到 `stable`，至少满足：

- JSON 合法率不下降。
- 总 token 不超过上一 stable 配置 110%，除非人工确认准确率收益明显。
- 每个领域至少抽检 3-5 道题，不能只优化单一领域。
- 失败分析中没有新增高风险违规项，例如使用 embedding、把 GLM/非 Qwen 运行时结果混入官方提交链路、语义摘要缓存。
- 变更写入 `experiments/reports/{run_id}.md`。

### 9.7 合规边界

允许：

- 基于语料和题目构建词典、别名、正则、BM25 索引。
- 基于客观文本解析生成 chunk、table、section、page。
- 开发期用日志、人工复核、GLM/指定模型调整规则与 prompt。
- 开发验证阶段用 GLM 或 `.env` 指定模型做题目解析、候选判断、证据判定、答案生成和错误分析。
- 官方提交阶段在用户明确允许后，用 Qwen 做题目解析、候选判断、证据判定和答案生成，并计入 token。

不允许作为正式答题依赖：

- embedding 向量。
- GLM 或其他非 Qwen 模型生成的 rerank、摘要、QA、答案、候选过滤。
- 开发期模型生成的文档级语义摘要直接缓存到正式推理。
- 通过多模型投票提高答案。

## 10. 配置示例

```yaml
run:
  name: rule_glm_eval_v0
  mode: dev_eval
  env_file: /public/home/zhangfanjin/zhangnianhao/.env
  judge_provider: glm
  judge_model_env: GLM_MODEL
  qwen_enabled: false
  temperature: 0
  max_repair_rounds: 1

retrieval:
  doc_top_k_b: 5
  option_chunk_top_k: 6
  final_evidence_max: 18
  neighbor_window: 1
  weights:
    bm25: 1.0
    exact_entity: 0.8
    number_year: 0.7
    section_title: 0.6
    clause: 0.6
    table_header: 0.5

packing:
  max_tokens_l1: 10000
  max_tokens_l2: 18000
  max_tokens_l3: 30000
  min_evidence_per_option: 2

repair:
  trigger_unknown_count: 2
  trigger_no_evidence: true
  trigger_missing_number: true
  repair_top_k: 4
```

## 11. evidence.json 设计

```json
{
  "fin_a_001": {
    "answer": "AC",
    "evidence": [
      {
        "evidence_id": 1,
        "doc_id": "annual_byd_2025_report",
        "page": 37,
        "section_path": ["主要会计数据和财务指标"],
        "text": "...",
        "support_options": ["A"],
        "score": 14.2
      }
    ],
    "option_judgement": {
      "A": {
        "verdict": "TRUE",
        "evidence_ids": [1, 2],
        "reason": "..."
      }
    },
    "tokens": {
      "prompt_tokens": 10000,
      "completion_tokens": 300,
      "total_tokens": 10300
    }
  }
}
```

## 12. 实施路线图

### V0：可跑通 A 榜闭环

- PDF/TXT/HTML 抽取为 `docs.jsonl/chunks.jsonl/tables.jsonl`。
- 建 BM25 和规则检索。
- A 榜使用给定 `doc_ids` 做 option-level 检索。
- GLM/指定模型一次判题，作为开发期效果验证。
- 生成 `answer.csv/evidence.json/logs`。

### V1：分领域增强

- 保险公式与排序校验。
- 监管条文级切分与条号检索。
- 财报表格指标归一和跨年计算。
- 合同字段抽取与多文档比对。
- 研报图表/预测指标邻域检索。

### V2：自进化实验台

- 引入 `experiments/configs` 和 run_id。
- 自动汇总 token、非法答案、UNKNOWN、no_evidence、missing_number。
- 支持配置网格搜索和 prompt A/B。
- 形成错误案例库。

### V3：B 榜盲文档召回

- doc-level BM25 + 标题/实体/别名规则。
- top 3-5 候选文档召回。
- 候选冲突时使用配置模型做轻量 doc selector；官方提交链路需切换为 Qwen 且先得到用户许可。
- 进入同一套 option-level evidence pipeline。

### V4：官方提交链路

- 仅在用户明确允许后开启 `qwen_enabled: true`。
- 使用同一套可复现检索、pack、verify、output 逻辑。
- 清理或隔离 GLM/其他非 Qwen 开发期运行结果，确保官方 `answer.csv/evidence.json` 不依赖非 Qwen 运行时判断。

## 13. 当前最优先任务

1. 建立 `processed_data` 的客观解析和 chunk schema。
2. 先跑通 A 榜 100 题的本地闭环，哪怕答案未必高。
3. 从日志中抽 20 道题做人工证据复核，建立第一版失败标签。
4. 先优化检索召回，再优化 prompt；不要过早做复杂多轮 Agent。
5. 保持所有实验可复现，开发期 run 默认依赖规则、索引、GLM/指定模型和配置文件；官方 run 只有在用户许可后才切换到 Qwen。
