# C1 PX4 telemetry-delay No-Go 归因（只读诊断）

本文件解释 `aegisair-c1-px4-telemetry-delay-v1` 的首个冻结 trial 为什么得到
`full_envelope min_rho=-0.296013`。它**不修改** C1 参数、停止规则或 No-Go 决策。

## 1. 排除项

- 不是启动/坐标错误：episode 第 0 步实际机间距为 8.09 m，接近冻结起点间距 8 m；两机
  均完成 PX4 velocity-reset，轨迹无 collision。
- 不是 AoI margin 缺失：full 条件的 peer age 为约 0.300–0.402 s，`d_safe` 明显大于
  no-AoI 条件；同一 trial 的 no-AoI 最低距离仅 0.3966 m，`min_rho=-0.713061`，比 full
  条件更差。
- 不是 RA 未介入：full 条件记录 1128 个 CBF intervention；两架本地 RA 从第 28 步起均
  进入 sampled-data QP infeasible/braking 路径。

## 2. 直接时序证据（full_envelope，seed 5101）

| step（t） | 实际距离 | peer age | `d_safe` | `rho` | QP |
| ---: | ---: | ---: | ---: | ---: | --- |
| 0（0 s） | 8.090 m | 0.000 s | 0.582 m | +12.890 | feasible |
| 20（1.0 s） | 6.829 m | 0.301 s | 3.434 m | +1.010 | feasible |
| 30（1.5 s） | 5.451 m | 0.300 s | 4.584 m | +0.192 | infeasible |
| 62（3.1 s） | 2.578 m | 约 0.30 s | — | **-0.058** | infeasible |
| 68（3.4 s） | 2.129 m | 0.402 s | 2.985 m | **-0.296** | infeasible |

`d_safe=d0+M_dyn+M_comm`。在对头高速接近时，`M_dyn` 同时包含反应/控制时延和制动项；
300 ms AoI 还带来 `M_comm=2·AoI+1.5·AoI²`。因此 full 条件在延迟缓冲建立后，安全边界从
启动阶段的约 0.58 m 迅速增长到约 4.58 m。此时真实距离虽仍为 5.45 m，但双机闭合速度已
接近 2.9 m/s，局部 QP 已无法找到维持下一采样边界的动作。

## 3. 根因链

1. **delay warm-up 的安全边界跃迁。** `SharedStateEstimator` 在其 300 ms 历史尚未填满时
   回传当前样本；约 0.3 s 后才选择真正延迟 peer 样本。RA 因而从低 AoI/小边界启动，随后在
   双机已加速相向时切入完整的 300 ms 通信 margin。
2. **对称对头的可达性不足。** 两机均朝对方目标以 `NOMINAL_GAIN=1.5` 加速；一旦边界增至
   约 4.6 m，双方同时制动仍无法让 sampled-data QP 满足扩张后的 next-step 约束。证据是
   第 28 步起两侧 `feasible=false`，而非单侧故障。
3. **stale-view 可行性切换造成刹车—再加速。** 例如 step 50–55，局部 stale view 报告
   `rho≈+0.52/+0.59` 并恢复朝目标的命令；step 60 又因边界/闭合速度变化重回 infeasible。
   这使实际距离继续缩小，直到负裕度区间。
4. **执行模型仍是放大因素。** 本 C1 transfer 内部 RA 使用 `tau_px4=0.2 s` 的一步预测，
   但 PX4 阶跃辨识约为 0.5–0.7 s；外部命令已用 `feedforward_tau=0.7 s` 改善速度设定点，
   却没有令 barrier 内部的完整可达性预测与该执行模型共同重冻结。C3 的平行恢复场景未暴露
   这一点；本 C1 对头+陈旧 peer 场景将其放大。

## 4. 结论与下一步边界

这不是“full envelope 无效”的反向证据：它相对 no-AoI 保持了更大的最小距离（1.0305 m vs
0.3966 m）和较高的裕度。但它明确否定了当前冻结实现可在该 PX4 对头/300 ms peer-delay
包络内维持 `rho>0` 的主张。

不应通过本 trial 调整 margin、τ、初始距离、NOMINAL_GAIN 或让行策略后续跑。若另立研究，
应先冻结一个不同假设，例如“进入交会前的 admission control / delayed-peer warm-up holding
是否能避免不可达边界”，并把 estimator warm-up、执行模型与局部可达性一并纳入新协议。

## 5. 与已修复的轻量 C1 300 ms 问题的对应关系

本次**不是**旧 D1/D2 bug 的回归。旧问题是将本机状态也经 300 ms estimator 延迟，或让
nominal 使用当前状态而 RA 使用所有陈旧状态，导致自身几何/速度闭环不一致。C1 v6 的 D3
修复改为“本机新鲜、peer 陈旧、每机独立 RA”；本 PX4 runner 已用同一
`local_fresh_self_stale_peers` 局部视图，且 trajectory 的本机位置来自当前 telemetry。

但 D3 从未证明 300 ms 条件下始终 `rho>0`。轻量 C1 v6 的 telemetry-delay cell 已是
collision 0%、平均最小距离 0.760 m，而 full 条件 `min_rho=-0.384615`；no-AoI 为
`-0.424000`、最小距离 0.288 m。也就是说，当时的修复解决的是**碰撞与观测一致性**，
而非保证扩张后的动态安全边界始终可达。

PX4 C1 的结果与这一残余限制方向一致：full 条件保持更大物理分离（1.0305 m vs 0.3966 m）
却仍有负 `rho`。不同之处在于真实飞控的执行滞后、20 Hz 实时调度和 estimator warm-up 使
QP infeasible 与刹车—再加速切换可直接在 trajectory 中观察到。因此正确表述是：**D3 修复
已正确移植，但它没有也不曾解决 delayed-peer 对头交会的可达性/执行一致性问题。**
