# C1-v4 empirical certificate-coverage audit protocol

## Frozen objects

- Calibration only: five new PX4/Gazebo seeds 9401--9405, `AEGIS_HOCBF_V4` only,
  nominal C1 geometry and all v4 control parameters unchanged.
- Evaluation only: the completed sealed C1-v4 validation and post-freeze OOD
  trajectories.  They are never used to select an envelope.
- The audit is one-step and empirical, not a continuous-time theorem certificate.

## Calibration envelope

For each time step, log the issued velocity request, measured next velocity and
position.  Under the frozen `tau=0.7 s` exact-ZOH model, form the predicted
next state.  For the PB constraint evaluated with the issued safe action, set

\[
\delta_B(t)=|F_B(q_{t+1}^{meas},a_t)-F_B(q_{t+1}^{pred},a_t)|.
\]

Freeze `Delta_B` as `1.10 * max(delta_B)` across calibration trajectories.
No quantile, seed, method, or control parameter may be changed after this
calculation.

## Coverage audit

At every v4 recovery-active step, compute PB strict slack

\[
\eta_B(t)=\max_{a\in[-a_{max},a_{max}]^{2n}}\min_{pairs} F_B(q_t,a).
\]

Report `C_B(t)=eta_B(t)-Delta_B`, its minimum, and the fraction of recovery
steps where it is strictly positive.  A non-positive value is reported as
uncovered evidence, never hidden or used for retuning.

## Claim boundary

Positive coverage supports: “the frozen empirical execution envelope covered
the PB strict-slack condition at the audited recovery steps.”  It does not
establish a deterministic bound, continuous-time safety, or an online deployed
certificate.
