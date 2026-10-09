"""Frozen historical batch and single-method final evaluation."""
from pathlib import Path
import json,os
import numpy as np
import pandas as pd
from .common import dump,digest,now,append
from .protocol import check_protocol,check_finalist,registry,cache_key,ProtocolError,verify_input_bytes
from .data import panels,assemble
from .features import eligibility,network_score,controls,target_weights,rank
from .outcomes import read_bars,calendar_labels
from .account import simulate
from .statistics import hac_mean,holm,select_method,overlap

FOLDS=[('2018-01-01','2019-12-31'),('2020-01-01','2021-12-31'),('2022-01-01','2023-12-31')]

def skeleton():
    return {'schema_version':1,'study_id':'literature-factor-20261009','created_utc':now(),'research_outcome':'BLOCKED_DATA','method_selected':None,'validation_qualified':False,'candidate_results':[],'final':None,'final_unavailable_reason':'No frozen evaluable method yet','release_authorized':False,'publication':'NOT_PUBLISHED','package_readiness':'INCOMPLETE'}

def validate_metrics(m):
    assert m['release_authorized'] is False and m['publication']=='NOT_PUBLISHED'
    selected=m['method_selected']
    if selected:
        row=next(x for x in m['candidate_results'] if x['candidate_id']==selected)
        assert row['evaluable'] and row['distinct']
        assert bool(row['validation_qualified'])==bool(m['validation_qualified'])
        if not m['validation_qualified'] and m.get('final',{}):assert m['research_outcome'] in {'NO_FACTOR_PASSED','BLOCKED_DATA'}
    if m.get('final') and m['final'].get('evaluated'):
        f=m['final'];assert f['candidate_id']==selected and f['sessions']==7
        assert f['first_date']=='2026-09-21' and f['last_date']=='2026-09-30'
        assert m['research_outcome']!='STRONG_CANDIDATE'
    json.dumps(m,allow_nan=False)
    return True

def schedule_targets(score,eligible,dates,benchmark=False,minimum=200):
    dates=pd.DatetimeIndex(dates);all_dates=score.index
    targets={}
    for pos in range(0,len(dates),5):
        i=all_dates.get_indexer([dates[pos]])[0]
        if i<1:continue
        signal=all_dates[i-1];e=eligible.loc[signal]
        if benchmark:
            w=pd.Series(0.,index=e.index)
            if e.sum()>=minimum:w.loc[e]=1/e.sum()
        else:w=target_weights(score.loc[signal],e,minimum=minimum)
        targets[signal]=w
    return targets

def measure(account,benchmark,capital=1e6,short=False):
    a=account['daily'].copy();b=benchmark['daily'];r=a.net_equity.pct_change();r.iloc[0]=a.net_equity.iloc[0]/capital-1
    br=b.net_equity.pct_change();br.iloc[0]=b.net_equity.iloc[0]/capital-1
    active=r-br;gross=a.gross_same_fills_equity.iloc[-1]/capital-1;net=a.net_equity.iloc[-1]/capital-1
    dd=a.net_equity/np.maximum.accumulate(np.r_[capital,a.net_equity])[1:]-1
    summary={'sessions':len(a),'first_date':a.date.iloc[0],'last_date':a.date.iloc[-1],'capital':capital,'net_return':net,'gross_same_fills_return':gross,'benchmark_net_return':b.net_equity.iloc[-1]/capital-1,'relative_compounded_return':a.net_equity.iloc[-1]/b.net_equity.iloc[-1]-1,'active':hac_mean(active),'max_drawdown':dd.min(),'mean_daily_turnover':a.turnover.mean(),'fees_cny':a.fees_cumulative.iloc[-1],'slippage_cny':a.slippage_cumulative.iloc[-1],'dividend_tax_reserve':a.dividend_tax_reserve.iloc[-1],'last_cash':a.cash.iloc[-1],'last_positions_value':a.positions_value.iloc[-1],'last_receivables':a.receivables.iloc[-1],'last_position_count':int(a.position_count.iloc[-1]),'failed_orders':len(account['failures']),'stale_position_days':int(a.stale_positions.sum()),'annualized':None if short else {'cagr':(1+net)**(252/len(a))-1,'sharpe_cash_zero':r.mean()/r.std(ddof=1)*np.sqrt(252) if r.std(ddof=1)>0 else None,'active_ir':active.mean()/active.std(ddof=1)*np.sqrt(252) if active.std(ddof=1)>0 else None}}
    a['net_return']=r;a['benchmark_return']=br;a['net_active_return']=active
    return summary,a

