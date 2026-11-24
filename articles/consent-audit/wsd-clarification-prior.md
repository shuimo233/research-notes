# 五套 WSD 评测能检验怎样的词义澄清成本

2026 年 11 月 24 日查证。Raganato、Camacho-Collados 与 Navigli 的 ALL 提供了 SemCor 之外的另一批词元级参考义项。它适合检验一个限定的问题：给定两处名词，若能准确揭示其中一处的词义，是否足以确定两个义项在 WordNet 中的关系。资料原本标注的是词义。词对关系由冻结词典导出，询问成本由实验协议定义；原赛事没有请人按不同顺序回答这一组问题。[统一评测原论文 §3–4](https://aclanthology.org/E17-1010.pdf) · [本项目评分前协议](wsd-clarification-protocol.md)

## 五个来源与多金标

| 统一评测中的来源 | 原任务及影响选样的差异 |
| --- | --- |
| Senseval-2 | 英语 all-words 部分，早期标注使用 WordNet 1.7，统一版包括四类内容词。[原任务报告](https://aclanthology.org/S01-1005/) |
| Senseval-3 | 取英语 all-words task 1，WordNet 1.7.1。词汇样本任务另有自己的选词和评估单位。[Snyder 与 Palmer 的原报告](https://aclanthology.org/W04-0811/) |
| SemEval-2007 | 取 Task 17 的细粒度 all-words 部分，原用 WordNet 2.1；统一版此项仅有名词与动词。2007 同年另有粗粒度任务，不能混算。[Pradhan 等的原报告](https://aclanthology.org/S07-1016/) |
| SemEval-2013 | 取 Task 12 的英语数据，原用 WordNet 3.0，只选名词。原说明明确允许在歧义时给多个义项，并鼓励可以确定时只给一个。[原任务 §2](https://aclanthology.org/S13-2040.pdf) |
| SemEval-2015 | 取 Task 13 的英语 WSD 部分。原赛事同时涉及多语消歧和实体链接；统一版对应 WordNet 3.0。收录文档来自生物医学、数学与计算、社会议题三个领域。[Moro 与 Navigli 的原报告](https://aclanthology.org/S15-2049/) · [统一版的选取说明](https://aclanthology.org/E17-1010.pdf) |

统一团队将旧版义项映到 WordNet 3.0，高置信映射先自动接受，其余人工检查，必要时重标或移除。五个来源的词性覆盖、文档题材和选词范围原本就不同，仅留同句共现、两端均有可用标注的名词，会进一步改变样本组成。合并总数是这批位置组合的加权结果，不能视为对五次同条件独立复验取平均。多个软件仓库分发相同文件可用于核验文件版本，不能增加独立标注来源；跨语料收录也不自动保证词项与文档来源完全无交叉。[统一流程与原语料组成](https://aclanthology.org/E17-1010.pdf)

多个金标表示发布者接受多个答案，并未向本实验提供这些答案的发生频率或投票权重。还应区分多个 sense key 与它们最终映到几个不同 synset。若两处词元分别允许多个 synset，独立枚举可接受集合的笛卡尔积，可以判断目标关系是否在所有组合中固定，也可给每个词对位置的询问数上下界。原任务没有为该词对提供联合分布，多个位置组合如重用同一词元，各自的极值也未必能一起达到。保留单 synset 主表与多金标边界，可以避免任取第一个标签造成的虚假确定性。以人工多义项判断研究细粒度词义适用程度已有直接词义学先例。[SemEval-2013 的多标规则](https://aclanthology.org/S13-2040.pdf) · [Erk、McCarthy 与 Gaylord 的上下文词义研究](https://aclanthology.org/J13-3003.pdf)

## 词义、词典路径与决策

Princeton WordNet 把词义组织为 synset，并在名词资料中区分普通上位指针与实例上位指针。由这些指针可达所得到的上下位关系、两个 synset 是否相同、以及两边均不可达，都是指定词典和指定边类型下的判据。同句出现两个词，不能据此将词典路径解释为说话者在该句中断言了二者的关系。Renner、Denis 与 Gilleron 已用 WordNet 义项层级和词对消歧研究有方向的词汇蕴含；HyperLex 还专门采集人对词对的分级蕴含判断。两者分别提供词典方法与直接关系标注的对照。[Princeton 的指针定义](https://wordnet.princeton.edu/documentation/wninput5wn) · [WordNet 词对消歧与词汇蕴含](https://aclanthology.org/2023.findings-emnlp.615/) · [HyperLex 原论文](https://aclanthology.org/J17-4004/)

将候选义项对视为可能世界、将词典关系视为输出，同一输出下的世界构成决策等价类。已获答复所剩的世界全部同答时就可以停，这是已有的等价类判定问题。Javdani 等还处理同一假设可接受多个行动、决策区域重叠的情形。这里需分清三个集合：多金标是评估时仍可接受的义项，候选集是询问前允许的世界，决策区域取决于最终要回答哪个问题。把四种关系投影成“甲是否严格下位”时，若“是”只对应原先的一种关系，任何能在真实正例上保证回答“是”的证书也已确定原来的四类答案；若合并两个方向为“可比”，证书才可能包含不同的正向关系。这是重新划分等价类的直接推论。某种短证书存在，也不等于无需预知真值的策略能在每个世界选到它。[Golovin、Krause 与 Ray 的等价类判定](https://proceedings.neurips.cc/paper_files/paper/2010/hash/1e6e0a04d20f50967c64dac2d639a577-Abstract.html) · [Javdani 等的决策区域判定](https://proceedings.mlr.press/v33/javdani14.html)

## 问一次与花多长时间

Joshi 等对六名词典编纂者进行印地语词义标注眼动实验，把时长分为形成词义假设、寻找上下文线索、比对释义并作选择；不同词类的时长有明显差异。Brown、Rood 与 Palmer 的三个实验还分别改变候选数量和词义区分粒度，观察到更粗的区分可提高其任务上的标注一致率。因而“准确揭示一个端点的义项记一次”是一项可审计的操作计数，不能直接折算为人工秒数、劳动成本或回答正确概率。[Joshi 等的实测，§§3–5](https://aclanthology.org/N13-1088.pdf) · [Brown 等的标注实验](https://aclanthology.org/L10-1630/)

在医疗 WSD 上，Wang 等已比较多种索取标注的策略，在三个既有语料上用模拟标注过程测量达到模型准确率目标所需的标注量。他们研究训练一个可处理后续文本的分类器；此次询问要解决的是当前词对的词典关系，正确性要求是剩余的所有候选均同答。可报告的新观测是各来源、预定词对与扩大选词范围、不同目标问题下，这批参考义项实际能够省掉哪些询问，以及省下的是否包括严格上下位正例。[Wang 等，Interactive Medical Word Sense Disambiguation Through Informed Learning](https://academic.oup.com/jamia/article/25/7/800/4953034) · [此次实验的比较范围](wsd-clarification-protocol.md)

检索覆盖 ACL Anthology、统一评测发布方、Princeton WordNet、NeurIPS、PMLR 与 JAMIA 的原始论文或机构说明。主要检索词包括 “Raganato ALL five all-words multiple senses”、各年度任务名与 “multiple senses annotators”、“word sense disambiguation hypernym pair clarification cost”、“equivalence class determination decision regions overlapping tests” 和 “word sense annotation time eye tracking labeling effort”。未在原文中定位到对同一登记词对、五套外部语料、四种关系问法和单／多金标成本边界的完整实测。此次查新只读取论文与发布说明，没有打开外部逐词答案文件或计算实验结果。
