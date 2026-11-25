
# 两实况的分组，加入第三个实况后还成立吗？

在新的 SNLI 测试中，直接沿用两实况分组，在 360 个预先登记的配置里有 **35 个出现归一全拒绝不一致**。其中 31 个需要增加组数，另外 4 个只需重新分组。多实况仍能用二项证据核验整批，但最优性证书随实况数而变。五个实况已经足以构造一个必须分三组的例子，其中任意两两冲突的请求集合最多只有两项。 [冻结协议](https://github.com/shuimo233/research-notes/blob/b872d661bdb63a1f50c486d3754309c2ede96d3a/articles/consent-audit/audit-runtime-multiworld-protocol.md)

## 整批保证仍可从二项推出

保留每项原有的档位分布。每批一半概率逐项独立抽档，其余按固定分区组内共抽一次、组间独立。任意两个实况都可以单独应用前一轮的二项充分性证明，因此每组的每一对请求若在所有实况间都兼容，整个分区的所有窗口也兼容。若某对存在冲突，它在任何以正概率采用的分区里都必须分开。

进一步看每项的活跃集合，即它的条件拒绝率会随档位改变的实况。

- 两项各自在部分实况中活跃时，有共同活跃实况便冲突。没有交集时，两项可以共组。
- 在每个实况都活跃的请求，与部分活跃的请求必须分组。全活跃请求之间若各自的比例类在实况间保持一致，可以同时共组。比例类发生变化时，只有恰好两种不同类型且处处互换的请求可以成对共组。
- 在任何实况都稳定的请求可以放入任一组。

这给出一个可以直接计算的分解。活跃集合只有一个实况的请求先拿掉。给定当前组数 \(k\)，其余请求占用了这个实况的多少组，恰等于还有多少个请求在该实况活跃。单点请求只需补到空余的组里。加回它们后，部分活跃请求所需的最少组数，是余下核心的最少组数与各实况总活跃数中的最大值。 [概率证明与分组结构](audit-runtime-multiworld-prior.md)

## 五个实况出现的边界

当实况不超过五个，核心的活跃集合都至少有两个元素，所以每组最多容纳两项核心请求。给两个不相交的集合连一条兼容边，最大匹配能配成尽可能多的两项组。匹配给出实际分组，奇分量与相应删除集合给出可独立验算的下界。

四个以内的实况总能用两两冲突集合证出最优值。五环则可以由恰好五个实况实现。每个实况只激活五环的一条边的两个端点，活跃项的两档拒绝率设为 \(1/4,3/4\)，其余项恒为 \(1/2\)。于是冲突图恰是五环。其最大团为二项，余下核心的兼容图也是五环，最大匹配配成两对，第三组不可省。这是团下界首次可能偏松的实况数。

实况数随输入增长时，一般图的每条边可以用一个实况表达，再加入全稳定实况，便把图着色嵌入该调度问题。这里采用的是已知的集合相交表示、图着色困难性和最大匹配。候选贡献是从归一全拒绝条件推导出这些精确结构，以及四到五个实况时最优性证书必须改变的边界。 [五环输入](audit-runtime-multiworld-example.json) · [查新与证明](audit-runtime-multiworld-prior.md)

## 在另一套真实推理题上复验

从固定 SNLI 测试集取 480 个同时有蕴含、中立和矛盾三个标注的前提。每八个前提组成一个目录，共 60 个。每个标注取最早一条，并用前提的哈希把三个方向分给三个实况。使用此前固定的 CPU INT8 DistilBERT 模型，对 1,440 个句对按八档执行，记录 34,560 个 float32 分数。六档分差门槛共得到 360 个配置。门控使用三分类参考标注作为实验验证。 [SNLI 原论文](https://aclanthology.org/D15-1075/) · [固定数据](https://huggingface.co/datasets/stanfordnlp/snli/blob/cdb5c3d5eed6ead6e5a341c8e56e669bb666725b/plain_text/test-00000-of-00001.parquet) · [实际模型分数](audit-runtime-multiworld-logits.tsv)

| 比较 | 配置数 |
| --- | ---: |
| 两实况分组在第三实况有确切反例 | 35 / 360 |
| 加入第三实况后必须增加组数 | 31 / 360 |
| 精确方法比保守规则更少分组 | 0 / 360 |
| 精确分组比逐项独立抽档省配置 | 360 / 360 |

在第 34 号目录的零分差门槛配置里，旧分组共用一个档位。第一和第五项在两个原实况的归一倍率均为 1，在第三个实况为 \(13931/8342\)，约 1.67。这里的档位分布只将四分之一的可变份额移入一个预设档位。新分组把这两项拆开，所有窗口通过核验。真实样本中，精确规则与保守规则给出的组数相同，新增收益来自重新核对实况范围。 [逐例分组、反例及最优性证书](audit-runtime-multiworld-policies.json.gz) · [完整结果](audit-runtime-multiworld-results.json)

采集使用参考标注核准回答。部署仍需要可靠的答案验证器、同一个档位分布和条件独立的执行规则。给出的保证只覆盖全拒绝事件的归一倍率，实测延迟仍缺数据。 [工具实现](audit_runtime_multiworld.py) · [独立检查器](audit_runtime_multiworld_check.py)

## 复现

```bash
python -B audit_runtime_multiworld_run.py audit-runtime-multiworld-logits.tsv replay
python -I -B audit_runtime_multiworld_check.py audit-runtime-multiworld-logits.tsv replay
python -B audit_runtime_multiworld.py audit-runtime-multiworld-example.json
python -B audit_runtime_multiworld_boundary_check.py audit-runtime-multiworld-example.json
uv run --no-project --with duckdb==1.4.3 python -B audit_runtime_multiworld_infer.py prepare snli-test.parquet selected.json --fetch
python -B audit_runtime_multiworld_infer.py infer selected.json model-cache new-logits.tsv --fetch
```

SNLI 三实况重放和独立核验只用 Python 3.13 标准库。有非平凡匹配的最优化分支沿用 NetworkX 3.6.1。当核心允许三项共组，求解器可用活动类型计数动态规划，计算量随实况与类型数量增长。实际推理沿用 NumPy 2.2.6、tokenizers 0.23.1 与 ONNX Runtime 1.25.1 CPU。选题步骤以固定 Parquet 摘要和原始行号为准。
