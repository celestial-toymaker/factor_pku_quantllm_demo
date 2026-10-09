"""Predeclared diagnostics; none can nominate an alternative method."""
from pathlib import Path
import numpy as np
import pandas as pd
from .statistics import hac_mean
from .features import rank,network_score
from .account import simulate

def industry_panel(root,dates,symbols):
    out=pd.DataFrame(None,index=dates,columns=symbols,dtype=object)
    for year in range(2018,2024):
        p=Path(root)/f'private/downloads/industry/{year}.csv'
        if not p.exists():continue
        df=pd.read_csv(p)
        if not (df.updateDate<=df.requested_date).all():raise ValueError('Industry snapshot contains future update')
        if not (pd.to_datetime(df.requested_date)<pd.Timestamp(f'{year}-01-01')).all():raise ValueError('Industry snapshot not available before year')
        for row in df.itertuples():
            s=row.code[3:]+('.SSE' if row.code.startswith('sh.') else '.SZSE')
            if s in out:out.loc[out.index.year==year,s]=row.industry
    return out

def fit_control_projection(score,control_panels):
    """Fit a score-on-controls projection on 2008–2017 only; no outcome regression."""
    ranked=rank(score);controls={k:rank(p) for k,p in control_panels.items()}
    y=ranked.loc['2008':'2017'].to_numpy().ravel()
    x=np.column_stack([np.ones(len(y))]+[p.loc['2008':'2017'].to_numpy().ravel() for p in controls.values()])
    valid=np.isfinite(y)&np.isfinite(x).all(axis=1)
    if valid.sum()<1000:return ranked*np.nan,{'available':False,'reason':'Insufficient training-side matched scores'}
    beta=np.linalg.lstsq(x[valid],y[valid],rcond=None)[0]
    residual=ranked-beta[0]
    for coefficient,p in zip(beta[1:],controls.values()):residual-=coefficient*p
    return residual,{'available':True,'training_start':'2008-01-01','training_end':'2017-12-31','observations':int(valid.sum()),'controls':list(controls),'coefficients':beta.tolist(),'outcomes_used':False,'refit_in_validation':False}

def ordering_diagnostics(score,labels,eligible,industry,residual_score):
    """Matched labels, fixed training projection, and descriptive within-sector IC."""
    records=[];sector_records=[];groups=[];year_records=[]
    common_index=score.index.intersection(labels.index)
    for d in common_index:
        mask=eligible.loc[d]&score.loc[d].notna()&labels.loc[d].notna()
        names=score.columns[mask]
        if len(names)<200:continue
        x=score.loc[d,names];y=labels.loc[d,names];g=industry.loc[d,names]
        coverage=float(g.notna().mean());ok=g.notna()
        sector_ic=None;partial_ic=None
        residual=residual_score.loc[d,names];good=residual.notna()
        if good.sum()>=200:partial_ic=residual[good].corr(y[good],method='spearman')
        within=[];counts=[]
        for sector in g.dropna().unique():
            z=g==sector
            if z.sum()>=10:
                rho=x[z].corr(y[z],method='spearman')
                sector_records.append({'date':str(d.date()),'sector':sector,'stocks':int(z.sum()),'rank_ic':rho})
                if pd.notna(rho):within.append(rho);counts.append(int(z.sum()))
        if within:sector_ic=float(np.average(within,weights=counts))
        records.append({'date':str(d.date()),'rank_ic':x.corr(y,method='spearman'),'matched_stocks':len(names),'industry_coverage':coverage,'within_sector_rank_ic':sector_ic,'training_residual_rank_ic':partial_ic})
        # Complete quantile ties; overlapping forward returns are never annualized.
        if x.nunique()>=5:
            cuts=x.quantile([.2,.4,.6,.8]).to_numpy()
            bucket=np.searchsorted(cuts,x.to_numpy(),side='left')+1
            groups.append({'date':str(d.date()),**{f'q{i}_forward_return':float(y.iloc[bucket==i].mean()) if (bucket==i).any() else None for i in range(1,6)}})
    daily=pd.DataFrame(records);sectors=pd.DataFrame(sector_records);group=pd.DataFrame(groups)
    if daily.empty:return {'available':False,'reason':'Fewer than 200 matched observations per date'},daily,sectors,group
    sector_summary={}
    for s,g in sectors.groupby('sector'):
        sector_summary[s]={'dates':len(g),'mean_rank_ic':g.rank_ic.mean(),'mean_stocks':g.stocks.mean()}
    for year,g in daily.groupby(pd.to_datetime(daily.date).dt.year):year_records.append({'year':int(year),'rank_ic':hac_mean(g.rank_ic),'dates':len(g)})
    residual=hac_mean(daily.training_residual_rank_ic.dropna())
    sector_neutral=hac_mean(daily.within_sector_rank_ic.dropna())
    positive_sectors=sum(x['dates']>=60 and x['mean_rank_ic']>0 for x in sector_summary.values())
    ic=hac_mean(daily.rank_ic)
    summary={'available':True,'rank_ic':ic,'rank_ir_unannualized':daily.rank_ic.mean()/daily.rank_ic.std(ddof=1),'rank_ic_quantiles':{str(q):daily.rank_ic.quantile(q) for q in [.05,.25,.5,.75,.95]},'industry_coverage_mean':daily.industry_coverage.mean(),'industry_coverage_min':daily.industry_coverage.min(),'within_sector_rank_ic':sector_neutral,'training_residual_rank_ic':residual,'sector_summary':sector_summary,'positive_sectors_min60dates':positive_sectors,'breadth_pass':bool(daily.industry_coverage.mean()>=.95 and positive_sectors>=3 and sector_neutral['mean'] is not None and sector_neutral['mean']>0),'yearly':year_records,'quintile_mean_forward_returns':{col:group[col].mean() for col in group if col!='date'},'group_returns_interpretation':'Overlapping next-open five-session adjusted-price labels, descriptive and unannualized; complete cutoff ties retained','unknown_industry_reason':'Annual snapshots may omit newly listed or newly classified members; missing groups remain unknown'}
    return summary,daily,sectors,group

