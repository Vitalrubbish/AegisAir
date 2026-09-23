"""索引本次修正版证据；文件存在/哈希不等同实验通过。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = [
    'drones_corrected_c1_v2_20260921', 'drones_corrected_ablation_v2_20260921',
    'drones_corrected_external_matched_v2_20260922', 'drones_corrected_external_unmatched_v2_20260922',
    'drones_corrected_c2_v2_20260922', 'drones_corrected_ood_v2_20260922',
    'drones_corrected_c3_v2_20260922', 'drones_corrected_admission_calibration_v2_20260922',
    'drones_corrected_group_calibration_v2_20260922', 'drones_corrected_group_qualification_v2_20260922',
    'drones_corrected_group_sealed_v2_20260922', 'drones_corrected_certificate_v2_20260922',
    'drones_corrected_certificate_inputs_v1_20260922', 'drones_corrected_certificate_diagnosis_v1_20260922',
    'drones_corrected_trigger_grid1_v2_20260922', 'drones_corrected_trigger_grid2_v2_20260922',
    'drones_corrected_trigger_grid3_v2_20260922', 'drones_corrected_trigger_test_freeze_v1_20260922',
    'drones_corrected_trigger_test_v1_20260922', 'drones_corrected_trigger_analysis_v1_20260923',
    'drones_corrected_admission_geometry_v2_20260922', 'drones_admission_state_comparison_v1_20260922',
    'drones_trigger_velocity_state_audit_v1_20260922',
    'paper_full_rerun_20260921_441c8f1/01_step_response_attempt3_freeflight',
]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not Path('/Volumes/Expansion').is_mount():
        raise ValueError('外置盘未挂载')
    entries, states = [], {}
    for name in CAMPAIGNS:
        folder = args.data_root / name
        if not folder.is_dir():
            raise ValueError(f'证据目录缺失：{folder}')
        status = folder / 'status.json'
        states[name] = json.loads(status.read_text()).get('state') if status.exists() else '分析/离线输出，无统一状态字段'
        for path in sorted(folder.rglob('*')):
            if path.suffix not in ('.json', '.jsonl') or path.name.startswith('._'):
                continue
            if any(part.endswith('_logs') for part in path.relative_to(folder).parts):
                continue
            entries.append(dict(path=str(path), bytes=path.stat().st_size, sha256=digest(path)))
    source_hashes = {str(path.relative_to(ROOT)): digest(path)
        for base in ('scripts', 'tests', 'configs', 'paper/drones_submission')
        for path in sorted((ROOT / base).rglob('*'))
        if path.suffix in ('.py', '.json', '.tex', '.bib', '.cls') and not path.name.startswith('._')}
    report = dict(campaign_states=states, indexed_files=len(entries), entries=entries,
        current_source_hashes=source_hashes,
        note='保存本次指定证据根的JSON/JSONL文件，含原始/无效尝试和派生副本；排除旁路_logs遥测和AppleDouble。索引不是通过判定，接纳仅6条部分开发，不含未授权资格/正式组。当前分析/论文源码哈希不是替换各尝试的源/运行时哈希；旧图形几何参考和公开存储不由此索引认证。')
    with args.out.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(indexed_files=len(entries), campaign_states=states), ensure_ascii=False))


if __name__ == '__main__':
    main()
