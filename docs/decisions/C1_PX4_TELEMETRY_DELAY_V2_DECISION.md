# C1 PX4/Gazebo 正裕度恢复 v2 决策：GO

## 决策

`aegisair-c1-px4-telemetry-delay-v2` 在冻结的 20 个独立 seed（6101–6120）上完整通过：

| 指标 | 结果 |
| --- | ---: |
| 正裕度 | 20/20 |
| 任务完成 | 20/20 |
| 碰撞 | 0/20 |
| `min_rho` 最低 / 均值 / 最高 | 1.207318 / 1.372772 / 1.420060 |
| 最小物理距离最低 / 均值 | 3.9628 m / 3.9933 m |
| 平均路径长度 | 32.9268 m（范围 31.9950–34.2391 m） |
| brake-latch trip | 0 |
| CBF intervention | 0 |

数据目录：`/Volumes/Expansion/Aegis/c1_px4_telemetry_delay_validation_v2`。20 条 trajectory、
逐 trial summary、manifest hash 均由 `marllib/analyze_c1_px4_v2.py` 复核；目录存在
`COMPLETE`，聚合 `summary.json` 的决策为 `GO`。

## 机制解释

v1 的 RA-only 对头交会在 estimator 的 300 ms 延迟历史建立后才突然看到完整动态边界，
此时双机已高速接近，QP 从可行切到不可行并出现刹车—再加速，最终
`min_rho=-0.296013`。v2 没有修改该 v1 结果，而是另立协议并修复进入不可恢复区之前的
决策：

1. 先 HOLD 8 个周期，使延迟历史成熟；
2. 用横向 staging、固定通行权和清场阶段串行化目标互换；
3. 以 `rho<=0.2`/QP infeasible 进入全局零速锁存，以连续 5 个 `rho>=0.5` 可行周期释放；
4. 将三个 tau 分离：barrier 一步参数 0.2 s，PX4 命令前馈与 admission execution lag
   均为 0.7 s。

所有 20 个 v2 trial 都没有触发第 3 项，说明本次正裕度主要由预热与提前准入建立，而不是
越界后靠锁存恢复。锁存仍作为 fail-closed 后备机制保留并由单元测试覆盖。

## 与 v1 和轻量 C1 的统一口径

- v1 No-Go 仍成立：它证明 RA-only 在该 PX4 对头/300 ms peer-delay 包络中不足以维持
  正裕度。
- v2 GO 是新的“执行一致、准入控制的安全交会”主张，不得倒写成 v1 RA-only 成功。
- 轻量 C1 的一致观测消融仍说明 full envelope 相对消融改善碰撞/距离，但不提供普遍正
  `rho`；v2 说明要将其迁移为正裕度闭环，还需要任务级 admission，而不是单独扩大 margin。
- v2 平均路径约 32.93 m，显著高于直接对头互换路径；论文必须同时报告这一效率代价。

## 无效启动审计

正式运行前有一次缺少持久 GCS heartbeat 的 arm 失败。该次在任务开始前退出，没有
trajectory/安全结果，已隔离到
`/Volumes/Expansion/Aegis/c1_px4_telemetry_delay_validation_v2_invalid_arm_20260822T1446`，
不计入 20 个 seed。随后恢复 broker、18572/18573 heartbeat 和 adapter 健康，才启动正式
validation。

## 可报告边界

可报告：在冻结的两机目标互换、300 ms peer delay、20 Hz 和当前 PX4/Gazebo 栈内，执行
感知的确定性 admission supervisor 在 20 个独立 seed 中保持正归一化裕度、零碰撞并完成
任务。

不可报告：真机保证、任意延迟/多机交会保证、连续时间安全定理，或 0.7 s 是确定性执行
上界。
