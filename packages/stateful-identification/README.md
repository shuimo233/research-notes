# Stateful Identification 0.2.0

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

`errors` 接受一个非负整数或按规则名给出的剩余错读次数。每次复查均从同一初态开始，同一探针允许重复。`plan` 在声明的两个预算内先求最短固定清单，再优先选动作成本最低的同长清单。若预算内无法保证成功，返回 `None`；`run` 此时返回 `no_guaranteed_plan`，不调用观测器。凡已能保证选对动作时可以提前结束。调用方取得动作名后自行执行。辨识器的 `Domain.checks` 专用于模型验证，行动模式使用 `Domain.probes`。

已有实验清单可以直接交给 `assess`。把大量重试写成 `{探针元组: 次数}` 即可。计划失败时 `obstruction` 给出仍可能共同解释一条记录、且没有共同动作的一组规则。保证成功时可选 `witnesses=True`，提取令各组不可能同时存活的包含极小证据。保证以实际机制在表中、错读受限、动作有效性经过验收为前提。精确搜索最短清单及枚举无共同动作的规则组均可能很贵，适用于有限规模；已知清单可跳过搜索直接核验。

原有的 `identify` 接口用于无错读的确定性规则辨识。可用 `stateful-identify demo sqlite --truth FAIL` 运行内置示例。[行动证书的推导与复现](../../articles/joint-action-certificates/README.md)
