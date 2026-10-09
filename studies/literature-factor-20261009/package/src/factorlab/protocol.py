from pathlib import Path
import hashlib,json
from .common import digest,dump,code_hash,now,append

class ProtocolError(RuntimeError):pass

def registry():
    rows=[]
    for k in [5,10,20]:
        for a in [.2,.4]:
            rows.append({'candidate_id':f'NET_K{k:02d}_A{int(a*10):02d}','family':'cross_stock_empirical_lead_lag','leaders':k,'alpha':a,'complexity':k,'holding_sessions':5,'sign':1,'formula':'weighted mean of other stocks EWMA log returns; positive lag-one antisymmetric Pearson graph; expanding bimonthly refits','status':'registered'})
    for i in range(7,19):rows.append({'candidate_id':f'UNUSED_{i:02d}','status':'unused_reserved','p_one_sided':1.})
    return rows

def fingerprint(root):
    root=Path(root)
    files=['research/protocol.md','research/method.md','configs/research.yaml','configs/candidate_registry.json','data/data_manifest.json','data/history_fingerprints.json','data/industry_fingerprints.json','results/history_data_audit.json','research/exposure_ledger.json','requirements.lock','pyproject.toml']
    return {'files':{p:digest(root/p) for p in files},'code_hash':code_hash(root)}

def freeze_protocol(root):
    root=Path(root);p=root/'configs/protocol_freeze.json'
    if p.exists():raise ProtocolError('Protocol already frozen; do not overwrite history')
    if not (root/'configs/candidate_registry.json').exists():dump(root/'configs/candidate_registry.json',registry())
    exposed=json.loads((root/'research/exposure_ledger.json').read_text())
    record=fingerprint(root);record.update(frozen_utc=now(),performance_examined=bool(exposed.get('candidate_performance_before_protocol_freeze',False)))
    dump(p,record);append(root/'research/experiment_ledger.jsonl',{'event':'protocol_frozen','time':now(),'hash':digest(p),'configuration':record,'seed':20261009})
    return record

def check_protocol(root):
    root=Path(root);p=root/'configs/protocol_freeze.json'
    if not p.exists():raise ProtocolError('Freeze protocol before evaluating')
    frozen=json.loads(p.read_text());current=fingerprint(root)
    if current['files']!=frozen['files'] or current['code_hash']!=frozen['code_hash']:raise ProtocolError('Frozen data/config/code changed')
    return frozen

def cache_key(root,additional):
    return hashlib.sha256(json.dumps({'base':fingerprint(root),'additional':additional},sort_keys=True).encode()).hexdigest()

def verify_input_bytes(root):
    root=Path(root)
    for name in ['history_fingerprints','industry_fingerprints']:
        for record in json.loads((root/'data'/f'{name}.json').read_text()):
            path=root/record['path']
            if not path.is_file() or digest(path)!=record['sha256']:
                raise ProtocolError('Frozen input bytes missing or changed: '+record['path'])

def freeze_finalist(root):
    root=Path(root);check_protocol(root)
    metrics=json.loads((root/'results/metrics.json').read_text())
    selected=metrics.get('method_selected')
    if selected is None:raise ProtocolError('No evaluable candidate; final must remain unopened')
    if (root/'configs/finalist.json').exists():raise ProtocolError('Finalist already frozen')
    record={'candidate_id':selected,'validation_qualified':metrics['validation_qualified'],'selection_kind':'qualified' if metrics['validation_qualified'] else 'fallback','protocol_hash':digest(root/'configs/protocol_freeze.json'),'metrics_hash':digest(root/'results/metrics.json'),'code_hash':code_hash(root),'frozen_utc':now(),'final_start_in_cash':True,'final_sessions':['2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-28','2026-09-29','2026-09-30'],'release_authorized':False}
    record['freeze_hash']=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()
    dump(root/'configs/finalist.json',record);append(root/'research/experiment_ledger.jsonl',{'event':'finalist_frozen',**record});return record

def check_finalist(root):
    root=Path(root);check_protocol(root);p=root/'configs/finalist.json'
    if not p.exists():raise ProtocolError('No frozen finalist')
    r=json.loads(p.read_text());actual=dict(r);h=actual.pop('freeze_hash')
    if hashlib.sha256(json.dumps(actual,sort_keys=True).encode()).hexdigest()!=h:raise ProtocolError('Finalist hash mismatch')
    if r['code_hash']!=code_hash(root):raise ProtocolError('Code changed after finalist freeze')
    return r
