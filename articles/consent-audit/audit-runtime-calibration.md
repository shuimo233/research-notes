# 用实测行成本降低审计推理的尾部耗时

在 AMD Ryzen 9 7845HX 主机上，同一组审计题、证据槽和掩码经过三种 CPU 执行方式，两轮共核对 82,944 个输出分数，逐位一致。用实测行成本分配并行任务后，与原四线程分桶执行相比，两轮的整批 P95 分别下降 20.6% 和 25.0%，模型调用次数少了约三分之一。随后在另六个目录上固定执行器做消融，保留贪心分配、只更换行成本，就已经通过预设的改善门槛。

## 实测成本与对照

逐行裁切的 INT8 ONNX 图允许一个调用内处理不同宽度的输入。旧调度用宽度平方估计每行工作量，按从重到轻的次序向最轻的任务组放置。实测策略在与评估分开的三个目录中，用相同的词元分别执行两行和四行，取每对 `(T4 − T2) / 2`，再取中位数。480 对计量覆盖主试验预先列出的 40 种宽度。输入表只用到评估题的宽度清单，计时和模型分数都来自独立校准目录。实测的每行成本从宽度 16 的 4.073 ms 变为宽度 128 的 27.981 ms，相差 6.87 倍，宽度平方的相应比例是 64 倍。该差值也包含随行数变化的主机准备开销。

精确分配在至多八行、四个任务组的范围内最小化最重一组的估计成本。线程争用和回填等开销由整批计时共同反映。主试验计入求解时间，其 P95 约为 0.143 ms。默认对照沿用原四线程会话及默认自旋行为，两种任务并行共用一个单线程会话和四个工作线程。主试验在两轮独立进程中反转执行臂顺序，旧贪心臂均居中。 [主试验冻结协议](https://github.com/shuimo233/research-notes/blob/6fb830889f0d743fffece12df1eea96eab87a8ed/articles/consent-audit/audit-runtime-calibration-protocol.md) · [校准表](audit-runtime-calibration-profile.json)

| 执行方式 | 第一轮整批 P95 | 第二轮整批 P95 |
| --- | ---: | ---: |
| 默认四线程分桶 | 55.168 ms | 55.130 ms |
| 宽度平方与贪心分配 | 49.861 ms | 48.794 ms |
| 实测行成本与精确分配 | 43.820 ms | 41.341 ms |

实测加精确的组合相对于同执行器的宽度平方贪心，两轮 P95 下降 12.1% 和 15.3%，两臂的模型调用数相同。主试验预先指定的六个新目录也通过门槛，其相对默认执行的 P95 分别下降 25.4% 和 29.9%。这部分检验已知宽度在另一组输入上的表现。 [汇总](audit-runtime-calibration-results.json) · [逐批记录](audit-runtime-calibration-trace.json.gz)

## 收益主要来自哪里

第二场在另外六个此前未计时的目录上，固定同一个逐行图和执行器，轮换四种组合的计时顺序。它复用已经冻结的成本表，对宽度 49、51、54、55 做相邻点插值。共记录 2,304 次整批计时，核对 55,296 个分数，全部逐位一致。

| 消融执行方式 | 第一轮整批 P95 | 第二轮整批 P95 |
| --- | ---: | ---: |
| 宽度平方与贪心分配 | 48.209 ms | 51.565 ms |
| 宽度平方与精确分配 | 49.136 ms | 52.349 ms |
| 实测行成本与贪心分配 | 40.869 ms | 45.602 ms |
| 实测行成本与精确分配 | 40.278 ms | 44.151 ms |

在贪心分配保持一致时，只换实测成本，两轮 P95 下降 15.2% 和 11.6%。固定实测成本，再加入精确求解，只多降了 1.4% 和 3.2%，两轮都低于预先要求的 5% 独立增益。宽度平方下，精确分配和贪心分配在两轮每个批次都生成了同一布局，计时有约 1.5% 到 1.9% 的波动。本实验支持将实测成本与贪心分配作为后续框架接入的优先候选。 [消融冻结协议](https://github.com/shuimo233/research-notes/blob/7c12445ec09178aab3c3bbbfe1424fc7d359463a/articles/consent-audit/audit-runtime-calibration-ablation-protocol.md) · [消融汇总](audit-runtime-calibration-ablation-results.json) · [逐批记录](audit-runtime-calibration-ablation-trace.json.gz)

## 可以主张的范围

Packrat 已把离线实测带入 CPU 推理的线程与子批配置，Liou 和 Hong 已用实测代价求精确的子批分配，AsymServe 已按输入长度和批大小离线测量 CPU 推理性能。本实验给出了特定逐行审计推理系统中的可复算证据，量化了边际成本替代宽度平方后的 P95 变化，以及精确分配在这组任务上的独立增益。这里的 P95 是单机逐批完成时间。在线排队、跨模型和不同处理器上的收益尚未验证，检索也未建立发表优先权。 [Packrat 原论文](https://proceedings.mlr.press/v267/bhardwaj25a.html) · [Liou 和 Hong 原论文](https://doi.org/10.1145/3672608.3707809) · [AsymServe 作者稿](https://wang-xinkai.github.io/files/xinkai_asymserve_appt2025.pdf) · [先例和方法边界](audit-runtime-calibration-prior.md)

## 复算与重新计时

在当前文章目录中运行。归档检查重新推导分配、分数摘要和计时统计。重跑主试验会在新目录产生一份成本表和计时。复跑已冻结成本表的消融时，继续传入仓库中的 `audit-runtime-calibration-profile.json`。重跑的纳秒时间随负载变化。 [固定输入、模型与构图步骤](audit-runtime-latency.md#复算)

```bash
python -I -B audit_runtime_calibration_check.py audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz .
python -B audit_runtime_calibration_boundary_check.py
python -B audit_runtime_calibration_ablation.py selected.json audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz audit-runtime-calibration-profile.json model-cache row-widths.onnx . --check

python -B audit_runtime_calibration_run.py selected.json audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz model-cache row-widths.onnx replay
python -B audit_runtime_calibration_ablation.py selected.json audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz audit-runtime-calibration-profile.json model-cache row-widths.onnx replay
```
