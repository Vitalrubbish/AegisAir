# C3-Reservation 四机 Calibration 决策

## 结论

**Calibration GO；尚不是 sealed 论文证据。**

C3-Reservation 复用既有 `safe_holding_point`，补齐“等待稳定、目标服务锁存、
终点清空、下一机释放、全部穿越后的最终归位”。在冻结四机 simultaneous crossing
与 HOCBF-v4 条件下，单个有效 calibration seed 同时满足正裕度、QP 可行、权限边界
和任务完成门。

该结果不覆盖：

- 原 C3 fail-closed orphan-goal recovery；原结论保持不变；
- C3-Admission v2 的 No-Go；R2 在本次同条件运行仍出现负裕度和 QP 不可行；
- 多 seed、其他几何、真实飞行或统计优越性。

## 新机制

```text
NORMAL
  → ADMISSION_PENDING
  → STAGING                 # 所有等待机到冻结安全点且速度稳定
  → PASS(agent_i)
  → GOAL_SERVICE_LATCHED
  → CLEAR(agent_i)          # 到一次性冻结的航路外清空点
  → RELEASE
  → 下一架 PASS
  → FINAL_RETURN            # 全部清空后逐架回原目标
  → COMPLETE
```

连续明确 RA veto 会进入 `REVOKE_HOLD`。明确 veto 只由冻结 RA 输出
`feasible=false` 判定；可行 HOCBF 在目标附近为 PX4 超调制动而产生的反向
`safe_action` 不是 veto。

## 协议与结果

- manifest：`configs/c3_reservation_4uav_calibration_smoke_v1.json`
- manifest SHA-256：`5717b58ad9a61554089e32e37b82ddac693ed47afcc33f283340565156cb5418`
- 有效输出：`/Volumes/Expansion/Aegis/c3_reservation_4uav_calibration_smoke_v1_retry1/calibration`
- seed：`9521`
- 四机：`2/3/4/5`
- 控制率：20 Hz；1200 步；60 s
- R2/R3 共享起点、目标、RA 参数、冲突区、准入时域和执行模型
- `COMPLETE` 与逐文件完整性校验通过

| 指标 | R2 C3-Admission | R3 C3-Reservation |
|---|---:|---:|
| 四机最终归位 | 是 | 是 |
| collision | 0 | 0 |
| min rho | -0.841959 | **+0.186606** |
| min distance | 0.7002 m | **1.4857 m** |
| selected QP 不可行步 | 60 | **0** |
| RA bypass | 0 | 0 |
| service/clear/final return | 不适用 | **4/4、4/4、4/4** |
| revoke hold | 不适用 | 0 |
| P99 | 18.546 ms | **9.571 ms** |
| deadline miss | 5/1200 | **1/1200（0.083%）** |
| 平均控制努力 | 0.204072 | **0.051849** |
| 路径长度 | 73.196 m | **65.136 m** |

R3 首次触发位于 step 0，当时当前 `min_rho=0.586975`。状态转换完整，四个清空点
在 episode 内各只有一个版本；step 1185 进入 `complete`。

## 无效实现运行

目录 `/Volumes/Expansion/Aegis/c3_reservation_4uav_calibration_smoke_v1` 保留首次运行。
该次把 step 367--369 的可行目标附近制动误判为 RA veto，并错误进入
`revoke_hold`。审计显示这些步 `feasible=true`、`recovery_active=false`，且裕度从
0.773 上升到 0.830，属于 veto 分类器实现错误。目录内
`INVALID_IMPLEMENTATION_VETO_CLASSIFIER.md` 已说明；未删除轨迹或 summary。

修复只收紧审计分类，不改变运动指令、RA、场景、manifest 或通过门。随后使用完全
相同 manifest 产生上述有效结果。

## 当前可写主张

可以写为 calibration finding：

> 在一个四机对称交换 calibration 中，单纯通行排序虽完成任务但违反冻结安全裕度；
> 终点占用感知的安全等待—清空—最终归位预约在同一不可绕过 RA 边界下完成四机任务，
> 且该次运行保持正裕度和 QP 可行。

不能写：

- R3 已统计优于 R2；
- C3 已普遍证明四机安全；
- 单 seed GO 可替代 sealed paired validation；
- 零碰撞、正 `rho` 可外推为真实飞行或全局保证。

## 下一闸门

只有冻结新的 sealed paired manifest、使用独立 seeds 并完成完整性审计后，才能判断
该机制是否进入论文主证据。sealed 前不得再根据本 calibration 调整清空点规则、
状态门、RA veto 定义、RA 参数或任务时域。
