"""审计并汇总 C1/C2/C3 当前 HEAD 重跑产物。"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 9)


def _audit_trial_dir(root: Path, expected: dict, expected_protocol: str) -> list[dict]:
    summary_path = root / expected["trial_id"] / "summary.json"
    summary = _load(summary_path)
    assert summary["protocol_id"] == expected_protocol
    assert summary["selected_trial_ids"] == [expected["trial_id"]]
    assert [row["condition"] for row in summary["trials"]] == expected["condition_order"]
    for row in summary["trials"]:
        trajectory = summary_path.parent / row["trajectory"]
        assert trajectory.is_file()
        assert _sha256(trajectory) == row["trajectory_sha256"]
    return summary["trials"]


def audit_c1(manifest_path: Path, result_path: Path) -> dict:
    manifest = _load(manifest_path)
    result = _load(result_path)
    assert result["protocol_id"] == manifest["protocol_id"]
    assert result["manifest_sha256"] == _sha256(manifest_path)
    rows = result["trials"]
    assert [row["seed"] for row in rows] == manifest["seeds"]
    return {
        "protocol_id": manifest["protocol_id"],
        "decision": result["decision"],
        "n": len(rows),
        "positive_rho": sum(row["min_rho"] > 0 for row in rows),
        "completed": sum(row["completed"] for row in rows),
        "collisions": sum(row["collision"] for row in rows),
        "min_rho": min(row["min_rho"] for row in rows),
        "mean_min_rho": _mean([row["min_rho"] for row in rows]),
        "cbf_events": sum(row["cbf_events"] for row in rows),
        "qp_infeasible_steps": sum(row["qp_infeasible_steps"] for row in rows),
        "final_phases": sorted({row["supervisor"]["phase"] for row in rows}),
        "audit_passed": True,
    }


def audit_c2(manifest_path: Path, root: Path) -> dict:
    manifest = _load(manifest_path)
    assert (root / "COMPLETE").is_file()
    assert _sha256(root / "manifest.json") == _sha256(manifest_path)
    rows = []
    for trial in manifest["trials"]:
        rows.extend(_audit_trial_dir(root, trial, manifest["protocol_id"]))
    assert len(rows) == 3 * len(manifest["trials"])
    by_condition = {}
    for condition in ("E2_FIXED", "E2_QP_GATE", "C2_PRIME"):
        selected = [row for row in rows if row["condition"] == condition]
        by_condition[condition] = {
            "n": len(selected),
            "mean_min_rho": _mean([row["min_rho"] for row in selected]),
            "min_rho": min(row["min_rho"] for row in selected),
            "positive_rho": sum(row["min_rho"] > 0 for row in selected),
            "geometric_contact_lt_0_25_m": sum(row["min_distance_m"] < 0.25 for row in selected),
        }
    paired = []
    for trial in manifest["trials"]:
        trial_rows = {row["condition"]: row for row in rows if row["trial_id"] == trial["trial_id"]}
        paired.append(trial_rows["C2_PRIME"]["min_rho"] - trial_rows["E2_QP_GATE"]["min_rho"])
    go = (
        by_condition["C2_PRIME"]["positive_rho"] == len(manifest["trials"])
        and all(delta > 0 for delta in paired)
        and by_condition["C2_PRIME"]["geometric_contact_lt_0_25_m"] == 0
    )
    return {
        "protocol_id": manifest["protocol_id"],
        "decision": "GO" if go else "NO_GO",
        "trial_count": len(manifest["trials"]),
        "episode_count": len(rows),
        "conditions": by_condition,
        "c2_prime_minus_e2_qp_gate": {
            "mean": _mean(paired),
            "positive_pairs": sum(delta > 0 for delta in paired),
            "values": [round(delta, 6) for delta in paired],
        },
        "audit_passed": True,
    }


def audit_c3(manifest_path: Path, root: Path) -> dict:
    manifest = _load(manifest_path)
    assert (root / "COMPLETE").is_file()
    assert _sha256(root / "manifest.json") == _sha256(manifest_path)
    rows = []
    for trial in manifest["trials"]:
        selected = _audit_trial_dir(root, trial, manifest["protocol_id"])
        assert all(row["seed"] == trial["seed"] for row in selected)
        rows.extend(selected)
    assert len(rows) == 2 * len(manifest["trials"])
    by_condition = {}
    for condition in ("R0", "R1"):
        selected = [row for row in rows if row["condition"] == condition]
        by_condition[condition] = {
            "n": len(selected),
            "critical_reached": sum(row["critical_reached"] for row in selected),
            "positive_rho": sum(row["min_rho"] > 0 for row in selected),
            "collisions": sum(row["collision"] for row in selected),
            "min_rho": min(row["min_rho"] for row in selected),
            "mean_min_rho": _mean([row["min_rho"] for row in selected]),
            "mean_path_length_m": _mean([row["path_length_m"] for row in selected]),
            "cbf_events": sum(row["cbf_events"] for row in selected),
            "trials_with_cbf_intervention": sum(row["cbf_events"] > 0 for row in selected),
        }
    r1 = [row for row in rows if row["condition"] == "R1"]
    paired_direction = sum(
        not next(row for row in rows if row["trial_id"] == trial["trial_id"] and row["condition"] == "R0")["critical_reached"]
        and next(row for row in rows if row["trial_id"] == trial["trial_id"] and row["condition"] == "R1")["critical_reached"]
        for trial in manifest["trials"]
    )
    go = (
        paired_direction == len(manifest["trials"])
        and all(row["min_rho"] > 0 and not row["collision"] for row in rows)
        and all(row["recovery_step"] == 31 for row in r1)
        and all(row["counters"]["mission_changes"] == 1 for row in r1)
    )
    return {
        "protocol_id": manifest["protocol_id"],
        "decision": "GO" if go else "NO_GO",
        "trial_count": len(manifest["trials"]),
        "episode_count": len(rows),
        "paired_r0_false_r1_true": paired_direction,
        "conditions": by_condition,
        "r1_recovery_step_31": sum(row["recovery_step"] == 31 for row in r1),
        "r1_mission_changes_1": sum(row["counters"]["mission_changes"] == 1 for row in r1),
        "audit_passed": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--c1-result", type=Path, required=True)
    parser.add_argument("--c2-root", type=Path, required=True)
    parser.add_argument("--c3-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "c1_lightweight_bridge": audit_c1(Path("configs/c1_v2_lightweight_bridge_v1.json"), args.c1_result),
        "c2_v2_current_head": audit_c2(Path("configs/c2_prime_validation_v2_current_head.json"), args.c2_root),
        "c3_v2_current_head": audit_c3(Path("configs/c3_closed_loop_validation_v2_current_head.json"), args.c3_root),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
