# 在肯定句上取证、在否定作用域内反转：MoNLI 先例核查

查证日期为 2026 年 11 月 23 日。**MoNLI 作者已经给出了本实验的上层算法。** Geiger、Richardson 与 Potts 在图 1 的 INFER 中先取得替换词的词汇蕴含方向，再按否定有无返回反向或原向。论文 §3 用一个具体句对说明，去掉两句中的否定会交换两个方向的标签；图 1 后的分析研究 BERT 是否表示并利用这个中间关系。在当前检索范围，尚未定位到把下面两种取证方式、同一冻结 INT8 检查点及其逐题对照一起报告的原文：一是在改写后的完整肯定句对上重跑双向评分，二是从同源已标肯定句提取可追踪的词项路径，仅当路径没有给出唯一方向时才调用模型。可归属的工作是这两种具体实现和在锁定题目上的检验。分解、方向反转及利用传递路径都是已知方法。[MoNLI 原论文 §3、图 1 及 §6](https://aclanthology.org/2020.blackboxnlp-1.16.pdf) · [作者数据版本](https://github.com/atticusg/MoNLI/tree/5bf388ad669a28500c1d46dba3b7d665d62b0536) · [本次评分前登记](monli-scope-protocol.md)

## 同一道否定题可以怎样利用肯定证据

| 原文 | 已经做到的步骤 | 本次对照所问的更窄问题 |
| --- | --- | --- |
| [MacCartney 与 Manning，An Extended Model of Natural Logic](https://nlp.stanford.edu/pubs/natlog-iwcs09.pdf) | 形式化局部语义关系经过上下文算子的投影。向下单调环境会交换正向与反向蕴含。 | 在已知且受限的板式中，如何由一个冻结的句对分类器恢复足够可靠的局部方向。 |
| [Geiger、Richardson 与 Potts，2020](https://aclanthology.org/2020.blackboxnlp-1.16.pdf) | 在同一数据上显式区分词汇关系和否定。词对来自 WordNet 的上下位替换，原文还区分整题输出与中间变量，并用探针和表征交换检验模型。 | 本项目另造肯定对应句，将黑盒双向输出当作中间关系的近似。原文中从隐藏状态预测该关系与这种整句重复调用是不同的实测。 |
| [Helwe 等，TINA，2022，表 1、附录 A.2](https://aclanthology.org/2022.findings-emnlp.301.pdf) | 明确使用“若 A 蕴含 B，则非 B 蕴含非 A”，并利用可导出的变换及标签构造训练材料。 | 该文推导的是命题否定下的规则。本项目在 MoNLI 的词项替换位置使用已知的向下单调性，模型推理时重新评分，权重固定。 |
| [Feng 等，2022，§3 及表 2](https://aclanthology.org/2022.tacl-1.14.pdf)；[Strong 与 Vlachos，2024，Zero-NatVer](https://aclanthology.org/2024.findings-emnlp.991/) | 前者用神经模型估计局部关系并作上下文投影和组合；后者在事实核验中使用指令模型、组块对齐和自然逻辑操作，没有为任务训练另一个自然逻辑分类器。 | 用模型供应局部信息、由显式推理规则给出结论，以及无任务训练地组合两者，都有先例。此处比较的是同一冻结 NLI 接口读取肯定句和原否定句所得方向。 |
| [Leveraging Affirmative Interpretations from Negation，2022](https://aclanthology.org/2022.emnlp-main.393/)；[Semantic Inversion, Identical Replies，2025](https://aclanthology.org/2025.emnlp-main.1088.pdf) | 前者收集带否定句与肯定解释的配对数据，测试其对 NLI 等任务的帮助。后者对照同一模型面对相关肯定、否定查询的回答，以区分基础知识错误和否定推理失效，并测试任务分解等提示方法。 | 肯定改写、对基础知识作配对测量都已有先例。这里刻意取消局部否定、估计相反方向；保持原句意思的肯定释义通常不会触发该反转。 |
| [Truong 等，2023，表 5 及图 5](https://aclanthology.org/2023.starsem-1.10.pdf) | 用其他模型、提示与少样本设置在作者发布的 200 道 MoNLI 否定测试题上评估，也检验提示中显式提到否定的作用。 | 本文负句直接评分、无条件反选、肯定改写评分、肯定改写评分后反选四路，使用了不同的信息。比较结果应注明与原作者测试文件、上游训练文件各自的关系。 |

直接反转负句输出只需要原句分数。肯定句取证则需要另外一次双向评分；两者可能在同一题上给出不同答案。这个差异可以通过逐题输赢测量。若在某一分割上二者准确率接近，不能单凭与原始负句的改善数，就说肯定改写提供了额外信息。模板内的 *not a single*、*any*、*at all* 具有各自的作用，删除否定词不能普遍生成想要的肯定命题。当前改写的目标是给同一 NLI 模型提供可计算的对照输入。改写句未经独立人工复标，原始否定题答案仍是评价对象。真实文本中的否定范围、被否定成分、多个量词的辖域都需要额外识别。[本次改写和负控的逐项定义](monli-scope-protocol.md) · [NaN-NLI 的细粒度否定构造](https://aclanthology.org/2022.aacl-main.65/)

## 有来源的词汇边、传递与回退

**蕴含图中的方向和传递路径是直接先例。** Berant、Dagan 与 Goldberger 将命题模板作为节点，引入有向蕴含边，并明确说明在词义固定时可以沿任意长度路径传递。同文也说明为什么词面相同而语义不同的节点不能自动合并。Chen 与其合作者进一步用文本蕴含模型对类型化谓词构造的模板句估计局部边，再以软传递约束处理图的稀疏性。因此，用句对获得边，以中间词项连接两条已知关系并形成有向证明，均有清楚的前身。[Berant 等，2010，§3](https://aclanthology.org/P10-1124.pdf) · [Entailment Graph Learning with Textual Entailment and Soft Transitivity，2022](https://arxiv.org/abs/2204.03286)

可追溯证明同样已有公开实现。EntailmentBank 要求用明确的已有事实，经中间结论得到答案，作者发布了事实标识和证明步骤。de Jong 等让模型提供带方向的词汇知识，再由形式证明器判断这些知识是否足以证明句级蕴含。它们说明了“语言模型出事实、形式系统出证明”以及“结论附可核验的前提链”各自的既有归属。[Dalvi 等，Explaining Answers with Entailment Trees](https://arxiv.org/abs/2104.08661) · [作者的数据格式及证明字段](https://github.com/allenai/entailment_bank) · [de Jong 等，2026 年预印本](https://arxiv.org/abs/2609.32491)

本次图分支的特殊之处是**边的来源可以逐题重建**。仅从 PMoNLI 已标为蕴含的正极性句对抽取“窄词→宽词”边，记录首条来源的文件行号；给负极性题查询两向的最短可达路径，仅在单向可达时反转输出。图有冲突、图未覆盖或词项抽取失败时，再由同一冻结模型读取肯定改写。这样可以分别报告直接重用同源词对、借助中间词的间接覆盖、以及模型回退的正确数。PMoNLI 标注为这一分支提供了监督，即使没有进行梯度训练，也不应把图路线称作“无标注”或把词对重用计成陌生词义泛化。源行证书核实的是程序依赖哪些原始标注；自然语言词义是否沿链保持一致仍是额外假设。原作已用受控词汇划分讨论过记住词对与系统泛化的区别。[评分前登记的抽边、可达与回退条件](monli-scope-protocol.md) · [作者的词汇划分与基准构造](https://aclanthology.org/2020.blackboxnlp-1.16.pdf) · [蕴含图的词义条件](https://aclanthology.org/P10-1124.pdf)

## 查新边界

截至上述日期，在 ACL Anthology、arXiv、Stanford NLP 原始论文和 MoNLI 作者仓库中检索。用到的查询包括 `MoNLI without negation positive counterpart reverse entailment direction zero shot`、`PMoNLI NMoNLI remove negation score swapped premise hypothesis`、`NLI negate both premise and hypothesis revert affirmative score contraposition`、`lexical relation natural logic polarity projection zero-shot`、`entailment graph template sentences lexical relations transitivity`、`entailment proof source facts paths`。逐项对照原文中的输入、是否读已有标签、是否更新模型、在何处反转、评估分割和对照项。

此次没有核实到与登记的四路冻结评分及“PMoNLI 标签图优先、肯定句评分回退”全部吻合的既有公开测量。可检验的差异是这份部署在指定数据上的逐对结果、在无条件反选之上的实际增益或退化，以及直连、纯多步和无路径三类的证据与成本。现有检索不足以证明某项组装方法从未被使用。
