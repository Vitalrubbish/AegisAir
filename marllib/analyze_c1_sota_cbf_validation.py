#!/usr/bin/env python3
"""审计 C1 强基线 validation，并按 trial 聚类做配对 bootstrap。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _paired_cluster_ci(
    rows: list[dict], treatment: str, reference: str, metric: str, *, seed: int
) -> dict[str, float]:
    trial_ids = sorted({row["trial_id"] for row in rows})
    differences = []
    for trial_id in trial_ids:
        pair = {}
        for method in (treatment, reference):
            group = [
                row
                for row in rows
                if row["trial_id"] == trial_id and row["method"] == method
            ]
            if metric == "cbf_events":
                pair[method] = float(sum(row[metric] for row in group))
            else:
                pair[method] = float(np.mean([row[metric] for row in group]))
        differences.append(pair[treatment] - pair[reference])
    values = np.asarray(differences, dtype=np.float64)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(10_000, len(values)))
    means = values[indices].mean(axis=1)
    return {
        "mean_difference": float(values.mean()),
        "ci95_low": float(np.quantile(means, 0.025)),
        "ci95_high": float(np.quantile(means, 0.975)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = json.loads(args.input.read_text(encoding="utf-8"))
    assert result["protocol_id"] == manifest["protocol_id"]
    assert result["manifest_sha256"] == _sha256(args.manifest)
    rows = result["episodes"]
    expected = len(manifest["trials"]) * len(manifest["scenarios"]) * len(manifest["methods"])
    assert len(rows) == expected
    assert len({(row["trial_id"], row["scenario"], row["method"]) for row in rows}) == expected
    summaries = {item["method"]: item for item in result["summary"]}
    treatment = "AEGIS_HOCBF_V2" if "AEGIS_HOCBF_V2" in summaries else "AEGIS_HOCBF"
    velocity = summaries["VELOCITY_CBF"]
    ours = summaries[treatment]
    efficiency = {
        "cbf_events": _paired_cluster_ci(
            rows, treatment, "VELOCITY_CBF", "cbf_events", seed=20260822
        ),
        "control_effort": _paired_cluster_ci(
            rows, treatment, "VELOCITY_CBF", "control_effort", seed=20260823
        ),
    }
    absolute_go = (
        ours["collisions"] == 0
        and ours["boundary_violations"] == 0
        and ours["completed"] == ours["episodes"]
        and ours["cbf_events"] > 0
    )
    velocity_go = (
        ours["collisions"] == velocity["collisions"]
        and ours["boundary_violations"] == velocity["boundary_violations"]
        and ours["completed"] == velocity["completed"]
        and (
            efficiency["cbf_events"]["ci95_high"] < 0.0
            or efficiency["control_effort"]["ci95_high"] < 0.0
        )
    )
    sota_go = True
    for baseline in ("ZOCBF", "PB_CBF"):
        other = summaries[baseline]
        no_worse = (
            ours["collisions"] <= other["collisions"]
            and ours["boundary_violations"] <= other["boundary_violations"]
            and ours["completed"] >= other["completed"]
        )
        strict = (
            ours["collisions"] < other["collisions"]
            or ours["boundary_violations"] < other["boundary_violations"]
            or ours["completed"] > other["completed"]
        )
        sota_go = sota_go and no_worse and strict
    report = {
        "protocol_id": manifest["protocol_id"],
        "decision": "GO" if absolute_go and velocity_go and sota_go else "NO_GO",
        "gates": {
            "absolute": absolute_go,
            "versus_velocity": velocity_go,
            "versus_sota": sota_go,
        },
        "summary": result["summary"],
        "paired_cluster_bootstrap_ours_minus_velocity": efficiency,
        "audit_passed": True,
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
