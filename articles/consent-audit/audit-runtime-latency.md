
# 分组用的档位更少，实际推理会更快吗？

这次测到的是明确的取舍。分组把每批实际有效宽度数从约 **6.1 降到 4.7**，配对中位耗时只小幅下降，**P95 耗时却增加了约 37% 到 48%**。把所有行打包成一次调用后，尾部效应仍然存在。四项比较都没有通过预先登记的延迟收益门槛。 [冻结协议](https://github.com/shuimo233/research-notes/blob/e0b85eaac04cbb559d8cebfc6f3f87de851006e4/articles/consent-audit/audit-runtime-latency-protocol.md)

## 先保证执行的仍是原来的推理

给前一轮的 ONNX 单例 Scan 增加第三个输入流，随每行传入最小补齐宽度。循环体只截取该行有效前缀，再补到该行选定的宽度。独立结构核验从循环体恢复了源模型的 **732 个运算节点和 184 个参数张量**，均与源图一致。

同一份 CPU 会话能按有效宽度分桶调用，也能整批只调用一次并传入各行宽度。对上轮 SNLI 的 1,440 个方向和八档混合输入，**34,560 个分数都与冻结的单独执行结果逐位一致**。两种执行方式的全部实测批次也会逐项对照分数。 [导出与调用接口](audit_runtime_pack.py) · [图结构检查](audit_runtime_pack_check.py) · [原始 SNLI 分数](audit-runtime-multiworld-logits.tsv)

## 用逐题档位完全配平的重放测耗时

对六个固定目录和三个实况做两轮，每种调度在每轮对每题恰好采用每档两次。前半轮还逐批复用完全相同的分配，后半才比较逐项抽档与认证分组。四种执行方式轮换先后顺序，固定同一个四线程 CPU 会话。2,304 项计时含数组准备、参数核验、执行和结果回填。模型载入、分词与预热都在计时前完成。

表中比较值低于 1 表示更快。中位数使用同一批次的时间之比，再对相应轮取中位。P95 分别在两种执行方式中计算后取比。

| 对比 | 两轮配对中位数比 | 两轮 P95 比 |
| --- | ---: | ---: |
| 分桶调用内，分组相对逐项 | 0.979 / 0.987 | 1.403 / 1.457 |
| 单次打包内，分组相对逐项 | 0.996 / 0.988 | 1.368 / 1.484 |
| 逐项调度下，单次打包相对分桶 | 0.976 / 0.979 | 0.999 / 0.986 |
| 分组调度下，单次打包相对分桶 | 0.990 / 0.989 | 0.974 / 1.005 |

逐题配平使两种调度每轮的有效宽度和、平方和完全相同。差别在于这些计算分布在哪些批次。批内有效宽度总和的 P95，两轮分别从 **648、634** 变成 **920、960**。长档位更常在同一批出现，与计时中的尾部变化方向一致。前半轮的逐批输入完全一样，配对时间比的中位数都在 1% 以内。这里只在一台 Windows CPU 主机计时，配对结果不外推为其他机器、在线队列或并发配置的延迟保证。 [原始纳秒记录](audit-runtime-latency-trace.json.gz) · [全部汇总](audit-runtime-latency-results.json) · [核验脚本](audit_runtime_latency_check.py)

## 能从计算量推断什么

每项档位的边缘相同，则任意按项相加的确定性工作成本有相同的期望。这个事实也能精确核对有限回放中的总工作。共享档位改变的是这些工作量之间的相关性。即使均值不变，尾部分位也可以改变。

实际有效宽度的启动成本可以单独计算。给定目标宽度 \(t\)，同组各请求在一次共同抽签中达到 \(t\) 的事件彼此嵌套。所以共用一档后，该组命中 \(t\) 的概率等于组内最大的单项命中概率。与分开抽签相比，任何非负的按不同有效宽度计的启动成本，其期望都不会因合并组而增加。但独立的两个合规分区未必能通过依次合并联系起来。一个四项路径冲突的精确例子中，两组时平均有 \(7/4\) 个有效宽度，另一个三组方案只需 \(3/2\) 个。最少分组的证书针对组数。 [概率推导与相关先例](audit-runtime-latency-prior.md) · [精确算例](audit_runtime_latency_load.py)

计时完成后，做了一个补充的尾部约束计算。对各实况分别要求有效宽度总和与平方和的 P95 均不高于逐项独立基线。固定分组和共同档位分布时，任一阈值的超限概率都是共享比例的仿射函数，可直接算出允许上限。六个目录的原分组因此只能共用 **不到 0.009%** 的批次。在每次最多共用一对的细分方案中，最宽松的一项也只有 **0.072%**，期望有效宽度数少于基线的幅度小于每批 **0.00024 种**。这是精确的计算量代理约束，实验未对该补充方案重新计时。 [补充计算结果](audit-runtime-latency-load.json)

## 复算

```bash
uv run --no-project --with onnx==1.19.1 --with numpy==2.3.3 python -B audit_runtime_pack.py model-cache/onnx/model_quantized.onnx row-widths.onnx
uv run --no-project --with onnx==1.19.1 --with numpy==2.3.3 python -I -B audit_runtime_pack_check.py model-cache/onnx/model_quantized.onnx row-widths.onnx
python -B audit_runtime_latency.py selected.json audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz model-cache row-widths.onnx replay
python -I -B audit_runtime_latency_check.py audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz replay
python -B audit_runtime_latency_load.py audit-runtime-multiworld-logits.tsv audit-runtime-multiworld-policies.json.gz
```

用上轮的固定 SNLI 流程准备 selected.json。实际运行使用 ONNX Runtime 1.25.1 CPU、NumPy 2.2.6、tokenizers 0.23.1。运行脚本加 --semantic-only 可只复核逐位语义。重新测量的墙钟时间会变，独立脚本可用已发布的原始记录重算本次报告。 [前一轮的数据准备流程](audit-runtime-multiworld.md#复现)
