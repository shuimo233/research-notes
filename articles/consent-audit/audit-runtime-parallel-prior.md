# 同一推理语义下切换 CPU 并行层级的先例

## CPU 推理并行的直接先例

Bhardwaj、Phanishayee、Narayanan 和 Stutsman 的 Packrat 已经在固定 CPU 预算下比较了算子内并行和跨模型实例并行。它实测了算子内线程扩展的收益递减，在 TorchServe 中根据模型、批大小和线程预算选择实例数、实例内线程数和分批方式，支持在线重配置。它确立了把线程移到任务层可能改善时延这一结果。当前实验是在一个批次内把已选好宽度的请求拆成并行调用，两种并行执行方式向同一单线程 ONNX Runtime 会话提交任务。维持逐行位模式与请求路由的拒绝率合同是另外的约束。 [Packrat 原论文](https://proceedings.mlr.press/v267/bhardwaj25a.html)

Triton 文档已经给出形状感知组批和不规则批输入，Krell 等也研究过把不同长度的序列打包并保留序列间的计算隔离。Clockwork 对推理执行时间和端到端排队行为分别建模，在线服务的尾部还取决于到达过程和调度。本次比较的三个方式都使用现成的逐行补齐图。测量从已就绪的词元与档位开始，到整批结果按请求顺序返回为止。 [Triton 不规则批文档](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/ragged_batching.html) · [Krell 等序列打包原论文](https://arxiv.org/abs/2107.02027) · [Clockwork 原论文](https://www.usenix.org/conference/osdi20/presentation/gujarati) · [先前逐行宽度实验](audit-runtime-latency.md)

## 共享会话与线程设置

ONNX Runtime 将 intra-op 定义为同一算子内部的计算并行。显式设为四时，这一总额包括调用线程。顺序执行模式由图内按依赖关系执行的路径决定。同一个会话的不同推理调用是否能重叠，由执行提供器等配置决定。维护者在同模型、多线程的讨论里明确支持在一个会话上并发调用 Run。v1.25.1 的会话实现查询各提供器的并发能力，并在有不支持并发的提供器时为图执行加会话锁。该版本常规 Python Run 绑定在原生推理期间释放解释器锁。数组构造、提交和回填等 Python 主机路径仍有自身开销。 [官方线程文档](https://onnxruntime.ai/docs/performance/tune-performance/threading.html) · [维护者对并发会话的答复](https://github.com/microsoft/onnxruntime/issues/20599) · [v1.25.1 会话实现](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/core/session/inference_session.cc) · [v1.25.1 Python 绑定](https://github.com/microsoft/onnxruntime/blob/v1.25.1/onnxruntime/python/onnxruntime_pybind_state.cc)

本次固定 CPUExecutionProvider、ONNX Runtime 1.25.1、顺序执行和 inter-op 为一。算子内方式用一个 intra-op 为四的会话，其余两种方式用同一个 intra-op 为一的会话和至多四个工作线程。两个会话均显式关闭线程池自旋。关闭自旋会改变空闲成本和唤醒延迟，所以单独配对测量当前设置下的对照，历史默认设置的纳秒记录仅作背景。四线程是执行配置，操作系统对物理核心的分配、主机准备工作和 CPU 时间通过实验范围和记录另行交代。 [官方线程与自旋设置](https://onnxruntime.ai/docs/performance/tune-performance/threading.html#thread-spinning-behavior) · [锁定版本的发布文件](https://pypi.org/project/onnxruntime/1.25.1/) · [冻结协议](audit-runtime-parallel-protocol.md)

## 按有效宽度平方安排任务

令第 \(i\) 项的有效宽度为 \(s_i=\max(\ell_i,W_i)\)。同宽度桶保持原有任务划分。均衡方式将每行视为一个权重为 \(s_i^2\) 的任务，从最长项开始依次放入当前累计权重最少的一组，并使用固定平手顺序。组数至多为四，也至多为该批不同有效宽度的数量，所以实际调用次数受原分桶次数约束。Graham 已证明，在同质处理器、独立任务、已知处理时长和目标为完工跨度的模型下，最长处理时间优先有 \(4/3-1/(3m)\) 的近似界，\(m\) 为处理器数。本实验的平方权重是固定调度代理。这个界可以用于该代理的理想分组模型，无法由它推出实际执行的 P95。按任务发起调用还有张量构造、复制、队列、共享缓存和同步等成本，必须实测。 [Graham 原论文，定理 2](https://doi.org/10.1137/0117039) · [已有宽度计数与实际延迟的对照](audit-runtime-histogram.md)

## 输出与行为核验的边界

组批保持数学形式也仍需核验实际数值。ONNX 的动态线性量化用输入张量的极值计算尺度。项目中已有批大小改变分数的复现，Kasa 等也考察了同形状但不同批内容的 CPU 动态 INT8 影响。本次复用无跨行状态的 Scan，每行按自身最低宽度执行原单例计算。改变线程、任务和组装顺序后，每个臂仍对照相同请求、词元、掩码及档位的冻结分数逐位核验。 [ONNX 量化运算定义](https://onnx.ai/onnx/operators/onnx__DynamicQuantizeLinear.html) · [ORT 项目复现](https://github.com/microsoft/onnxruntime/issues/10111) · [Kasa 等预印本](https://arxiv.org/abs/2610.09111) · [ONNX Scan 规范](https://onnx.ai/onnx/operators/onnx__Scan.html)

固定一批输入与抽到的完整档位向量后，若各请求的分数逐位相同，既有固定规则从分数得到的通过、拒绝等结果也逐项相同。由于整批档位的联合分布沿用原来已审计的调度，可以逐个档位向量比较，再对同一分布取期望，从而保留原来的整窗拒绝概率保证。这个推导要求完整结果回填，且决策规则沿用原有输入。若在线超时、取消、部分故障、背压或完成顺序直接改变拒绝行为，需要将这些事件纳入新的测量和合同。CPU 执行变快也不足以推出其他机器或在线队列的 P95。 [原多实况证书](audit-runtime-multiworld-prior.md) · [分层调度的概率保证](audit-runtime-strata-prior.md) · [Mytkowicz 等计时偏差原论文](https://sape.inf.usi.ch/publications/asplos09.html)

在核对的先例中，CPU 并行层级调整、单会话并发、形状打包和最长任务优先均有明确依据。当前候选增量是保持已审计 INT8 逐行宽度语义的可验证执行替换，并用逐题相同输入分别量化同宽度桶并行和按估计工作量合并调用的效果。有限查新仍不足以确定发表优先权。
