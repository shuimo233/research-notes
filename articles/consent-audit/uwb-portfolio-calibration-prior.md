# UWB 证据组合的分离半径和留出校准先例

本次查新比较最坏情形传感器选择、抗坏测量的诊断、用校准数据选择观测、拒答分类，以及 UWB 稳健定位。关注的具体判据是对每个固定锚组合 \(S\)，先求可跨标签共享读数的最小容限 \(\rho(S)\)，再与真位置或真标签在校准读数上的需求次序统计量比较。 [冻结实验协议](uwb-portfolio-calibration-protocol.md)

## 传感器选择与分离

- Wang、Sznaier 与 Dabbene 在给定有界测量噪声集合的条件下，从众多可用传感器中选择受预算限制的组合，使最坏状态估计误差最小。他们的状态可行集也是所有能产生观测的候选状态。区别在于其噪声集预先给定，目标是状态误差而非带实际读数校准的跨标签可分离性。 [A Convex Optimization Approach to Worst-Case Optimal Sensor Selection](https://robustsystems.coe.neu.edu/sites/robustsystems.coe.neu.edu/files/systems/papers/Yin_CDC13.pdf)
- Jung 等人的式 (1) 已经在噪声和模型不确定性下选择最便宜的传感器组合，要求所有指定故障情形达到最低可区分度。其可区分度衡量可达到的线性残差信噪比，候选传感器本身假定无故障。Ma 等人则在二类高斯模型均值落在不同椭球的条件下，最大化选中传感器最不利参数下的 Chernoff 距离。两者都提供了最坏跨类区分与传感器组合相关的直接先例。 [Sensor Selection for Fault Diagnosis in Uncertain Systems](https://www.diva-portal.org/smash/get/diva2%3A806672/FULLTEXT01.pdf) · [A Gradient-Based Method for Robust Sensor Selection in Hypothesis Testing](https://www.mdpi.com/1424-8220/20/3/697)
- Scott 等人在有界噪声的故障诊断中以不同故障的联合输出集合不相交作为保证条件，第 4 节检验两输出集合之差是否含零，第 5 节据此选择满足分离要求的测试输入。Shinohara 与 Namerikawa 直接求满足最坏情形恢复要求的最低成本仪器配置，坏读数按全局数量计。联合输出分离、按跨候选对取最坏值、容忍任意坏测量这三项各有先例。 [Input Design for Guaranteed Fault Diagnosis Using Zonotopes](https://web.mit.edu/braatzgroup/input_design_for_guaranteed_fault_diagnosis_using_zonotopes.pdf) · [Optimal Resilient Sensor Placement Problem for Secure State Estimation](https://doi.org/10.1016/j.automatica.2023.111454)
- 在结构健康监测中，用训练集中健康与受损数据拟合 SVM，再选择使最小间隔最大的传感器组合，也有实测案例。该方法比较统计分类超平面附近的训练样本，无法直接提供给定有界误差模型下的最早共同读数。 [On Sensor Optimisation for Structural Health Monitoring Robust to Environmental Variations](https://wes.copernicus.org/articles/6/1107/2021/)

## 校准、采购与拒答

- Cortes-Gomez 等人已经用下游决策代价设计共形预测集合。Zhang 与 Bates 进一步给出全局特征排序实例，用一组样本选特征顺序、独立样本做校准、第三组做测试，每个前缀分别校准。其量化对象是类别集合平均大小或共形信息量，未使用有限物理候选、可分配坏测量及闭区间首次相交的半径。Hoarau 等人则按预定代价顺序在线增加模态，并在共形集合只有一个标签时停止。固定组合的独立校准及唯一标签后停止采集都已有先例。 [Utility-Directed Conformal Prediction](https://proceedings.iclr.cc/paper_files/paper/2025/hash/0c6b452f1bbfb6905f6bac957d73b321-Abstract-Conference.html) · [Conformal Prediction Sets Quantify Information Gain，附录 D.2](https://arxiv.org/html/2610.08785v1#A4.SS2) · [Reducing Aleatoric and Epistemic Uncertainty Through Multi-modal Data Acquisition，第 3 节](https://doi.org/10.1007/s10994-026-07042-w)
- 拒答与错误率之间的权衡可追溯到 Chow，El-Yaniv 与 Wiener 给出了选择性分类的风险与覆盖表述。Sadinle、Lei 与 Wasserman 在满足真标签覆盖时最小化预测集合的平均大小，也记录了预测集为空的情形。Jin 与 Ren 说明边际覆盖与通过筛选后条件覆盖不同，举例包括只取单标签预测。多组合共享同一批校准样本时，可使用预先冻结的独立二次校准，或针对多个候选的显著性校正方案。Angelopoulos 等人的 Learn Then Test 提供了后一路径的通用范式。 [Chow](https://doi.org/10.1109/TIT.1970.1054406) · [On the Foundations of Noise-free Selective Classification](https://www.jmlr.org/papers/v11/el-yaniv10a.html) · [Least Ambiguous Set-Valued Classifiers with Bounded Error Levels](https://doi.org/10.1080/01621459.2017.1395341) · [Confidence on the Focal](https://arxiv.org/abs/2403.03868) · [Learn Then Test](https://arxiv.org/abs/2110.01052)
- 截尾最小二乘的目标是保留最小的若干平方残差再求和，是已有稳健估计方法。UWB 文献亦有枚举或挑选定位锚子集、排除坏链路以及加权最小二乘的实测先例。本轮强对照把截尾最小二乘放在与主法相同的有限位置候选、固定偏差和允许删除一锚的条件下，属于对经典估计准则的同预算实现。它给出相对最小损失的分类分数和经验校准阈值，输出与拒答均可逐案核对。 [New Algorithms for Computing the Least Trimmed Squares Regression Estimator](https://www.sciencedirect.com/science/article/pii/S0167947300000566) · [Range-Based Localization for UWB Sensor Networks in Realistic Environments](https://doi.org/10.1155/2010/476598) · [Anchor Selection by Geometric Dilution of Precision](https://doi.org/10.1049/wss2.12006)

## 严格门槛能说明什么

把 \(R_S(y,w)\) 定义为让位置 \(w\) 接受读数 \(y\) 所需的最小容限，其中允许合同内的偏差和坏锚。闭合同下的第一跨类重合半径是
\[
\rho(S)=\min_{\ell(w)\ne\ell(v)}\inf_y\max\{R_S(y,w),R_S(y,v)\}.
\]
本轮有限候选及闭区间模型另构造达到临界值的共同读数。阈值 \(q(S)<\rho(S)\) 排除任何读数同时支持两个不同标签。若读数满足 \(R_S(y,w_{\rm true})\le q(S)\)，真标签就在输出集中，并因分离而成为唯一标签。超出合同的读数仍可能误判、拒答或碰巧给对结果。选择性错误率需要另算已给结论为分母的错误比例。

对 \(k\le n\)，经验第 \(k\) 小需求 \(q_{(k)}(S)<\rho(S)\) 当且仅当至少 \(k\) 个需求值严格低于 \(\rho(S)\)。分离半径比较与严格小于该半径的支持比例可共用审计记录。后续可以另定义真标签分数为同标签位置的需求最小值。该分数不大于真位置的需求，更直接对照结论，但无法据此验证具体位置恢复。两种分数与阈值必须在看留出数据之前固定。

分位秩 \(\lceil(n+1)(1-\alpha)\rceil\) 与拆分共形校准一致。适用的有限样本边际覆盖依赖于固定评分规则和校准单元与测试单元的交换性。本轮是空间分块的现场档案回放，没有验证这个交换性。其阈值只代表事先冻结的经验规程，结果中应报告真实位置不成立的次数、给出单标签的比例和其中错误次数。读取重复包也不会增加独立位置的数目。 [Distribution-Free Predictive Inference for Regression，第 2 节](https://www.stat.berkeley.edu/~ryantibs/papers/conformal-jasa.pdf) · [UWB 采集与原始校准先例](uwb-heldout-calibration-prior.md)

本次检索在上述原始工作中没有找到把每个固定组合的最小几何跨类重合半径与该组合在独立真位置或真标签读数上的容限需求分位作严格比较，并进一步用它选择最低成本抗坏锚组合的完整等价方案。可核验范围是特定有界误差模型、固定候选合同和预设对照下的这一组合。已有研究对其中的各类方法有明确优先权，有限检索不建立本组合的全球优先权。
