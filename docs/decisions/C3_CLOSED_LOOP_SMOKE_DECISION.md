# C3 闭环（PX4/Gazebo）Smoke 决策（2026-08-21，进行中）

- 决策：**smoke GO。执行模型失配已归因并确认；用 feedforward_tau（τ=0.7s）重跑
  6-trial smoke，R1 6/6 覆盖 orphan goal、R0 6/6 不覆盖，碰撞=0、bypass=0。下一步
  进入 30-trial validation。**
- 数据目录：`/Volumes/Expansion/Aegis/c3_smoke01_v2_20260821`、
  `/Volumes/Expansion/Aegis/c3_closed_loop_smoke_v1/smoke02`。

## 1. 已验证（正项）

- 完整闭环可运行：broker + GCS heartbeat（18572/18573）+ `aegisair-adapters` +
  PX4/Gazebo SITL（实例 2/3）+ `run_c3_gazebo.py` 端到端跑通。
- `connection_lost` 由 GCS heartbeat 正确清除；runner 的 arm/takeoff/velocity-reset
  正常。
- 恢复机制**触发且被采纳**：`drone 2 fail_drone` 在 step 31 触发 MISSION_CHANGE，
  `RuleMissionPlanner` 提交 ABORT(drone 2) + REASSIGN(drone 3 → orphan goal)。
- 碰撞 = 0、`safety bypass = 0`（两条件均未观测到）。

## 2. 结果（max_steps=600，即 30s，修正后）

- smoke01 v2：R0 `critical_reached=false`；R1 `critical_reached=true`（recovery step 31）。
- smoke02：R0 `critical_reached=false`；R1 `critical_reached=false`（recovery step 31，
  但 drone 3 未收敛）。

smoke01 的 R1 达到 orphan goal；smoke02 的 R1 虽触发且朝 orphan 飞行，但 30s 内最小
距离到 (4,0) 仍有 1.40 m（step 186），随后大幅过冲至 x≈11、再回摆，未在
`goal_epsilon=0.5 m` 内收敛。

## 3. 根因（已归因，来自离线拟合）

- 对 smoke01 v2 与 smoke02 的 R1 轨迹，用 `v_act(t+1)=v_act(t)+(v_cmd(t)-v_act(t))·dt/τ`
  拟合一阶速度跟踪时间常数：
  `τ_x ≈ 0.47–0.52 s`、`τ_y ≈ 0.67–0.69 s`（两 trial 一致，约等于 Phase 7 阶跃拟合的
  `τ_hat=0.7 s`）。
- RA 的速度命令是 `v_cmd = v_act + a_safe·dt`（把加速度 Euler 积分为速度设定点），
  隐含"速度在一个控制周期 dt=0.05s 内被跟上"的假设（`tau_px4=0.2 s`）。但真实 PX4
  速度跟踪带宽是 τ≈0.5–0.7s。
- 因此在 `a_safe` 饱和到 ±2 m/s² 时，实测有效加速度只有约 **0.11 m/s²**（约为
  `a_safe·dt/τ`），比 `a_max=2` 慢约 18 倍。
- 该慢速有效加速度叠加比例式 go-to-goal（`NOMINAL_GAIN=1.5`），使 drone 3 在接近
  goal 时刹不住，8 m 直线目标实际走了约 30 m（约 4 倍行程），于是 `critical_reached`
  时灵时不灵。
- 结论：这是**执行模型失配**（RA 假设的快速执行 vs PX4 真实的慢速速度跟踪），不是
  C3 恢复逻辑 bug，也不是轻量仿真能复现的（轻量 exact-ZOH 点质量收敛干净）。C2 的
  闭环指标是最小间距/`min_rho`，不依赖目标收敛，因此此前未暴露；C3 的
  `critical_reached` 首次把目标收敛当主指标，才把它量化出来。

## 4. 不可做的后续

- 不得用 `critical_reached` 的失败去回调 `NOMINAL_GAIN`/`kv`/`a_max`/`goal_epsilon` 等
  参数"救"本假设；那会用 smoke 数据选阈值。
- 不得把 smoke01 的 `critical_reached=true` 单点当成恢复完成率的证据。

## 5. 确认实验（已完成，决定性）

冻结的 2 机 drone_failure、R1-only、`max_steps=600`，只改速度命令机制，不动安全阈值：

| 速度命令机制 | critical_reached | drone 3 路径 | min_rho |
|---|---|---|---|
| (a) `v_cmd = v_act + a_safe·dt`（现状） | false | ≈30.7 m | 0.99 |
| (b) `v_cmd = v_act + a_safe·τ`（τ=0.7s 前馈） | true | ≈13.1 m | 0.29 |
| (c) 直接发 `v_nom` | true | ≈13.5 m | 0.26 |

- (b)/(c) 把 drone 3 的路径从约 30 m 压到约 13 m，且 `critical_reached` 由 false 变 true。
- 结论：**执行模型失配是唯一根因**。现状用 `dt=0.05s` 积分加速度生成速度设定点，
  隐含"一个周期内速度被跟上"的假设，而真实 PX4 速度跟踪 τ≈0.5–0.7s。把命令改成
  τ 前馈或直接发 `v_nom` 后，go-to-goal 收敛，振荡消失。
- 恢复机制（触发 + REASSIGN + fail-closed）自始至终正常；本轮只是把 RA 的速度命令层
  修正到与真实执行一致，不涉及任何 C3 安全阈值回调。

## 6. Smoke 结果（feedforward_tau，τ=0.7s，6 trial，已通过）

数据目录：`/Volumes/Expansion/Aegis/c3_closed_loop_smoke_ff_v4`。

| trial | R0 critical_reached | R1 critical_reached | R1 路径 | 碰撞 |
|---|---|---|---|---|
| smoke01 | false | true | 13.05 m | 0 |
| smoke02 | false | true | 12.97 m | 0 |
| smoke03 | false | true | 12.99 m | 0 |
| smoke04 | false | true | 13.33 m | 0 |
| smoke05 | false | true | 12.93 m | 0 |
| smoke06 | false | true | 12.86 m | 0 |

- R0：6/6 `critical_reached=false`（orphan 未覆盖，符合 RA-only 基线）。
- R1：6/6 `critical_reached=true`（规则恢复覆盖 orphan goal），`recovery_step=31`、
  `mission_changes=1`、碰撞=0、`safety bypass=0`。
- drone 3 路径从振荡时的约 30 m 收敛到约 13 m。
- 四条 smoke 门全部满足：闭环可运行、R0/R1 对比清晰、触发可解释、碰撞/bypass=0。

## 7. 下一步

按 C3 协议进入 30-trial validation：先冻结独立 validation manifest（30 trial、R0/R1
Latin-square、独立 seed 与 smoke 分离），用 `feedforward_tau`（τ=0.7s）执行；Go 判据
沿用 C3 协议（R1 collision=0、boundary violation 受限、相对 R0 的配对恢复指标提升、
`safety bypass=0`、触发来自冻结原因码、不得删异常 trial）。同时把"执行模型 fidelity
（RA 假设 τ=0.2 vs 真实 PX4 τ≈0.5–0.7s）"写为论文的独立结论。
