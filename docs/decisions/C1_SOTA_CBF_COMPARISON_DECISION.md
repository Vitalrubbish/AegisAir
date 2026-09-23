# C1 强 CBF 基线适配与对比裁决

> 日期：2026-08-22  
> 总裁决：**v2 轻量仿真 GO、PX4/Gazebo NO-GO；结构修复后的 v3 在独立轻量与
> PX4/Gazebo 20-seed validation 均 GO。加强后的 PB-CBF 是当前 SOTA 主基线；v4 的
> 可行余量感知 PB 恢复已通过 3-seed PX4 smoke，但尚未完成独立 validation。**

## 1. 比较对象与选择理由

本次没有选择明显偏弱的 strawman，而是采用两个 2024 年提出、理论能力与本文问题直接
相关的方法，再保留一个工程上很强的标准速度 CBF：

1. **ZOCBF**：Xiao Tan、Ersin Das、Aaron D. Ames、Joel W. Burdick，
   *Zero-order Control Barrier Functions for Sampled-Data Systems with State and Input
   Dependent Safety Constraints*，arXiv:2411.17079。其优势是无需对 barrier 求导，直接约束
   相邻采样时刻，且显式面向 sampled-data、高相对阶和 state/input-dependent constraint。
   官方实现：<https://github.com/ersindas/Zero-order-CBFs>。
2. **Prediction-Based CBF（PB-CBF）**：Ali Mesbah、Seid H. Pourtakdoust、Alireza
   Sharifi、Afshin Banazadeh，*Prediction-Based Control Barrier Functions for
   Input-Constrained Safety Critical Systems*，arXiv:2412.12926。其优势是把有限制动能力所需
   的预测裕度写进 barrier，直接针对 input-constrained feasibility。
3. **Velocity-CBF**：标准一阶相对位置速度 CBF-QP。它不是 2024/2025 SOTA，但在本环境中
   是最强实际基线，不能省略，也没有被人为降速或缩小任务难度。

未将 predictive terminal-set CBF 或 neural input-constrained CBF 纳入主比较：前者需要为本
多机任务另行设计终端安全集，后者需要训练网络；两者都会同时改变 barrier、训练数据和任务
结构，无法在本轮形成可归因的纯 CBF 对照。

## 2. 公平适配与冻结边界

- 所有方法共享相同场景、seed、名义控制、20 Hz、`v_max=1.5 m/s`、`a_max=2.0 m/s²`、
  执行模型与命令前馈 `tau=0.7 s`。
- 统一用完整动态/AoI safety envelope 离线计算公共 `rho`；内部约束保持方法忠实：标准
  velocity-CBF、ZOCBF、PB-CBF 使用各自静态几何 barrier，本文 HOCBF 使用动态/AoI boundary。
  因此比较的是同一公共安全口径，而不是把各方法自己的 barrier 值混在一起。
- ZOCBF 使用一阶速度滞后下精确的单步位置系数
  `beta=dt-tau(1-exp(-dt/tau))`；PB-CBF 使用径向闭合速度与有限制动距离；本文方法使用
  二阶 HOCBF，并以冻结的 execution-model one-step boundary-growth guard 处理下一周期动态
  边界增长。
- calibration seeds 为 7301–7305；轻量 sealed v1 为 7401–7420；结构修复后的 sealed v2
  为 7501–7520；PX4 smoke 为 7601；PX4 sealed validation 为 7701–7720。各层互不复用。
- 参数选择按碰撞、公共边界 violation、QP infeasible、完成率、控制代价的词典序执行；不以
  sealed 结果反调参数。

## 3. 轻量 sealed validation

每个方法为 20 seeds × 3 场景，共 60 episodes；完整原始结果与审计分别位于：

- `/Volumes/Expansion/Aegis/c1_sota_cbf_active_validation_v1.json`
- `/Volumes/Expansion/Aegis/c1_sota_cbf_active_validation_v1_audit.json`
- `/Volumes/Expansion/Aegis/c1_sota_cbf_active_validation_v2_boundary_growth.json`
- `/Volumes/Expansion/Aegis/c1_sota_cbf_active_validation_v2_audit.json`

