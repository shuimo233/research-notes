
# 同一批里，哪些请求可以共用推理档位？

以真正采集的 MoNLI 模型分数为输入，新的分组调度在 **54 个主实验配置**里比上一轮整批共用策略更省配置，同时在任意共同档位分布下把归一偏差压到零。另有 3 个配置仍是旧策略更省，1,197 个成本相同。新程序为每个目录输出实际可用的分组和一个证明组数最少的请求集合。 [冻结协议](https://github.com/shuimo233/research-notes/blob/26da9557b979462c2bc473cceea20bb0a6cdb94c/articles/consent-audit/audit-runtime-partition-protocol.md)

## 一条可以在调度前检查的规则

先给每项保留完整的档位分布 \(w\)。一半批次按原来方式逐项独立抽档，另一半依预先固定的分区，在每组里共抽一次，组和组之间独立。调用时不输入哪个实况成立。每项抽到各档的概率保持原值，独立路也保留了原完整概率表的一半。

先处理一对请求。若它们共用档位时，存在某个 \(w\) 让两实况的归一全拒绝行为不一致，就在这两项之间画一条冲突边。若固定混合的分区中有一部分把它们放到同组，二项归一差恰等于这部分的概率乘以共用档位时的差异。于是存在冲突的两项不能在任何有正概率的分区里共组。

反过来，对这里的有限档位条件概率表，**一个组里每对都兼容，足以保证组内任意窗口兼容**。对任一实况，把一个请求对各档的正拒绝率看成一个向量。稳定向量从归一比中消去。两项都随档位变化时，二项归一倍率是齐次有理函数，分母是两项边缘率的线性函数之积。正的条件拒绝率保证两个分母因子都无法约掉。若两个实况的二项函数对所有 \(w\) 相同，多项式唯一分解就要求它们的两个向量分别成比例，允许交换位置。任一窗口的所有兼容对因此确定了它在两侧的非恒定向量多重集，整窗归一倍率也相同。不同组的倍率相乘，固定分区的混合则保留等式。 [完整证明与适用范围](audit-runtime-partition-prior.md)

## 最少分几组可以直接算

向量按比例归类。仅在实况一变化的请求两两冲突，仅在实况二变化的请求也一样。可以给这两类各取一项组成一组。两个实况向量成比例的请求可以共成一组。对于两侧都变化、向量又不成比例的请求，只有配对的向量类型恰好互换时才能共组。一直稳定的请求可以放入任一组。

因此只需按这几类做匹配。每个互斥类别选出较长一侧，再把各类别的见证合起来，就得到与组数相同的两两冲突请求集合。这也证明不能再少一组。配置种数的期望随独立抽档次数增加，最少分组同时给出这种调度策略中最小的期望配置种数。证明允许任意正的条件拒绝率向量，档位分布取值要包含单纯形中的一个相对开集。 [分组实现](audit_runtime_partition.py) · [独立冲突检查器](audit_runtime_partition_check.py)

## 预先登记的对照

比较的成本是等权时一次批处理涉及的不同预设档位的期望种数。旧整批策略允许 5% 的归一偏差，且只需在上轮的漂移集合里满足限制。新策略要求在任意共同档位分布下保持归一倍率相等。

| 目录 | 配置数 | 新分组更省 | 旧策略更省 | 相同 |
| --- | ---: | ---: | ---: | ---: |
| 主目录 | 1,254 | 54 | 3 | 1,197 |
| 旧分数聚集的压力目录 | 1,254 | 99 | 27 | 1,128 |

主目录中差距最大的一项，预计每批从 **3.266 种降至 2.593 种**。上轮第 1168 项也从 **2.930 降至 2.593 种**。第 1044 项体现另一种取舍，旧策略只需 2.338 种，新分组需要 2.593 种，但可以对整个档位单纯形保证归一一致。 [全部比较](audit-runtime-partition-results.json) · [逐例分区与下界](audit-runtime-partition-policies.json.gz)

对事先固定的第 1044 和 1168 项，使用等权与偏移档位分布，各重放三种调度。288 个批次共发出 2,304 次实际 ONNX 调用，全部 6,912 个模型分数的位模式与既有冻结档案一致。独立检查器又从种子复算了每个选档、辅助抽签和拒绝位。效能比较使用精确期望，执行试验核对实现。预设档位种数没有换算成耗时。 [运行程序](audit_runtime_partition_live.py) · [运行记录](audit-runtime-partition-live.json.gz) · [执行检查器](audit_runtime_partition_live_check.py)

已有共同随机数、按冲突图排批以及配置感知的模型推理。这里的具体候选贡献，是从两个实况的整窗概率合同推导出精确的二项冲突图，直接得到可运行的最优分组和下界见证。模型分数来自已固定的实际执行，答案合法性由参考标注核对。部署需要自己的答案验证器，并要保证不同组确实独立选档。证书覆盖全拒绝事件的归一倍率，真实赔率仍受两个实况单项率差异影响。 [查新](audit-runtime-partition-prior.md)

## 复算

```bash
python -B audit_runtime_partition.py audit-runtime-drift-example.json
python -B audit_runtime_partition_run.py audit-runtime-logits.tsv audit-runtime-policies.json.gz audit-runtime-drift-policies.json.gz replay
python -I -B audit_runtime_partition_check.py audit-runtime-logits.tsv audit-runtime-policies.json.gz audit-runtime-drift-policies.json.gz replay
python -B audit_runtime_partition_boundary_check.py
python -B audit_runtime_partition_live.py audit-runtime-logits.tsv audit-runtime-policies.json.gz audit-runtime-drift-policies.json.gz replay/audit-runtime-partition-policies.json.gz monli-data model-cache replay/audit-runtime-partition-live.json.gz
python -I -B audit_runtime_partition_live_check.py audit-runtime-logits.tsv audit-runtime-policies.json.gz audit-runtime-drift-policies.json.gz replay
```

分组和证书使用 Python 3.13 标准库。实际模型重放依赖固定的 MoNLI、模型和分词器文件，以及沿用的 CPU ONNX 环境。模型位置、下载和依赖版本见前一轮。 [固定输入的取得方式](audit-runtime.md#复算)
