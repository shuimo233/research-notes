# 三星证书能否跨日期成立？

冻结地图和误差尺度后，用另一日期的 Pixel 5 走测验证。只要三星读数排除了另一类便作答，两类仍相容才加读第四星。212 个历元中，这个规则答对 70 例、拒答 142 例，始终只读三星。相同三星的加权和非加权截尾最小二乘都答对 212 例。预定的 5,088 次软件单读数扰动也未使最小二乘误判。实验未通过预先规定的效用和故障门槛。 [冻结预案](gnss-prefix-verification-protocol.md) · [主结果](gnss-prefix-verification-result.json)

## 全局保证和单例证据

对于任意两个异类候选，三星允许双方各把一个不同的读数解释成坏星，剩下的一条可由自由钟差对齐。由此能构造跨类共同回复，所以任何固定三星名单都无法保证处理每一份合约内回复。同一名单在具体一例仍可能排除另一类。给定一个候选位置，把每条观测变成一段可能的钟差区间，保留至少两段有公共点即可。两个标签各自搜索全部同类位置，恰一类可行才作答。

读第四星时仍允许一颗坏星，因此四星的可行集合包含于前三星的可行集合。如果四星支持真实标签，三星独占一个标签时该标签必为真实标签。若地图或误差模型已排除真实标签，条件不成立。实验中的地图和容差有限，允许用真实参考轨迹在评分后审计这些前提。

## 外部留出

校准和候选位置两者都来自 2022 年轨迹，2023 年的参考位置只用于评分和诊断。目录有 170 个历史点，按 10 秒划块取点。留出有 120 个南侧历元、92 个北侧历元，另有一个进入保护带、一个缺少足够可用星，没有 15–60 米近边界的入选点。以一颗星的伪距为单位计算读取成本。三个前缀星号来自同一套四星几何设计。

| 方法 | 原始留出正确 / 212 | 软件扰动正确 / 5,088 | 两组错误 |
| --- | ---: | ---: | ---: |
| 先读三星，必要时加读第四星 | 70 | 1,754 | 0 |
| 固定三星证书 | 70 | 1,754 | 0 |
| 固定四星证书 | 9 | 244 | 0 |
| 同名单固定三星，截尾最小二乘 | 212 | 5,088 | 0 |
| 同名单固定四星，截尾最小二乘 | 212 | 5,088 | 0 |

扰动逐个替换四星名单中的一个读数，加上 ±5、±10、±20 米，其余读数来自原始日志。每个幅度、方向和星号都计入。没有足够证据支持对真实故障率或更大故障的结论。S4 回看中能构造跨越最小二乘判别边界的读数，只能说明这种反例在其模型下存在。预定的 PE1 扰动给出了不同的实用结果。

### 校准外失配

保持四星名单、观测、权重与尺度不变，事后只换同标签候选位置。170 点历史图支持真实标签 9/212。改用 1,695 个未稀疏历史参考点，增加到 63/212。给诊断程序直接提供每例 2023 年真实位置，170/212 满足合同。真实位置到原来同类地图最近点的三维距离中位数为 93.15 米。稀疏或不同日期的路线覆盖产生了显著失配，直接用真位置时仍有 42 例超出误差模型。地图分辨率、路线变化和误差都需区分，现有诊断没有逐案分解最后两种因素。 [事后诊断数据](gnss-prefix-verification-compatibility.json) · [诊断代码](gnss_prefix_verification_diagnose.py)

## 先例与复现

有界误差集合、容许若干异常 GPS 观测、用地图约束定位、对模棱两可的路线结果拒答和按成本顺序获取特征已有先例。这次复核保留了可明确验证的三星前缀与四星条件。它在真正分开的日期上的覆盖不足，且未超过同预算强对照，因此未达到原创实用成果的门槛。 [有界误差定位](https://www.hds.utc.fr/~bonnif/pdf/2011_GPS_solution.pdf) · [地图匹配完整性](https://www.hds.utc.fr/~bonnif/pdf/2008_JITS.pdf) · [伪距快照道路监测](https://skoge.folk.ntnu.no/prost/proceedings/ifac2008/data/papers/4184.pdf) · [顺序特征获取综述](https://ijcai.org/proceedings/2026/860)

按 [时钟审计](gnss-clock-audit.md) 构建 RTKLIB 预测器，配置 Python 3.13 和 NumPy，从 [数据包](https://github.com/taroz/gsdc2023) 按 [校验清单](gnss-prefix-verification-sources.json) 提取两个 Pixel 5 日志、参考轨迹与导航文件。在文章所在目录运行。

```powershell
$train = 'dataset_2023/train/2022-01-26-20-02-us-ca-mtv-pe1'
$test = 'dataset_2023/train/2023-05-09-21-32-us-ca-mtv-pe1'
$manifest = 'gnss-prefix-verification-sources.json'
$exe = 'gnss_clock_audit_rtk.exe'
$out = 'pe1-output'
$plan = "$out/gnss-prefix-verification-design.json.gz"
python -B gnss_prefix_verification.py design $train $test $manifest $exe $plan
python -B gnss_prefix_verification.py replay $train $test $manifest $plan $out
python -B gnss_prefix_verification_check.py $train $test $manifest $plan "$out/gnss-prefix-verification-rows.json.gz" "$out/gnss-prefix-verification-result.json"
python -B gnss_prefix_verification_diagnose.py $train $test $manifest $exe $plan $out
```

独立核验以区间交集复查 69,559 种四星组合，以成对差平方和复算截尾损失，逐案核对 212 例原始结果和 5,088 次软件扰动。从冻结提交解出源码后重跑，设计、逐例输出和汇总的 SHA-256 均一致。 [冻结选星提交](https://github.com/shuimo233/research-notes/commit/a86367e711756926cdba299eaf7f4c2e4f7c9f35) · [逐例结果](gnss-prefix-verification-rows.json.gz) · [独立核验](gnss-prefix-verification-check.json)
