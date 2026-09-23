#!/usr/bin/env python3
"""审计冻结的 C1-v4 post-freeze OOD 验证，不对结果作再调参。"""

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
    rows: list[dict] = []
    for summary in sorted(root.glob("*/summary.json")):
        payload = json.loads(summary.read_text(encoding="utf-8"))
        if len(payload.get("trials", [])) != 1:
            raise ValueError(f"unexpected condition summary: {summary}")
        rows.append({**payload["trials"][0], "condition_dir": summary.parent.name})
    return rows


def _method_summary(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["scenario_id"], row["method"])].append(row)
    output = []
    for (scenario_id, method), group in sorted(groups.items()):
        output.append({
            "scenario_id": scenario_id,
            "method": method,
            "episodes": len(group),
            "completed": sum(bool(r["mission_complete"]) for r in group),
            "collisions": sum(bool(r["collision"]) for r in group),
            "minimum_rho": min(float(r["min_rho"]) for r in group),
            "mean_min_rho": float(np.mean([r["min_rho"] for r in group])),
            "selected_qp_infeasible_steps": sum(int(r["qp_infeasible_steps"]) for r in group),
            "mean_control_effort": float(np.mean([r["mean_control_effort"] for r in group])),
            "mean_path_length_m": float(np.mean([r["path_length_m"] for r in group])),
            "command_hold_jitter_count": sum(int(r["command_hold_jitter_count"]) for r in group),
        })
    return output


def _paired(rows: list[dict], scenario_id: str, comparator: str) -> dict:
    pairs: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        if row["scenario_id"] == scenario_id:
            pairs[row["trial_id"]][row["method"]] = row
    paired = [p for _, p in sorted(pairs.items()) if V4 in p and comparator in p]
    rng = np.random.default_rng(20260823)
    metrics = ("min_rho", "mean_control_effort", "path_length_m", "cbf_events")
    deltas = {}
    for metric in metrics:
        values = np.asarray([float(p[V4][metric]) - float(p[comparator][metric]) for p in paired])
        samples = np.asarray([np.mean(rng.choice(values, size=len(values), replace=True)) for _ in range(10000)])
        deltas[metric] = {
            "mean": float(np.mean(values)),
            "bootstrap_95_ci": [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))],
        }
    return {"scenario_id": scenario_id, "comparator": comparator, "pairs": len(paired), "deltas_v4_minus_comparator": deltas}


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
    scenarios = sorted({trial["scenario_id"] for trial in manifest["trials"]})
    payload = {
        "protocol_id": manifest["protocol_id"],
        "manifest_sha256": _sha256(args.manifest),
        "conditions_expected": sum(len(t["condition_order"]) for t in manifest["trials"]),
        "conditions_found": len(rows),
        "method_summary": _method_summary(rows),
        "paired": [
            _paired(rows, scenario, comparator)
            for scenario in scenarios
            for comparator in ("AEGIS_HOCBF_V4_REACTIVE", "PB_CBF")
            if any(r["scenario_id"] == scenario and r["method"] == comparator for r in rows)
        ],
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
