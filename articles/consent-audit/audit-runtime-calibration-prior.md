# 实测行成本与精确分批的先例

## 最接近的工作

Bhardwaj 等的 Packrat 已用离线实测的线程数与批大小时延表，在 CPU 推理中联合选择模型实例数、实例内线程数和各实例处理的子批大小。论文在 TorchServe 中验证了从算子内并行转向多实例并行可能降低时延。对应专利公开说明了以独立运行的实测表作动态规划输入，也明确指出并行实例的共享资源争用会使实际时延偏离这个表上的最优解。离线测量、选取分批方案和并发后的偏差都有直接先例。 [Packrat 原论文](https://proceedings.mlr.press/v267/bhardwaj25a.html) · [专利公开 WO2025042537A1，第 0036–0039 段](https://patents.google.com/patent/WO2025042537A1/en)

Liou 和 Hong 在多核推理加速器上，先实测子批大小和分配核数的代价，再用动态规划选各子批及核心配额，目的是缩短动态批推理时间。Wang 等的 AsymServe 已离线记录 CPU 上 LLM 的分桶性能，特征包括模型、执行阶段、输入长度、批大小及资源配置，并将测量用于在线调度。两者分别覆盖了以实测代价求动态批划分，以及按长度与批大小建立 CPU 推理性能表。 [Liou 和 Hong 原论文](https://doi.org/10.1145/3672608.3707809) · [作者提供的论文](https://homepage.iis.sinica.edu.tw/papers/dyhong/new-7534-F.pdf) · [AsymServe 作者稿，第 5 节](https://wang-xinkai.github.io/files/xinkai_asymserve_appt2025.pdf)

TVM 已用实机测量反馈训练算子程序的代价模型。Ansor 用实机运行高分候选程序，把测得的时间反馈到模型，并安排编译搜索预算。ONNX Runtime 自身也提供可指定序列长度、批大小和线程数的 Transformer 性能测试，以及逐节点时间的分析器。本轮直接计量包含张量构造和图调用的整段，固定模型图、CPU 执行提供器和单线程配置。 [TVM 原论文](https://www.usenix.org/conference/osdi18/presentation/chen) · [Ansor 原论文，第 5–6 节](https://www.usenix.org/system/files/osdi20-zheng.pdf) · [ONNX Runtime Transformer 性能工具](https://onnxruntime.ai/docs/performance/transformers-optimization.html) · [本轮运行脚本](audit_runtime_calibration_run.py)

## 两种批大小的实测含义

对有效宽度 \(w\)，在同一个单线程 CPU 会话中重复同一校准输入，分别执行 2 行和 4 行。序列在两次调用中的词元、掩码和最低宽度一致。令 \(T_k(w)\) 表示此条件下处理 \(k\) 行的时钟时间。如果这段范围近似满足 \(T_k(w)=B(w)+kC(w)\)，差值 \((T_4(w)-T_2(w))/2\) 抵消共同的调用成本 \(B(w)\)，估计增加一行的成本 \(C(w)\)。实际按校准项和重复次数取得成对差值的中位数，并轮换先运行哪种行数。差值仍包含随行数增长的主机准备和数组处理，也可能受分配策略、缓存状态、输入组成及计时漂移影响。用同一词元重复测量是为了控制这一实验中的输入差异，混合宽度任务中的共享外层输入形状仍可能改变主机成本。 [ONNX Scan 规范](https://onnx.ai/onnx/operators/onnx__Scan.html) · [本轮校准协议](audit-runtime-calibration-protocol.md) · [模型调用实现](audit_runtime_pack.py) · [Mytkowicz 等关于测量偏差的实验](https://sape.inf.usi.ch/publications/asplos09.html)

校准分数来自预先指定的校准目录的词元和时钟，比较组的标签、模型分数和时钟均不参与拟合。比较组的有效宽度清单在计时前已知，并用于决定直接计量哪些宽度。这可以检验已知宽度、不同输入上的计时表现。对尚未出现的宽度、其他模型、执行提供器和机器，协议中的插值或端点取值仍需独立验证。 [本轮校准协议](audit-runtime-calibration-protocol.md) · [校准与比较检查器](audit_runtime_calibration_check.py)

## 精确目标与实测目标

把每行的正整数代价视为可加、处理线程视为等价时，固定 \(m\) 个任务组的目标是让最重组的代价最小。这是同质并行机的完工跨度问题 \(P\|C_{\max}\)。经典最长处理时间优先规则提供近似解。Dell’Amico 等已经给出精确算法，Korf 和 Schreiber 专门研究了至多七台同质并行机的精确调度。当前上限是八行、四组，使用可行容量与小规模搜索来精确求出代价表上的最优值。边界检查在小规模问题中枚举划分，实测检查器对每批调用独立的求解实现核对最优值。 [Graham 原论文](https://doi.org/10.1137/0117039) · [Dell’Amico 等原论文](https://pubsonline.informs.org/doi/abs/10.1287/ijoc.1070.0246) · [Korf 和 Schreiber 原论文](https://doi.org/10.1609/icaps.v23i1.13544) · [求解实现](audit_runtime_calibration.py) · [边界检查](audit_runtime_calibration_boundary_check.py) · [实测检查器](audit_runtime_calibration_check.py)

实测 P95 来自多线程完成整批并按原顺序回填的计时。提交、分组求解、共享缓存与内存带宽、线程唤醒和会话配置都会影响结果。任务组数沿用已有宽度平方策略的上限，两种并行臂比较的是更换代价表与求解算法的合计影响。把影响分别归给代价表和求解算法，需要固定其中一项后再比较。相对于默认四线程会话的比较还包含线程配置与调用数量的变化。两轮独立进程的顺序反转提供时间漂移检查，宽度平方臂均居中，所以机器波动仍可能影响比较。在线队列到达、超时与流量的 P95 另有测量条件。 [Packrat 专利公开，第 0039 段](https://patents.google.com/patent/WO2025042537A1/en) · [ONNX Runtime 线程与自旋设置](https://onnxruntime.ai/docs/performance/tune-performance/threading.html) · [Clockwork 原论文](https://www.usenix.org/conference/osdi20/presentation/gujarati) · [本轮校准协议](audit-runtime-calibration-protocol.md)

## 可归因的研究问题

检索覆盖了 CPU 子批配置、按长度分桶计量、实机算子代价、同质机精确划分，以及 ONNX Runtime 中量化模型的长度感知执行。已找到的论文支持这些组成部分。此轮可以检验的窄问题是，在现有的逐行 INT8 `Scan` 审计边界内，2 行与 4 行成对测出的分宽度边际成本，加上精确最小化最重任务的代价，能否比宽度平方的启发式和默认线程分桶给出更合适的实测方案。比较还需要在同一请求、掩码和档位下逐位复核分数，并按原槽位回填。这样才能把它视为既有审计决策的执行替换。有限检索只能确认已核对的重合与差异，发表优先权和其他系统的收益仍未建立。 [既有并行实验查新与语义边界](audit-runtime-parallel-prior.md) · [本轮校准协议](audit-runtime-calibration-protocol.md)
