# GoEmotions INT8 的组批与补齐敏感性有何先例

查证日期为 2026 年 11 月 23 日。**已有针对文本分类器的直接控制实验。** Kasa、Kasa 与 Negi 固定分类器及文本，分别改变补齐宽度、批大小和固定形状下的同批文本，记录逐例判决及分数变化，并用固定量化尺度消除其 CPU INT8 实验中的同批样本影响。更早的 ONNX Runtime 问题记录已经对同句单独推理、不同补齐宽度、浮点与动态量化进行对照。将这些机制分开测试、检查标签翻转、提出固定尺度或边界附近重算，都已有公开先例。[Kasa 等，2026 年 10 月预印本，图 4、附录 B.11 和 E.3](https://arxiv.org/html/2610.09111v1) · [Microsoft ONNX Runtime #8625，2021 年 8 月](https://github.com/microsoft/onnxruntime/issues/8625)

本次核查未定位到对 SamLowe 这份确定的 GoEmotions 导出图，在原测试顺序上将“自然宽度单例、匹配宽度单例、同文复制批、自然异文批”四个判决沿途连接，并关联两套逐人投票参考的已发表测量。可报告的成果是这一特定模型和评测协议上的外部复现，以及两套参考如何改变这些翻转的计分含义。那四个条件的具体组合不能支持“首次发现组批会改变文本分类”的主张。[公开导出版](https://huggingface.co/SamLowe/roberta-base-go_emotions-onnx/tree/90ee0c1c4796d370e68968687b8ba51fc11224f4) · [本项目的粗标签对账](goemotions.md)

## 可以直接对照的实验

| 来源 | 所做的比较 | 解读范围 |
| --- | --- | --- |
| [ONNX Runtime #8625](https://github.com/microsoft/onnxruntime/issues/8625) | 第一手报告用相同的 100 句做测试，额外细查两句。报告者每次仅送入一句，改变补齐长度，比较浮点与动态量化 ONNX，并改变补齐位的位置编号。维护者另解释整批数据共用尺度会使组批与单条计算不同。 | 单条补齐宽度对照、观察实际分类质量和讨论补齐位都早在 2021 年出现。具体模型的位置编号会影响能否迁移其解释。 |
| [Kasa、Kasa、Negi](https://arxiv.org/html/2610.09111v1) | 作者训练 180 个文本分类器，五个数据集含 SST-2、SST-5、AG News、Emotion 与 IMDb。相同 checkpoint 和文本下，区分相同批形状改同伴、相同同伴改宽度，以及容许同伴长度一同改变的联合干预。另检查同一排程重复运行、换目标位置、换推理精度。 | 已经直接回答“宽度和组员能否分开测”。其 Emotion 基准为 Saravia 等的数据。研究正文没有对应本项目的 GoEmotions 逐细类阈值、七粗类与双参考。他们的许多统计口径是最高分的单类是否改变。 |
| [Thinking Machines Lab，2025](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/) | 给出批次不变性的定义，展示同一调用可重复但跨批形状数值会变，设计批次不变的归约、矩阵乘法与注意力核。 | 重点在浮点 GPU 大模型。即使每次重复同一批都得到一致结果，跨排程仍需另行检验。 |
| [Foerster 等，2026](https://arxiv.org/abs/2604.26505) | 原作者系统记录多种框架中，运行时为整批适配量化参数会让一个输入的结果受其他输入影响。 | 其机制与固定形状替换同批输入有关。本文只采用这一已知数值依赖，讨论公开测试集的离线计分。 |
| [Khatri，2026](https://arxiv.org/abs/2609.31796) | 逐条比较多种浮点格式及批大小下的探针判决，量化总体准确率会遗漏多少相互抵销的变化。 | 判决来自生成模型的激活探针。逐例报告翻转并与总指标并列的做法已有明确先例。 |

## 锁定模型的图与运行机制

SamLowe 分别发布全精度和动态量化 INT8 的 ONNX 文件，给出针对 28 个细标签的阈值评估和按批补齐示例。本轮只读解析本地已校验的 INT8 原始 GraphProto，在序列化图中计得 **1,038 个节点，其中 DynamicQuantizeLinear 与 MatMulInteger 各 98 个**。文件 SHA-256 为 `0c1981c5b479674747911c8e2228f0c4ec90bf47bf66e830f7d4fc62be082958`，作者仓库版本为 `90ee0c1c4796d370e68968687b8ba51fc11224f4`。原图计数支持引用这个具体算子。运行时可融合算子，图中节点数不代表实际执行内核数，也不能据此把某一个阈值翻转定位到某一个层。[作者的 ONNX 模型卡](https://huggingface.co/SamLowe/roberta-base-go_emotions-onnx) · [固定的 INT8 文件](https://huggingface.co/SamLowe/roberta-base-go_emotions-onnx/blob/90ee0c1c4796d370e68968687b8ba51fc11224f4/onnx/model_quantized.onnx)

ONNX 的 DynamicQuantizeLinear 以一个输入张量为单位产生**标量**尺度和零点。规范用全张量 ReduceMin、ReduceMax，包含零后按 8 位整数范围确定尺度。若该张量含多个样本或补齐位置，其中任一元素成为新极值都可能改变该次量化的网格。因此，最长序列相同的两批仍可能使同一文本得到不同的量化值。注意力掩码决定注意力如何使用补齐位，而该量化算子的接口只有输入张量，不能从掩码推断其归约跳过哪些位置。是否确有新极值并传播到特定输出，需要额外的中间数值证据。[ONNX 算子定义与函数体](https://onnx.ai/onnx/operators/onnx__DynamicQuantizeLinear.html) · [ONNX Runtime 量化说明](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)

量化粒度已有成熟替代方案。ZeroQuant 针对包括 BERT 系的模型，对每个 token 的隐藏向量单独动态定尺度，论文及消融给出精度和代价；SmoothQuant 比较了逐张量、逐 token 与逐通道，并研究离群激活如何影响尺度。固定校准尺度同样是已有的静态量化方法，Kasa 等实际验证其解除自身实验中的共享尺度依赖。这些技术改变了推理部署，可能影响绝对分数与速度。单独切换量化粒度也无法保证所有浮点内核、所有设备、所有批形状逐位一致。[ZeroQuant §3](https://arxiv.org/pdf/2206.01861) · [SmoothQuant 图 3](https://proceedings.mlr.press/v202/xiao23c/xiao23c.pdf) · [Kasa 等的干预与代价](https://arxiv.org/html/2610.09111v1)

## 四个条件能说明什么

下表将原发布模型、分词、右截断、阈值和目标文本固定。复制批和异文批还应固定张量形状、目标所占位置与该行的 token、mask。正常评估的异文批可以沿用发布测试文件的连续顺序，并公开末批的实际大小。[本项目的排程与环境](go-layout-protocol.md) · [Kasa 等的匹配干预定义](https://arxiv.org/html/2610.09111v1)

| 配对 | 可观测的改变 | 解释边界 |
| --- | --- | --- |
| 自然宽度单例 → 补至该异文批宽度的单例 | 仅改输入的补齐宽度，整次调用仍只有目标一条。 | 宽度、补齐位及形状可共同改变执行。不能只凭结果断定是哪项内部数值运算所致。 |
| 匹配宽度单例 → 同文复制批 | 将已补齐的同一输入复制到每一行，输出比较沿用目标槽位。 | 对理想相同输入，复制不会扩大量化前张量的一份相同元素的极差；规模、内核选择及上游舍入仍可能变化。 |
| 同文复制批 → 同尺寸异文批 | 在相同形状和槽位上，替换其他行的正常文本和掩码。 | 直接测出固定形状时批中内容的影响。与整张量量化机制吻合只是因果线索，真实中间尺度若未经测量，就不能断定是具体哪个极值、补齐 token 或统计离群点。 |

三个相邻差额的**有符号分数变化**可沿规定路径相加得到端点差。对于单个二元判决，端点是否相异等于三次翻转标志的异或。中途翻转两次能使端点相同，翻转总次数和端点不同数因而是两种统计量。同样，同一条评论的两个细类翻转可能被组内 OR 遮蔽。宜同时报告细类、粗类、逐评论变动率及按两套参考计算的 F1。这样的分解依赖指定的干预顺序，无法单独代表任意排序或日常请求分布下的发生概率。[逐例翻转与聚合指标的先例](https://arxiv.org/abs/2609.31796) · [本项目固定分类器的计分先例说明](goemotions-model-prior.md)

## 检索范围

检索覆盖 ONNX 算子规范、微软 ONNX Runtime 文档与原问题记录、SamLowe 模型发布页、arXiv、PMLR 论文和 Thinking Machines 原实验。关键词包括 `same text different prediction serving context fixed shape peer composition quantization`、`ONNX Runtime BERT quantize_dynamic same sentence different padding and position IDs`、`batch-invariant classifier dynamic quantization per-tensor per-token scale`、`SamLowe roberta-base-go_emotions-onnx batch padding replicated sample`、`GoEmotions singleton repeated versus mixed batch quantized classifier threshold`。对匹配原文另查 GoEmotions、重复样本、量化尺度与应用的数据集；未索引的复现实验、未公开的评测与软件实现可能存在。原始节点计数来自本地锁定文件，仅限该导出版本。