v1 本文 HOCBF 有 4/60 公共边界 violation，最差 `rho=-0.027616`，按规则 NO-GO。没有在
该 sealed set 上调参；另立结构假设：动态 boundary 在执行滞后的一步内增长，而原 HOCBF
只约束当前 sample-held boundary。使用原 calibration seeds 冻结 `k1=4`、`k2=6`、
`boundary_guard=0.5`、buffer=0 后，再用独立 v2 seeds 验证。

| 方法 | collision | 公共边界 violation | 完成 | 最低 rho | CBF events | QP infeasible | 平均控制代价 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AEGIS_HOCBF_V2 | 0/60 | 0/60 | 60/60 | +0.023085 | 9,128 | 0 | 0.562700 |
| Velocity-CBF | 0/60 | 0/60 | 60/60 | +0.002617 | 18,897 | 0 | 0.588027 |
| PB-CBF | 0/60 | 20/60 | 40/60 | −0.392934 | 27,256 | 5,887 | 0.906863 |
| ZOCBF | 16/60 | 51/60 | 20/60 | −0.659413 | 27,722 | 7,904 | 1.086367 |

与真正强的 velocity-CBF 相比，本文方法在同为 60/60 安全完成时，每 trial 少 488.45 次
介入，cluster bootstrap 95% CI `[−512.85, −465.05]`；平均控制代价差为 −0.02533，95% CI
`[−0.03922, −0.01159]`。本文方法的平均 `min_rho` 并不更大，因此论文主张必须是
**等安全/等完成下更少干预和更低控制代价**，不能写成全指标支配。

## 4. PX4/Gazebo smoke 与迁移裁决

完整审计：`/Volumes/Expansion/Aegis/c1_sota_cbf_px4_audit_v1.json`。

每个方法使用 fresh SITL；第一次把四个 condition 串在同一 SITL 的尝试因第二次复位导致
PX4 EKF 发散，判为基础设施无效并保留。随后发现 HOCBF `FilterResult` 漏写 `a_safe`，使
PX4 `feedforward_tau` 实际发送近似当前速度；已修复并增加回归测试，全套 175 tests 通过。

| 方法 | 完成 | collision | 最低 rho | CBF events | QP infeasible | smoke |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Velocity-CBF | 是 | 0 | +0.305846 | 110 | 0 | PASS |
| AEGIS_HOCBF_V2 | 是 | 0 | +0.014206 | 72 | 20 | PASS，但裕度紧且存在 infeasible |
| PB-CBF | 是 | 0 | −0.115159 | 68 | 0 | FAIL（公共边界） |
| ZOCBF | 否 | 0 | −0.403264 | 706 | 353 | FAIL |

只有 smoke 绝对通过的 velocity-CBF 与本文方法进入 20-seed PX4 validation。首个 sealed
seed 7701 中：velocity-CBF `rho=+0.346493`；本文 HOCBF-v2 虽任务完成且 collision=0，
但 `rho=-0.023440`、QP infeasible 21 steps。预冻结门要求两个方法均 20/20 `rho>0`，因此该
门已数学上不可达，立即停止剩余 19 seeds，裁决 **NO-GO_STOP_RULE**。

## 5. 论文口径

### 5.1 v3 结构修复与独立验证

v2 PX4 负裕度的直接链路为：高增益 HOCBF 在远离边界时约束较松，接近动态边界后 QP
突然不可行；旧 fallback 仅使用 `a=-v`，在约 1 m/s 速度下没有使用允许的完整
`a_max=2 m/s²`；单周期 0.15 m buffer 也没有覆盖遥测与命令两个 20 Hz pipeline 周期。

v3 冻结三项结构变化：

1. `boundary_guard=1.0`，纳入完整一步动态边界增长；
2. `boundary_buffer=2*v_max*(telemetry_dt+command_dt)=0.30 m`；
3. QP 不可行时沿当前速度反方向使用完整 `a_max`，作为显式 fail-closed backup。

原 calibration seeds 7301–7305 的独立增益扫描选择 `k1=k2=4`。独立轻量 seeds
7831–7850 中，本文与 velocity-CBF 均 60/60 完成、零碰撞、零边界违反、零 QP infeasible；
本文最低 `rho=+0.337659`。

