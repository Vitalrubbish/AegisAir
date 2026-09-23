#!/usr/bin/env python3
"""审计冻结的 C1 HOCBF-v4 PX4 paired validation。"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


V4 = "AEGIS_HOCBF_V4"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(root: Path) -> list[dict]:
    rows = []
    for summary in sorted(root.glob("*/summary.json")):
        payload = json.loads(summary.read_text(encoding="utf-8"))
        if len(payload["trials"]) != 1:
            raise ValueError(f"unexpected condition summary: {summary}")
        rows.append({**payload["trials"][0], "condition_dir": summary.parent.name,
                     "manifest_sha256": payload["manifest_sha256"]})
    return rows


def _method_summary(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["method"]].append(row)
    output = []
    for method, group in sorted(groups.items()):
        output.append({
            "method": method,
            "trials": len(group),
            "completed": sum(bool(r["mission_complete"]) for r in group),
            "collisions": sum(bool(r["collision"]) for r in group),
            "minimum_rho": min(float(r["min_rho"]) for r in group),
            "mean_min_rho": float(np.mean([r["min_rho"] for r in group])),
            "mean_cbf_events": float(np.mean([r["cbf_events"] for r in group])),
            "selected_qp_infeasible_steps": sum(int(r["qp_infeasible_steps"]) for r in group),
            "primary_hocbf_infeasible_steps": sum(int(r.get("hocbf_primary_infeasible_steps", 0)) for r in group),
            "recovery_infeasible_steps": sum(int(r.get("hocbf_recovery_infeasible_steps", 0)) for r in group),
            "mean_control_effort": float(np.mean([r["mean_control_effort"] for r in group])),
            "mean_path_length_m": float(np.mean([r["path_length_m"] for r in group])),
        })
    return output


def _paired(rows: list[dict], comparator: str) -> dict:
    by_trial: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        by_trial[row["trial_id"]][row["method"]] = row
    paired = [by_trial[trial] for trial in sorted(by_trial) if V4 in by_trial[trial] and comparator in by_trial[trial]]
    metrics = ("min_rho", "cbf_events", "mean_control_effort", "path_length_m", "qp_infeasible_steps")
    rng = np.random.default_rng(20260823)
    payload = {"comparator": comparator, "pairs": len(paired), "deltas_v4_minus_comparator": {}}
    for metric in metrics:
        delta = np.asarray([float(pair[V4][metric]) - float(pair[comparator][metric]) for pair in paired])
        samples = np.asarray([np.mean(rng.choice(delta, size=len(delta), replace=True)) for _ in range(10000)])
        payload["deltas_v4_minus_comparator"][metric] = {
            "mean": float(np.mean(delta)),
            "paired_wins": int(np.sum(delta < 0.0)) if metric != "min_rho" else int(np.sum(delta > 0.0)),
            "bootstrap_95_ci": [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))],
        }
    return payload


def _mechanism(root: Path, rows: list[dict]) -> list[dict]:
    audits = []
    for row in rows:
        if row["method"] != V4:
            continue
        path = root / row["condition_dir"] / row["trajectory"]
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        first_recovery = None
        first_primary_bad = None
        for record in records:
            drone = next(iter(record["drones"].values()))
            if first_recovery is None and drone["recovery_active"]:
                first_recovery = {
                    "step": int(record["step"]), "reason": drone["recovery_reason"],
                    "rho": float(drone["rho"]), "primary_feasible": bool(drone["primary_feasible"]),
                    "reserve": float(drone["feasibility_reserve"]),
                }
            if first_primary_bad is None and drone["primary_feasible"] is False:
                first_primary_bad = int(record["step"])
        lead = None if first_recovery is None or first_primary_bad is None else first_primary_bad - first_recovery["step"]
        audits.append({
            "trial_id": row["trial_id"], "seed": row["seed"], "first_recovery": first_recovery,
            "first_primary_infeasible_step": first_primary_bad, "lead_steps": lead,
            "pass": bool(first_recovery and first_recovery["reason"] == "feasibility_reserve_low" and first_recovery["primary_feasible"] and lead is not None and lead > 0),
        })
    return audits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"refusing to overwrite audit: {args.out}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = _rows(args.root)
    expected_conditions = len(manifest["trials"]) * len(manifest["methods"])
    mechanisms = _mechanism(args.root, rows)
    payload = {
        "manifest_sha256": _sha256(args.manifest), "conditions_expected": expected_conditions,
        "conditions_found": len(rows), "method_summary": _method_summary(rows),
        "paired": [_paired(rows, name) for name in ("AEGIS_HOCBF_V4_REACTIVE", "AEGIS_HOCBF_V3", "PB_CBF")],
        "mechanism_audit": mechanisms,
        "go": bool(len(rows) == expected_conditions
                   and all(r["manifest_sha256"] == _sha256(args.manifest) for r in rows)
                   and all(not r["collision"] and r["mission_complete"] and float(r["min_rho"]) > 0.0 for r in rows)
                   and all(item["pass"] for item in mechanisms)
                   and all(int(r["qp_infeasible_steps"]) == 0 for r in rows if r["method"] == V4)),
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
