# GoEmotions 粗标签次序与固定分类器评估的先例

查证日期为 2026 年 11 月 23 日。已有研究覆盖了三件事：在 GoEmotions 上将每位评审的细标签映至 Ekman 类再汇总、保持被评输出不动而更换人工参考、用两个固定分类器的预测计数判断 F1 名次能否改变。此次可独立报告的结果是指定版本的 GoEmotions 测试集、两条硬标签规则和冻结预测共同确定的命中数、分数差，以及实际出现或未出现的严格逆序。检索没有定位到同时具备这三个实验条件并给出逐项对账的既有工作。这个结论只涉及下列检索范围。[Wu 等，附录 B.3](https://arxiv.org/html/2606.05376v1) · [Kulshreshtha 等，固定输出换参考](https://arxiv.org/html/2610.03825v1) · [Fernández-Barrios 等，F1 排名的精确界](https://arxiv.org/html/2611.01712v1)

## 两种参考标签分别来自哪里

Demszky 等在 ACL 2020 原文 §5.1 描述了精细标签的筛选。先删掉仅一人选择的细类，只保留至少剩余一类的评论，然后随机分割。公开测试集有 5,427 条评论。论文给出了细类到六种 Ekman 情绪的映射，另保留 neutral，在数据集上实际评估过粗分类器。官方脚本 `replace_emotions.py` 读取已含标签编号的 TSV，把旧标签替换为相应组并去重。因此，“取已发布细类再映射”和“在这些粗类上评价”都已有直接实现。公开 JSON 只列六种情绪组，neutral 独置才与论文的七类口径一致。测试集的门槛是至少两位评审，样本评审数可以变化。[原论文 §5.1 及表 5、6](https://aclanthology.org/2020.acl-main.372.pdf) · [发布方的数据说明](https://github.com/google-research/google-research/blob/7951440944924ac61b6e2f9a2a3c715834005c40/goemotions/README.md) · [作者的替换脚本](https://github.com/google-research/google-research/blob/7951440944924ac61b6e2f9a2a3c715834005c40/goemotions/replace_emotions.py) · [六个非中性组](https://github.com/google-research/google-research/blob/7951440944924ac61b6e2f9a2a3c715834005c40/goemotions/data/ekman_mapping.json)

SHALA-LLM 附录 B.3 明确写出从 GoEmotions 原始逐人回答开始，先映到 Ekman 情绪，再跨评审汇总并归一化。他们剔除少于三名评审提供有效情绪标签的样本，按主要类别分层抽样，研究目标包括预测人类标注分布。他们的目标与此次硬判据存在两处实质差异：前者产出归一化类别分布，本次逐类判断有无两个不同评审支持；前者重新筛选与抽样，本次固定原发布测试 ID。仅凭该文的描述，也不宜断言其逐人重复细类的去重实现与本项目逐位相同。[Wu 等，附录 B.3、C 及 §4](https://arxiv.org/html/2606.05376v1)

Öhman、Koufakou 与 Diegoli 已经用带评审标识的 GoEmotions 逐人数据分析相邻细类，包含 anger/annoyance、fear/nervousness、joy/excitement 等六对。其研究将评审整体偏好多选和特定情绪对的边界分开，并明确讨论仅保留投票边际会失去什么。另有 Öhman 与 Koufakou 的多标签情绪实验对照硬标签与软票份额监督，评价含 micro-/macro-F1。这些原文使“标注归并、类别边界及评审关联会影响情绪实验”已有充分直接的研究归属。[逐人 GoEmotions 研究 §§3–4](https://arxiv.org/html/2611.01539v1) · [多标签情绪数据的汇总与评估](https://arxiv.org/abs/2606.21069)

本项目早一轮已经对齐官方 ID、原始评审与另行发布的粗标签测试文件，报告了 5,427 条中 468 条变化，共增加 486 个“评论—粗类”标签，且发布细标签能逐项从原始打分重建。这个对账给出了本轮可以使用的嵌套参考集。后续冻结模型实测的新增信息，是这些额外正标签中模型命中了多少，以及同一批输出在两种问题下究竟得几分。这个有限测试集描述也有入选条件，原本没有任何细类获两票的评论没有进入测试集。[本项目的逐项对账](goemotions.md) · [有限样本计数](goemotions-results.json)

## 更换参考与固定输出的名次

| 第一手研究 | 覆盖到哪一步 | 与本次精确比较的区别 |
| --- | --- | --- |
| [Kulshreshtha、Dalmia、Mukherji，2026](https://arxiv.org/html/2610.03825v1) | 在六语个人信息识别数据上固定被评输出，交换两个原始标注、发布参考与复审参考。作者量出每个输出的 F1 变动及两输出分差的交互变化，并单列排序能否维持。 | 单位为实体片段，参考替换源自其标注与复审机制；此次同一批评论的额外正标签由可重放的粗类投票次序产生。 |
| [Fernández-Barrios 等，2026 年 11 月预印本](https://arxiv.org/html/2611.01712v1) | 已知两分类器预测相异样本的真实标签后，仅凭两种共同预测样本的正例数便能给出所有可能补全下的 F1 名次界。包含冻结输出、定量容差与逆序反例。 | 此次两套参考均可观测，改变的标签也可能位于两分类器预测相异的单元。已知端点计分仅需直接计算。 |
| [Northcutt、Athalye、Mueller，2021](https://arxiv.org/abs/2103.14749) | 在原基准与纠正测试标签上比较分类器，观察到部分模型相对次序受标签修改影响。 | 该工作追查错误标签；“细类已获两票”与“粗类已获两票”分别对应可解释的问题，无需把其中之一判作标注错误。 |
| [Bonagiri 等，STABLEVAL，2026](https://arxiv.org/abs/2605.02122) | 比较多数票、潜在正确性与评审混淆模型对系统排名稳定性的影响。 | 主要问题是评审异质性与抽样下的稳定性。此次量的是确定数据集上改变操作顺序的结果。 |

## micro-F1 的精确差额

在同一组“评论—粗类”单元上，记已发布细类映射所得正例为 $A$，逐人先合并得到 $B=A\cup D$，其中 $D\cap A=\varnothing$。冻结一个预测集 $P$，置 $a=|A|,\ d=|D|,\ p=|P|,\ t=|P\cap A|,\ h=|P\cap D|$。聚合所有标签后直接代入 Dice/F1 定义，得到

$$
F_A=\frac{2t}{p+a},\quad F_B=\frac{2(t+h)}{p+a+d},\qquad
F_B-F_A=\frac{2((p+a)h-td)}{(p+a)(p+a+d)}.
$$

分母为正且 $d>0$ 时，分数上升当且仅当 $h/d>F_A/2$。新增命中比例与旧 F1 的一半相等时，两次计分完全一致。$d=0$ 时差额为零，遇全空集合须采用预先声明的零分母规则。这个等式是 F1 定义的代数推论。Lipton、Elkan 与 Narayanaswamy 对预测决策阈值已有 F1 一半的经典结果，其中校准概率与最优分类阈值有特定关系。本式固定实际预测，给的是已知有限参考新增标签后的得分，没有使用分类器校准假设。[Lipton 等的原论文](https://arxiv.org/abs/1402.1892)

对固定输出 $P_1,P_2$，依次定义 $p_i,t_i,h_i$。旧名次由 $t_1(p_2+a)-t_2(p_1+a)$ 的符号决定，新名次由 $(t_1+h_1)(p_2+a+d)-(t_2+h_2)(p_1+a+d)$ 决定。两符号相反才是严格逆序，任一符号为零应报并列。即使两者都漏掉全部新增标签，也可能因为预测量不同而交换名次。举例令 $a=2,d=2,(p_1,t_1,h_1)=(1,1,0),(p_2,t_2,h_2)=(5,2,0)$，两者从 $2/3>4/7$ 变为 $2/5<4/9$。这个构造解释了比较时必须同时报告预测量与命中数。它没有测量任何模型的实际排名。[更广的固定分类器 F1 排名分析](https://arxiv.org/html/2611.01712v1)

## 可复用模型与复现边界

- SamLowe 的公开模型以 RoBERTa-base 为底座，用 GoEmotions 微调，28 个细类各输出一个概率。模型卡说明采用多标签损失、3 个训练轮次，列出了阈值 0.5 的测试结果。其评估笔记本使用 Hugging Face 的 `go_emotions/simplified` 测试集，执行严格的 `probability > threshold`，表头汇总 F1 使用 `average='macro'`。本次七粗类 micro-F1 另有分母。SamLowe 是此 checkpoint 的发布者，GoEmotions 原作者的论文基线是 BERT-base。[SamLowe 模型卡](https://huggingface.co/SamLowe/roberta-base-go_emotions) · [作者的计分笔记本](https://github.com/samlowe/go_emotions-dataset/blob/main/eval-roberta-base-go_emotions.ipynb) · [GoEmotions 原作者的模型与数据](https://aclanthology.org/2020.acl-main.372/)
- 同作者发布的 `onnx/model.onnx` 为全精度，`onnx/model_quantized.onnx` 为 INT8，分别提供 0.5 阈值评估。冻结具体文件版本、精度、分词器、标签顺序、截断选项、logits 到逐类 sigmoid 的函数与不等号，才能重放边界判定。先按细类二值化再 OR，在统一阈值下等于对组内最大概率作同一不等号比较。若改为概率相加，或只取概率最高的单一细类，就改动了预测规则。[作者的 ONNX 模型卡及两个文件](https://huggingface.co/SamLowe/roberta-base-go_emotions-onnx)
- 模型和基准共用 GoEmotions 的数据体系，模型卡及作者笔记本已公开查看测试分数和选阈值的结果。两种参考上的比较可以固定完全相同的预测，作同一有限测试集的配对计量。若在这批测试数据上寻找逆序阈值，应标记为探索性例子，同时报告搜索范围。一个 checkpoint 的两个阈值对应两个操作点，各训练得到的两个 checkpoint 才能支持“两种受测模型”的措辞。公开说明不提供训练日志级的逐文本去重证明，不能据此推出其与预训练语料完全无交叉或这批数据能独立代表其他平台。[模型发布者的评估与阈值搜索](https://huggingface.co/SamLowe/roberta-base-go_emotions) · [官方数据覆盖及局限](https://github.com/google-research/google-research/blob/7951440944924ac61b6e2f9a2a3c715834005c40/goemotions/README.md)

## 检索范围

查阅 ACL Anthology、arXiv 原文、Google Research 的官方发布、SamLowe 的 Hugging Face 模型卡与 GitHub 评估代码。交叉检索词包括 `GoEmotions Ekman rater mapping before after aggregation two annotators`、`GoEmotions coarse fine agreement frozen SamLowe predictions threshold`、`emotion taxonomy granularity prior to majority vote`、`gold reference change fixed outputs micro F1 rank reversal`、`add positive labels test set F1 disagreement partial identification`。进入同数据的细类边界、独立评审软标签、分类层级、不同参考以及分类器排名文献检查实际实验对象。未索引的笔记本、私有模型以及尚未公开的研究不在覆盖范围内。旧标签每个具体元素是否保留、本次实际逆序及数值大小，都应由已发布 ID 和冻结模型产物独立验证。
