import argparse,datetime,json
from pathlib import Path
from nhl_data import get_schedule,get_bundle,enrich_deployment
from engine import run_slate
from gate_executor import execute_gate_matrix
from core_publication import publish_verified_core
p=argparse.ArgumentParser();p.add_argument('--date',default=datetime.datetime.now(datetime.timezone.utc).date().isoformat());p.add_argument('--mode',choices=['projected','confirmed'],default='projected');p.add_argument('--history',type=int,default=8);p.add_argument('--out',default='runs');a=p.parse_args()
games=get_schedule(a.date);bundles=[enrich_deployment(get_bundle(g),a.mode) for g in games];report=run_slate(bundles,a.mode,a.history);report['slateDate']=a.date
report['fullGateMatrix']=execute_gate_matrix(report)
# The full-pool sequential matrix, not legacy G18 trace labels, is the publication authority.
matrix=report['fullGateMatrix']
survivors={(str(p['gameId']),str(p['playerId'])) for p in matrix['playerResults'] if p['survived']}
core=(report.get('coreOutput') or {}).get('core') or []
core_keys={(str(p.get('gameId')),str(p.get('playerId'))) for p in core}
matrix_valid=(bool(core) and len(core_keys)==len(core)
              and core_keys.issubset(survivors)
              and matrix['playersEvaluated']==sum(len(g.get('players',[])) for g in report.get('games',[]))
              and matrix['playersWithMissingEvidence']==0)
if not matrix_valid:
    report.setdefault('validationSummary',{})['finalPlayerPathsCertified']=False
    report['validationSummary']['status']='NOT CERTIFIED — COMPLETE FULL-POOL GATE MATRIX REQUIRED'
    report.setdefault('coreOutput',{})['core']=[]
    report['coreOutput']['status']='NO PUBLISHABLE CORE — GATE EXECUTION INCOMPLETE'
    report['gateExecutionCertification']={'certified':False,'reason':'Missing or unpassed sequential gate evidence across the eligible player pool'}
else:
    report['gateExecutionCertification']={'certified':True,'reason':'All evaluated skaters have complete sequential gate dispositions; Core members survived'}

out=Path(a.out);out.mkdir(parents=True,exist_ok=True);path=out/f'nhl_blender_{a.date}_{a.mode}.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8');publication=publish_verified_core(report,'state')
print(f'{path} | games={len(games)} | run={report["runId"]} | publication={publication}')
