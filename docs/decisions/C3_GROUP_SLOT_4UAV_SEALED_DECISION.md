# C3-GroupSlot 四机 Sealed Validation 决策

## 决策

**SEALED GO：四机中等密度分组走廊结果可进入论文正文。**

在 calibration 和五 seed qualification 通过后，冻结 seeds `10001--10020`，保持
GroupSlot、几何、RA、20 Hz、60 s、完成门和停止规则不变。20 个有效 trial 均使用全新
PX4/Gazebo 栈，联合成功 20/20；成功率 Wilson 95% CI 为 `[0.8389, 1.0000]`。

## 汇总指标

| 指标 | 结果 |
|---|---:|
| 有效 trial | 20 |
| 无效基础设施启动 | 1 |
| 四机任务联合成功 | 20/20 |
| collision | 0/20 |
| QP 不可行 | 0（全部 trial） |
| RA bypass | 0（全部 trial） |
| `min_rho` 均值 | 0.304034 |
| `min_rho` bootstrap 95% CI | [0.298142, 0.309604] |
| `min_rho` 范围 | [0.268621, 0.323986] |
| 路径长度均值 | 30.150056 m |
| P99 求解时间均值 | 3.190241 ms |
| 最差 trial P99 | 4.024828 ms |
| 合并 P50 / P95 / P99 | 1.725271 / 2.722398 / 3.409217 ms |
| 全步最大求解时间 | 63.559834 ms |
| 50 ms deadline miss | 5/24,000（0.0208%） |

合并统计覆盖 20 个有效 trial 的 24,000 个控制步。五次 deadline miss 分别出现在五个
trial 中；其总体比例仍低于冻结的 `<1%` 闸门，因此不改变 `SEALED GO`。正文不得将本结果
写成“零 deadline miss”，也不得只报告 P99 而隐藏最大值。

20 份 trial 的 `summary.json`、轨迹 SHA-256、`integrity.sha256` 与 `COMPLETE` 均已
核验；根级 `sealed_summary.json`、`sealed_integrity.sha256`、`SEALED_GO` 和
`COMPLETE` 已生成。

