# 先选要读的锚点，再检验它们能支撑多大的误差

真实测量需要的容限，与设备还能区分结论的容限，是两个独立的量。上一轮把全部锚点纳入测距合同，绝大多数留出位置未通过。本轮先用旧校准数据选择实际会查询的锚点，再独立校准已冻结的组合。新位置分为校准和测试两组。比较对象包括全锚合同以及同一锚点组合上的截尾最小二乘。 [冻结规则](uwb-portfolio-calibration-protocol.md) · [读取新测距前冻结的锚点与评分](uwb-portfolio-calibration-design.json) · [上一轮实测](uwb-heldout-calibration.md)

## 实测结果

| 环境 | 冻结查询数 | 新校准与留出位置 | 首次跨标签重合 | 新校准要求的容限 | 在安全上限下的正确结论 | 同预算截尾最小二乘 |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| environment0 | 5 | 16 / 15 | 143.25 毫米 | 415.50 毫米 | 4/15 | 15/15 |
| environment2 | 6 | 21 / 20 | 504.00 毫米 | 874.00 毫米 | 15/20 | 20/20 |

精简档案覆盖 88 个此前未使用的位置，排除参考线附近的位置后有 37 个用于新校准、35 个用于留出评分。两个冻结组合的校准要求均越过可分离上限，主规则据此全部拒答。表中的安全上限表现是按预先声明的诊断，将容限设为低于冲突半径的最大四分之一毫米刻度，剩余位置均拒答。在相同诊断下，全锚合同分别答对 0/15 和 13/20。删去部分来源确实提高了给定故障条件下的可用性，但两个组合仍未达到实用门槛。同预算截尾最小二乘对这 35 个留出点均给出正确标签。该结果是一次有限档案回放，样本覆盖和风险无法外推到现场。 [逐案数据](uwb-portfolio-calibration-results.json)

独立检验逐一枚举删锚和闭区间交集，复算了 318 个候选组合、377,301 个位置对半径和 4 条临界共同回复。另以独立的截尾平方目标复算新校准分数和全部留出结论。 [核验汇总](uwb-portfolio-calibration-verification.json)

## 怎样知道安全容限在哪里结束

对两个目标标签不同的候选位置，把每个所购锚的预测值相减，再把这些差值排序。设两位置分别允许一个任意坏锚。若双方可以产生相同回复，最多两个锚可由双方的故障解释吸收。其余差值都必须落在某个偏差差值 $d$ 的 $2e$ 以内，其中 $e$ 是每条诚实测量的残差容限。$d$ 必须在两个允许偏差区间相减得到的 $[L,U]$ 中。

对至少保留 $n-2$ 个差值的一个连续窗口，记最小值和最大值为 $a,b$。让所有这些诚实回复可以重合所需的最小容限等于
\[
\max\!\left(\frac{b-a}{4},\frac{b-U}{2},\frac{L-a}{2}\right).
\]
这是求同时满足 $b-2e\le d\le a+2e$ 和 $L\le d\le U$ 的最小 $e$。在所有保留窗口中取最小，再在所有反标签位置对中取最小，就得到组合的冲突半径。上界是闭的，恰在这个半径处已经能构造共同回复。求解器记录两个候选位置、两边实际偏差、逐锚回复及各自的故障位置。只有严格低于该半径的容限才保证相反标签不会同时被接受。

对真位置的一次实测，类似地计算允许删去一个坏锚时的最小残差容限。这个数来自读数，冲突半径来自候选几何和故障口径。用独立新校准位置取固定次序统计量，比较读数需要的容限能否低于冲突半径。两者不兼容时，该规程拒答。次序统计量沿用了拆分共形校准的秩，空间位置的交换性没有验证，档案回放不提供分布无关的覆盖保证。 [拆分共形预测的覆盖条件](https://www.stat.berkeley.edu/~ryantibs/papers/conformal-jasa.pdf)

## 对照怎么保持相同的测量成本

同预算对照读取完全相同的锚点，在同样的候选几何与偏差范围下，枚举一个可能受污染的来源，然后拟合使剩余平方误差最小的偏差。每个标签取其候选中最小的损失，减去全候选最小损失后得到非负分数。用同一批新校准位置和相同校准秩冻结阈值。若两标签都过阈值，或都没有通过，就拒答。两种方法均由真位置所属一侧的参考标签评分。 [估计、采购与留出校准的先例](uwb-portfolio-calibration-prior.md)

精确分离、容错传感器选择和选址后的独立校准均有先例。这里可复核的研究对象，是给每组已购锚点计算可构造反例的分离上限，再比较实测需要的容限。本次检索尚未确认这一组合判据的优先性，实测对照也未显示相对已有稳健估计的实际优势。 [原始研究与等价结果](uwb-portfolio-calibration-prior.md)

## 复现

随文提供的精简档案来自 Klemen Bregar 等人发布的 UWB Positioning and Tracking Data Set v2，按 CC BY 4.0 许可。测量字段含原始成员的 CRC 和 SHA-256。读数只来自上轮未使用过的目录，排除了已知的先导位置。评分是固定离散检查点的逻辑查询数，不测量设备延迟。实验环境为 Python 3.13、NetworkX 3.6.1 和 SciPy 1.16.3。 [Zenodo 源数据](https://zenodo.org/records/8280736) · [新位置观测](uwb-portfolio-calibration-observations.json.gz) · [逐位置结果](uwb-portfolio-calibration-results.json) · [独立核验](uwb-portfolio-calibration-verification.json)

```text
python -B uwb_portfolio_calibration.py design uwb-heldout-calibration-observations.json.gz design.json
python -B uwb_portfolio_calibration.py replay design.json uwb-portfolio-calibration-observations.json.gz replay.json
python -B uwb_portfolio_calibration_check.py uwb-heldout-calibration-observations.json.gz design.json uwb-portfolio-calibration-observations.json.gz replay.json
```

如从 Zenodo 重建新量程数字，选址必须先冻结。抓取器校验 ZIP64 响应区间和成员 CRC，只读所需字节区间。

```text
python -B uwb_portfolio_calibration_fetch.py uwb-heldout-calibration-observations.json.gz design.json range-cache uwb-portfolio-calibration-observations.json.gz
```
