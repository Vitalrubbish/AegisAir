# Failure-aware recoverability admission calibration 决策

> 日期：2026-08-26  
> 决策：**GO，可进入独立 qualification；不是 sealed 论文证据。**

## 完整性

- manifest：`configs/c_recoverability_admission_calibration_v1.json`；SHA-256
  `c3e5f1a1530913a20e01f1298a37a3b2667693b7ac0fc7a7990663d704013438`；
- 输出：`/Volumes/Expansion/Aegis/c_recoverability_admission_calibration_v1`；
- 4 个 development geometries × 3 条件 = 12/12 fresh PX4/Gazebo conditions；
- audit SHA-256：`f1da997ce50ba22ef8dbc28f2e78bd2650631e8f3ecb3dc8e0cf1772d3a575e7`；
- `COMPLETE`、全部 trajectory、summary 和 audit 均存在；anti-vacuity=true。

## 结果

`RECOVERABILITY_ADMISSION_RA` 对三个 expected-admit 几何均恰好提交一次并完成 critical goal，
对 occupied-orphan-goal 几何正确拒绝且零提交。四条 admission 条件均 collision=0、`min_rho>0`、
selected-QP infeasible=0、unsafe commit=0、RA bypass=0、deadline miss=0；最差 P99 为 `1.938 ms`。
三个安全准入的 `min_rho` 分别为 `0.683328`、`0.242977`、`1.373555`；正确拒绝为 `1.275046`。

`RA_ONLY_HOLD` 四条均保持 frozen hold、零 critical-goal coverage、正 `min_rho` 和零不可行。

`IMMEDIATE_COMMIT_RA` 原样复现失败边界：四条 `min_rho` 均为负；on-path 有 3 个不可行步，
bottleneck 与 occupied-goal 分别有 705 和 702 个不可行步。它只作诊断比较，未用于放宽 admission 门。

## 审计修正

首次自动审计把 occupied-goal 几何标为 No-Go，因为公共 runner 在 `change_step` 前看到失效机已位于
critical goal，提前置 `critical_reached=true`。这不是算法失败。未重跑任何 episode，也未改 manifest、
seed 或参数；审计直接从原始 trajectory 重新计算“change_step 后健康机覆盖”，并修复公共 runner，
使后续 recovery coverage 只从故障发生后计数。重审后 admission rejection 和 RA-only hold 均为零覆盖。

## 边界与下一步

旧 deterministic cross-geometry No-Go 仍有效。本 calibration 只证明机制在已暴露 development 几何上
同时做到了安全准入与正确拒绝。下一步必须使用未参与开发的新几何和五个全新 seed 做 qualification；
任一有效失败即停止，不能调准入间距、候选集合或任务时域。
