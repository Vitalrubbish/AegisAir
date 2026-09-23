#!/usr/bin/env python3
"""审计 C1 HOCBF-v3 与 velocity-CBF 的 20-seed PX4 配对验证。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = []
    for path in sorted(args.root.glob("cbfv3px4_*_*/summary.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if len(payload["trials"]) != 1:
            raise ValueError(f"summary 条件数错误：{path}")
        row = dict(payload["trials"][0])
        trajectory = path.parent / row["trajectory"]
        if sha256(trajectory) != row["trajectory_sha256"]:
            raise ValueError(f"trajectory hash 不一致：{trajectory}")
        row["summary_sha256"] = sha256(path)
        rows.append(row)
    expected = len(manifest["trials"]) * 2
    if len(rows) != expected:
        raise ValueError(f"有效条件数 {len(rows)} != {expected}")

    summaries = []
    for method in ("AEGIS_HOCBF_V3", "VELOCITY_CBF"):
        group = [row for row in rows if row["method"] == method]
        summaries.append(
            {
                "method": method,
                "episodes": len(group),
                "completed": sum(row["mission_complete"] for row in group),
                "collisions": sum(row["collision"] for row in group),
                "boundary_violations": sum(row["min_rho"] <= 0 for row in group),
                "minimum_rho": min(row["min_rho"] for row in group),
                "mean_min_rho": float(np.mean([row["min_rho"] for row in group])),
                "cbf_events": sum(row["cbf_events"] for row in group),
                "qp_infeasible_steps": sum(row["qp_infeasible_steps"] for row in group),
                "mean_control_effort": float(
                    np.mean([row["mean_control_effort"] for row in group])
                ),
                "mean_path_length_m": float(
                    np.mean([row["path_length_m"] for row in group])
                ),
            }
        )

    by_trial = {}
    for row in rows:
        by_trial.setdefault(row["trial_id"], {})[row["method"]] = row
    diffs = {
        "cbf_events": np.array(
            [v["AEGIS_HOCBF_V3"]["cbf_events"] - v["VELOCITY_CBF"]["cbf_events"] for v in by_trial.values()]
        ),
        "control_effort": np.array(
            [v["AEGIS_HOCBF_V3"]["mean_control_effort"] - v["VELOCITY_CBF"]["mean_control_effort"] for v in by_trial.values()]
        ),
        "min_rho": np.array(
            [v["AEGIS_HOCBF_V3"]["min_rho"] - v["VELOCITY_CBF"]["min_rho"] for v in by_trial.values()]
        ),
    }
    rng = np.random.default_rng(20260822)
    paired = {}
    for metric, values in diffs.items():
        boot = np.mean(
            values[rng.integers(0, len(values), size=(20000, len(values)))], axis=1
        )
        paired[metric] = {
            "mean_difference_ours_minus_velocity": float(np.mean(values)),
            "ci95_low": float(np.quantile(boot, 0.025)),
            "ci95_high": float(np.quantile(boot, 0.975)),
        }
    ours = summaries[0]
    velocity = summaries[1]
    gate = bool(
        ours["episodes"] == 20
        and ours["completed"] == 20
        and ours["collisions"] == 0
        and ours["boundary_violations"] == 0
        and velocity["completed"] == 20
        and velocity["collisions"] == 0
        and velocity["boundary_violations"] == 0
    )
    payload = {
        "protocol_id": manifest["protocol_id"],
        "manifest_sha256": sha256(args.manifest),
        "audit_passed": True,
        "decision": "GO" if gate else "NO_GO",
        "summary": summaries,
        "paired_cluster_bootstrap": paired,
        "invalid_startups_excluded": sorted(
            str(p.relative_to(args.root))
            for p in args.root.glob("*invalid*")
            if not p.name.startswith("._")
        ),
        "episodes": rows,
    }
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: payload[k] for k in ("decision", "summary", "paired_cluster_bootstrap", "invalid_startups_excluded")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
