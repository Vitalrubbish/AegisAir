"""仅完整开发网格允许按既定词典序选阈值并写新测试配置。"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from run_corrected_trigger_comparison import settings_for

THRESHOLDS={'AEGIS_HOCBF_V4_DISTANCE':'recovery_distance_threshold_m',
            'AEGIS_HOCBF_V4_TTC':'recovery_ttc_threshold_s'}


def score(rows,threshold):
    if not rows or any(not row['infrastructure_valid'] or not math.isfinite(row['min_rho']) or not math.isfinite(row['mean_control_effort']) for row in rows):
        raise ValueError('无完整有限的有效开发结果')
    return (sum(row['collision'] for row in rows),sum(not row['mission_complete'] for row in rows),
            sum(row['min_rho']<=0 for row in rows),sum(row['mean_control_effort'] for row in rows)/len(rows),threshold)


def verified_grid(root,grid):
    settings=settings_for(grid)
    if json.loads((root/'run_settings.json').read_text())!=settings or json.loads((root/'status.json').read_text())['state']!='COMPLETED':
        raise ValueError('开发网格未完整完成或配置变化，不挑选赢家')
    rows=[]
    for scenario in dict.fromkeys(trial['scenario_id'] for trial in settings['trials']):
        folder=root/scenario
        group=dict(settings,trials=[trial for trial in settings['trials'] if trial['scenario_id']==scenario])
        if json.loads((folder/'run_settings.json').read_text())!=group:
            raise ValueError('开发子组配置不一致')
        state=json.loads((folder/'status.json').read_text())
        actual=json.loads((folder/'results.json').read_text())
        expected=[(trial['trial_id'],method,trial['seed']) for trial in group['trials'] for method in trial['condition_order']]
        if state['state']!='COMPLETED' or [(row['trial_id'],row['method'],row['seed']) for row in actual]!=expected:
            raise ValueError('开发条件缺失、重复或乱序')
        for row in actual:
            attempts=[a for a in state['attempts'] if a['state']=='VALID' and a['label'].startswith(row['trial_id']+'_'+row['method']+'_attempt')]
            if len(attempts)!=1:
                raise ValueError('原始结果归属不唯一')
            summary=Path(attempts[0]['summary'])
            if json.loads(summary.read_text())['trials']!=[row] or hashlib.sha256((summary.parent/row['trajectory']).read_bytes()).hexdigest()!=row['trajectory_sha256']:
                raise ValueError('原始摘要或轨迹哈希不一致')
        rows.extend(actual)
    return settings,rows


def choose(campaigns):
    if len(campaigns)!=3:
        raise ValueError('必须完成三个开发网格')
    selected={}
    for method,key in THRESHOLDS.items():
        candidates=[]
        for grid,(settings,rows) in enumerate(campaigns,1):
            subset=[row for row in rows if row['method']==method]
            if len(subset)!=6 or len({row['seed'] for row in subset})!=6:
                raise ValueError('每阈值必须恰有原定六个 seed')
            threshold=settings['methods'][method][key]
            candidates.append(dict(grid=grid,threshold=threshold,score=score(subset,threshold)))
        best=min(candidates,key=lambda candidate:candidate['score'])
        selected[method]=dict(best=best,candidates=candidates)
    return selected


def build_test(campaigns,roots):
    selection=choose(campaigns)
    test=copy.deepcopy(campaigns[0][0])
    for method,key in THRESHOLDS.items():
        test['methods'][method][key]=selection[method]['best']['threshold']
    methods=list(test['methods'])
    scenarios=list(dict.fromkeys(trial['scenario_id'] for trial in test['trials']))
    test['trials']=[dict(trial_id=f'trigtest_{index+1:02d}',scenario_id=scenarios[index//5],seed=22001+index,
        condition_order=methods[index%4:]+methods[:index%4]) for index in range(15)]
    test.update(experiment='trigger_test',phase='独立测试 seed；开发阈值已封存，不再搜索',
        parent_protocol_id='aegisair-trigger-comparison-test-corrected-v2',
        development_roots=[str(root.resolve()) for root in roots],
        development_settings_sha256=[hashlib.sha256((root/'run_settings.json').read_bytes()).hexdigest() for root in roots],
        stopping_rule='完整配对后碰撞停止本几何后续 seed；非正裕度/未完成保留。基础设施同条件重试最多三次后诊断；安全链疑点暂停。不改变选定阈值。')
    return test,selection


def load_frozen_test(path):
    frozen=json.loads(path.read_text())
    roots=[Path(root) for root in frozen['development_roots']]
    if len(roots)!=3:
        raise ValueError('必须有完整三组开发来源')
    campaigns=[verified_grid(root,grid) for grid,root in enumerate(roots,1)]
    expected,selection=build_test(campaigns,roots)
    if frozen!=expected or json.loads((path.parent/'selection.json').read_text())!=json.loads(json.dumps(selection)):
        raise ValueError('选阈规则、配置或封存选择记录不一致')
    return frozen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grid-roots',nargs=3,type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    campaigns=[verified_grid(root,grid) for grid,root in enumerate(args.grid_roots,1)]
    test,selection=build_test(campaigns,args.grid_roots)
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2))
    (args.out/'run_settings.json').write_text(json.dumps(test,ensure_ascii=False,indent=2))
    print(json.dumps(selection,ensure_ascii=False))


if __name__=='__main__':
    main()
