# C1-v4 reserve-triggered recovery 的充分条件与主张边界

> 日期：2026-08-23  
> 状态：论文方法附录候选；不修改已完成 C1/C2/C3 的控制器、参数或结论。

## 1. 目的

本说明给 v4 的 reserve-triggered PB recovery 一个可检验的数学解释，同时避免把经验
`reserve_threshold=1.0` 写成未经证明的全局安全定理。v4 的已有实验事实仍仅限冻结的
PX4/Gazebo 包络。

## 2. 定义

对一对飞行器，令相对状态为 `q=(r,v)`，HOCBF 约束写作

\[
F_H(q,a)=c(r)^\top a-b(r,v,d)\geq0,\qquad a\in\mathcal U=[-a_{\max},a_{\max}]^{2n}.
\]

令 `M(q)=a_max ||c(r)||_1`。实现中的归一化可行余量为

\[
R_H(q)=\frac{M(q)-b(q)}{M(q)}.
\]

因此 `M R_H` 是该 pair 在加速度盒上可获得的最大 HOCBF 左端余量；`R_H<1` 等价于
`b>0`，即维持该约束已需要正的分离加速度。它是**主 HOCBF 的早期可行性告警量**，不是
PB-QP 可行性的定义。

令 PB recovery 的 sampled-data barrier constraint 为 `F_B(q,a)>=0`。定义 PB 严格
可行余量

\[
\eta_B(\hat q)=\max_{a\in\mathcal U}\min_{(i,j)}F_{B,ij}(\hat q,a).
\]

这里 `hat q` 是 RA 所见的状态；`eta_B>0` 表示 PB QP 对所有 pair 存在严格可行解。

## 3. 假设

在一次接管窗口 `H` 内，假设：

1. 执行与状态估计误差有界：`||r-hat r||<=eps_r`、`||v-hat v||<=eps_v`、
   `||a_exec-a||<=eps_a`。后者可由命令保持、时延变化、跟踪误差的预先声明上界给出。
2. 相对距离远离零，且状态、动作均在一个紧集 `K` 内；故 `F_H` 和 `F_B` 在 `K` 上对
   `(r,v,a)` Lipschitz。
3. PB recovery 在接管期间保持被选中，且其离散 barrier 的正向不变性条件在真实执行
   动态上成立；PB 不可行时的 max-brake 只能视为 fail-closed fallback，不能写入该命题。

定义由实现/测量失配产生的界

\[
\Delta_H=L_{Hr}\epsilon_r+L_{Hv}\epsilon_v+L_{Ha}\epsilon_a,
\quad
\Delta_B=L_{Br}\epsilon_r+L_{Bv}\epsilon_v+L_{Ba}\epsilon_a.
\]

各 `L` 必须在论文的目标工作域中给出解析上界或经独立辨识后固定；不能从 sealed OOD
结果回填。

## 4. 引理与命题

**引理 1（主 HOCBF reserve 的鲁棒可行性）。** 若

\[
M(\hat q)R_H(\hat q)>\Delta_H,
\]

则在真实状态与执行误差界内，存在 `a in U` 使真实 HOCBF 约束成立。

*理由。* 在估计状态的盒上最优分离动作给出的 slack 为 `M R_H`；由 Lipschitz 界，真实
约束值最多减少 `Delta_H`，严格正差保留一个可行解。

**引理 2（PB 的鲁棒严格可行性）。** 若

\[
\eta_B(\hat q)>\Delta_B,
\]

则同一 PB 动作在真实接管状态仍满足全部 PB constraint。

**命题 1（reserve-triggered 接管的充分条件）。** 当实现发现
`R_H(hat q)<gamma_R` 并切换至 PB，若在该时刻及后续保持期都有

\[
\eta_B(\hat q)>\Delta_B
\]

且假设 3 的 PB 正向不变性成立，则在该保持期的采样时刻维持 PB 安全集。若还存在
`M(hat q)R_H(hat q)>Delta_H`，主 HOCBF 也尚有鲁棒可行解；若该不等式临近失效，切换的
作用正是避免等到主 QP 已不可行才接管。

*解释。* `gamma_R=1.0` 是部署中的早期告警阈值，决定**何时**请求 backup；真正使 backup
可行的充分条件是 PB 的严格余量覆盖 `Delta_B`。因此该命题不把阈值本身偷换成安全证明。

**推论 1（理想执行退化）。** 当 `eps_r=eps_v=eps_a=0` 时，`Delta_H=Delta_B=0`；上述条件
退化为普通 HOCBF/PB 的可行性与 sampled-data 正向不变性条件。若不触发 recovery，v4 即为
其冻结的主 HOCBF filter。

## 5. 对现有结果能与不能说什么

- 可说：20/20 v4 seed 的 `R_H<1` 触发发生在 primary HOCBF 首次不可行前 2--3 个周期，且
  PB recovery selected-QP 无不可行；这与“reserve 作为提前接管告警”一致。
- 不可说：当前实验没有辨识并冻结 `eps_*`、`L_*` 或在线求 `eta_B`，因此不能声称已验证
  `eta_B>Delta_B` 的连续时间、全局或真机安全保证。
- 论文落地：将本说明写为带条件的 Proposition，并在局限中明确经验 `tau=0.7 s` 不是确定性
  执行上界。若日后加入在线 PB strict-slack audit 和独立误差界辨识，才可将命题变为可逐步
  运行时验证的证书。
