# 多个温差判断，怎样共用一张最省的耐错清单？

要让一组判断都能抵御一次来源错答，可以逐项购买各自最便宜的来源，再合并付费。这会漏掉一类跨目标的合包机会。NOAA 气温和 BART 计划时刻的回放中，即使允许逐项方案在所有同价最优清单中协同选择，联合采购仍将总费用从 **1,647 降到 1,506，下降 8.56%**。费用和来源库存按预登记规则模拟。 [数据核验](interval-fault-joint-source-verification.json) · [主协议](https://github.com/shuimo233/research-notes/blob/fe4fb3707c0d040fe928c56da2ef19973e4ecd04/articles/consent-audit/interval-fault-joint-source-protocol.md)

## 所有异结论世界对，可以缩减为相邻边界

把每个世界的全部目标标签合成一个向量。方案必须让所有目标向量不同的世界，在所购来源中至少有 $2r+1$ 份来源答复不同，才能抵御 $r$ 份任意错误来源。一个来源可以给多项读数，比较时应把它的完整答复计为一个位置。 [来源级耐错条件](interval-fault-source-bundle.md)

若能找到一个世界顺序，使每个来源相同的答复始终连成一段，那么只需保证**相邻且目标向量不同**的世界对达到要求。必要性直接成立。充分性来自任意两个异标签世界之间至少存在一个相邻异标签边界。某来源若能区分该边界两侧，就一定能区分区间的两个端点，否则它的同一答复将跳过中间那次变化。这个论证还适用于目标为其他有限标签的情形。

单错报差值图提供一种可构造的顺序。每份来源的比较图连通，并且含一个共同锚点时，可以由它的整份答复求出各涉及顶点相对于锚点的差值。把切点顺序从锚点的路径位置之后开始读取。每项到锚点的差值沿新顺序至多改变一次，因此完整答复一旦改变就不会再恢复成此前的向量。允许两点已附在同一条路径位置，也允许可信区间删除部分切点。来源可共享的是锚点的路径位置，使用同一顶点是一个直接充分条件。程序也接受调用方给出的其他线序，只要逐个来源核对了相同答复的连续性。 [切点算法](interval-fault-cut.md) · [连续一性质与顺序先例](interval-fault-joint-source-prior.md)

无共同锚点时，原切点顺序的相邻性可能漏检。四点零路径加闭合读数 1，目标为闭合边与中间路径边是否达到 1。给三个来源重复核实首边，另给三个来源重复核实末边。每一对循环相邻的切点都在三份来源上有不同答复。然而删闭合边的世界与删中间边的世界完全同答，结论又相反。独立检查器确认这一反例，程序也会拒绝这个不满足连续性的输入顺序。 [反例核验](interval-fault-joint-source-verification.json)

## 两项比较和三项比较之间有复杂度分界

一个共享锚点的连通来源若含 $k$ 条比较，最多涉及 $k+1$ 个不同顶点位置。锚点固定在新线序边缘，所以最多分隔 $k$ 个需求边界。每个来源至多两项比较时，把它视为连接至多两个需求边界的带价边。全买后，边界 $v$ 最多可少买 ${\deg(v)-(2r+1)}$ 条关联边。按这些上限最大化省下的价格，恰为带单位边容量的最大权 $b$-匹配。单边界来源可接到虚拟私有端点，重复报价继续对应不同来源。匹配互补公式已有直接先例。实现为每个边界建立容量副本，调用标准的整数最大权匹配。 [Khan 等，第 III-B 节](https://www.cs.purdue.edu/homes/apothen/Papers/IPDPS2018.pdf) · [匹配实现所用工具](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.matching.max_weight_matching.html) · [代码](interval_fault_joint_source.py)

允许三项比较，即使所有来源仍以同一顶点作锚、同价且仅允许一次来源错答，问题也已是 **APX-hard**。从最大度三图的最小顶点覆盖出发，把原图每条边做成一个待覆盖的边界，每个图顶点是至多覆盖三个边界的一份来源。

具体实现用一条零差值路径和闭合读数 1 构成单错报环。按切点 $1,\ldots,M,0$ 排序，选路径切点 $2,\ldots,M-1$ 的边作目标，统一问差值是否达到 1。切点 0、1、$M$ 都是全假，其余各自把一项目标变成真。第 $j$ 个需求边界由锚点 0 到顶点 $j$ 的比较实现，$1\le j<M$。这些比较都经过顶点 0，所有目标边都避开顶点 0。对于每个原图边界 $u$，加一个私有保护边界 $g$。再增加两份覆盖 $\{u,g\}$ 的来源及一份只覆盖 $g$ 的来源。保护边界要三重覆盖，三份全被强制购买。每个旧边界因此只剩一份需要由原顶点来源补足。新最优值等于原顶点覆盖最优值加上原图边数的三倍，且至多为原最优值的十倍。移除强制包就得到原问题的解，超出最优值的差额完全保留。60 个冻结的小图与 3,920 个顶点子集复算一致。 [Alimonti–Kann 原论文，定理 3.1](https://doi.org/10.1016/S0304-3975(98)00158-3) · [结构边界和查新](interval-fault-joint-source-prior.md)

## 回放和并列对照

实验使用原来冻结的真实温度与计划时刻。对每份档案遍历锚点，只审查不接该锚点的原报告，查询均为从锚点出发的一项或两项差值。档案错报、来源容量和采购费用均按预登记规则模拟。多个锚点配置可能来自同一份原档案，因此同时记录去重档案数。 [气温数据](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily) · [BART GTFS](https://www.bart.gov/schedules/developers/gtfs)

| 两项或更多目标歧义，且可联合定案 | NOAA | BART | 合计 |
| --- | ---: | ---: | ---: |
| 不同原档案 | 24 | 13 | 37 |
| 锚点配置 | 42 | 37 | 79 |
| 固定顺序选单项最优后去重 | 742 | 922 | 1,664 |
| 所有同价单项最优中找最低去重价 | 742 | 905 | 1,647 |
| 联合精确购买 | 695 | 811 | 1,506 |

第一种逐项对照的降幅为 9.50%。补充对照穷举所有单项目标的最优清单，再以总费用最低的方式去重。这个更强的基线使其中四个配置更便宜，仍有 **27 个配置**严格受益于联合购买，累计节省 8.56%。两种对照都达到事前费用和不同档案数门槛。这里的联合目标允许为某个单项接受非最低单项价格，只要共享后的总方案更便宜。五点环的合成实例把这个区别具体化。每项价格最低为 12，最优的单项合并总价为 18，联合采购低至 15。原补充协议中的四点候选在试验前更正，因为它漏掉了环末端的一对异标签世界。 [最有利的逐项对照及构造](https://github.com/shuimo233/research-notes/blob/62aa9f84f243720bcce474d0cd4ced7e14032923/articles/consent-audit/interval-fault-joint-source-ties-protocol.md) · [详细数据](interval-fault-joint-source-verification.json)

独立程序不用相邻化假设，从原始档案重建世界，按**所有异标签世界对**复算费用，核验了 6,543 个锚点配置。对 623 个可判的歧义配置重放了 25,554 份答复，覆盖正常回复、被其他可行向量替换和被任意非法向量替换的等价类。其余 42 个歧义配置都有可核对的共同回复反例。200 个随机小覆盖实例另与匹配解交叉核对。 [汇总](interval-fault-joint-source-results.json) · [独立复算](interval_fault_joint_source_check.py)

## 查新与使用

传统耐错分离覆盖、连续一顺序和带权 $b$-匹配均有先例。本轮可定位的原创候选是：在同一单错报差值合同中，多目标、共锚来源和禁止直查目标使两项比较可精确匹配求解，而三项比较已经 APX-hard。当前有限查新未定位到相同复合结果，发表优先权尚待进一步审查。 [先例原文对照](interval-fault-joint-source-prior.md)

使用 Python 3.11 或更新版本，回放锁定 NetworkX 3.6.1。从文章目录运行以下命令。

```bash
python -m pip install networkx==3.6.1
python -B interval_fault_joint_source_run.py station-tmax-through-2025.csv.gz transit-optimality-fixtures.json.gz replay
python -B interval_fault_joint_source_check.py station-tmax-through-2025.csv.gz transit-optimality-fixtures.json.gz replay
```

对新档案先由切点编译器求世界并用 `after_anchor` 排序。把每个来源在各世界上的整个答复写成 `Offer`，将目标向量和报价传给 `joint_plan`。返回的 `selected` 指定固定采购，`witness` 给出预算内不能保证时的两个世界与共同答复。获得实际回复后，将其交给 `possible_labels` 解码目标向量。
