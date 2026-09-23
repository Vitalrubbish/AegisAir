# Failure-aware recoverability admission calibration 协议

> 日期：2026-08-26  
> 阶段：development/calibration；不是 qualification 或 sealed 论文证据。

## 1. 相邻主张

旧 deterministic recovery 的跨几何 No-Go 保持不变。本分支检验新的相邻主张：失效机权限撤销后，
任务管理器只在冻结候选航路位于声明的可恢复包络内时提交 orphan goal；没有候选通过时必须
fail-closed hold。所有实际速度仍经过原 Runtime Assurance，准入器没有执行权限。

## 2. 冻结比较

1. `IMMEDIATE_COMMIT_RA`：原 deterministic commit + RA；
2. `RECOVERABILITY_ADMISSION_RA`：commit 前候选准入 + RA；
3. `RA_ONLY_HOLD`：不接管 orphan goal，权限撤销后冻结健康机 hold。

manifest 为 `configs/c_recoverability_admission_calibration_v1.json`。使用三个旧 No-Go 几何作为开发数据，
另加一个失效机占据 orphan goal 的正确拒绝几何。四个 calibration seed 为 13001--13004；每个条件
使用 fresh PX4/Gazebo，输出写入
`/Volumes/Expansion/Aegis/c_recoverability_admission_calibration_v1`。

## 3. 准入对象

候选集合固定为 direct route，以及围绕失效机制动包络的有限单 waypoint 折线。制动包络使用
`2.0 m/s^2`，要求全路线预测间距至少 `2.4 m`，最大路线长度 `18 m`。候选按路线长度、再按间距
确定性排序。候选集合、间距、采样数、arena 和 waypoint 门均在运行前冻结。

拒绝时不提交 `REASSIGN`，而是冻结健康机事件时位置并令 nominal scale 为零；RA 仍保留最终过滤权。

## 4. Go/No-Go

- expected admit：必须恰好准入一次、零 unsafe commit、完成 critical goal，并满足
  `collision=0`、`min_rho>0`、selected-QP infeasible=0、RA bypass=0、P99<50 ms、deadline miss=0；
- expected reject：必须恰好拒绝一次、零 plan commit、不覆盖 critical goal、hold 目标不漂移，并满足同一安全门；
- anti-vacuity：有效 calibration 中必须同时至少有一个 admission 和一个 rejection；
- immediate baseline 原样报告，不能用于放宽 admission 门；
- 任一 admission 条件有效失败即 calibration No-Go，不改参数、不追加 seed。基础设施无效启动只允许
  在同一 manifest/seed 下隔离重启。

只有 calibration GO 才能另立全新 qualification 几何和五个全新 seed；旧几何不能进入 qualification
或 sealed 正向统计。
