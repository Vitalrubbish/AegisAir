# C1 HOCBF-v4 可行余量感知 PB 恢复裁决

> 日期：2026-08-22  
> 当前裁决：**3-seed PX4/Gazebo smoke GO，可进入新的独立 paired validation；尚不能形成显著性或 SOTA 优越性结论。**

## 1. 问题与机制

HOCBF-v3 在 PX4 闭环中保持正公共裕度，但高相对速度交会时会在 `rho>0` 的状态下先发生
QP feasibility loss，随后依靠最大制动 fallback 保持安全。诊断 seeds 8401–8405 已用于定位
该问题，不得重新作为 sealed validation。

v4 保留 HOCBF 作为主过滤器，并增加两个显式、可审计的判断：

1. 按 `tau=0.7 s` 的执行模型进行三周期 HOCBF 可行性探测；第一周期按命令管线尚未生效的
   fail-closed 假设处理，后续周期恢复一阶执行模型。
2. 计算加速度 box 的最小归一化可行余量
   `R=min((a_max*||c||_1-b)/(a_max*||c||_1))`。当 `R<1.0` 时，约束已经要求正的分离
   加速度，提前切换至同预算 PB-CBF；连续 5 个 clean 周期后返回 HOCBF。

选中的 PB 恢复 QP、HOCBF 主 QP、预测 QP分别记账。PB 不可行时才使用最大制动，不能把
PB 恢复或最大制动隐藏成普通 HOCBF intervention。

## 2. Calibration 边界

- 轻量 calibration：seeds 8501–8505、3 场景。v3 本来就全程可行，因此 v4 不触发且与
  v3 数值一致；这验证了无冲突状态下不会无故切换，但不能证明 PX4 收益。
- PX4 calibration：seed 8701。最初的一步预测仍在主 QP 不可行后才切换，轨迹审计确认
  原因是预测器假设新加速度当拍生效，而实测存在命令管线延迟。该负结果保留。
- 加入可行余量判据后，同一诊断 seed 的 fresh-SITL 复核在 step 30 切换，主 QP 到 step 32
  才首次不可行；`min_rho=+0.207439`、任务完成、collision=0、选中链路 infeasible=0。

以上 calibration 只用于冻结 `prediction_steps=3`、第一周期 execution fraction=0、
`reserve_threshold=1.0`、PB `alpha=0.5`、制动预算 `2.0 m/s²`、buffer `0.30 m` 和
5-cycle hysteresis。

## 3. 独立 3-seed PX4 smoke

manifest：`configs/c1_hocbf_v4_px4_smoke_v1.json`。数据与审计：

- `/Volumes/Expansion/Aegis/c1_hocbf_v4_px4_smoke_v1`
- `/Volumes/Expansion/Aegis/c1_hocbf_v4_px4_smoke_v1_audit.json`

每个 condition 使用 fresh SITL；seeds 8801–8803，方法顺序轮换。

| 方法 | 完成 | collision | 最低 rho | 平均 CBF events | 选中 QP infeasible | 平均 effort | 平均路径 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HOCBF-v3 + hard brake | 3/3 | 0 | +0.048666 | 92.67 | 65 | 0.224197 | 18.411 m |
| HOCBF-v4 + PB recovery | 3/3 | 0 | +0.184536 | 89.33 | 0 | 0.130926 | 18.540 m |
| PB-CBF only | 3/3 | 0 | +0.473125 | 162.00 | 0 | 0.173739 | 18.755 m |

三次 v4 的首次恢复均由 `feasibility_reserve_low` 触发，触发时主 HOCBF QP 仍可行；相对
首次主 QP 不可行均提前 2 个 20 Hz 周期。PB recovery 自身 infeasible 为 0。

## 4. 当前可写边界

smoke 支持以下设计假设进入独立验证：v4 相比 v3 消除了选中控制链路的 feasibility-loss，
提高公共裕度并降低控制 effort；相比 PB-only，v4 使用更少 intervention、更低 effort 和更短
路径，但保留较小公共裕度。因此潜在主张是“更好的安全—效率折中”，不是全指标支配。

目前不得写：

- v4 显著优于 PB-CBF 或达到 SOTA；只有 3 个 smoke seeds。
- HOCBF 主 QP 全程可行；v4 中仍记录 75 个主 HOCBF infeasible steps，只是未被选为输出。
- PB 恢复是本文原创 barrier；本文创新仅可能位于可行余量判据、执行延迟探测、切换/滞回与
  PX4 闭环证据。
- 用 calibration seed 8701 或 smoke seeds 8801–8803 进入最终统计。

下一步若继续，应冻结新的独立 paired seeds，仅比较 PB-only、HOCBF-v3、完整 v4 与去掉
reserve trigger 的 reactive ablation；不得再修改上述参数。
