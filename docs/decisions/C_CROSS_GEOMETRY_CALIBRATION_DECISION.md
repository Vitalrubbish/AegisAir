# C 工作包跨几何失效恢复 calibration 决策

> 日期：2026-08-24  
> 决策：`NO_GO`，不生成 20-seed sealed manifest  
> 原始数据：`/Volumes/Expansion/Aegis/c_cross_geometry_calibration_smoke_v1`

## 1. 冻结协议

- manifest：`configs/c_cross_geometry_calibration_smoke_v1.json`
- manifest SHA-256：`8b1934c6e4f6b8104a595eb0e7bc2ec6d534c2616ae89b73996414bd16920e06`
- 三种预注册几何：`on_path_failure`、`lateral_failure`、
  `bottleneck_merge_failure`。
- 每个几何一个独立 calibration seed、fresh PX4/Gazebo、R0/R1 配对；共 6 个有效 episode。
- R0：RA-only；R1：deterministic RuleMissionPlanner + 同一 RA。LLM/MARL 不参与。
- 失效发生于 step 30；`feedforward_tau=0.7 s` 与 HOCBF-v4/PB recovery 参数保持冻结。
- 主闸门：三个几何均要求 R0 不覆盖、R1 覆盖、`collision=0`、`min_rho>0`、
  selected-QP infeasible=0、RA bypass=0、失效机权限逐步撤销且 P99 `<50 ms`。

## 2. 有效结果

| 几何 | R0 coverage | R1 coverage | 最低 rho | selected-QP infeasible | 碰撞 | 最大 P99 | 决策 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| on-path | 0 | 1 | `-0.515746` | 3 | 0 | 1.058 ms | No-Go |
| lateral | 0 | 1 | `-0.043064` | 0 | 0 | 1.092 ms | No-Go |
| bottleneck merge | 0 | 0 | `-0.395008` | 516 | 0 | 1.080 ms | No-Go |

共同通过的审计项：

- 6/6 episode `collision=0`，但仿真零碰撞不能替代正裕度门槛；
- 6/6 episode 从 change step 起，失效机每步均为 `command_authority=failed_zero`，水平命令为零；
- 所有轨迹 `ra_bypass_count=0`；
- 所有 R1 均在 step 31 提交一次确定性 mission change；
- 所有 episode RA deadline miss 为 0，计算不是失败原因；
- 12 个 manifest/trajectory/summary 哈希全部通过。

## 3. 无效启动与恢复

第一次完成 on-path 后，清理竞态使 lateral 和 bottleneck 启动器检测到上一实例尚未退出并拒绝启动；
两次分别标记为 `invalid_launch`，不计入算法样本。编排随后改为等待本次 `STATE` 记录的精确 PID，
并使用同一 manifest 断点续跑；已完成 on-path 按 summary 跳过，最终获得三个几何、6 个有效 episode。
早期错误 `COMPLETE` 保留为 `PREMATURE_COMPLETE_BEFORE_RESUME`，没有隐藏。

## 4. No-Go 解释

1. on-path 表明当前规则重分配能完成 orphan goal，但进入了冻结 RA 的负裕度/局部不可行区域。
2. lateral 没有 selected-QP infeasible，却仍出现轻微负裕度；不能把“QP 可行”写成“安全裕度满足”。
3. bottleneck 中恢复既未覆盖 orphan goal，又有 516 个 selected-QP infeasible 步，是明确的恢复包络外结果。
4. 权限撤销、RA 不可绕过与计算 deadline 均通过，因此负结果定位在“任务重分配进入安全层可恢复域之前
   缺少 admission 检查”，而不是 LLM、权限旁路或算力不足。

## 5. 决策与新主张边界

**停止工作包 C 的 20-seed sealed validation，不调几何、阈值、故障时刻或 recovery 参数。**
原 C3 单几何 30-seed 正结果继续有效，但不能外推到本轮三种新几何。

若继续研究，应另立新的可证伪主张：在提交 orphan-goal reassignment 之前，由 RA 对任务候选执行
failure-aware recoverability admission；不可准入时保持 fail-closed，而不是先提交任务再等待 PB
recovery 处理。该方向必须使用新的 calibration/sealed seeds 和输出目录，且不能回写本次 No-Go。
在它通过之前，论文不能声称“跨三种失效几何均安全恢复”。
