# C1 PCBF Huang et al. ECC 2025 adaptation：Gate 1 No-Go 决策

## 决策

**No-Go。停止 PCBF external-baseline 分支。**

不得改变 horizon、终端集、slack 权重、共同安全边界、任务时限或 fail-closed 规则以重跑；不得运行余下四个 calibration seeds，更不得生成 PCBF sealed seeds。

## 有效试验与完整性

- frozen manifest：`configs/c1_pcbf_huang_ecc2025_calibration_v1.json`
- 外部输出根：`/Volumes/Expansion/Aegis/c1_pcbf_huang_ecc2025_calibration_v1`
- 有效 trial：`pcbfcal01`，seed `12601`，方法 `PCBF_HUANG_ECC2025`
- 轨迹：`pcbfcal01_PCBF_HUANG_ECC2025/pcbfcal01_00_PCBF_HUANG_ECC2025.jsonl`
- 轨迹 SHA-256：`e875ac0806febcaf807961c285e7fd15cb72aeb677ed42a465af3d7b972709ae`

首次基础设施启动曾因 `run_mqtt_loop` 缺失 PCBF 参数透传而在 runner 入口失败；当时没有产生 trajectory 或 summary，空目录已隔离到 `invalid_infrastructure/pcbfcal01_runner_argument_rejection`，不计作试验。接线修复、单元测试通过后，以同一冻结 seed 重新启动，以下结果为唯一有效 trial。

## 结果

| 指标 | 值 | Gate 判定 |
|---|---:|---|
| collision | false | 通过 |
| min rho | 3.149565 | 通过 |
| solver/RA infeasible steps | 0 | 通过 |
| p99 RA solve latency | 2.343 ms | 通过（< 50 ms） |
| deadline misses | 0 | 通过 |
| safety bypass | 0 | 通过 |
| mission complete | false | **失败** |
| CBF interventions | 800 | 任务始终被安全器接管 |
| path length | 4.089431 m | 仅作描述，不用于挽救 |

## 解释与论文边界

PCBF 适配在当前冻结的 terminal hover-safe set 下保持了正安全裕度和实时性，但无法在共同的 400-step mission horizon 内完成交叉任务。按预注册 Gate 1，completion 是与 collision、`min_rho`、solver/fail-closed、latency 并列的进入 sealed 条件；单项失败即终止。

这不是 AegisAir 主结论的否定，也不能改写为“PCBF 不安全”。可写的、严格限定的事实只是：在该共同 PX4/Gazebo 接口、冻结 terminal-set PCBF adaptation 和五-seed Gate 1 的第一个有效 trial 中，PCBF 因任务完成失败而未获准进入 sealed external-baseline comparison。

## 后续

回到 bounded TAES 路线：保留单几何 C1 安全/实时性结果、诚实保留 prediction ablation 阴性增量和 cross-geometry recovery No-Go；不将 PCBF 写为已成功完成的 external baseline，也不以 SACBF 或其他方法替换来规避本次停止规则。
