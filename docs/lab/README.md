# AFAC Evidence Lab 运行与设计说明

本项目在上游金融长文本问答 Agent 上增加可量化的性能优化、上下文限制和批处理恢复能力。默认只做离线检索与证据准备，模型接口可配置。

## 快速运行

在仓库根目录执行，实测 Python 3.9.6，新增模块仅依赖标准库：

```bash
python3 -m evidence_lab run --out runs/lab-demo
python3 -m evidence_lab run --out runs/lab-demo
python3 -m unittest discover -s tests -v
```

两道演示题及两份年报均为虚构。第二次运行的 `reused` 应为 2；没有模型调用，`answer` 为空且状态为 `needs_model_judge`，不会伪造答案。

接入已有文档解析数据：

```bash
python3 -m evidence_lab prepare --source /path/to/prepared --out /path/to/new-data
python3 -m evidence_lab run --data /path/to/new-data --out /path/to/new-run
python3 -m evidence_lab.benchmark --data /path/to/new-data --out /path/to/new-benchmark --repeats 3
```

`prepared` 目录需包含 `documents.json` 和 `questions-a.json`，示例结构见 `evidence_lab/data.py`。导入范围限定为 A 榜题目引用文档，不等同于全库 B 榜检索。所有新输出目录应按本地工作区组织规则放置。实验输出目录必须新建；任务续跑使用相同 run 输出目录。

## 执行链路

```mermaid
flowchart LR
 A[按页文本与题目白名单] --> B[文档路由与稀疏检索]
 B --> C[缓存片段静态特征和局部 IDF]
 C --> D[文档与选项覆盖选择]
 D --> E[完整提示词字符预算]
 E --> F[离线占位或模型判题]
 F --> G[答案与引用结构检查]
 G -->|需要复核且未超轮次| I[补充查询与扩大候选集]
 I --> D
 G -->|通过或轮次耗尽| H[SQLite 逐题检查点与结果日志]
```

**缓存。** `CachedIndex` 对不可变语料缓存片段数字、年份、条款和领域词命中；按有序候选文档集合缓存局部 IDF。评分公式和权重来自上游，改动不做模型训练。缓存仅属于当前进程、当前索引；候选 ID 必须全局唯一，语料更新需重新建索引。额外缓存会增加内存占用，当前未完成独立峰值内存对照。

**预算。** 使用与实际 `ModelJudge` 相同的 `build_judge_messages`，计算 system 与 user 两条消息内容的 Unicode 字符数，包含题目、输出 schema、证据元数据和正文。默认上限 12,000，最多 18 片段、单片段 900 字符。采用贪心覆盖选择：优先补齐缺失指定文档或选项检索路径，再按相关性与边际字符成本选择。每次加入前检验总预算；仅固定提示词就超限时失败，不强行截断题目。

这是字符预算，不是 Qwen Token 上限；不含模型响应和传输 JSON 外壳，不能由此推断实际 Token 消耗。`retrieval_options` 仅记录检索来源，`support_options` 不预设为真。覆盖某个选项的检索结果不意味着足以判断选项。

**引用。** 保留文档 ID、物理页号（从 1 开始）、原解析文本偏移、原片段哈希与展示引文哈希。HTML/TXT 不伪造页号。答案检查验证引用 ID 是否属于当前证据包、TRUE/FALSE 是否带引用、选择结果与逐项判断是否一致；UNKNOWN 标记为需要复核。`validated_structure` 只表示结构校验通过，不代表引用在语义上支持结论。哈希检测意外文本改变，不是外部签名或事实证明。

**恢复。** SQLite 每题一笔事务，成功完成的结果可复用。指纹覆盖所有 Agent/Lab Python 源文件、数据文件、预算、检索配置与模型端点/名称/采样配置。改变这些因素需要新输出目录；失败题不缓存为成功，后续可重试。这里是单进程批处理恢复：并发执行同一个输出目录不受支持；若模型请求完成后、写入检查点前进程崩溃，恢复时仍可能再次调用模型，不能宣称外部请求 exactly-once。

