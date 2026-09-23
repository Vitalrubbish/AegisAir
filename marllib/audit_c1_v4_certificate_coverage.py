#!/usr/bin/env python3
"""Freeze an empirical PB execution envelope and audit strict-slack coverage."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np

DT, TAU, ALPHA, MU, AMAX, D = 0.05, 0.70, 0.5, 2.0, 2.0, 0.8

def rows(root: Path):
    for path in sorted(root.glob("*AEGIS_HOCBF_V4/*.jsonl")):
        if path.name.startswith("._"):
            continue
        yield path, [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]

def affine(q):
    p2,p3,v2,v3=q; r=p2[:2]-p3[:2]; v=v2[:2]-v3[:2]; dist=float(np.linalg.norm(r)); n=r/dist
    radial=float(n@v); closing=min(radial,0.0); h=dist-D-closing**2/(2*MU)
    if closing < 0:
        coeff=-closing/MU; c=np.r_[coeff*n,-coeff*n]; tang=(float(v@v)-radial**2)/dist
        return c, -ALPHA*h-(radial+coeff*tang)
    return np.zeros(4), 0.0 if radial+ALPHA*h >= 0 else 1.0

def q(row):
    d=row['drones']; return tuple(np.asarray(d[str(i)][key],float) for key in ('pos','pos','v_actual','v_actual') for i in [])

def state(row):
    d=row['drones']; return (np.asarray(d['2']['pos'],float),np.asarray(d['3']['pos'],float),np.asarray(d['2']['v_actual'],float),np.asarray(d['3']['v_actual'],float))

def main():
 p=argparse.ArgumentParser(); p.add_argument('--calibration',type=Path,required=True); p.add_argument('--evaluate',type=Path,action='append',required=True); p.add_argument('--out',type=Path,required=True); a=p.parse_args()
 if a.out.exists(): p.error('refusing to overwrite audit')
 alpha=1-np.exp(-DT/TAU); beta=DT-TAU*alpha; deviations=[]
 for _,trace in rows(a.calibration):
  for now,nxt in zip(trace,trace[1:]):
   if 'v_requested' not in now['drones']['2']: continue
   p2,p3,v2,v3=state(now); u2=np.asarray(now['drones']['2']['v_requested'][:2]); u3=np.asarray(now['drones']['3']['v_requested'][:2])
   pp2=p2.copy(); pp3=p3.copy(); vv2=v2.copy(); vv3=v3.copy(); pp2[:2]+=v2[:2]*DT+beta*(u2-v2[:2]); pp3[:2]+=v3[:2]*DT+beta*(u3-v3[:2]); vv2[:2]=(1-alpha)*v2[:2]+alpha*u2; vv3[:2]=(1-alpha)*v3[:2]+alpha*u3
   c,b=affine((p2,p3,v2,v3)); act=state(nxt); ca,ba=affine(act); x=np.r_[now['drones']['2']['a_safe'],now['drones']['3']['a_safe']]
   deviations.append(abs(float(ca@x-ba)-float(c@x-b)))
 delta=1.10*max(deviations)
 report=[]
 for root in a.evaluate:
  for path,trace in rows(root):
   vals=[]
   for r in trace:
    if r['drones']['2']['recovery_active']:
     c,b=affine(state(r)); eta=float(AMAX*np.abs(c).sum()-b); vals.append(eta-delta)
   if vals: report.append({'trajectory':str(path),'recovery_steps':len(vals),'min_certificate_margin':min(vals),'covered_steps':sum(x>0 for x in vals)})
 total=sum(x['recovery_steps'] for x in report); covered=sum(x['covered_steps'] for x in report)
 a.out.write_text(json.dumps({'definition':'empirical one-step PB affine-constraint deviation envelope; not a deterministic bound','calibration_trajectories':5,'delta_B':delta,'calibration_max_deviation':max(deviations),'evaluation':report,'coverage':{'steps':total,'covered_steps':covered,'fraction':covered/total if total else None}},ensure_ascii=False,indent=2)+'\n')
 print(a.out)
if __name__=='__main__': main()
