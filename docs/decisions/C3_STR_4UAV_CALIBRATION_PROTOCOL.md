# C3-STR 四机 Calibration Smoke 冻结协议

## 1. 独立性与边界

本协议不修改、覆盖或重跑 C3-Reservation qualification No-Go。C3-STR 是新的可证伪
任务协调机制：C3 冻结服务/归位时间窗和短时航点承诺；Runtime Assurance 仍保留最终
硬安全权。MAPPO 不参与本实验。

## 2. 新增机制

- 四个服务槽保持逐机互斥；
- 清场点到最终目标的线段按 `1.9 m` 静态间隔组成兼容归位组；
- 同一兼容归位组允许并行归位；
- 任何授权不得早于 `planned_open_step`；
- 实际进度超窗或 RA 明确否决时，未完成时间窗只能整体后移；
- RA 否决后的固定等待期间 `authorized_drone_ids=[]`；
- 日志逐步保存窗口、当前槽、修订号、累计延迟和承诺航点。

## 3. 冻结对象

- manifest：`configs/c3_str_4uav_calibration_smoke_v1.json`
- seed：`9701`
- 控制率：`20 Hz`
- 时域：`1200` 步，即 `60 s`
- 时域推导：`6 s staging + 4×8 s service + 2×7 s grouped return = 52 s`，
  另加预先固定的 `8 s` 余量；
- 起点、终点、RA、冲突区、清场规则沿用旧四机场景，不从旧失败结果修改安全参数。

## 4. Smoke Go/No-Go

Go 必须同时满足：

- 状态机进入 `COMPLETE`；
- `service_latched/cleared/final_returned` 均为 `4/4`；
- 至少一个归位槽包含两架兼容无人机；
- `collision=0`、`min_rho>0`、QP 不可行 `0`、RA bypass `0`；
- 没有提前授权、槽成员不匹配或窗口向前移动；
- RA P99 `<50 ms`，deadline miss 率 `<1%`。

本次只运行一个开发 smoke。算法门失败即 No-Go，不调参重跑；纯基础设施或接口实现
错误可修复，但必须保留无效记录。Smoke Go 也不是论文统计，只允许进入新的五 seed
qualification 设计。
