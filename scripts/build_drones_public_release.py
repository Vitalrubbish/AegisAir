"""构建 Drones 论文的可核验公开归档，不修改实验原件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]

# 每组保留原始摘要、轨迹、运行清单、状态和独立分析；开发负结果也保留。
CAMPAIGNS = {
    "control": (
        "paper_full_rerun_20260921_441c8f1/01_step_response_attempt3_freeflight",
        "drones_corrected_c1_v2_20260921",
        "drones_corrected_ablation_v2_20260921",
        "drones_corrected_c2_v2_20260922",
        "drones_corrected_external_matched_v2_20260922",
        "drones_corrected_external_unmatched_v2_20260922",
        "drones_corrected_ood_v2_20260922",
        "drones_corrected_certificate_v2_20260922",
        "drones_corrected_certificate_inputs_v1_20260922",
        "drones_corrected_certificate_diagnosis_v1_20260922",
        "drones_corrected_trigger_grid1_v2_20260922",
        "drones_corrected_trigger_grid2_v2_20260922",
        "drones_corrected_trigger_grid3_v2_20260922",
        "drones_corrected_trigger_test_freeze_v1_20260922",
        "drones_corrected_trigger_test_v1_20260922",
        "drones_corrected_trigger_analysis_v1_20260923",
        "drones_admission_state_comparison_v1_20260922",
    ),
    "mission": (
        "drones_corrected_c3_v2_20260922",
        "drones_corrected_group_calibration_v2_20260922",
        "drones_corrected_group_qualification_v2_20260922",
        "drones_corrected_group_sealed_v2_20260922",
    ),
    "admission": (
        "c_recoverability_admission_sealed_v1",
        "drones_corrected_admission_calibration_v2_20260922",
        "drones_corrected_admission_calibration_v5_20260923",
        "drones_admission_arc_probe_v6_bottleneck_20260923",
        "drones_corrected_admission_calibration_v6_20260923",
        "drones_corrected_admission_qualification_v6_20260923",
        "drones_corrected_admission_sealed_v6_20260923",
        "drones_corrected_admission_comparison_v6_20260923",
        "drones_corrected_admission_geometry_v2_20260922",
    ),
}

DATA_SUFFIXES = {".json", ".jsonl", ".csv", ".sha256", ".txt"}
SOURCE_SUFFIXES = {".py", ".sh", ".json", ".tex", ".bib", ".md", ".txt", ".yaml", ".yml", ".cls", ".bst", ".pdf", ".png"}
SOURCE_DIRS = ("configs", "scripts", "swarm", "marllib", "px4_adapter", "tests")
ROOT_SOURCE_FILES = ("README.md", "REPRODUCIBILITY.md", "requirements.txt", "environment.yml", "docker-compose.yml")
SENSITIVE = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb'(?i)"(?:password|client_secret|api_key)"\s*:\s*"[^"]{5,}"'),
)


def selected_data(root: Path, campaign: str):
    folder = root / campaign
    if not folder.is_dir():
        raise FileNotFoundError(folder)
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.startswith("._"):
            continue
        relative = path.relative_to(folder)
        log_folder = any(part.endswith("_logs") for part in relative.parts[:-1])
        if log_folder and path.name not in {"telemetry_arrivals.jsonl", "command.json"}:
            continue
        if path.suffix in DATA_SUFFIXES or path.name == "COMPLETE":
            yield path, Path("evidence") / campaign / relative


def selected_source():
    for directory in SOURCE_DIRS:
        folder = REPO / directory
        if not folder.is_dir():
            raise FileNotFoundError(folder)
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.name.startswith("._"):
                continue
            relative = path.relative_to(REPO)
            if any(part in {"__pycache__", ".pytest_cache", "output"} for part in relative.parts):
                continue
            if path.suffix in SOURCE_SUFFIXES or path.name.startswith("Dockerfile"):
                yield path, Path("source") / relative
    for name in ROOT_SOURCE_FILES:
        path = REPO / name
        if path.is_file():
            yield path, Path("source") / name


def write_zip(destination: Path, files, category: str, entries: list[dict], findings: list[str]):
    count = 0
    total = 0
    with zipfile.ZipFile(destination, "w", allowZip64=True, compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, relative in files:
            size = path.stat().st_size
            digest = hashlib.sha256()
            info = zipfile.ZipInfo(str(relative), (2026, 9, 23, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            first_bytes = b""
            with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as target:
                while block := source.read(1024 * 1024):
                    digest.update(block)
                    if len(first_bytes) < 1024 * 1024:
                        first_bytes += block[: 1024 * 1024 - len(first_bytes)]
                    target.write(block)
            if any(pattern.search(first_bytes) for pattern in SENSITIVE):
                findings.append(str(relative))
            entries.append({"archive": destination.name, "path": str(relative), "bytes": size, "sha256": digest.hexdigest(), "category": category})
            count += 1
            total += size
            if count % 250 == 0:
                print(f"{category}: {count} files, {total / 1e6:.1f} MB read", flush=True)
    print(f"{category}: {count} files, {total / 1e6:.1f} MB raw, {destination.stat().st_size / 1e6:.1f} MB archive", flush=True)


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("/Volumes/Expansion/Aegis"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not Path("/Volumes/Expansion").is_mount():
        parser.error("外置实验盘未挂载")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("输出目录必须为空，以免覆盖已有发布包")
    args.out.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    findings: list[str] = []
    for category, campaigns in CAMPAIGNS.items():
        files = (item for campaign in campaigns for item in selected_data(args.data_root, campaign))
        write_zip(args.out / f"aegisair-drones-{category}-evidence.zip", files, category, entries, findings)
    write_zip(args.out / "aegisair-drones-source-snapshot.zip", selected_source(), "source", entries, findings)
    (args.out / "file_manifest.json").write_text(json.dumps({
        "schema": "aegisair-drones-public-release-v1",
        "license_for_evidence": "CC-BY-4.0",
        "source_snapshot_note": "Release-time source snapshot; per-attempt recorded source/runtime hashes identify historical executions.",
        "excluded": "Container/PX4/MQTT text logs and most *_logs sidecars; per-attempt manifests, summaries, trajectories, integrity files, and telemetry-arrival/command sidecars are included.",
        "files": entries,
    }, indent=2, ensure_ascii=False) + "\n")
    (args.out / "security_scan_findings.json").write_text(json.dumps(findings, indent=2) + "\n")
    if findings:
        print(f"潜在敏感项 {len(findings)} 个，禁止上传前需逐项复核", file=sys.stderr)
    (args.out / "README.md").write_text(
        "# AegisAir Drones study: corrected simulation evidence\n\n"
        "This release accompanies *Control-Authority Reserve and Selective Mission Recovery for Multi-UAV Runtime Assurance*. "
        "The evidence files are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). "
        "The source snapshot is supplied for inspection and reanalysis; no separate software license is granted here.\n\n"
        "## Contents\n\n"
        "- `aegisair-drones-control-evidence.zip`: step response, corrected C1/C2, ablation, matched and unmatched PCBF comparisons, OOD, PB-slack diagnostics, and trigger development/test.\n"
        "- `aegisair-drones-mission-evidence.zip`: corrected orphan-goal recovery and four-UAV calibration, qualification, and twenty-seed corridor run.\n"
        "- `aegisair-drones-admission-evidence.zip`: historical static admission, stopped dynamic development, multi-waypoint development and qualification, corrected twenty-case rerun, and geometry-only comparison.\n"
        "- `aegisair-drones-source-snapshot.zip`: release-time code, configurations, analysis scripts, and tests.\n"
        "- `file_manifest.json`: relative member path, size, category, and SHA-256 for every archived file. `SHA256SUMS` checks the downloaded release assets.\n\n"
        "## Verification\n\n"
        "Download all files into one directory and run `python verify_release.py .`. "
        "The command verifies each asset and every ZIP member against the manifest. "
        "The original campaign names are retained as provenance identifiers, not pooled experimental conditions.\n\n"
        "## Evidence boundaries\n\n"
        "The historical static-admission result, stopped single-waypoint development, final multi-waypoint qualification, and corrected twenty-case rerun are distinct. "
        "The final rerun reuses the original twenty-case design and is not a newly independent blind set. "
        "Infrastructure-invalid attempts remain represented in the archived statuses and manifests. "
        "The release omits bulky container/PX4/MQTT text logs and most runtime sidecars; it retains original episode summaries, trajectories, run settings, integrity records, and selected telemetry-arrival/command sidecars. "
        "The source snapshot reflects release time; per-attempt hashes identify the historical runtime, whose complete environment is not reconstructed by this archive. "
        "Absolute paths in archived records are historical host metadata; checksum verification works without those paths, while some legacy analysis scripts need path rebasing after extraction. "
        "Reported selected-output feasibility should not be read as certification of every published command.\n\n"
        "中文说明：本包保留论文核心表图对应的逐次摘要、轨迹、配置、校验和有效负结果。"
        "历史静态接纳、开发阶段的有效拒绝、最终方法资格组和原二十例修正重跑分别解释；"
        "二十例重跑不是全新独立盲测。数据采用 CC BY 4.0，使用时请注明作者和本发布版本。\n"
    )
    (args.out / "LICENSE_DATA.md").write_text(
        "# Data license / 数据许可\n\n"
        "The evidence archives, file manifest, and release metadata are licensed under "
        "Creative Commons Attribution 4.0 International (CC BY 4.0): "
        "https://creativecommons.org/licenses/by/4.0/\n\n"
        "Attribution: Jiajun Li, *AegisAir Drones study: corrected simulation evidence*, "
        "release version identified by this archive's SHA256SUMS and the GitHub release tag.\n\n"
        "This notice does not relicense third-party PX4/Gazebo components or the included source-code snapshot.\n"
    )
    shutil.copy2(REPO / "scripts/verify_drones_public_release.py", args.out / "verify_release.py")
    release_names = [
        "LICENSE_DATA.md",
        "README.md",
        "aegisair-drones-admission-evidence.zip",
        "aegisair-drones-control-evidence.zip",
        "aegisair-drones-mission-evidence.zip",
        "aegisair-drones-source-snapshot.zip",
        "file_manifest.json",
        "verify_release.py",
    ]
    products = [args.out / name for name in release_names]
    (args.out / "SHA256SUMS").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in products))
    print(f"manifest: {len(entries)} files; security findings: {len(findings)}", flush=True)


if __name__ == "__main__":
    main()
