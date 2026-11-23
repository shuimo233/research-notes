# Research Notes

用来记录学习记录的仓库：整理个人在 AI Agent、上下文管理与软件工程中的研究、实验和实践。

这里优先保存问题、方法、证据和取舍，而不是只保留最终答案。实验中的失败、成本与适用范围也属于记录的一部分。

## 研究文章

| 日期 | 文章 | 主题 |
| --- | --- | --- |
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
