# 已知候选版本，能给出完整的 npm 声明范围审计吗？

我们把此前的[按需查询框架](frontier.md)用于九个开源项目的历史 npm 锁文件。只给程序看每个位置的候选版本，以及待审计的依赖关系。每次查询揭示一个位置的精确版本。程序须对每条关系给出可复验的标签：候选父包未声明普通依赖、子包版本满足声明、子包版本超出声明范围。

105 项需查询的任务中，精确策略读了 821 次，固定覆盖加追问读了 825 次。降幅为 0.485%，低于[事前登记](https://github.com/shuimo233/research-notes/blob/d577eae4de4aec711fe1f156fe79aa064d44888a/articles/consent-audit/npm-query-protocol.md)的 0.5% 门槛。更显著的结果来自在查询之前合并候选版本：107 项任务的 7,903 个候选实例可以缩到 4,233 个等价类，且每个候选组合的标签都不变。

## 哪些版本可以合并

把一条依赖关系的三态标签写成二元表。若同一位置的两个候选值在每条相邻关系表中有完全相同的切片（作为依赖方时比较行，作为被依赖方时比较列），就把它们放进同一类。双向关系分别比较两组标签。任选两个类的代表元，一次替换关系表的一个坐标，标签保持不变，因此整张审计表可以由这些类来表示。

这也是保持所有标签的最粗逐位置划分。若两个版本有不同的切片，必然有某个相邻位置的候选值使二者产生不同的标签。固定这个相邻值和其他位置的选择，只改变这两个版本，任何把它们映成同一局部摘要的方案都会给两个不同标签相同的表示。这个结论比较的是对候选支持笛卡尔积保留全部关系标签的逐位置编码。

精确策略对各位置采用独立先验，类的权重等于成员的先验权重之和。在这项假设下，读到类内的精确版本不会进一步更新未读位置的分布，后续规划只须知道该版本所在的类。若位置之间相关，类内成员可能影响其他位置的后验，这时要重新检查规划是否可以合并。[相关读数实验](mixture-query.md)

## 九份锁文件的回放

使用 [固定的 Git 提交](npm-query-pins.json)，按提交时已发布的同主版本稳定版本排序，每 16 个形成一个候选带。锁文件决定真实位置、待审计的边以及版本所在的带。版本在策略发出查询之前保持隐藏。107 项不同任务保留了 1,616 条带任务位置的有向关系实例，涉及 1,143 个位置实例。两项任务的标签无需查询即可确定。

| 读法 | 105 项查询任务的总读取数 |
| --- | ---: |
| 读取每个有多个原始候选的位置 | 1,031 |
| 最优固定覆盖加追问 | 825 |
| 整任务贪心 | 822 |
| 精确自适应规划 | 821 |
| 知道完整真值后才能选取的最短证书 | 813 |

三种策略共用候选合并。按模型中的均匀独立先验，固定覆盖和精确策略的期望总量分别为 784.139 和 783.606。真实回放中精确策略比固定覆盖少读 4 次、比贪心少读 1 次。候选实例减少 46.44%，预处理中的 SemVer 判断在复用重复范围后从 90,931 次降到 47,390 次。读取次数和比较次数是两项不同的指标；版本带是用锁文件人工遮蔽构造的，部署时的网络延迟、人工成本和端到端耗时未测量。[逐项记录](npm-query-ledger.jsonl.gz) · [按项目计数](npm-query-results.json)

独立的 Node 程序重算了冻结数据中的 97,206 个候选版本对标签。同时对照了九份原始锁文件与 575 份注册表清单快照，核验字节哈希、版本带、对应路径和声明范围。另一个 Python 程序按原始表重建合法查询条件，核对 315 条非空策略路径、105 个最短证书和 105 个期望最优值，并对 12 项小任务用未合并的候选版本重算根节点最优值。[声明核验器](npm_query_verify.cjs) · [规划核验器](npm_query_check.py)

三条真实的声明范围差异来自 TypeScript 同一个快照。锁文件中的 `@vscode/extension-telemetry@1.5.2` 声明了下表范围，根项目的 `overrides` 字段明确选择了表中的精确版本。这样的输出可用于标记哪些上游声明被项目配置覆盖。审计合同只判断原始声明，实际安装规则需要同时读取根项目配置。[TypeScript 锁文件](https://github.com/microsoft/TypeScript/blob/0b0aeb31e416c280bcbef7d7734aa21e7d999cdd/package-lock.json) · [同提交的根项目清单](https://github.com/microsoft/TypeScript/blob/0b0aeb31e416c280bcbef7d7734aa21e7d999cdd/package.json) · [npm overrides](https://docs.npmjs.com/files/package.json/#overrides)

| 依赖 | 上游声明 | 锁中版本 |
| --- | --- | --- |
| `@microsoft/1ds-core-js` | `^4.4.1` | `4.3.11` |
| `@microsoft/1ds-post-js` | `^4.4.1` | `4.3.11` |
| `@microsoft/applicationinsights-web-basic` | `^3.4.1` | `3.3.11` |

## 与已有工作的位置

Freuder 在 1991 年给出的邻域可交换性已经包含逐一比较相邻约束的思路。这里将它用于保留三类审计输出，并把类概率接入现有查询控制器。PacSolve 针对依赖求解和更换版本，npm 的查询命令对已有依赖树运行选择器。本次预先固定候选位置和待回答的边，只决定索取哪些精确版本。现有检索支持把这轮工作写成一个有独立核验器的实证迁移；世界范围的优先权仍无法确认。[Freuder 原论文](https://cse.unl.edu/~choueiry/Documents/FreuderAAAI91.pdf) · [PacSolve](https://arxiv.org/abs/2203.13737) · [npm 依赖查询](https://docs.npmjs.com/cli/npm-query/)

## 复算和试用

在本文目录运行。Python 回放和询问工具使用标准库。Node 核验器需要 npm 自带的 `semver@7.8.1`，构造程序同时用 `@npmcli/arborist@9.7.0`；将 `NPM_MODULES` 替换为包含这两个库的目录。回放输出目录须尚未创建。

```text
node npm_query_verify.cjs NPM_MODULES npm-query-fixtures.json.gz npm-query-source.json
python -I -B npm_query_run.py npm-query-fixtures.json.gz reproduced
python -I -B npm_query_check.py npm-query-fixtures.json.gz reproduced
python -I -B npm_query_inquiry.py npm-query-example.json --ask
```

交互样例在记录中挑选，用来展示查询过程，省略了精确值。从冻结输入的同一行取对应位置的版本序号即可重放。其中精确策略和固定覆盖各读 4 次，贪心读 5 次。对于自己的数据，可以按[样例结构](npm-query-example.json)提供位置、候选版本和关系表，将交互工具的输入回调替换为版本源。程序只向该回调索取实际需要的版本。返回读取记录和全部关系标签，证书可以通过检查与已读值一致的关系表切片来复验。

若要从源重新构造，将 [固定版本](npm-query-pins.json) 的锁文件按 `RAW_LOCK_ROOT/owner--repo/package-lock.json` 放置，然后运行 `node npm_query_prepare.cjs NPM_MODULES RAW_LOCK_ROOT normalized`。程序在 `RAW_LOCK_ROOT/packuments` 缓存 npm 目录响应。将 `RAW_LOCK_ROOT` 作为核验器的最后一个参数可额外检查原始字节。随文冻结了复算所需的候选、声明和标签，以及[原始来源校验清单](npm-query-source.json)。npm 目录响应持续变化，从在线目录重新抓取时原始字节和可取版本可能有变化。
