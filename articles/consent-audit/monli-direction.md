# 强制推理器只选一个方向，为什么整对得分上升，逐题却错得更多？

“一个人没有任何哺乳动物”可以推出“他没有狗”，反过来无法推出。让同一个模型分别判断这两个方向，它起初两边都答“推不出”，得一题。即使提前告诉推理器两向中必有一个成立，它按自己的相对分数还是选择了“没有狗 ⇒ 没有哺乳动物”，得零题。这是 MoNLI 否定测试文件的头两行。模型的两个方向在批量服务里都能稳定复现。[原始数据](https://github.com/atticusg/MoNLI/blob/5bf388ad669a28500c1d46dba3b7d665d62b0536/nmonli_test.jsonl) · [逐题分数](monli-direction-logits.tsv)

在全部 100 对否定题上，强制选择方向后，整对答对从 **6 对升到 9 对**，逐道答对却从 **42/200 降到 18/200**。我们在看分前已约定两项都提高才算改善，因此主要实验失败。它给出了一项有实际用途的核验：对于承诺修复逻辑不一致的推理系统，整对得分可能因修复规则自身的性质而只能持平或上升；需要另算它修复了多少原来判错的方向，又牺牲了多少原来判对的方向。[事前登记](https://github.com/shuimo233/research-notes/blob/02ce2552336abbf2591c89f69410f2a8f87b9000/articles/consent-audit/monli-direction-protocol.md)

## 先把两类正确数算清

把一句话作为前提、另一句作为结论，运行一次三分类推理器；再交换两句运行一次。每个方向的分差为“蕴含”分数减去“中立”和“矛盾”中较高的分数。只在任务已知恰有一个方向成立时，保留分差较高的那个方向。若分差相等就弃答，两道都计入分母且均不得分。调用只需要两个方向的分数，不输入参考答案。这次两个数据子集都没有平分。[实现中的 choose_direction](monli_direction_score.py)

设 $H$ 是原先两向给出同一判决的对数，$K$ 是这 $H$ 对中修复后选对方向的对数。原先已经只肯定一个方向的对，其肯定方向分差非负、另一方向分差为负，修复会保留它。两边同判的每一对原先恰有一道答对；修复选对得两道，选错或弃答得零道。因此有

$$
\Delta\text{整对正确数}=K,\qquad
\Delta\text{逐道正确数}=2K-H.
$$

整对分数天然偏爱这类修复。原来整对答对的题都会保留，有一对修对，它就会上升。逐道分数要求更高，必须在原本同判的题中选对超过一半。任何保留原有唯一方向、并对每个同判对选定一个方向或弃答的程序，都可以据此查验收益。这个计数关系依赖对内恰有一个真方向及上述弃答口径。约束推理已有系统研究，逐项损失与整组损失不同也是已有结论。[约束推理](https://cogcomp.seas.upenn.edu/papers/RothYi04a.pdf) · [Hamming 与整组零一损失](https://www.mathematik.uni-marburg.de/~eyke/publications/dembczynski_762.pdf)

**进一步查新找到了这两条式子的直接先例。** Herald Bao Di 的最小对评测工具在 2026 年 11 月 4 日的固定提交中，已经写明逐项正确率与整对正确率之差是同判比例的一半，也写明强制选择相对原整对正确率的增加量等于同判但排序正确的比例。把正确率还原成题数，就得到上面两条关系。原工具用于语言可接受度；这里直接采用它的计数解释，增量在于自然逻辑任务的预登记对照和逐题证据。Gardner 等也早已使用“一组对照题全部答对”衡量模型表现。[Di 的固定版本与指标说明](https://github.com/heralddi/minimal-pairs/blob/a3c78c0d0769b5d047fc09626e1a0a22a9ee1f64/README.md#metrics) · [对照组一致性](https://aclanthology.org/2020.findings-emnlp.117/)

## 在已发表的自然逻辑测试上验算

数据采用 Geiger、Richardson 与 Potts 发布的 MoNLI。这套题利用上下位关系考查蕴含方向，例如“狗”是“哺乳动物”的下位词。使用冻结的 MNLI DistilBERT INT8 模型，测试时不输入数据中的词汇层级、模板或极性标记，无训练、无阈值选择。负极性用作者标作测试的文件。正极性用作者的正极性文件，合并重复的有序句对后计分。[MoNLI 论文](https://aclanthology.org/2020.blackboxnlp-1.16/) · [模型版本](https://huggingface.co/Xenova/distilbert-base-uncased-mnli/tree/fddd480db7392a87114a6813c6acb5ede13ff4ee)

| 题集与运行方式 | 原先同判 $H$ | 修对 $K$ | 原先 → 修后整对正确数 | 原先 → 修后逐道正确数 |
|---|---:|---:|---:|---:|
| 否定 100 对，稳定单例 | 30 | 3 | 6 → 9 | 42 → 18 / 200 |
| 否定 100 对，普通八条组批 | 26 | 5 | 4 → 9 | 34 → 18 / 200 |
| 正极性 736 对，稳定单例 | 233 | 188 | 487 → 675 | 1,207 → 1,350 / 1,472 |
| 正极性 736 对，普通八条组批 | 214 | 171 | 506 → 677 | 1,226 → 1,354 / 1,472 |

对稳定单例，否定题的 30 对分成两组，24 对原先两向都判蕴含，6 对两向都判非蕴含。修复挑对 3 对、挑错 27 对，净失 24 道。另有 64 对本来就坚定地选反，修复保留了全部 64 个错误方向。正极性题的修复则净增 143 道，因而这项修复在这里有实测收益。两份文件的句型和词项分布不同，这组比较不能识别仅添加否定词的因果效应。两类题也用了同一个模型，不能概括其他模型或自然语言推理的总体表现。[全部四类判决及计数](monli-direction-scores.json)

## 放进一个可复核的推理框架

对于已经由外部任务保证“正反两个方向恰好一个成立”的题，可以给出双向分数，再用 `choose_direction(forward_logits, reverse_logits)` 选择方向或弃答。对自己的有标注数据，`audit_pairs` 接受任意数量的三元组 `(正向分数, 反向分数, 正确方向)`，方向写为 `forward` 或 `reverse`，每组三个分数依次为蕴含、中立、矛盾。返回原始四类判断、修复对错、弃答数及逐题净收益。若任务中允许两句等价或彼此无关，需要先说明如何识别适用对象。这项实验并未训练这种识别器。[标准库评分接口](monli_direction_score.py)

为了把服务端数值漂移和方向错误分开检验，我们用最短单例执行，再按行号的 SHA-256 改序，将题目八条成批送入先前实现的逐题 ONNX 封装。两种执行的 5,016 个 float32 分数逐位相同。另一路程序重新读取发布者的原句，分别分词、手工补齐，复算三种配置的全部 15,048 个分数，用数组运算独立核对两项指标，并覆盖平分及换序的小例。它们是在同一项目内交叉核验的结果。[独立复核](monli_direction_check.py) · [复核记录](monli-direction-checks.json) · [逐题执行的原始实验](pointwise.md)

查新覆盖自然逻辑单调性、前提与结论交换、蕴含方向预测、逻辑约束解码，以及整组与逐项损失。Truong 等已经在同一批 200 道 MoNLI 否定题上测过其他模型。我们能具体归属的工作是这份预先登记的冻结模型测量、两个方向相反的收益，以及把它们解释到每一道修复的可执行核验。用模型名、数据文件、交换评分与组批方式交叉检索，未找到报告这一组合逐题结果的原文。检索范围仍有边界。[同一批否定题的已有评测](https://aclanthology.org/2023.starsem-1.10.pdf) · [交换前提与假设](https://www.cs.cmu.edu/~epxing/papers/2019/Wang_etal_AAAI19.pdf) · [预测蕴含方向](https://aclanthology.org/2024.eacl-short.36/) · [行为测试 CheckList](https://aclanthology.org/2020.acl-main.442/)

### 实际验收需要核对多少条答案

如果验收目标是判断本批题上修复的净影响，已经只肯定一个方向的题可以跳过，程序会证明它们对差值的贡献为零。在原先同判的 $H$ 对中，设已核对且选对的有 $k$ 对，尚未核对且修复确实选择了方向的有 $u$ 对，分差相等的弃答已确定得零分。逐道正确数的净变动必在 $[2k-H,\ 2(k+u)-H]$，整对净变动必在 $[k,k+u]$。只假定每对恰有一个真方向、允许各对独立赋值时，两端都有相容的答案配置。区间完全落在零的一侧，即可在未读完所有参考答案时判定这个有限批次的正负收益。这些是确定性界限。用分歧选择应标注的样本已有直接先例。[按分歧抽取验证记录](https://www.nature.com/articles/s41598-023-48017-4) · [主动比较预测模型](https://proceedings.neurips.cc/paper_files/paper/2012/hash/92fb0c6d1758261f10d052e6e2c1123c-Abstract.html)

用上游已知标签离线模拟验收，把原本同判的题按两个句子摘要组成的固定哈希排序。这个回放是在主结果出来后补做的。否定 100 对只读 **17 对**，其余答案无论怎样，净变动都在 **−28 至 −2 道**；读完 30 对即知精确净损失为 24 道。正极性 736 对只读 **146 对**，净变动已在 **+1 至 +175 道**；读完 233 对即知精确净收益为 143 道。这分别是这一顺序首次判明方向的读数。没有新招募标注员或测量人工工时；其他队列的首次判定位置可能不同。[队列摘要、区间与核对条数](monli-direction-review.json)

独立使用时，`--pairs` 读取由题对 ID 映射到正反两个分数数组的 JSON，无需原始标签。`--judgments` 可选，提供已经核对的题对 ID 及其正确方向。程序返回仍需核对的 ID 和两种收益的可能区间。仓库另有包含平分、同判、单向判决的穷举夹具，为 81 种标签可见情况逐一构造所有相容答案，核验区间端点。[可复用核对工具](monli_direction_review.py)

### 复算命令

在本目录运行，输入可使用前一篇的已校验缓存。`monli_direction.py` 下载并校验两份源文件，缺少封装图时从固定源图导出；TSV 输出请使用新文件名。下列第三行可仅用 Python 3.13 标准库运行，最后一行以另一种方式复算并对照已发布计数。[评分程序](monli_direction_score.py)

```sh
python -I -B rte_context_fetch.py rte-data
uv run --no-project --python 3.13 --with onnx==1.19.1 --with numpy==2.3.3 --with tokenizers==0.22.1 --with onnxruntime==1.23.2 --with duckdb==1.4.3 -- python -I -B monli_direction.py monli-data rte-data point.onnx replay.tsv
python -I -B monli_direction_score.py replay.tsv
python -I -B monli_direction_review.py --study replay.tsv
uv run --no-project --python 3.13 --with onnx==1.19.1 --with numpy==2.3.3 --with tokenizers==0.22.1 --with onnxruntime==1.23.2 --with duckdb==1.4.3 -- python -I -B monli_direction_check.py monli-data rte-data point.onnx replay.tsv monli-direction-scores.json
```
