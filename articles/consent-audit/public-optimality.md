# 只凭公开读数，能证明披露已经是最少吗？

[上一轮](slack-certificate.md)中，审阅者可以核验少量时间戳是否足以确定新版报告。证明这些时间戳已经最少时，独立程序仍使用完整记录。本轮去掉这一依赖。外部复核只读取旧档案、公开读数和新版标签，对**每一份与公开信息相容的真实记录**判断是否还有更短的替代证书。

在 430 项公开 CI 作业的模拟归档上，简短证明覆盖 418 项，通过事前门槛。再对其余项目做精确复核，共有 **429 项**能只凭公开信息证明最优。第 430 项的公开信息同时允许两个最优披露数不同的世界，因此这项不能从现有公开材料证实。[预登记](https://github.com/shuimo233/research-notes/blob/932326e29f9c324dbf74e3eb31343063ec657f35/articles/consent-audit/public-optimality-protocol.md)

## 把公开反例组变成顶点覆盖

分别用三个有界整数差分网络描述任务。A 是旧档案，C 是 A 加上当前已公开读数，所有 C 中的记录都满足新版报告。对报告中的一条界 `x[v]−x[u] ≤ b`，B 是 A 加上它的反面 `x[v]−x[u] ≥ b+1`。B 为空时，旧档案本身已能证明这条界。

对一个候选位置组 G，我们要确认：对每个 C 中的原始表，都能找到一份只在 G 内改动、落入 B 的替代表。等价地，C 保留 G 以外位置的投影包含于 B 在相同位置上的投影。这个包含关系可以从现成的差分矩阵闭包直接检查。闭包用 `D[i,j]` 表示两点差值的最紧上界，投影只需保留位置对应的子矩阵。一种直接延拓是对保留位置集合 K 取 `y[j]=min(x[i]+D_B[i,j] for i in K)`。它在 K 上恢复给定值，并满足差分约束。免费原点始终保留。[Miné 的闭包与精确遗忘](https://arxiv.org/pdf/cs/0703073)

因此，每个满足 `D_C[i,j] > D_B[i,j]` 的位置对都必须至少有一个端点落在 G 内。这些位置对是一张图，G 是它的顶点覆盖。证明文件只需要列出组内位置和要推翻的界。审阅者可以自己重算图，整个过程无需访问隐藏读数。

任何能从旧档案得到新版报告的替代证书都必须读 G 中至少一项。若它避开 G，对那个实况就存在与其所有读数一致却改变报告的替代表。互不重叠的 G 可以相加得到下界。找到的组数等于公开读数数目时，就证明了最优。选定每组要推翻的界后，用二元子句同时约束覆盖和互斥即可。选择各组对应哪条界时仍需搜索，实验每项最多尝试 5,000 个分支。[见证组与 2-SAT 先例](public-optimality-prior.md)

## 补上最后一项的差距

当公开读数只比下界多一项时，若有更短证书，它恰好要在每个不重叠的组里选一个位置。一个组内已知固定偏移的位置任选其一。对每种读数名单，检查是否**存在**同一份 C 中的真实记录，使这些读数对每个非空的违反区域 B 都足以排除。排除 B 等价于至少有一对已读位置的差超过该 B 的闭包上界，其中免费原点也可作端点。把各界所选的超界条件一起放回 C 检查可行性，即可给出精确结论。这个补检在预登记回放之后探索，只处理相差一次读取的情形。

本次 12 项补检中，11 项排除了所有更短的名单。余下一项来自 ruff 的作业。上一轮已用原始记录证实实际至少要披露 6 项。公开纤维却容许另一个时间表，它与所有 6 项已公开值一致，而且有一个可独立核验的 5 项替代证书。不交反例组还给出了 5 项下界，所以两个相容世界的最优披露数确实不同。[来源作业](https://github.com/astral-sh/ruff/actions/runs/45076871024/job/137376082350) · [替代时间表与新证书](public-optimality-exact.json)

## 回放与复核

| 从公开信息计算下界的方法 | 证明已达最优的作业 | 累计下界 |
| --- | ---: | ---: |
| 单个位置作反例组 | 0 / 430 | 436 |
| 固定偏移的位置组 | 278 / 430 | 2,643 |
| 任意互斥反例组 | 418 / 430 | 2,814 |
| 再做最后一项的精确补检 | 429 / 430 | 2,825 |

各任务共披露 2,826 个真实时刻。任意组方案证明了 97.21% 的作业，累计下界达到真值最优数的 99.58%，高于事前要求的 90% 和 95%。相对固定偏移组，多在 140 项作业上证实最优。独立的 Bellman–Ford 程序从原始约束核对所有证明，并独立复查最后一项的全部候选。它还在 200 个小整数网络中穷举了 5,516 组投影条件，另用 300 个小公式检测 2-SAT 求解器。原始 GitHub Actions 时间真实，旧报表与改版阈值来自模拟合同。[公开输入包](public-optimality-packets.json.gz) · [预登记计数](public-optimality-results.json) · [独立核验器](public_optimality_check.py)

在本文目录用 Python 3.13 运行。下面的命令只需要已经公开的数据。交互样例的公开读数足以确定报告，补检可以独立确认其最优性。

```text
python -I -B public_optimality_inquiry.py make public-optimality-example.json --complete > proof.json
python -I -B public_optimality_inquiry.py check public-optimality-example.json proof.json --complete
python -I -B public_optimality_run.py public-optimality-packets.json.gz reproduced
python -I -B public_optimality_exact.py public-optimality-packets.json.gz reproduced/public-optimality-ledger.jsonl.gz reproduced/exact.json
python -I -B public_optimality_check.py public-optimality-packets.json.gz reproduced reproduced/exact.json
```

需要核查公开输入是如何从之前实验证据导出时，可以运行 `python -I -B public_optimality_export.py slack-certificate-fixtures.json.gz slack-certificate-ledger.jsonl.gz rebuilt-packets.json.gz`。独立核验器的 `--export-sources` 接受这两个来源文件。向审阅者发放证书后，可以只用公开输入重算下界和最优性。用于公开验证的信息本身足以运行程序；本研究未测量这些输入对其他隐藏属性的泄露。

直接先例包括对所有相容配置成立的见证集、整数差分网络的精确投影，以及不相交顶点覆盖的 2-SAT 表达。本轮可独立检验的候选贡献是将它们用于**看不到实际记录时的最少披露证明**，再用公开的真实记录回放，区分可证最优和公开信息不足。检索未定位相同的完整构造，世界范围的首创性仍待独立核查。[原始文献对照](public-optimality-prior.md)
