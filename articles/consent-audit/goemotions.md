# 把 27 种情绪归成 6 大类，先合并还是先数票？

GoEmotions 的测试集中有 5,427 条评论。按作者公开的映射，把已有细标签换成六种情绪大类，并保留中性一类；再从同一批原始打分出发，让每位标注者先把自己的选择归入大类，然后逐类数是否有至少两人支持。**468 条评论的结果改变了，占 8.62%，合计多出 486 个“评论—大类”标签。** 一个独立发布的同题材粗标签文件与第一种算法逐条吻合。这让我们可以确切指出第二种问题会在哪些已发布记录上得到不同答案。[官方论文](https://aclanthology.org/2020.acl-main.372/) · [官方映射程序](https://github.com/google-research/google-research/blob/7951440944924ac61b6e2f9a2a3c715834005c40/goemotions/replace_emotions.py) · [第三方文件核对](goemotions-derivative-results.json)

## 一条读得懂的例子

测试评论 `eczt8co` 有三份打分。下表保留标注者各自选了什么，省略正文与人员编号。它是按预先规定的 ID 顺序取到的第一个符合条件的例子。

| 打分单 | 选中的细类 |
| --- | --- |
| 第一份 | anger、disappointment、disgust、fear、sadness |
| 第二份 | disappointment |
| 第三份 | disapproval |

只有 disappointment 在同一细类上得到两票，映射后是 sadness。若先在各张打分单内归类，第一人选的 anger 和第三人选的 disapproval 都属于 anger 大类，于是 **anger 和 sadness 都得到两人支持**。这两种做法都遵循“两票”和同一份分类表；差别只在于我们希望两人对具体情绪取得一致，还是只需对上位类别取得一致。[原始键、打分与结果](goemotions-results.json) · [作者的分类表](https://github.com/google-research/google-research/blob/7951440944924ac61b6e2f9a2a3c715834005c40/goemotions/data/ekman_mapping.json)

形式上，某个细类已获两人支持，一定能让其上位类别获得两人支持。反过来，两人可能因不同细类而支持同一上位类别。这种单向包含关系对任意固定人数门槛都成立。析取条件下先对理由投票和先形成个人结论的区别，在判断聚合文献中有直接先例。与此相连的 [WMT 研究](mqm-consensus.md) 给出了遗失评审关联后仍可恢复哪些多数意见的条件。[List 对析取判断的讨论](https://eprints.lse.ac.uk/5829/2/The_discursive_dilemma_and_public_reason_%28LSERO%29_.pdf)

## 与原发布文件逐项对账

读取 211,225 份逐人打分，覆盖 58,011 个评论 ID。每份记录包含 28 个二值标签，包括 neutral。原发布的训练、开发、测试合计 54,263 条，全部能用评论 ID 接回原始记录，三者无重叠。按细类先数不同标注者，**54,263 条都能逐项重现原发布的细标签**。同人同例重复行数为零，3,411 份标为 very_unclear 的打分单都没有肯定标签，也均未被解释为中性票。本研究使用原基准的固定两票规则，原始测试集每例实际有 2 至 5 名标注者，因此有些例子的两票只表示两人支持。[分割与原始数据说明](https://github.com/google-research/google-research/blob/7951440944924ac61b6e2f9a2a3c715834005c40/goemotions/README.md) · [完整结果与人数分布](goemotions-results.json)

| 数据范围 | 评论数 | 先按人合并会改变粗标签的评论数 |
| --- | ---: | ---: |
| 测试 | 5,427 | 468 |
| 开发 | 5,426 | 444 |
| 训练 | 43,410 | 3,483 |
| 仅在原始标注中、没有进入三个分割 | 3,748 | 2,822 |

最后一行比较两种从原始打分计算的规则。这里有 2,822 条原本没有任何细类获两票，却有大类能获两票。这批评论适合研究筛选规则的影响，不能把它们直接并入原测试集后仍沿用原基准名称。测试集新增的 486 个标签中，joy 有 196 个，anger 和 surprise 各 113 个，sadness 有 59 个，fear 有 5 个。只有一个细类的大类 disgust 和仅映射到自身的 neutral 都没有变化，符合形式推导。[逐类及逐分割数据](goemotions-results.json)

## 是否影响别人正在分发的标签

第三方 SkyWater21 已发布 `labels_ekman`，并公开了标签顺序和映射。我们对固定版本的测试 Parquet 文件校验 SHA-256，按原评论 ID 连接并比较标签集合。它与“映射原发布细标签”的 5,427 条结果全部相同；与“先逐人合并，再取两票”在上述 468 条记录上有别。这是对现成公开数据产品的逐条核对。是否有人用这个版本训练特定模型、模型排名会如何改变，都没有在本实验中测量。[数据作者的映射说明](https://huggingface.co/datasets/SkyWater21/en_go_emotions/blame/main/README.md) · [固定版本的测试文件](https://huggingface.co/datasets/SkyWater21/en_go_emotions/blob/36b96f67e724026cac6210b857d1fe388bd46048/simplified_ekman/test-00000-of-00001.parquet) · [独立读盘结果](goemotions-derivative-results.json)

对使用这个标签评测的研究者，具体区别在于要声明系统该预测什么。如果目标是“至少两人都读出了这一大类”，可使用逐人归类后数票的列；如果目标是重现已有发布基准，可使用从发布细标签映射出的列。两列可以按同一测试 ID 并排导出。它们都描述标注者对文字的解读；本数据没有评论作者对自身情绪的同时测量。

## 哪些已有先例，哪些是本次产物

- Demszky 等发布了原始逐人打分、两票过滤、多层情绪分类的模型实验与粗类转换脚本。本研究直接采用作者的两票门槛和分类表。CARE 研究也已使用基于 GoEmotions 的粗粒度映射。[原研究](https://aclanthology.org/2020.acl-main.372/) · [CARE 原文](https://aclanthology.org/2022.conll-1.5/)
- Öhman、Koufakou 和 Diegoli 于 2026 年 11 月公布了对这批逐人数据的研究，考察标注者选择标签的宽窄、类别边界以及不确定响应。逐人保留分歧这一研究方向已有直接先例。第三方也已有粗类数据集，本次逐条比对使用其中一个固定文件。[逐人分歧研究及方法](https://arxiv.org/html/2611.01539v1) · [已发布粗标签的说明](https://huggingface.co/datasets/SkyWater21/en_go_emotions/blame/main/README.md)
- 本次形成的是一个可执行的版本审计，内容包括原始细标签全数复原、两种聚合次序逐条对账、对未入选条目的筛选效应计数，以及可供现有评测系统接入的双列导出。查新在本次检索范围内未找到提前报告相同 468 条测试差异和 486 个标签差异的原文。全球优先权及其他版本上的数量均待额外证据。[计算前公开的研究口径](https://github.com/shuimo233/research-notes/blob/af5feeaf5e74b76ad4d7b0e3c3db1f754b7135d9/articles/consent-audit/goemotions-protocol.md)

## 复现与接入

主计算与独立 SQLite 实现仅使用 Python 标准库。下载器锁定三份原始数据的 Google Cloud 对象代次与发布者校验值，分割、词表及映射锁定 Git blob。第一条分析命令打印汇总并生成按 ID 排序的 JSONL，每条保留 `published_ekman` 与 `two_reporters_ekman` 两列。输出路径须为新文件。第二套程序另行读取原始文件，以 SQL 的 `COUNT(DISTINCT voter)` 重算，每一个测试 ID 的两列标签都要核对。[主程序](goemotions_order.py) · [独立 SQL 检验](goemotions_reference.py)

```sh
python -I -S -B goemotions_fetch.py go-data
python -I -S -B goemotions_order.py go-data --write-test-comparison test-comparison.jsonl
python -I -S -B goemotions_reference.py go-data goemotions-results.json test-comparison.jsonl
```

复核第三方 Parquet 另需 DuckDB。下例使用 1.4.3。程序会在读标签前检查下载文件的完整 SHA-256。本次运行通过 Hugging Face 镜像取得该固定对象，校验值与发布元数据逐字节匹配。[读盘程序](goemotions_derivative.py) · [核对用摘要](goemotions-derivative-results.json)

```sh
curl -fL -o test.parquet https://huggingface.co/datasets/SkyWater21/en_go_emotions/resolve/36b96f67e724026cac6210b857d1fe388bd46048/simplified_ekman/test-00000-of-00001.parquet
uv run --no-project --with duckdb==1.4.3 -- python -I -B goemotions_derivative.py test.parquet test-comparison.jsonl
```
