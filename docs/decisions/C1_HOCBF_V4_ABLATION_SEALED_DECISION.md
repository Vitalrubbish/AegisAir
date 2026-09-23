# C1 HOCBF-v4 reserve/prediction sealed 消融决策

> 日期：2026-08-25  
> 决策：**安全门 GO；prediction 增量为阴性，reserve 与 PB takeover 增量保留为有界证据。**

## 冻结对象与完整性

- manifest：`configs/c1_hocbf_v4_ablation_sealed_v1.json`
- manifest SHA-256：`8b0cfe7b1737c71255bdcc8717068c8dfea1613418d6fc8cbcd66160159f983b`
- 原始输出：`/Volumes/Expansion/Aegis/c1_hocbf_v4_ablation_sealed_v1`
- 有效样本：20 个新 paired seeds（9601--9620）× 4 条件 = 80/80。
- audit SHA-256：`2144ce9247f4e062ba928ab9f5b54a4c5363f1b8cbe627281cf18f47f9bff5de`。
- `COMPLETE` 已在 audit `go=true` 后写入；早先的 `PREMATURE_COMPLETE_BEFORE_AUDIT` 仅保留为编排审计记录，不代表实验完成。
- 三次无轨迹或无 summary 的启动分别标记为 invalid infrastructure，不进入算法分母：首次 PX4 runtime signature failure，以及 `abl08/V3`、`abl13/V4` 的 telemetry readiness timeout。

## 全条件安全门

| 条件 | 完成 | collision | 全局最低 rho | 平均最低 rho | selected QP infeasible | 平均 effort |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HOCBF-Fallback | 20/20 | 0 | +0.031534 | +0.085034 | 449 | 0.225046 |
| Reactive PB Takeover | 20/20 | 0 | +0.036212 | +0.117975 | 0 | 0.148553 |
| Reserve-Only Takeover | 20/20 | 0 | +0.116848 | +0.175535 | 0 | 0.132088 |
| Full Hybrid RA | 20/20 | 0 | +0.115686 | +0.172416 | 0 | 0.132432 |

所有有效 episode 的 `collision=0`、`mission_complete=true`、`min_rho>0`；因此预注册安全门为 GO。该结论限于冻结 PX4/Gazebo 包络，不是连续时间、真机或一般安全保证。

## 预注册 paired contrasts

差值均为“左条件减右条件”，95% CI 为 seed-level paired bootstrap。

| 对比 | 主要结果 | 决策 |
| --- | --- | --- |
| Full Hybrid RA − Reserve-Only | effort `+0.000344`，CI `[-0.001074,+0.001784]`；min rho `-0.003119`，CI `[-0.016531,+0.010627]`；QP infeasible 均为 0 | **prediction 增量阴性**：不能宣称 prediction 在本包络中带来独立安全或效率改善 |
| Reserve-Only − Reactive PB | effort `-0.016465`，CI `[-0.018347,-0.014523]`；min rho `+0.057560`，CI `[+0.031894,+0.083567]`；QP infeasible 均为 0 | **reserve 增量保留**：在本协议中更低 effort 且更高平均最小 rho |
| Reactive PB − HOCBF-Fallback | QP infeasible `-22.45`/trial，CI `[-23.20,-21.70]`；effort `-0.076493`，CI `[-0.079933,-0.073053]`；min rho `+0.032941`，CI `[+0.008088,+0.056990]` | **PB takeover 增量保留**：减少 primary-feasibility loss 并改善该冻结指标 |

## 论文与后续边界

1. 原 `Full vs Reserve-Only` 不能再写成 prediction 的独立贡献；该阴性结果必须进入表格或补充材料。
2. 可以把 reserve 的贡献收窄为：在这组新、配对、冻结 PX4/Gazebo trials 中，相对 reactive PB takeover，reserve-only condition 具有更低 control effort 与更高平均 minimum rho。
3. PB takeover 的贡献可写为相对 HOCBF-Fallback 减少 selected-QP infeasible steps 与 effort；不推导为全面优于所有基线。
4. 本工作包不替代 published external baseline，也不解决跨几何 recoverability-admission 分支；后两者仍按独立协议处理。
5. 不依据结果调 reserve 阈值、prediction horizon、几何或 seed。下一步按既定顺序推进 external baseline 的原文复现门；其后才决定 admission calibration。
