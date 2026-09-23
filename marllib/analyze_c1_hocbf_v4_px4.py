#!/usr/bin/env python3
"""审计 C1 HOCBF-v4 PX4 smoke 的安全、性能与提前切换证据。"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def _load_trials(root: Path) -> list[dict]:
    rows = []
    for summary in sorted(root.glob("*/summary.json")):
        payload = json.loads(summary.read_text(encoding="utf-8"))
        for row in payload["trials"]:
            rows.append({**row, "condition_dir": summary.parent.name})
    return rows


def _method_summary(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["method"]].append(row)
    output = []
    for method, group in sorted(groups.items()):
        output.append(
            {
                "method": method,
                "trials": len(group),
                "completed": sum(bool(row["mission_complete"]) for row in group),
                "collisions": sum(bool(row["collision"]) for row in group),
                "minimum_rho": min(float(row["min_rho"]) for row in group),
                "mean_min_rho": float(np.mean([row["min_rho"] for row in group])),
                "mean_cbf_events": float(np.mean([row["cbf_events"] for row in group])),
                "selected_qp_infeasible_steps": sum(
                    int(row["qp_infeasible_steps"]) for row in group
                ),
                "primary_hocbf_infeasible_steps": sum(
                    int(row.get("hocbf_primary_infeasible_steps", 0)) for row in group
                ),
                "recovery_infeasible_steps": sum(
                    int(row.get("hocbf_recovery_infeasible_steps", 0)) for row in group
                ),
                "mean_control_effort": float(
                    np.mean([row["mean_control_effort"] for row in group])
                ),
                "mean_path_length_m": float(
                    np.mean([row["path_length_m"] for row in group])
                ),
            }
        )
    return output


def _mechanism_audit(root: Path, rows: list[dict]) -> list[dict]:
    audits = []
    for row in rows:
        if row["method"] != "AEGIS_HOCBF_V4":
            continue
        trajectory = root / row["condition_dir"] / row["trajectory"]
        records = [
            json.loads(line)
            for line in trajectory.read_text(encoding="utf-8").splitlines()
        ]
        first_recovery = None
        first_primary_bad = None
        for record in records:
            drone = next(iter(record["drones"].values()))
            if first_recovery is None and drone["recovery_active"]:
                first_recovery = {
                    "step": int(record["step"]),
                    "reason": drone["recovery_reason"],
                    "rho": float(drone["rho"]),
                    "feasibility_reserve": float(drone["feasibility_reserve"]),
                    "primary_feasible": bool(drone["primary_feasible"]),
                }
            if first_primary_bad is None and drone["primary_feasible"] is False:
                first_primary_bad = int(record["step"])
        lead = (
            first_primary_bad - first_recovery["step"]
            if first_recovery is not None and first_primary_bad is not None
            else None
        )
        audits.append(
            {
                "trial_id": row["trial_id"],
                "seed": row["seed"],
                "first_recovery": first_recovery,
                "first_primary_infeasible_step": first_primary_bad,
                "lead_steps": lead,
                "mechanism_pass": bool(
                    first_recovery is not None
                    and first_recovery["reason"] == "feasibility_reserve_low"
                    and first_recovery["primary_feasible"]
                    and lead is not None
                    and lead > 0
                ),
            }
        )
    return audits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = _load_trials(args.root)
    mechanisms = _mechanism_audit(args.root, rows)
    payload = {
        "source": str(args.root),
        "method_summary": _method_summary(rows),
        "mechanism_audit": mechanisms,
        "smoke_go": bool(
            len(rows) == 9
            and all(not row["collision"] for row in rows)
            and all(row["mission_complete"] for row in rows)
            and all(float(row["min_rho"]) > 0.0 for row in rows)
            and all(item["mechanism_pass"] for item in mechanisms)
            and all(
                int(row["qp_infeasible_steps"]) == 0
                for row in rows
                if row["method"] == "AEGIS_HOCBF_V4"
            )
        ),
        "claim_boundary": (
            "三 seed smoke 仅支持机制与扩展 GO；不支持显著性或 SOTA 优越性结论。"
        ),
    }
    if args.out.exists():
        parser.error(f"拒绝覆盖已有审计：{args.out}")
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
