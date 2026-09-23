# C1 external PCBF sealed comparison v1：完成决策

## 完整性与安全门

**COMPLETE / GO。** 20 个全新 paired seeds、五种方法，共 100/100 个 PX4/Gazebo conditions 完成；20/20 paired trials 完整，0 safety-gate failure。外部审计 `audit.json` 报告 `expected=100`、`found=100`、`go=true`。

输出根：`/Volumes/Expansion/Aegis/c1_external_pcbf_sealed_v1`。

所有 conditions 均满足：mission complete、collision=false、`min_rho>0`、safety bypass=0。运行中一次 telemetry readiness timeout 未产生 trajectory/summary；批次按冻结 manifest 从断点恢复，不替换 seed、不改参数。

## 描述性结果

| 方法 | n | 最小 rho | 平均 min rho | 平均 effort | 平均 path [m] | 最大 p99 [ms] |
|---|---:|---:|---:|---:|---:|---:|
| AegisAir full hybrid RA | 20 | 0.126621 | 0.175715 | 0.132215 | 18.646424 | 2.479 |
| Reactive PB takeover | 20 | 0.052527 | 0.124573 | 0.148445 | 18.632209 | 1.810 |
| HOCBF-Fallback | 20 | 0.024063 | 0.083443 | 0.224645 | 18.464169 | 2.015 |
| PB-CBF | 20 | 0.466452 | 0.504116 | 0.172002 | 18.762334 | 1.722 |
| PCBF Huang ECC 2025 adaptation | 20 | 0.061302 | 0.085911 | 0.113490 | 19.329716 | 6.820 |

上述仅为描述性汇总。论文比较必须继续使用 seed-level paired analysis，并报告置信区间；不能仅凭均值写“全面优于”。

## 可写边界

PCBF 条件是遵循 predictive safe-MPC 思路、使用真实二维距离、有限候选预测优化和 bounded-braking terminal recovery 的 testbed adaptation，不是作者原始数值例程的逐行复刻。允许的结论是：该 external published-method adaptation 在共同 PX4/Gazebo testbed 中通过任务、安全和实时性门，并表现出较低 effort、较长 path、较低安全裕度和较高但仍低于 deadline 的求解时延。

## Seed-level paired analysis

分析目录：`/Volumes/Expansion/Aegis/c1_external_pcbf_sealed_v1/analysis_v1`。分析以 20 个 seed 为独立单位，报告 10,000 次 paired bootstrap 95% CI、exact paired sign-flip randomization p-value，并在每个指标的四个 baseline 比较内使用 Holm 校正。所有方法均 20/20 完成且无碰撞，二分类结局没有 discordant pair，exact McNemar `p=1`。

AegisAir 相对 PCBF adaptation：

- `min_rho`：`+0.089804`，95% CI `[0.079363, 0.098956]`；
- control effort：`+0.018725`，CI `[0.017866, 0.019662]`；
- path length：`-0.683292 m`，CI `[-0.743299, -0.613783]`；
- intervention events：`-6.6`，CI `[-7.7, -5.5]`；
- p99 latency：`-3.995862 ms`，CI `[-4.116556, -3.871608]`。

以上五项对应的 Holm-adjusted randomization p-value 均小于 `8e-6`。因此不能写成 AegisAir 全指标支配 PCBF：AegisAir 在该 testbed 中获得更高 margin、更短路径、更少干预与更低延迟，但使用更高 control effort。两者的 selected-output infeasible steps 均为零。

生成物：`analysis.json`、`paired_comparisons.csv`、`external_baseline_tradeoff.{png,pdf}`、`paired_effects.{png,pdf}`。
