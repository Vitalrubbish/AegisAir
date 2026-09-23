# C3 闭环 30-trial validation 冻结协议

- 协议 ID：`aegisair-c3-closed-loop-v1`；阶段：`validation`。
- 本文件与 `configs/c3_closed_loop_validation_v1.json` 一起冻结。其 SHA-256 由 runner 写入每个结果目录。

## 冻结对象

- 场景、几何、失效语义、RA 参数及主指标严格沿用 `C3_CLOSED_LOOP_PROTOCOL.md`；不改阈值、不增场景。
- 30 个物理 trial 为 `val01`–`val30`，Gazebo seeds 为 `4101`–`4130`；均未用于 calibration 或 smoke。
- 同一 physical trial 内 R0/R1 使用同一 Gazebo seed 与同一新启动 SITL；次序按 manifest 15:15 Latin-square 平衡。
- 速度命令固定为 `feedforward_tau`，`tau_command_s=0.7`。这不是以 validation 数据调出的量；依据是 Phase-7 的执行辨识与独立确认实验。
- 每个 trial 新建 Gazebo/PX4 rootfs；启动器将 seed 真实传给 `gz sim --seed`，并写入启动日志。任何断链、failsafe、启动失败或审计文件不完整均记为 invalid，不能删除或替换。

## 预注册 Go/No-Go

仅在 30 个有效配对全部完成时判定。否则为 **No-Go（证据不足）**，不补跑挑选结果。

1. 安全：60 个 episode 的物理碰撞均为 0、`safety_bypass` 均为 0，且所有 `min_rho > 0`。
2. 机制：每个 R1 都有 `MISSION_CHANGE` 触发，且 `mission_changes=1`、`recovery_step=31`；R0 不得产生恢复提交。
3. 覆盖：至少 27/30 个 R1 `critical_reached=true`，至多 3/30 个 R0 为 true，且至少 27 个配对为 `(R0=false, R1=true)`，反向 discordant 配对为 0。
4. 不删除异常、不会在 validation 中再调 `tau_command_s`、RA 参数、目标增益、步数或 `goal_epsilon`。

可报告的结论限于本冻结 PX4/Gazebo `drone_failure` 包络：规则 fail-closed 恢复在执行模型校正后提高 orphan-critical-goal coverage，同时维持已审计安全边界。不得外推为真机或任意场景保证。
