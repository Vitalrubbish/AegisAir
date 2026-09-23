# C3-STR 四机 Qualification 决策

## 1. 最终裁决

**Qualification No-Go；停止剩余条件，不进入 20-seed sealed validation。**

五个全新 seed 的即时停止门在 seed 9802 的第二个有效 R4 trial 触发。该 trial 保持正
安全裕度、QP 可行、RA 不可绕过，并让四机几何上进入目标容差；但冻结 `60 s` 结束时
仅首个双机归位组完成稳定锁存，状态机未进入 `COMPLETE`。这是有效算法失败，不能通过
延长时域、修改时隙或重跑挽救。

## 2. 冻结对象与完整性

- manifest：`configs/c3_str_4uav_qualification_v1.json`
- seeds：`9801–9805`
- 已执行有效条件：3/10
- R4：2 个有效 trial，1 Go、1 No-Go
- 无效启动：0
- 输出：`/Volumes/Expansion/Aegis/c3_str_4uav_qualification_v1`
- 根标记：`STOP_RULE_NO_GO`、`COMPLETE`
- 根 manifest/summary 和三个逐 trial trajectory/summary 的 SHA-256 全部通过
- 清理后无残留 PX4/Gazebo/adapter

## 3. 有效 trial

| seed | 条件 | `COMPLETE` | `final_returned` | `min_rho` | QP不可行 | bypass | P99 | 完成步 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 9801 | R3 | 是 | 4/4 | +0.240880 | 0 | 0 | 7.953 ms | 1175 |
| 9801 | R4 | 是 | 4/4 | +0.316127 | 0 | 0 | 6.610 ms | 1156 |
| 9802 | R4 | **否** | **2/4** | +0.178593 | 0 | 0 | 15.578 ms | 截尾 |

seed 9802 的 R4 还满足：

- `mission_complete=true`、碰撞 0；
- `service_latched=4/4`、`cleared=4/4`；
- 首个归位组 `[3,4]` 完成；第二组 `[5,2]` 在 step 1114 获得合法授权，但未在
  step 1200 前满足连续稳定锁存；
- 窗口只后移、修订号单调；提前授权 0、槽成员错误 0；
- deadline miss 3/1200，低于 1% 门。

因此失败只来自预注册的固定时域生命周期门，不来自碰撞、负裕度、QP不可行、权限绕过、
预约一致性或实时性门。

## 4. 可以与不可以写的结论

可以写：

> C3-STR 通过显式时间窗和兼容归位组，在两个全新 R4 trial 中均保持正安全裕度、QP
> 可行和几何任务完成；但第二个有效 qualification trial 未在固定 60 s 内完成完整状态
> 生命周期，因此该机制的跨 seed 四机活性主张为 No-Go。

不可以写：

- C3-STR 已稳定通过四机；
- qualification 成功率为 50% 或据此进行总体统计推断；
- 用 calibration retry1 或 seed 9801 覆盖 seed 9802；
- 延长时域、放宽锁存、修改窗口或更换 seed 后继续 sealed；
- 把几何 `mission_complete` 替代预注册 `COMPLETE`。

## 5. 论文处理

C3-STR 只保留为四机终点交换压力验证和边界证据，不进入 headline 正向贡献或 sealed
优越性表。论文主线仍使用已经冻结并通过正式统计的两机 Runtime Assurance 与原 C3
fail-closed orphan-goal recovery。四机部分应透明报告：协调层可恢复安全和几何活性，
但固定时域内的完整多机任务活性仍未获得 qualification 支持。

本四机方向至此关闭，不再追加 MAPPO、第三种预约器或调参救援。
