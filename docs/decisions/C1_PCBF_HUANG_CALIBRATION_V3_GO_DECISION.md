# C1 PCBF Huang et al. external baseline：Calibration v3 GO

## 决策

**GO。** PCBF nonlinear finite-candidate adaptation 通过五个全新 PX4/Gazebo calibration seeds，可冻结参数并进入独立 sealed paired evaluation。

本结果仅用于 baseline 参数冻结，不并入论文统计。此前 v1/v2 的失败配置与结果继续保留，不覆盖、不重分类。

## 冻结对象

- manifest：`configs/c1_pcbf_huang_ecc2025_calibration_v3.json`
- 输出：`/Volumes/Expansion/Aegis/c1_pcbf_huang_ecc2025_calibration_v3`
- horizon：24（20 Hz）
- terminal buffer：0.10 m
- slack / tracking weight：20.0 / 0.05
- lateral candidates：0.0、0.5、1.0、1.5、2.0 m/s²
- fail-closed：max-brake

## Gate 结果

五个 trial 均满足：mission complete、collision=false、`min_rho>0`、0 infeasible、0 deadline miss、0 safety bypass。

| Seed | min rho | Interventions | Effort | Path [m] | p99 [ms] |
|---:|---:|---:|---:|---:|---:|
| 12801 | 0.068208 | 98 | 0.112743 | 19.248639 | 5.832 |
| 12802 | 0.122289 | 96 | 0.114456 | 19.307721 | 5.726 |
| 12803 | 0.071369 | 96 | 0.113213 | 19.327510 | 5.508 |
| 12804 | 0.087556 | 96 | 0.115033 | 19.530599 | 5.627 |
| 12805 | 0.088408 | 96 | 0.111089 | 19.286137 | 6.002 |

最差 p99 为 6.002 ms，低于 50 ms deadline；最小观测 `rho` 为 0.068208。

## 下一步边界

使用全新 seeds 建立五方法 20-pair sealed manifest：AegisAir、Reactive Takeover、HOCBF-Fallback、PB-CBF、PCBF。不得继续调整 PCBF v3 参数；不得使用 calibration seeds 作为 sealed evidence。