def write_account(root,name,account,daily=None):
    dest=Path(root)/'results/accounts'/name;dest.mkdir(parents=True,exist_ok=True)
    for key,df in account.items():(daily if key=='daily' and daily is not None else df).to_csv(dest/f'{key}.csv',index=False)

def historical(root):
    root=Path(root);frozen=check_protocol(root)
    verify_input_bytes(root)
    if (root/'results/metrics.json').exists():raise ProtocolError('Historical batch already recorded; preserve completed or blocked run')
    started=now();audit=json.loads((root/'results/history_data_audit.json').read_text());m=skeleton()
    candidates=[r for r in registry() if r['status']=='registered']
    if not audit['integrity_pass']:
        reasons=audit['material_findings'];m['blockers']=reasons
        for c in candidates:
            row={**c,'evaluable':False,'distinct':False,'validation_qualified':False,'mean_net_active':None,'turnover':None,'p_one_sided':None,'holm_p':1.,'unavailable_reason':'Material input/accounting integrity findings; no return calculation performed'}
            m['candidate_results'].append(row)
            append(root/'research/experiment_ledger.jsonl',{'event':'candidate_blocked','candidate_id':c['candidate_id'],'parent_id':None,'start':started,'end':now(),'command':'factorlab validate','seed':20261009,'split':'development/validation','protocol_hash':digest(root/'configs/protocol_freeze.json'),'data_fingerprint':digest(root/'data/history_fingerprints.json'),'decision':'ineligible; no performance exposed','result':'results/history_data_audit.json','metrics':None})
        m['final_unavailable_reason']='All six candidates are ineligible because essential accounting/data findings remain unresolved; fallback cannot manufacture an evaluable method.'
        dump(root/'results/metrics.json',m);validate_metrics(m);return m
    raw=read_bars(root,'validation');raw.date=pd.to_datetime(raw.date)
    cached=pd.read_parquet(root/'private/course/prices.parquet');cached=cached[cached.date<='2023-12-31']
    cal=pd.read_csv(root/'private/downloads/history/full_calendar.csv');calendar=pd.to_datetime(cal.loc[cal.is_trading_day.astype(str)=='1','calendar_date'])
    p=panels(cached,calendar);r=panels(raw,calendar);membership=pd.read_csv(root/'private/course/membership.csv')
    e=eligibility(p,membership)
    for k in ['tradestatus','isST']:r[k]=r[k].reindex(index=e.index,columns=e.columns)
    historical_known=e.index>=pd.Timestamp('2017-01-01')
    e.loc[historical_known]&=(r['tradestatus'].loc[historical_known]==1)&(r['isST'].loc[historical_known]==0)
    coverage=e.sum(axis=1);coverage.to_csv(root/'results/eligible_breadth.csv',header=['eligible_count'])
    cs=controls(p,e);actions=json.loads((root/'private/processed/history_actions.json').read_text())
    from .diagnostics import industry_panel,ordering_diagnostics,selected_diagnostics,fit_control_projection
    industry=industry_panel(root,p['close'].index,p['close'].columns)
    validation_labels=pd.concat([calendar_labels(p['open'],5,end,p['volume']>0).loc[start:end] for start,end in FOLDS])
    bs={};baseline={}
    for start,end in FOLDS:
        dates=calendar[(calendar>=start)&(calendar<=end)]
        btargets=schedule_targets(p['close'],e,dates,True)
        bs[start]=simulate(raw,btargets,dates,actions)
        ct=schedule_targets(cs['existing_equal_rank'],e,dates)
        baseline[start]=simulate(raw,ct,dates,actions)
        write_account(root,'benchmark_'+start,bs[start]);write_account(root,'existing_baseline_'+start,baseline[start])
    comparisons=[]
    for c in candidates:
        print('Evaluating',c['candidate_id'],flush=True);begin=now()
        append(root/'research/experiment_ledger.jsonl',{'event':'candidate_started','candidate_id':c['candidate_id'],'start':begin,'command':'factorlab validate','seed':20261009,'split':'2008–2017 development; three 2018–2023 validation folds','cache_key':cache_key(root,c)})
        score,fits=network_score(p['close'].where(p['volume']>0),e,c['leaders'],c['alpha'])
        private=root/'private/scores';private.mkdir(exist_ok=True);score.to_parquet(private/(c['candidate_id']+'.parquet'))
        dump(root/'results'/f"{c['candidate_id']}_refits.json",fits)
        folds=[];active_all=[];increment=[];turn=[];ics=[];overlap_stats={}
        development=calendar_labels(p['open'],5,'2017-12-31',p['volume']>0)
        dev_ic=score.loc['2008':'2017'].corrwith(development.loc['2008':'2017'].where(e.loc['2008':'2017']),axis=1,method='spearman')
        for start,end in FOLDS:
            dates=calendar[(calendar>=start)&(calendar<=end)];targets=schedule_targets(score,e,dates)
            a=simulate(raw,targets,dates,actions);summary,daily=measure(a,bs[start]);folds.append(summary)
            write_account(root,c['candidate_id']+'_'+start,a,daily)
            _,base_daily=measure(baseline[start],bs[start]);increment.extend((daily.net_return-base_daily.net_return).tolist())
            active_all.extend(daily.net_active_return.tolist());turn.extend(daily.turnover.tolist())
            labels=calendar_labels(p['open'],5,end,p['volume']>0).where(e)
            ic=score.loc[dates].corrwith(labels.loc[dates],axis=1,method='spearman');ics.extend(ic.dropna().tolist())
        for name,control in cs.items():
            o=overlap(score.loc['2018':'2023'],control.loc['2018':'2023'],e.loc['2018':'2023'])
            o['candidate_id']=c['candidate_id'];o['control_id']=name;comparisons.append(o)
            overlap_stats[name]={'median_absolute_rho':o.spearman.abs().median(),'rho_q05':o.spearman.quantile(.05),'rho_q95':o.spearman.quantile(.95),'mean_tail_jaccard':o.tail_jaccard.mean(),'matched_dates':int(o.spearman.notna().sum()),'mean_common_count':o.common_count.mean()}
        primary=hac_mean(active_all);distinct=all(x['median_absolute_rho']<.8 for x in overlap_stats.values() if pd.notna(x['median_absolute_rho']))
        distinct &= any(x['matched_dates']>0 for x in overlap_stats.values())
        residual,projection=fit_control_projection(score,{k:cs[k] for k in ['reversal5','momentum20','existing_equal_rank','liquidity_cv_abnormal']})
        ordering,ic_daily,sector_daily,groups=ordering_diagnostics(score.loc['2018':'2023'],validation_labels,e,industry,residual)
        ordering['control_projection']=projection
        ic_daily.to_csv(root/'results'/f"{c['candidate_id']}_ic_daily.csv",index=False)
        sector_daily.to_csv(root/'results'/f"{c['candidate_id']}_sector_ic.csv",index=False)
        groups.to_csv(root/'results'/f"{c['candidate_id']}_label_groups.csv",index=False)
        row={**c,'evaluable':True,'distinct':bool(distinct),'validation_qualified':False,'mean_net_active':primary['mean'],'turnover':float(np.mean(turn)),'primary':primary,'p_one_sided':primary['p_one_sided'],'hac_sensitivity':{str(l):hac_mean(active_all,l) for l in [5,20]},'folds':folds,'positive_folds':sum(x['active']['mean']>0 for x in folds),'incremental_over_existing':hac_mean(increment),'mature_daily_rank_ic':hac_mean(ics),'development_rank_ic':hac_mean(dev_ic.dropna()),'development_account':None,'development_account_reason':'Pre-2017 raw action/tradability ledger not obtained; only adjusted-price ordering diagnostic','overlap':overlap_stats,'ordering_diagnostics':ordering,'sector_breadth_available':ordering['available']}
        m['candidate_results'].append(row)
        scored=score.loc['2018':'2023'].notna().sum(axis=1)
        row['scored_breadth']={'min':int(scored.min()),'median':float(scored.median()),'max':int(scored.max()),'sessions_below_200':int((scored<200).sum()),'sessions':len(scored)}
        append(root/'research/experiment_ledger.jsonl',{'event':'candidate_completed','candidate_id':c['candidate_id'],'start':begin,'end':now(),'metrics':row,'decision':'await frozen Holm and selection rule'})
    adj=holm({r['candidate_id']:r['p_one_sided'] for r in m['candidate_results']})
    for row in m['candidate_results']:
        row['holm_p']=adj[row['candidate_id']]
        inc=row['incremental_over_existing'];lo=inc['ci95'][0] if inc['ci95'] else None
        ordering=row['ordering_diagnostics'];partial=ordering.get('training_residual_rank_ic',{}).get('mean')
        row['validation_qualified']=bool(row['evaluable'] and row['distinct'] and row['holm_p']<=.05 and row['positive_folds']>=2 and lo is not None and lo>0 and ordering.get('breadth_pass',False) and partial is not None and partial>0 and row['mature_daily_rank_ic']['mean']>0)
        row['qualification_failures']=[name for name,passed in {
            'integrity':row['evaluable'],'distinctness':row['distinct'],'Holm_5pct':row['holm_p']<=.05,
            'two_positive_folds':row['positive_folds']>=2,'incremental_account_HAC_lower_positive':lo is not None and lo>0,
            'sector_breadth':ordering.get('breadth_pass',False),'residual_ordering_positive':partial is not None and partial>0,
            'raw_ordering_positive':row['mature_daily_rank_ic']['mean'] is not None and row['mature_daily_rank_ic']['mean']>0}.items() if not passed]
    picked=select_method(m['candidate_results'])
    m.update(method_selected=picked['candidate_id'] if picked else None,validation_qualified=picked['validation_qualified'] if picked else False,research_outcome='PROMISING_NEEDS_NEW_DATA' if picked and picked['validation_qualified'] else ('NO_FACTOR_PASSED' if picked else 'BLOCKED_DATA'),unused_hypotheses=12,holm_slots=18)
    if picked:
        selected_score=pd.read_parquet(root/'private/scores'/f"{picked['candidate_id']}.parquet")
        print('Running frozen diagnostics for',picked['candidate_id'],flush=True)
        m['selected_diagnostics']=selected_diagnostics(root,picked,selected_score,p,e,raw,actions,calendar,FOLDS,cs)
        append(root/'research/experiment_ledger.jsonl',{'event':'fixed_diagnostics_completed','candidate_id':picked['candidate_id'],'time':now(),'selection_permitted':False,'metrics':m['selected_diagnostics']})
    pd.concat(comparisons,ignore_index=True).to_csv(root/'results/overlap_daily.csv',index=False)
    dump(root/'results/metrics.json',m);validate_metrics(json.loads((root/'results/metrics.json').read_text()))
    append(root/'research/experiment_ledger.jsonl',{'event':'method_selection','time':now(),'method_selected':m['method_selected'],'validation_qualified':m['validation_qualified'],'rule':'qualified first, otherwise best evaluable pooled validation mean net active; exact ties complexity, turnover, ID'})
    return m

