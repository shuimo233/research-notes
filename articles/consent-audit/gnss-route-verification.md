# 六颗卫星能否核验已知路线标签

本轮把公开城市峡谷轨迹写成一个有限检查点任务。给定多个已知位置，判断手机位于参考纬度的南侧还是北侧。参考线两边各保留 15 米拒答带，候选目录中共有 233 个检查点。每个位置允许任意一颗卫星出错，其余卫星共用同一个自由接收机钟差。先用候选几何和广播星历选择要读取的卫星，再用不同时间块的实测伪距校准和回放。 [原始伪距核验](gnss-clock-audit.md) · [冻结预案](gnss-route-verification-protocol.md)

## 实测结果

| 回放方法 | 每历元读数 | 南侧正确 / 106 | 北侧正确 / 10 | 误答 |
| --- | ---: | ---: | ---: | ---: |
| 按分离半径选六星，实测校准后核验 | 6 | 101 | 4 | 0 |
| 按仰角选六星，实测校准后核验 | 6 | 94 | 3 | 0 |
| 全星，实测校准后核验 | 中位数 11 | 0 | 0 | 0 |
| 主组六星，截尾最小二乘 | 6 | 106 | 10 | 0 |
| 仰角六星，RTKLIB FDE | 6 | 102 | 10 | 0 |

未答对且未误答的案例均为拒答。按分离半径选择的六星帮助多核验 8 个历元，留出历元的分离半径中位数为 21.31 米，仰角六星为 6.20 米。全星的中位分离半径为 23.19 米，但一颗坏星的假设无法涵盖全星读数的残差，校准出的需求比值大于 1，按预案全部拒答。只用六星的主法仍在北侧漏掉了 6 个检查点，且同预算截尾最小二乘答对了全部留出点，主效用门槛未通过。 [并列方法、阈值和门槛](gnss-route-verification-results.json)

即使直接使用每历元严格低于分离半径的最高容限，主组六星也只在北侧答对 6/10，仰角六星答对了 10/10。此诊断按预先冻结的规则计算，不作为经过校准的策略。它表明扩大模型内的分离半径不足以确保实测更易满足模型。南侧有 106 个留出位置，北侧只有 10 个，北侧结果不能从总体平均推断，也未在第二条路线复现。 [逐历元回放](gnss-route-verification-replay.json.gz)

## 计算分离半径以及它的反例

给定两个不同标签的候选位置，求每颗已读卫星在两位置的名义伪距差。要同时符合两种解释，每颗诚实卫星的差必须落在某一共享钟差差值的 $2e$ 以内，这里的 $e$ 是每颗好卫星的残差容限。两种解释各可吸收一个冲突，因此若买了 $n$ 颗星，至少要有 $n-2$ 个差值落在长度 $4e$ 的区间。排序后找覆盖 $n-2$ 个差值的最短连续窗口，就得到这个候选对第一次可以共用回复的容限。对所有南北位置对取最小值。临界点上记录具体的共用回复、两端钟差及坏星分配，所以判断能独立检查。

对每历元的所有六星子集都比较这一半径。固定的少数位置对给每个组合一个数学上界。上界已低于当前解或只能产生排在其后的并列解，即可跳过对该组合的全对遍历。233 个历元共有 135,367 种六星选择，只有 278 种实际需要遍历全部位置对。独立核验从每个区间下界出发计数可能保留的卫星，证明冻结组合的最优值，并检查 699 条临界共同回复、117 个校准历元和 116 个留出历元。 [几何选星记录](gnss-route-verification-design.json.gz) · [独立核验](gnss-route-verification-verification.json)

每个查询组合在校准历元上计算真位置所需容限与分离半径之比。主组六星按固定秩取出的比值约为 0.618，仰角六星约为 0.517，全星约为 2.306。比值低于 1 时，才允许把它乘上该历元的分离半径作为阈值。这个阈值保证有限候选在其测量合同内没有跨标签共同回复。时间块仍来自同一条轨迹，未验证交换性，也未估计现场无条件风险。 [校准规则和相关先例](gnss-route-verification-prior.md)

## 结论边界

最坏故障保护下的选星、直接从伪距比较道路候选和地理边界拒答均有已有研究。本轮可复核的候选贡献，是把精确跨标签分离上限用于六星选择，再独立检验这组卫星的实测需求能否落在上限内。结果限于这份档案及其有限候选定义，实测优势和首创性仍待确认。逻辑读数也不代表接收机射频能耗。 [相关原始研究](gnss-route-verification-prior.md)

## 复现

使用 Python 3.13、NumPy 2.2.6，以及 [上一轮固定版本的 RTKLIB 适配器和 TAUN 星历](gnss-clock-audit.md#复现)。从本目录执行以下各阶段。

```powershell
$exe = 'D:/path/to/gnss_clock_audit_rtk.exe'
$nav = 'D:/path/to/TAUN00FIN_R_20232230000_01D_MN.rnx'
python -B gnss_route_verification.py design gnss-clock-audit-fixture.json.gz $exe $nav output
python -B gnss_route_verification.py replay gnss-clock-audit-fixture.json.gz output/gnss-route-verification-design.json.gz $exe $nav output
python -B gnss_route_verification_check.py gnss-clock-audit-fixture.json.gz output/gnss-route-verification-design.json.gz output/gnss-route-verification-replay.json.gz output/gnss-route-verification-results.json $exe $nav
```
