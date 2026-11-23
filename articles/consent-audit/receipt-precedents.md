# 三段复制日志的切点标签：先例、等价问题与区间核验

核查日期为 2026 年 11 月 23 日。设有 n≥2 个有序候选切点，注册人知道两个真实切点 i<j。它们把每个事件的导出记录分为三个非空连续段。每段逐位忠实复制同一个来源对该事件给出的那一位报告，三份来源报告里至多一份错误。审计者看到完整位串，注册人可以预发一个与事件无关、可复用的可信标签。下文把可选的可信同源核验记为 SAME，它直接判断两个位置是否属于同一来源段。

**任意标签的数学子问题已有直接等价前例。** 它正是只有两个键的单调最小完美哈希：为有序集合 {i,j} 存一段资料，日后给定一个保证属于集合的键，只需回答其秩。Assadi、Farach-Colton 和 Kuszmaul 的冲突图甚至已经使用移位图。他们的冲突图在两键时与这里的图完全一致。能单独提出的候选增量是把三段日志归约至此，以及当部分标签必须由指定的区间同源核验产生时，精确计算余下需要的标签数。未找到把后一公式用于同一任务的已发表原文。[Belazzougui、Boldi、Pagh 和 Vigna，SODA 2009](https://epubs.siam.org/doi/10.1137/1.9781611973068.86) · [Assadi、Farach-Colton 和 Kuszmaul，作者稿第 3 页及第 3 节](https://arxiv.org/pdf/2207.10556)

## 三段多数、端点的秩与移位图

没有跳变时，多数即共同值；有两次跳变时，第一段与第三段相同，多数即两端的值。仅出现一次跳变时，设跳变在 t。若 t=i，跳变右侧涵盖后两个来源，取右值；若 t=j，左侧涵盖前两个来源，取左值。反过来，给定 {i,j} 和保证属于它的 t，可造一个在 t 从 0 跳至 1 的可行日志，从多数恢复 t 的秩。因此归约双向成立。每个三来源取值均可把其多数当作真实位，并满足至多一个来源报错的承诺。

两套布局发生冲突，当且仅当存在 a<b<c，两套切点分别为 (a,b) 与 (b,c)。同一个可见跳变 b 在两套布局中的秩相反。故任意标签正好是移位图 Sh(n) 的顶点着色。该图的色数为 ⌈log₂ n⌉，最小固定长度为 ⌈log₂⌈log₂ n⌉⌉ 比特。直接编码时，可把 0 至 n−1 写成等长二进制数，存两键最高不同位的位置；查询键在该位取 0 就是小键，取 1 就是大键。这里 n 指候选切点数。[Erdős 和 Hajnal，1966，原文](https://www.renyi.hu/~p_erdos/1966-07.pdf) · [Simonyi 和 Tardos，作者稿第 5 页，明确写出精确色数](https://arxiv.org/pdf/0906.2897)

| 先例 | 和本题的关系 |
| --- | --- |
| 单调最小完美哈希 | 查询元素已知在集合中，输出它在排序集合中的位置。Assadi 等的图连接在公共键上要求不同秩的两个键集。原文还解释一般多键移位图是其冲突图的子图；对两键，只有公共键在其中一个集合为小键、在另一集合为大键才会冲突，两图相等。上述标签复杂度是该已有模型的直接特例。一般多键的渐近或随机化空间界不能替代这个精确的小规模推导。[2009 年原始模型](https://vigna.di.unimi.it/ftp/papers/MonotoneMinimalPerfectHashing.pdf) · [2023 年论文](https://epubs.siam.org/doi/10.1137/1.9781611977554.ch20) |
| 零错边信息编码与函数计算 | Witsenhausen 将接收端有附加信息的零错编码与图的着色联系起来。这里接收者只需知道函数值；只在相同可见日志要求不同输出时连边。若改为要求重建全部切点，图就会改变。单次、固定长、最坏情形的色数也要与多样本平均编码率区分。[Witsenhausen，1976](https://ieeexplore.ieee.org/document/1055607/) · [Orlitsky 和 Roche，2001](https://doi.org/10.1109/18.915643) · [Meng 和 Ramamoorthy，零错函数计算的经典与量子模型](https://arxiv.org/abs/2402.01549) |
| 分布式局部着色 | 利用相邻标识的二进制差异迅速缩减颜色，在 Cole–Vishkin 的确定性链表算法已有先例；Linial 的下界亦研究局部视野上的着色。两键单调哈希给本题提供了更直接的输入输出等价。[Cole 和 Vishkin，1986](https://www.sciencedirect.com/science/article/pii/S0019995886800237) · [Linial，1992](https://epubs.siam.org/doi/abs/10.1137/0221015) |

## 固定 SAME 的查询能力

选两个日志位置做 SAME，取其回答的反，即可得到“这两个位置之间是否至少有一个切点”的答案。对切点编号而言，这是一项区间 OR 群测试。在原始的区间群测试文献中，同一查询形式常用来恢复所有阳性位置，还有允许错误或承诺阳性连续的变体。本题切点可不相邻，输出只需保证已知跳变在二元组中的秩正确。两对切点即便得到相同的全部核验结果，只要不存在同一日志要求不同多数，也可以共用这些结果。已核查的完整识别结果没有直接给出这个较弱目标的精确查询数。[Cicalese、Damaschke 和 Vaccaro，2005](https://www.inderscience.com/info/e_inarticle.php?artid=8441) · [《Interval group testing for consecutive positives》，2017](https://doi.org/10.1016/j.disc.2017.02.010)

若没有额外任意标签，令 L(b) 表示 [1,b−1] 中所有点均有某个终点小于 b 的所选区间覆盖；R(b) 同理，要求 [b+1,n] 中所有点均有起点大于 b 的区间覆盖。一个内部点 b 可以与 a<b、c>b 形成混淆，当且仅当 L(b)、R(b) 同时失败。原因是一个避开 b 的连续区间不能同时覆盖 a 和 c。只需也必须每个内部 b 至少满足一项。

由此可以独立验出 n≥4 时恰需 ⌈n/2⌉ 项固定 SAME。每个内部 b 的 L 或 R 至少占用一个终点 b−1 或起点 b+1，这些算作有类型的不同端点。若两种条件各有一个内部见证，还至少有起点 1 和终点 n，它们都不能承担上述 n−2 项要求；因此至少需要 n 个端点。若内部点全部同向，则至少要 n−2 个不同区间，同样足够给出下界。上界取相邻两点为一组的所有区间，末尾如有单点即单独成组。n=2、3 的精确值分别为 0、1。几何区分码也利用端点落在相邻点之间的间隙刻画可区分性，但其任务是以区间成员关系识别单个点，允许的混淆对与此处不同。[《Discriminating Codes in Geometric Setups》，第 2 节](https://ffoucaud.github.io/new-backup/Publications/Papers/C15_DiscriminatingCodes_Geometric_ISAAC2020.pdf)

## 给定任意区间表后，还需多少种标签

设 hₜ 是所选区间中含点 t 的那些区间编号。布局 (i,j) 的区间 OR 答案为 hᵢ∪hⱼ。对每个在某点出现的签名 v，记 mᵥ 为带此签名的点数。若在所有这些点的左侧存在 hₜ⊊v 的点，置 lᵥ=1，否则取 0；在右侧同样定义 rᵥ。固定这张区间表后，最少额外标签种数为

> max(1, maxᵥ ⌈log₂(mᵥ+lᵥ+rᵥ)⌉)。

标签的固定比特长度还需要对该种数再取一次 ⌈log₂⌉。注册人知道布局和预定区间表，因而能算出核验答案，不需要看到任何事件位。

1. 若 (a,b)、(b,c) 给出相同的区间 OR 答案，则 hₐ、h𝒸 均包含于 hᵦ。事实上，对一个不含 b 的区间，两边 OR 相等要求它同时含 a 和 c 或同时不含二者，而前者和区间连续性矛盾。因此任何冲突发生在以 v=hᵦ 为答案的子图内。没有任何点持有该签名的答案组仅有孤立顶点。
2. 同签名 v 的首末位置之间，每一点的签名都包含 v。因而真子签名点只能位于左端或右端。对有冲突的顶点来说，所有可充当左端的此类点可映成一个左端代表；右侧亦然。核心点之间以及代表至核心的弧形成按顺序相接的移位图。取一名实际左代表和一名实际右代表，即可在原图中找到相同的核心。两端代表互连的长弧是否属于答案组取决于两者签名并集；在对应移位图中，这条弧本来就是孤点，其缺失不影响任何非平凡着色下界。对没有边的非空输入仍需一个标签。
3. 不同答案组可以重复使用同一套标签，故取各组色数的最大值。作为独立特检，如果只许问一个区间，并允许 r≥1 **种**额外标签，则最多容纳 n=2·2ʳ−1 个切点；取非空前缀或后缀达到这个数。区间两边都留点时，其内部签名两侧均有真子签名，给出的上界反而少一点。这里 r 是标签种数，不是比特数。

上述证明的外框是经典的按已知答案分组后给冲突图着色，以及移位图色数。具体推论用到了区间的连续性：它排除两侧同时命中却跳过中点，还把真子签名点限制到核心外侧。一般的任意子集 OR 查询不具备这两个性质。检索也覆盖了弧图、删去首末弧和图同态；这些通用框架涵盖着色的推理，未找到原文已经给出这个由区间签名和两端存在性决定的闭式。[Assadi 等，冲突图](https://arxiv.org/pdf/2207.10556) · [Simonyi 和 Tardos，移位图](https://arxiv.org/pdf/0906.2897) · [《Iterated Arc Graphs》](https://arxiv.org/abs/1610.01259)

## 工程对应与假设边界

- Apache Arrow 的 run-end encoded 数组用递增的结束位置和每段的值表示连续相同值。若把来源 ID 作为值编码，便可显式保存布局；仅对报告位做值压缩时，相邻来源报告同一位会遮住来源交界。规范本身没有承诺来源身份、三个独立根或至多一个故障。[Apache Arrow 列式格式，Run-End Encoded Layout](https://arrow.apache.org/docs/format/Columnar.html#run-end-encoded-layout)
- Thanos 的查询层使用配置好的 replica label 对来自高可用副本的时间序列去重，并可从另一副本补齐中断期间的样本。它提供“标识副本后才可合并”的实际例子。此机制的目的、采样和合并策略均不能作为三连续来源忠实复制同一次观测的实测证据。[Thanos Query，Deduplication](https://thanos.io/v0.35/components/query.md/)
- 日志中的“复制”须在模型里明确定义。同一段导出的是**同一次来源观测的完整复制**，允许原始来源报错。如果故障允许在归档后任意篡改记录、插删、重排，或每个副本各自重新测量，三段常值和可见跳变的推导不再适用。标签还需绑定布局版本和正确的顺序，其最小比特数只计算布局建议，不包含签名、版本号或认证开销。W3C PROV 的实体及派生关系可以记录来源关系，其语义本身不会认证这些前提。[W3C PROV-DM](https://www.w3.org/TR/prov-dm/)

## 检索记录与可主张的范围

- 第一轮用英文检索 `three run majority two breakpoints provenance zero-error communication`、`rank of element in pair promise one-way`、`shift graph side information endpoint`、`monotone minimal perfect hashing two keys conflict graph`、`local IDs deterministic coin tossing`，并查中文“有序三段 多数 端点秩 位移图 单调最小完美哈希”。原文回查覆盖 SODA、IEEE、作者预印本及 Erdős 的文章扫描本。
- 第二轮检索 `nonadaptive interval group testing arbitrary two positives`、`discriminating codes geometric intervals points`、`interval OR rank of one of two defectives`、`shift graph coloring interval signatures`、`monotone minimal perfect hashing assisted by side information`、`arc graph transitive tournament delete long edge`，并查中文“非自适应 区间群测试 两件次品 已知端点 秩”。工程部分查 Apache Arrow 官方格式与 Thanos 的维护者文档。
- 两键秩存储、移位图、精确色数和一般零错着色理论均已有文献依据。此次未查到直接表述三段复制多数与该问题双向等价的论文，也未查到在给定任意区间核验后明示上述剩余标签闭式的原文。适合发表的表述是“将三段审计化为两键秩查询，并推导区间核验后的精确剩余标签数”。未覆遍所有语言、术语或未公开作品，此次检索不构成优先权证明。
