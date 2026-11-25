# 逐行宽度执行与调度延迟的先例

## 单例分数是一个有必要核对的执行合同

ONNX 的 DynamicQuantizeLinear 用整个输入张量的极值计算量化尺度和零点。ONNX Runtime 项目中已有用户复现动态量化模型在批大小改变时给出不同预测，维护者指出不同批可以产生不同的尺度与零点。Kasa、Kasa 和 Negi 进一步在 CPU 动态 INT8 分类实验中固定批形状，仅改变同批样本，也观测到分数和标签变化，并用固定离线量化尺度的对照验证了机制。对于使用分数门槛的审计，标签一致还不足以确认门槛行为一致。 [ONNX 量化运算定义](https://onnx.ai/onnx/operators/onnx__DynamicQuantizeLinear.html) · [ORT 项目报告与讨论](https://github.com/microsoft/onnxruntime/issues/10111) · [Kasa 等预印本附录 B.11](https://arxiv.org/html/2610.09111v1)

ONNX Scan-11 已支持沿同一批轴并行索引多个扫描输入。无跨行状态时，可以让扫描体同时读取某行的令牌、掩码和最低宽度，先按该行的有效长度裁剪，再按它自己的最低宽度补齐，随后调用原单例图。仓库已有前两种扫描输入与固定宽度的导出器。本轮把最低宽度改为随行输入，复用原图和量化参数。规范给出了迭代和形状语义。不同编译器与后端的浮点位模式仍需用锁定的单例档案逐位核验。 [ONNX Scan-11 迭代语义](https://onnx.ai/onnx/operators/onnx__Scan.html#scan-11) · [已有逐行图与固定补齐宽度](pointwise.md) · [原始多档 SNLI 分数采集](audit-runtime-multiworld.md)

## 形状分桶和一次调用各有什么先例

Triton 默认按输入形状判断能否动态组批，其不规则批功能可把不同长的输入连成一维数据，并提供额外的批描述。Krell 等用屏蔽跨序列注意力的方式，在训练时打包不同长度的序列以减少填充。Thinking Machines 的批不变 GPU 内核工作则直接控制归约顺序，使生成推理的相关内核不随批形状或排布改变。这些先例确立了变长载荷、额外逐项元数据、隔离批内计算和测量实际性能的价值。当前要检验的是固定 CPU INT8 单例语义下，由审计调度选出的最低宽度怎样进入执行，以及同一逐行图按实际宽度多次调用或整批一次调用的差别。 [Triton 不规则批文档](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/ragged_batching.html) · [Krell 等序列打包原论文](https://arxiv.org/html/2107.02027v2) · [Thinking Machines 批不变内核实验](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)

ONNX Runtime 的性能文档区分图优化及其会话启动开销，并记录线程调度等因素可能带来的延迟方差。这里使用同一已加载会话和相同 CPU 执行配置，测到的是已就绪令牌进入执行、得到并恢复结果的时间。组内逐行运算依旧按各自有效宽度执行。一次调用能减少调用与独立准备张量的次数，分桶则可能减少主机端矩形输入需要填的令牌数。两种效应的量级要从计时确定。 [ORT 图优化文档](https://onnxruntime.ai/docs/performance/graph-optimizations) · [ORT 性能排查文档](https://onnxruntime.ai/docs/performance/tune-performance/troubleshooting.html)

## 平衡回放能固定什么

令第 \(i\) 项的有效宽度为 \(s_i=\max(\ell_i,W_i)\)，其中 \(\ell_i\) 为该行令牌数，\(W_i\) 为它抽到的宽度下限。若成本为逐行相加的 \(\sum_i c_i(W_i)\)，具有同样逐行边缘分布的任何调度，期望都等于 \(\sum_i \sum_w \Pr(W_i=w)c_i(w)\)。如果两个有限回放连每项每档的次数都相等，则这类成本在完整回放中的总量也精确相等。\(c_i=\max(\ell_i,W_i)\) 与 \(c_i=\max(\ell_i,W_i)^2\) 都满足这个条件。单批的总行宽、有效宽度种数和计时仍可不同。前两个尺度是执行结构的计数代理。

McKay、Beckman 和 Conover 的拉丁超立方抽样已有逐列通过随机排列实现均衡覆盖的先例。这里用有限的档位排列构造配平的回放，以隔离共同抽档改变的批内组合。每次排列内部的批间用档相依，不能把重复回放的所有批次当作彼此独立的线上样本。Mytkowicz 等证明系统测量设置本身能引入偏差，并提倡随机化。Google Benchmark 也支持交织重复。Kalibera 和 Jones 明确区分变化来自哪一层以及相应的不确定性。因此结果应保留重复、执行顺序和批次归属，对同一主机的实际差别作有范围的解释。 [McKay 等抽样原论文](https://www.stat.cmu.edu/technometrics/70-79/VOL-21-02/v2102239.pdf) · [Mytkowicz 等性能测量原论文](https://sape.inf.usi.ch/publications/asplos09.html) · [Google Benchmark 随机交织文档](https://github.com/google/benchmark/blob/main/docs/random_interleaving.md) · [Kalibera 与 Jones 分层计时原论文](https://kar.kent.ac.uk/33611/45/p63-kaliber.pdf)

## 实际分桶种数的期望可以直接推导

对某个实际宽度 \(t\)，一行在共同档位 \(W\) 下进入该宽度的事件，由该行长度 \(\ell_i\) 决定。若 \(\ell_i<t\)，事件是 \(W=t\)。若 \(\ell_i=t\)，事件是 \(W\leq t\)。若 \(\ell_i>t\)，事件为空。它们相互嵌套。令 \(p_i(t)\) 为对应事件的概率，同组共享一次抽签时，该组占用 \(t\) 的概率是 \(\max_i p_i(t)\)。逐行独立的概率是 \(1-\prod_i[1-p_i(t)]\)，至少一样大。组间独立时，可以把各组未占用 \(t\) 的概率相乘。由此每个实际宽度的出现概率在共享方案下都不会增加，期望实际宽度种数及非负固定分桶开销的期望也不会增加。独立分支与共享分支混合仍保留这一不等式。

这个推导适用于固定的行长、同一档位分布和按实际宽度分桶的规则。它约束的是跨抽样的期望。有限配平回放的组间共现仍会随排列变动，实测耗时还取决于数据复制、缓存、分派和内核执行。

## 同样的总工作量仍可有不同的尾部

同组共享一个有序档位，且每行成本随档位不降时，组内的成本具有共单调结构。既有定理表明，在固定边缘下，共单调耦合使求和成本在凸序中最大。这一结论约束凸风险指标，单个分位数的变化方向仍取决于分布。取两行各耗费 \(1\) 或 \(3\) 个时间单位，高成本概率为 \(p\)。完全独立时，合计成本 \(2,4,6\) 的概率是 \((1-p)^2,2p(1-p),p^2\)。改为一半概率独立、一半共用抽签时，概率是 \((1-p)^2/2+(1-p)/2,p(1-p),p^2/2+p/2\)。当 \(p=1/10\) 时，上述规则令第 95 百分位从 \(4\) 升至 \(6\)，而均值相同。当 \(p=3/100\) 时，第 95 百分位从 \(4\) 降至 \(2\)。这是一项解析对照，用来解释为什么同时报告中位数与高分位。 [Kaas 等固定边缘下和的凸序原论文](https://jandhaene.org/wp-content/uploads/2025/10/2002-kaas-dhaene-vyncke-goovaerts-denuit.pdf)

## 查新与证据边界

已找到批设置改变量化分数、多输入扫描、变长批处理、分层计时和平衡抽样的直接先例。当前候选增量是在已核验的多实况归一拒绝调度上，明确保留逐题选档，通过第三个扫描输入回放原单例位模式，并用同一主机、严格逐题配平的档位轨迹比较两条执行路径。查检范围包括已有 CPU INT8 分类论文、官方算子及服务文档、变长打包论文和性能实验方法。尚未在这些资料中定位到相同的审计合同与执行对照，现有检索不足以确定发表优先权。

本轮性能证据适用于给定图、数据、预先选择的档位、运行库和硬件。线上排队、到达过程、跨服务开销、吞吐目标和峰值资源需要独立测量。MLPerf Inference 明确以负载发生器的提交时间和答复到达定义时延，并有各场景的到达过程与测试要求，可作为今后定义线上验收口径的参照。 [MLPerf Inference 场景与时延规则](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc#51-loadgen-operation)
