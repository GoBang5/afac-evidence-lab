# 泛化与消融实验｜2026-09-30

本轮完成外部检索泛化、6 组 AFAC 组件消融与外部缓存等价实验。FinQA 1,147 题的宏平均证据 Recall@5 为 **80.60%**，全部标注证据进入前 5 的题目占 **68.96%（791/1,147）**。AFAC 去掉文档覆盖优先后，指定文档完整覆盖从 **95/100 降至 91/100**；去掉逐选项检索后降至 **87/100**。

这些结果验证的是检索与证据选择。**真实模型调用为 0，答案准确率尚未评测。** 没有把上游比赛成绩、旧项目的模型实验或伪标签计入本轮成果。

## 数据与固定协议

外部数据使用 [FinQA 官方公开测试集](https://github.com/czyssrs/FinQA)，固定版本 `0f16e2867befa6840783e58be38c9efb9229d742`：1,147 题、100 家公司、35,862 个文本/表格行候选。下载文件 14,395,143 字节，Git blob SHA-1 `59958c7c3bb3b21f4dff6bc912a0fe0ae710aee0` 与该版本源文件一致，SHA-256 另见 [数据清单](generalization/finqa-data-manifest.json)。本轮使用全部公开测试题，无训练、无基于测试结果的调参或筛题。

FinQA 只在每题已提供的文本和表格上下文内检索；这比搜索完整年报更受限，不能据此宣称跨长文档路由或数值推理能力。检索输入仅包含 `id/pre_text/post_text/table/qa.question`；`qa.gold_inds` 的事实编号单独落入评测文件，答案、程序、预置检索结果不进入输入。先保存检索预测，再加载标签评分。

所有表格行统一使用官方修正后的、与标签无关的转换模板，包括表头行。7,517 个表格行的序列化结果与固定版本官方函数逐条一致，避免正负例格式差异泄露标签。转换模板及派生事实编号遵循 [FinQA MIT 许可](generalization/FinQA-LICENSE.txt)。

AFAC 使用已参与过开发的 A 榜 100 题、68 份指定文档、19,114 个片段，是已知数据上的组件回归实验。没有可信答案标签，因此只报告文档与检索路线覆盖。此前使用过的 FinanceBench 不作为新的独立外部测试集重复包装。

[协议](generalization/protocol.json) 在本轮评分前写入，并随各次执行归档；这是本地固定协议，并非第三方预注册。实现与输入由各次 `run_manifest` 的源码/数据哈希标识。Python 3.9.6，macOS，标准库实现，无训练或 GPU 依赖。

## FinQA 泛化与评分消融

`Recall@k`：每题命中的标注事实数 / 该题标注事实总数，再对全部题目取平均。`All@k`：该题全部标注事实都在前 k 条中的比例。候选是完整的原文句段或表格行；本实验未经过 AFAC 的选择题提示词打包器。主指标为 All@5，其他指标用于诊断。

| 评分方案 | Recall@3 | Recall@5 | All@3 | All@5 |
|---|---:|---:|---:|---:|
| 完整评分 | 70.54% | **80.60%** | 56.23% | **68.96%** |
| 移除数字/年份加分 | 69.96% | 80.41% | 55.45% | 68.53% |
| 仅保留词频与 IDF 评分 | 70.15% | 80.27% | 55.97% | 68.53% |

第二组仅移除专门的数字与年份匹配奖励，文本中数字仍可通过词项匹配得分；第三组沿用相同查询，仅保留词频/IDF 分量，不是另行训练的检索模型，也不等同于标准 BM25。

以公司为簇、同题配对、固定种子 20260930 做 2,000 次 bootstrap，计算“消融 − 完整方案”的 All@5 差异：

| 对照 | 差异（百分点） | 95% 探索性区间（百分点） |
|---|---:|---:|
| 移除数字/年份加分 | −0.44 | [−1.18, +0.17] |
| 仅词频/IDF | −0.44 | [−1.76, +0.77] |

两个区间均包含 0，不能宣称完整评分具有显著优势。区间按公司整簇重采样、保留公司内题目相关性，且没有做多重比较校正，仅用来表示差异的不确定性。结果不是 FinQA 官方执行准确率或排行榜成绩。

完整方案的分层结果揭示了更重要的改进方向：

| 标注证据类型 | 题数 | Recall@5 | All@5 |
|---|---:|---:|---:|
| 纯文本 | 283 | 88.89% | 80.92% |
| 纯表格 | 706 | 82.09% | 74.36% |
| 文本与表格混合 | 158 | 59.14% | **23.42%** |

混合证据完整召回明显不足。当前逐条排序尚不能可靠地联合召回互补事实。纯文本组中，两种简化评分的 All@5 均为 81.63%，略高于完整评分的 80.92%；总分的小幅优势并非每类题都成立。两道题分别有 6、8 条标注事实，固定 top-5 不可能全召回；这两题仍保留在分母中，没有剔除。

## AFAC 组件消融

所有方案固定 system+user 消息内容上限 12,000 字符、最多 18 条证据、单条引用最多 900 字符；每选项候选 top-6，题干 top-14，文档 top-16。其余设置不变。

| 方案 | 指定文档完整覆盖 | 全选项检索路线覆盖 | 平均提示词字符 | 超预算题数 |
|---|---:|---:|---:|---:|
| 完整方案 | **95/100** | 100/100 | 11,592.12 | 0 |
| 去掉文档覆盖优先 | 91/100 | 100/100 | 11,589.47 | 0 |
| 去掉选项路线覆盖优先 | 95/100 | 100/100 | 11,587.81 | 0 |
| 去掉全部覆盖优先 | 91/100 | 100/100 | 11,585.16 | 0 |
| 去掉逐选项查询，仅题干检索 | 87/100 | 不适用¹ | 11,495.37 | 0 |
| 去掉按新增字符成本归一化 | 95/100 | 100/100 | 11,685.00 | 0 |

¹ 原始记录为 0，因为选项查询被关闭，路线标签随之消失。这是实验定义的直接结果，不能作为语义质量下降的证据。此消融同时减少查询次数和候选池规模，因此 8 题覆盖差异不能单独归因为查询语义。

文档覆盖优先的 4 题收益均出现在保险类：`ins_a_002/005/008/010`。完整方案没有在其他题上造成文档覆盖回退。逐选项查询的 8 题收益分布在财报、保险、法规、研究报告类，逐题编号及分领域统计见结果文件。

本数据上，选项路线优先没有增加完整覆盖题数；该指标已达 100/100，不能据此认定策略对答案无用。字符成本归一化平均减少 92.88 字符，并使平均证据条数从 11.86 增至 12.17，文档完整覆盖不变；未证明真实 Token、费用或答案质量收益。

指定文档完整覆盖只要求每份指定文档至少有一条片段；选项路线覆盖只要求选项查询返回的候选被选中。两者均不证明证据足以支持正确答案。

## 外部数据上的缓存实验

同一 FinQA 输入，上游原始检索与新增缓存检索进行 1 轮冷启动、3 轮热缓存对照。交替执行先后顺序，保留题干 top-14；计时仅含检索，排除加载、打包、模型和网络。质量实验的 top-5 与本缓存协议分开记录。

| 指标 | 上游原始 | 新增缓存 |
|---|---:|---:|
| 冷启动完整一轮 | 1.848 秒 | 2.178 秒 |
| 热缓存完整一轮，3 轮均值 | 0.789 秒 | 0.324 秒 |

热缓存比值 **2.43×**；冷启动缓存填充有额外开销。本机短时基准受系统负载影响，不能外推生产吞吐量。1,147 × 4 = **4,588** 次对照的返回候选分数、特征和顺序完全一致；未宣称逐个穷举比较全部候选。

## 验证与材料清单

- Material Passport：来源 `academic-research-suite / experiment-agent`；日期 2026-09-30；版本 v1；状态 VERIFIED（离线实跑与确定性复跑一致），真实模型评测未执行。
- 29 项测试通过，覆盖标签隔离、错误事实编号、评分分母、成簇配对、消融控制以及既有预算/引用/断点恢复。
- FinQA 预测、逐题评分、汇总文件二次执行字节一致；AFAC 逐题结果二次执行字节一致。计时不要求一致。
- 新增开关的默认配置与上一轮 AFAC 100 题的证据 ID 和提示词字符数逐题完全一致。
- 未发生评测崩溃或样本排除；首次数据下载有网络超时，完整下载后通过 Git blob 与文件哈希验证。
- 统计解释检查 11/11 项：按证据类型披露异质性；避免从聚合分数推个体正确率；保留全部样本；不做碰撞变量控制或极端样本筛选；无诊断率基率主张；公开全部预定对照；不从工程覆盖推断答案因果；无反向因果主张。主要限制是已知 AFAC 数据、公开外部数据、仅检索指标和未经多重校正的探索性区间。

| 材料 | 文件 |
|---|---|
| 固定协议与复跑核验 | [protocol.json](generalization/protocol.json)、[verification.json](generalization/verification.json) |
| AFAC 六组结果 | [summary](generalization/afac-summary.json)、[逐题结果](generalization/afac-rows.jsonl) |
| FinQA 三组结果 | [summary](generalization/finqa-summary.json)、[逐题结果](generalization/finqa-rows.jsonl)、[评分前预测](generalization/finqa-predictions.jsonl) |
| 缓存对照 | [summary](generalization/cache-summary.json)、[一致性检查](generalization/cache-checks.jsonl)、[逐题计时](generalization/cache-timing.jsonl) |
| 源码和输入哈希 | [AFAC](generalization/afac-run_manifest.json)、[FinQA](generalization/finqa-run_manifest.json)、[cache](generalization/cache-run_manifest.json) |

## 复现

在仓库根目录执行。`--protocol` 用于归档协议；参数由本版本实现固定，不会动态加载该 JSON 中的任意配置。输出目录必须不存在，以防覆盖既有实验。

```bash
mkdir -p data/finqa-source
curl --compressed -fL \
  https://raw.githubusercontent.com/czyssrs/FinQA/0f16e2867befa6840783e58be38c9efb9229d742/dataset/test.json \
  -o data/finqa-source/test.json
python3 -m evidence_lab.experiments prepare-finqa \
  --source data/finqa-source/test.json --out data/finqa-test
python3 -m evidence_lab.experiments finqa --data data/finqa-test \
  --out runs/generalization/finqa --protocol docs/lab/generalization/protocol.json
python3 -m evidence_lab.experiments cache --data data/finqa-test \
  --out runs/generalization/cache --protocol docs/lab/generalization/protocol.json
python3 -m unittest discover -s tests -v
```

AFAC 数据不随仓库发布。先按 [原运行说明](README.md) 转换持有的 A 榜数据，再把实际转换目录传给下列命令：

```bash
python3 -m evidence_lab.experiments afac --data /path/to/prepared-afac-a \
  --out runs/generalization/afac --protocol docs/lab/generalization/protocol.json
```

## 后续真实模型实验

需要模型名称、API 地址、密钥配置文件路径和费用上限，当前尚未收到。下一阶段应在开发集验证数值答案接口、单位/百分比归一化和执行评分，再冻结提示词，在未用于调优的测试题上比较同一模型的答案质量、实际 Token、延迟、失败率及引用正确性。当前 AFAC 选择题接口不能直接作为 FinQA 数值答案评测器。

混合证据补全可以作为下一项实现假设；需在开发数据上设计与调整，再用新的冻结协议评测。不能根据本次测试集结果修改策略后，继续将同一批题称为全新盲测。
