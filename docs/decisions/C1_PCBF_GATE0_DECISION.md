# C1 PCBF external baseline：Gate 0 决策

## 冻结对象

Gate 0 针对 Huang et al.（ECC 2025）PCBF 的双机集中式、离散安全 MPC 适配进行最小复现。该对象的完整实现/后续门定义见 `paper/PCBF_EXTERNAL_BASELINE_IMPLEMENTATION_GATE.md`。

本 Gate 不使用 PX4、Gazebo、calibration seeds 或 sealed seeds；不改变任何已有 sealed manifest。

## 实现边界

- 预测模型：二维双积分离散模型，`dt=0.05 s`。
- 输入界：每机二维 acceleration box `[-2,2]^2 m/s^2`。
- 优化结构：预测域软机间状态约束、硬终端 hover-safe set、每周期执行首个控制量。
- 终端集合：固定视线方向上的分离投影不小于当前安全距离加 `0.10 m`，且每机终端速度为零；零加速度局部控制器保持该集合正不变。
- 求解失败：显式 `fail_closed`，输出沿当前速度反向的 `max-brake`；不会调用 HOCBF、PB-CBF 或 AegisAir recovery。
- 运行时动态安全边界仅在一个 MPC solve 的起点取值并在该 horizon 内保持；因此本 Gate 仅验证 published-PCBF 结构的适配，不外推原文时不变约束定理到完整 PX4 执行链。

## 验证结果

执行：`conda run -n eai-swarm python -m unittest tests.test_pcbf tests.test_ra -v`

| Gate 0 项 | 证据 | 结果 |
|---|---|---|
| 硬安全 hover 的零 slack | `test_safe_hover_has_zero_slack_and_terminal_feasible` | PASS |
| 软约束状态的 recovery slack | `test_soft_constraint_is_positive_before_recovery` | PASS |
| 终端不可达的 fail-closed | `test_terminal_unreachable_fails_closed_with_braking` | PASS |
| 首控制量后滚动重规划仍终端可行 | `test_replanning_after_first_control_remains_terminal_feasible` | PASS |
| RA 显式分支与诊断 | `test_pcbf_is_an_explicit_runtime_assurance_method` | PASS |
| 全仓回归 | 239 tests | PASS |

同一开发环境的 100 次 warm solve latency：p50 `0.400 ms`，p95 `0.462 ms`，p99 `0.491 ms`，max `0.538 ms`。这不是 PX4/Gazebo 的实时性证据；PX4 Gate 1 仍须重新测量并以 p99 `<50 ms` 判定。

## 决策

**Gate 0：GO。**

允许进入下一步：建立新的五个 PCBF calibration seeds、将 `PCBF_HUANG_ECC2025` 加入专用 runner/manifest，并运行严格的 Gate 1。禁止在 Gate 1 前修改已完成的 C1 sealed 或 ablation 结果。
