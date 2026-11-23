# 将逐条语义迁移到自然语言蕴含判断

首轮情绪任务的 Scan 封装在已运行的两个组序中都匹配单例。为检验迁移，另选 GLUE 原始 RTE 开发集全部条目，以及独立发布的 `Xenova/distilbert-base-uncased-mnli` 量化图，锁定提交 `fddd480db7392a87114a6813c6acb5ede13ff4ee`。截至这个约定，已核查模型与验证集的版本、校验值、三分类映射，尚未运行 RTE 预测。评估的是前提和假设之间的蕴含关系。三类按最大 logit 取答，ENTAILMENT 对应原二元任务中的 entailment，NEUTRAL 和 CONTRADICTION 均对应 not_entailment。使用原开发集全部条目，不训练、不调阈值。原 ZIP 与 NYU 分发的固定 Parquet 分别导入并逐键对照。[GLUE 原论文](https://openreview.net/forum?id=rJ4km2R5t7) · [模型发布](https://huggingface.co/Xenova/distilbert-base-uncased-mnli) · [GLUE 固定分发](https://huggingface.co/datasets/nyu-mll/glue/tree/bcdcba79d07bc864c1c254ccfcedcce55bcc9a8c/rte)

使用作者 tokenizer 的原生句对格式，最长 512 个 token，按最长优先截断。保持前提、假设次序；普通模式分别单条及按原文件顺序连续八条、批内最长右补齐。把逐例裁剪和 Scan 封装迁移到这个独立的三分类图。按原顺序八条和按 ID 的字符串 SHA-256 顺序八条复核。主要判断是两种组序中每一个样例的三类及二类决定是否与原模型单例相同。报告原有二元准确率、普通组批改变多少个判断、封装后残余多少，以及完整 logits 是否逐位一致。预期行为是保留单例输出；若封装改变准确率或数值，须原样公布。没有对未见文本或不同硬件建立统计或数值保证。

工程层面尝试共用同一导出器，模型允许有不同的 opset 和输出类数，支持已核验的两输入、单 logits、确定性编码器接口。在模型原图中发现难以兼容的节点时记录原因。第二项验证针对自然语言蕴含基准上的既有模型行为，不足以证明一般逻辑推理能力增强。
