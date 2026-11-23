# 重建逐题模型、运行实验和核对数据

入口文章是[同一句前提和假设，推理器能只看这一题吗？](pointwise.md)。以下命令从本目录执行，解释器为 Python 3.13。原始权重和句子均从发布者获取，仓库保存生成器、决策、必要的分数及校验值。

## 准备锁定版本

```sh
python -I -S -B goemotions_fetch.py go-data
python -I -S -B go_model_fetch.py go-onnx --file tokenizer.json
python -I -S -B go_model_fetch.py go-onnx --file onnx/model_quantized.onnx
python -I -S -B rte_context_fetch.py rte-data
```

两个模型下载器都支持 `--host https://hf-mirror.com`。本次模型通过这个镜像取得，原 RTE 压缩文件从其公开发布地址获取。下载器核验发布版本对应的 Git blob 或 SHA-256。RTE 程序还将 ZIP 和 Parquet 的前提、假设、键和参考逐字对齐。[模型与 GLUE 文件摘要](rte_context_fetch.py) · [GoEmotions 模型摘要](go_model_fetch.py)

## 一次跑完

```sh
uv run --no-project --python 3.13 --with numpy==2.3.3 --with tokenizers==0.22.1 --with onnxruntime==1.23.2 --with onnx==1.19.1 --with duckdb==1.4.3 -- python -I -B point_reproduce.py go-data go-onnx rte-data fresh-point-run
```

最后一个路径是新的输出目录。命令顺序生成两个 ONNX 模型、从原文分词并完成四组对照、运行两个组序的封装、重算两项任务的结果、复核图并计时。默认 CPU 运行，每次 ONNX 会话使用 4 个算子内线程、1 个算子间线程。最耗时的是将每一条 GoEmotions 评论复制成一个完整批次的对照。各进程记录实际输出，`verification.json` 列出与仓库校验一致的产物。计时仅用于衡量本次机器的开销。图和数据在运行时使用本地文件。[复现入口](point_reproduce.py) · [运行开销记录](go-point-timing.json)

## 快速复核

只核对已发布的数值时，可以跳过模型推理。GoEmotions 部分只额外从 `go-data` 读取原词表和细类映射。RTE 的所有分数直接保存在 TSV 中，每个八位十六进制数对应一个 IEEE 754 float32 的比特图。

```sh
python -I -S -B point_results.py go-point-decisions.tsv go-model-batch.tsv go-data rte-point-logits.tsv
```

GoEmotions 决策表中的 `*_mask` 使用原 `emotions.txt` 顺序，一个细类占一位。对应的 `*_top` 为最高分细类索引。表还含有效 token 长度、原批宽度、实际批大小和原槽位。原始分数的比特摘要以 ID 字典序、28 个细类的原顺序、float32 小端连续数组计算。[完整决策表](go-point-decisions.tsv) · [摘要](go-point-logit-checks.json)

## 独立核对覆盖

结构程序将 Scan 内的节点在还原输入输出命名后逐一与锁定原图比较，逐一比较所有原始初始化张量，并在四个 opset 的小图上检查裁剪和掩码合同。第二份推理程序调用分词器自身的批量补齐接口。它在 GoEmotions 对 16 个确定抽取的完整批和最后一个短批分别复算四种实际输入，一共核对 524 项阈值集合及第一选择。RTE 直接从独立发布的 Parquet 读出所有句对，重算四种调用条件的全部 3,324 个 float32 值。两项都是同一项目内部的独立实现，外部团队尚未复现。[结构与决策检查](point-checks.json) · [独立重推理检查](point-reinference.json)

原图、导出图、ONNX Runtime 的 CPU 算子实现都有版本。更换模型、后端或机器后，位级一致性、运行耗时和参考答案上的准确率需要分别复核。
