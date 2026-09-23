# C3-GroupSlot 四机 Qualification 决策

## 决策

**GO：允许设计独立 sealed validation。**

中等密度分组走廊 calibration seed 9901 通过后，qualification v2 使用五个全新
Gazebo seeds `9921--9925`。五个有效 trial 均使用全新 PX4/Gazebo 栈，结果全部满足
联合安全、任务与实时性门。

| seed | 完成 | collision | min_rho | QP 不可行 | RA bypass | P99 ms | deadline miss |
|---:|:---:|:---:|---:|---:|---:|---:|---:|
| 9921 | 是 | 0 | 0.299460 | 0 | 0 | 2.748 | 0 |
| 9922 | 是 | 0 | 0.296833 | 0 | 0 | 3.663 | 0 |
| 9923 | 是 | 0 | 0.290325 | 0 | 0 | 3.313 | 0 |
| 9924 | 是 | 0 | 0.296830 | 0 | 0 | 3.545 | 0 |
| 9925 | 是 | 0 | 0.304135 | 0 | 0 | 3.303 | 0 |

所有 trial 的等待点冻结审计、模式覆盖和两组授权审计均通过；各自
`integrity.sha256`、`COMPLETE` 以及根级 `QUALIFICATION_GO/COMPLETE` 已核验。

## 基础设施审计

早期 qualification v1 因 trial 间 PX4 子进程未完全退出而产生无效启动；这些运行不计入
算法样本。修复内容包括真实 telemetry 字段探针、adapter 顺序启动和显式 PX4 子进程
清理。v2 使用全新 seeds，未用失败结果调参。

## 主张边界

本结果只支持冻结的四机中等密度分组走廊扩展，不支持极端终点交换、一般化四机安全、
MAPPO 性能提升或最终成功率估计。qualification 不是 sealed 统计证据。
