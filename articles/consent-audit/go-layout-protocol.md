# 批量部署复核约定

单例、不补齐的主结果已发布于 `fb0cf3c`。随后以原测试细标签核对，单例全精度 macro-F1 为 0.449909，INT8 为 0.448501；模型卡分别显示 0.450 和 0.447。模型卡给出了按批次最长长度补齐的 ONNX 调用示例。这里补做另一套部署方式的实测，尚未运行该方式或查看其预测。[锁定的初次结果](https://github.com/shuimo233/research-notes/blob/fb0cf3c10fdab76f4692f78aa65a82fa7a4e0e17/articles/consent-audit/go-model-ranking.md) · [发布者的 ONNX 示例](https://huggingface.co/SamLowe/roberta-base-go_emotions-onnx)

按原 test.tsv 顺序将连续八条作为一批，最后一批保留原长度。先对每条执行相同的 128 token 右截断，再右补齐到该批最长长度，使用词表 PAD ID 及正确的 attention mask。权重、软件版本、CPU、线程数、标签映射及阈值均沿用单例实验。分别运行全精度及 INT8。按每个部署报告与本身单例预测相比有几条细类和粗类决策不同，逐套列出两个粗参考的 micro-F1 及原细类 macro-F1。对这一新部署下的全精度阈值与 INT8 阈值继续使用相同的整条审计，报告可达分差、是否能翻转及最少切换数。预先接受批量与单例结论相同、变弱或不同的结果。本比较共同改变了输入批量与补齐布局，观测差异不能单独归因于其中一个因素；作者原测的批次、机器及运行时未在此复现。
