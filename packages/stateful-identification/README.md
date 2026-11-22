# Stateful Identification 0.5.0

有限、可重置系统的黑盒辨识与行动规划。需要 Python 3.10 或更高版本，运行时仅用标准库。在仓库根目录执行 `python -m pip install ./packages/stateful-identification` 安装。在本目录执行 `python -B -m unittest discover -s tests` 验证。

## 允许错读时选动作

0.2.0 新增 `ActionPlanner`。每条规则声明哪些动作可用，探针返回整数 0、1 或布尔值。下例中有四台副本，恰好一台停机。两个读数表示停机副本编号的两位，可能有一个读错。最终选择的副本须可用。

```python
from stateful_id import ActionPlanner, Budget, Domain

probes = [("first",), ("second",)]
names = ("00", "01", "10", "11")
rules = {name: (lambda q, n=name: int(n[probes.index(q)])) for name in names}
domain = Domain("replicas/v1", rules, probes)
allowed = {down: set(names) - {down} for down in names}
planner = ActionPlanner(domain, allowed, errors=1)
schedule = planner.plan(Budget(queries=2, cost=2))
assert planner.assess(schedule, witnesses=True).guaranteed
readings = iter([0, 1])
result = planner.run(lambda q: next(readings), Budget(2, 2))
assert (result.status, result.action) == ("ready", "10")
```

### 0.5.0 的计数范围与核验提示

当三维类结构判据无法处理一组规则时，规划器会尝试用两条或四条原始行的线性和缩小各探针的正读数范围，再精确求解剩余问题。若已经有共同计数记录，只需在保留的区间内搜索即可还原到原清单。

调用 `problem, claim = planner.audit(schedule, count_hints=True)` 会附上用于推导边界的原始行名。接收端按自己的业务表重算整数和；行被剔除时，相应提示随之失效。默认仍检查每份行证据删去任何一行后都可行。若业务只要求行动保证，可显式使用 `minimal=False` 避免逐行提取极小证据。检查器对该声明返回 `guarantee only checked`。接收方可用 `verify(problem, claim, require_minimal=True)` 或 CLI 的 `--require-minimal` 要求逐删核验。未启用两个新选项时继续导出旧格式。两种新字段需要 0.5.0 或更新的接收端。

### 0.4.0 的独立核验

下面接着上面的副本示例，将可信问题表和待审查声明分别保存。接收方可以从自己的配置生成问题表，再把对方给出的声明拿来检查。若两份文件都由同一来源提供，核验结论只对文件所描述的模型成立。

```python
import json
from pathlib import Path
from stateful_id.audit import verify

problem, claim = planner.audit(schedule)
assert verify(problem, claim).status == "verified"
for name, value in [("problem.json", problem), ("claim.json", claim)]:
    Path(name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
```

安装包后运行 `stateful-audit problem.json claim.json`。也可只把包内的 `stateful_id/audit.py` 复制到接收方，然后用 `python -I -S audit.py problem.json claim.json` 核验。退出码 0 表示证据有效，1 表示输入或声明被拒绝，2 表示搜索节点额度耗尽。用 `--max-nodes 500000` 可改默认额度 100,000。具体反例只需直接计算错配，无需搜索。通过核验的每份行证据都满足删去其中任何一行就有解，某些实例还可能有行数更少的其他证据。

JSON 中 `probes` 的顺序同时定义了预测位与反例正读数的顺序。重复数、错读额度与反例计数使用无前导零的十进制字符串，零写成 `"0"`，使 JavaScript 中转也能保留超过安全整数范围的奇数。每条规则的 `bits` 仍用数值 0、1。`problem_sha256` 绑定问题表内容与顺序，供接收方和自己的可信问题表核对。

### 0.3.0 的记录回放与反例

`decide(schedule, ones)` 可直接读取已采集的探针计数。`ones` 必须给每种已安排探针提供 1 的次数，包括零。返回 `ready`、`ambiguous` 或 `conflict`，以及仍可解释实测记录的规则。它不会调用观测器。

```python
actual = planner.decide(schedule, {probes[0]: 0, probes[1]: 1})
assert actual.action == "10"
short = [probes[0]]
failed = planner.assess(short, witnesses=True)
example = planner.decide(short, dict(failed.counterexample_ones))
assert example.status == "ambiguous"
```

固定清单无法保证行动时，`counterexample_ones` 是所返回冲突组可以共同解释的一份可达记录。当结构判据识别出互相兼容的一组列、且余下列没有三角交叉时，新版直接用行间距离给出联合判定。请求证据时，从两种奇偶各至多四条原始行开始删除冗余行。一般表仍采用精确后备求解。

`errors` 接受一个非负整数或按规则名给出的剩余错读次数。每次复查均从同一初态开始，同一探针允许重复。`plan` 在声明的两个预算内先求最短固定清单，再优先选动作成本最低的同长清单。若预算内无法保证成功，返回 `None`；`run` 此时返回 `no_guaranteed_plan`，不调用观测器。凡已能保证选对动作时可以提前结束。调用方取得动作名后自行执行。辨识器的 `Domain.checks` 专用于模型验证，行动模式使用 `Domain.probes`。

已有实验清单可以直接交给 `assess`。把大量重试写成 `{探针元组: 次数}` 即可。计划失败时 `obstruction` 给出仍可能共同解释一条记录、且没有共同动作的一组规则。保证成功时可选 `witnesses=True`，提取令各组不可能同时存活的包含极小证据。保证以实际机制在表中、错读受限、动作有效性经过验收为前提。精确搜索最短清单及枚举无共同动作的规则组均可能很贵，适用于有限规模；已知清单可跳过搜索直接核验。

错配预算覆盖整份清单的规则在联合判定时可以忽略，返回实际记录时仍计入存活规则。两个完整示例及独立整数规划对照见本次研究。[0.3.0 的证明、实验和计时](../../articles/weighted-conflict-audit/README.md)

原有的 `identify` 接口用于无错读的确定性规则辨识。可用 `stateful-identify demo sqlite --truth FAIL` 运行内置示例。[行动证书的推导与复现](../../articles/joint-action-certificates/README.md)
