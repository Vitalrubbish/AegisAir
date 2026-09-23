# C2′：执行模型失效感知 Runtime Assurance 协议

- 状态：**已完成 PX4/Gazebo calibration 与 smoke；监督链可运行，但尚无正向实验结论。**
- 协议 ID：`aegisair-c2-prime-v1`
- 核心原则：执行模型与 AI 组件一样不可信；阈值仅由 calibration 数据冻结，validation/
  final 数据不得用于调参。

## 1. 原 C2 的处置

原主张“固定 exact-ZOH 执行模型 E2 在 PX4 闭环中优于历史近似 E1”降级为负结果。
2026-08-21 的 10 次 Gazebo 重复中，E2 的 `min_rho` 10/10 为负，均值 `-0.143`；
E1 为 9/10 负，均值 `-0.065`。不得再用轻量仿真中 E2 对 E1 的正向结果覆盖该闭环结果。

该轮只能视为开发证据，不是最终统计：脚本没有使用 seed 生成扰动，且每次固定按
E0→E1→E2 顺序运行，存在次序混杂。

## 2. 新 claim

> 在冻结的 PX4/Gazebo 测试包络内，执行一致性监测器能够检测一步执行响应、QP 可行性、
> 求解 deadline 或遥测时效对 RA 假设的破坏，并在失效时切换到加速度受限的确定性撤退
> 控制；相对固定 E2，它减少 boundary violation，同时不允许任何 safety bypass。

不可写：连续时间全局保证、任意 PX4 参数保证、真机安全、首次 adaptive/robust CBF。

## 3. 系统改动

### 3.1 一步执行残差

对上一周期实发速度命令 `u_k`，按冻结的短时模型计算：

```text
alpha(dt,tau) = 1 - exp(-dt/tau)
beta(dt,tau)  = dt - tau*alpha
v_hat(k+1)    = v_k + alpha*(u_k-v_k)
p_hat(k+1)    = p_k + v_k*dt + beta*(u_k-v_k)
```

记录 `||v_obs-v_hat||` 与 `||p_obs-p_hat||`。这里的 `tau_s` 只是冻结模型参数；论文不得
把它描述成任意工况下的 PX4 全局时间常数。

### 3.2 触发与迟滞

以下任一条件连续达到冻结的 `trip_samples` 即接管：

- 速度或位置残差超过 calibration 阈值；
- QP infeasible；
- RA 求解时间超过 20 Hz deadline；
- telemetry age 超过时效上限。

接管后必须连续 `release_samples` 个健康周期才释放，避免切换抖动。每一步记录原因码、
残差、QP 状态、求解时间和遥测年龄。

### 3.3 确定性备份

备份速度沿远离其他无人机质心的方向撤退；每周期速度变化满足
`||Delta v|| <= a_max*dt`，速度不超过 `v_max`。它替换了旧 QP fallback 的 `a=-v`
弱制动语义，但仍只在验证过的 recoverability envelope 内作经验安全主张。

## 4. Calibration（最先运行）

清单：`configs/c2_prime_calibration_v1.json`。

- 12 个单机、无冲突的 PX4 速度执行 trial；
- 只观察、不切换；
- 保存每步残差、求解时间、telemetry age 和原始轨迹；
- 速度/位置残差阈值冻结为 calibration trial 最大值的最大者再乘 `1.10`；
- 求解 deadline 固定为 `0.05 s`，telemetry age 上限固定为 `0.15 s`，不得由慢运行
  calibration 放宽；
- calibration artifact 写出后哈希，不覆盖。

命令：

```bash
conda run -n eai-swarm python marllib/run_c2_prime_gazebo.py \
  --manifest configs/c2_prime_calibration_v1.json \
  --out-dir /Volumes/Expansion/Aegis/c2_prime_calibration_v1

conda run -n eai-swarm python marllib/analyze_c2_prime_calibration.py \
  --calibration-dir /Volumes/Expansion/Aegis/c2_prime_calibration_v1 \
  --out /Volumes/Expansion/Aegis/c2_prime_calibration_v1/frozen_thresholds.json
```

Calibration 若没有有效残差、reset 不稳定或 telemetry/轨迹不完整，则停止，不进入 smoke。

## 5. 三条件 smoke

清单：`configs/c2_prime_smoke_v1.json`，6 个物理 trial，三条件采用完整 Latin-square
次序平衡：

- `E2_FIXED`：固定 E2，无 C2′ supervisor；
- `E2_QP_GATE`：只启用 QP/deadline/staleness gate；
- `C2_PRIME`：完整 residual + feasibility supervisor。

```bash
conda run -n eai-swarm python marllib/run_c2_prime_gazebo.py \
  --manifest configs/c2_prime_smoke_v1.json \
  --calibration /Volumes/Expansion/Aegis/c2_prime_calibration_v1/frozen_thresholds.json \
  --out-dir /Volumes/Expansion/Aegis/c2_prime_smoke_v1
```

Smoke 只验证：执行链可运行、三条件确实不同、触发原因可解释、备份命令满足加速度/速度
约束、无 safety bypass。Smoke 不产生论文效力结论。

## 6. Validation Go/No-Go（smoke 通过后另行冻结 manifest）

30 个 trial，三条件继续采用 Latin-square 次序平衡；trial 配置与 calibration 分离。

C2′ Go 必须同时满足：

1. `C2_PRIME` collision = `0/30`；
2. boundary violation 不超过 `1/30`；
3. 相对 `E2_FIXED` 的配对 `min_rho` 差 95% bootstrap CI 下界 `> 0`；
4. safety bypass = 0；
5. completion 相对 E2 降低不超过 10 个百分点；
6. 触发必须来自冻结原因码，且不得删除异常 trial。

任何一项不满足即 C2′ No-Go；不放松阈值、不追加模型、不用 validation/final 数据重做
calibration。只有 validation Go 才冻结独立 final manifest。

## 7. 当前边界

当前已完成代码、接口、单元测试、PX4 calibration 与 smoke。详见
`docs/decisions/C2_PRIME_SMOKE_DECISION.md`。C2′ 目前仍是**可检验的新假设，不是正向
创新结论**。
