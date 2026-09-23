# C1 PX4/Gazebo 正裕度恢复 v2 协议

## 1. 研究边界

v1 已因 seed 5101 的 `min_rho=-0.296013` 判定 No-Go，结论保持不变。v2 是新的、预先冻结的
问题：在同一两机对头目标互换、300 ms peer delay 和真实 PX4/Gazebo 执行链路下，加入
**估计器预热、确定性准入、刹车锁存和执行模型一致性**，能否同时获得正裕度、零碰撞和
任务完成。

## 2. 四项机制

1. **估计器预热**：任务运动前 HOLD `ceil(0.3 s × 20 Hz)+2=8` 个周期，保证 300 ms
   历史已存在后再准入。
2. **确定性准入**：drone 2 固定先行；drone 3 先进入横向 staging point。drone 2 到达原
   目标后横向清场，drone 3 再通行，最后 drone 2 返回目标。两机不会同时进入对头走廊。
3. **刹车锁存**：任一局部 QP infeasible 或 `rho<=0.2` 时，两机命令锁存为零；仅当全部
   QP feasible 且 `rho>=0.5` 连续 5 周期后释放，消除 stale-view 下的刹车—再加速抖动。
4. **执行模型一致性**：三个时间常数独立命名并写入每条结果：
   `barrier_tau_px4_s=0.2`、`command_feedforward_tau_s=0.7`、
   `admission_execution_tau_s=0.7`。其中 0.7 s 来自 PX4 速度执行辨识，用于速度命令前馈
   与准入距离；它不替换 sampled-data barrier 的短时一步参数 0.2 s。

staging clearance 不由 v1 失败轨迹调参，而由冻结公式产生：对单机最大通行速度 1.5 m/s，
将 0.7 s 执行滞后加入反应项，并计入 300 ms AoI 后得到边界 3.5975 m，再加 0.2 m
准入余量，固定为 3.7975 m。

## 3. 冻结验证

- manifest：`configs/c1_px4_telemetry_delay_validation_v2.json`；独立 seeds 6101–6120。
- 每个 seed 使用新 SITL；20 Hz、600 steps；原始轨迹写入移动硬盘
  `/Volumes/Expansion/Aegis/c1_px4_telemetry_delay_validation_v2`。
- GO：20/20 均 `collision=false`、`min_rho>0`、`mission_complete=true`，且结果中的三个
  tau 与 manifest 完全相等。
- 首个 seed 任一条件失败即停止；不在 validation 内调整阈值、路径、tau、速度或步数。

可报告结论只限该两机、300 ms peer-delay、确定性顺序准入的 PX4/Gazebo 包络；不得改写
为“原 v1 RA-only 已通过”或推广到任意延迟、四机交会和真实飞行。
