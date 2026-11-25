# 固定伪距误差合同下的最低读取预算先例

固定精度门槛下按历元改变卫星组合或星数，已有 GNSS 先例。允许任意坏源的最低成本选传感器也已有先例。这一轮可检验的具体做法，是对已知有限位置集合的标签，以逐星有界误差、每个候选各自的共享钟差和至多一颗任意坏星为条件，读值前计算每档预算的精确跨标签重合边界，再以同一个绝对误差尺度挑最小可证预算。查阅的一手文献中暂未发现同时实现这组条件的公开方法。范围见 [S4 冻结预案](gnss-budget-frontier-protocol.md)。

## GNSS 选星与完整性

- Nie、Gao、Wang 与 Ji 的算法明确为固定精度要求选择可变数量卫星，并用多星座观测作数值评估。公开的作者摘要支持其可控加权 PDOP 门槛与可变星数，全文的全局最小性在本次检索中未核实。Shi 等全文的公式 (14) 给出了可直接检查的另一例，从四星开始逐个加入，满足 GDOP ≤ 2 或达到指定星数上限即停。其星数由一条贪心路径决定，评估量是连续定位的精度因子。这些工作覆盖了按门槛改变预算这一思路。 [Nie 等，Survey Review，2017，2016 年在线](https://doi.org/10.1080/00396265.2016.1171959) · [Shi 等，GPS Solutions，2023，公式 (14)](https://doi.org/10.1007/s10291-022-01384-3)
- Gerbeth 等用 ARAIM 的保护级比较高效选星与遍历组合，主计时比较固定十二星，另扫描五至十九星报告规模成本。Walter 等的 SBAS 工作已提出将已知服务告警限值放入保护级目标，给定通道数时可用遍历作为最优参照。二者的保护级针对定位误差与完整性风险。S4 的边界是两个异标签候选在各自容许故障后，第一次能产生同一个伪距向量时的误差尺度。 [Gerbeth 等，ION GNSS+ 2016](https://elib.dlr.de/106284/1/Satellite%20Selection%20Methodology%20for%20Horizontal%20Navigation%20and%20Integrity%20Algorithms.pdf) · [Walter 等，ION GNSS+ 2016](https://web.stanford.edu/group/scpnt/gpslab/pubs/papers/Walter_IONGNSS_2016_SatSelection.pdf)
- Drevelle 与 Bonnifait 已用包含接收机钟差的区间伪距模型及鲁棒集合反演诊断可能的坏星。Su 的论文 §5.1.5 和 §5.2 已使用基于 C/N₀ 的逐星误差区间并列举可能有无界粗差的卫星子集。Fouque 与 Bonnifait 已在有限道路候选上用 GPS L1 快照残差检验兼容路段。三项先例分别覆盖有界坏星模型、信号强度加权及地图标签判定。 [Drevelle 与 Bonnifait，GPS Solutions，2011](https://www.hds.utc.fr/~bonnif/pdf/2011_GPS_solution.pdf) · [Su，2025，§5.1.5、§5.2](https://publikationen.badw.de/en/050454888/050454888.pdf) · [Fouque 与 Bonnifait，IFAC，2008](https://skoge.folk.ntnu.no/prost/proceedings/ifac2008/data/papers/4184.pdf)

## 固定可分性条件与最低成本

- Jung 等的公式 (1) 直接最小化传感器总成本，约束所有待区分故障对和故障参数实现的可分性达到给定门槛。其可分性基于故障噪声比与统计残差。Shinohara 与 Namerikawa 对动态系统最小化传感器布置成本，使系统状态在若干传感器遭任意篡改时仍能恢复。Scott 等已把在给定扰动界下保证故障可区分写成不同故障输出可达集两两不交，并据此优化激励输入。把固定要求、最低成本、坏源容忍或可达集不交单列为原创，都会与其中至少一项重合。 [Jung 等，International Journal of Control，公式 (1)](https://doi.org/10.1080/00207179.2018.1484171) · [Shinohara 与 Namerikawa，Automatica，2024](https://doi.org/10.1016/j.automatica.2023.111454) · [Scott 等，Automatica，2014](https://web.mit.edu/braatzgroup/input_design_for_guaranteed_fault_diagnosis_using_zonotopes.pdf)
- 在本模型中，固定公共尺度 \(q\) 后，每个候选中未设为故障的卫星允许的误差都是该星固定权重乘以 \(q\)。令 \(\rho_k\) 为所有 \(k\) 星组合中最大的首次跨标签重合尺度。在有限候选、闭误差区间和既定可用星集合下，存在安全的 \(k\) 星组合当且仅当 \(q < \rho_k\)。\(q = \rho_k\) 已容许两个标签产生同一回复。由于一个更大组合的共同回复可投影到子组合，且投影保留误差合同与坏星上限，增加可读星数时最优 \(\rho_k\) 不下降。依次比较四、五、六星的 \(\rho_k\) 给出候选预算内的精确最小值。少于四个读取时，两个候选可以各删去一颗星，仅剩至多一颗共同诚实星，自由共享钟差可把这颗星对齐。这个下界取决于当前模型，读值后追加、改变故障约束或额外获取钟差观测都定义了别的优化问题。 [加权边界的推导](gnss-quality-verification.md) · [S4 冻结预案](gnss-budget-frontier-protocol.md)
- 各预算比较使用同一 \(q\)，其意义是在同一逐星误差合同下买足以区分标签的读取。用参考位置所需误差尺度 \(R_k\) 除以该预算的 \(\rho_k\)，再用统一比例阈值 \(t\) 校准，则每个历元与预算实际使用 \(q_k=t\rho_k\)。只要 \(\rho_k\) 变化，绝对容许误差就跟随地图分离度变化。这种标准化是已有的 conformal 技法，回答的是随案例变化的误差尺度下的可分性。固定误差合同下的预算结论不能直接从比例阈值换算。 [Diquigiovanni、Fontana 与 Vantini，Journal of Multivariate Analysis，2022，§3](https://arxiv.org/pdf/2106.01792) · [六星比例规则与先例](gnss-route-verification-prior.md)

## 有限预算的同时校准

在有参考位置的每个校准历元，先计算冻结的四、五、六星组分别需要的最小误差尺度 \(R_4,R_5,R_6\)，再用三者最大值作单个分数。由最大值不超过 \(q\) 即三项都不超过 \(q\)，若完整的历元分数向量可交换，且候选位置、选星、误差权重和校准规则符合该秩校准所需的冻结条件，则以 \(\lceil (n+1)(1-\alpha)\rceil\) 选秩，能把三档预算的同时覆盖作为一个边际事件。预算格内分数可以任意相关。不同预算各做一次同水平的分位校准，没有同时覆盖结论。最大分数做同时覆盖在既有多变量 conformal 研究已有系统处理。另一种已有思路是在有限策略族上采用多重检验直接控制预定义风险。 [Diquigiovanni、Fontana 与 Vantini，§3、附录 A.1](https://arxiv.org/pdf/2106.01792) · [Angelopoulos 等，Learn Then Test](https://arxiv.org/abs/2110.01052)

该边际结论依赖完整案例的可交换性，不能自动转为给定星数、已作答历元或任一标签内的条件覆盖。S4 的校准和留出来自一趟路线的交错时块，按预案只报告实测，秩仅是尺度选择规则。模型内的条件保证可以单独核验。只要真位置在候选内、实际误差符合合同且 \(q<\rho_k\)，恰有一个标签能兼容这次回复。 [Jin 与 Ren，选择条件覆盖](https://arxiv.org/abs/2403.03868) · [S4 冻结预案](gnss-budget-frontier-protocol.md)

## 实用性比较与陈述范围

沿用同一选星组合、可用星库存和故障预算，对比绝对尺度法与截尾最小二乘，可以区分判定器与预算方案的影响。固定四、五、六星的对照能检查变预算是否优于最便宜的同等成功方案。若另做选星基准，C/N₀ 排序或加权 GDOP 是已发表的廉价策略。用同一 \(q\) 和跨标签判定器分别评估这些策略，可检查昂贵的全组合排序到底减少了读取还是提高了可答率。报告各标签正确、错误、拒答与交集成本，防止把零读取拒答当作同等任务下的节省。 [Nie 等，加权 PDOP](https://doi.org/10.1080/00396265.2016.1171959) · [S4 冻结预案](gnss-budget-frontier-protocol.md)

读取单位是离线应用已跟踪的一条伪距值。可见性、C/N₀、历元和星历是已给定的规划输入，全部候选位置也作为有限路线地图预先给定。历元的真实候选归属在校准与最终评估中各自使用。研究结论应限定到这种已知地图和元数据下的预算与实测误差，并把射频采集、首次捕获、连续定位、地图遗漏和真实功耗留给直接测量这些量的验证。 [Tiwari 与 Mather，GNSS 信号获取与重捕获](https://doi.org/10.3390/engproc2025088063) · [SnapperGPS，实体低功耗接收机验证](https://arxiv.org/abs/2207.06310)
