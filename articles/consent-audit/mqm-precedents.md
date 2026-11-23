# WMT 2020 专家标注：多数意见、匿名发布与先例

核查日期为 2026 年 11 月 23 日。主问题是对每份系统译文，三位评审中是否至少有两位各自指出某类译文错误。两人可以指出不同位置和不同子类。参考答案是**保留评审分组时这些专家实际记录的意见**。是否客观存在错误、两人是否指出同一处、作者发布的平均错误负担，都是不同的测量对象。

**最接近的直接先例是 Stanford AIMS 的 WMT MQM 数据转换。** 它已经在本研究使用的两份 2020 数据及另外六份 2021–2022 数据上，按译文和评审分组，生成“此评审是否标过这个类别与严重度”的 18 个二值指标。其代码明确对每位评审内部重复的该类记录去重。因此逐人构造二值指标这一工作已有人完成。此次未查到作者在去掉评审对应关系后计算三人多数的锐界，也未查到该数据上为任意类别并集编码最少补充信息的同一研究。[AIMS 的数据说明及覆盖表](https://github.com/aims-foundations/measurement-db/blob/7e223f127c76f7f049955730c3493345e330827d/benchmarks/wmt_mqm/metadata.yaml) · [2026-10-01 的转换代码，第 62–76 行](https://github.com/aims-foundations/measurement-db/blob/7e223f127c76f7f049955730c3493345e330827d/benchmarks/wmt_mqm/build.py#L62-L76)

## 哲学上的直接先例

看完中英主结果后，补查了 `judgment aggregation disjunctive agenda premise conclusion` 及其与 `WMT MQM majority error categories` 的组合。List 在《The Discursive Dilemma and Public Reason》中直接给出了析取例子，多人可以因各自不同的理由支持同一结论，以至于逐项理由均得不到多数。“先在每人之内合并理由再投票可以改变结果”已有明确先例，本研究沿用它作为可执行对照。在本次检索范围内，尚未找到针对这两个 WMT 文件报告同一组逐层频数、自然碰撞及条件编码费用的一手发表物。归档方法是否依赖特定限制，仍需对照每项字段合同。[List 原文](https://eprints.lse.ac.uk/5829/2/The_discursive_dilemma_and_public_reason_%28LSERO%29_.pdf) · [List 和 Pettit 对判断聚合的早期形式化](https://ppettit.scholar.princeton.edu/sites/g/files/toruqf7426/files/documents/Aggregating_EconomicsandPhilosophy_2002.pdf)

## 哪些是原始协议

| 核对项 | 一手证据与本次采用口径 |
| --- | --- |
| 数据与评审设计 | Freitag 等重新评价 newstest2020 的英德和中英译文，每个语言方向有 10 个系统或人工参照输出。论文表 2 指 MQM 每段计划有 3 份专业评审，评审池有 6 人。20 个三人组合按文档轮派，同一人评价分配给他的文档的全部 10 个输出。实际三人覆盖应在文件里核对。不能据此把每份译文视作独立抽到三位评审。[论文第 3 节、表 2](https://aclanthology.org/2021.tacl-1.87/) |
| 错误与五条上限 | 对每位评审、每段译文，最多标出五个译文错误；超过五个时只选最严重的五个。五是上限，标满五条时无法由记录推断全部错误数。Major、Minor、Neutral 是严重度；Neutral 的普通类别标注仍是一条记录。No-error 是显式无错占位，两者不能仅凭分值相同合并。Marot 定义文件中的 category 和 severity 并列出无错占位，具体拼写应从使用的发布版列值校验。[评审指南，论文附录表 10–12](https://arxiv.org/pdf/2104.14478) · [Marot 发布格式](https://github.com/google-research/google-research/blob/master/marot/README.md) |
| 来源错误与整段非翻译 | 表 12 明确规定 Source error 单独标注且**不计入五个译文错误的限额**，由源文错误导致的译文错误仍按通常规则处理。选 Non-translation 时整段最多一项，不再标其他错误。在原始计分中，这个特殊类别按 25 分计算；对于二人多数，它仍只来自一次评审。宽口径“任意译文 Major”须明确是否包含 Major 的 Non-translation；窄口径只含 Accuracy 或 Fluency 时不能自动纳入它。[附录表 11–12](https://arxiv.org/pdf/2104.14478) · [发布仓库说明](https://github.com/google/wmt-mqm-human-evaluation/blob/29acd6999aaea3586378c9dcb58d8cc4820cede3/README.md) |
| 正文变体与额外文件 | 仓库历史说明，`.no-postedits.tsv` 是自动移除 post-edits 得到的同数据版本。`.source-errors.tsv` 是补充来源错误标注，发布者特别说明该补充文件的标记出现在目标一侧。不能把变体当成新专家或依据高亮位于哪一侧来认定译文错误。[移除 post-edits 的上游提交](https://github.com/google/wmt-mqm-human-evaluation/commit/2fec9a7c6115) · [增加来源错误的上游提交](https://github.com/google/wmt-mqm-human-evaluation/commit/3b7ab370d54f) |
| 官方平均分 | WMT21 指明 avg_seg_scores 仅给出按原论文严重度模型计算的片段平均分。原论文先算每人错误权重总和，再在评审之间平均；一个人的两个 Major 和两个人各一个 Major 都可能贡献同样总分。默认相对权重为 Major 5、Minor 1、Neutral 0，另有 Minor/Fluency/Punctuation 0.1 和 Non-translation 25 等规则。另一发布工具 `score_mqm.py` 在各评审内求和、再平均，并在常规 Google 分支为便于评测取负；直接比数值需先说明版本、符号、键和取整。平均分有清楚的原定用途。[WMT21 官方的文件说明](https://www.statmt.org/wmt21/metrics-task.html) · [原文章计分](https://arxiv.org/pdf/2104.14478) · [作者维护的评分转换器](https://github.com/google-research/mt-metrics-eval/blob/main/mt_metrics_eval/converters/score_mqm.py) |

对提交 `29acd6999aaea3586378c9dcb58d8cc4820cede3` 独立读取两份**仅含数值的平均分文件**。两者表头均为空白分隔的 `system mqm_avg_score seg_id`，实际数据行也用空格。在每个语言方向内，英德 14,180 行恰有 14,180 个不同的 (system, seg_id) 键、1,418 个不同的全局 seg_id；中英对应为 20,000、20,000 和 2,000。两者均含 10 个不同的 system。平均分表没有文档内局部键或评审 ID。核对没有下载翻译标注主文件、读取源文译文或计算投票实证数；实证数字以项目另行运行的标注元数据程序为准。[英德平均分发布文件](https://github.com/google/wmt-mqm-human-evaluation/blob/29acd6999aaea3586378c9dcb58d8cc4820cede3/newstest2020/ende/mqm_newstest2020_ende.avg_seg_scores.tsv) · [中英平均分发布文件](https://github.com/google/wmt-mqm-human-evaluation/blob/29acd6999aaea3586378c9dcb58d8cc4820cede3/newstest2020/zhen/mqm_newstest2020_zhen.avg_seg_scores.tsv)

## 无身份后具体能推断什么

先说明发布内容。如果只去掉一列却保留原行顺序、错误跨度、文档间的稳定编号或其他能聚类的线索，剩下的数据比“每份译文无序的类别行直方图”更强。本研究的可行重分组针对后一个明确的发布方式。若来源错误行混在输入里，译文五项限额仍只约束译文行；仅有来源错误的打分是否留下占位，要按照实际导出规则处理。不能把没有满足三席、五条或占位条件的译文静默解释成三张有效票。

对一个预先指定的错误集合，有个简单的锐界可作为程序对照。先分配所有必须独占一位评审的 No-error 和 Non-translation；如果整段非翻译满足所选谓词，其专用席位贡献一张确定的赞成票。剩余 h 个普通席位，每席须有 1 至 C 条译文标注，合计有 T 条谓词命中、U 条其他标注。只在这些确实是可自由分组的普通行、且 h≤T+U≤Ch 时，普通赞成票数 x 的精确区间为

> max(⌈T/C⌉, h−U, 0) ≤ x ≤ min(T,h)。

左界分别来自每席容量和必须给每个反对席一条非命中记录。反向构造先为 x 个赞成席各置一条命中行、其余席各置一条非命中行，再把余下命中行仅放进赞成席，其余非命中行放入剩余容量即可。如果另有逐类别不同评审人数、源文专用记录、或已保留局部身份关系，这个仅有 T、U 的公式也应相应加强。可行区间跨过两票门槛时，发布的统计允许两种相反结论。它不提供哪个解释更可能，也不等于实证中确实标错了多少份。

一个可人工检查的例子是三席共享的无序直方图含两个 Major/Accuracy 和三个相同的普通 Minor 项。一种分配将两个 Major 和一个 Minor 放进第一席，其余两席各一个 Minor。另一种分配在前两席各放一个 Major 与一个 Minor，第三席仍有一个 Minor。两者逐行类型直方图、三席数、计分权重及官方平均分相同，二人多数相反；若另外公开 Major/Accuracy 的不同评审数，它们当然已能区分。

已有工作研究从聚合资料或未知配对中识别哪些个体层面事实；统计匹配会把多种相容联合分配保留下来。有关群大小含信息的研究还说明按记录数加权和按群体数加权可以对应不同的估计量。这里一人可能标多行，按错误行投票在定义上就与按人投票不同。反过来，在一个已知有限测试集里，将具有完全相同发布统计的实例聚类，对某个固定是非题逐类取两种金标准计数的较小值再求和，是任何只看该统计的确定规则在**该批已知实例**上的最少错误数；它是另一种问题，不能用来估计其他语种或未来译文的错误概率。[统计匹配下的部分识别](https://digital.library.adelaide.edu.au/server/api/core/bitstreams/3826e064-edd5-4d60-9778-31a5f8697748/content) · [Williamson、Datta 和 Satten，Biometrics 2003](https://onlinelibrary.wiley.com/doi/10.1111/1541-0420.00005)

## 任意未来类别并集需要保存的函数

选定原子词表（严重度、规范化叶类别），不含 No-error 或来源错误。每位评审形成原子集合 Aᵢ，对未来查询 S 求“至少两个 Aᵢ 与 S 有交集”。单原子查询就显出所有被至少两人持有的原子；这些原子出现于 S 时答案直接为是。剔除它们后，两原子的查询为是，当且仅当它们各由一位不同的人持有。把这种最小真对画成边，非孤立原子组成完全多部图，同一个人的原子处在同一部分。只要出现两个不同持有人，图上的不相邻关系就恢复其无名分组。若总共只剩一位持有人，则所有这类原子对都无法通过，查询函数不需要它们。该表是针对**全部原子子集查询**的函数等价表示；若未来查询只允许两个预设类别或必须符合某个分类树，最少摘要可能更小。

这个推导是单调布尔函数由其包含极小真集决定的简单情形，也与聚合查询的来源信息一脉相承。已有研究系统处理单调 DNF 与超图，数据库文献已经研究聚合结果的来源。这里可报告的具体观察是阈值给极小真集带来的“单点或跨持有人的二点”结构，以及它在此语料上比保留所有评审字段省多少。[Eiter、Gottlob 和 Makino，单调对偶化与超图](https://arxiv.org/abs/cs/0204009) · [Amsterdamer、Deutch 和 Tannen，PODS 2011](https://arxiv.org/abs/1101.1110)

## 在已公布逐类型人数后，最少还要几比特

假定发布方与解码者均知道各原子行数 k、不同评审人数 d，以及相同三席规则；No-error 可计入这些公开边际但不能作为查询项。令 F 是该**固定边际**下可实现的不同查询函数数。若 F≥1，逐段独立的最坏固定长度字段至少要 ⌈log₂F⌉ 比特。按双方一致的顺序枚举可行函数，发送其序号即可达到；F=1 时无需该字段，F=0 是输入不相容。这里没有计入边际本身的发布成本、字典和认证，也没有比较跨段联合或概率变长编码。用集合大小决定固定长度、以排名编码均有经典先例。[Cover，*Enumerative Source Encoding*，IEEE 1973](https://isl.stanford.edu/~cover/papers/transIT/0073cove.pdf)

枚举可行函数时，固定词表顺序，只遍历 d=1 查询原子的无名分区。可把第一次出现的所有者编号为 0，下一个新所有者编号为 1，然后是 2，以受限增长串产生每个划分一次。不同划分总能通过某对原子的同主或异主查询区分，单原子时亦只有一个划分。对每个划分，剩余 d≥2 的原子仍须能分别由恰好 d 位持有、共写 k 行，且各人的总行数不能超过上限。No-error、Non-translation 等排他类型要在同一次填写里消耗整张席位。若有多种共同原子填写、三个实名的多种置换或多种行排列，都只计入一个函数。若遇零次出现的查询原子，已知 d=0 也已经决定其单项作用。若只有一位独有原子的持有人，固定 d 边际下所有这些原子本来就只有一个单块划分，不另发其所有者信息。

在固定边际下枚举这个可行空间，与统计学中受约束列联表的 **fiber**（满足已知汇总的所有表）相近。不过此处既有限定支持人数和特殊行排他约束，又只需要计算表在一组变量上的不同投影。以分区作为投影、其余填写作为只需存在的辅助变量，恰是已有 **projected model counting** 的定义；多种填写不可重复计数。前缀计数、按分支大小排名与反排名也属于枚举编码。尚未发现针对这套 MQM 约束预先给出相同可行性程序和实测补充码长的原文。若引用该算法，应把通用数理工具与本次将评审协议编入约束区分清楚。[Slavković、Zhu 和 Petrović，固定条件与边际下列联表的 fiber](https://arxiv.org/abs/1401.1397) · [Aziz、Chu、Muise 和 Stuckey，SAT 2015](https://arxiv.org/abs/1507.07648) · [Cover 的枚举编码](https://isl.stanford.edu/~cover/papers/transIT/0073cove.pdf)

## 与既有 MQM 一致性研究的差别

Freitag 等第 4.4 节已比较不同专家的平均分类负担和评分尺度，并以重采样研究评价设计对系统排名的影响。后续 MQM Re-Annotation 工作研究给同事的标注做复核以改善评价；另一类工作测量跨度召回或类别匹配。Stanford AIMS 已实际公开含评审对应关系的二值类型读数，其 207,090 个 item 与 113 个 subject 按该库的跨年份组织定义；subject 指翻译系统或人工参照，不能解读成 113 位 2020 评审。上述来源均不足以证成任意匿名发布下的多数可识别，更不能证明 WMT 的平均分有误。[原研究的评审一致性分析](https://aclanthology.org/2021.tacl-1.87/) · [MQM Re-Annotation，ACL 2026](https://aclanthology.org/2026.acl-long.1553/) · [AIMS 数据卡](https://measurementdb.org/measurement-db/wmt_mqm)

检索覆盖作者仓库、WMT 任务说明、ACL Anthology、AIMS 转换源码、统计匹配与计量统计期刊，以及 SAT、PODS、IEEE 信息论的原始论文。检索组合包括 `WMT20 MQM majority two of three major errors`、`per-rater category severity indicators`、`No-error Non-translation source error five-error limit`、`anonymous annotator reconstruction MQM`、`statistical matching partial identification`、`informative cluster size`、`contingency table fiber`、`monotone Boolean minimal true sets`、`projected model counting` 和 `enumerative source encoding`。公开页面未检索到本任务全部实证比较或锐界的直接重复，这项有限检索不构成优先权证明。
