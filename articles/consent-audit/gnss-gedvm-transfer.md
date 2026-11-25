# 加权六星在新日期与新手机上能否复现

上一轮用逐星载噪比设定诚实误差容限，在芬兰 Hervanta 的一条留出步行路线得到 29/34 个可核验的正确结论。这里用 GEDVM 发布的六份完整卡尔加里驾车日志。每次留出一天的一部手机，只用另外两天的另一种型号校准。这样同次行程的伴随手机及任何同型号记录都不会进入该次校准。 [冻结预案](gnss-gedvm-transfer-protocol.md) · [上一轮](gnss-quality-verification.md) · [GEDVM 原始发布](https://github.com/YangRiverJiang/gedvm_dataset/tree/e2966fb40f89f009a4cc6c5282f2decdb1fe7035)

## 跨日、跨型号的实测结果

| 留出记录 | 加权六星 | 同组六星的截尾最小二乘 | 主要门槛 |
| --- | ---: | ---: | --- |
| 第一次行程 Pixel 5 | 89/89 | 89/89 | 未通过 |
| 第一次行程 Pixel 7 Pro | 89/89 | 89/89 | 未通过 |
| 第二次行程 Pixel 5 | 70/70 | 70/70 | 通过 |
| 第二次行程 Pixel 7 Pro | 68/70 | 70/70 | 未通过 |
| 第三次行程 Pixel 5 | 5/42 | 42/42 | 未通过 |
| 第三次行程 Pixel 7 Pro | 4/40 | 40/40 | 未通过 |

按其他两天、另一型号校准后，主法答对 325/400，零误答。几何六星答对 333，仰角六星 339，C/N0 六星 331，全星 332。同组六星的截尾最小二乘答对 400/400。精确六星组合合计比全星少读 1,309 次，同组六星对照也享有这项读数节省。相对几何六星，整体验证未呈现正确率优势。只有第二次行程的 Pixel 5 端通过所有预设细项，因此跨行程主门槛未通过。 [逐记录结果](gnss-gedvm-transfer-results.json)

用完全冻结的芬兰 S3 阈值直接迁移，加权方法答对了 400/400，零误答。诊断中各采购的最大安全阈值也都可答对这 400 个已知位置。这意味着卡尔加里再校准产生的拒答不能全归因于缺乏几何分离。第三次行程的两部手机拿到的归一化阈值约为 0.035，两个早期行程的宽分离尺度将比值压低。例如 Pixel 5 的逐星需求双倍尺度中位数在第一次和第三次行程分别为 5.59 和 5.65，临界双倍尺度却从 608.26 变为 83.39。直接迁移得到的满分主要来自远离边界的位置，距边界 15–60 米的留出点只有四个。现有结果不足以推断密集路线边界、其他日期或现场覆盖率。 [精确回放记录](gnss-gedvm-transfer-results.json.gz)

共构造 402 个参考检查点，其中两个历元无法形成共同采购库存，评分保留 400 个。独立核验从原档案复算 3,846 条入选伪距、78,493 个六星组合、2,000 条临界共同回复与全部校准来源。 [独立核验](gnss-gedvm-transfer-verification.json) · [冻结的几何与输入](gnss-gedvm-transfer-data)

## 输入如何核验

六份 ZIP 和六份参考数据与作者公布的 SHA-256 一致。Pixel 5 和 Pixel 7 Pro 可能在不同小数秒采样。解码先用整数 GPS 周和纳秒恢复实际接收时间，在相邻的手机专属 ECEF 参考点之间插值，只在参考间隔不超过 1.05 秒时接受。drive02 的当地采集日与原始 GPS 日跨界。使用实际导航日 256 的 NOAA 文件，不用文件名日期推断同一时刻。留出分组仍是作者的三个原始行程。 [作者时间对齐](https://github.com/YangRiverJiang/gedvm_dataset/blob/e2966fb40f89f009a4cc6c5282f2decdb1fe7035/docs/TIME_ALIGNMENT.md) · [NOAA 广播星历](https://geodesy.noaa.gov/CORS/data/#ephemeris) · [输入程序](gnss_gedvm_transfer_inputs.py)

每个日期的南北边界从两部手机的完整参考轨迹定义。每部手机在 15 米拒答带外每分钟最多取一个实际对齐历元。候选目录由这些离散参考位置构成，同样提供给主方法和对照。选星时只读取几何、星历及允许的库存质量元数据。六星选择使用上一轮公开的有理数临界值计算器，基线仍包括同组六星上的截尾最小二乘。每种采购单独冻结校准秩。另重放芬兰 S3 的旧阈值，以比较阈值直接搬移和档案内再校准。 [计算与分组实现](gnss_gedvm_transfer.py)

## 适用范围

同一行程的两部手机共享道路与观测环境。三天是主要的采集分组，时序历元不能当作独立样本。即使三个行程可交换，留一天也只有两个独立的校准行程，普通 90% 拆分秩无法给出有限行程级阈值。这里只报告实测回放。已知候选目录来自参考轨迹，因此也没有检验地图遗漏或未见道路。先例已有整场景留出、联合输出分离和手机信号质量建模。项目所增加的可复核对象是同一加权误差合同的精确采购与不同日期及机型的阈值迁移对照。 [原始研究与口径对照](gnss-gedvm-transfer-prior.md)

## 复现

固定运行环境是 Python 3.13、NumPy 2.2.6 和 [RTKLIB 适配器](gnss-clock-audit.md#复现)。将三天解压后的 NOAA NAV 文件放入 nav 目录。源仓库可以用 Git 稀疏克隆取得元数据，必须切换到固定提交；抓取器通过官方 API 续取完整档案及参考并验证作者哈希。

```powershell
$source = 'D:/path/to/pinned-gedvm'
$nav = 'D:/path/to/noaa-nav'
$exe = 'D:/path/to/gnss_clock_audit_rtk.exe'
python -B gnss_gedvm_transfer_inputs.py fetch $source full
python -B gnss_gedvm_transfer_inputs.py prepare $source full $nav fixtures
foreach ($f in Get-ChildItem fixtures -Filter '*-fixture.json.gz') {
  $name = $f.Name.Replace('-fixture.json.gz','-design.json.gz')
  python -B gnss_gedvm_transfer.py design $f.FullName $exe $nav (Join-Path 'designs' $name)
}
$prior = 'gnss-quality-verification-s3-results.json'
python -B gnss_gedvm_transfer.py replay fixtures designs $prior replay.json
python -B gnss_gedvm_transfer_check.py $source full $nav fixtures designs $prior replay.json
```
