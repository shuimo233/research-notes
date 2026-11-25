# UWB 留出校准的原始数据与先例

Bregar 的公开实验在四个环境采集 DWM1000 双向测距。实验人员用激光测距定位标签，并让标签在每个预定点保持静止，然后按锚点及信道顺序各采集 31 份读数。工业环境的 84 个位置属于同一次实验路径。按同一个点的读数编号留出，能检验同位置上的重复测量。按完整位置和连续路径段留出，才涉及未参与拟合的几何条件。不同锚点同一编号的读数也没有同步采样依据。 [数据 v2.0](https://zenodo.org/records/8280736) · [数据论文，第 5–6 页](https://www.nature.com/articles/s41597-023-02639-5.pdf#page=5)

## 作者发布的处理顺序

1. 将 `walking_path.csv` 的坐标按位置目录对应到每个原始文件，覆写原始 CSV 的标签 XYZ。坐标键和评估参考值使用修正后的位置目录及路径表。读取 raw CSV 时，前两行分别是版本和列名。Zenodo 目录示例采用 `location`，作者脚本使用 `environment`，具体路径以归档成员为准。 [数据格式](https://zenodo.org/records/8280736) · [修正标签坐标](https://github.com/KlemenBr/uwb_positioning/blob/ef1c7906344ce54ab1b0de9c3e7b4e1e5f4dc4cc/preprocess/fix_position_data.py#L21-L50)
2. 对每个位置、锚点和信道的文件，在参考距离与实测距离两个变量上应用 DBSCAN，参数是 `eps=2.0`、`min_samples=5`。代码最终保留 `core_sample_indices_`，范围可能窄于论文叙述的“只删除聚类噪点”。随后把恰为 `NLOS` 的原始字段转成 1，其余转成 0。该代码只是转码，无法证明所有非 `NLOS` 记录都有可靠的无遮挡参考。 [异常处理](https://github.com/KlemenBr/uwb_positioning/blob/ef1c7906344ce54ab1b0de9c3e7b4e1e5f4dc4cc/preprocess/fix_outliers.py#L75-L101) · [NLOS 转码](https://github.com/KlemenBr/uwb_positioning/blob/ef1c7906344ce54ab1b0de9c3e7b4e1e5f4dc4cc/preprocess/fix_nlos_type.py#L51-L64)
3. 对每个环境、锚点、信道组合，扫描路径中通过首行 LoS 检查的位置，选择欧氏参考距离最短的一处。偏移用该处平均实测距离减参考距离估计，再从所有相应读数减去该数。论文式 (14) 给出的偏移符号与代码相反，文字也写减去偏移。以代码的符号重建作者算法。文章和软件都使用全路径标注计算该结果。做留出对照时，仅从校准切分找最近的 LoS 位置，不复用全路径拟合的偏移。 [论文，第 8–9 页](https://www.nature.com/articles/s41597-023-02639-5.pdf#page=8) · [偏移计算](https://github.com/KlemenBr/uwb_positioning/blob/ef1c7906344ce54ab1b0de9c3e7b4e1e5f4dc4cc/preprocess/fix_offset.py#L62-L84) · [应用偏移](https://github.com/KlemenBr/uwb_positioning/blob/ef1c7906344ce54ab1b0de9c3e7b4e1e5f4dc4cc/preprocess/fix_offset.py#L111-L123) · [论文所引软件归档](https://zenodo.org/records/8428557)
4. 发布者发现工业环境 A6 从墙面安装点掉落。论文图 5 对比了 A6 与 A7，并报告约在位置 50 到 61 之间有 11 个异常位置。构造清理版数据时，代码排除了工业环境所有位置的 A6。若需要观察这个故障，使用 v2 的 raw CSV；使用固定名义坐标计算的只能是相对原安装位置的残差。论文未提供掉落后的锚点坐标、逐包安装状态或可独立核验的故障时间戳，不把图中的范围直接当成逐包标注，也不利用其挑选校准样本。 [数据论文，第 8–9 页](https://www.nature.com/articles/s41597-023-02639-5.pdf#page=8) · [A6 排除代码](https://github.com/KlemenBr/uwb_positioning/blob/ef1c7906344ce54ab1b0de9c3e7b4e1e5f4dc4cc/preprocess/fix_final_loc2_A6.py#L48-L57)

## 实测校准的强对照

- **真实锚点校准已有先例。** 产品文档明确允许对每个 DWM1000 模块校准天线延迟，并提供 APS014。Shalaby 等人进一步把设备天线延迟与依接收信号功率变化的偏差、方差建模，用训练实验拟合后在两次测试实验评估。Bregar 的 Eq. (12) 显示一对设备的发送和接收天线延迟累加，因此多个链接确实能共享标签端的硬件项。但这个数据集只有一个移动标签。如果每个锚点偏置也未知，自由改变标签共同项并作反向调整即可保持所有拟合值，数据本身无法分别识别两者。全标量偏差是待检验的简化模型。 [Qorvo DWM1000 文档与 APS014](https://www.qorvo.com/products/p/DWM1000) · [Calibration and Uncertainty Characterization for UWB TWR，第 III–V 节](https://arxiv.org/abs/2210.05888) · [Bregar 的式 (12)](https://www.nature.com/articles/s41597-023-02639-5.pdf#page=8)
- **同一档案上的任务已有后续工作。** PLOS ONE 的 LightGBM 集成直接使用这份 v2 数据从 CIR 预测 LoS/NLoS。Bregar 的技术验证已发布 WLS 多边定位及学习型测距修正。它们的输出分别是路径状态及连续位置或距离误差，和有拒答机制的离散结论采购有不同评测对象。比较时可用相同已购读数做 WLS 或有限候选残差打分，在校准位置匹配拒答覆盖率，然后比较测试位置上的错误与每案查询数。直接对比论文所报准确率会混入输出任务和切分差异。 [LightGBM 论文](https://doi.org/10.1371/journal.pone.0353288) · [Bregar 技术验证代码入口](https://github.com/KlemenBr/uwb_positioning#run-experiments)
- **真实锚点子集选择也已有验证。** Albaidhani 等人对实测 UWB 锚点组合使用加权 GDOP 排序，再对选中组合做线性化最小二乘。Zhao、Goudar 与 Schoellig 在杂物环境中同时优化几何位置、NLOS 偏差及所需锚点数量，适用于 TDoA 安装规划。Van Herbrugge 等人对比 TWR 与 TDoA 的偏差校正和定位链条，其锚点子集选择放在 TDoA 分支，先用全部时间差估计位置，再选择最接近该位置的若干双曲面重新拟合。后一方法在第一步已经读取全部测量，可比较事后鲁棒性，却不能直接作为少读取测量的报价对照。 [加权 GDOP 锚点选择](https://doi.org/10.1049/wss2.12006) · [二维和三维 TDoA 布点实测](https://arxiv.org/abs/2204.04508) · [多指标定位基准，第 IV-B.6 节](https://doi.org/10.1109/ACCESS.2024.3358274)

Wang 与 Dong 也使用 Bregar 档案进行连续位置的误差缓解，其第 5.1 节报告排除了 11 个位置的异常 A6 读数。保留整个原始 A6 条带来观察故障表现时，应明确区分这项选择和已有误差缓解实验。该文单独的环境级留出针对另一份 LoS/NLoS 识别数据，不能用来证明 Bregar 档案上的跨位置留出效果。 [UKF–BiLSTM 双向修正，第 5.1 节](https://www.mdpi.com/2079-9292/15/3/687#sec5dot1)

同位置复测能支持短程回放和方法核验。要说明跨位置实用性，预先规定位置切分、校准方法和拒答阈值，保留一次真实 A6 故障的时间相关性，报告每个位置的错误及拒答。保守判断只能在明确的误差与故障合同范围内保证结论。由有限校准数据挑出的经验边界需要独立测试其覆盖，范围不能从设备规格或发表的全数据清理结果直接继承。
