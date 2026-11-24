# 差分档案里的公开证据能跨领域复用吗？

上一轮在 CI 作业上用公开档案验证了最少披露。本轮在 **500 个 BART 换乘时刻表任务**上复验。结果是，任意不交反例组为 413 项证明最优，低于事前规定的 90%。在同一公开输入上做精确补检后，可证最优的比例达到 93.2%。余下 34 项都有一份相容时刻表，允许更短的证书。

理论上也得到一个边界。如果允许反例在不同实况下推翻不同条款，判断一个读数组是否始终不能省略，即便档案里只有二元值之间的先后关系，也已是 coNP 完全问题。如果待核验的组很小，则仍能有效地作精确判定。[上一轮](public-optimality.md) · [完整证明与查新](universal-witness-prior.md)

## 从单条反例扩展到多条

设 A 是旧档案，C 是与当前公开读数相容的实况集合。对每条新版上界，计算违反它的区域 B。若允许改动的组是 G，只保留组外。G 对所有可能真值都必读，当且仅当 C 的组外投影被全部违反区域的组外投影覆盖。这样，任何相容记录都能在组内改出一份错误报告，具体翻转的条款可随实况变化。单个违反区域仍能用上轮的最短路投影检查。[差分约束投影](https://arxiv.org/pdf/cs/0703073) · [盒覆盖先例](https://gki.informatik.uni-freiburg.de/papers/hoffmann-kupferschmid-ijcai2005.pdf)

这个更强条件的困难性来自一个保持原始结构的归约。把 3-CNF 的每个变量留在组外，每条子句在组内建两个端点 U、V，需要证实 V≤U。正文字加入 x≤U，负文字加入 V≤x。公布每个 U=1 后，每个组外布尔赋值都与公开输入相容。给定一个赋值，对应条款可以被翻转，恰好在子句为假时成立。存在一份只读组外就能证实整份报告的实况，恰好等价于公式可满足。删除重言子句后，每项公开读数都不能单独删掉。按隐藏组大小的参数复杂度及算法边界见完整证明，其中二元补问题分别按组大小和待证界数都是 W[1] 完全。[受限归约及参数证明](universal-witness-prior.md)

对整数域，固定一组组外数值后，每个隐藏位置都能用差分闭包计算最紧上下界。每条尚未被旧档案确定的界，只需下端点的下界和上端点的上界。给每个隐藏位置猜至多两个实际达到极值的组外位置，然后将所有新版要求合并成一份差分可行性问题。猜对时存在一份组外数据足以给出报告，所有猜法都失败时证明该组始终必读。设组大小为 `g`、候选上界数为 `r`，每组最多猜 `2 min(g,r)` 个位置。这给出对有界整数域的精确枚举，并允许在报告任意长的情况下核验单个位置。[可运行算法](universal_witness.py)

独立穷举在 100 个小网络上比对了 647 次分组判定，另核对了 100 份公式和 70 个多色团构造。要求反例必须翻转同一条的限制确有影响，合成例中没有一条能单独覆盖全部相容实况，允许两条交替时该组必读。100 份公式中有一次通用枚举达到节点预算，二元域的彩色团法和直接穷举仍给出一致结论。[核验程序](universal_witness_check.py)

## BART 换乘回放

使用官方 GTFS 第 72 版的三个服务日，按周历、停靠许可和父站重建同站换乘候选，最后按固定哈希选出 500 个互不重复的窗口。每个位置公开五分钟时间带，旧与新版报告按不同的秒级阈值分类同站不同路线的候车时间。这里核验的是计划时刻，报表阈值是模拟设置。[官方时刻表](https://www.bart.gov/schedules/developers/gtfs) · [冻结协议](https://github.com/shuimo233/research-notes/blob/afb91380b558bbbbc216a789f10184246a46fa07/articles/consent-audit/transit-optimality-protocol.md) · [冻结来源](transit-optimality-source.json)

| 指标 | 结果 |
| --- | ---: |
| 核对的新版标签 | 8,525 |
| 向审阅者公开全部时间戳 | 4,622 |
| 看见精确实况之前的最少固定披露 | 3,399 |
| 保管方看见精确实况后的最少披露 | 2,289 |
| 固定偏移反例组可公开证实最优 | 90 / 500 |
| 任意不交反例组可公开证实最优 | 413 / 500 |
| 精确补检后可公开证实最优 | 466 / 500 |
| 找到相容世界的更短证书 | 34 / 500 |

保管方选证据比最少固定名单少披露 32.66%。任意组方案的累计下界为 2,191，达到真值最优总量的 95.72%，但 82.6% 的作业覆盖率低于 90% 门槛，所以主复验未通过。探索性补检在剩下 87 项中排除了 53 项的更短替代证书，另外 34 项则找到可复核的反例。例如 2026 年 8 月 19 日 17:20 窗口的 19TH 站任务，真实时刻的最短证书有六项，而另一份符合现有公开材料的时刻表只需五项。[公开分组计数](transit-optimality-packing-results.json) · [补检及替代表](transit-optimality-exact.json)

独立程序重算了原始 GTFS 所用的时刻、每条新版标签、所有私有最短证书以及公开反例组的投影条件。对于 53 项用补检证明最优的任务，独立地排除了 457 个候选替代名单。对 34 份替代表及其更短证书也逐项复核。此实验衡量披露时刻数与可证明比例，未测量实际运行时列车或换乘表现。[独立验证](transit_optimality_check.py)

对上述 53 项再做探索性分析，让每个反例组可以随实况翻转不同条款，共找出并独立复核了 46 个单一条款无法证明的组。它们让其中 16 项重新获得了不交反例组的最优性证明。这里的增量来自多界判定本身，研究对象选自已被精确补检证实的任务。[补充实验与证书](transit-optimality-mixed.json)

## 复算

以下命令使用 Python 3.13。在本文目录运行，输出目录需尚未存在。公开核验阶段从已导出的时间带、旧报告、新标签和所披露值读取。

```text
python -I -B universal_witness_check.py
python -I -B universal_witness_inquiry.py public-optimality-example.json 1 2
python -I -B transit_optimality_export.py transit-optimality-fixtures.json.gz exported
python -I -B public_optimality_run.py exported/transit-optimality-packets.json.gz replayed
python -I -B transit_optimality_finish.py exported/transit-optimality-packets.json.gz replayed/public-optimality-ledger.jsonl.gz exact.json
python -I -B transit_optimality_check.py transit-optimality-fixtures.json.gz transit-optimality-source.json exported replayed exact.json
python -I -B transit_optimality_mixed.py exported/transit-optimality-packets.json.gz exact.json mixed.json
```

[冻结的公开包](transit-optimality-packets.json.gz)可以直接用于公开阶段。持有 SHA-256 匹配的原始 ZIP 时，可用 `python -I -B transit_optimality_prepare.py bart.zip normalized` 重新抽取样本，并向核验器传入 `--gtfs bart.zip` 核验选中的时刻。原网址是 BART 最新时刻表的永久链接，线上文件会更新。

一般盒覆盖的困难性、二元子句溯因按目标数的参数分类和差分约束投影均有先例。这轮的原创候选限于有界时刻表的公开证据合同、严格受限的归约，以及从隐藏组极值构成的可运行判定方法。另一个独立发现是，CI 中很少出现的公开信息缺口，在交通时刻表上可以反复重现。检索未确认有相同的完整构造，首创性仍待独立审阅。[原始文献对照](universal-witness-prior.md)
