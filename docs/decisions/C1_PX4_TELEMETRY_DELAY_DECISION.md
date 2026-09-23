# C1 PX4/Gazebo telemetry-delay 核心迁移决策（2026-08-22）

- 协议：`aegisair-c1-px4-telemetry-delay-v1`。
- 决策：**No-Go；在第一个冻结 physical trial 后停止，不运行 seed 5102–5120。**

## 有效运行

- 数据目录：`/Volumes/Expansion/Aegis/c1_px4_telemetry_delay_validation_v1`。
- manifest SHA-256：`6cded809ea75eb5b1c51e51ad0d5b48cd0c0b527aaea5804436ce55c6089ea9a`。
- `c1px4_01`（Gazebo seed 5101）使用新 PX4/Gazebo SITL，20 Hz、600 steps、300 ms
  peer estimator delay、本机新鲜/peer 延迟局部 RA；`full_envelope` 与 `no_aoi_margin`
  依冻结 Latin-square 次序完成。

## 结果与停止理由

| 条件 | collision | `min_rho` | min distance | CBF events |
| --- | ---: | ---: | ---: | ---: |
| `full_envelope` | 0 | **-0.296013** | 1.0305 m | 1128 |
| `no_aoi_margin` | 0 | -0.713061 | 0.3966 m | 189 |

冻结 gate 要求 `full_envelope` 在 20/20 episode 中 collision=0 且 `min_rho>0`。首个
full episode 已出现负裕度，故主张无法成立并立即停止。虽然无物理碰撞且 `full_envelope`
优于 no-AoI 对照，但这些观察不能替代预注册 gate，也不能作为扩大 seed、修改 margin、
改变 τ 或调整几何后重跑的理由。

## 论文口径

1. C1 的正向证据仍仅限轻量仿真的 800 episode 一致观测消融。
2. 本 PX4/Gazebo 核心迁移**不支持**把 C1 写成 PX4 正向安全结果。
3. 该负结果可在讨论中简短说明：将 300 ms peer-delay 的 C1 核心带入当前两机 PX4
   对头闭环后，动态安全边界仍发生瞬时违反；这暴露了轻量模型到飞控闭环的迁移缺口。
4. 不得用 C3 的 `feedforward_tau` 成功或 C2/C3 参数去“救”本 C1 协议；若研究继续，必须
   提出独立假设并重新冻结 calibration、场景和停止规则。
