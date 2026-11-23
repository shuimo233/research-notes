# 双向路径的事实依赖：两个单调 DNF 之差

2026 年 11 月 23 日查证。**保留多少个原始事实位才能重放每种删边结果，是布尔函数本质变量的问题。** 两个余因子不同的变量必须保留，余因子相同的变量可以消去。下述路径筛选式成立。它把这个通用判据专门写成对两份已显式列出的路径反链的运算，还能为每个保留位给出只相差该位的两种事实状态。其数学材料有很近的先例，包括布尔函数的规范表示、偏布尔导数、反链收缩和序凸布尔函数的约简 DNF。研究归属宜限于这一表示下的推导、实现和实际数据结果。[Bryant 的原始 BDD 论文](https://www.cs.cmu.edu/~bryant/pubdir/ieeetc86.pdf) · [Cornuéjols，反链收缩 §1.4](https://www.sfu.ca/~mdevos/notes/pack-cover/Cornuejols.pdf) · [Timoshkin，序凸布尔函数](https://doi.org/10.1007/s10559-019-00109-8)

## 可独立核算的公式

令 $U$ 是可独立保留或删除的有限事实集。$\mathcal P,\mathcal Q$ 各是按包含关系去重、去除真超集后的事实集合族。对事实状态 $A\subseteq U$，输出 $F(A)=1$ 当且仅当某个 $P\in\mathcal P$ 包含在 $A$ 中，且没有 $Q\in\mathcal Q$ 包含在 $A$ 中。目标是在**所有** $A$ 上重放这个输出。定义

$$
\mathcal L=\{P\in\mathcal P:\ \nexists Q\in\mathcal Q,\ Q\subseteq P\},\qquad
\mathcal R(P)=\min_{\subseteq}\{Q\setminus P:Q\in\mathcal Q\}\quad(P\in\mathcal L).
$$

对每个可行 $P$，$\mathcal R(P)$ 都不含空集。令 $E_+$ 表示有时添加单个事实会令输出从 0 升到 1 的变量，$E_-$ 表示有时添加它会令输出从 1 降到 0 的变量。那么

$$
E_+=\bigcup_{P\in\mathcal L}P,\qquad
E_-=\bigcup_{P\in\mathcal L}\ \bigcup_{T\in\mathcal R(P)}T.
$$

- **上升见证。** 若 $v\in P\in\mathcal L$，$P$ 是真点；$P\setminus\{v\}$ 缺少完整正项，故为假点。反之，任何添加 $v$ 后变真的边必补全某个含 $v$ 的正项。该正项不含阻断项，因为新状态为真。
- **下降见证。** 若 $v\in T\in\mathcal R(P)$，令 $A=P\cup(T\setminus\{v\})$。它包含正项。若有阻断项已被满足，其相对 $P$ 的剩余集会是 $T$ 的真子集，与极小性矛盾。添加 $v$ 后满足产生 $T$ 的阻断项，输出从 1 变 0。反之，若 $A$ 真而 $A\cup\{v\}$ 假，取 $A$ 内任一正项 $P$。新状态必须包含某个阻断项 $Q$。在包含于 $Q\setminus P$ 的所有阻断剩余集中选取极小者 $T$。若 $v\notin T$，产生该 $T$ 的阻断项已包含于 $A$，矛盾。
- **最小保留集。** 任何一个上述见证都迫使逐坐标保留方案包含相应变量。反之，若两个状态在 $E_+\cup E_-$ 相同，逐位修改其它坐标的整条路径上，输出始终不变。因此它是唯一的按包含关系最小的原始坐标集，也有最少的坐标数。这里假设保留物必须是原始事实位。如果可以先编码整个状态再存任意函数，仅用于一个固定布尔输出时，存输出的一位就足够。

不存在以某个方向为先验的单调性。取 $\mathcal P=\{\{x\},\{a\}\}$、$\mathcal Q=\{\{x,b\}\}$，添加 $x$ 在状态 $\varnothing$ 上使结果上升，在状态 $\{a,b\}$ 上使结果下降。也不能直接取所有剩余阻断项的并。取 $\mathcal P=\{\{a\}\}$、$\mathcal Q=\{\{a,u\},\{u,v\}\}$，相对 $\{a\}$ 的剩余项是 $\{u\}$ 与 $\{u,v\}$，后者被吸收，$v$ 不影响任何输出。在独立的四变量真值表校验中，四变量的 168 种反链两两配对，共 28,224 个函数表示；逐一比较超立方体上所有相邻状态，得到的上升集、下降集都与公式吻合。检验包含空族、含空项和常函数。

## 与已有理论的直接关系

| 已有工作 | 与本式的关系 |
| --- | --- |
| [Bryant，Graph-Based Algorithms for Boolean Function Manipulation](https://www.cs.cmu.edu/~bryant/pubdir/ieeetc86.pdf)；[Quine，The Problem of Simplifying Truth Functions](https://doi.org/10.1080/00029890.1952.11988183) | 相同两个分支的布尔判定可以删除。若有真值表、规范 BDD 或全部素蕴含项，均可求出函数的本质变量，完整规范化还有可能产生很大的中间表示。给某个变量的正负两种见证，等价于分别检查其两个余因子之间的有向差集是否为空。 |
| [Cornuéjols，Combinatorial Optimization: Packing and Covering，§1.4](https://www.sfu.ca/~mdevos/notes/pack-cover/Cornuejols.pdf)；[Marichal，Structure Functions and Minimal Path Sets](https://arxiv.org/abs/1401.0803) | 对集合反链收缩变量，正是从所有边中删去该变量再取包含极小者，多个变量可以依次收缩。因此 $\mathcal R(P)$ 就是固定 $P$ 全为真的阻断反链收缩。一个单调函数的正最小项刻画其结构；每个最小项上的任一变量都可通过删去它得到单坐标见证。这里的反链收缩作用于路径的**事实集合**，与把原 WordNet 图的顶点或边进行图收缩的操作含义不同。 |
| [Timoshkin，An Algorithm for Constructing Reduced DNFs of Order-Convex Boolean Functions，2019](https://link.springer.com/article/10.1007/s10559-019-00109-8) | 当前函数的真点在包含序上序凸：若 $A\subseteq B\subseteq C$ 且两端为真，$A$ 提供正项、$C$ 保证没有阻断，故 $B$ 为真。作者已研究**同类函数**，从理想和余理想构建约简 DNF。已核实出版社摘要、书目信息；其全文在本次检索中未能核对，因此无法断言作者已明列、或未明列上述两个变量并集公式。 |
| [Kvassay、Levashenko、Zaitseva，Analysis of Minimal Cut and Path Sets Based on Direct Partial Boolean Derivatives](https://journals.sagepub.com/doi/10.1177/1748006X15598722)；[非相干故障树的素蕴含项计算](https://www.sciencedirect.com/science/article/pii/S0951832097000343) | 可靠性文献已用有向偏布尔导数刻画“改变一个部件会使系统结果发生什么变化”，并将其与最小路集、最小割集、非相干系统中的正负条件联系。此处取是否存在某个翻转状态，不能用按状态分布平均后的一个有符号重要度代替；上升与下降在平均时可能抵销。$\mathcal Q$ 是另一方向的充分路径族，通常并非 $\mathcal P$ 的割集或其超图对偶。 |
| [Amsterdamer、Deutch、Tannen，On the Limitations of Provenance for Queries With Difference](https://arxiv.org/abs/1105.2255)；[Lee 等，Efficiently Computing Provenance Graphs for Queries with Negation](https://arxiv.org/abs/1701.05699)；[Meliou 等，Causality and Responsibility for Query Answers and Non-Answers](https://arxiv.org/abs/1009.2021) | 差查询输出依赖一侧存在且另一侧不存在；带否定的数据库溯源和在删除一组元组后再检验单个元组的反事实影响也已有系统研究。这里明确限定布尔集合语义、固定查询和对全部事实子集的输出保持。数据库的非单调因果定义、给定实例的一条推导或带重数的溯源语义各自有额外约定。 |

还可以从素蕴含项直接看出这项结果的已有数学基础。把合取项看成区间 $[L,H]=\{A:L\subseteq A\subseteq H\}$。对非空的序凸真域，每个兼容的“极小真点 $L$、极大真点 $H$”都给出一个极大的全真区间，反过来每个这样的极大区间都有这类端点。这是因为其下端或上端一旦还能向外扩至真点，序凸性就保证所得更大区间仍全真。故其素蕴含项的正文字来自 $L$，负文字来自 $U\setminus H$。若两个边界已知，上升变量直接取所有极小真点的并，下降变量取所有极大真点之补的并。本文的剩余阻断式采用另一份输入表示，可直接得到同样的带符号依赖，不必生成全部极大真点或全部素蕴含项。[同类函数的约简 DNF 研究](https://doi.org/10.1007/s10559-019-00109-8) · [布尔最小化的原始工作](https://doi.org/10.1080/00029890.1952.11988183)

## 对路径审计的适用范围

若输入已经列出两侧全部最小支持，朴素实现只需对每个正项检查阻断，对剩余阻断逐对作包含比较。以每个集合用 $|U|$ 位数组存储为例，共需 $O(|\mathcal P|\,|\mathcal Q|^2\,|U|+|\mathcal P|\,|\mathcal Q|\,|U|+|\mathcal P|\,|U|)$ 次基本位检查；不同行及相同剩余集可去重。这个界的输入是**显式列表**。仅提供原图或一个压缩图时，最小路径条数本身可能很大，式子不提供按原图大小的同一复杂度。若只保留一条抽样路径、把同一事实的多个别名误作独立变量、限制一次只能删少量边，或允许回退模型本身随删边状态而改变，原有证明的输入或量词随之改变。若两侧同判时默认输出正向，则正向输出条件成为 $\neg(Y\land\neg X)$。应先交换两份路径族，再对结果整体取负；这个最后的取负交换上升与下降见证。若任务输出还须区分无证据、双向证据等多个状态，应对各输出位分别推导需要保留的坐标。

核查覆盖出版社、作者论文和数据库溯源、布尔最小化、组合优化、可靠性理论原文。检索词包括 “difference of two monotone DNFs essential variables positive negative influence”、“order-convex Boolean functions reduced DNF ideal coideal”、“monotone Boolean function support minimal path sets”、“clutter contraction inclusion-wise minimal members”、“non-coherent fault tree direct partial Boolean derivatives prime implicants” 和 “provenance with difference tuple contingencies deletion”。没有核实到以两份显式单调路径反链为输入、按上述剩余阻断并集写出的原样公式。已有理论足以导出它；在序凸文献仍有全文缺口时，更不宜把它列为首个一般性布尔依赖定理。
