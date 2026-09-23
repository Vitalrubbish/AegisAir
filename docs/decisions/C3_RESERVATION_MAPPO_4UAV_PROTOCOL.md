# C3-Reservation × MAPPO 四机接入协议

## 决策

将已有 `randomized_4` MAPPO checkpoint 接入 C3-Reservation 上游，但只赋予其
**名义二维速度生成权**。MAPPO 不决定安全等待点、通行顺序、目标服务锁存、清场点，
也不能绕过 Runtime Assurance。

```text
冻结 MAPPO actor / Go-to-goal
              ↓
       C3-Reservation
  HOLD / PASS / CLEAR / RETURN
              ↓
       Runtime Assurance
              ↓
             PX4
```

## 冻结对象

- 最多四架 UAV，实例为 `2,3,4,5`；
- 使用 `randomized_4` 的五个训练种子，不按本任务表现挑选模型；
- actor 接口固定为 44 维观测、2 维速度动作、8 个邻居槽、1.5 m/s 上限；
- 每个 checkpoint 的 SHA-256 固定在 manifest；
- C3、RA、初始状态、目标和 Gazebo seed 与上一轮 Reservation calibration 相同。

## Calibration 对照

- `G0`：Go-to-goal + C3-Reservation + RA；
- `G1-seed1..5`：冻结 MAPPO + C3-Reservation + RA。

每个条件必须启动全新的四机 SITL，独立落地并生成完整性文件，禁止在同一 PX4 进程内
连续复位不同名义策略。记录任务完成、碰撞、`min_rho`、QP 不可行、RA bypass、状态机
完整性、路径长度、控制努力和 RA 延迟。五个 MAPPO 条件中任一个未通过完整安全任务门，
本次“跨训练种子稳健复用”即为 No-Go，不允许事后挑选成功模型。

## 主张边界

该实验只能回答：冻结 MAPPO 名义策略能否在 C3-Reservation 与 RA 权限边界内完成
四机终点互换。即使全部通过，也不能声称 MAPPO 自身安全；calibration 结果不能直接
作为 sealed 论文统计证据。

## v1 calibration 结果与停止

全生命周期直连 v1 在首个冻结 MAPPO checkpoint（training seed 1）即达到预注册
No-Go：`collision=0`、`min_rho=0.433264`、QP 不可行和 RA bypass 均为 0，但 1200 步
全部停留在 `STAGING`，没有任何飞行器进入 `PASS`。因此停止 v1 的 seed 2–5，不按
当前任务表现挑 checkpoint，也不放宽等待点收敛门。

该结果表明旧 MAPPO 可以在 RA 后保持安全，却不适合承担精确安全等待点、清场点和
最终归位的全生命周期跟踪。

## v2：PASS-only 角色

v2 是独立新协议：MAPPO 在触发前提供冲突意图，触发后只允许为 C3 当前明确授权的
`PASS` 飞行器生成名义速度。`STAGING/HOLD`、`CLEAR`、`FINAL_RETURN` 和
`REVOKE_HOLD` 全部改由 C3 确定性目标跟踪执行，随后仍由同一 RA 过滤。

v2 不修改 v1 的 No-Go。它检验的是“旧 MAPPO 能否在更窄、可审计的权限角色中复用”，
不是对失败方案的参数补救。

v2 在 seed 1 上同样 No-Go：它可以从 `STAGING` 进入 `PASS`，但第二架获准机在
`PASS` 阶段无法收敛到服务目标。安全门仍通过，任务门失败。因此停止 v2 的其余训练
种子，不调整动作缩放或 checkpoint。

## v3：intent-only 顾问角色

v3 不再赋予 MAPPO 任何 PX4 闭环执行权。MAPPO 只在 C3 冲突预测前生成名义意图，
供冲突区进入时间和通行顺序计算使用；C3 触发后的所有实际速度均由确定性目标跟踪
产生，再由 RA 过滤。

这一角色与 v1/v2 的失败主张不同：它只检验旧 MAPPO 是否能作为不可信意图源接入，
而不是检验其导航控制能力。论文中若采用，只能称为 `advisory MARL intent`。

v3 的冻结顺序结果为：seed 1 与 seed 2 均完成完整生命周期且通过安全门；seed 3
在第 6 步才触发 C3，随后出现 `min_rho=-0.120074`、selected QP 不可行 2 步和
RA veto 2 步，并且未在 1200 步内进入 `COMPLETE`。虽然没有碰撞或 bypass，仍同时
违反正裕度门、QP 门和状态完整性门。因此 v3 为 No-Go，并按停止规则不运行 seed 4–5。

最终结论：旧 MAPPO 已完成三种权限角色的真实 PX4/Gazebo 接入审计，但当前 checkpoint
不能进入 C3-Reservation 主实验。保留其代码和负结果用于说明 `Assume AI can fail`，
主线继续使用确定性名义控制 + C3-Reservation + RA。
