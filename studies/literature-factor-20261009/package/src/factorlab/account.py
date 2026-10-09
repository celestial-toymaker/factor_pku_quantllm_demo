"""Daily-bar, long-only cash/share ledger with explicitly modeled fills.

No synthetic return evidence. Unsupported corporate actions must fail data audit
before this engine runs. Daily bars cannot establish opening-auction liquidity.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import pandas as pd
import numpy as np

def charges(date,side,notional,friction=1.,commission=.0003,minimum=5.):
    date=pd.Timestamp(date)
    if date<pd.Timestamp('2017-01-01'):raise ValueError('Statutory schedule only verified for 2017 onward')
    transfer=notional*(.00002 if date<pd.Timestamp('2022-04-29') else .00001)
    stamp=notional*(.001 if date<pd.Timestamp('2023-08-28') else .0005) if side=='sell' else 0.
    return {'commission':max(minimum,notional*commission)*friction,'transfer':transfer,'stamp':stamp}

@dataclass
class Account:
    cash:float=1_000_000.
    friction:float=1.
    participation:float=.01
    slippage:float=.0005
    max_position:float=.05
    shares:dict=field(default_factory=dict)
    settled:dict=field(default_factory=dict)
    marks:dict=field(default_factory=dict)
    pending:list=field(default_factory=list)
    entitlements:dict=field(default_factory=dict)
    fills:list=field(default_factory=list)
    failures:list=field(default_factory=list)
    fees:float=0.
    slip_cost:float=0.
    dividend_tax_reserve:float=0.
    tax_liability:float=0.

    def equity(self):
        return self.cash+sum(q*self.marks[s] for s,q in self.shares.items())+sum(p['cash']+p['shares']*self.marks.get(p['symbol'],0) for p in self.pending)-self.tax_liability

    def corporate_actions(self,date,actions):
        # Shares held at the recorded record-date close determine entitlement.
        for a in actions:
            key=a['id'];s=a['symbol']
            if a['ex_date']==date:
                q=self.entitlements.get(key,0.)
                if q:
                    div=q*a['cash_ps'];bonus=math.floor(q*a['bonus_ps']+1e-8)
                    # Conservative reserve, explicitly not a claim of exact individual tax settlement.
                    tax=.2*div;self.dividend_tax_reserve+=tax
                    stock_tax=.2*q*a.get('stock_dividend_ps',0.)
                    self.dividend_tax_reserve+=stock_tax;self.tax_liability+=stock_tax
                    self.pending.append({'symbol':s,'cash':div-tax,'shares':bonus,'pay_date':a['pay_date'],'list_date':a['list_date']})
                    if s in self.marks:self.marks[s]=(self.marks[s]-a['cash_ps'])/(1+a['bonus_ps'])
        remaining=[]
        for p in self.pending:
            if p['cash'] and p['pay_date']<=date:self.cash+=p['cash'];p['cash']=0.
            if p['shares'] and p['list_date']<=date:
                s=p['symbol'];self.shares[s]=self.shares.get(s,0)+p['shares'];self.settled[s]=self.settled.get(s,0)+p['shares'];p['shares']=0.
            if p['cash'] or p['shares']:remaining.append(p)
        self.pending=remaining
        tax_payment=min(self.cash,self.tax_liability);self.cash-=tax_payment;self.tax_liability-=tax_payment

    def record_entitlements(self,date,actions):
        for a in actions:
            if a['record_date']==date:self.entitlements[a['id']]=self.shares.get(a['symbol'],0.)

    def trade(self,date,s,side,quantity,bar,lag_adv,nav):
        reason=None
        if bar is None or not np.isfinite(bar.get('open',np.nan)) or bar.get('tradestatus')!=1 or bar.get('volume',0)<=0:reason='suspended_or_missing'
        elif bar.get('isST')!=0 and side=='buy':reason='risk_warning'
        elif not np.isfinite(lag_adv) or lag_adv<=0:reason='missing_lagged_liquidity'
        elif bar.get('preclose',0)<=0:reason='missing_limit_reference'
        else:
            # Main-board stocks only. Both boundaries blocked on either side conservatively.
            # Historical daily isST also forces conservative 5% movement blocking for sells.
            limit=.05 if bar.get('isST') else .10
            upper=math.floor(bar['preclose']*(1+limit)*100+.500001)/100
            lower=math.floor(bar['preclose']*(1-limit)*100+.500001)/100
            if bar['open']>=upper-.00001 or bar['open']<=lower+.00001:reason='opening_at_limit'
        if reason:
            self.failures.append({'date':date,'symbol':s,'side':side,'requested':quantity,'reason':reason});return
        raw=bar['open'];price=raw*(1+(1 if side=='buy' else -1)*self.slippage*self.friction)
        # Price tick rounded against the account.
        price=(math.ceil(price*100-1e-9) if side=='buy' else math.floor(price*100+1e-9))/100
        # Lagged ADV defines order size; realized volume only caps a possible fill.
        cap=min(lag_adv*self.participation/price,bar['volume']*self.participation)
        quantity=min(quantity,cap)
        if side=='buy':quantity=min(quantity,max(0,nav*self.max_position/price-self.shares.get(s,0)))
        else:quantity=min(quantity,self.settled.get(s,0))
        if side=='sell' and quantity>=self.shares.get(s,0)-1e-8:q=self.shares.get(s,0)
        else:q=math.floor(quantity/100)*100
        while q>0:
            c=charges(date,side,q*price,self.friction);fee=sum(c.values())
            if side=='sell' or q*price+fee<=self.cash+1e-8:break
            q-=100
        if q<=0:
            self.failures.append({'date':date,'symbol':s,'side':side,'requested':quantity,'reason':'cash_lot_or_participation'});return
        notional=q*price
        if side=='buy':self.cash-=notional+fee;self.shares[s]=self.shares.get(s,0)+q
        else:
            self.cash+=notional-fee;self.shares[s]-=q;self.settled[s]-=q
            if self.shares[s]<=1e-8:self.shares.pop(s);self.settled.pop(s,None)
        self.fees+=fee;slip=q*abs(price-raw);self.slip_cost+=slip
        self.fills.append({'date':date,'symbol':s,'side':side,'quantity':q,'raw_open':raw,'price':price,'notional':notional,**c,'slippage_cost':slip,'cash_after':self.cash})
        if self.cash < -1e-6:raise AssertionError('Cash constraint violated')

def simulate(bars, targets, dates, actions=(), capital=1_000_000.,friction=1.,delay=1,max_position=.05,participation=.01):
    """targets have close timestamps; eligible fills are >=delay sessions later."""
    dates=pd.DatetimeIndex(dates)
    wanted=set(s for w in targets.values() for s in w.index[w>0])
    bars=bars.loc[pd.to_datetime(bars.date).between(dates[0]-pd.Timedelta(days=90),dates[-1])].copy()
    # Preserve the complete market calendar even if no target passes breadth.
    calendar_dates=pd.DatetimeIndex(sorted(pd.to_datetime(bars.date).unique()))
    bars=bars[bars.symbol.isin(wanted)];bars['date']=pd.to_datetime(bars.date)
    all_dates=calendar_dates;symbols=sorted(bars.symbol.unique())
    amount=bars.pivot(index='date',columns='symbol',values='amount').reindex(all_dates)
    adv=amount.rolling(20,min_periods=20).mean().shift(1)
    bydate={d:x.set_index('symbol').to_dict('index') for d,x in bars.groupby('date')}
    ac=Account(capital,friction,participation,max_position=max_position);daily=[];positions=[];orders={};intentions=[]
    for signal,weights in targets.items():
        i=all_dates.get_indexer([pd.Timestamp(signal)])[0]
        if i>=0 and i+delay<len(all_dates):orders[all_dates[i+delay]]=weights
    for date in dates:
        ds=str(date.date());day=bydate.get(date,{})
        ac.settled=dict(ac.shares)
        ac.corporate_actions(ds,actions)
        # A missing current close is marked at the last known price, with explicit stale count.
        for s,q in ac.shares.items():
            if s in day and np.isfinite(day[s].get('preclose',np.nan)):ac.marks[s]=day[s]['preclose']
            elif s not in ac.marks:raise ValueError('Unpriced holding')
        nav=ac.equity();fills_before=len(ac.fills)
        if date in orders:
            weights=orders[date]
            for s,w in weights.items():
                if w>0 and (s not in day or not np.isfinite(day[s].get('open',np.nan))):
                    ac.failures.append({'date':ds,'symbol':s,'side':'buy','requested':None,'reason':'missing_execution_bar'})
            # preclose is the exchange's known pre-opening reference, including
            # announced ex-right adjustments. Current open/close never size intentions.
            desired={s:nav*float(w)/day[s]['preclose'] for s,w in weights.items() if w>0 and s in day and day[s].get('preclose',0)>0}
            intentions.extend({'execution_date':ds,'symbol':s,'target_shares_before_lots':q,'known_reference':day[s]['preclose'],'decision_nav':nav} for s,q in desired.items())
            # Sales first. All buys scale to available cash; ordering is fixed by ticker only for fills.
            for s in sorted(ac.shares):
                q=ac.shares[s]-desired.get(s,0)
                if q>0:ac.trade(ds,s,'sell',q,day.get(s),adv.at[date,s] if s in adv else np.nan,nav)
            buys={s:max(0,q-ac.shares.get(s,0)) for s,q in desired.items()}
            needed=sum(q*day[s]['preclose'] for s,q in buys.items());scale=min(1,max(0,ac.cash-ac.tax_liability)/max(needed*1.002,1))
            for s,q in sorted(buys.items()):
                if q>0:
                    ac.marks[s]=day[s]['open'];ac.trade(ds,s,'buy',q*scale,day[s],adv.at[date,s] if s in adv else np.nan,nav)
        stale=0
        for s,q in ac.shares.items():
            if s in day and np.isfinite(day[s].get('close',np.nan)):ac.marks[s]=day[s]['close']
            else:stale+=1
            positions.append({'date':ds,'symbol':s,'quantity':q,'close':ac.marks[s],'value':q*ac.marks[s]})
        ac.record_entitlements(ds,actions)
        eq=ac.equity();traded=sum(f['notional'] for f in ac.fills[fills_before:])
        daily.append({'date':ds,'cash':ac.cash,'positions_value':sum(q*ac.marks[s] for s,q in ac.shares.items()),'receivables':sum(p['cash']+p['shares']*ac.marks.get(p['symbol'],0) for p in ac.pending),'tax_liability':ac.tax_liability,'net_equity':eq,'gross_same_fills_equity':eq+ac.fees+ac.slip_cost+ac.dividend_tax_reserve,'fees_cumulative':ac.fees,'slippage_cumulative':ac.slip_cost,'dividend_tax_reserve':ac.dividend_tax_reserve,'turnover':traded/nav if nav>0 else 0,'stale_positions':stale,'position_count':len(ac.shares)})
    return {'daily':pd.DataFrame(daily),'fills':pd.DataFrame(ac.fills),'failures':pd.DataFrame(ac.failures),'positions':pd.DataFrame(positions),'intentions':pd.DataFrame(intentions)}
