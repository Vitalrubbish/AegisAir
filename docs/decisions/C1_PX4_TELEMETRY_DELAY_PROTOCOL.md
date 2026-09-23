# C1 PX4/Gazebo 20-seed 核心迁移验证协议

- 协议 ID：`aegisair-c1-px4-telemetry-delay-v1`。
- 目的：验证 C1 的关键接口主张——**本机新鲜、peer 延迟估计与 AoI 动态 margin**——能否通过
  真实 PX4/Gazebo 控制链路；这不是原 C1 四机四场景消融的替代品。

## 冻结对象

- 两机对头，drone 2/3 的共享 FLU 起点为 `(-4,0)/(4,0)`，目标互换；20 Hz、600 steps。
- peer telemetry 经 300 ms `SharedStateEstimator`，每架 RA 只以自身新鲜遥测替代本机状态。
- 同一 Gazebo seed 内比较 `full_envelope` 与 `no_aoi_margin`；20 个独立 seed（5101–5120），
  10:10 Latin-square，物理 trial 使用新 SITL。
- RA 保留 exact-ZOH、sampled-data、`tau_ctrl=tau_px4=0.2 s`；速度命令固定为此前独立
  确认过的 `feedforward_tau=0.7 s`。

## 假设与停止规则

`full_envelope` 必须在 20/20 episode 中 collision=0 且 `min_rho>0`；出现任一 full 条件
碰撞或负裕度即停止并 No-Go，不调 margin、tau、目标增益或几何。只有全部完成后才评估
paired `min_rho` 与 baseline 的方向性差异；该对比不允许用 validation 数据重调参数。

可报告结论仅限两机、300 ms peer-delay、当前 PX4/Gazebo 栈。它不能证明原 C1 的四机、
perception-dropout 或任意陈旧通信情形。
