# C3-STR 四机 Calibration Smoke 决策

## 1. 裁决

**实现审计修复后的 retry1 为 Calibration Smoke Go；仍不是论文统计。**

C3-STR 在冻结 `60 s` 内完成四机终点交换生命周期，并保持正安全裕度、QP 可行和
RA 不可绕过边界。该结果只允许进入新的五 seed qualification，不改变旧
C3-Reservation qualification No-Go。

## 2. 冻结对象

- manifest：`configs/c3_str_4uav_calibration_smoke_v1.json`
- manifest SHA-256：`a753e81c903095f15cd9b9d58ff0fad4d5c15d1b3cbe2f0121cdfc575b68296f`
- seed：`9701`
- 有效输出：`/Volumes/Expansion/Aegis/c3_str_4uav_calibration_smoke_v1_retry1/calibration`
- 时域：`1200` 步，`20 Hz`，即 `60 s`
- 预约上界：`6 s staging + 4×8 s service + 2×7 s grouped return = 52 s`，
  加固定 `8 s` 余量。

## 3. 有效 retry1 结果

| 指标 | R4 C3-STR |
|---|---:|
| 状态机 `COMPLETE` | 是，step 1155 |
| `service_latched/cleared/final_returned` | 4/4，4/4，4/4 |
| 兼容归位组 | `[3,4]`、`[5,2]` |
| 碰撞 | 0 |
| `min_rho` | **+0.295748** |
| 最小距离 | 1.5583 m |
| selected QP 不可行 | 0 |
| RA bypass | 0 |
| 路径长度 | 66.151153 m |
| 平均控制努力 | 0.052001 |
| RA P99 | 5.106 ms |
| 50 ms deadline miss | 2/1200，0.167% |
| 提前授权/槽成员错误 | 0/0 |
| 窗口只后移/修订单调 | 是/是 |

逐文件 SHA-256、runner `COMPLETE` 和外层 `COMPLETE` 均通过；清理后无残留
PX4/Gazebo/adapter。

## 4. 首次运行为何无效

原输出 `/Volumes/Expansion/Aegis/c3_str_4uav_calibration_smoke_v1` 完整保留，
`summary.json` 仍为 `NO_GO`。当时算法已在 step 1147 完成且安全门通过，但父状态机在
模式切换当步先输出旧式授权：step 60 和 step 1005 各有一次提前授权，step 926 只授权
兼容组中的一架。下一步虽被空时层收回，仍违反冻结审计。

该问题被标记为接口实现错误，而非有效算法 trial。修复只把切换当步纳入同一时间窗检查，
没有修改 manifest、seed、RA、场景、时域或任何预约参数；新增回归测试后运行 retry1。

## 5. 允许的下一步

冻结五个全新 seed 的 R3/R4 配对 qualification：

- R3：原反应式 C3-Reservation + RA；
- R4：C3-STR + RA；
- 每个 condition 使用全新 PX4/SITL；
- R4 任一有效 trial 失败立即 Qualification No-Go；
- 只有 R4 `5/5` 通过，才允许设计 20-seed sealed paired validation。

不得把本 smoke 写成多 seed 稳健性或一般化四机安全证据。
