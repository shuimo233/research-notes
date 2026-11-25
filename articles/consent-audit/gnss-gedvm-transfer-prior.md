# GEDVM 手机和行程留出的数据口径及先例

这轮核对 GEDVM 作者发布的原始数据目录、时间对齐和参考解口径，并查找以新行程、环境或设备验证 GNSS 信号质量、误差模型与行为分类的原始研究。所核对的 GEDVM 公开发布固定于 2026 年 10 月 15 日提交，采集与论文发表另有各自日期。 [作者公开数据](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/README.md) · [Jiang 等人 2025 年论文](https://doi.org/10.1109/TITS.2025.3594956)

## 采集单元和配对

作者在加拿大卡尔加里录制三个普通驾车行程。三天的 GPS 周均为 2331，日期与本轮广播星历日序对应。每个行程发布两部手机的未修改原始压缩日志、相应参考轨迹和接收机钟差历元索引。相同物理手机标识跨日重复，两代机型不代表六个不同接收机。 [正式会话清单](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/metadata/sessions.csv) · [选取与限制](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/docs/SELECTION.md)

| 行程 | 日期和日序 | Pixel 5 | Pixel 7 Pro | 两机与参考的共同时间包络 |
| --- | --- | --- | --- | ---: |
| drive01 | 2024-09-10 / 254 | gp51 | gp7p3 | 88.0 分钟 |
| drive02 | 2024-09-11 / 255 | gp52 | gp7p3 | 69.8 分钟 |
| drive03 | 2024-09-12 / 256 | gp51 | gp7p4 | 41.4 分钟 |

共同时间包络只说明时间有重叠。两部手机记录同一行程，因此共享路线、部分卫星、传播环境和参考设备。仅留出一条手机日志，若校准仍使用同次行程的伴手机，会保留同场景信息。留行程时将当日两部手机全部排除。留物理设备时排除所有同 ID 记录，其余仍可包含相同机型。留机型时排除整个模型系列。若要验证跨日且跨机型，校准和拟合都不使用目标日或目标型号的记录。同日跨手机可作为另一种较近迁移的对照。 [选取与限制](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/docs/SELECTION.md) · [正式会话清单](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/metadata/sessions.csv)

原始手机和参考导出均约 1 Hz。数据发布中的 271 个候选加速事件是从参考轨迹重新筛选，18 个预切事件例来自同一批行程，事件窗口可重叠。两部手机的数据用于配对重放；候选事件不构成额外的独立行程。原论文用载波相位差和整段图优化分析驾驶动作。本文的单历元码伪距标签任务与该论文的运动量、事件计数及性能指标不同。 [数据集 README](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/README.md) · [事件生成口径](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/docs/SELECTION.md) · [原论文](https://doi.org/10.1109/TITS.2025.3594956)

## 时间与参考位置的有效范围

- **用 GPS 周内秒同步。** 文档用接收机的 TimeNanos 减去 FullBiasNanos 和 BiasNanos 作为历元时标，保持整数纳秒或 Decimal 至相减结束。每颗星的实际码伪距仍需测量偏移、GPS 周界及状态判断。2024 年这三天 GPS 比 UTC 快 18 秒，该固定转换只用于当期显示。Pixel 5 常在整数 GPS 秒后约 0.44 秒，Pixel 7 Pro 常接近整数秒。按物理时刻匹配，并仅在有效相邻参考行之间插值。若在约 30 m/s 的记录中直接四舍五入这类偏移，误配可达十米量级。包内没有拟合的延迟修正。 [作者时间对齐文档](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/docs/TIME_ALIGNMENT.md) · [Android GnssClock](https://developer.android.com/reference/android/location/GnssClock) · [Android GnssMeasurement](https://developer.android.com/reference/android/location/GnssMeasurement)
- **保留硬件钟边界及取得顺序。** 历元索引按 HardwareClockDiscontinuityCount 与 TimeNanos 键组织。正式清单列出 drive02 的两份日志分别有 81 和 500 条无效钟差 Raw 行，口径是记录行数。drive03 的 Pixel 7 Pro 有一处非正的历元钟差步长。不能靠重排、跨不连续区间插值或把手机 Fix、出厂文件名的墙钟当作共同基准来弥补。参考秒数与伪距统一时基后，才可比较各手机的同一路段。 [作者时间对齐文档](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/docs/TIME_ALIGNMENT.md) · [会话清单](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/metadata/sessions.csv)
- **使用每部手机对应的参考导出。** PwrPak7 GNSS/INS 平滑解以 WGS84 ECEF 米给出位置，电话各有杆臂关联。发布者只转成 CSV，未重新做杆臂或平滑。实际导出头标记 Inertial Explorer 8.90.6611 和 Smoothed TC Combined，论文文字提到版本 9。复现以导出头为准。未发布 PwrPak7 原始记录、高频参考和逐历元协方差。质量码保留为诊断元数据，不能用作普遍确定性精度界。参考 GNSS 与手机也可能共享卫星传播误差。框架可把这条独立设备轨迹作为参考证据，不能从发布包重建或认证绝对真值误差。 [参考文件格式](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/docs/DATA_FORMAT.md) · [参考导出头示例](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/metadata/reference_drive01_gp51.txt) · [作者选择说明](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/docs/SELECTION.md) · [Inertial Explorer GNSS 处理文档](https://docs.novatel.com/Waypoint/Content/Inertial_Explorer/GNSS.htm)
- **固定位置候选的来源。** 若地图或标签带由目标行程的参考生成，留出只考察伪距阈值在该已知候选域内的迁移。要进一步考察未见道路，候选地图和标签边界应在目标轨迹前独立固定。缓冲区、地图外、没有足够健康测量及无法同步的历元分别计数。评估时查看参考只用于核对真标签与域条件。 [GEDVM 选择文档](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/docs/SELECTION.md) · [Google/ION 2022 路线隔离说明](https://www.ion.org/newsletter/upload/ION-Summer22-low.pdf) · [有限地图与缓冲区](gnss-route-verification-prior.md)

## 独立实测与统计先例

- Pervysheva、Nurmi 与 Lohan 在四类随身设备共 104 份 Android GNSS 日志上用最强的两颗卫星构造交通方式分类。第 II 节把同场景的所有设备归为一组，留出整个场景测试。按实际场景而非电话日志分割以及少星分类都已有实测。其预测器是学习型分类，研究目标是旅行方式。 [Pseudorange-Based Multi-Modal Transport Classification，第 II 节](https://trepo.tuni.fi/bitstream/handle/10024/234532/Pseudorange-Based_Multi-Modal_Transport_Classification_with_Raw_GNSS_Android_Data.pdf?isAllowed=y&sequence=-1)
- IEEE ITSC 2023 的 GNSS 非视距识别与不确定性预测从香港训练集迁移到亚琛，另在独立的杜塞尔多夫车载测量做故障排除。论文记录跨场景 C/N0 差异及模型性能下降。2024 年手机码伪距随机模型论文将修改后的 SIGMA-ɛ 方差函数用于外部 Google 实验集中的同型号 Xiaomi Mi 8 行驶记录，静态验证则来自同一拟合数据的切片。前者提供跨场景 GNSS 质量估计的先例，后者提供同机型跨采集源检验伪距噪声模型的先例。两者的输出是信号质量、连续定位或估计误差。 [GNSS 观测不确定性预测与外场迁移](https://pure.tudelft.nl/ws/portalfiles/portal/181613371/Learning-based_NLOS_Detection_and_Uncertainty_Prediction_of_GNSS_Observations_with_Transformer-Enhanced_LSTM_Network.pdf) · [Improving the Stochastic Model for Code Pseudorange Observations](https://doi.org/10.1007/s10291-024-01690-y)
- Google/ION 的手机分米挑战已经将训练、公开测试和私有测试按驾驶记录隔开。之后限制测试记录每次行程只有一部手机，路线变化也用于防止通过已知参考轨迹泄漏。Dunn、Wasserman 和 Ramdas 更一般地处理重复测量下的分层预测，指出不同组的观测不能直接自由交换。即使额外假设 GEDVM 三次行程可交换，每次留出一天也只有两个独立行程可作为校准。如果每行程用一个分数，普通 90% 拆分共形所需秩为 \(\lceil3\cdot0.9\rceil=3\)，超过两条校准分数。可报告按日和按设备的实测迁移，不能据大量相关历元把门槛说成 90% 分布无关覆盖。 [挑战赛组织方 2022 说明](https://www.ion.org/newsletter/upload/ION-Summer22-low.pdf) · [2023 组织方数据切分](https://www.ion.org/gnss/upload/Smartphone-Decimeter-Challenge-2023-2024.pdf) · [Distribution-Free Prediction Sets for Two-Layer Hierarchical Models](https://doi.org/10.1080/01621459.2022.2060112)

## 同预算对照

- 用相同数量的 GPS L1 码伪距和同样的可用星条件，对照 C/N0 排名前 \(k\) 颗，或使用预先固定的地图中心计算加权几何稀释度。后者的中心独立于被核验历元的真实位置。所有方法将只依赖星历、可见性及预先允许的质量字段的选星和实际读伪距时点记清楚。 [手机 C/N0 子集选择](https://doi.org/10.3390/s24082598) · [固定预算完整性选星](https://elib.dlr.de/106284/1/Satellite%20Selection%20Methodology%20for%20Horizontal%20Navigation%20and%20Integrity%20Algorithms.pdf)
- 固定所用卫星后，对照等宽合同及截尾加权最小二乘。后者按候选位置对共享钟差求最小残差，可枚举去除一星，再将同标签最小代价转成标签分数。校准与拒答规则使用同一批允许的源日志冻结，比较正确、错误和拒答数量。若使用先读齐所有候选伪距才发现坏星的算法，则单独报告为全输入参考。 [GNSS 伪距快照残差](https://skoge.folk.ntnu.no/prost/proceedings/ifac2008/data/papers/4184.pdf) · [截尾最小二乘及同预算对照](uwb-portfolio-calibration-prior.md)

有限检索已找到按场景留出、GNSS 误差及质量模型迁移、少星分类和同成本选星的原始先例。暂未定位到将同一可证的有限地图位置标签合同，在固定卫星预算下按日与手机迁移其误差或分离比值阈值的完整等价流程。实测支持的范围仍是三个同城日期的有限录像及对应地图。未读取或评分留出测量。
