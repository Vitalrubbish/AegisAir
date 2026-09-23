# Failure-aware recoverability admission sealed 决策

> 日期：2026-08-26  
> 决策：**COMPLETE / GO。**

## 完整性

- manifest：`configs/c_recoverability_admission_sealed_v1.json`；SHA-256
  `bb9ca756d1d5fcb80b00227d32f3d5d424c49af9812bde7f07f32c196c2b3870`；
- 输出：`/Volumes/Expansion/Aegis/c_recoverability_admission_sealed_v1`；
- 20 个全新 seed × 3 条件 = 60/60 fresh PX4/Gazebo conditions；
- audit：`COMPLETE`、`decision=GO`、anti-vacuity=true；SHA-256
  `a87a6e9237bfa3b0c234659d4f1f6354dd70fc4e0662ac30106b8f57b1f4cad6`。

一次 `radms04/IMMEDIATE_COMMIT_RA` 启动期缺少 UAV 3 telemetry，没有 trajectory，记录为 invalid
infrastructure attempt；随后使用同一 manifest 和 seed 13204 fresh 重启。它不进入算法分母，也没有
替换任何有效负结果。

## 三条件结果

| 条件 | 有效数 | 故障后 critical coverage | collision | mean / min `min_rho` | selected-QP infeasible | max P99 |
|---|---:|---:|---:|---:|---:|---:|
| Immediate commit + RA | 20 | 19/20 | 2 | `-0.304785 / -0.962714` | 2325 | `2.608 ms` |
| Recoverability admission + RA | 20 | 12/20 | 0 | `1.091248 / 0.076997` | 0 | `2.353 ms` |
| RA-only safe hold | 20 | 0/20 | 0 | `2.741783 / 1.582744` | 0 | `2.135 ms` |

所有三条件均 RA bypass=0。Immediate comparator 的两次仿真碰撞发生在 `radms13` 和 `radms20`；
它们和全部负 margin/不可行步原样保留。

## Selective recovery 主结果

- 12 个 expected-admit cases：12/12 恰好准入一次，12/12 完成故障后 critical goal；
- 8 个 expected-reject cases：8/8 正确 `rejected_hold`、零 plan commit、零 critical coverage；
- unsafe commit：0；
- 20/20 admission 条件 collision=0、`min_rho>0`、selected-QP infeasible=0、RA bypass=0、
  deadline miss=0；
- 20/20 RA-only 条件保持安全 hold，且没有虚假任务覆盖；
- 因此不是依靠“全部拒绝”获得安全，anti-vacuity 门通过。

## 允许主张与边界

允许写：在冻结的双机 PX4/Gazebo 参数化失效包络中，commit 前 recoverability admission 将任务恢复
变成 selective recovery：对预测可恢复候选安全提交并完成任务，对不可恢复候选 fail closed；相对直接
提交，消除了本 sealed 集中的仿真碰撞、负 margin 和 selected-QP infeasibility，同时没有绕过 RA。

不得写成：旧 deterministic recovery 已被“救活”、任意跨几何任务都可恢复、拒绝任务也是恢复成功、
连续时间/真机安全证明或一般多机保证。旧跨几何 calibration No-Go 仍作为直接提交基线的失败边界保留。
