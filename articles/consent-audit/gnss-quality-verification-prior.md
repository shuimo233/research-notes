# 按信号质量设置 GNSS 合同及选星的先例

查新范围是共同接收钟差下的异宽有界伪距、允许任意坏星的集合估计、手机信号质量加权和完整性导向选星。另核对了 2024 年第 254 至 256 日的公开广播 GPS 星历，供独立测量档案复现。 [共享钟差与卫星选择的基础先例](gnss-clock-audit-prior.md) · [六星路段核验与归一化先例](gnss-route-verification-prior.md)

## 最接近的先例

- **按星单独设置区间，并用 C/N0 决定宽度，已经用于 GNSS 完整性。** Jingyao Su 的 2025 年论文第 5.1.5 节式 (5.26) 将统一检测区间改为随测量变化的对角宽度。式 (5.29) 与 (5.30) 给出基于信号强度的例子，宽度因子为 \(\sqrt{V_i+C_i10^{-(C/N_0)_i/10}}\)。第 5.2 节进一步对多个坏测量模式分别求区间可行域并合并，和故障概率一起生成保护水平。\(C/N_0\) 是观测载噪密度比。该做法与本轮的异宽误差合同最接近。Drevelle 与 Bonnifait 则更早在有界伪距和共享用户钟差下用放松集合逆容许少量坏星。 [Su，区间完整性监测，第 5 章](https://doi.org/10.15488/19619) · [Drevelle 与 Bonnifait，高度辅助的集合成员定位](https://www.hds.utc.fr/~bonnif/pdf/2011_GPS_solution.pdf)
- **用共有钟差的伪距集合消除位置歧义已有手机实测。** Neamati、Bhamidipati 与 Gao 从四维伪距方程出发，将每颗星的可行状态投影至未知共同钟差与二维位置，在旧金山手机记录上用前后向迭代滤波选道路场景中的可能位置。该方法用空间可行域和跨历元约束，实验目标是选择位置模态。 [Set-Based Ambiguity Reduction in Shadow Matching with Iterative GNSS Pseudoranges](https://par.nsf.gov/servlets/purl/10404008)
- **用 C/N0 或综合质量选手机卫星组合已有实测。** Deng、Wang、Wei 与 Zhang 用手机和参考站的综合 \(C/N_0\) 选择优质卫星子集，再用双差码伪距残差构建随机模型。在遮挡数据中对照了只用 \(C/N_0\) 的随机权重。Wang 等人进一步使用综合质量评价选星，在多款手机的遮挡和移动环境中验证相对定位。Gerbeth 等人此前已用固定数量的全组合最优选星作为水平 ARAIM 基线。不同研究分别标定连续定位的随机误差和保护水平。本轮可将公开做法中的质量排序用作同预算对照。 [Deng et al. 2024](https://doi.org/10.3390/s24082598) · [Wang et al. 2025](https://doi.org/10.1016/j.asr.2025.09.016) · [Gerbeth 等人的水平 ARAIM 选星](https://elib.dlr.de/106284/1/Satellite%20Selection%20Methodology%20for%20Horizontal%20Navigation%20and%20Integrity%20Algorithms.pdf)
- **忽略固定数目的离群点后最小化加权最大距离属于已有数学模型。** 加权位置中心研究中的 \(k\)-max 目标使用加权距离的顺序统计量，允许忽略若干最大项。固定位置对比较时，可以把共同钟差看作一维中心、某一星的伪距差看作对应点、坏星看作允许丢弃的点。分离半径的有限候选公式可直接从闭区间公共交推导。 [Exact Algorithms for Handling Outliers in Center Location Problems on Networks Using k-Max Functions](https://www.sciencedirect.com/science/article/abs/pii/S0377221718307252)

## 加权合同的精确判据

设候选位置 \(A,B\) 对卫星 \(i\) 的名义伪距之差是 \(d_i=g_i(B)-g_i(A)\)。两世界允许健康读数在容限 \(q\) 下各有半宽 \(q\,a_i(A)\)、\(q\,a_i(B)\)，其中各尺度均为正。令 \(w_i=a_i(A)+a_i(B)\)。若星 \(i\) 在两边都健康，共享伪距要求两世界的钟差之差 \(\delta\) 落入 \([d_i-q w_i,d_i+q w_i]\)。

固定两个世界删坏星后留下的公共健康集合 \(J\)。闭区间两两相交就有共同交点，故在 \(\delta\) 不设界时最小可混淆容限为
\[
\max_{i,j\in J}\frac{|d_i-d_j|}{w_i+w_j}.
\]
只有一个共同健康源或没有共同健康源时，该值为零。若 \(\delta\) 需在非空有界闭区间 \(\Delta\)，再对全部 \(i\) 取 \(\operatorname{dist}(d_i,\Delta)/w_i\)，与上式一并取最大。对合规的删源组合取最小，就得到位置对的精确半径。若两边各至多有一颗任意坏星，删源并集最多两颗，二者可各承担一颗不同星。达到临界值时可从公共 \(\delta\) 及每颗健康星的回复交集恢复一条共用伪距见证。

异宽时无法照搬等宽的连续排序窗口。令六个差值为 \(0,0.1,2,3,4.9,5\)，对应合并宽度系数为 \(100,0.1,100,100,0.1,100\)。保留四颗时，\(0,2,3,5\) 的非连续组合在 \(q=0.025\) 处相交。三个按差值排序的连续四元素窗口所需容限都更大。独立复核可以枚举所有允许删除的卫星，再逐一检查端点交集和最优临界值。

同时把所有宽度乘同一个正数，会按同一比例的倒数缩放实测需求与几何半径。二者的比值和按半径进行的组合排序不变，因而只能靠相对宽度配置改变实测对照。\(C/N_0\) 模型给出质量尺度，不能直接证明一个确定性噪声上限。实测应冻结由质量字段到宽度的映射，再校准并留出评估。若选星要先读取所有候选星的质量字段，较少使用伪距不代表已经省去全部候选信号的跟踪开销。

## 公开广播星历入口

NOAA 国家大地测量局的 NCN 数据目录明确列出公开 AWS 分发的每日 GPS 广播星历。此处三个链接均以普通 HTTPS 请求返回 HTTP 200，无需登录。已完整读取压缩字节并解压，文件头均为 RINEX 2.11 GPS 导航电文，记录含 GPS PRN 1 至 32。下表的摘要来自压缩文件的原始字节。这里只核验星历文件及格式，未读取手机或参考轨迹的测量数据。 [NOAA NCN 每日广播星历目录](https://geodesy.noaa.gov/CORS/data/#ephemeris) · [IGS RINEX 格式目录](https://www.igs.org/wg/rinex/)

| 2024 日序 | 下载 | 压缩字节 | 导航记录数 | SHA-256 |
| --- | --- | ---: | ---: | --- |
| 254 | [NOAA brdc2540.24n.gz](https://noaa-cors-pds.s3.amazonaws.com/rinex/2024/254/brdc2540.24n.gz) | 71227 | 491 | e12e241da3cf9d034052de40e3c405ecf0d50e618e429e1d7b611cd5478e9d08 |
| 255 | [NOAA brdc2550.24n.gz](https://noaa-cors-pds.s3.amazonaws.com/rinex/2024/255/brdc2550.24n.gz) | 70953 | 487 | ef484bb751743dcb37601112c2a6c0b81c7e738b4cb9f2faf4bfb1fa446aace3 |
| 256 | [NOAA brdc2560.24n.gz](https://noaa-cors-pds.s3.amazonaws.com/rinex/2024/256/brdc2560.24n.gz) | 70647 | 490 | fbdd52c46bff292706c07e47232aede5fc52aaf5dc0e9cb510581406e7cde8bb |

三个文件均含上一晚的早期参考历元，逐星选择时应按广播星历有效期和参考时刻判定。RINEX 2.11 的首行使用数字 PRN 和两位年份，单条 GPS 导航电文八行，需支持 Fortran `D` 指数与 RINEX 2 的电离层头字段。NASA CDDIS 访问本轮重定向至 Earthdata 登录页。IGS 还列出由 DLR 提供的 RINEX 3 产品，可通过 BKG 的每日归档获取。本环境访问 BKG 遇到证书验证错误，未把该镜像列为字节级复现来源。NOAA 旧的机构站点路径返回 410，正式目录已注明迁移。 [IGS 的 BRDM00DLR 数据目录](https://igs.org/mgex/mgex-product-descriptions/) · [NCN 迁移说明](https://geodesy.noaa.gov/CORS/data/)

有限检索尚未找到完整等价方案，将各星质量尺度纳入有限异标签位置首次重合的精确半径，用该半径选择固定预算组合，再在独立记录按同一尺度校准并对照。区间按星加权、坏星集合容忍、共享钟差和按完整性选星均已见于上述先例。剩余主张应限于组合目标与独立复现所支持的经验表现。