def selected_diagnostics(root,c,score,p,e,raw,actions,calendar,folds,controls):
    from .evaluate import schedule_targets,measure,write_account
    scenarios={}
    for name,capital,friction,delay in [('friction_2x',1e6,2,1),('friction_3x',1e6,3,1),('delay_plus_one',1e6,1,2),('capacity_10m',1e7,1,1)]:
        records=[];active=[]
        for start,end in folds:
            dates=calendar[(calendar>=start)&(calendar<=end)]
            a=simulate(raw,schedule_targets(score,e,dates),dates,actions,capital,friction,delay)
            b=simulate(raw,schedule_targets(score,e,dates,True),dates,actions,capital,friction,delay)
            s,d=measure(a,b,capital);records.append(s);active.extend(d.net_active_return)
            write_account(root,'diagnostic_'+name+'_'+start,a,d)
        scenarios[name]={'folds':records,'pooled_active':hac_mean(active),'selection_permitted':False}
    # A prespecified second universe: higher-liquidity half. It has a 100-name
    # breadth floor and its own same-universe benchmark; no primary rank changes.
    from .features import target_weights
    liquid=p['amount'].rolling(20).median().where(e)
    transfer=e&liquid.ge(liquid.median(axis=1),axis=0)
    transfer_results=[];active=[]
    for start,end in folds:
        dates=calendar[(calendar>=start)&(calendar<=end)]
        tt=schedule_targets(score,transfer,dates,minimum=100)
        b=simulate(raw,schedule_targets(score,transfer,dates,True,minimum=100),dates,actions)
        a=simulate(raw,tt,dates,actions);s,d=measure(a,b);transfer_results.append(s);active.extend(d.net_active_return)
        write_account(root,'diagnostic_transfer_'+start,a,d)
    scenarios['transfer_higher_liquidity_half']={'folds':transfer_results,'pooled_active':hac_mean(active),'breadth_floor':100,'selection_permitted':False}
    placebo,_=network_score(p['close'].where(p['volume']>0),e,c['leaders'],c['alpha'],permuted=True)
    ablation={k:controls[k] for k in ['reversal5','momentum20','existing_equal_rank']};ablation['permuted_leader_graph']=placebo
    for name,sc in ablation.items():
        records=[];active=[]
        for start,end in folds:
            dates=calendar[(calendar>=start)&(calendar<=end)]
            b=simulate(raw,schedule_targets(score,e,dates,True),dates,actions)
            a=simulate(raw,schedule_targets(sc,e,dates),dates,actions);s,d=measure(a,b);records.append(s);active.extend(d.net_active_return)
            write_account(root,'ablation_'+name+'_'+start,a,d)
        scenarios['ablation_'+name]={'folds':records,'pooled_active':hac_mean(active),'selection_permitted':False}
    return scenarios
