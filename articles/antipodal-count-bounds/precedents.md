# 互补行对、四行聚合与重复计数的先例

核查日期为 2026-11-22。本文考察二元预测表，含 `h` 条行约束、`m` 种探针，每种有整数重复数，行的错配额度可以不同。查核的优先权问题是能否为每个计数求出**一次、至多四条原行、不结合变量盒、最后才整数取整**所能给的最强单坐标界，以及如何返回可复核的原行。

**两个数学成分都有直接先例。** Hufsky 等人 2011 年的引理 2 已给出两行相同位置上的总偏离上限。Arratia 与 DeSalvo 2011 年的定理 3、命题 3–4 已将符号矩阵最小线性依赖中至多四项的绝对系数分类为 `11` 与 `1111`。这两处分别直接解释了两行界和四行完备性的结构。下面给出它们与当前算法的逐项映射。本次查核可辨识的工程贡献是将这些结论用于异质预算的压缩计数表，以行对和的字典为每个方向返回界、预算和原行，再恢复共同记录。本次未核实工业求解器或全部专用求解器是否已有相同实现。[Hufsky 等，原文引理 1–2](https://doi.org/10.1186/1471-2105-12-106) · [Arratia 与 DeSalvo，原文 PDF，第 10、13–14 页](https://arxiv.org/pdf/1105.2834)

## 两行界在 Closest String 中已有直接来源

设行 `s` 在计数 `z` 的错配总数为 `D_s(z)`。在第 `j` 块，若行预测 0，其错配为 `z_j`，若预测 1，其错配为 `n_j-z_j`。对任意两行 `s,t`，令 `E` 为预测相同的块集合。不同块贡献固定值，相同块贡献两倍错配。因此二元情形有恒等式

```text
D_s(z) + D_t(z) = Σ_{j∉E} n_j + 2 Σ_{j∈E} e_{sj}(z).
```

当 `E={j}` 时，`e_{sj}(z)≤⌊(r_s+r_t-Σ_{k≠j}n_k)/2⌋`。Hufsky 等的引理 2 在同半径 `r` 时对**所有**相同位置给出 `r-⌈d_H(s,t)/2⌉` 的总预算。引理 1 和随后的算法覆盖预算为零、两个方向固定同一位置产生冲突、逐行剩余额度，以及已定位置引发的进一步缩减。将相同位置合成一个有重数的块，立刻得到本轮同半径单坐标公式。使用不同 `r_s,r_t` 的一般式直接来自上述恒等式。Ma 与 Sun 的 Neighbor String 已以逐行距离阈值为输入。Rohwedder 与 Węgrzycki 的式 `2`–`3` 也明确比较二元 Closest String 和非均匀版本。[Hufsky 等，预处理与 Cascading](https://doi.org/10.1186/1471-2105-12-106) · [Ma 与 Sun，SIAM J. Comput. 2009](https://doi.org/10.1137/080739069) · [Rohwedder 与 Węgrzycki，ITCS 2025，§2](https://doi.org/10.4230/LIPIcs.ITCS.2025.83)

整数规划的映射也很直接。每行的仿射错配不等式移去常数后具有符号法向。给两行各取 `1/2` 倍再相加，所有干扰坐标消失，目标系数为 `+1` 或 `-1`，向下取整得到上述界。Chvátal 的行组合与取整规则直接准许这个推导。Achterberg 等已研究通过多行预处理收紧边界，并用哈希加速平行行检测。其平行行索引处理的是全部系数成比例的场合。此处另以目标坐标为例外检索。[Chvátal，Discrete Mathematics 1973](https://doi.org/10.1016/0012-365X(73)90167-2) · [Achterberg 等，Multi-Row Presolve Reductions，§3–4](https://orsj.org/ramp/wp-content/uploads/sites/9/2021/03/paper2014_4-4.pdf)

## 三行和四行的权重分类已有直接定理

把行记作 `a_i z≤b_i`。固定方向 `j` 和支持集 `I`，删去 `j` 列得到矩阵 `M`。消去所有干扰列的非负乘子形成锥 `K={λ≥0:Mᵀλ=0}`。对非零极射线，只取正支撑的 `k` 行，所得干扰矩阵的秩恰为 `k-1`。否则可沿第二个核方向作足够小的正负扰动，破坏极性。矩阵系数为整数，极射线可化成互素的正整数权。非负核的任意向量可分成这种极射线，且分量的支撑均在原支撑内。[Rockafellar，The Elementary Vectors of a Subspace of Rⁿ，定理 1](https://sites.math.washington.edu/~rtr/papers/rtr020-ElemVectors.pdf) · [Müller 与 Regensburger，定理 3](https://arxiv.org/abs/1512.00267)

将该原始权向量排序得 `λ`。干扰列都属于与 `λ` 正交的符号列，已张成 `k-1` 维。即使加入全部此类符号列，秩也仍为 `k-1`。这正满足 Arratia 与 DeSalvo 的定理 3 对 *novel partition* 的判据。命题 3 排除三项，命题 4 将四项限于 `1,1,1,1`。两项只能 `1,1`。此应用允许任意多干扰列，矩阵无需为方阵，原文所用概率模型亦无需成立。若根本没有干扰列，单行已给出纯轴界，单列输入须单独覆盖。五项 `2,1,1,1,1` 及六项的进一步分类也见同一原文。[Arratia 与 DeSalvo，定理 3、命题 3–6](https://arxiv.org/pdf/1105.2834)

从分类到带右端的最优性还需一步。令每条极射线的目标系数为 `c`，右端为 `b`。要求实的非负零法向组合都满足 `b≥0`。在所给支撑内，设所有 `c>0` 的极射线中最小 `b/c` 为 `u`。每个负方向极射线可与达到 `u` 的正方向极射线相消，故其右端也满足 `b≥uc`。零方向由假设给出同样不等式。任意组合均满足 `b≥uc`，正方向最强实界由单条极射线实现，最终取整保持顺序。负方向可翻转坐标。故至多四条原行的最强轴界由行对或等权四行达到。这是上述分类和非负组合性质的推论。存在负右端零法向证书时应先作为实矛盾处理。若借用变量界、在聚合中途取整或迭代切割，所得推理系统更强，不在定理的完备范围内。[Arratia 与 DeSalvo](https://arxiv.org/pdf/1105.2834) · [Rockafellar](https://sites.math.washington.edu/~rtr/papers/rtr020-ElemVectors.pdf) · [Chvátal](https://doi.org/10.1016/0012-365X(73)90167-2)

四面体的标准四个尾符号为 `+++`、`+--`、`-+-`、`--+`。它们逐列相消，任意两个都不能逐列相消。给四行添同号目标坐标即可分开四行和两行。这三个干扰坐标的符号矩阵也出现在 Arratia 与 DeSalvo 的 Example 1 中，允许原文的行、列置换、列翻号与上述写法互换。[Arratia 与 DeSalvo，Example 1 与 Proposition 4](https://arxiv.org/pdf/1105.2834)

## 索引、残余问题和复杂度

- **两行索引。** 取一行的按位补码，逐一翻转目标位，枚举至多 `m` 个字典键。对 `h` 条行共有 `O(hm)` 次查询。重复签名按最紧预算及一条原行编号聚合。单错配字典查询属于成熟字符串算法问题。[Chan 与 Lewenstein，Fast String Dictionary Lookup with One Error](https://tmc.web.engr.illinois.edu/one_err_cpm.pdf)
- **四行索引。** 把两个符号法向相加，取值为 `-2,0,2`，可以两个位掩码表示。在每一目标位找余列恰好相反的另一行对。区分两个行对在目标位的和，每个完整键只需保留最小右端及行号。两侧右端相加、按实际非零轴系数归一化。共 `O(mh^2)` 次键查询。同一行参与两侧时仍是至多四条行的合法非负组合。折半配对寻找互补和是既有算法技巧。尚未在所核原文中找到同时针对压缩汉明行、异质右端、原行证据及全部四行强轴界的相同实现。[Horowitz 与 Sahni，Computing Partitions with Applications to the Knapsack Problem](https://www.cise.ufl.edu/~sahni/papers/computingPartitions.pdf) · [Achterberg 等，多行预处理](https://orsj.org/ramp/wp-content/uploads/sites/9/2021/03/paper2014_4-4.pdf)
- **成本口径。** 上述为查表次数。掩码横跨多个机器字时，复制、变换、哈希及相等检查还需计费。常规哈希表每次常数访问为期望口径。若以字符串重建每个邻居，还会多出一层长度因子。由推理取到区间 `[L_j,U_j]` 后，用 `y_j=z_j-L_j`，保留 `U_j-L_j` 次，逐行预算扣掉零预测列的 `L_j` 和一预测列的 `n_j-U_j`。这是仿射变量平移，整数可行点逐点对应。逻辑上固定的是某类回答的数量，在一块内部可以任意选择同样多的实际位置。残余计数盒仍可能很大。输出逐次读数本身至少花费总重复数，压缩证书只需输出各块计数。[Chvátal 的整数线性框架](https://doi.org/10.1016/0012-365X(73)90167-2) · [Hufsky 等，已定位置的扣减与后续精确搜索](https://doi.org/10.1186/1471-2105-12-106)
- **更强基线。** 一般行对即使共同列多于一个，仍给出这些列偏离之和的上限。行组全体等权相加也可用逐列最小错配排除不可能。Nicolae 与 Rajasekaran 已将这一逐列总距离下界用于共同邻居剪枝，并给出三个串与各自距离阈值的精确判据。另一项对照是允许任意行数的线性规划，针对每一轴直接求实极值再取整。整体整数可行性可再交给整数规划。它们覆盖的推理和运行成本各异。只测试两行对四行无法确定与既有预处理或通用优化器相比的收益。[Nicolae 与 Rajasekaran，Consensus total distance 与共同邻居条件](https://doi.org/10.1186/1471-2105-15-34) · [Rohwedder 与 Węgrzycki，二元 ILP](https://doi.org/10.4230/LIPIcs.ITCS.2025.83)

## 完整立方体与偶校验族的专用对照

对完整 `2^d` 个符号、统一半径和任意各块重复数，给定 `z` 后最远行的距离是 `Σⱼ max(z_j,n_j-z_j)`。取每个 `z_j` 为一半附近的整数即得最小值 `M = Σⱼ ⌈nⱼ/2⌉`。每块均为正奇数、取半径 `M-1` 时，全组无解。删掉任意一行，分别向每个块的中点两侧取整，使删去的行恰好为唯一最远行，则其余每行都至少近一位。单位重时这就是 Raman、Subedi、Tewari 与 Alon、Jin、Sudakov 明列的经典缺一角构造。编码论解释为对补码封闭的重复码直和。最大距离等于总长度减去离最近码字的距离，注意最大与最小两层优化的顺序。[Alon、Jin 与 Sudakov，命题 2.1，原文标注下界来自 RST](https://people.math.ethz.ch/~sudakovb/helly-number-hamming-balls.pdf) · [Raman、Subedi 与 Tewari](https://proceedings.mlr.press/v247/raman24b.html) · [Graham 与 Sloane，On the Covering Radius of Codes](https://mathweb.ucsd.edu/~ronspubs/85_01_covering_radius.pdf)

非均匀的单位盒植入也有直接对照。选择 `0≤L_j<n_j`，若行预算正好为 `d-1` 加上植入盒之外已确定的错配，令 `x_j=z_j-L_j`。不必事先知道 `x` 落在单位盒内。所有角行最坏的剩余距离为 `Σⱼ max(x_j,1-x_j)≥d`，对任意整数 `x` 都成立。角行齐全时无解，有角行缺失就取该行补码的单位盒点。该证明同时覆盖这一特定预算结构下的所有删行子族。至少四维时，`2^d>8` 条都必需，Doignon 定理排除用三个共享整数变量、每原行一个凸约束、在所有子族上保持可行性的统一表述。它不限制随子族重新构造的模型、任意析取或一般求解算法。[Doignon，Convexity in cristallographical lattices](https://doi.org/10.1007/BF01949705) · [Alon、Jin 与 Sudakov，命题 2.1](https://people.math.ethz.ch/~sudakovb/helly-number-hamming-balls.pdf)

对完整偶校验行表和统一额度，最远偶校验行也可直接求。先按块选较远符号，若奇偶不符，改动损失 `|2z_j-n_j|` 最小的一块。若 `m≥2` 且各 `n_j` 均为奇数，最小包围半径为 `M-1`。设 `t=min_j|2z_j-n_j|≥1`，和在各块中点附近相比至少增加 `m(t-1)/2`，修正校验最多减 `t`，所以最坏距离至少 `M-1`。逐块平分并使最远角为奇即可达到。六位偶校验中两行间的距离只能为偶数，不能恰好差五位。将干扰位按 `1,1,3` 分组复制四面体符号，则四行可使所有干扰位抵消并保持相同目标位。此例说明两种推理强度不同。逐行非仿射扰动的定量效果需由对应实验说明。

## 检索范围与证据强度

检索覆盖作者和出版机构原文、arXiv、Dagstuhl、SIAM、Springer、PLOS、大学原稿库及数学期刊全文。采用的交叉术语包括 `Closest String permanent positions`、`common neighbor unequal distance thresholds`、`consensus total distance`、`binary column types integer programming`、`multi-row presolve nearly parallel rows hashing`、`one-error dictionary lookup`、`positive circuits cube vertices`、`Bernoulli orthogonal complements novel partitions`、`four-row aggregation cuts`、`k-SUM pair sums`、`Hamming ball Helly lower bound` 和 `covering radius direct sum repetition code`。其中 2011 年的两篇原论文已直接覆盖主要几何不等式和最小系数分类。其余较窄的索引、原行证据和应用组合，本次检索尚不足以确立优先权。正式表述可报告实现、完整性所依赖的已知定理、固定的数据分布和可复验的性能差异。
