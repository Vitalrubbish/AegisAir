#!/usr/bin/env python3
"""汇总四机 R3/R4 C3-STR qualification。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marllib.run_c3_str_qualification_gazebo import (
    CONDITIONS,
    PROTOCOL_ID,
    validate_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _integrity_ok(directory: Path) -> bool:
    integrity = directory / "integrity.sha256"
    if not integrity.is_file():
        return False
    for line in integrity.read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        target = directory / name.strip()
        if not target.is_file() or _sha256(target) != digest:
            return False
    return True


def _method_summary(rows: list[dict[str, Any]], condition: str) -> dict[str, Any]:
    group = [row for row in rows if row["condition"] == condition]
    completion_steps = [
        int(row["completion_step"])
        for row in group
        if row["completion_step"] is not None
    ]
    return {
        "condition": condition,
        "valid_trials": len(group),
        "mission_completed": sum(bool(row["mission_complete"]) for row in group),
        "joint_successes": sum(bool(row["joint_success"]) for row in group),
        "collisions": sum(bool(row["collision"]) for row in group),
        "minimum_rho": min((float(row["min_rho"]) for row in group), default=None),
        "selected_qp_infeasible_steps": sum(
            int(row["audit"]["selected_qp_infeasible_steps"]) for row in group
        ),
        "ra_bypass_count": sum(int(row["audit"]["ra_bypass_count"]) for row in group),
        "mean_completion_step": (
            float(np.mean(completion_steps)) if completion_steps else None
        ),
        "mean_path_length_m": (
            float(np.mean([row["path_length_m"] for row in group])) if group else None
        ),
        "mean_control_effort": (
            float(np.mean([row["mean_control_effort"] for row in group])) if group else None
        ),
    }


def collect(manifest_path: Path, root: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    manifest_hash = _sha256(manifest_path)
    rows: list[dict[str, Any]] = []
    attempt_audit: list[dict[str, Any]] = []
    for seed_index, seed in enumerate(manifest["qualification_seeds"], start=1):
        seed_root = root / f"q{seed_index:02d}_seed{seed}"
        for condition in manifest["condition_order_by_seed"][str(seed)]:
            condition_root = seed_root / condition
            valid = []
            invalid = []
            for attempt in sorted(condition_root.glob("attempt_*")):
                calibration = attempt / "calibration"
                summary_path = calibration / "summary.json"
                if (
                    summary_path.is_file()
                    and (calibration / "COMPLETE").is_file()
                    and _integrity_ok(calibration)
                ):
                    payload = json.loads(summary_path.read_text(encoding="utf-8"))
                    if (
                        payload.get("protocol_id") != PROTOCOL_ID
                        or payload.get("manifest_sha256") != manifest_hash
                        or payload.get("seed") != seed
                        or payload.get("condition") != condition
                    ):
                        raise ValueError(f"条件身份或 manifest 不匹配：{summary_path}")
                    valid.append((attempt, payload))
                else:
                    invalid.append(attempt)
            if len(valid) > 1:
                raise ValueError(f"发现多个有效重跑，违反冻结协议：{condition_root}")
            attempt_audit.append(
                {
                    "seed": seed,
                    "condition": condition,
                    "invalid_attempts": [str(path) for path in invalid],
                    "valid_attempt": str(valid[0][0]) if valid else None,
                }
            )
            if valid:
                attempt, payload = valid[0]
                row = dict(payload["trial"])
                row["summary_path"] = str(attempt / "calibration" / "summary.json")
                row["trajectory_path"] = str(
                    attempt / "calibration" / row["trajectory"]
                )
                rows.append(row)

    r4_rows = [row for row in rows if row["condition"] == "R4_C3_STR"]
    any_r4_failure = any(row["r4_qualification_go"] is False for row in r4_rows)
    expected = len(manifest["qualification_seeds"]) * len(CONDITIONS)
    complete = len(rows) == expected
    qualification_go = bool(
        complete
        and len(r4_rows) == len(manifest["qualification_seeds"])
        and all(row["r4_qualification_go"] for row in r4_rows)
    )
    decision = "NO_GO" if any_r4_failure else "GO" if qualification_go else "INCOMPLETE"
    return {
        "protocol_id": PROTOCOL_ID,
        "phase": manifest["phase"],
        "decision": decision,
        "qualification_go": qualification_go,
        "manifest_sha256": manifest_hash,
        "expected_valid_conditions": expected,
        "found_valid_conditions": len(rows),
        "r4_valid_trials": len(r4_rows),
        "r4_passed_trials": sum(bool(row["r4_qualification_go"]) for row in r4_rows),
        "invalid_startups": sum(len(item["invalid_attempts"]) for item in attempt_audit),
        "method_summary": [_method_summary(rows, condition) for condition in CONDITIONS],
        "attempt_audit": attempt_audit,
        "trials": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"拒绝覆盖：{args.output}")
    payload = collect(args.manifest, args.root)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"decision": payload["decision"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
