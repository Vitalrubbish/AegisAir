# B2 4-UAV PX4/Gazebo 基础设施 smoke 决策

> 日期：2026-08-24  
> 决策：`NO_GO`  
> 地位：有效的单 seed 基础设施/控制边界负结果，不是 sealed 统计证据。  
> 原始数据：`/Volumes/Expansion/Aegis/b2_4uav_px4_infrastructure_smoke_v1`

## 1. 冻结对象与健康门

- manifest：`configs/b2_4uav_px4_infrastructure_smoke_v1.json`
- manifest SHA-256：`3d4c2faa42456e728b46fff1569356cb463a5110a235ce019b09046e388bfe2a`
- Gazebo seed：`9501`
- 四架独立 PX4：实例 `2/3/4/5`；20 Hz adapter；18572--18575 GCS heartbeat。
- telemetry 坐标与四个预注册起点一致；起飞前均为 `failsafe=false`、
  `connection_lost=false`。
- 方法：冻结参数的 `AEGIS_HOCBF_V4`；高层使用已有 deterministic
  `SEQUENTIAL_PASS`，LLM/MARL 不参与。
- 第一次 runner 调用因缺少 `host/port` 在进入 live loop 前抛出 `TypeError`，只产生空目录；
  已移除空目录，不计 trial。随后同一 seed 的第一次物理执行为本结果。

## 2. 结果

| 指标 | 结果 | smoke 门槛 |
| --- | ---: | ---: |
| mission complete | false | true |
| collision | false | false |
| `min_rho` | `-0.164023` | `>0` |
| 最小距离 | `0.9019 m` | 仅诊断，不替代 rho |
| selected-QP infeasible | 34 步 | 0 |
| primary / predictive / recovery infeasible | 57 / 58 / 34 步 | 完整披露 |
| RA P50 / P95 / P99 / max | 1.550 / 2.276 / 4.554 / 32.165 ms | P99 `<50 ms` |
| 50 ms deadline miss | 0 | 0 |
| reset elapsed | 4.177 s | 有效 reset |

轨迹、manifest 与 summary 的 `integrity.sha256` 均通过。`COMPLETE` 已存在。

## 3. 原因分解

1. **计算规模不是本次失败原因。** 800 个 PX4 闭环步没有 50 ms deadline miss，和 B1 的
   4-UAV 计算 Go 一致。
2. **当前四机同时交叉安全门真实失败。** 负裕度集中在第 31--52 步；第 50 步 PB recovery
   已选中但不可行。该现象发生在后续任务漂移之前，不能用状态机修复删除。
3. **任务未完成还包含独立状态机缺陷。** 原 `SEQUENTIAL_PASS` 每周期基于当前位置重算
   `safe_holding_point`，使等待目标持续向外漂移；已到达目标的飞行器也可能再次被 stall 逻辑
   纳入循环。轨迹中飞行器被带到约 `|x|=6 m` 的边缘，造成 121.22 m 总路径且 800 步未完成。

已对状态机做最小工程修复：一次顺序通行只冻结一次 holding point，并记录已完成飞行器，避免
重复纳入 stall/通行循环；相关单元测试已增加。此修复不能追溯性改变 smoke v1 的安全 No-Go，
也未用来重跑同一协议救结果。

## 4. 决策与论文边界

**停止 B2 的 4-UAV sealed 扩种子。** 当前证据只支持“4-UAV RA 计算路径在本机达到 20 Hz”，
不支持“当前 v4 在四机同时交叉中保持正裕度和任务完成”。历史 4-UAV 正裕度运行也不能替代
本次新协议。

若后续继续 4-UAV，必须另立新主张与新协议，例如在冲突形成前进行 deterministic task
admission / sequential passage，再比较同一高层协调下的 RA 方法；它属于新的结构性方案，不能
覆盖本次 No-Go，也不能由本次 seed 选参数。工作包 C 的 2-UAV 三种失效几何可独立预注册，
但不得把它写成 4-UAV 规模通过。
