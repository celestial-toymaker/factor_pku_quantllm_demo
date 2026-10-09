"""Point-in-time feature calculations. This module has no outcome reader."""
from __future__ import annotations
import numpy as np
import pandas as pd

def rank(s):
    return s.rank(axis=1,method='average',pct=True)

def eligibility(panel, membership, raw_status=None, minimum_history=252, minimum_amount=20_000_000):
    close=panel['close'];dates=close.index;symbols=close.columns
    mask=pd.DataFrame(False,index=dates,columns=symbols)
    for row in membership.itertuples():
        if row.symbol in symbols:
            mask.loc[(dates>=pd.Timestamp(row.start))&(dates<=pd.Timestamp(row.end)),row.symbol]=True
    main=np.array([str(s).startswith(('000','001','002','003','600','601','603','605')) for s in symbols])
    history=close.notna().cumsum()>=minimum_history
    liquid=panel['amount'].rolling(20,min_periods=20).median()>=minimum_amount
    # Only signal-date tradability is used. Execution-day rejection occurs in the account.
    mask &= history & liquid & (panel['volume']>0) & main
    if raw_status is not None:
        mask &= (raw_status['isST']==0)&(raw_status['tradestatus']==1)
    return mask

def graph_weights(returns, eligible, leaders=10, min_pairs=200):
    """C_ij = corr(r_i,t-1, r_j,t), pairwise calendar-aligned observations."""
    a=returns[:-1];b=returns[1:]
    ma=np.isfinite(a).astype(float);mb=np.isfinite(b).astype(float)
    a=np.nan_to_num(a);b=np.nan_to_num(b)
    n=ma.T@mb;sa=a.T@mb;sb=ma.T@b
    cov=a.T@b-np.divide(sa*sb,n,out=np.zeros_like(n),where=n>0)
    va=(a*a).T@mb-np.divide(sa*sa,n,out=np.zeros_like(n),where=n>0)
    vb=ma.T@(b*b)-np.divide(sb*sb,n,out=np.zeros_like(n),where=n>0)
    with np.errstate(invalid='ignore',divide='ignore'):
        c=cov/np.sqrt(np.maximum(va,0)*np.maximum(vb,0))
    valid=(n>=min_pairs)&(n.T>=min_pairs)&np.isfinite(c)&np.isfinite(c.T)&(c>0)
    w=np.where(valid,np.maximum(c-c.T,0),0)
    w[~eligible,:]=0;w[:,~eligible]=0;np.fill_diagonal(w,0)
    # Equal edge weights at the kth boundary are all retained; never use ticker order to split ties.
    for j in range(w.shape[1]):
        positive=w[:,j][w[:,j]>0]
        if len(positive)>leaders:
            threshold=np.sort(positive)[-leaders];w[w[:,j]<threshold,j]=0
    totals=w.sum(axis=0)
    return np.divide(w,totals,out=np.zeros_like(w),where=totals>0)

def network_score(close, eligible, leaders, alpha, start='2008-01-01', min_pairs=200, permuted=False):
    """Expanding-window bimonthly refits, through the PREVIOUS session only."""
    ret=np.log(close/close.shift(1)).replace([np.inf,-np.inf],np.nan)
    ret=ret.where(close.notna()&close.shift(1).notna())
    ew=ret.ewm(alpha=alpha,adjust=False,ignore_na=False,min_periods=5).mean()
    ew=ew.where(ret.notna())
    out=pd.DataFrame(np.nan,index=close.index,columns=close.columns)
    w=None;previous_block=None;fits=[]
    for t,d in enumerate(close.index):
        block=(d.year,(d.month-1)//2)
        if block!=previous_block:
            hist=ret.iloc[:t];hist=hist.loc[hist.index>=pd.Timestamp(start)]
            if len(hist)>=min_pairs+1:
                e=eligible.iloc[max(t-1,0)].to_numpy(bool)
                local=graph_weights(hist.to_numpy()[:,e],np.ones(e.sum(),dtype=bool),leaders,min_pairs)
                if permuted:
                    # Fixed seeded leader-identity placebo. Never a selectable candidate.
                    local=local[np.random.default_rng(20261009).permutation(len(local))]
                    np.fill_diagonal(local,0)
                    totals=local.sum(axis=0)
                    local=np.divide(local,totals,out=np.zeros_like(local),where=totals>0)
                w=np.zeros((len(e),len(e)));w[np.ix_(e,e)]=local
                fits.append({'date':str(d.date()),'training_start':str(hist.index[0].date()),'training_end':str(hist.index[-1].date()),'edges':int((w>0).sum())})
            previous_block=block
        if w is not None:
            x=ew.iloc[t].to_numpy();available=np.isfinite(x)&eligible.iloc[t].to_numpy(bool)
            mass=available.astype(float)@w
            s=np.where(available,x,0.)@w
            # Do not create a score when most original leader weight is missing.
            s=np.divide(s,mass,out=np.full_like(s,np.nan),where=mass>=.8)
            s[~eligible.iloc[t].to_numpy(bool)]=np.nan;out.iloc[t]=s
    return out,fits

def controls(panel, eligible):
    c,o,h,l,v,a=[panel[k] for k in ['close','open','high','low','volume','amount']]
    r=c/c.shift(1)-1;gap=o/c.shift(1)-c/o
    reversal=-(c-c.shift(4))/c
    pos=(c-c.rolling(20).min())/(c.rolling(20).max()-c.rolling(20).min())
    result={
      'reversal5':-(c/c.shift(5)-1),
      'momentum20':c/c.shift(20)-1,
      'weak_close':-(c-l)/(h-l),
      'gap_diff4':gap.rolling(4).sum(),
      'gap_diff4_amount':gap.rolling(4).sum()*rank(a),
      'pv_anti5':-c.rolling(5).corr(v),
      'rev4_amount_highpos':reversal*rank(a)*pos,
      'strong_close_event':((c-l)/(h-l)).where(r>=.095,0.0),
      'liquidity_cv_abnormal':-(rank(a.rolling(20).std()/a.rolling(20).mean())+rank(a.rolling(5).mean()/a.rolling(20).mean()))
    }
    result={k:s.replace([np.inf,-np.inf],np.nan).where(eligible) for k,s in result.items()}
    result['existing_equal_rank']=sum(rank(s)-.5 for k,s in result.items() if k!='strong_close_event')/8
    return result

def target_weights(score, eligible, fraction=.2, max_weight=.05, minimum=200):
    s=score[eligible & score.notna()]
    if len(s)<minimum or s.nunique()<5:return pd.Series(0.,index=score.index)
    cutoff=s.quantile(1-fraction)
    chosen=s.index[s>=cutoff]
    # Includes complete cutoff tie; constant/sparse scores cannot manufacture quintiles.
    ans=pd.Series(0.,index=score.index);ans.loc[chosen]=min(1/len(chosen),max_weight)
    return ans
