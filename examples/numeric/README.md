# 虚构数值题

三题覆盖金额与百分比、带括号负数的现金流加总、第一行就是数据的收购表格。全部为构造样例，不属于 FinQA 分数。

在仓库根目录运行：

```bash
python3 -m evidence_lab run --data examples/numeric --out runs/numeric-offline
python3 -m evidence_lab run --data examples/numeric --out runs/numeric-model --judge-mode openai_compatible --use-local-api --max-requests 6
```

预期结果分别为 18.75（百万）、-312（百万）、1900/31300（比例）。仅第二条命令调用配置中的模型。
