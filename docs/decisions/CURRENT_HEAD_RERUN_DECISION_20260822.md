# C1/C2/C3 当前 HEAD 重跑裁决（2026-08-22）

## 1. 重跑边界

本轮只验证执行模型与监督器改动后的当前代码，不覆盖或删除历史结果。数据均放在
`/Volumes/Expansion/Aegis/`，仓库只保存冻结 manifest、运行脚本、审计程序和裁决。

| 证据线 | 冻结对象 | 规模 | 裁决 |
| --- | --- | ---: | --- |
| C1-v2 轻量桥接 | seeds 6201–6220，300 ms peer delay，execution/command/admission tau=0.7 s，barrier tau=0.2 s | 20 | **No-Go** |
| C2-v2 PX4/Gazebo | seeds 8101–8112，三条件 Latin-square | 12 trials / 36 episodes | **No-Go** |
| C3-v2 PX4/Gazebo | seeds 9101–9130，R0/R1 交替顺序，`feedforward_tau=0.7 s` | 30 trials / 60 episodes | **GO** |

审计汇总：`/Volumes/Expansion/Aegis/current_head_rerun_audit_20260822.json`。审计程序逐条检查
manifest、trial/condition 顺序和 trajectory SHA-256。

## 2. C1-v2 轻量桥接：No-Go

- `min_rho>0`：20/20；最低 0.370100，均值 0.470526。
- collision：0/20；QP infeasible：0；CBF intervention：0。
- completion：0/20；20 次均在 1200 steps 后停于 `PASS_PRIMARY`。

因此它证明同一组 supervisor 参数在轻量模型中保持了正安全裕度，但没有完成任务。不能用
PX4-v2 的 20/20 completion 替代本项，也不能把本项写成轻量/PX4 完全一致。当前可证结论是：
轻量环境对 PX4 admission 状态机的执行语义仍不具备充分 fidelity；本冻结桥接验证失败。

## 3. C2-v2：No-Go

| 条件 | 正裕度 | mean `min_rho` | worst `min_rho` | `min_distance<0.25 m` |
| --- | ---: | ---: | ---: | ---: |
| E2_FIXED | 0/12 | -0.507532 | -0.842554 | 0 |
| E2_QP_GATE | 0/12 | -0.520203 | -0.822954 | 0 |
| C2_PRIME | 2/12 | -0.444815 | -0.885788 | 2 |

C2_PRIME 相对 E2_QP_GATE 的 paired mean delta 为 +0.075388，但仅 5/12 配对为正，且绝对
安全裕度 gate 失败。均值改善由少数 trial 拉动，不能据此宣称稳定提升。C2-v2 的当前 HEAD
重跑没有把历史负结果翻成正结果，论文仍应将 C2 写为执行模型审计与反例，而非安全增益贡献。

`min_distance<0.25 m` 在此仅报告为几何接触阈值，不替代仿真器原生碰撞传感器。

## 4. C3-v2：GO

| 条件 | critical reached | 正裕度 | collision | 最低 `min_rho` | 平均路径 | CBF events |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| R0 | 0/30 | 30/30 | 0/30 | 0.867307 | 12.2585 m | 0 |
| R1 | 30/30 | 30/30 | 0/30 | 0.148028 | 13.0382 m | 142 |

- 30/30 配对均为 `(R0=false, R1=true)`，反向为 0。
- R1 的 `recovery_step=31` 与 `mission_changes=1` 均为 30/30。
- R1 有 13/30 trial 出现非零 CBF intervention，共 142 次；因此本验证既包含 admission-safe
  样本，也包含主动安全过滤样本。
- R1 较低的裕度来自健康机继续覆盖失效机的 orphan goal；在冻结场景中仍保持正裕度和零碰撞。

本 GO 只覆盖冻结的 PX4/Gazebo `drone_failure` 场景、当前接口与 tau=0.7 s，不外推到真机、
任意故障或连续时间理论保证。summary 未导出独立 `safety_bypass` 计数，不能声称本 30-trial
validation 直接测得 bypass=0。

## 5. 无效运行处理

C3 的 head18/head19 启动阶段曾因上一 PX4 instance 仍在退出而被 launcher 拒绝；两次均未创建
trial summary 或 trajectory，故按基础设施无效运行处理，并用原 seed、原 manifest 重试。运行脚本
随后改为等待 instance 2/3 的进程条件真正清空再启动，不改变控制器、场景、seed 或判据。

## 6. 论文裁决

1. C1 的 PX4-v2 admission GO 仍可报告，但新增轻量桥接 No-Go 必须并列披露，不能声称跨仿真
   fidelity 已闭合。
2. C2/C2-v2 均为负结果，用于支持“执行一致性必须实测，增加 gate 不自动带来安全增益”。
3. C3-v2 是当前 HEAD 的主要正向闭环证据，并首次在完整 30-trial 中直接记录到非零 CBF 介入。
