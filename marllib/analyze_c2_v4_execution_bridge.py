#!/usr/bin/env python3
"""审计冻结的 C2-v4 execution-bridge PX4 配对验证。"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


FULL = "AEGIS_HOCBF_V4"
COMPARATORS = ("AEGIS_HOCBF_V4_BAD_TAU", "AEGIS_HOCBF_V4_REACTIVE")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(root: Path) -> list[dict]:
    rows: list[dict] = []
    for summary in sorted(root.glob("*/summary.json")):
        payload = json.loads(summary.read_text(encoding="utf-8"))
        if len(payload["trials"]) != 1:
            raise ValueError(f"unexpected condition summary: {summary}")
        rows.append({**payload["trials"][0], "condition_dir": summary.parent.name,
                     "manifest_sha256": payload["manifest_sha256"]})
    return rows


def _summary(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["method"]].append(row)
    return [{
        "method": method, "trials": len(group),
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
    } for method, group in sorted(groups.items())]


def _paired(rows: list[dict], comparator: str) -> dict:
    by_trial: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        by_trial[row["trial_id"]][row["method"]] = row
    pairs = [by_trial[key] for key in sorted(by_trial)
             if FULL in by_trial[key] and comparator in by_trial[key]]
    rng = np.random.default_rng(20260823)
    metrics = ("min_rho", "cbf_events", "mean_control_effort", "path_length_m", "qp_infeasible_steps")
    payload = {"comparator": comparator, "pairs": len(pairs), "deltas_full_minus_comparator": {}}
    for metric in metrics:
        delta = np.asarray([float(pair[FULL][metric]) - float(pair[comparator][metric]) for pair in pairs])
        boot = np.asarray([np.mean(rng.choice(delta, size=len(delta), replace=True)) for _ in range(10000)])
        payload["deltas_full_minus_comparator"][metric] = {
            "mean": float(np.mean(delta)),
            "paired_wins": int(np.sum(delta > 0.0)) if metric == "min_rho" else int(np.sum(delta < 0.0)),
            "bootstrap_95_ci": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
        }
    return payload


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
    expected = len(manifest["trials"]) * len(manifest["methods"])
    manifest_hash = _sha256(args.manifest)
    payload = {
        "manifest_sha256": manifest_hash,
        "conditions_expected": expected, "conditions_found": len(rows),
        "method_summary": _summary(rows),
        "paired": [_paired(rows, comparator) for comparator in COMPARATORS],
        "go": bool(len(rows) == expected
                   and all(row["manifest_sha256"] == manifest_hash for row in rows)
                   and all(not row["collision"] and row["mission_complete"] and float(row["min_rho"]) > 0.0 for row in rows if row["method"] != "AEGIS_HOCBF_V4_BAD_TAU")
                   and all(int(row["qp_infeasible_steps"]) == 0 for row in rows if row["method"] == FULL)),
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
