# GNSS 的共享钟差能否接入可核验测量模型

UWB 实验发现，一个共享偏差不足以约束实测读数。GNSS 的接收机钟差有更明确的物理解释：同一接收机、同一测量历元、同一信号类型的伪距都受同一个接收机时间误差影响。本轮先从公开的城市峡谷手机日志重建 GPS L1 伪距，对照同次参考轨迹，并用 RTKLIB 和独立广播公式交叉核验。 [原始数据](https://zenodo.org/records/8340005) · [冻结接入口径](gnss-clock-audit-protocol.md)

## 接入结果

| 检查项 | 结果 |
| --- | ---: |
| 原始 GPS L1 行 | 6,659 |
| 通过物理与时钟状态筛选的历元 | 566 |
| 用 GNSS 测量时标配对的 RTK 固定解 | 240 |
| 配对时间差中位数 | 1 毫秒 |
| RTKLIB 返回有效点解 | 65 / 240 |
| 有效点解平面误差的中位数 / 第 90 百分位 | 3.45 / 12.23 米 |
| 真坐标处允许一颗坏星时所需逐星容限的中位数 / 第 90 百分位 | 23.16 / 54.48 米 |

以 250 毫秒为固定配对上限，从日志的 utcTimeMillis 字段只能配对 2 个固定解。按硬件接收时标、GPS 周与闰秒恢复测量 UTC 后，配对数为 240。测量时标比此日志字段晚的中位差为 439.5 毫秒。原始对照没有删除。只有 65 个历元通过 RTKLIB 单点定位的检验，其余 175 个历元记录卡方检查失败。误差分位只针对返回点解的历元。 [原始分组与统计](gnss-clock-audit-results.json) · [GNSS 记录格式](https://github.com/google/gps-measurement-tools/blob/master/LOGGING_FORMAT.md) · [GPST 与 UTC](https://maia.usno.navy.mil/information/eo-values)

真坐标处的诊断给每个历元一个自由的共享钟差，并允许丢弃一颗健康且仰角达到 5 度的卫星。剩下的伪距残差仍常常需要几十米的确定性容限。这个量合并了传播、多径、参考与其他残差，本轮没有逐项识别原因。RTK 输出的自身误差估计也不包含手机与背包天线的安装间距。 [实验采集与参考](https://www.mdpi.com/2079-9292/12/23/4781)

## 从时标到名义伪距

接收时刻由 TimeNanos、FullBiasNanos、BiasNanos 和 TimeOffsetNanos 恢复。先处理整数纳秒和周边界，再进行米制换算。本数据中通过筛选的 TimeOffsetNanos 都为零。原始日志保留多个星座和频率，本轮只用 GPS L1，并按硬件时钟历元以及卫星编号去重。 [Android 测量接口](https://developer.android.com/reference/android/location/GnssMeasurement) · [Google 的伪距说明](https://developer.android.google.cn/develop/sensors-and-location/sensors/gnss/downloads/gnss_analysis_tools_from_google.pdf)

生成候选位置的名义伪距时，从广播星历和候选坐标计算几何光行时，迭代得到发射时刻。采用 RTKLIB 的地球自转项、卫星钟、GPS L1 群延迟及广播大气修正。预测端不读手机的实测伪距，避免在选择查询源时提前得到其答复。独立程序复算全部 2,815 条入选伪距，并对抽取的 137 个卫星状态另写广播公式。与 RTKLIB 的 ECEF 位置最大差 0.365 毫米，钟差最大差不到百万分之一纳秒。这是对两个实现的数值一致性检验，未用精密轨道测量广播星历的真实误差。 [独立程序](gnss_clock_audit_check.py) · [数值核验](gnss-clock-audit-verification.json) · [RTKLIB v2.4.3-b34](https://github.com/tomojitakasu/RTKLIB/tree/180043ee24b6d2b168f98b64be15f69d50046b1a)

## 已有工作和这轮边界

Drevelle 和 Bonnifait 已用区间反演同时约束接收机位置和共享钟差，并允许一颗坏星。直接从伪距比较道路候选、使用卫星子集降低完整性监测开销也有明确先例。这个接入实验只建立可复核的原始输入以及标准定位对照。后续候选贡献要检验的是，用固定查询组合的跨结论重合半径对照实测需要的容限，能否在离散目标辨别中降低查询数并维持实际表现。这里的历元来自一段城市步行档案，结果不用于导航完整性或射频能耗推断。 [区间 GNSS 完整性先例](https://www.hds.utc.fr/~bonnif/pdf/2011_GPS_solution.pdf) · [完整先例对照](gnss-clock-audit-prior.md)

## 复现

从数据档案中提取 S2_dynamic_campus 下的 OnePlus 原始日志、配对的参考位置文件与当天 TAUN 星历。确切文件名和 SHA-256 在结果文件中。数据由 Antoine Grenier、Elena Simona Lohan、Aleksandr Ometov 和 Jari Nurmi 发布，按 CC BY 4.0 许可。结果附带入选记录及已计算的广播状态。 [数据发布页](https://zenodo.org/records/8340005) · [精简输入与逐历元输出](gnss-clock-audit-fixture.json.gz)

在 Windows 的 MinGW GCC 8.1 与 Python 3.13 下，令 RTK_SRC 表示已固定版本的 src 目录。PowerShell 中从本目录运行。

```powershell
$RTK_SRC = 'D:/path/to/RTKLIB/src'
$units = 'rtkcmn','rinex','ephemeris','pntpos','preceph','ionex','sbas' | ForEach-Object { Join-Path $RTK_SRC "$_.c" }
gcc -O2 -std=gnu99 -I $RTK_SRC gnss_clock_audit_rtk.c $units -o gnss_clock_audit_rtk.exe -lwinmm -lws2_32
$log = 'log_OnePlusNord2_20230811103018.txt'
$reference = 'NMND17420010S_2023-08-11_07-40-20.pos'
$navigation = 'TAUN00FIN_R_20232230000_01D_MN.rnx'
python -B gnss_clock_audit.py $log $reference $navigation gnss_clock_audit_rtk.exe output
python -B gnss_clock_audit_check.py $log $reference $navigation output/gnss-clock-audit-fixture.json.gz output/gnss-clock-audit-results.json
```
