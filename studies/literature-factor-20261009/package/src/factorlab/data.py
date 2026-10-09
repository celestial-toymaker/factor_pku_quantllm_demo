"""Normalize public downloads and fail closed on material accounting gaps."""
from pathlib import Path
import json, hashlib, re
import numpy as np
import pandas as pd
from .common import dump,digest,now
from .cache import membership_mask

def assemble(root, stage='history', require_complete=True):
    root=Path(root);base=root/'private/downloads'/stage
    if require_complete and not (base/'completion.json').exists():raise RuntimeError('Download incomplete')
    membership=pd.read_csv(root/'private/course/membership.csv',parse_dates=['start','end'])
    bars=[];actions=[];problems=[];files=[];warnings=[]
    audit_start='2018-01-01' if stage=='history' else '2026-09-21'
    supplemental=json.loads((root/'data/supplementary_actions.json').read_text()) if (root/'data/supplementary_actions.json').exists() else []
    rights={(a['symbol'],a['ex_date']) for a in supplemental if a['type']=='optional_rights'}
    def potentially_held(symbol,date):
        m=membership[membership.symbol==symbol];d=pd.Timestamp(date)
        # Retain possible suspended holdings after membership exit; no future exclusion.
        return bool(((m.start<=d)&(m.end+pd.Timedelta(days=365)>=d)).any())
    for p in sorted(base.glob('*/bars.csv')):
        symbol=p.parent.name;b=pd.read_csv(p,parse_dates=['date']);b['symbol']=symbol
        for f in sorted(p.parent.glob('*.csv')):files.append({'path':str(f.relative_to(root)),'sha256':digest(f),'bytes':f.stat().st_size})
        if b.empty:continue
        b=b.sort_values('date');bars.append(b)
        dividends=[]
        for f in sorted(p.parent.glob('dividends_*.csv')):
            d=pd.read_csv(f)
            if len(d):dividends.append(d)
        div=pd.concat(dividends,ignore_index=True).drop_duplicates(['dividOperateDate','dividRegistDate']) if dividends else pd.DataFrame()
        known={}
        for i,r in div.iterrows():
            ex=str(r.dividOperateDate);cash=float(r.dividCashPsBeforeTax) if pd.notna(r.dividCashPsBeforeTax) else 0.
            described=re.search(r'^10(?:转[\d.]+)?(?:送[\d.]+)?派([\d.]+)元',str(r.dividCashStock))
            if pd.isna(r.dividCashPsBeforeTax) and described:cash=float(described.group(1))/10
            bonus=sum(float(r[k]) if pd.notna(r[k]) else 0. for k in ['dividStocksPs','dividReserveToStockPs'])
            record=str(r.dividRegistDate);pay=str(r.dividPayDate);listing=str(r.dividStockMarketDate)
            missing=[]
            if pd.isna(r.dividCashPsBeforeTax) and '派' in str(r.dividCashStock) and not described:missing.append('cash amount')
            if cash and (pay=='nan' or pay<ex):missing.append('cash payment date')
            if bonus and (listing=='nan' or listing<ex):missing.append('bonus tradability date')
            if record=='nan' or ex=='nan' or record>=ex:missing.append('record/ex dates')
            if missing and ex>=audit_start and (stage=='final' or potentially_held(symbol,ex)):problems.append({'symbol':symbol,'date':ex,'kind':'corporate_action_fields','detail':'; '.join(missing)})
            action={'id':symbol+':'+ex,'symbol':symbol,'record_date':record,'ex_date':ex,'pay_date':pay if cash else ex,'list_date':listing if bonus else ex,'cash_ps':cash,'bonus_ps':bonus,'stock_dividend_ps':float(r.dividStocksPs) if pd.notna(r.dividStocksPs) else 0.,'known_date':str(r.dividPlanDate),'fields_complete':not missing}
            actions.append(action);known[ex]=action
        for a in supplemental:
            if a['symbol']==symbol and a['type']=='cash_dividend' and a['ex_date'] not in known:
                actions.append(a);known[a['ex_date']]=a
        prev=b.close.shift(1)
        # Raw preclose incorporates exchange ex-right reference. Unexplained resets
        # require terms of rights, mergers, conversions or other capital actions.
        for n,r in b.loc[(prev-b.preclose).abs()>.011].iterrows():
            if r.date<pd.Timestamp(audit_start) or n==b.index[0]:continue
            pos=b.index.get_loc(n);prior=prev.iloc[pos]
            if not np.isfinite(prior) or not np.isfinite(r.preclose):continue
            ds=str(r.date.date());a=known.get(ds)
            expected=(prior-a['cash_ps'])/(1+a['bonus_ps']) if a else prior
            # One-cent quote rounding plus floating point tolerance.
            if abs(expected-r.preclose)>.011 and (stage=='final' or potentially_held(symbol,ds)):
                finding={'symbol':symbol,'date':ds,'kind':'unreconciled_ex_reference','detail':f'previous_close={prior}; supplied_preclose={r.preclose}; explained_reference={expected}; disclosed_cash_bonus={a is not None}'}
                if (symbol,ds) in rights:
                    finding['kind']='verified_rights_lapse_policy';warnings.append(finding);continue
                # Theoretical exchange references may weight excluded repurchased
                # shares differently from cash per entitled share. Book the disclosed
                # cash/bonus and use the supplied exchange reference for limits.
                (warnings if a and a['fields_complete'] else problems).append(finding)
    df=pd.concat(bars,ignore_index=True).sort_values(['date','symbol'])
    duplicates=int(df.duplicated(['date','symbol']).sum())
    if duplicates:problems.append({'kind':'duplicate_bars','count':duplicates})
    calendar=pd.read_csv(base/'calendar.csv');dates=pd.to_datetime(calendar.loc[calendar.is_trading_day.astype(str)=='1','calendar_date'])
    outside=int((~df.date.isin(dates)).sum())
    if outside:problems.append({'kind':'non_calendar_bars','count':outside})
    active=df.tradestatus.eq(1)&df.volume.gt(0)
    invalid=int((active&((df.low>df[['open','close']].min(axis=1)+.011)|(df.high<df[['open','close']].max(axis=1)-.011)|(df.close<=0))).sum())
    if invalid:problems.append({'kind':'invalid_active_OHLC','count':invalid})
    units=(df.amount/df.volume).where(active)
    relevant=df.symbol.str.startswith(('000','001','002','003','600','601','603','605'))&active&(df.date>=audit_start)
    unitfail=int((relevant&((units<df.low-.02)|(units>df.high+.02))).sum())
    if unitfail:problems.append({'kind':'amount_volume_price_inconsistency','count':unitfail})
    processed=root/'private/processed';processed.mkdir(exist_ok=True)
    df.to_parquet(processed/f'{stage}_bars.parquet',index=False)
    dump(processed/f'{stage}_actions.json',actions)
    dump(root/'data'/f'{stage}_fingerprints.json',files)
    for f in sorted(base.glob('*.csv')):files.append({'path':str(f.relative_to(root)),'sha256':digest(f),'bytes':f.stat().st_size})
    for f in [root/'data/supplementary_actions.json',root/'private/course/prices.parquet',root/'private/course/membership.csv']:
        if f.exists():files.append({'path':str(f.relative_to(root)),'sha256':digest(f),'bytes':f.stat().st_size})
    dump(root/'data'/f'{stage}_fingerprints.json',files)
    detail=pd.DataFrame(problems);detail.to_csv(root/'results'/f'{stage}_integrity_findings.csv',index=False)
    calendar_missing=[]
    if stage=='history':
        cached=pd.read_parquet(root/'private/course/prices.parquet',columns=['date','symbol','close','amount','eligible_member']).rename(columns={'eligible_member':'member'})
        match=cached[cached.date.between('2018-01-01','2023-12-31')].merge(df[['date','symbol','close','amount']],on=['date','symbol'],how='left',suffixes=('_cache','_raw'))
        missing=int((match.member & match.close_raw.isna()).sum())
        if missing:problems.append({'kind':'cached_member_raw_bars_missing','count':missing})
        # Traded CNY amount should agree independent of price-adjustment scale.
        match=match[match.member&match.amount_raw.notna()]
        rel=(match.amount_cache-match.amount_raw).abs()/match.amount_raw.abs().clip(lower=1)
        amount_q={str(q):float(rel.quantile(q)) for q in [.5,.99,1.]}
        mismatch=int((rel>.01).sum())
        if mismatch:problems.append({'kind':'provider_cache_amount_mismatch_over_1pct','count':mismatch})
    else:
        missing=None;amount_q=None
        member_file=base/'membership.csv'
        if not member_file.exists():problems.append({'kind':'final_membership_missing'})
        else:
            members=pd.read_csv(member_file)
            members['symbol']=[s[3:]+('.SSE' if s.startswith('sh.') else '.SZSE') for s in members.code]
            members['date']=pd.to_datetime(members.requested_date)
            matched=members.merge(df[['date','symbol','close']],on=['date','symbol'],how='left')
            missing=int(matched.close.isna().sum())
            if missing:problems.append({'kind':'final_member_reference_bars_missing','count':missing})
    completion=json.loads((base/'completion.json').read_text()) if (base/'completion.json').exists() else None
    if completion and completion.get('request_errors'):problems.append({'kind':'acquisition_request_errors','count':completion['request_errors']})
    audit={'stage':stage,'created_utc':now(),'download_complete':completion is not None,'bars':len(df),'symbols':df.symbol.nunique(),'first_date':str(df.date.min().date()),'last_date':str(df.date.max().date()),'duplicates':duplicates,'invalid_ohlc':invalid,'unit_failures':unitfail,'cached_member_rows_missing':missing,'amount_relative_error_quantiles':amount_q,'corporate_actions':len(actions),'findings_count':len(problems),'material_findings':problems,'warnings':warnings,'integrity_pass':len(problems)==0 and completion is not None,'fingerprints_sha256':digest(root/'data'/f'{stage}_fingerprints.json'),'raw_prices':'BaoStock adjustflag=3; CNY per share; volume shares; amount CNY','redistribution':'Unverified: raw inputs withheld from release; anonymous noncommercial research access only','final_outcomes_read':stage=='final'}
    dump(root/'results'/f'{stage}_data_audit.json',audit)
    return audit

def panels(df,calendar=None):
    dates=pd.DatetimeIndex(calendar) if calendar is not None else pd.DatetimeIndex(sorted(df.date.unique()))
    return {k:df.pivot(index='date',columns='symbol',values=k).reindex(dates) for k in ['open','high','low','close','volume','amount','tradestatus','isST'] if k in df}
