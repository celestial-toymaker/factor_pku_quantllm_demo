import numpy as np
import pandas as pd
from scipy.stats import norm

def hac_mean(values, lag=10):
    x=np.asarray(values,dtype=float);x=x[np.isfinite(x)];n=len(x)
    if n<max(20,lag+2):return {'n':n,'mean':float(x.mean()) if n else None,'se':None,'p_one_sided':None,'ci95':None,'reason':'Too few dates for declared HAC inference'}
    mean=x.mean();u=x-mean;v=u@u/n
    for k in range(1,lag+1):v+=2*(1-k/(lag+1))*(u[k:]@u[:-k])/n
    se=np.sqrt(max(v,0)/n)
    p=float(norm.sf(mean/se)) if se>0 else (0. if mean>0 else 1.)
    return {'n':n,'mean':float(mean),'se':float(se),'p_one_sided':p,'ci95':[float(mean-1.96*se),float(mean+1.96*se)],'lag':lag}

def holm(pvalues, slots=18):
    names=list(pvalues);p=[pvalues[k] if pvalues[k] is not None else 1. for k in names]
    if len(p)>slots:raise ValueError('Hypothesis budget exceeded')
    p=np.array(p+[1.]*(slots-len(p)));order=np.argsort(p,kind='stable');adj=np.empty(slots);peak=0.
    for rank,i in enumerate(order):peak=max(peak,(slots-rank)*p[i]);adj[i]=min(peak,1.)
    return {name:float(adj[i]) for i,name in enumerate(names)}

def select_method(candidates):
    eligible=[r for r in candidates if r['evaluable'] and r['distinct'] and r.get('mean_net_active') is not None and np.isfinite(r['mean_net_active'])]
    qualified=[r for r in eligible if r['validation_qualified']]
    pool=qualified or eligible
    if not pool:return None
    return sorted(pool,key=lambda r:(-r['mean_net_active'],r['complexity'],r['turnover'],r['candidate_id']))[0]

def overlap(score, control, eligibility):
    rows=[]
    for d in score.index:
        pair=pd.concat([score.loc[d],control.loc[d]],axis=1).dropna()
        pair=pair.loc[eligibility.loc[d].reindex(pair.index).fillna(False)]
        rho=pair.iloc[:,0].corr(pair.iloc[:,1],method='spearman') if len(pair)>=200 and pair.iloc[:,0].nunique()>1 and pair.iloc[:,1].nunique()>1 else np.nan
        event=pair[pair.iloc[:,1]!=0]
        erho=event.iloc[:,0].corr(event.iloc[:,1],method='spearman') if len(event)>=20 and event.iloc[:,1].nunique()>1 else np.nan
        if len(pair) and pair.iloc[:,0].nunique()>1 and pair.iloc[:,1].nunique()>1:
            a=set(pair.index[pair.iloc[:,0]>=pair.iloc[:,0].quantile(.8)]);b=set(pair.index[pair.iloc[:,1]>=pair.iloc[:,1].quantile(.8)])
            tail=len(a&b)/len(a|b)
        else:tail=np.nan
        rows.append({'date':str(d.date()),'common_count':len(pair),'spearman':rho,'event_spearman':erho,'tail_jaccard':tail})
    return pd.DataFrame(rows)