PX4/Gazebo 使用独立 seeds 8001–8020、20:20 paired conditions、Latin-square 顺序且每
condition fresh SITL。审计文件为
`/Volumes/Expansion/Aegis/c1_hocbf_v3_px4_validation_v1_audit.json`。

| 方法 | 完成 | collision | violation | 最低 rho | CBF events | QP feasibility-loss | 控制 effort | 平均路径 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AEGIS_HOCBF_V3 | 20/20 | 0 | 0 | +0.009999 | 1,852 | 434 | 0.223355 | 18.460 m |
| Velocity-CBF | 20/20 | 0 | 0 | +0.295866 | 2,164 | 0 | 0.096634 | 19.226 m |

本文每 trial 少 15.6 次介入，paired cluster-bootstrap 95% CI `[−17.40,−13.55]`，平均
路径短 0.766 m；但平均 `min_rho` 低 0.2505、控制 effort 高 0.1267，且安全闭环依赖
434 个 feasibility-loss step 中的最大制动 backup。因此 v3 是**正裕度系统闭环 GO**，不是
“HOCBF-QP 单独全程可行”或“全面优于 velocity-CBF”。

### 5.2 最终可写边界

可以写：

1. 在冻结轻量执行模型与三类几何中，execution/AoI-aware HOCBF-v2 相对强 velocity-CBF
   达到同等安全和完成率，同时显著降低干预次数与控制代价。
2. ZOCBF 与 PB-CBF 是能力相当、针对 sampled-data/input constraints 的近期方法；在本次
   method-faithful 适配和公共动态安全口径下没有通过，但该结果只约束本环境适配。
3. PX4 smoke 暴露并修复了 HOCBF 加速度到速度前馈的接口缺口；修复后机制会真实介入。
4. 首个 sealed PX4 seed 否定了“轻量正裕度结论可直接迁移到 PX4”的假设，执行 fidelity
   仍是设计约束；v3 通过双周期 buffer 和 fail-closed maximum-braking backup 闭合该边界。
5. v3 在独立 PX4 20-seed 中与 velocity-CBF 均保持 20/20 正裕度和完成；本文方法减少
   介入次数并缩短路径，但以更高控制 effort、更低裕度和频繁 backup 为代价。

不得写：

- “本文 HOCBF 全面优于 velocity-CBF”；强基线在裕度、控制 effort 和 QP 可行性上更好。
- “本文方法普遍优于 ZOCBF/PB-CBF”；只能报告冻结适配结果。
- “零碰撞等于安全”；PX4 sealed seed 已出现公共 `rho<0`。
- 用 sealed seed 7701 调 guard/buffer 后仍称同一 validation。
- 把 434 个 feasibility-loss step 隐藏为普通 HOCBF intervention，或声称 HOCBF-QP 全程可行。

## 6. SOTA-only 更新与 HOCBF-v4 开发门

后续共享执行预算适配后，PB-CBF 在 PX4 smoke 中成为真正强基线；velocity-CBF 退出主文
SOTA 比较，仅保留补充材料。SOTA-only 轻量结果与 v3/PB PX4 诊断见外置盘
`c1_sota_only_validation_v1.json`、`c1_sota_only_px4_smoke_v1` 和
`c1_hocbf_v3_vs_pb_px4_validation_v1`。后者完成 5 个 paired diagnostic seeds 后按用户要求
停止，这些 seeds 已用于设计 v4，不得恢复为 sealed validation。

v4 采用 HOCBF 主过滤、归一化加速度 box 可行余量、执行延迟探测、PB-CBF 恢复和滞回退出。
独立 seeds 8801–8803 的 fresh-SITL smoke 中，v4 3/3 完成、collision=0、最低
`rho=+0.184536`、选中链路 infeasible=0；v3 最低 `rho=+0.048666` 且累计 65 个
feasibility-loss，PB-only 最低 `rho=+0.473125` 但平均 162 次介入。三次 v4 均提前 2 个
20 Hz 周期进入 PB 恢复。完整边界见
`docs/decisions/C1_HOCBF_V4_FEASIBILITY_RECOVERY_DECISION.md`。
