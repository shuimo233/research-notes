# 按价复测的最坏费用与 Jackson 排程先例

核查日期为 2026-11-23。研究问题是用确定性顺序策略判断有限价格域上的请求函数是否全零。每次购买一个观测副本，同一价位可以复测。不同副本的费用已知，数据生成者在所有记录上共用有界的对抗翻转额度。比较指标是所有允许路径中已支付的最大总价。

**排序本身已有精确先例。** 一旦把每个价位的两项费用差算成 U 和 W，余下的问题就是单机最早交期优先排程。已有文献也分别给出了单位价带谎 OR 的精确次数，以及不同测试价格下建立最坏成本决策树的一般模型。本次未找到原文将这两者连起来，推得下述依赖历史、有限容量和分档价格的精确费用。可检验的增量是从带谎决策树导出 U、W 两项，以及证明同一个值既约束所有自适应策略，又能被一项具体策略达到。[Maharjan 与 Watson，观察 3](https://doi.org/10.4230/LIPIcs.FSTTCS.2022.26) · [Cicalese、Laber 与 Saettler，ICML 2014](https://proceedings.mlr.press/v32/cicalese14.html) · [Jackson，1955 年研究报告](https://ntrl.ntis.gov/NTRL/dashboard/searchResults/titleDetail/AD152722.xhtml) · [Lawler，单机最大完成费用](https://doi.org/10.1287/mnsc.19.5.544)

## 费用公式怎样进入一项经典排程

假设全零基线仍相容，剩余错误额度为 R。仅保留还相容的单点例外 i，令 qᵢ 为该例外的剩余额度加一。若没有这样的单点，区间历史的超可加损失已排除所有非空例外。以下设至少有一个。每个 i 必须有至少 qᵢ+R 份确切报价容量，这一必要条件来自基线与单点之间的二元检验。它也足以执行下述流程。[此前的顺序推导](sequential-precedents.md) · [Zhigljavsky，固定答错额度的分离条件](https://orca.cardiff.ac.uk/id/eprint/15201/1/Group%2520testing%2520lies.pdf)

令 Aᵢ(k) 为购买 i 最便宜 k 个独立、可互换副本的累计价格，Aᵢ(0)=0。非负边际价格按非降序使用。设

```text
Uᵢ = Aᵢ(qᵢ+R) − Aᵢ(qᵢ)
Wᵢ = Aᵢ(qᵢ) − Aᵢ(max(qᵢ−R,0)).
```

对顺序 π，所需优化的额外费用为

```text
maxᵢ [ Uᵢ − Σ(在 π 中晚于 i 的 j) Wⱼ ].
```

给排程中的作业 i 设处理时长 Wᵢ，设 K=maxᵢ Uᵢ，交期 dᵢ=K−Uᵢ。无空转时其完成时间 Cᵢ 是前缀处理时长之和。写 W 为所有 Wᵢ 之和，则 Cᵢ−dᵢ 与方括号内的量恰好相差常数 W−K。因此从小到大排列交期，也就是从大到小排列 U，即得最优顺序。有一个作业交期为零，最大迟延非负，因此最大迟延和 Jackson 报告标题中的最大延期在此映射下也相等。Lawler 的一般定理允许任意非降的作业完成费用，他的原稿还明确讨论最大延期或迟延的特例。[Jackson，原报告官方书目](https://ntrl.ntis.gov/NTRL/dashboard/searchResults/titleDetail/AD152722.xhtml) · [Lawler，伯克利原稿，第 3–6 页](https://www2.eecs.berkeley.edu/Pubs/TechRpts/1971/Archive/ERL-m-327.pdf)

## 排程定理之外还必须证明什么

- **所有查询树的下界。** 在任意策略的全零路径上，按各价位首次收满 qᵢ 个确切零的先后排列。选其中任一 i 作对手集中翻转的位置，在 i 已收 qᵢ−1 个零、即将得到第 qᵢ 个零前开始，只把 i 接下来的 R 个回答改成一，其他回答为零。若 i 没有被继续询问，基线与单点 i 会一直相容，故正确策略必须继续。比 i 早完成的价位已付至少 Aⱼ(qⱼ)，i 至少付 Aᵢ(qᵢ+R)。每个较晚的 j 仍须收满 max(qⱼ−R,0) 个确切零，才能在这条基线轨迹上排除单点 j。不精确报价可选用异于该单点的允许值，从而无法替代这些确切零。由此对每个 i 均得到“全零基准费用加方括号内差值”的下界。单位费用下，这是 Maharjan 与 Watson 最后一个坐标对手的延伸。异价时必须允许任一坐标作集中翻转的位置，只看最后一项会漏掉昂贵的中途复测。[Maharjan 与 Watson，第 26:3 页观察 3](https://doi.org/10.4230/LIPIcs.FSTTCS.2022.26)
- **一个顺序达到这个下界。** 给定 π，每个价位连续处理到其单点被排除，然后移到下一价位。若此前已在其他价位收到 s 个一，该价位还需 max(qᵢ−s,0) 个零。基线可实现的路径上，设 tᵢ 为在 i 收到的一的个数，Σtᵢ≤R。该顺序的费用由 Σᵢ Aᵢ(max(qᵢ−Σⱼ早于ᵢ tⱼ,0)+tᵢ) 上界。用相邻整数处线性插值后，Aᵢ 凸且非降，括号内也是凸函数，因此总和是凸函数。每个允许点都是单纯形顶点 0 和 R·eᵢ 的凸组合，故上界由某一顶点取得。零顶点给出全零基准费用，顶点 R·eᵢ 恰好给出基准加 Uᵢ 减去晚于 i 的 W 总和。最后一项的 U 非负，已覆盖零顶点。若策略在第 R+1 个阳性答复时停止，把末次答复改为零，已付款项不变，并可沿一个仍与基线相容的延长路径继续；因此该类提前停机轨迹也在同一上界内。R=0 直接按全零基准处理，无须作单纯形分解。
- **还要覆盖多点行为。** 历史按各候选的最少错数结算。独立的集合值历史使 d(S)−d(∅)≥Σᵢ∈S(d({i})−d(∅))。因此在基线存活时，若已经排除所有单点，也就排除了所有非空 S。这一步使上述零配额论证适用于完整行为类。它依赖观测模型，不能直接推广到给每个非空 S 任意指定误差余量。原文与导出的剩余额度模型见[顺序审计先例](sequential-precedents.md)。

最优费用等于 Σᵢ Aᵢ(qᵢ) 加上按 U 降序时的上述最大差值。若每个坐标内单价固定为 cᵢ，则 Uᵢ=R·cᵢ、Wᵢ=min(qᵢ,R)·cᵢ；R>0 时优先处理单价高者。分档菜单中的优先级取决于基准份额之后最多 R 份的追加总价。例如两价位均有 q=R=1，副本费用分别为 (2,100) 和 (5,6)。先处理前者的最坏费用是 102，反序是 107。两者全零都只花 7，以首份费用或这条实测路径无法解释最坏费用的区别。

## 带价查询、错误收费和随机检测的直接对照

| 原始研究 | 已给出的结果 | 与本题的关系 |
|---|---|---|
| [Kenyon 与 Yao，1990](https://doi.org/10.1142/S0129054190000023)；[Maharjan 与 Watson，2022](https://doi.org/10.4230/LIPIcs.FSTTCS.2022.26) | 总计有限次假答的布尔函数求值。后者给出单位价 AND 的精确最坏高度及适用于一般函数的动态规划。 | 对输入与输出取补即得单位价 OR。次数统一计价，原文的 n(E+1)+E 不能通过把 n 换成所有货币价格之和得到本题公式。 |
| [Charikar 等，Query Strategies for Priced Information](https://web.cs.ucla.edu/~sahai/work/web/2002%20Publications/J.CompSysSci2002.pdf) | 获取真实输入值需要付费，研究布尔函数及与已知该实例的最优证书相比的竞争比。 | 查询有不同价格早已建立。其目标和信息通道都与全局对抗错读预算下最大实付金额不同。 |
| [Cicalese、Laber 与 Saettler，2014](https://proceedings.mlr.press/v32/cicalese14.html) | 采用带价确定测试给对象分类，明确定义决策树最坏和期望测试费用，并给一般近似算法。 | 有限副本时，将对象展开为 (真实行为 S，剩余额度内的故障副本集合 F)，标签为 S 是否为空，恰能编码本问题。对一条确定性树路径，事后把路径上翻转的副本放进 F 就得到同一条路径。这个一般表示可能要枚举大量故障集合，原文没有据此化出 U/W 顺序。 |
| [Ahlswede 等，Searching with Lies under Error Cost Constraints](https://www.math.uni-bielefeld.de/ahlswede/homepage/public/221.pdf) | 按正确符号与报告符号之间的替换种类给谎言赋权，限制作答者可消耗的总权重。 | 费用发生在错误一方。本审计的购买费用对真、假回答都支付，总错读数另行限制。 |
| [Gkenosis 等，随机布尔函数求值](https://arxiv.org/abs/2111.08793)；[Tan 等，分布鲁棒 k-of-n 测试](https://arxiv.org/abs/2603.23705) | 前者研究随机输入下的带价读取，后者让各测试的失败概率在区间内变化，最小化最坏期望测试费用。 | 概率、平均费用与全局有限次任意位置的答错是不同假设，概率排序不能充当此处最坏轨迹的证明。 |
| [Jia 等，Noisy Outcome 的最优决策树](https://arxiv.org/abs/2312.15357) | 在含噪测试、包括重复测试可返回同一噪声结果的模型中研究近似求解。 | 持久错误不能靠购买同一传感器的多份副本保证排除。需要明确哪些副本各占用一个真实的错误单位。 |

## 一次错读时，分档价格可使顺序方案便宜近 m 倍

设 m 为非空的存活单点数，F 是固定批次的最优费用，V 是顺序树的最优最坏费用。仅在 V>0 时讨论比值。每一个单点 i 都可单独与空基线保持歧义，直到在 i 处花掉至少 Aᵢ(qᵢ+R)。因此 V 不小于其中的最大值，而 F 正是这些值之和，故 F≤mV。这个上界只用了“和不超过项数乘最大项”，有判别力的是它在一次错读的特定 OR 模型内仍可任意逼近。[带谎分离距离](https://orca.cardiff.ac.uk/id/eprint/15201/1/Group%2520testing%2520lies.pdf) · [单位价 OR 精确下界的单坐标对手](https://doi.org/10.4230/LIPIcs.FSTTCS.2022.26)

取空历史、f=R=1，每个价格可买三份，费用分别为 1、1、M，其中 M≥1。此时 qᵢ=2、Uᵢ=M、Wᵢ=1。固定批次在每个价格都必须预购昂贵第三份，总价 F=m(2+M)。顺序最坏总价 V=2m+M，只需为一个价格的第三份留出预算。固定 m 令 M 增大，比值趋于 m；允许 m 增长便没有独立于域大小的常数上界。固定的问题序列即使可以提前停机，最坏费用也无改善，因为其最坏停机前缀自身必须完成两类分离。顺序算法虽然预先确定价格优先级，实际购买的副本数和下一次被问的价格仍取决于回答。[固定序列早停的前缀证明](sequential-precedents.md)

若每个价格的所有副本恒价为 cᵢ，则 R≤1 和 qᵢ≥1 直接给出 F=Σcᵢ(qᵢ+R)≤2Σcᵢqᵢ≤2V。此常数在**允许有历史**时可逼近。令每个确切价格已有一次诚实的零回答，令各 cᵢ=1、f=1，则 qᵢ=R=1，F=2m、V=m+1。若要求**空历史**，qᵢ=2，强界为 F≤(3/2)V，等价位时 F/V=3m/(2m+1) 逼近该值。空历史恒价例的顺序次数直接由 Maharjan 与 Watson 的观察 3 得到。[Maharjan 与 Watson](https://doi.org/10.4230/LIPIcs.FSTTCS.2022.26)

“适应性差距”有成熟文献。2025 年 APPROX/RANDOM 论文对随机 k-of-n 函数求值给出一般测试价格下的精确最坏比值 2，并说明其单位价版本为 3/2。该比值比较的是**期望费用**，测试真实输入位并在结果已确定时停止。2022 年的随机布尔求值论文也给出其他函数类中随规模增长的差距。因此“大差距”“常数 2 或 3/2”都不宜单独主张新颖；上述分档反例的具体含义是在 OR、全局至多一次对抗翻转、按路径实付最坏费用下，m 个单点就能逼近 m 倍差距。本次核查未见上述条件和构造同时出现的既有原文。[Non-Adaptive Evaluation of k-of-n Functions，定理 1](https://doi.org/10.4230/LIPIcs.APPROX/RANDOM.2025.26) · [Adaptivity Gaps for the Stochastic Boolean Function Evaluation Problem](https://arxiv.org/abs/2208.03810)

## 查新口径与限制

检索覆盖 Dagstuhl、ICML/PMLR、JMLR、INFORMS、SIAM、Elsevier、美国国家技术报告馆、伯克利技术报告库及作者原稿。交叉关键词包括 *priced Boolean function evaluation, fault tolerant query complexity, non-uniform costs OR with lies, asymmetric remaining lies, minimax testing with fallible inspections, sequential diagnosis with imperfect tests, arbitrary error cost, box search with imperfect detection, decision trees worst testing cost, Jackson earliest due date, single machine maximum lateness, sequencing with delivery times*。Jackson 原报告以官方书目核对，排程定理用 Lawler 的完整原稿核实。未查实既有论文给出同一测试问题的价差 U、W 以及双方匹配的精确保证。这支持报告一项有明确前提的数学归约和特化算法，无法确认全球首创。
