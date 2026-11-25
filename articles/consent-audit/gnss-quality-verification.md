# 把逐星读数质量纳入可核验的 GPS 选星

上一轮按几何分离半径选星，在已公开路线的北侧仍频繁拒答。本轮给每颗卫星不同的诚实读数容限，在同一误差合同下比较四种六星采购和全星采购。S2 只用于诊断。S3 使用另一部手机与另一条步行路线。预案、时间对齐补充及两条路线的组合均在评分前提交。 [预案](gnss-quality-verification-protocol.md) · [上一轮](gnss-route-verification.md) · [评分前冻结的组合](https://github.com/shuimo233/research-notes/commit/873b61c429ff2716c04818769fde695f723b2817)

## 独立路线结果

| S3 方法 | 南侧正确 / 24 | 北侧正确 / 10 | 错误 |
| --- | ---: | ---: | ---: |
| 按加权分离尺度选六星 | 20 | 9 | 0 |
| 同一合同内使用未加权几何六星 | 0 | 0 | 0 |
| 同一合同内使用仰角六星 | 0 | 0 | 0 |
| 同一合同内使用载噪比最高的六星 | 0 | 0 | 0 |
| 同一合同内读取全星 | 0 | 0 | 0 |
| 主法所选六星上的截尾最小二乘 | 24 | 10 | 0 |

其余案例均拒答。加权组合的实测校准秩为临界尺度的 0.926 倍，未加权几何、仰角、载噪比及全星各自校准后均超过 1，触发统一的拒答规则。S3 的 34 个留出历元中，33 个比读全星少读，合计少 101 次逻辑查询，另一个历元本来就只有六颗合格星。预设的逐案省一星门槛和强基线门槛均未通过。截尾最小二乘与主法读取同一组卫星，它在本次留出回放中答对全部位置。 [S3 分项数据与门槛](gnss-quality-verification-s3-results.json)

S2 的加权组答对南侧 101/106 和北侧 9/10，零误答。已知路线原始未加权主法的北侧结果是 4/10。只按载噪比选六星、沿用本轮加权合同的简化对照，在 S2 多答对一个南侧历元，北侧相同。这个诊断与 S3 的结果一并保留，避免把一次轨迹内的改进当成普遍收益。 [S2 诊断](gnss-quality-verification-s2-results.json) · [上轮未经加权的实测](gnss-route-verification.md)

## 从逐星误差容限到共同回复

预案根据 C/N0 给每颗星取正权重 $w_i$。对于一个异标签位置对，记第 $i$ 星的两个名义中心之差为 $d_i$。在公共误差尺度 $q$ 下，若双方该星都诚实，两种钟差的差值必须在闭区间 $[d_i-2qw_i,d_i+2qw_i]$ 内。在某个允许保留的集合 $J$ 上，第一次产生公共点的尺度是
\[
q_J=\max_{i,j\in J}\frac{|d_i-d_j|}{2(w_i+w_j)} .
\]
理由是最大下界不能超过最小上界，所以每对区间必须相交。一维闭区间的成对相交与全部相交等价。通过对允许删两星的保留集取最小，再对异标签位置对取最小，得到紧的分离边界。对于实测真位置的支持尺度，只删一星，并去掉公式分母中的系数 2。权重不同后，删星后的最短保留集合可能不连续，等宽区间的排序窗口不再适用。 [数学和测量先例](gnss-quality-verification-prior.md)

实现把每历元的有理数比较压成精确整数顺序。若分母最大为 $D$，两个不同有理数之差至少为 $1/D^2$。将分数乘 $D^2+1$ 后向下取整，必然保留严格大小与并列关系。若整数乘积超界，程序拒绝继续。临界值和共同回复以分数保存，独立核验直接计算闭区间相交，不使用该压缩。两条路线一共独立检查了 144,552 种六星组合和 1,495 条临界共同回复。 [选星代码](gnss_quality_verification.py) · [独立核验程序](gnss_quality_verification_check.py)

## S3 输入和查新边界

S3 手机的 GPS 测量历元通常在整秒后约 0.42 秒，原 250 毫秒近邻规则无法合格配对。补充规则只在分别为 RTK 固定解、相隔不大于一秒的相邻位置间插值，不跨浮点解、不外推。获得 865 个历元，其中 66 个检查点按冻结时序采样进入主要试验。独立程序从原始日志复算 8,041 条进入接入样本的伪距，核对每个插值端点。留出位置来自同一条 S3 路线，不能据此声称分布无关覆盖。C/N0 假设在请求具体伪距前可获得，这里的查询数没有转换为硬件能耗。 [原始数据](https://zenodo.org/records/8340005) · [S3 独立核验](gnss-quality-verification-s3-verification.json)

GNSS 中按每颗星的信号质量设置检测区间、容忍粗差和按质量选星均已有直接先例。有限查新尚未找到把精确加权跨标签重合边界用于固定预算选择、再以独立实测校准对照的完整等价流程。本轮验证了这一组合在一条新路线中的条件性收益。对更强实测基线的优势及优先性仍未确认。 [主要先例及其他可复核数据源](gnss-quality-verification-prior.md)

## 复现

数据来自 Antoine Grenier 等人公开的 Hervanta 档案，许可为 CC BY 4.0。S3 手机原始文件、参考文件和导航文件的 SHA-256 保存在 [精简数据](gnss-quality-verification-s3-fixture.json.gz) 的 inputs 中。编译适配器参见 [GNSS 输入核验](gnss-clock-audit.md#复现)。运行环境为 Python 3.13、NumPy 2.2.6。 [S3 设计](gnss-quality-verification-s3-design.json.gz) · [S3 回放](gnss-quality-verification-s3-results.json.gz) · [S2 设计](gnss-quality-verification-s2-design.json.gz) · [S2 回放](gnss-quality-verification-s2-results.json.gz) · [S2 核验](gnss-quality-verification-s2-verification.json)

在当前目录复现 S3。以下路径指向公开档案成员和已构建的适配器。

```powershell
$log = 'log_SamsungA52_20230811141745.txt'
$ref = 'NMND17420010S_2023-08-11_12-00-17.pos'
$nav = 'TAUN00FIN_R_20232230000_01D_MN.rnx'
$exe = 'D:/path/to/gnss_clock_audit_rtk.exe'
python -B gnss_quality_verification_s3.py $log $ref $nav fixture.gz
python -B gnss_quality_verification.py design fixture.gz design.gz $exe $nav
python -B gnss_quality_verification.py replay fixture.gz replay.json design.gz
python -B gnss_quality_verification_check.py fixture.gz design.gz replay.json.gz replay.json --s3-inputs $log $ref $nav
```

S2 用 `gnss-clock-audit-fixture.json.gz` 作为输入，三个命令分别添加 `--geometry gnss-route-verification-design.json.gz`，核验不传 S3 原始输入。
