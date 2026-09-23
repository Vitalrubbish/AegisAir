"""C1 修订比较：区分基线结局、主方法失败与基础设施问题。"""
import math

PRIMARY = 'AEGIS_HOCBF_V4'


def paired_decision(rows, expected_methods):
    methods = [r['method'] for r in rows]
    if len(methods)!=len(expected_methods) or set(methods)!=set(expected_methods):
        raise ValueError('配对不完整或存在重复条件')
    if any(not r.get('infrastructure_valid', False) for r in rows):
        return 'RETRY_INFRASTRUCTURE'
    if any(r.get('safety_bypass_count',0)>0 or
           r.get('published_command_mismatch_count',0)>0 or
           r.get('published_command_constraint_unknown_count',0)>0 for r in rows):
        return 'STOP_SAFETY_CHAIN'
    main = next(r for r in rows if r['method']==PRIMARY)
    rho = main.get('min_rho')
    if (main['collision'] or not main['mission_complete'] or rho is None or
            not math.isfinite(rho) or rho<=0):
        return 'STOP_PRIMARY_FAILURE'
    return 'CONTINUE'
