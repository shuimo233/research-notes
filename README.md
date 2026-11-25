# Research Notes

用来记录学习记录的仓库：整理个人在 AI Agent、上下文管理与软件工程中的研究、实验和实践。

这里优先保存问题、方法、证据和取舍，而不是只保留最终答案。实验中的失败、成本与适用范围也属于记录的一部分。

## 研究文章

| 日期 | 文章 | 主题 |
| --- | --- | --- |
| 2026-11-25 | [联合发布可以有多少次直接跳过求解？](articles/consent-audit/retuned-odds-ci.md) | 在 6 个 CI 项目复验拒绝预算，并精确求解单证词请求 |
| 2026-11-24 | [两次发布想少透露一些，最少要改多少旧规则？](articles/consent-audit/retuned-odds.md) | 给出联合发布的最小概率改动、拒绝预算障碍和可扩展的乘积紧例 |
| 2026-11-24 | [两类请求分别安全，合起来还会多透露什么？](articles/consent-audit/joint-odds.md) | 保留两边发布概率，复验联合披露并定位拒绝概率的容量约束 |
| 2026-11-24 | [审阅者也能看到拒绝，发布规则还能保证什么？](articles/consent-audit/denial-odds.md) | 在最低成功率合同下精确优化赔率，24 项严格优于任意恒定成功率 |
| 2026-11-24 | [一条证词已经为真，抽中它还能改变多少赔率？](articles/consent-audit/selection-odds.md) | 精确校准发布概率，在 25 份 BART 目录逐项核验最优性 |
| 2026-11-24 | [证词的内容安全，选择证词的规则也安全吗？](articles/consent-audit/selection-protection.md) | 审计实际选择的推断，构造公开可核验的确定性与随机发布规则 |
| 2026-11-24 | [只用一份假想时间表，证明没有新确定任何线性统计量](articles/consent-audit/lag-protection.md) | 以公开的有理表验证全体时差保护，复算 35 项最少披露任务 |
| 2026-11-24 | [怎样验证披露最少，同时保留原先未知的时刻？](articles/consent-audit/unlocked-attestation.md) | 候选压缩与存在性困难，独立核验 35 项档案的保护条件 |
| 2026-11-24 | [用一条时间差证词，补足公开最优性证明](articles/consent-audit/attested-optimality.md) | 核验 35 个信息缺口，并证明两项与三项原读数之间的补证边界 |
| 2026-11-24 | [差分档案里的公开证据能跨领域复用吗？](articles/consent-audit/transit-optimality.md) | 复验 500 个 BART 换乘窗口，定位 34 个信息缺口，确定多界反例组的复杂度 |
| 2026-11-24 | [只凭公开读数，能证明披露已经是最少吗？](articles/consent-audit/public-optimality.md) | 只用公开输入证明 429 项证书最优，并定位 1 项真实回放的信息缺口 |
| 2026-11-24 | [如何只披露足以复核新版报告的时间戳？](articles/consent-audit/slack-certificate.md) | 构造精确反例集合，独立证实 430 份 CI 报告的最少披露 |
| 2026-11-24 | [只留旧报告时，哪些读数必须重查？](articles/consent-audit/conclusion-replay.md) | 用整数差分约束直接确定最小固定读取集合，在 1,450 份温差报告上检验 |
| 2026-11-24 | [已知候选版本，能给出完整的 npm 声明范围审计吗？](articles/consent-audit/npm-query.md) | 九份历史锁文件的版本合并、按需读取、可核验结果与事前判据 |
| 2026-11-24 | [独立更新的模块，可以分别做最坏损失规划吗？](articles/consent-audit/factored-robust.md) | 已知必问前缀后的精确分解、全局核验与共享未知前缀的反例 |
| 2026-11-24 | [两套先验之间，如何选择有保证的询问策略？](articles/consent-audit/two-prior.md) | 精确求解最小最坏损失，在 1,244 项任务中核验，并检查原始读数的价值 |
| 2026-11-24 | [先查必问位置，旧策略可以适用得更久](articles/consent-audit/mandatory-reuse.md) | 剔除必问点的复用证书让安全复用从 395 项增至 758 项，并实现批量精确求解 |
| 2026-11-24 | [更新询问先验后，旧策略的损失最多是多少？](articles/consent-audit/prior-reuse.md) | 用分块运输认证策略复用，在 1,244 项实测任务中通过事前效用和核验条件 |
| 2026-11-24 | [读数相关时，先证明复杂规划值不值得算](articles/consent-audit/mixture-query.md) | 2025 年 NOAA 留出复验和相关输入规划器，在 662 项任务上用证书直接跳过后验搜索 |
| 2026-11-24 | [等宽测量区间何时只需保存逐边概率？](articles/consent-audit/end-cut-budget.md) | 给出离散温差三分类的精确边界，从逐边统计重建 5,055 项 NOAA 查询路径 |
| 2026-11-24 | [气温档案回放中，精确规划的读数节省很小](articles/consent-audit/station-query.md) | 在 5,055 项 NOAA 跨站温差任务上验证块分解，保留未达效用门槛的结果 |
| 2026-11-24 | [少记一对追问的联合概率，最优预算能错多少？](articles/consent-audit/pair-budget.md) | 证明单位费用下的极小极大预算误差，并在 501 项词义关系任务上独立复算保证区间 |
| 2026-11-24 | [每次询问都算一次时，双连通块仍是最细的通用分组](articles/consent-audit/unit-block-proof.md) | 同一张图、相同的单位费用与均匀义项，局部统计相同的两个预算仍可相差 0.47 次以上 |
| 2026-11-24 | [用另一套人工词义标注复验：整句规划还能少问吗？](articles/consent-audit/gloss-frontier.md) | 在 Princeton WordNet Gloss Corpus 全量定义中复验预先登记的询问收益及块内统计 |
| 2026-11-24 | [为了决定下一问，哪些概率必须一起保存？](articles/consent-audit/frontier.md) | 证明整句自适应查询的最细安全分组，在 449 个标注句上通过事前效用比较 |
| 2026-11-24 | [把要问的词排好顺序，真实标注上能少问多少？](articles/consent-audit/heldout-triangle.md) | 用文档外词义频数使固定方案少问 120 次，量化额外抽签的收益并发布可交互工具 |
| 2026-11-24 | [自然句里真的有值得随机延后一个词的情形吗？](articles/consent-audit/natural-triangle.md) | 穷举 38,349 个句子单元，定位 2 个新句的正例，并检验它们对义项频率的依赖 |
| 2026-11-24 | [三个词先问哪两个，抽签有用吗？](articles/consent-audit/mixed-cover.md) | 99 个自然句中固定方案均已最优，给出三词严格反例、异质边际最优策略和 WordNet 中的适用范围 |
| 2026-11-24 | [各项最坏成本能否同时发生？](articles/consent-audit/fair-union.md) | 公平二元来源下的二触发线性判定、全正三触发困难性与精确半项缺口 |
| 2026-11-24 | [一句里先问哪些词，能证明选对了吗？](articles/consent-audit/coupling-witness.md) | 对 99 句的全部 244 个极小覆盖作稳健预算核对，比较见证、合并及无环判据 |
| 2026-11-24 | [只知道每个词的义项频率，能把整句的询问预算算准吗？](articles/consent-audit/cover-dependence.md) | 为 99 个真实句子构造精确相关性预算，给出可线性计算与 NP-hard 的结构边界 |
| 2026-11-24 | [同一个词义只问一次，一句话能少问多少？](articles/consent-audit/shared-sense.md) | 对照逐题缓存、整句询问顺序与最短证书，在两套语料中逐句核验 |
| 2026-11-24 | [确认“这是一种什么”有时也能少问一次](articles/consent-audit/wsd-clarification.md) | 五套外部语料中核对四种问法，公布未达门槛的复验、四个正例和逐项证书 |
| 2026-11-24 | [推理器什么时候可以少问一个词义？](articles/consent-audit/semcor-clarification.md) | 用真实同句词义标注核验提前停止，比较六种询问顺序并公开失败的主要假设 |
| 2026-11-23 | [一条理由撤回后，推理器还会给出同一个判断吗？](articles/consent-audit/wordnet-conflict.md) | 普查 WordNet 双向证据，对照 596 道冻结题，公开最少来源边与可撤回的推理服务 |
| 2026-11-23 | [保留 596 个推理判断，哪些来源必须随服务一起发布？](articles/consent-audit/monli-preserver.md) | 验证最少 23 条来源边可保留判决，保留全部证据覆盖则需 192 条，并实测模型调用成本 |
| 2026-11-23 | [推理器判断否定句时，查到的证据究竟能帮多少？](articles/consent-audit/monli-scope.md) | 对照肯定改写、简单反转、带出处的路径与 WordNet，区分模型和外部知识带来的收益 |
| 2026-11-23 | [只选一个蕴含方向，为什么整对答对更多、逐道却错得更多？](articles/consent-audit/monli-direction.md) | 在 836 对自然逻辑题上，用精确计数检验一次逻辑一致性修复的得失 |
| 2026-11-23 | [补齐宽度更像普通组批，答案会更好吗？](articles/consent-audit/rte-width.md) | 预先登记的 RTE 实验中，宽差下降 57.5%，新增评估题的判决分歧与错误反而增加 |
| 2026-11-23 | [同一句前提和假设，推理器能只看这一题吗？](articles/consent-audit/pointwise.md) | 隔离补齐和组内文本影响，用两种模型核验逐题推理，以及稳定性与准确率的实际取舍 |
| 2026-11-23 | [468 条评论可以有两种解释，模型排名还站得住吗？](articles/consent-audit/go-model-ranking.md) | 在冻结的真实模型输出上证明排名稳定，给出精确 F1 分差与可复用的逐条审计器 |
| 2026-11-23 | [把 27 种情绪归成 6 大类，先合并还是先数票？](articles/consent-audit/goemotions.md) | 复原 GoEmotions 的全部发布细标签，对照 5,427 条真实测试记录与第三方粗标签文件 |
| 2026-11-23 | [两位专家都说有严重错误，他们需要指出同一种错误吗？](articles/consent-audit/mqm-consensus.md) | WMT 真实专家记录中的判断聚合、可核对反例与可查询存档 |
| 2026-11-23 | [知道日志来源，什么时候真的能少读几页？](articles/consent-audit/row-noise.md) | 错页和缺页下的最低读取费用、完整来源信息的不变性与可验证的购页清单 |
| 2026-11-23 | [给归档格式留一个自由位，能省几项同源检查？](articles/consent-audit/receipt-frontier.md) | 固定来源检查与可编码信息的精确容量，最少检查数及可执行构造 |
| 2026-11-23 | [同一份日志，两种相反的行为，归档时还要留几位来源信息？](articles/consent-audit/receipts.md) | 给定已有同源检查的精确剩余标签数，三段副本的证明与 SQLite 文件回读 |
| 2026-11-23 | [哪几份证据值得提前买？一份可以验算的最低价清单](articles/consent-audit/panels.md) | 采用已有测试集合算法，在来源不确定时选择固定审计清单并复核最低费用 |
| 2026-11-23 | [先核对来源，还是再读一份报告？](articles/consent-audit/lineage.md) | 来源图不确定时的核验费用、行列覆盖与三根冲突证书 |
| 2026-11-23 | [两份日志，几个证人？按来源核验代理行为](articles/consent-audit/sources.md) | 同源错报、反例清单大小的紧界与最低核验费用 |
| 2026-11-23 | [第一次便宜、第二次很贵时，应该先查哪份证据？](articles/consent-audit/weighted.md) | 分层复核价格下的最优顺序、费用差距与逐文件核验 |
| 2026-11-23 | [已经测过一些条件，还要测多少次才能判断代理是否遵守同意？](articles/consent-audit/sequential.md) | 区间报价历史的顺序审计、精确最坏次数与可用容量 |
| 2026-11-23 | [零次未经同意的写入，能说明代理尊重同意吗？](articles/consent-audit/README.md) | 同意原则的行为审计、单点例外配额与两个学习器的实测 |
| 2026-11-22 | [32 个故障原因，怎样让接收方查得动一份保证？](articles/antipodal-count-bounds/README.md) | 四行边界编译、无法降至三维的证据及独立验收 |
| 2026-11-22 | [五行能证明什么？一次独立核验与更正](articles/weighted-conflict-audit/audit.md) | 2008 年先例、13 行实例的三维归约与 0.4.0 独立核验器 |
| 2026-11-22 | [一份行动计划需要几行证据？](articles/weighted-conflict-audit/README.md) | 八行紧界、压缩核验器 0.3.0 与 44 个 SQLite 分片写入实验 |
| 2026-11-21 | [两两都可能，为什么已经能行动？](articles/joint-action-certificates/README.md) | 行动规划器 0.2.0、错读记录的联合核验和树积上的证据大小 |
| 2026-11-21 | [修好数据库，需要先知道它为什么错了吗？](articles/action-before-identification/README.md) | 有界错读下的行动成本、公共回退条件与真实 SQL 修复 |
| 2026-11-21 | [当所有旧规则都被观测推翻，该复查哪一项？](articles/conflict-rechecks/README.md) | 错读与模型遗漏、两批复查的最优成本、SQLite 反例 |
| 2026-10-30 | [让个人助手长期工作：AngelBot 的最小记忆与上下文框架](articles/long-lived-agent-framework/README.md) | 长期偏好、动态约束、工作视图、来源回查与 token 成本 |

## 阅读说明

- 每篇文章区分已实现机制、实际实验结果和待验证假设。
- 小样本工程诊断不包装为官方基准成绩，开源项目的产品描述也不当作效果证明。
- 只公开审查过的研究材料，不发布个人会话、凭据、原始模型协议或运行数据库。

相关实践项目：[AngelBot](https://github.com/shuimo233/AngelBot)。文章中的开发快照不一定已经进入项目公开主分支，请以各文的版本说明为准。
