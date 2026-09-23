# C3-Admission 四机 Calibration 决策

## 结论

**最终决策：NO-GO。停止调参，不生成 sealed seeds。**

新增 C3-Admission 已完成接口冻结、状态机、RA 前后权限链接入和四机 PX4/Gazebo
calibration。它能在冲突形成前改变协调结构，但在当前四机 simultaneous crossing、
固定等待点和冻结 HOCBF-v4 参数下，未同时满足正安全裕度、QP 可行和任务完成要求。

该结论不改变原 C3 结果：原 C3 仍只证明飞行器失效后的 fail-closed orphan-goal
recovery；C3-Admission 是独立事件分支，其负结果不能回填或否定原 C3。

## 冻结权限链

```text
nominal / LLM / MARL intent
        ↓
C3 Mission Coordinator
  ├─ vehicle failure → 原 orphan-goal recovery
  └─ conflict risk → C3-Admission passage/hold
        ↓
RA / HOCBF / PB recovery
        ↓
PX4 adapter
```

- `CoordinationAdmissionDecision` 已冻结到 `swarm/interfaces.py`；消息不含直接执行器命令。
- 状态机为 `normal → admission_pending → hold → pass → release`。
- 冲突区预测和 `reserve_low | predicted_rho_low` 必须同时开门。
- 等待点在一次 admission 周期进入时冻结，期间不重算。
- 每步记录准入机、等待机、冻结点、进入步、冲突区、RA 否决和权限来源。
- live runner 中 C3 只改写名义目标/尺度；所有命令仍经过同一 RA，实测 `RA bypass=0`。

## 运行与完整性

### v1 初始定义

- manifest：`configs/c3_admission_4uav_calibration_smoke_v1.json`
- 结果：`/Volumes/Expansion/Aegis/c3_admission_4uav_calibration_smoke_v1/calibration`
- 冲突区半径 `1.25 m`，准入时域 `2.5 s`
- manifest SHA-256：由结果目录 `manifest.sha256/integrity.sha256` 保存
- `COMPLETE` 存在，全部轨迹与 summary 完整性校验通过

### v2 唯一一次允许的修订

- manifest：`configs/c3_admission_4uav_calibration_smoke_v2.json`
- 有效结果：`/Volumes/Expansion/Aegis/c3_admission_4uav_calibration_smoke_v2_retry1/calibration`
- 冲突区半径 `2.0 m`，准入时域 `3.0 s`
- manifest SHA-256：`35179f2a3b8d63e612df28cab01fd81de72ac9872846344bc6063d272d8bcfa0`
- `adjustment_count=1`，唯一调整额度已消耗
- `COMPLETE` 存在，全部轨迹与 summary 完整性校验通过
- 此前同一 v2 manifest 有一次 `telemetry not ready for all drones`，目录
  `/Volumes/Expansion/Aegis/c3_admission_4uav_calibration_smoke_v2` 保留为无效基础设施启动，
  没有轨迹或有效 episode，未作为结果替换。

## 结果

| 定义/条件 | 完成 | min rho | QP 不可行步 | P99 / deadline miss | 准入审计 |
|---|---:|---:|---:|---:|---|
| v1 R0 RA-only | 否 | -0.363002 | 749 | 25.939 ms / 2 | C3-Admission 不存在 |
| v1 R1 SEQUENTIAL_PASS | 否 | -0.449768 | 592 | 35.530 ms / 5 | C3-Admission 不存在 |
| v1 R2 C3-Admission | 是 | -0.715494 | 198 | 15.765 ms / 2 | step 22 触发；冻结点稳定；RA veto 280 步 |
| v2 R0 RA-only | 否 | -0.503633 | 729 | 15.069 ms / 4 | C3-Admission 不存在 |
| v2 R1 SEQUENTIAL_PASS | 否 | -0.394599 | 351 | 40.710 ms / 6 | C3-Admission 不存在 |
| v2 R2 C3-Admission | 否 | -0.384322 | 358 | 23.882 ms / 2 | step 0 触发；冻结点稳定；RA veto 365 步；结束仍 active |

所有有效条件均无物理碰撞且 `safety_bypass_count=0`。但零碰撞不能覆盖负 `rho`、
QP 不可行、deadline miss 或任务失败。

## 可证实与不可证实内容

可以写：

> 原 C3 验证 fail-closed orphan-goal recovery。新增 C3-Admission 证明同一权限边界
> 可以审计地实施事件触发通行顺序，并能把触发提前到当前裕度仍为正的时刻；但本次
> 四机 calibration 未通过安全可行性与任务联合闸门，因此该分支不进入 sealed 验证。

不能写：

- C3 已证明四机安全或任务性能；
- C3-Admission 优于 RA-only 或 SEQUENTIAL_PASS；
- 无碰撞等价于正安全裕度或连续时间保证；
- 继续修改冲突区、时域、RA 参数或使用 sealed seed 挽救该分支。

## 停止边界

本方向保留为可复现实验平台和负结果，不作为当前二区稿 headline contribution。
若未来重新研究，必须提出新的、可证伪的协调机制和独立预注册协议，而不是在本 v2
上继续调参。当前工作回到尚未完成的文献/匹配基线与证据打包；文献按用户要求最后处理。
