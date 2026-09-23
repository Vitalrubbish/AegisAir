# C3-Reservation 四机 Qualification 冻结协议

## 研究问题

四机终点交换同时包含共享冲突区和终点占用。该 qualification 只检验：在不可绕过的
Runtime Assurance 边界下，C3-Reservation 的等待、逐机通行、目标服务锁存、航路外
清场和最终归位生命周期，能否稳定恢复四机任务活性。

论文定位固定为：

> **Four-UAV terminal-exchange stress validation**

不把该实验写成 MAPPO 性能提升，也不外推为一般化四机安全。

## 主对照与冻结对象

- `R2_C3_ADMISSION`：只有冲突前准入和冻结等待，没有终点清场生命周期；
- `R3_C3_RESERVATION`：完整等待—服务—清场—释放—最终归位生命周期。

R2 是机制消融，R3 是完整方法。RA-only、SEQUENTIAL_PASS 和旧 MAPPO 负结果只作
补充背景，不扩大本主实验。

以下对象直接继承 calibration manifest，不允许修改：

- UAV：`2/3/4/5`，最多四机；
- 四机起点、终点和终点容差；
- 20 Hz、1200 步、60 s；
- 冲突区、3 s 准入时域、等待点和清场点规则；
- HOCBF-v4、执行时延模型、RA 参数和 veto 定义；
- C3 状态门与 `safe_holding_point` 冻结语义。

## Qualification seeds 与顺序

使用五个未用于 calibration 的新 Gazebo seeds：`9601–9605`。R2/R3 使用相同 seed，
条件首位按 `3:2` 平衡：

| seed | 第一个条件 | 第二个条件 |
|---:|---|---|
| 9601 | R2 | R3 |
| 9602 | R3 | R2 |
| 9603 | R2 | R3 |
| 9604 | R3 | R2 |
| 9605 | R2 | R3 |

每个 seed-condition 是独立 physical trial，必须使用全新 PX4/Gazebo/SITL，不能在同一
PX4 进程中复位后继续下一条件。

## 无效启动与完整性

遥测未全部就绪、连接丢失、PX4/Gazebo 启动失败或 runner 未产生 `COMPLETE`，均记为
基础设施无效启动，不计入算法样本。同 seed-condition 最多允许三次全新基础设施重试；
所有失败目录必须保留。

有效 trial 必须同时具有 manifest hash、原始 JSONL、summary、逐文件 SHA-256 和
`COMPLETE`。有效算法失败不得重跑或替换。

## R3 即时停止门

五个 R3 有效 trial 必须全部满足：

- 四机最终归位且状态机进入 `COMPLETE`；
- `service_latched/cleared/final_returned` 均为 4/4；
- collision 为 0、`min_rho>0`；
- selected QP infeasible 为 0；
- RA bypass 为 0、`revoke_count=0`；
- RA P99 `<50 ms` 且 deadline miss `<1%`。

任一有效 R3 失败立即 Qualification No-Go，并停止后续算法 trial。不得修改参数、扩大
时域或用新 seed 替换。R2 的结果不决定 qualification Go。

## Sealed 闸门

只有 R3 达到 `5/5` qualification Go，才允许生成固定 20 个全新 seed 的 sealed paired
manifest。sealed 使用 R2/R3 同 seed 配对、`10:10` 条件首位平衡、每条件全新 SITL；
不得查看中途结果后扩到 30 seeds。

qualification 结果不进入最终统计。sealed 才报告 McNemar 精确检验、联合成功率差置信
区间、配对 bootstrap、RMST，以及对连续次要指标配对 sign-flip 检验的 Holm 校正。

## 预注册图形选择

- 轨迹示例按 R3 `min_rho` 排序，展示中位 seed 与最差有效 seed；
- 状态时间线使用同一个预注册中位 seed；
- 所有 seed 绘制 R2/R3 配对 `min_rho`；
- 联合成功定义为完成、正裕度、QP 可行和无 bypass 同时成立；
- 实时性 CDF 使用所有有效逐步求解时间并标出 50 ms deadline。

禁止按视觉效果挑选最好看的轨迹。
