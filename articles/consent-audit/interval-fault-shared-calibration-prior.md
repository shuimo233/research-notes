# 共享校准偏差下的证据采购先例

本次查新覆盖有限故障类的可靠区分、存在共用不确定参数的测量模型、区间交图和有容差的 Helly 定理。检索词包括 “sensor selection fault diagnosis uncertain systems”, “resilient sensor placement”, “interval graph dominant cliques”, “Leray numbers of tolerance complexes”, “matroid-constrained vertex cover” 和 “same measurement standard correlation”。以下比较以作者稿、论文正式版本和计量指南为据。

## 最接近的先例

- **带成本的诊断测量选择。** Jung、Dong、Frisk、Krysander 和 Biswas 在第 3 节式 (1) 中选择最低成本的传感器集合，要求各故障族的合格时间轨迹达到预定可区分度。方法已经考虑模型不确定性和测量噪声。其可区分度衡量线性残差的信号噪声比上限，候选传感器假定无故障。 [Sensor Selection for Fault Diagnosis in Uncertain Systems](https://www.diva-portal.org/smash/get/diva2%3A806672/FULLTEXT01.pdf)
- **联合可能输出的分离。** Scott、Findeisen、Braatz 和 Raimondo 使用有界扰动下的输出集合来定义保证诊断。第 4 节用两种故障情形的输出差集是否包含零来判定可分离性。第 5 节选择达到分离且干扰控制目标最小的测试输入。联合输出集合及其差集已经是成熟判据。 [Input Design for Guaranteed Fault Diagnosis Using Zonotopes](https://web.mit.edu/braatzgroup/input_design_for_guaranteed_fault_diagnosis_using_zonotopes.pdf)
- **抗任意读数错误的带价传感器配置。** Shinohara 和 Namerikawa 在最多固定数量读数可任意偏离的条件下，寻找使动态线性系统状态仍可唯一重建的最低成本传感器配置。他们的容量为全局错误数，本轮采用的是依候选世界变化的层级容量和结论标签。 [Optimal Resilient Sensor Placement Problem for Secure State Estimation](https://doi.org/10.1016/j.automatica.2023.111454)
- **共同参考量确实会产生观测相关性。** JCGM 100:2008 第 5.2.4 节指出，同一仪器、标准或参考数据用于确定不同输入时可能有显著相关性。第 5.2.6 节给出把共用影响量作为显式输入的建模办法。实际部署仍需用独立证据确定偏差的有效区间、可共享偏差的测量范围及剩余误差上限。该计量指南讨论标准不确定度，不能从中直接得到确定性误差边界。 [JCGM GUM 100:2008](https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf/cb0ef43f-baa5-11cf-3f85-4dcd86f77bd6/)
- **端点判定和容差删除的组合先例。** Fulkerson 和 Gross 第 8 节定理 8.3 给出闭区间极大团的连续排列与交图表述。Kim 和 Lew 的定理 1.1、1.5 及引理 4.2 给出区间情形按数目容许删除的紧上界，其中一维 Helly 证书至多含 \(2(t+1)\) 个区间。Lew 在混合拟阵与几何约束的 Helly 延伸中也使用容差复形和拟阵并。Huang 和 Sellier 研究在拟阵约束下选择顶点最大化所覆盖的边，层级拟阵包含在其适用范围。 [Incidence Matrices and Interval Graphs](https://msp.org/pjm/1965/15-3/pjm-v15-n3-p11-p.pdf) · [Leray Numbers of Tolerance Complexes](https://scholar.gist.ac.kr/bitstream/local/9990/2/s00493_023_00044_5.pdf) · [Extensions of the Colorful Helly Theorem，第 3 节](https://www.cambridge.org/core/journals/forum-of-mathematics-sigma/article/extensions-of-the-colorful-helly-theorem-for-d-collapsible-and-dleray-complexes/59F8ECC93B182C2578F1196F2D578242) · [Matroid-Constrained Maximum Vertex Cover](https://drops.dagstuhl.de/storage/00lipics/lipics-vol227-swat2022/LIPIcs.SWAT.2022.27/LIPIcs.SWAT.2022.27.pdf)

## 可复用的精确判据

设两个候选世界的正常读数区间分别为 \([m_{Ai}+z_A-\epsilon_{Ai},m_{Ai}+z_A+\epsilon_{Ai}]\) 和 \([m_{Bi}+z_B-\epsilon_{Bi},m_{Bi}+z_B+\epsilon_{Bi}]\)。每个世界内，同一个 \(z\) 适用于所有采购源。两个世界各自的偏差边界决定差值 \(d=z_A-z_B\) 的闭区间 \([L,U]\)。源 \(i\) 的正常读数能同时成立，当且仅当 \(d\) 落在以 \(m_{Bi}-m_{Ai}\) 为中心、以 \(\epsilon_{Ai}+\epsilon_{Bi}\) 为半径的区间 \(J_i\)。如果同一个源报告多条读数，各条采用已知的偏差线性系数，且系数在两个世界一致，就对各条允许的 \(d\) 区间求交。

固定 \(d\) 后，在所有被采购的源中找出 \(d\notin J_i\) 的冲突集合。能把它分配给两个世界各自允许的故障集合，就能构造一个共同回复。反过来，共同回复也会给出这样的分配。层级配额形成拟阵，合法冲突集合由两套拟阵取并得到。对 \(J_i\) 与 \([L,U]\) 的交集为空的源，它必须出现在冲突集合中。对其他源，共同回复等价于删去一个拟阵独立集后，剩下区间有共同交点。也可以构造由“不相交区间”组成的边，要求删去的集合覆盖这些边。理由是有限实线闭区间两两相交就有公共交点。 [Matroid Partition](https://sites.math.washington.edu/~thomas/teaching/m514_web/50YearsIP.pdf) · [非对称容量判据的先例](interval-fault-asymmetric-quota-prior.md)

只需检查 \([L,U]\) 的左界和落在其内的已购区间左端点。任取一个令冲突合法的 \(d\)，把它移到仍然能保持所有现有相交关系的最左点。这个点是这些区间左界与 \(L\) 的最大值。它的冲突集合只能缩小，仍符合故障约束。端点处相切仍可能产生共同回复。对反例可以输出精确的 \(d\)、两个故障集合和实际共享回复。对充分性可以依每个代表偏差给出拒绝见证。


单个跨标签对只使用全局计数 \(r\) 时，采购要求在每个代表偏差处至少有 \(r+1\) 个源冲突。按偏差排序，每列的冲突形态为前缀与后缀，循环排列后成为连续的一段 1。于是已有的均匀需求循环多重覆盖可以提供松弛基线。Hochbaum 和 Levin 第 4 节定理 11 的多项式算法假设同一列可重复选择。一次核验只采购每个源一次，对应有上界版本，不能直接继承这个复杂度结论。 [Cyclical Scheduling and Multi-Shift Scheduling](https://hochbaum.ieor.berkeley.edu/html/pub/cyclical-exactmatchingHL2006.pdf)

## 小证书与复核

令 \(r\) 为两个世界的故障集合之并能包含的最多源数的上界。对任何已购组合，保留左界最大的 \(r+1\) 个源和右界最小的 \(r+1\) 个源，证书至多使用 \(2(r+1)\) 个源。对任意偏差 \(d\)，若超过 \(r\) 个区间左界大于 \(d\)，则保留的 \(r+1\) 个已必然冲突。右界小于 \(d\) 的情况同理。其余情况下，两组保留源已经囊括全部冲突点，故障分配的可行性也完全相同。该推导只要求总数上界及故障约束可向子集继承。空区间可记为左界大于右界。相同界值任选，闭区间用严格不等式确定冲突。全局故障数恰为 \(r\) 时，取两个互不重叠的区间，各复制 \(r+1\) 份，就达到最坏证书大小。删除任一份后，可选择其相对的区间作为共同偏差。

本次作了独立的小规模核对。种子 91021 生成 128 个含 2 至 9 个源的区间和两组容量配置。参考算法枚举两套配额下的全部故障组合，直接求剩余闭区间的交，再比较左端点判据。覆盖 17,596 个采购子集。另对各端点及相邻端点的有理数中点进行 177,788 次逐点核对，完整采购与极端界值证书的故障可行性一致。它是数学判据的复核，部署收益需用实际证据选择任务检验。

最简单的差异见证用两个读数，世界 A 的名义向量为 \((0,1)\)，世界 B 为 \((1,0)\)，各自共用偏差在 \([-1,1]\)，无局部误差。各读数单独的区间都重叠。一致回复分别要求差值为 \(1\) 和 \(-1\)，所以两源合用就能排除共同回复。允许至多 \(r\) 个任意冲突时，可在同样规则下重复两个读数各 \(r+1\) 次。该例揭示逐源展开遗漏的是共用偏差约束。若已有正常读数之间的差量约束，同一现象也可由可行域交判定解释。

本次先例检索已覆盖不确定性下的最便宜诊断设计、全局错误计数下的鲁棒配置、拟阵独立集删除和区间端点。仍值得实测的组合点是对跨标签世界叠加共享标量偏差与不同层级故障合同，再把判据编译成可复核的最低成本采购方案。从这些领域的有限检索只能划出优先阅读范围。
