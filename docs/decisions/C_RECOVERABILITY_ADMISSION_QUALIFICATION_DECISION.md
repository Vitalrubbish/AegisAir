# Failure-aware recoverability admission qualification 决策

> 日期：2026-08-26  
> 决策：**GO，可冻结独立 sealed manifest。**

- manifest：`configs/c_recoverability_admission_qualification_v1.json`；SHA-256
  `33f0b999449dd9ef1e19408f524ec5a08ed77d172b9f4b83360dec0b47720e46`；
- 输出：`/Volumes/Expansion/Aegis/c_recoverability_admission_qualification_v1`；
- audit SHA-256：`1c8d45be8a0b109d2c7907503c967e7db03645ef9a25769d838edcef66d17725`；
- 五个未参与 development 的新几何/seed，三条件共 15/15 完整；anti-vacuity=true。

三条 expected-admit 均恰好准入一次并完成故障后 critical goal；两条 expected-reject 均正确拒绝、
零 commit、零故障后 coverage。五条 admission 的 `min_rho` 为
`[0.596870, 0.231308, 0.414043, 1.594815, 1.986413]`，selected-QP infeasible 全为 0，
unsafe commit、collision、RA bypass、deadline miss 全为 0，最差 P99 `2.284 ms`。

五条 RA-only hold 均零 coverage、正 margin、零不可行。Immediate commit 五条均覆盖目标，但
`min_rho` 全为负，其中三个条件出现不可行步；该比较原样保留。

首个 qualification episode 完整运行后，runner 在写 summary 时遇到常量名 post-processing 错误。
该 800-step trajectory 未重跑；使用固定重建脚本从原始逐步日志恢复 summary，并标记
`postprocessing_recovered=true`。两个在人工中断时尚未产生 trajectory 的空启动目录被隔离为
invalid infrastructure attempts，随后在同一 manifest/seed 下 fresh 重启，不进入算法分母。

下一步 sealed 使用 20 个全新 seed 和未参与 calibration/qualification 的参数化几何；准入与 RA 参数、
候选集合、终点、样本数、比较条件和停止规则在运行前冻结。sealed 期间不得修改。
