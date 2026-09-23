# C3-STR 四机 Qualification 冻结协议

## 1. 目的与对照

本协议只检验：单 seed calibration smoke 通过后的 C3-STR，能否在五个全新 Gazebo
seed 中稳定满足四机生命周期、安全、权限和实时性联合门。

- R3：原反应式 C3-Reservation + RA，机制对照；
- R4：C3-STR + RA，完整方法。

R3 不决定 qualification Go；旧 R3 qualification No-Go 保持不变。

## 2. 冻结设计

- seeds：`9801–9805`，均未用于 calibration；
- R3/R4 同 seed 配对；
- 条件首位按 3:2 平衡；
- 每个物理 condition 使用全新 PX4/SITL；
- `20 Hz`、`1200` 步、`60 s`；
- C3-STR 时隙、兼容间隔、RA、起终点和冲突区全部沿用 calibration retry1；
- 无效启动每 condition 最多三次，不计为算法样本。

| seed | 条件顺序 |
|---:|---|
| 9801 | R3 → R4 |
| 9802 | R4 → R3 |
| 9803 | R3 → R4 |
| 9804 | R4 → R3 |
| 9805 | R3 → R4 |

## 3. R4 即时停止门

每个有效 R4 必须全部满足：

- `COMPLETE`，且 `service_latched/cleared/final_returned=4/4`；
- 至少一个双机兼容归位槽实际启用；
- `collision=0`、`min_rho>0`、selected QP 不可行 0、RA bypass 0；
- 时间窗只后移，修订号单调；
- 无提前授权、无授权成员与活动槽不一致；
- RA P99 `<50 ms`，deadline miss 率 `<1%`。

任一有效 R4 失败立即 No-Go，停止后续算法 trial。不得调参、换 seed、延长时域或
重跑有效失败。只有 R4 `5/5` 通过，才允许设计 20-seed sealed paired validation。

## 4. 主张边界

Qualification Go 只表示允许进入 sealed validation，不是论文最终统计，也不证明一般化
四机安全。MAPPO 不参与；C3 只负责活性与空时协调，RA 始终保留最终硬安全权。
