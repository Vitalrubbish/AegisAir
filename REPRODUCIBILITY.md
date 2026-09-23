# AegisAir 可复现性说明

## 本公开版本包含什么

本仓库提供运行时安全保障、任务恢复、接口规范、控制器配置和离线测试。它支持复核算法逻辑、接口契约与冻结配置的一致性。

本仓库不提供论文、投稿材料、训练 checkpoint、PX4/Gazebo 原始日志、轨迹、ULog、统计汇总或其他实验产物。因此，克隆者不能从本仓库重建历史实验数值；可以用相同配置重新运行新的独立实验。

## 最小可复现检查

```bash
conda env create -f environment.yml
conda activate eai-swarm
pip install -r requirements.txt
python -m unittest discover -s tests
python scripts/validate_pcbf_baseline.py
python scripts/validate_dynamic_admission.py
```

该检查不需要 GPU、PX4、Gazebo 或原始数据。测试覆盖加速度约束的 HOCBF/QP、不可行时制动回退、确定性任务恢复、消息 schema 以及关键 manifest 的结构。PCBF 验证使用 CasADi/IPOPT 运行确定性的两阶段非线性规划检查；`validate_dynamic_admission.py` 只验证核心 `time_aligned_dynamic_rollout_v2` 的速度相关决策与计算时延，不验证 MQTT 传输、ROS 2 executor 或 PX4/Gazebo 闭环。

## 闭环仿真复现

完整 PX4/Gazebo 复现另需安装 PX4 SITL、Gazebo、ROS 2、MQTT broker 和 AegisAir adapter bridge。服务启动后，以冻结 manifest 运行对应 runner，并使用一个不存在的新输出目录：

```bash
python marllib/run_c3_gazebo.py \
  --manifest configs/c3_closed_loop_smoke_v1.json \
  --out-dir /path/to/new-output
```

原始实验的 checkpoint、日志和轨迹未公开；运行结果应被视为新的复现实验，不应冒充为历史封存结果。

任务接纳的 v1/v2/v3 manifest 与旧 sealed 结果均为历史协议记录。当前 PX4/Gazebo runner 只接受 `dynamic_admission_v4_nonblocking_bridge` 的 calibration/qualification manifest：先完成 calibration-v4 并取得 `GO`，再运行 qualification-v4；两者通过前不得生成 sealed-v4 manifest。v4 仅冻结 MQTT 发布为非阻塞、返回码受检的入队路径及新的协议标识，保持 v3 的几何、seed、条件顺序和算法参数不变。该闭环验收不能由上述离线 v2 核心模型检查替代；具体启动命令见 `docs/PX4_GAZEBO_REPRODUCTION.md`。

## 结果与失败的记录

有效碰撞、`min_rho <= 0`、runtime-assurance bypass、任务未完成和权限撤销失败均应作为有效结果保留。启动或 arm 前失败应单独标记，不应混入算法试验统计。