## 模型接入

新增运行器复用上游 OpenAI-compatible 客户端与严格 JSON 判题器。支持原有环境变量接入，以及 `--use-local-api` 从仓库上一层的 `api-config.local.env` 读取 `API_BASE_URL/API_MODEL/API_KEY`。配置作为数据解析，不执行 shell，不在运行指纹中保存密钥。数值题使用本地配置通道。

```bash
python3 -m evidence_lab run \
  --data /path/to/new-data --out /path/to/new-model-run \
  --judge-mode openai_compatible \
  --llm-base-url "$MODEL_BASE_URL" --llm-model "$MODEL_NAME" \
  --llm-api-key-env OPENAI_API_KEY --limit 2
```

Qwen 模式沿用上游 `--allow-qwen` 开关。早期版本仅使用传输 mock；随后已有真实模型评测。v1 单轮脚本与 v2 统一工作流的执行范围不同，详见[修复与验证报告](workflow-repair-report.md)。

## 验证与下一步

- 21 项测试覆盖页边界和答案字段隔离、重复候选 ID、等价评分、预算溢出、文档覆盖、虚假引用、引文改动、答案矛盾、检查点隔离、失败重试与模型适配链路。
- 100 题完整离线运行成功；第二次复用 100/100 检查点。
- 同数据运行上游与缓存检索，1 次冷启动和 3 次热缓存遍历中，返回候选的分数、特征、顺序全部一致。
- 5 道题仍缺部分指定文档。下一步应诊断候选召回与定向补查，冻结一组独立新样本后再验证，避免围绕同一 100 题反复调参。
- 若要写问答准确率，应先取得可信标注、单独配置模型并运行真实端到端评测；仓库 pseudo labels 不能当作官方答案。

本版本没有声称实现 MinerU、跨页表格重建、模型微调、ACE/OpenEvolve 自进化或获奖方案完整复现。实际解析输入来自本地已有 PyMuPDF/文本提取。

## 数值题与共同运行入口（2026-10-02）

`runner.run` 统一负责数据/代码/配置指纹、逐题检查点与请求缓存；`workflow.run_question` 根据 `answer_format` 路由选择题或数值题。`workflow_experiment.py` 直接调用同一 `runner.run`，预测落盘后才加载答案评分。

数值题流程：检索 → 完整证据单元字符预算 → 模型输出运算计划 → 数字引用/单位维度校验 → Decimal 计算 → 缺证或失败时定向查询并最多补检一次 → 输出。表格保存 `cells` 原始数组，第一行和邻近说明作为单独可引用事实，不强制把第一行解释为表头。预算不截断数值单元。初始 top-5，修复扩大至 top-12 并补充相关表格行，可附最多两条模型提供的检索查询。保守识别出的表头以 `column_labels` 与原始 `cells` 按位置对应。

`calculation` 已从自由文本改为受限表达式；操作数必须绑定证据 ID 与原文数字，百分比、千/百万/十亿尺度在执行器中转换。不使用 `eval`；属性访问、函数调用、下标、过大的指数、除零和单位维度冲突均拒绝。未解决的题返回空答案和 `needs_review`，不会把模型估算当作校验成功的答案。

`validated_calculation` 只证明给定计划的数字来源、运算与粗粒度单位维度通过检查，**不证明模型选择了正确指标、年份、公式或货币种类**。数值 yes/no 比较由程序执行；非数值 yes/no 仅检查引用，状态单独记为 `validated_citations`。不能用这些状态代替答案质量评测。

默认保留 12,000 提示词字符、18 个证据单元的硬上限；`--max-repair-rounds` 控制最多补检轮数（0–3），数值题输出最多 1,400 tokens。使用本地接口时记录每个请求的状态；请求结果未知或失败会停止，不自动重复计费。每个输出目录只允许一个进程。

消融项 `no_arithmetic_correction` 只关闭“程序计算结果替换模型估算”，保留引用与单位检查；不能叫做关闭全部验证器。复用完全相同的请求响应，因此该项可直接观察运算纠错的影响。
