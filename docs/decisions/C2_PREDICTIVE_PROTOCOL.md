# C2：前瞻式可恢复裕度 Gate（Pilot v1）

- 状态：**pilot 首组已完成并触发 No-Go；没有正向结论。**
- 协议 ID：`aegisair-c2-predictive-v1`。

## 假设与机制

当两机相向闭合时，反应式 `QP_INFEASIBLE` 触发可能已经晚于可恢复窗口。对每一对无人机，
在冻结参数下计算：

```text
required_distance = d_safe + buffer + v_close * response_delay
                    + v_close^2 / (2 * a_brake)
recoverability_margin = distance - required_distance
```

当裕度不大于零时，确定性地令编号较高的无人机让行，使用加速度受限的外向撤退；另一架保持
原 RA-filtered 命令。该规则不依赖 LLM、MARL 或在线学习，也不改变 CBF 的硬安全阈值。

## 冻结 pilot 合同

`configs/c2_predictive_pilot_v1.json` 在运行前固定：`d_safe=1.6 m`、response delay `0.30 s`、
单侧有效制动 `2.0 m/s²`、buffer `0.20 m`。delay 由既有 `tau_px4=0.2 s` 加两个 20 Hz
控制周期构成；制动上限与当前 RA 的 `a_max=2.0 m/s²` 一致。pilot 中不得改动这些参数。

## 三条件与停止规则

- `E2_FIXED`：无执行监督；
- `E2_QP_GATE`：既有反应式 QP/deadline/staleness gate；
- `PREDICTIVE_GATE`：C2′ 执行监督加前瞻式可恢复裕度 gate。

每个物理 trial 必须使用全新的 PX4/Gazebo 实例；同一实例只允许运行该 trial 内的三种
条件，避免姿态/EKF 状态从上一物理 trial 泄漏。runner 在 episode 中观测到 `failsafe` 或
链路丢失会直接使该 trial 无效。6 个物理 trial 使用 Latin-square 次序平衡。pilot 只决定
是否值得设计正式 validation：

1. `PREDICTIVE_GATE` 必须 6/6 `min_rho > 0`；
2. 不得出现碰撞、PX4 failsafe 或 safety bypass；
3. 相对 `E2_QP_GATE` 至少 5/6 trial 的 `min_rho` 更高；
4. 完成率相对 `E2_QP_GATE` 下降不得超过 10 个百分点。

任一项失败即停止，不用 pilot 数据回调 delay、buffer、制动或让行规则。通过后才建立独立
30-trial validation manifest。

`pilot01` 的具体结果及停止理由见 `C2_PREDICTIVE_PILOT_DECISION.md`。
