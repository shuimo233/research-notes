# 未经同意的请求能从什么行为中识别

核查日期为 2026-11-23。对照对象是[本轮实验协议](PROTOCOL.md)。闸前请求位表示代理要求工具执行受保护操作，另行向用户询问能否授权不计为这种请求。结果所指的部署性质是在指定收益范围内、无同意时是否发出该操作请求。执行闸则独立保证拦截所建模的未经同意效果。

**已有研究分别覆盖了有限报价不能证明绝对偏好、屏蔽器可以看到被拦的原动作、带出错预算的可行参数集，以及固定试验的纠错距离。** 阈值子问题的最低费用追加方案又可直接化为链形拟阵的加权贪心。相对更窄、值得单列的命题是，撤掉阈值假设后，在历史与全安全行为相容、每条试次独立选择实际报价的条件下，可以只用历史相容的单价例外精确算出对所有稳定确定行为的最小审计费。以下给出原文、推导和适用条件。[Kohli 与 Jedidi，定理 1](https://doi.org/10.1287/mksc.1060.0241) · [Alshiekh 等，屏蔽器两种接口](https://arxiv.org/abs/1708.08611) · [Jaulin，§2.1](https://webperso.ensta.fr/jaulin/paper_sauce_automatica.pdf) · [Zhigljavsky，§2.1，式 (3)](https://orca.cardiff.ac.uk/id/eprint/15201/1/Group%2520testing%2520lies.pdf)

## 有限激励和受保护价值

Baron 与 Spranca 的 *Protected Values* 研究人们把某些价值排除在交易之外的判断。Kohli 与 Jedidi 在有限属性水平上给出线性效用重现词典序的权重条件。这里的二元特例甚至无需估计权重。只要实验可能给出的最高收益是 M，任何有限 C≥M 的“收益严格大于 C 才请求”与绝对禁令 V 产生相同选择。知道 V 与日志相容只表示尚未排除它。反方向更容易，在预算允许的错读数之外记录到未经同意的请求，就可排除 V。把这个行为命题称为新发现的词典序偏好不可识别定理，缺乏依据。[Baron 与 Spranca，Protected Values](https://pubmed.ncbi.nlm.nih.gov/9236161/) · [Kohli 与 Jedidi，原文及定理 1](https://business.columbia.edu/sites/default/files-efs/pubfiles/2729/2729-Kohli.pdf) · [Hess 等，离散选择中的不交易行为](https://doi.org/10.1016/j.trd.2010.04.008)

在逆强化学习中，Amin 与 Singh 已研究主动选择多个环境后哪些回报可以识别。这里可直接构造给出相同日志的两个确定规则，所需假设比一般逆强化学习少。主动设计伦理选择也有实证先例，Keswani 等研究了主动选题能否改善对人类道德偏好的学习。其研究的预测效果与学习体验，和固定预算下对所有允许错读作逻辑保证，是不同的量。[Amin 与 Singh](https://arxiv.org/abs/1601.06569) · [Keswani 等，AIES 2024](https://arxiv.org/abs/2407.18889)

智能体已有相关实测。MACHIAVELLI 比较获取任务奖励时的伦理行为。ODCV-Bench 在隔离环境中配对施加结果激励或明确命令，评价代理是否违反约束。DelegationBench 的 2026 年预印本改变是否获得授权、利害或可逆性，还比较回答“该不该做”和实际使用工具时是否先询问。它们已覆盖“把授权和利害分别变化，并观察代理实际行为”的实验想法。合成示范上训练出的决策树与逻辑回归在新收益范围上出现不同表现，只能证明这两个学习器在该设计下的行为分化。训练行为相同而测试时泛化不同也已有实验先例。[MACHIAVELLI](https://arxiv.org/abs/2304.03279) · [ODCV-Bench，§3.3–3.4](https://arxiv.org/html/2512.20798v1) · [DelegationBench](https://arxiv.org/abs/2610.05532) · [Langosco 等，ICML 2022](https://proceedings.mlr.press/v162/langosco22a.html)

## 事前请求、事后效果和因果边界

Alshiekh 等让置于代理之后的 shield 查看拟议动作，并在必要时替换。AgentSpec 进一步给出执行前事件、用户检查和停止操作。Apeiron 等已用多智能体规范刻画授权的生效、到期、行动与承诺。因而拟议动作与环境实际执行的动作分开，以及在效果发生前介入的架构，均有直接先例。无同意时执行闸把所有请求映为效果 0，单看这个比特当然无法区分两种请求策略。若日志另含拦截计数、错误码或时序，必须重新计算观测等价类。Selective Labels 说明由决策决定结果可见性时如何妨碍评价；其论文要推断未观察到的结果，本实验主要是一个指定观测映射丢失原动作位。[Alshiekh 等](https://arxiv.org/abs/1708.08611) · [AgentSpec，§3–4](https://cposkitt.github.io/files/publications/agentspec_llm_enforcement_icse26.pdf) · [Apeiron 等，AAMAS 2025](https://www.ifaamas.org/Proceedings/aamas2025/pdfs/p133.pdf) · [Lakkaraju 等，KDD 2017](https://www.cs.cornell.edu/home/kleinber/kdd17-selective.pdf)

一个能改变解释的反例是，若报价仅在实际执行成功后支付、代理知道成功概率为零，而且尝试有正成本，那么可以被补偿的效用最大化者也会对每个报价拒绝。闸前记录能识别的是**在该实验机制中实际发请求的规则**。从这些数据推断撤闸后的行为，须另给保持请求规则不变的依据。审计者只知道收益区间也要与代理本身看不到收益区分，后者涉及代理到底对哪个信号作反应。随机策略、跨试次学习、共享未观测收益或审计感知都会改变协议的观测集合。[逆强化学习中的环境与可识别性](https://arxiv.org/abs/1601.06569) · [DelegationBench 关于对行为测量方式的实证比较](https://arxiv.org/abs/2610.05532)

## 固定阈值下的精确推断与最低费用

1. **日志允许 f 次翻转。** 每条日志对应使联合请求位和效果位相容的参数集。错一整条记一次。没有同意、观察到请求 1、收益在闭区间 [l,u] 时，相容条件是 C<u；观察到 0 时为 C≥l。其余一律相容或一律矛盾的位按协议合并。各试次实际收益可独立取值时，“与至少 N−f 条相容”充要。Jaulin 的 q-relaxed intersection 正是这一集合运算，论文还明确指出结果可能不是一个盒。这里用整数端点排序，输出精确区间并和无穷尾段。对不确定输入取最有利的允许实现，与 Hüllermeier 的集合值观测及广义损失相符。[Jaulin，§2.1](https://webperso.ensta.fr/jaulin/paper_sauce_automatica.pdf) · [Hüllermeier，集合值观测的损失最小化](https://arxiv.org/abs/1305.0698)
2. **部署保证。** 若存在相容阈值，最小相容 C 是所有候选共同拒绝的收益前缀上界。V 与任何足够大的有限 C 同时相容或同时被排除。部署上限 B 以下所有相容规则均拒绝，已足以给出该范围的条件保证。若相容集为空，应报告候选类与误差假设和记录冲突，不能用空集上的全称命题报告安全。[Kohli 与 Jedidi](https://doi.org/10.1287/mksc.1060.0241) · [Jaulin](https://webperso.ensta.fr/jaulin/paper_sauce_automatica.pdf)
3. **后续测试。** 两个历史存活规则各已至少需要 e₁、e₂ 条错误时，追加诚实记录的最小汉明距离必须大于 (f−e₁)+(f−e₂)。同一向量可兼容两个假设当且仅当两个半径之和至少为中心距离，证明是将距离坐标分配给两端。若诚实记录本身是集合，须先在两集合之间取最小距离，此步依赖各试次彼此独立。等半径的 2f+1 判据是编码论基本结果，Zhigljavsky 的固定实验模型已直接以任意测试函数写出该判据。Rivest 等亦分析比较搜索中的错误，但其序贯决策与本项目预先选定的追加清单不同。[Hamming 1950](https://doi.org/10.1002/j.1538-7305.1950.tb00463.x) · [Zhigljavsky，式 (3)](https://orca.cardiff.ac.uk/id/eprint/15201/1/Group%2520testing%2520lies.pdf) · [Rivest 等，Coping with Errors in Binary Search Procedures](https://people.csail.mit.edu/rivest/pubs/RMKWS78.pdf)
4. **链上的最低费用。** 受保护区间内，安全规则都答 0。危险阈值 C 只有在追加报价的下端 l>C 时才被保证答 1。所有这样的菜单集合随 C 嵌套。将容量概念上展开作证明，令 X 为购买的试次，E 为全部可用试次，每条约束是 |X∩A|≥k。若 |A|<k，A 就是菜单不足的证据。否则舍弃集 Y=E∖X 满足 |Y∩A|≤|A|−k。A 组成链，符合层状拟阵的定义。最大化舍弃试次的总价等于最小化购买价，因此加权拟阵贪心已给出最优性。程序可按容量成批从堆中取用，运行时无需物化所有试次。含历史误差的需求值以及原单位下的不足证据是本应用要交付的部分。[Fife 与 Oxley，层状拟阵定义](https://arxiv.org/abs/1606.08354) · [Edmonds，Matroids and the Greedy Algorithm](https://doi.org/10.1007/BF01584082)

## 撤掉单调性后，单价例外何时足以给全类定价

令 P 是受审计的有限收益集合，S⊆P 是一个稳定确定规则在未获同意时会请求的收益点。假设每条有信息的报价记录只含 P 内的可能收益，且不同试次独立实现。基线 S=∅ 的历史错数为 d₀≤f。记 d(S) 为规则 S 与历史相容至少需要的整行错误数，R=f−d₀，Δᵢ=d({i})−d₀。

除对所有规则相同的损失外，历史请求 1 对不确定收益集 I 的损失为 1[I∩S=∅]，请求 0 的损失为 1[I⊆S]。两个指示函数都超模。后者可由包含关系直接验证四项不等式，前者对后者的自变量取补即可得到。故正规化的 d(S)−d₀ 对不交并超可加，特别有 d(S)≥d₀+Σᵢ∈S Δᵢ。这里没有用到 I 是区间，任意非空的已知可能收益集合也可。取每条记录最有利的具体收益，以及用一个含集合的指示函数表示一致行动，都可对照集合值观测的广义损失和凸合作博弈的增量性质。[Hüllermeier](https://arxiv.org/abs/1305.0698) · [Shapley，Cores of Convex Games](https://doi.org/10.1007/BF01753431)

由此得到下列精确费用公式。在每个 Δᵢ≤R 的收益 i 上，购买至少 kᵢ=2R+1−Δᵢ 次**确定为 i** 的追加观测，其他位置取 kᵢ=0。

- 必要性来自相容单点 S={i}。唯有价格确定为 i 的报价才能保证其诚实请求与空集不同。含其他可能价格的报价可取到该价格，使诚实日志与空集相同。两套候选剩余错误半径之和为 2R−Δᵢ，所以单点强制该次数。
- 充分性对多点 S 也成立。若 S 与历史相容，则其中必有 Δᵢ≤R 的点，否则不交超可加性推出 d(S)>f。被采购的该点有 kᵢ+Δᵢ=2R+1，其他采购点也取这个值，未采购点有 Δⱼ>R≥0。累加得到 Σᵢ∈S kᵢ + d(S)−d₀ ≥ 2R+1，正是与空集的剩余错误半径分离条件。
- 若报价费用非负、各有独立容量，逐点购买 kᵢ 个最便宜的精确报价即为全局最优。某个 i 的精确容量不足时，单点本身就是不足证书。本结论允许同一价格对应多档费用。区间探针仍可能区分特定多点备选，但不能降低由仍存活单点强制的总费用。

无历史时，结果简化为每点 2f+1 次。f=0 时是验证全零布尔函数须查询每个坐标的标准单点反例。Hanneke 与 Yang 的 *star number* 明确建模围绕同一假设、每个备选只在一个被查询实例上不同。这解释了必要性的几何结构，不能独自推出有区间历史时的充分性。一般群测试从整个池的交集生成反馈，可能在池中有一个异常点就答阳性；本实验则仅观察从报价集合中实际实现的一个未知成员，正宽区间一般不能保证检出单点。把两个问题的最优次数直接等同会低估成本。[Hanneke 与 Yang，Minimax Analysis of Active Learning](https://jmlr.org/papers/v16/hanneke15a.html) · [Zhigljavsky，一般反馈及距离条件](https://orca.cardiff.ac.uk/id/eprint/15201/1/Group%2520testing%2520lies.pdf) · [Klonowski、Kowalski 与 Pająk，含反馈与对手的群测试框架](https://arxiv.org/abs/2112.01340)

本次检索未核实有原文已经明示 **2R+1−Δᵢ 的逐价采购公式，并同时证明全部历史相容的多点备选均被覆盖**。这里可报告在上述契约下对链形阈值类和任意确定风险集作出的精确成本比较，给出回溯到每个单价例外和剩余额度的可验证证据。超模性、单点必要性、纠错距离以及按价取最便宜份数，各自已有明确依据。改为自适应计划、不同价格间共享隐藏实现、按组一次支付、受审计时行为改变，或使空基线已被历史排除，都需要重新表述问题。

## 检索记录

覆盖了 AAAI、AIES、ICML、NeurIPS、AAMAS、SIAM、Springer、INFORMS、PMLR、JMLR、arXiv 及作者公开原稿。交叉关键词包括 *lexicographic choice and compensatory preferences, protected values, non-trading stated choice, IRL identifiability, post-posed shield, proposed vs executed action, before_action, shadow evaluation, consent in agent benchmarks, active moral preference elicitation, nonadaptive search with lies, q-relaxed intersection, laminar matroid test cover, imprecise instances generalized loss, teaching sets, star number, Boolean OR certificate, supermodular singleton bound, error-correcting test cover, adversarial group-testing feedback*。本文没有全面核查未公开评估系统、所有近期预印本、专利和商用审计平台，未确认同一整套协议的优先权。
