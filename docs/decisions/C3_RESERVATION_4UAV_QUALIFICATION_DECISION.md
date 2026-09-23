# C3-Reservation 四机 Qualification 决策

## 结论

**Qualification No-Go；停止 seeds 9602–9605，不进入 20-seed sealed validation。**

seed 9601 的 R3 是有效算法 trial。它保持了正裕度、QP 可行和 RA 权限边界，并且四机
几何上最终均进入目标容差；但冻结 60 s 结束时只完成 3/4 `final_returned`，状态机没有
进入 `COMPLETE`。这违反预注册任务生命周期门，不能通过延长时域或重跑有效失败挽救。

## 冻结协议

- manifest：`configs/c3_reservation_4uav_qualification_v1.json`
- qualification seeds：`9601–9605`
- 已执行 seed：`9601`
- 四机：`2/3/4/5`
- 20 Hz、1200 步、60 s
- 每个 condition 使用全新 PX4/Gazebo/SITL
- 主对照：R2 C3-Admission + RA；R3 C3-Reservation + RA
- 输出：`/Volumes/Expansion/Aegis/c3_reservation_4uav_qualification_v1`

## seed 9601 配对结果

| 指标 | R2 Admission | R3 Reservation |
|---|---:|---:|
| 四机最终进入目标容差 | 是 | 是 |
| 状态机 `COMPLETE` | 不适用 | **否** |
| `final_returned` | 不适用 | **3/4** |
| collision | 0 | 0 |
| `min_rho` | -0.774239 | **+0.334923** |
| 最小距离 | 0.3138 m | **1.5816 m** |
| selected QP 不可行步 | 432 | **0** |
| RA bypass | 0 | 0 |
| P99 | 21.191 ms | **8.256 ms** |
| deadline miss | 3/1200 | **1/1200** |
| 路径长度 | 94.770 m | **65.601 m** |
| 平均控制努力 | 0.778079 | **0.053596** |

R3 完整完成了四架机的目标服务和清场，随后依次完成 UAV 3、5、4 的最终归位；UAV 2
在 step 1124 开始最后归位，但在 step 1200 前没有满足连续稳定锁存要求。因此它是
“安全与几何任务完成、生命周期超时”的有效负结果。

## 基础设施与封装审计

- R2 与 R3 各有一个完整、逐文件 SHA-256 通过的有效 trial；无 condition-level 无效启动；
- R2 完成后的旧 PX4 进程清理曾触发隔离阻塞，R3 尚未启动，因此不构成算法样本；修复
  仅增加精确进程清理，未修改 manifest 或控制参数；
- 有效 R3 后，批处理曾因 shell 中文变量边界和汇总脚本导入路径错误而未生成根汇总；
  两次都只修复封装，并直接读取已有有效结果，没有重飞；
- 错误的提前 `COMPLETE` 已保留为 `INVALID_COMPLETE_BEFORE_AGGREGATE`，最终根目录的
  `COMPLETE` 只在正式 `qualification_summary.json` 生成后写入。

## 统计与图形边界

只有一个有效配对 seed，因此生成的轨迹、时间线、配对裕度、联合成功率和延迟 CDF 只作
描述性审计，不进行论文推断。McNemar、bootstrap CI、RMST 和 Holm 校正程序已实现，
但不得把当前 `n=1` 输出写成统计证据。

## 当前可写结论

可以写：

> 在新的四机 qualification seed 中，C3-Reservation 相比只有准入的 R2 恢复了正安全
> 裕度与 QP 可行性，并显著降低路径和控制努力；但完整 Reservation 生命周期未能在
> 预注册 60 s 内结束，因此该机制没有通过进入 sealed validation 的稳定性闸门。

不能写：

- R3 已统计优于 R2；
- R3 已稳定通过四机；
- 把几何进入目标容差替代预注册 `COMPLETE`；
- 延长时域、放宽锁存或重跑 seed 9601 后继续 sealed。
