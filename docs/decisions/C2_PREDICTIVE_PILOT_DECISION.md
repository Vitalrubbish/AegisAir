# C2 前瞻式可恢复裕度 Gate：Pilot v1 决策（2026-08-21）

- 决策：**No-Go；停止 pilot，不运行 pilot02–pilot06，也不进入 30-trial validation。**
- 数据：`/Volumes/Expansion/Aegis/c2_predictive_pilot01_live_20260821/summary.json`。
- 有效性：此组在独立 PX4/Gazebo 实例完成；GCS heartbeat 正常，runner 未观测到 episode
  内 failsafe 或 connection loss。此前把多个物理 trial 串在同一 SITL 的失败运行不计入
  本决策，且已由 runner 的 fail-closed 健康检查修复。

## Frozen pilot01 结果

| 条件 | min_rho | minimum distance (m) |
| --- | ---: | ---: |
| `E2_FIXED` | -0.675784 | 0.5326 |
| `E2_QP_GATE` | -0.696049 | 0.4313 |
| `PREDICTIVE_GATE` | -0.969459 | 0.2670 |

`PREDICTIVE_GATE` 的第一处 `PREDICTIVE_RECOVERABILITY` 发生在 step 77：距离 `2.8268 m`、
闭合速度 `1.5435 m/s`、所需距离 `2.8586 m`、预测裕度 `-0.0318 m`。同一步已经出现
`QP_INFEASIBLE`，说明该冻结合同未能在反应式 gate 之前建立可恢复窗口。最差点 step 124
达到 `rho=-0.969459`；因此 pilot 的第一条要求（6/6 `min_rho>0`）已经不可能满足。

## 不可做的后续

不得以 pilot01 的结果增加 delay、buffer、制动参数或更换让行方向来重跑 v1；那会用失败
pilot 数据选择阈值。当前实现和日志接口保留为可审计基础设施，但不能作为安全性能创新。

若继续研究，必须先冻结一个与本假设不同的问题，例如在任务发布阶段拒绝不可恢复的交会
请求（admission control），并使用独立的 calibration 与 pilot；不能把它描述成 C2 v1 的
参数修复。
