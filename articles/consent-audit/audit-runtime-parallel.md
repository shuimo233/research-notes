
# 保持每题分数不变，CPU 推理该在哪一层并行？

在关闭空闲线程自旋的主实验中，分层调度加均衡任务把两轮 P95 从 **78.77、78.48 毫秒降到 47.64、47.70 毫秒**，平均调用次数约从 6.1 次降到 4 次。主门槛与新增目录门槛均通过。再用原有默认线程设置作对照时，均衡任务依然节省约三分之一的调用和约 18% 的配对中位耗时，**P95 只改善了 4.7% 和 2.1%，未过补充的 5% 门槛**。 [主试验冻结协议](https://github.com/shuimo233/research-notes/blob/a41a891508fe1dba59cacc227daae4e503940bde/articles/consent-audit/audit-runtime-parallel-protocol.md) · [默认设置的补充协议](https://github.com/shuimo233/research-notes/blob/1ee8d33f7e15f9d1fac9678d3fc4dfcf2cae6bda/articles/consent-audit/audit-runtime-parallel-defaults-protocol.md)

## 同一份推理输入，三种执行方式

档位先按原来已审计的规则确定。执行器只决定哪些行交给同一个调用。原有逐行补齐 Scan 保持每行的词元、掩码和档位不变。结果按原请求顺序回填。由此可以分别检验每项的输出语义、宽度调度与实际执行开销。只要答复或拒绝仍从同样的分数和原有规则产生，整窗归一拒绝率证书就继续适用。

- **算子内并行。** 按实际有效宽度分桶，顺序发起调用，每个调用用四线程 CPU 会话。
- **并行分桶。** 沿用相同的桶，由四个工作线程并发调用同一个单线程 CPU 会话。
- **均衡任务。** 将各行按有效宽度平方从大到小排入当前工作量最低的任务。至多四个任务，且任务数不超过现有桶数。任务内可以是不同宽度。

两种任务并行共用同一个单线程会话。主机一次只执行一个批次，任务全部退出后再处理结果或传播异常。主试验两份会话都关闭自旋。代码约束的是请求的执行图线程配置与并发调用数。耗时测量采用这台 AMD Ryzen 9 7845HX 主机上的 CPU 后端。 [执行器](audit_runtime_parallel.py) · [ONNX Runtime 线程与并发先例](audit-runtime-parallel-prior.md)

## 什么时候并行有效？

两轮分别回放 12 个目录、三个实况的逐项与分层路由。在同一路由内，三个执行方式收到完全相同的输入。总共 **6,912 项计时、165,888 个逐位一致的模型分数**。下面是同比较中实际观察的 P95。

| 路由与执行 | 第一轮 P95 | 第二轮 P95 |
| --- | ---: | ---: |
| 逐项，算子内并行 | 78.77 ms | 78.48 ms |
| 逐项，并行分桶 | 86.23 ms | 87.68 ms |
| 逐项，均衡任务 | 50.81 ms | 51.03 ms |
| 分层，算子内并行 | 76.63 ms | 72.56 ms |
| 分层，并行分桶 | 84.31 ms | 82.97 ms |
| 分层，均衡任务 | 47.64 ms | 47.70 ms |

只把原有桶并行提交，配对中位耗时下降，两轮 P95 却都高于同路由的算子内并行。均衡任务同时改变了任务分配和调用次数。保持逐项路由时，它将 P95 降低 35.5% 和 35.0%，说明在关闭自旋的主实验中，执行层的改变本身就有较大的尾部收益。端到端组合的进程累计 CPU 时间约为对照的 65%。它是本次进程时钟的汇总。

对实际任务布局做的补充穷举显示，2,304 次布局中有 2,294 次达到了平方工作量代理的最优峰值。其余布局的最大超出为 5.43%。这核准了代理模型中的分配效果。实际墙钟 P95 仍按前表测量。 [原始计时和任务](audit-runtime-parallel-trace.json.gz) · [复算汇总](audit-runtime-parallel-results.json) · [代理最优性复核](audit-runtime-parallel-oracle.json)

## 默认线程设置的独立进程复验

从上述目录固定六个，保留同一套分层输入，把原有默认四线程会话与均衡任务分别置于独立进程。两轮交换运行先后，检查全部 **27,648 个分数**。默认设置对照的 P95 为 49.89 和 49.30 毫秒，均衡任务为 47.56 和 48.27 毫秒。调用次数从约 5.95 降到 4.00，配对中位耗时比例约为 0.817。尾部改善存在于这两轮的测量值，严格的两轮 5% 门槛未满足。这个对照说明，实际部署估计应使用当前线程设置下的基线。 [补充计时](audit-runtime-parallel-defaults-trace.json.gz) · [补充汇总](audit-runtime-parallel-defaults-results.json)

跨实例并行、线程配置和最长任务优先都有明确先例。本次候选贡献是让已经核验的逐行推理与整窗行为合同贯穿并行执行，并在同一图、同一输入的实测中区分并行分桶与混合宽度任务的代价。基线设置、硬件和在线并发都会影响耗时。若超时或部分失败改变了拒绝规则，须另行给出行为证据。 [查新与适用边界](audit-runtime-parallel-prior.md)

## 复现

```bash
python -B audit_runtime_parallel_run.py selected.json audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz model-cache row-widths.onnx replay
python -I -B audit_runtime_parallel_check.py audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz replay
python -B audit_runtime_parallel_defaults.py selected.json audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz model-cache row-widths.onnx replay
python -B audit_runtime_parallel_defaults.py selected.json audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz model-cache row-widths.onnx replay --check
python -B audit_runtime_parallel_oracle.py audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz replay
```

选题、模型、逐行图和 CPU 软件依赖沿用已有方案。执行结果可逐位复核，纳秒计时随环境和负载变化。 [固定输入与构建方式](audit-runtime-latency.md#复算)
