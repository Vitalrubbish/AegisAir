"""运行冻结的同位置不同速度接纳判定对照；不称闭环证据。"""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from marllib.run_c_recoverability_admission_gazebo import _admission_config
from swarm.recovery import RecoverabilityAdmissionCoordinator
from swarm.safety import DroneSnapshot


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    source = ROOT/'configs/admission_comparison_development_v1.json'
    raw = source.read_bytes()
    manifest = json.loads(raw)
    config = _admission_config(manifest['recoverability_admission'], rate_hz=20,
                              execution_tau_s=.7, command_feedforward_tau_s=.7)
    rows = []
    for name, geo in manifest['geometries'].items():
        for hv in ((1., 0., 0.), (-1., 0., 0.), (0., 1., 0.)):
            for fv in ((0., 0., 0.), (1., 0., 0.)):
                for geometry_only in (True, False):
                    c = RecoverabilityAdmissionCoordinator(config, geometry_only=geometry_only)
                    started = time.perf_counter()
                    c.step(step=30, snapshots={
                        2: DroneSnapshot(2, tuple(geo['reset_starts']['2']), velocity=fv),
                        3: DroneSnapshot(3, tuple(geo['reset_starts']['3']), velocity=hv),
                    }, base_goals={int(k): tuple(v) for k, v in geo['base_goals'].items()},
                        mission_change={'kind': 'fail_drone', 'drone': 2})
                    rows.append(dict(geometry=name, healthy_velocity=hv, failed_velocity=fv,
                                     method='geometry' if geometry_only else 'dynamic',
                                     elapsed_ms=1000*(time.perf_counter()-started), decision=c.summary()))
    result = dict(evidence_level='离线冻结状态判定，不是PX4闭环/准确率证据',
                  manifest_sha256=hashlib.sha256(raw).hexdigest(), rows=rows)
    (args.out/'manifest.json').write_bytes(raw)
    (args.out/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    (args.out/'COMPLETE').touch()
    print(json.dumps({'rows': len(rows), 'admitted': {m: sum(r['decision']['state']=='admitted' for r in rows if r['method']==m) for m in ('geometry','dynamic')}}))


if __name__ == '__main__':
    main()
