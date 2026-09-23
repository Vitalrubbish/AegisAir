# C3 闭环（PX4/Gazebo）fail-closed 恢复协议

- 状态：**冻结协议，待 smoke；尚无正向结论。**
- 协议 ID：`aegisair-c3-closed-loop-v1`。

## 0. 为什么现在做这个

C3 轻量仿真已证明确定性规则恢复 R1 相对 RA-only R0 改善预注册恢复指标，且
`safety bypass = 0`。但证据只在轻量点质量仿真里。论文核心命题是"确定性 fail-closed
恢复才是真安全边界，预测/AI 不可信"，因此需要把这条恢复线搬到 PX4/Gazebo 闭环。

本协议是 C2/C2′/C2-predictive 之外的一条**独立问题**：它不依赖、不修复、也不复述那三条
已 No-Go 的执行一致性/前瞻结论。任何本协议的失败都不得用 C2 的阈值或结论来救。

## 1. 命题（冻结，不可越界）

> 在冻结的 PX4/Gazebo 闭环测试包络内，确定性 fail-closed 恢复（R1）相对 RA-only（R0）
> 改善预注册恢复指标（orphan critical goal coverage / zone crossing / priority），
> 且 `safety bypass = 0`、物理碰撞 = 0。

不可写：真机安全、任意场景保证、连续时间安全定理、LLM 通用更强、LLM 实时避碰。

## 2. smoke 场景（先只做 drone_failure）

只做 `drone_failure`，理由：

- 两机平行轨迹（非对头），碰撞风险低，能隔离"恢复机制"这一单一因素；
- C2 已经显示对头场景在闭环 RA 下 `min_rho` 为负，不适合作为恢复机制的第一道门。

冻结几何（共享 FLU 坐标，单位 m，巡航高度 `CRUISE_ALTITUDE_M=2.5`）：

| drone | 逻辑 agent | 起点 | 原 goal |
|---|---|---|---|
| 2 | 0（失效机） | (-4, 0) | (4, 0) |
| 3 | 1（健康机） | (-4, -2) | (4, -2) |

- `change_step`：agent 0 在该步失效。
- `critical_goal`：(4, 0)（失效机原 goal，成为 orphan，必须被健康机覆盖）。
- 失效语义（冻结）：失效机原地 hold（速度置零），仍留在共享状态与 RA 中作为静止障碍，
  但不再向其原 goal 发命令。

## 3. 条件

| 条件 | 含义 |
|---|---|
| R0 | RA only（`mode=CBF_ONLY`），无恢复；失效机 hold，orphan goal 无人覆盖 |
| R1 | RA + `RuleMissionPlanner`（`mode=ASYNC`，`llm_client=rule`） |
| R2 | RA + 本地 Qwen + validator + rule fallback（smoke 阶段 skip，validation 再决定） |

smoke 只跑 R0、R1；R2 的轻量仿真已经证明本地 4B 无稳定增值，闭环 smoke 不重复它。

## 4. 冻结对象

- PX4 实例 id：`2,3`（逻辑 agent 0→drone 2、agent 1→drone 3）。
- RA 参数：`exact_zoh`、`tau_ctrl=0.2`、`tau_px4=0.2`、`gamma=0.1`、`sampled_data=True`。
- 失效语义见 §2；`critical_goal`、`change_step` 由 manifest 冻结。
- 每个物理 trial 使用独立 SITL（复用 C2′ 的 per-trial 隔离，避免飞控/EKF 状态泄漏）。
- 同一 trial 内 R0/R1 用 Latin-square 次序平衡；runner 观测到 `failsafe`/断链即判 trial 无效。

## 5. 指标

- 主指标：`critical_reached`（orphan goal 是否被健康机在 `goal_epsilon=0.5 m` 内到达）。
- 次指标：总完成、恢复 step/time、路径长度、碰撞率、`min_rho`、`safety bypass`、
  `fallback_plans_committed`、触发原因码。
- 安全门：所有条件物理碰撞 = 0；`safety bypass = 0`。

## 6. 统计与停止规则（smoke → validation 两级）

### smoke（本阶段）

- N=6 物理 trial，每 trial 独立 SITL，R0/R1 Latin-square 次序。
- 只验证：闭环链可运行、R0 确实不覆盖 orphan 而 R1 覆盖、触发可解释、碰撞=0、
  `safety bypass=0`。
- smoke **不产生论文效力结论**。

### 停止规则

1. smoke 若闭环链不可运行、或 R1 无可见恢复信号、或出现碰撞/bypass → **停止**，
   不调参、不加场景、不删异常 trial 救假设。
2. smoke 通过 → 另冻结 30-trial validation manifest（独立 seed 与 calibration 分离）。

## 7. claim 边界

任何结论都只限于：冻结的 `drone_failure` 几何、冻结的 PX4/Gazebo 闭环、测试范围与审计
分辨率内。不得外推到真机、任意故障或任意场景。
