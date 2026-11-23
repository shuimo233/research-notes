# 先例核查：有来源歧义时，如何选最便宜的固定测试面板

核查日期为 2026 年 11 月 23 日。本文讨论一次选定整套测试、按总价付费的面板。菜单既有可能受坏根影响的行为报告，也有保证正确的同源核验。每个可能世界的来源分区与坏根集合贯穿历史和未来，两世界的分区和坏根集合可以不同。

**最接近的直接先例是广义测试集合问题。** Douek-Pinkovich、Ben-Gal 和 Raviv 已经给出带价固定面板模型：完整答卷各自属于一个决策类，不同决策类的任一对答卷必须在所选测试上可分。他们甚至允许指定最少相异测试数 α。把本审计中所有可行完整答卷按决策类展开，取 α=1，得到同一个面板优化问题。如果同一完整答卷在两个类别下都可行，它给出空的差异集合，直接证明无解。这里可研究的差异是输入采用紧凑的来源和故障描述，可以据此按需构造带来源信息的约束。[《The generalized test collection problem》，第 2 节式 (1)–(2)、第 3 节命题 1](https://www.eng.tau.ac.il/~talraviv/Publications/GTCP_Sep2019.pdf) · [期刊版，TOP 2021](https://doi.org/10.1007/s11750-020-00554-1)

## 已有的测试、反例与选点算法

| 工作 | 原文结果 | 可直接采用之处 |
| --- | --- | --- |
| Moret 和 Shapiro，1985 | 求保持给定表全部区分能力的最低费用或最少数目的测试；比较精确搜索与启发式。 | 经典固定测试集基线。若只需输出类别，显式表应只对不同类别建立分离要求。[SIAM 原文](https://epubs.siam.org/doi/10.1137/0906067) |
| Douek-Pinkovich、Ben-Gal 和 Raviv，2021 | 跨类别答卷对需要至少 α 项不同结果，选测试的费用可不同。其 CRA 在显式候选差异集上删掉包含其他行的冗余行，并在行长等于 α 时强制选中行内测试。 | 目标和显式整数模型可以直接引用。CRA 属于预处理。该组后续随机测试集合论文则明确用懒约束生成，优化还涉及概率条件。[GTCP 原文，第 3 节](https://www.eng.tau.ac.il/~talraviv/Publications/GTCP_Sep2019.pdf) · [后续 EJOR 原文](https://www.sciencedirect.com/science/article/pii/S0377221721010997) |
| Chandrasekaran、Karp、Moreno-Centeno 和 Vempala，SODA 2011；Moreno-Centeno 和 Karp，2013 | 隐式命中集由验证器给出。候选解无法命中全族时，验证器返回漏掉的一个集合；仅对已知行精确优化，再反复验证，可求全局最优。2013 年论文还讨论可行解与下界的迭代。 | 每个对立世界见证产生一个差异集。已知行的最廉价解是全问题的下界；该解经精确验证可行时达到下界。原始问题以最少项数表述，上述下界论证同样适用于可加费用。SODA 将多项式时间验证器作为一般框架的假设。本审计中，故障上限作为输入时，得到分离反例本身可以是 NP 完全；外层正确性只要求验证器完备并最终返回。[SODA 原文](https://karthik.ise.illinois.edu/pubs/implicit-hitting-set.pdf) · [Operations Research 原文](https://pubsonline.informs.org/doi/10.1287/opre.1120.1139) |
| Cabasino、Lafortune 和 Seatzu，2013 | 用验证网捕捉违反可诊断性的行为，据此决定哪些变迁应增加可观察标签，再由整数规划求最小成本。 | “反例指导静态传感器部署”在故障诊断领域已有直接前例。原文处理离散事件系统的行为轨迹。[Automatica 原文，第 5 节](https://www.sciencedirect.com/science/article/abs/pii/S0005109813002665) |
| Shinohara 和 Namerikawa，2024 | 允许固定数量的测量受篡改，在可重构状态的约束下使部署成本最小，并给出一般情形的困难性及特定网络的算法。 | “坏传感器存在时仍选最廉价面板”本身也是已有目标。该文给定传感器和动力系统，本审计还要处理跨世界的来源重分组和可购买的可信身份查询。[Automatica 原文](https://www.sciencedirect.com/science/article/pii/S0005109823006210) |

## 一个反例能生成多强的条件

设候选面板允许两个相反世界给出完全相同的记录。固定两世界的真值、来源分区以及与见证相容的一组基础坏根。历史已经强制为坏的根必须包含在内。基础坏根以外，各世界的故障额度还剩 r₀、r₁。移除与基础坏根相连的行为报告和两世界本来就同答的报告。每个余下报告用左世界根 u 与右世界根 v 组成的边表示。两张分区对某个可信核验本就给出不同答案时，购买这项检查即可区分此世界对。故以下所有报告条件都以“未选择任何这样的检查”为前提。已有历史若含这类区分，世界对本应先被剔除。

**加强一条普通命中约束。** 选用剩余额度，在左、右侧各挑若干根，掩蔽所有关联边；尚未掩蔽的报告与可区分的可信检查构成一条有效的命中约束。用非负权衡量边并尽量多掩蔽，恰是 **matroid-constrained maximum vertex cover**。每个根是一个顶点，每个端点对的边权为对应探针权重之和，两侧根各构成有配额的一组，即分划拟阵。Huang 和 Sellier 的模型直接包含本题，且给出分划拟阵的参数化近似方案。任何合法扩充坏根集已经能产生有效约束，最大化掩蔽仅优化这一行的权重。不同的同权最优扩充可产生互不包含的约束；单行权重最小并不意味着整个算法需要最少轮数。原始见证坏根不能被换掉而不重新检查候选面板上的共同答卷。[Huang 和 Sellier，SWAT 2022](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.SWAT.2022.27)

**两侧联合计数。** 选中的报告先按二元组 (u,v) 去重。如有至多 r₀+r₁ 个不同端点对，可把其中至多 r₀ 个交给其左端覆盖，其余至多 r₁ 个交给其右端覆盖。因此若无可区分的可信检查，面板必须选中至少 r₀+r₁+1 个不同的残余端点对。在残余图为匹配时，这个条件充分：选一根最多掩盖一个端点对，同端点下的多个别名只计一次。一般图则可能拥有很多边却全由一个根控制，这个数量条件只给出必要性。若要求该条件对原始的固定真值和布局完整刻画，基础坏根应恰为历史强制坏根；另行固定额外坏根仅刻画这个坏根子族。[Jansen，约束二部图点覆盖的定义](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.STACS.2016.45)

**固定一侧后的精确计数。** 先取任意左侧可容许的额外坏根集 U，再剔除其关联报告。从余下已选报告中数右侧不同根的个数。若至多 r₁ 个，允许它们都坏就得到一个共同答卷。反过来，任何共同答卷给出一组左坏根 U，其余选中边的右端都属于不超过 r₁ 个右坏根。因此对于全部满足 |U|≤r₀ 的 U，同时要求“选了区分分区的可信核验，或选了至少 r₁+1 个不同的剩余右根”，就是固定世界对的精确条件。对称交换左右同样成立。面板优化时只取一个来自当前反例的左故障集合即可产生一行把当前面板排除的约束。这里应以历史强制的右坏根作右侧基础，避免把本可用于加强该行的右侧选择提前固定。

上述单侧公式是约束二部点覆盖的邻域表述：给定左侧覆盖部分后，未覆盖边的所有右端点都是强制项。把已购报告作为图的边选择变量，并将天然无误的身份核验作为附加析取项，是针对这个审计菜单的表达。未在核对的论文中找到带未知来源分区、既有历史和可信同源菜单的同式；公式从点覆盖条件立即推出。[Jansen，STACS 2016](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.STACS.2016.45)

## 纠错多覆盖与普通正子句的表达长度

对于一位真值、固定互异根、每根有一份报告且两侧故障额度同为 f 的特例，恰需选择 2f+1 个根。Laifenfeld 和 Trachtenberg 已经把可容忍 r 次错误的识别码归约为每对对象至少 2r+1 次的集合多覆盖；Fawzi、Tabuada 和 Diggavi 的命题 2 则明确按跨多次观测的传感器支持数计量。此处按独立根计数有直接理论依据。具有联合故障域时，机械地对别名或交叉边套用 2f+1 次计数会误判；上一节的匹配条件给出可以安全套用的场合。[Laifenfeld 和 Trachtenberg，IEEE Transactions on Information Theory 2008](https://ieeexplore.ieee.org/document/4608978/) · [Fawzi 等，命题 2](https://arxiv.org/pdf/1205.5073)

若 N≥2f+1，只保留原测试变量上“至少选一个”的普通反例行，任何有效的一行均至多排除一个大小为 2f 的候选面板。因为该行的补集至多有 2f 个元素，否则会误排一个本已充分的 2f+1 面板。排除所有大小为 2f 的配置需要至少 binom(N,2f) 行，逐个取其补集即可达到。这个下界针对普通正子句的显式表示，以及完全靠这种行排除候选的证明。若 f 固定，它随 N 多项式增长；只有随 N 选取相应的 f 时才有指数级族。单条基数约束或带辅助变量的 SAT 编码能压缩表示。Sinz 给出顺序计数器等通用编码；这里的计数证明是阈值布尔函数的基本性质，不支持通用求解时间下界。[Sinz，CP 2005](https://www.carstensinz.de/papers/CP-2005.pdf)

## 可复用实现与最优性检查

- 只有普通命中行时，PySAT 的 `Hitman` 在 `htype='sorted'` 下支持加权最小命中集。对当前解调用 `get()`，反例用 `hit(S, weights=...)` 增加；同一测试的权重必须保持一致。`enumerate()` 会自动屏蔽已输出解，和按真实反例添加约束的循环语义不同。[PySAT Hitman 文档](https://pysathq.github.io/docs/html/api/examples/hitman.html)
- 面板含条件基数行时，可直接以 RC2 求解加权部分 MaxSAT。每项付费选择 y 对应带其正整数价格的软子句 ¬y。用硬子句把分组指示变量连到相应报告的逻辑“或”，否则求解器可能把未购报告的分组当成已选。对报告分组的至少 K 约束可用 `CardEnc.atleast`；每条编码子句与“已选至少一项可区分的可信检查”取析取，即实现条件性。辅助变量需统一分配编号，免费测试可作为免费变量处理。最终成本应由选中的原菜单项独立求和。[PySAT RC2](https://pysathq.github.io/docs/html/api/examples/rc2.html) · [PySAT 基数编码](https://pysathq.github.io/docs/html/api/card.html)
- 若已有 OR-Tools，CP-SAT 支持整数变量和整数约束。报告成本最小值前核对求解状态为 `OPTIMAL`，且未以非零最优间隙提前结束。`FEASIBLE` 只提供可行上界。SciPy 的 `milp` 是另一基线，但目标、界和约束系数会转为双精度，对数值容差和大整数权重应分别处理。[Google CP-SAT 官方文档](https://developers.google.com/optimization/cp/cp_solver) · [SciPy milp 官方文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)
- 两类验证回答不同问题：用分区故障模型检查最终面板不存在相反世界，给出可行性；对生成的必要约束精确求最小成本，给出下界。两者成本相合才能证明全局最优。若另需第三方无需信任求解器就检查下界，须导出可重验的优化证明，或由独立方法重新求这些有限约束的最优值。[Moreno-Centeno 和 Karp，2013](https://pubsonline.informs.org/doi/10.1287/opre.1120.1139)

## 检索范围

第一轮检索了 SIAM、INFORMS、期刊原文及作者稿。关键词包括 `minimum cost fixed test set`、`generalized test collection problem different states`、`minimum sensor selection diagnosability verifier integer linear programming`、`implicit hitting set missed set oracle`、`resilient sensor placement secure state estimation`、`partition matroid maximum weighted vertex cover bipartite`。后续定向查了 `robust identifying codes 2r+1 multicover`、`constrained bipartite vertex cover separate budgets neighborhoods`、`test cover correlated failures fault domains sensor group shared risk`、`CNF cardinality constraints without auxiliary variables Sinz` 及求解器官方 API。显式固定面板、隐式命中集循环、最重掩蔽、独立根纠错阈值和通用 SAT 编码分别已有直接先例；本次未定位把两侧条件计数、可信同源核验和历史共用坏根结合到同一个面板验证器的已发表实现。此结论限于所查来源。
