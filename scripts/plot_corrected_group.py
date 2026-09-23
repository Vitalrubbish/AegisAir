"""完整四机组的下中位裕度与最低裕度轨迹，以及全部 seed 的计时。"""
import argparse
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    report = json.loads((args.root/'verified_analysis_v1.json').read_text())
    rows = json.loads((args.root/'results.json').read_text())
    settings = json.loads((args.root/'run_settings.json').read_text())
    if report['state']!='COMPLETED' or report['trials_verified']!=20 or not report['complete']:
        raise ValueError('不能把资格组或未完成正式组绘为二十 seed 结果')
    args.out.mkdir(parents=True,exist_ok=False)
    plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False})
    fig, axes = plt.subplots(2,2,figsize=(9,7.2),layout='constrained')
    colors = ['#186A8C','#A45430','#668246','#77558E']
    provenance = {}
    for column,(role,title) in enumerate((('lower_median','Lower-median margin'),('lowest_margin','Lowest margin'))):
        seed = report['representative_seeds'][role]
        source = next(item for item in report['sources'] if item['seed']==seed)
        row = next(item for item in rows if item['seed']==seed)
        path = Path(source['summary']).parent/row['trajectory']
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=source['trajectory_sha256']:
            raise ValueError('代表轨迹哈希变化')
        records = [json.loads(line) for line in raw.splitlines()]
        axis = axes[0,column]
        for drone,color in zip(settings['drone_ids'],colors):
            positions = np.asarray([record['drones'][str(drone)]['pos'] for record in records])
            axis.plot(positions[:,0],positions[:,1],color=color,label='UAV '+str(drone),linewidth=1.1)
            axis.scatter(*positions[0,:2],s=20,color=color)
            axis.scatter(*settings['base_goals'][str(drone)][:2],marker='*',s=80,color=color)
        axis.set(xlabel='x [m]',ylabel='y [m]',title=f'{title}: seed {seed}',aspect='equal',
                 xlim=(-3.6,3.6),ylim=(-3.6,3.6))
        axis.legend(loc='upper center',ncol=2,frameon=False,fontsize=8)
        axis.grid(alpha=.15)
        provenance[role] = source
    ordered = sorted(rows,key=lambda row:row['seed'])
    x = np.arange(len(ordered))
    for axis,key,title in ((axes[1,0],'p99','Episode RA P99'),(axes[1,1],'max','Episode RA maximum')):
        y = [row['ra_solve_latency_summary_ms'][key] for row in ordered]
        axis.scatter(x,y,s=24,color='#186A8C')
        axis.set_xticks(x[::2],[str(row['seed']) for row in ordered[::2]],rotation=60)
        axis.set(xlabel='Simulator seed',ylabel='Latency [ms]',title=title)
        if key=='max':
            axis.axhline(50,color='#A45430',linestyle='--',linewidth=.8,label='50-ms period')
            axis.legend(frameon=False,fontsize=8)
        axis.grid(axis='y',alpha=.15)
    fig.savefig(args.out/'fig_four_uav_corrected.png',dpi=300)
    plt.close(fig)
    provenance['analysis_sha256'] = hashlib.sha256((args.root/'verified_analysis_v1.json').read_bytes()).hexdigest()
    provenance['note'] = '沿用按最低裕度排序的下中位与最差 seed 选择规则；散点保留全部二十 seed，不声称通用四机能力。'
    (args.out/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
