#!/usr/bin/env python3
"""汇总 C1 强 CBF 基线的 PX4 smoke 与 sealed stop-rule 结果。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def one_row(summary: Path) -> dict:
    payload = json.loads(summary.read_text(encoding="utf-8"))
    if len(payload["trials"]) != 1:
        raise ValueError(f"每个 fresh-SITL summary 必须只有一个条件：{summary}")
    row = dict(payload["trials"][0])
    trajectory = summary.parent / row["trajectory"]
    if sha256(trajectory) != row["trajectory_sha256"]:
        raise ValueError(f"trajectory hash 不一致：{trajectory}")
    row["summary"] = str(summary)
    row["summary_sha256"] = sha256(summary)
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    smoke_root = Path("/Volumes/Expansion/Aegis/c1_sota_cbf_px4_smoke_v1_fresh")
    smoke_paths = {
        "VELOCITY_CBF": smoke_root / "VELOCITY_CBF/summary.json",
        "ZOCBF": smoke_root / "ZOCBF/summary.json",
        "PB_CBF": smoke_root / "PB_CBF/summary.json",
        "AEGIS_HOCBF_V2": smoke_root / "AEGIS_HOCBF_V2_attempt2/summary.json",
    }
    smoke = [one_row(path) for path in smoke_paths.values()]
    smoke_by_method = {row["method"]: row for row in smoke}
    absolute_pass = {
        method: bool(
            not row["collision"]
            and row["mission_complete"]
            and row["min_rho"] > 0.0
        )
        for method, row in smoke_by_method.items()
    }

    validation_root = Path(
        "/Volumes/Expansion/Aegis/c1_sota_cbf_px4_validation_v1"
    )
    validation = [
        one_row(validation_root / "cbfpx4v01_VELOCITY_CBF/summary.json"),
        one_row(validation_root / "cbfpx4v01_AEGIS_HOCBF_V2/summary.json"),
    ]
    ours = next(row for row in validation if row["method"] == "AEGIS_HOCBF_V2")
    gate = bool(
        not ours["collision"]
        and ours["mission_complete"]
        and ours["min_rho"] > 0.0
    )
    result = {
        "protocol_id": "aegisair-c1-sota-cbf-px4-audit-v1",
        "smoke": smoke,
        "smoke_absolute_pass": absolute_pass,
        "sealed_validation_completed_trials": 1,
        "sealed_validation_planned_trials": 20,
        "sealed_validation": validation,
        "decision": "GO" if gate else "NO_GO_STOP_RULE",
        "stop_reason": (
            None
            if gate
            else "首个 sealed seed 的 AEGIS_HOCBF_V2 min_rho<=0；20/20 正裕度门已不可达"
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
