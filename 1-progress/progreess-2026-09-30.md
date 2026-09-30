# 2026-09-30 GitHub 发布

任务：按用户要求将 AFAC Evidence Lab 上传到已确认的 `GoBang5` 账号。

环境：本地 macOS、Git、GitHub CLI；以 `gh api user` 核实当前用户为 `GoBang5`。目标仓库 `GoBang5/afac-evidence-lab`，初始可见性为私有，发布分支为 `main`。

超参数：本次仅发布，未改动模型或检索超参数，未调用真实模型。此前真实模型与独立测试集验证的讨论尚未转化为已完成的实验。

发布内容：已有 Agent/Lab 代码、两道虚构题的演示数据、21项测试、固定协议与实验结果、运行说明、贡献边界及4条简历候选表述。原始数据、运行数据库、环境凭证不进入本次新增提交。

核验：发布前逐文件核对 `docs/lab/benchmark-protocol.json` 中的源码哈希，确认与既有已测试实现一致；检查待上传文件的凭证模式。上游来源保留为 `upstream`，目标仓库设为 `origin`，通过当前 GitHub CLI 登录凭证推送。

结果记录：目标地址为 https://github.com/GoBang5/afac-evidence-lab 。推送后由 GitHub API 比较 `main` 与本地提交哈希，并检查默认分支、仓库归属与可见性。

后续用户要求公开，已通过 GitHub API 将仓库设为 PUBLIC 并核实。

## 泛化与消融

任务：执行外部泛化与组件消融，为简历表述补充可复核证据。

环境：Python 3.9.6、macOS、标准库；无GPU训练，无真实模型API配置。继续使用已发布的Evidence Lab；上游agent源码未变。实验工作流按academic-research-suite的协议、溯源与统计解释框架内联完成。

数据：FinQA官方公开test.json固定commit `0f16e2867befa6840783e58be38c9efb9229d742`，1,147题、100家公司、35,862候选。源文件Git blob hash与GitHub匹配；7,517表格行转换与官方修正函数完全一致。AFAC使用既有A100、68文档、19,114片段，仅作为回归消融。

超参数：AFAC字符预算12,000、证据18条、单引用900字符，option/query/doc top-k为6/14/16；六组为full、no_doc_priority、no_option_priority、no_coverage_priority、no_option_queries、no_cost_normalization。FinQA证据检索k=3/5，评分full/no_numeric_bonus/token_only；主指标All@5；以公司为簇做2,000次配对bootstrap，种子20260930。缓存实验top-14、1冷+3热、交替调用顺序。

结果：FinQA full Recall@5=80.6037%，All@5=68.9625%（791/1,147）；两个简化评分All@5均68.5266%，与full的差值区间包含零，不能宣称显著优越。混合证据158题All@5只有23.4177%，记录为短板，不在测试集上调参。AFAC完整文档覆盖依次95、91、95、91、87、95/100，全部600组题目处理均未超预算。

缓存结果：4,588次返回候选/分数/特征/排序严格相等；完整一轮热缓存均值0.7888→0.3244秒，2.4317倍；冷启动1.8480→2.1783秒，缓存略慢。上述均为检索阶段，不含模型和打包。

验证：29项测试通过；FinQA预测、评分和汇总复跑字节一致；AFAC600条结果复跑字节一致；默认full的100题证据ID和字符数与0928结果一致。输入和源码哈希、协议及原始计时存入docs/lab/generalization/，报告为docs/lab/generalization-report.md。下载时曾超时，恢复后文件完整校验通过，评测无样本排除。

限制：本轮API调用0，答案准确率为空。FinQA给定上下文检索不等于完整年报检索/数值推理；AFAC文档覆盖不等于标准证据召回。等待用户提供真实模型名称、地址、密钥文件路径和费用上限后再做模型评测。
