#!/usr/bin/env python3
"""Reproduce the Phase-7 PX4/Gazebo first-order velocity fits.

The script keeps the historical protocol fixed: for each RUN and STOP segment,
fit only the first three seconds to

    v(t) = v_inf + (v_0 - v_inf) exp(-t / tau).

For each candidate tau on a deterministic grid, the two linear coefficients are
solved by least squares. Repetitions r1/r2 form the identification set and r3 is
held out. The nominal value is the identification-set median rounded to one
decimal place; the empirical interval is the identification min/max expanded by
20 percent and rounded outward to two decimals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path


FIT_WINDOW_S = 3.0
TAU_GRID_MIN_S = 0.01
TAU_GRID_MAX_S = 5.0
TAU_GRID_STEP_S = 0.001


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator <= 0.0:
        raise ValueError("degenerate exponential regressor")
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    intercept = y_mean - slope * x_mean
    return intercept, slope


def _fit_segment(rows: list[dict]) -> dict:
    start = float(rows[0]["t_s"])
    samples = [row for row in rows if float(row["t_s"]) - start <= FIT_WINDOW_S]
    times = [float(row["t_s"]) - start for row in samples]
    velocities = [float(row["vx"]) for row in samples]

    best: tuple[float, float, float, float] | None = None
    count = int(round((TAU_GRID_MAX_S - TAU_GRID_MIN_S) / TAU_GRID_STEP_S)) + 1
    for index in range(count):
        tau = TAU_GRID_MIN_S + index * TAU_GRID_STEP_S
        regressors = [math.exp(-time_s / tau) for time_s in times]
        v_inf, amplitude = _linear_fit(regressors, velocities)
        residuals = [
            velocity - (v_inf + amplitude * regressor)
            for velocity, regressor in zip(velocities, regressors)
        ]
        rmse = math.sqrt(statistics.fmean(value * value for value in residuals))
        candidate = (rmse, tau, v_inf + amplitude, v_inf)
        if best is None or candidate < best:
            best = candidate

    assert best is not None
    rmse, tau, v_initial, v_final = best
    return {
        "tau_s": round(tau, 3),
        "rmse_mps": round(rmse, 6),
        "v_initial_fit_mps": round(v_initial, 6),
        "v_final_fit_mps": round(v_final, 6),
        "sample_count": len(samples),
    }


def analyze(input_dir: Path) -> dict:
    trials = []
    identification_values = []
    held_out_values = []

    for path in sorted(input_dir.glob("step_v*_r*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            raise ValueError(f"empty input: {path}")
        repetition = path.stem.rsplit("_", 1)[-1]
        partition = "held_out" if repetition == "r3" else "identification"
        fits = {}
        for tag in ("run", "stop"):
            segment = [row for row in rows if row.get("tag") == tag]
            if not segment:
                raise ValueError(f"missing {tag} segment: {path}")
            fits[tag] = _fit_segment(segment)
            target = held_out_values if partition == "held_out" else identification_values
            target.append(float(fits[tag]["tau_s"]))
        trials.append(
            {
                "file": path.name,
                "sha256": _sha256(path),
                "partition": partition,
                "fits": fits,
            }
        )

    if len(trials) != 9 or len(identification_values) != 12 or len(held_out_values) != 6:
        raise ValueError(
            "expected 9 trials, 12 identification fits, and 6 held-out fits; "
            f"got {len(trials)}, {len(identification_values)}, {len(held_out_values)}"
        )

    median_tau = statistics.median(identification_values)
    selected_tau = round(median_tau, 1)
    lower = math.floor(min(identification_values) * 0.8 * 100.0) / 100.0
    upper = math.ceil(max(identification_values) * 1.2 * 100.0) / 100.0
    return {
        "protocol": {
            "model": "v(t)=v_inf+(v_0-v_inf)*exp(-t/tau)",
            "fit_window_s": FIT_WINDOW_S,
            "tau_grid_s": [TAU_GRID_MIN_S, TAU_GRID_MAX_S, TAU_GRID_STEP_S],
            "identification_repetitions": ["r1", "r2"],
            "held_out_repetitions": ["r3"],
            "nominal_selection_rule": "identification median rounded to 0.1 s",
            "empirical_interval_rule": "identification min/max expanded by 20%, rounded outward to 0.01 s",
        },
        "summary": {
            "identification_fit_count": len(identification_values),
            "identification_tau_median_s": round(median_tau, 6),
            "selected_nominal_tau_s": selected_tau,
            "empirical_interval_s": [lower, upper],
            "held_out_fit_count": len(held_out_values),
            "held_out_inside_empirical_interval": all(lower <= value <= upper for value in held_out_values),
            "all_fit_tau_median_s": round(
                statistics.median(identification_values + held_out_values), 6
            ),
        },
        "trials": trials,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = analyze(args.input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
