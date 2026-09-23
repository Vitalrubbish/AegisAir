#!/usr/bin/env python3
"""分析四机 R2/R3 paired 结果并生成预注册统计与图形。"""

from __future__ import annotations

import argparse
import math
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import numpy as np


R2 = "R2_C3_ADMISSION"
R3 = "R3_C3_RESERVATION"
BOOTSTRAP_SEED = 20260825
BOOTSTRAP_DRAWS = 10000


def _paired_rows(payload: dict[str, Any]) -> list[tuple[dict, dict]]:
    by_seed: dict[int, dict[str, dict]] = {}
    for row in payload["trials"]:
        by_seed.setdefault(int(row["seed"]), {})[row["condition"]] = row
    return [
        (by_seed[seed][R2], by_seed[seed][R3])
        for seed in sorted(by_seed)
        if R2 in by_seed[seed] and R3 in by_seed[seed]
    ]


def _bootstrap_mean(delta: np.ndarray, rng: np.random.Generator) -> list[float]:
    if len(delta) == 0:
        return [float("nan"), float("nan")]
    draws = np.asarray(
        [np.mean(rng.choice(delta, size=len(delta), replace=True)) for _ in range(BOOTSTRAP_DRAWS)]
    )
    return [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))]


def _mcnemar_exact_p(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if discordant == 0:
        return 1.0
    smaller = min(left_only, right_only)
    lower_tail = sum(math.comb(discordant, value) for value in range(smaller + 1)) / (
        2**discordant
    )
    return min(1.0, 2.0 * lower_tail)


def _paired_sign_flip_p(delta: np.ndarray) -> float:
    delta = np.asarray(delta, dtype=np.float64)
    delta = delta[~np.isclose(delta, 0.0)]
    if len(delta) == 0:
        return 1.0
    observed = abs(float(np.mean(delta)))
    combinations = 1 << len(delta)
    extreme = 0
    batch_size = 65536
    bit_positions = np.arange(len(delta), dtype=np.uint64)
    for start in range(0, combinations, batch_size):
        codes = np.arange(start, min(start + batch_size, combinations), dtype=np.uint64)
        signs = 1.0 - 2.0 * ((codes[:, None] >> bit_positions) & 1).astype(np.float64)
        means = np.mean(signs * delta[None, :], axis=1)
        extreme += int(np.sum(np.abs(means) >= observed - 1e-12))
    return extreme / combinations


def _holm(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values, key=p_values.get)
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for index, name in enumerate(ordered):
        running = max(running, (total - index) * p_values[name])
        adjusted[name] = min(1.0, running)
    return adjusted


def statistics(payload: dict[str, Any]) -> dict[str, Any]:
    pairs = _paired_rows(payload)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    r2_success = np.asarray([bool(left["joint_success"]) for left, _ in pairs])
    r3_success = np.asarray([bool(right["joint_success"]) for _, right in pairs])
    r2_only = int(np.sum(r2_success & ~r3_success))
    r3_only = int(np.sum(~r2_success & r3_success))
    discordant = r2_only + r3_only
    mcnemar_p = _mcnemar_exact_p(r2_only, r3_only)
    success_delta = r3_success.astype(float) - r2_success.astype(float)
    metrics = {
        "min_rho": np.asarray([right["min_rho"] - left["min_rho"] for left, right in pairs]),
        "path_length_m": np.asarray(
            [right["path_length_m"] - left["path_length_m"] for left, right in pairs]
        ),
        "mean_control_effort": np.asarray(
            [
                right["mean_control_effort"] - left["mean_control_effort"]
                for left, right in pairs
            ]
        ),
    }
    horizon_s = 60.0
    r2_time = np.asarray(
        [
            min(
                horizon_s,
                (left["completion_step"] / left["rate_hz"])
                if left["completion_step"] is not None
                else horizon_s,
            )
            for left, _ in pairs
        ]
    )
    r3_time = np.asarray(
        [
            min(
                horizon_s,
                (right["completion_step"] / right["rate_hz"])
                if right["completion_step"] is not None
                else horizon_s,
            )
            for _, right in pairs
        ]
    )
    metrics["rmst_60s"] = r3_time - r2_time
    raw_p = {name: _paired_sign_flip_p(delta) for name, delta in metrics.items()}
    return {
        "pairs": len(pairs),
        "inference_scope": (
            "qualification_descriptive_only"
            if payload.get("phase", "").startswith("five_seed_qualification")
            else "sealed_predeclared_inference"
        ),
        "joint_success": {
            "r2": int(np.sum(r2_success)),
            "r3": int(np.sum(r3_success)),
            "paired_difference_r3_minus_r2": float(np.mean(success_delta)) if len(pairs) else None,
            "paired_bootstrap_95_ci": _bootstrap_mean(success_delta, rng),
            "mcnemar_exact_p": mcnemar_p,
            "discordant_r2_only": r2_only,
            "discordant_r3_only": r3_only,
        },
        "paired_metrics_r3_minus_r2": {
            name: {
                "mean": float(np.mean(delta)) if len(delta) else None,
                "median": float(np.median(delta)) if len(delta) else None,
                "paired_bootstrap_95_ci": _bootstrap_mean(delta, rng),
                "paired_sign_flip_raw_p": raw_p[name],
            }
            for name, delta in metrics.items()
        },
        "holm_adjusted_p": _holm(raw_p),
        "rmst_definition": "mean min(completion_time, 60 s); incomplete trials retained at 60 s",
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
    }


def _read_records(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(row["trajectory_path"]).read_text(encoding="utf-8").splitlines()
    ]


def _example_rows(payload: dict[str, Any]) -> tuple[dict, dict]:
    r3 = sorted(
        (row for row in payload["trials"] if row["condition"] == R3),
        key=lambda row: (float(row["min_rho"]), int(row["seed"])),
    )
    if not r3:
        raise ValueError("没有有效 R3 trial 可绘图")
    worst = r3[0]
    median = r3[len(r3) // 2]
    return median, worst


def _plot_trajectories(
    payload: dict[str, Any], manifest: dict[str, Any], output: Path
) -> None:
    median, worst = _example_rows(payload)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    goals = {int(key): value for key, value in manifest["base_goals"].items()}
    colors = {2: "#0072B2", 3: "#D55E00", 4: "#009E73", 5: "#CC79A7"}
    for axis, row, label in zip(axes, (median, worst), ("Median seed", "Worst valid seed")):
        records = _read_records(row)
        for drone in manifest["drone_ids"]:
            positions = np.asarray([record["drones"][str(drone)]["pos"][:2] for record in records])
            axis.plot(positions[:, 0], positions[:, 1], color=colors[drone], label=f"UAV {drone}")
            axis.scatter(*positions[0], color=colors[drone], marker="o", s=28)
            axis.scatter(*goals[drone][:2], color=colors[drone], marker="*", s=90)
        center = manifest["shared_admission"]["conflict_zone_center"]
        radius = manifest["shared_admission"]["conflict_zone_radius_m"]
        axis.add_patch(Circle(center, radius, fill=False, ls="--", color="0.35"))
        decision_rows = [r.get("coordination_reservation") for r in records]
        holds = {}
        clears = {}
        for decision in decision_rows:
            if not decision:
                continue
            holds.update(decision.get("frozen_hold_goals") or {})
            if decision.get("clearance_drone_id") is not None:
                clears[str(decision["clearance_drone_id"])] = decision["clearance_goal"]
        if holds:
            points = np.asarray([value[:2] for value in holds.values()])
            axis.scatter(points[:, 0], points[:, 1], marker="s", facecolors="none", edgecolors="k", label="Hold")
        if clears:
            points = np.asarray([value[:2] for value in clears.values()])
            axis.scatter(points[:, 0], points[:, 1], marker="x", color="k", label="Clear")
        axis.set_title(f"{label}: seed {row['seed']}, min rho={row['min_rho']:.3f}")
        axis.set_xlabel("x [m]")
        axis.set_ylabel("y [m]")
        axis.axis("equal")
        axis.grid(alpha=0.25)
    axes[0].legend(ncol=2, fontsize=8)
    fig.savefig(output / "four_uav_trajectories.png", dpi=220)
    fig.savefig(output / "four_uav_trajectories.pdf")
    plt.close(fig)


def _plot_timeline(payload: dict[str, Any], output: Path) -> None:
    median, _ = _example_rows(payload)
    records = _read_records(median)
    modes = [
        (record.get("coordination_reservation") or {}).get("coordination_mode", "normal")
        for record in records
    ]
    order = ["normal", "admission_pending", "staging", "pass", "clear", "release", "final_return", "complete"]
    values = np.asarray([order.index(mode) if mode in order else -1 for mode in modes])
    fig, axis = plt.subplots(figsize=(12, 3.8), constrained_layout=True)
    axis.step(np.arange(len(values)) / median["rate_hz"], values, where="post", color="#0072B2")
    axis.set_yticks(range(len(order)), [name.upper() for name in order])
    axis.set_xlabel("Time [s]")
    axis.set_title(f"C3-Reservation state timeline: median seed {median['seed']}")
    axis.grid(axis="x", alpha=0.25)
    fig.savefig(output / "reservation_state_timeline.png", dpi=220)
    fig.savefig(output / "reservation_state_timeline.pdf")
    plt.close(fig)


def _plot_paired(payload: dict[str, Any], output: Path) -> None:
    pairs = _paired_rows(payload)
    fig, axis = plt.subplots(figsize=(6, 5), constrained_layout=True)
    for left, right in pairs:
        axis.plot([0, 1], [left["min_rho"], right["min_rho"]], marker="o", alpha=0.8)
    axis.axhline(0.0, color="black", ls="--", lw=1)
    axis.set_xticks([0, 1], ["R2 Admission", "R3 Reservation"])
    axis.set_ylabel("Minimum rho")
    axis.set_title("Paired four-UAV safety margin")
    axis.grid(axis="y", alpha=0.25)
    fig.savefig(output / "paired_min_rho.png", dpi=220)
    fig.savefig(output / "paired_min_rho.pdf")
    plt.close(fig)


def _plot_joint_success(payload: dict[str, Any], output: Path) -> None:
    pairs = _paired_rows(payload)
    values = [
        sum(bool(left["joint_success"]) for left, _ in pairs),
        sum(bool(right["joint_success"]) for _, right in pairs),
    ]
    fig, axis = plt.subplots(figsize=(6, 4.5), constrained_layout=True)
    axis.bar(["R2 Admission", "R3 Reservation"], values, color=["#999999", "#0072B2"])
    axis.set_ylim(0, max(1, len(pairs)))
    axis.set_ylabel(f"Joint successes / {len(pairs)}")
    axis.set_title("Completion + positive rho + feasible QP + no bypass")
    for index, value in enumerate(values):
        axis.text(index, value, str(value), ha="center", va="bottom")
    fig.savefig(output / "joint_success.png", dpi=220)
    fig.savefig(output / "joint_success.pdf")
    plt.close(fig)


def _plot_latency(payload: dict[str, Any], output: Path) -> None:
    fig, axis = plt.subplots(figsize=(7, 5), constrained_layout=True)
    for condition, color in ((R2, "#777777"), (R3, "#0072B2")):
        values = []
        for row in payload["trials"]:
            if row["condition"] != condition:
                continue
            values.extend(float(record["ra_solve_latency_ms"]) for record in _read_records(row))
        if values:
            ordered = np.sort(values)
            axis.plot(ordered, np.arange(1, len(ordered) + 1) / len(ordered), label=condition, color=color)
    axis.axvline(50.0, color="#D55E00", ls="--", label="50 ms deadline")
    axis.set_xlabel("RA solve latency [ms]")
    axis.set_ylabel("Empirical CDF")
    axis.set_title("Four-UAV runtime latency")
    axis.grid(alpha=0.25)
    axis.legend()
    fig.savefig(output / "latency_cdf.png", dpi=220)
    fig.savefig(output / "latency_cdf.pdf")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"拒绝覆盖图表目录：{args.output}")
    args.output.mkdir(parents=True)
    payload = json.loads(args.summary.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = statistics(payload)
    result["example_selection"] = {
        "rule": "R3 min_rho median and minimum among all infrastructure-valid trials",
        "median_seed": _example_rows(payload)[0]["seed"],
        "worst_valid_seed": _example_rows(payload)[1]["seed"],
    }
    (args.output / "statistics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _plot_trajectories(payload, manifest, args.output)
    _plot_timeline(payload, args.output)
    _plot_paired(payload, args.output)
    _plot_joint_success(payload, args.output)
    _plot_latency(payload, args.output)
    print(json.dumps({"statistics": str(args.output / 'statistics.json'), "pairs": result["pairs"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
