
# 推理档位的占比变了，只查最极端的分布够吗？

一组真实 MoNLI 模型输出给出了精确反例。八档等概率时，允许共用档位的比例为 **50%**。逐一核查允许分布的全部顶点，会把它降到 **45.65%**。最坏分布把可变份额分到两种档位，整个集合的精确上限进一步降到 **42.11%**。重新计算原始门控和概率表都能得到这个结果。 [真实门控的解析证明](audit-runtime-drift-prior.md#第-1044-个真实门控表可直接求出全局最坏比例)

## 保留档位比例之间的关系

沿用上一轮真实模型分数和参考标签门控。每项可能独立选档，也可能和同目录其他项共用一档。两条路的选档分布都为 \(w\)。本轮假定 \(w=3u/4+v/4\)，其中 \(u\) 为八档等权分布，\(v\) 是任意八档分布。等价地，每档有至少 \(3/32\) 的概率，概率总和为一。该条件可以由调度器执行。本轮的四分之一是预先规定的压力幅度。 [冻结协议](https://github.com/shuimo233/research-notes/blob/dbb206c63c038a5d1f6665a73659fec574800bc2/articles/consent-audit/audit-runtime-drift-protocol.md) · [前一轮的真实模型分数和门控](audit-runtime.md)

给定 \(w\)，各实况在窗口内的全拒绝概率，是独立路的 \(a_X(w)\) 和共用路的 \(b_X(w)\) 按共享比例 \(\lambda\) 的混合。\(a_X\) 是逐项拒绝率的乘积，\(b_X\) 是先在每档内做乘积、再按档位概率加权。令 \(d_X(w)=b_X(w)/a_X(w)-1\)。和原审计一样，正向归一倍率比不超过 \(B=21/20\) 等价于 \(\lambda[d_P(w)-B d_Q(w)]\le B-1\)，反向交换两侧。要求所有窗口、两个方向和所有允许分布都成立。

在某个窗口里，两档若对两实况的相关请求有完全相同的条件拒绝率，可以把它们合成一档，所有概率以两档总质量进入计算。合并后的可变份额仍能遍历完整单纯形，因为每类的份额都可以赋给其中任一原档。与档位无关的请求也从归一倍率中消去。这两步可减少需要处理的窗口和分布维度。

## 每个上限都有两种证据

对子单纯形中的分布，把方括号中的量写成有理函数 \(N/D\)。分母由正的逐项率构成。把分子分母统一到相同齐次次数后，\(N/D\) 是各个对应系数之比的加权平均，权重非负。因此最大的系数比给出子单纯形上的上界。综合覆盖全部允许分布的子单纯形，可以为共享比例发出安全下端。代入具体允许分布则能证实超过多少会失败，给出上端。计算预算耗尽时仍保留当前夹逼。

证书记录分割和反例分布。独立程序从原分数还原条件拒绝率，重新建立全部窗口、归并档位、计算有理系数并核查分割覆盖。系数界和单纯形分割采用已有的有理 Bernstein 方法。 [原理、先例与查新边界](audit-runtime-drift-prior.md) · [优化器](audit_runtime_drift.py) · [独立检查器](audit_runtime_drift_check.py)

## 冻结对照

| 目录 | 配置总数 | 等权上限遇漂移会超标 | 只查顶点的上限会超标 | 安全下端比逐项分别取界更高 |
| --- | ---: | ---: | ---: | ---: |
| 主目录 | 1,254 | 55 | 8 | 57 |
| 旧分数聚集的压力目录 | 1,254 | 124 | 12 | 126 |

超标数只计入有可行反例见证的配置。2,508 个配置全部达到 **0.1 个百分点**的预设夹逼宽度，其中 2,468 个上下端完全一致。主目录最多分割 7 次，压力目录最多 15 次。主目录的 57 个有联合效应的配置，每个窗口最多需要区分 5 类档位。主目录里等权上限偏差最大的一项从 **50% 降到 16.49%**，稳健结果两端相等；把有关概率分别取界只允许约 **1.71%**。

第 1044 项由两项请求决定，第二项只在宽度 64 时拒绝率低，第四项只在宽度 96 或 128 时拒绝率低。精确最坏分布把四分之一可变质量按 \(11/16\) 和 \(5/16\) 分给这两类档位，使两类总质量相等。该解析复算是在冻结后针对已出现的反例所做的补充。 [完整结果](audit-runtime-drift-results.json) · [逐例夹逼](audit-runtime-drift-policies.json.gz) · [真实门控输入示例](audit-runtime-drift-example.json)

## 复现

```bash
python -B audit_runtime_drift.py audit-runtime-drift-example.json > evidence.json
python -I -B audit_runtime_drift_check.py audit-runtime-drift-example.json evidence.json --contract
python -B audit_runtime_drift_run.py audit-runtime-logits.tsv audit-runtime-policies.json.gz replay
python -I -B audit_runtime_drift_check.py audit-runtime-logits.tsv audit-runtime-policies.json.gz replay
python -B audit_runtime_drift_boundary_check.py audit-runtime-logits.tsv audit-runtime-policies.json.gz audit-runtime-drift-example.json
```

计算与核验仅用 Python 标准库。原模型行为来自固定的真实分数，档位漂移集合和标签核验规则由实验指定。此保证针对这份集合内的归一全拒绝赔率。实际部署需有稳定的条件拒绝行为、可核对的选档分布约束和独立的答案验证器。线上比例、耗时和其他观察事件并未测量。