def final_evaluation(root):
    root=Path(root);f=check_finalist(root)
    marker=root/'research/final_attempt.lock'
    fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as handle:handle.write(json.dumps({'started':now(),'candidate_id':f['candidate_id'],'freeze_hash':f['freeze_hash']}))
    append(root/'research/final_access.jsonl',{'event':'single_final_attempt_reserved','time':now(),'candidate_id':f['candidate_id']})
    from .provider import acquire
    m=json.loads((root/'results/metrics.json').read_text())
    try:
        acquire(root,'final');audit=assemble(root,'final')
    except Exception as exc:
        m.update(research_outcome='BLOCKED_DATA',final={'evaluated':False,'candidate_id':f['candidate_id'],'reason':f'Independent acquisition/audit failed: {type(exc).__name__}: {exc}'})
        dump(root/'results/metrics.json',m)
        append(root/'research/experiment_ledger.jsonl',{'event':'final_acquisition_blocked','time':now(),'reason':m['final']['reason']})
        return m
    if not audit['integrity_pass']:
        m.update(research_outcome='BLOCKED_DATA',final={'evaluated':False,'candidate_id':f['candidate_id'],'reason':'Independent final download failed data integrity','findings':audit['material_findings']})
        dump(root/'results/metrics.json',m);return m
    raw=read_bars(root,'final',f['freeze_hash']);raw.date=pd.to_datetime(raw.date)
    cal=pd.read_csv(root/'private/downloads/final/calendar.csv');calendar=pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_trading_day.astype(str)=='1','calendar_date']))
    actual=[str(x.date()) for x in calendar if pd.Timestamp('2026-09-20')<=x<=pd.Timestamp('2026-10-07')]
    if actual!=f['final_sessions']:raise ValueError('Official seven-session final calendar mismatch')
    p=panels(raw,calendar);reference=raw.pivot(index='date',columns='symbol',values='preclose').reindex(calendar)
    ret=np.log(p['close']/reference).replace([np.inf,-np.inf],np.nan).where((p['tradestatus']==1)&(p['tradestatus'].shift(1)==1))
    adjusted=np.exp(ret.fillna(0).cumsum()).where(p['close'].notna())
    members=pd.read_csv(root/'private/downloads/final/membership.csv')
    e=pd.DataFrame(False,index=calendar,columns=adjusted.columns)
    for d,g in members.groupby('requested_date'):
        syms=[s[3:]+('.SSE' if s.startswith('sh.') else '.SZSE') for s in g.code]
        e.loc[pd.Timestamp(d),syms]=True
    e &= adjusted.notna().cumsum().ge(252)&p['amount'].rolling(20).median().ge(2e7)&p['isST'].eq(0)&p['tradestatus'].eq(1)
    e &= np.array([s.startswith(('000','001','002','003','600','601','603','605')) for s in e.columns])
    c=next(x for x in registry() if x['candidate_id']==f['candidate_id'])
    # Only the September refit is needed. The fit uses history through August 31.
    from .features import graph_weights
    fit_end=pd.Timestamp('2026-08-31');nodes=e.loc[fit_end].to_numpy(bool);w=np.zeros((len(nodes),len(nodes)))
    history=ret.loc['2008-01-01':fit_end]
    w[np.ix_(nodes,nodes)]=graph_weights(history.to_numpy()[:,nodes],np.ones(nodes.sum(),bool),c['leaders'])
    ew=ret.ewm(alpha=c['alpha'],adjust=False,ignore_na=False,min_periods=5).mean().where(ret.notna())
    score=pd.DataFrame(np.nan,index=calendar,columns=e.columns)
    for d in e.index[e.any(axis=1)]:
        x=ew.loc[d].to_numpy();avail=np.isfinite(x)&e.loc[d].to_numpy(bool);mass=avail.astype(float)@w
        score.loc[d]=np.divide(np.where(avail,x,0.)@w,mass,out=np.full(len(nodes),np.nan),where=mass>=.8)
    dates=pd.to_datetime(f['final_sessions']);actions=json.loads((root/'private/processed/final_actions.json').read_text())
    targets=schedule_targets(score,e,dates);bt=schedule_targets(score,e,dates,True)
    diagnostics={};daily_records=None
    for name,capital,friction,delay in [('base',1e6,1,1),('friction_2x',1e6,2,1),('friction_3x',1e6,3,1),('delay_plus_one',1e6,1,2),('capacity_10m',1e7,1,1)]:
        a=simulate(raw,targets,dates,actions,capital,friction,delay);b=simulate(raw,bt,dates,actions,capital,friction,delay)
        measured,daily=measure(a,b,capital,True);diagnostics[name]=measured
        if name=='base':daily_records=daily.to_dict('records')
        write_account(root,'final_'+name,a,daily);write_account(root,'final_benchmark_'+name,b)
    adjusted_open=adjusted*p['open']/p['close']
    labels=calendar_labels(adjusted_open,5,'2026-09-30',(p['volume']>0)&p['tradestatus'].eq(1)).where(e)
    signal_dates=pd.DatetimeIndex([pd.Timestamp('2026-09-18')]+list(dates))
    ic=score.loc[signal_dates].corrwith(labels.loc[signal_dates],axis=1,method='spearman').dropna()
    liquid=p['amount'].rolling(20).median().where(e);transfer=e&liquid.ge(liquid.median(axis=1),axis=0)
    a=simulate(raw,schedule_targets(score,transfer,dates,minimum=100),dates,actions)
    b=simulate(raw,schedule_targets(score,transfer,dates,True,minimum=100),dates,actions)
    measured,daily=measure(a,b,short=True);diagnostics['transfer_higher_liquidity_half']=measured
    write_account(root,'final_transfer',a,daily);write_account(root,'final_benchmark_transfer',b)
    m['final']={'evaluated':True,'candidate_id':f['candidate_id'],'sessions':7,'first_date':'2026-09-21','last_date':'2026-09-30','diagnostics':diagnostics,'daily':daily_records,'rank_ic':hac_mean(ic),'mature_ic_dates':list(ic.index.astype(str)),'annualized_headlines_suppressed':True,'independent_untouched_sample':False,'reason':'Seven sessions; partly overlaps prior student exposure; no strong-candidate inference'}
    m['final_unavailable_reason']=None
    m['research_outcome']='NO_FACTOR_PASSED' if not f['validation_qualified'] else ('PROMISING_NEEDS_NEW_DATA' if diagnostics['base']['active']['mean']>0 else 'INCONCLUSIVE')
    dump(root/'results/metrics.json',m);validate_metrics(json.loads((root/'results/metrics.json').read_text()))
    append(root/'research/experiment_ledger.jsonl',{'event':'single_final_completed','time':now(),'candidate_id':f['candidate_id'],'outcome':m['research_outcome'],'metrics_path':'results/metrics.json'})
    return m
