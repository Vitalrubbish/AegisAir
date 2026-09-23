#!/usr/bin/env python3
"""汇总每条件全新 SITL 产生的 C3-Reservation × MAPPO calibration。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marllib.run_c3_reservation_gazebo import _sha256
from marllib.run_c3_reservation_mappo_gazebo import (
    RULE_CONDITION,
    _paired_delta,
    _validate_manifest,
)


def aggregate(manifest_path: Path, conditions_root: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    manifest_hash = _sha256(manifest_path)
    rows = []
    sources = []
    for index, condition in enumerate(manifest["condition_order"]):
        run_root = conditions_root / f"{index:02d}_{condition}"
        summary_path = run_root / "calibration" / "summary.json"
        complete_path = run_root / "calibration" / "COMPLETE"
        if not summary_path.is_file() or not complete_path.is_file():
            raise FileNotFoundError(f"条件结果不完整：{run_root}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("protocol_id") != manifest["protocol_id"]:
            raise ValueError(f"协议不匹配：{summary_path}")
        if summary.get("manifest_sha256") != manifest_hash:
            raise ValueError(f"manifest 哈希不匹配：{summary_path}")
        if summary.get("single_condition_run") is not True:
            raise ValueError(f"不是单条件隔离结果：{summary_path}")
        condition_rows = summary.get("conditions", [])
        if len(condition_rows) != 1 or condition_rows[0].get("condition") != condition:
            raise ValueError(f"条件身份不匹配：{summary_path}")
        rows.append(condition_rows[0])
        sources.append(
            {
                "condition": condition,
                "summary": str(summary_path),
                "summary_sha256": _sha256(summary_path),
            }
        )
    rule = rows[0]
    all_go = all(row["condition_go"] for row in rows)
    return {
        "protocol_id": manifest["protocol_id"],
        "phase": manifest["phase"],
        "decision": "GO" if all_go else "NO_GO",
        "manifest_sha256": manifest_hash,
        "gazebo_seed": manifest["gazebo_seed"],
        "fresh_sitl_per_condition": True,
        "all_conditions_go": all_go,
        "mappo_conditions_passed": sum(row["condition_go"] for row in rows[1:]),
        "mappo_conditions_total": len(rows) - 1,
        "paired_deltas_vs_rule": [_paired_delta(rule, row) for row in rows[1:]],
        "condition_sources": sources,
        "conditions": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--conditions-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"拒绝覆盖：{args.output}")
    summary = aggregate(args.manifest, args.conditions_root)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"decision": summary["decision"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
