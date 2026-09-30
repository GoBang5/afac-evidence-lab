# 2026-09-30 GitHub 发布

任务：按用户要求将 AFAC Evidence Lab 上传到已确认的 `GoBang5` 账号。

环境：本地 macOS、Git、GitHub CLI；以 `gh api user` 核实当前用户为 `GoBang5`。目标仓库 `GoBang5/afac-evidence-lab`，初始可见性为私有，发布分支为 `main`。

超参数：本次仅发布，未改动模型或检索超参数，未调用真实模型。此前真实模型与独立测试集验证的讨论尚未转化为已完成的实验。

发布内容：已有 Agent/Lab 代码、两道虚构题的演示数据、21项测试、固定协议与实验结果、运行说明、贡献边界及4条简历候选表述。原始数据、运行数据库、环境凭证不进入本次新增提交。

核验：发布前逐文件核对 `docs/lab/benchmark-protocol.json` 中的源码哈希，确认与既有已测试实现一致；检查待上传文件的凭证模式。上游来源保留为 `upstream`，目标仓库设为 `origin`，通过当前 GitHub CLI 登录凭证推送。

结果记录：目标地址为 https://github.com/GoBang5/afac-evidence-lab 。推送后由 GitHub API 比较 `main` 与本地提交哈希，并检查默认分支、仓库归属与可见性。
