#!/usr/bin/env python3
"""汇总 C 工作包三种失效几何 calibration smoke。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_integrity(root: Path) -> list[dict]:
    checks = []
    for integrity in sorted(root.glob("*/integrity.sha256")):
        for line in integrity.read_text(encoding="utf-8").splitlines():
            expected, name = line.split(maxsplit=1)
            path = integrity.parent / name
            actual = _sha256(path)
            checks.append(
                {
                    "path": str(path.relative_to(root)),
                    "expected": expected,
                    "actual": actual,
                    "ok": expected == actual,
                }
            )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"拒绝覆盖审计文件：{args.out}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    summaries = []
    for trial in manifest["trials"]:
        path = args.root / trial["trial_id"] / "summary.json"
        if path.exists():
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
    rows = [row for summary in summaries for row in summary["trials"]]
    by_geometry = []
    for trial in manifest["trials"]:
        geometry_rows = [
            row for row in rows if row["geometry_id"] == trial["geometry_id"]
        ]
        if len(geometry_rows) != 2:
            continue
        r0 = next(row for row in geometry_rows if row["condition"] == "R0")
        r1 = next(row for row in geometry_rows if row["condition"] == "R1")
        by_geometry.append(
            {
                "geometry_id": trial["geometry_id"],
                "decision": next(
                    summary["decision"]
                    for summary in summaries
                    if summary["trial"]["geometry_id"] == trial["geometry_id"]
                ),
                "r0_critical_reached": r0["critical_reached"],
                "r1_critical_reached": r1["critical_reached"],
                "minimum_rho": min(r0["min_rho"], r1["min_rho"]),
                "collisions": sum(row["collision"] for row in geometry_rows),
                "selected_qp_infeasible_steps": sum(
                    row["trajectory_audit"]["selected_qp_infeasible_steps"]
                    for row in geometry_rows
                ),
                "ra_bypass_count": sum(
                    row["trajectory_audit"]["ra_bypass_count"]
                    for row in geometry_rows
                ),
                "authority_revoked_all": all(
                    row["trajectory_audit"]["failed_authority_revoked_all_steps"]
                    and row["trajectory_audit"][
                        "failed_horizontal_command_zero_all_steps"
                    ]
                    for row in geometry_rows
                ),
                "maximum_ra_p99_ms": max(
                    row["ra_solve_latency_summary_ms"]["p99"]
                    for row in geometry_rows
                ),
                "deadline_misses": sum(
                    row["ra_solve_latency_summary_ms"]["deadline_misses"]
                    for row in geometry_rows
                ),
            }
        )
    integrity = _verify_integrity(args.root)
    complete = (args.root / "COMPLETE").exists()
    payload = {
        "protocol_id": manifest["protocol_id"],
        "decision": (
            "GO"
            if len(by_geometry) == 3
            and all(row["decision"] == "GO" for row in by_geometry)
            and complete
            and all(item["ok"] for item in integrity)
            else "NO_GO"
        ),
        "manifest_sha256": _sha256(args.manifest),
        "expected_geometries": len(manifest["trials"]),
        "completed_geometries": len(by_geometry),
        "valid_episodes": len(rows),
        "invalid_launch_markers": sorted(
            path.name
            for path in args.root.glob("*.invalid_launch")
            if not path.name.startswith("._")
        ),
        "complete_marker": complete,
        "integrity_all_ok": bool(integrity) and all(item["ok"] for item in integrity),
        "integrity_checks": integrity,
        "by_geometry": by_geometry,
    }
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
