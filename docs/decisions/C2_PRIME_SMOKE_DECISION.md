# C2′ PX4/Gazebo Smoke 决策（2026-08-21）

- 决策：**C2′ 安全提升主张 No-Go；不进入 30-trial validation。**
- 保留：执行一致性监测、冻结 calibration、可审计原因码和确定性备份实现。
- 禁止动作：不得用本 smoke 重标定阈值、不得删除负样本、不得将触发日志写成安全提升。

## 冻结对象与有效性

- calibration：`/Volumes/Expansion/Aegis/c2_prime_calibration_live_20260821`，12 个单机
  `E2_OBSERVE` trial；所有 trial 有逐步残差与遥测记录。
- 冻结阈值：速度残差 `0.05698655 m/s`，位置残差 `0.06566755 m`；遥测 age `0.15 s`、
  求解 deadline `0.05 s` 未由 calibration 放宽。
- validation smoke：`/Volumes/Expansion/Aegis/c2_prime_smoke_live_20260821`，6 个物理
  trial、3 条件 Latin-square 次序平衡、18 条轨迹；manifest 与 calibration SHA256 已写入
  `summary.json`。

## 结果

| 条件 | mean min_rho | min_rho < 0 |
| --- | ---: | ---: |
| `E2_FIXED` | -0.626513 | 6/6 |
| `E2_QP_GATE` | -0.516476 | 6/6 |
| `C2_PRIME` | -0.532255 | 6/6 |

`C2_PRIME - E2_FIXED` 的逐 trial 配对均值为 `+0.094258`（4/6 为正），但相对更合适的
`E2_QP_GATE` 为 `-0.015780`（3/6 为正）。因此新增的残差门没有显示出超越既有
QP/deadline/staleness gate 的安全裕度收益。

监督链确实工作：`C2_PRIME` 6/6 trial 发生接管，共 386 个 active step；其中 3/6 trial
出现 `VELOCITY_RESIDUAL` 原因码。作为对照，`E2_QP_GATE` 也是 6/6 接管、368 个 active
step，且只出现 `QP_INFEASIBLE`。这支持“系统可观测、可追溯”，不支持“边界安全提升”。

## 结论与后续边界

原 C2 与 C2′ smoke 都不能写成正向安全 claim。下一项研究若继续，应另立新问题并先冻结
干预包络与成功终点；不得改动本轮阈值或用相同数据重新选择备份策略。现有 C2′ 实现可作为
runtime-assurance 可审计基础设施，而非论文中的性能创新结论。
