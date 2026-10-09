from pathlib import Path
import json,time
import numpy as np
import pandas as pd
import baostock as bs
from factorlab.data import panels
from factorlab.features import eligibility
from factorlab.common import dump,digest
root=Path(__file__).resolve().parents[1]
base=root/'private/downloads/industry';base.mkdir(exist_ok=True)
print(bs.login().error_msg,flush=True)
for year in range(2018,2024):
    date=f'{year-1}-12-29' if year!=2021 else '2020-12-30'
    path=base/f'{year}.csv'
    if not path.exists():
        rs=bs.query_stock_industry(date=date);rows=[]
        if rs.error_code!='0':raise RuntimeError(rs.error_msg)
        while rs.next():rows.append(rs.get_row_data())
        df=pd.DataFrame(rows,columns=rs.fields);df['requested_date']=date;df.to_csv(path,index=False)
    print(year,len(pd.read_csv(path)),flush=True)
bs.logout()
cal=pd.read_csv(root/'private/downloads/history/full_calendar.csv');dates=pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_trading_day==1,'calendar_date']))
cached=pd.read_parquet(root/'private/course/prices.parquet');p=panels(cached,dates)
raw=pd.read_parquet(root/'private/processed/history_bars.parquet');r=panels(raw,dates)
e=eligibility(p,pd.read_csv(root/'private/course/membership.csv'))
e.loc['2018':'2023'] &= r['tradestatus'].reindex(columns=e.columns).loc['2018':'2023'].eq(1)&r['isST'].reindex(columns=e.columns).loc['2018':'2023'].eq(0)
ret=np.log(p['close']/p['close'].shift(1));ret.index.name='date';ret.columns.name='symbol'
a=ret.stack().rename('cache_log_return').reset_index().merge(raw[['date','symbol','close','preclose','tradestatus']],on=['date','symbol'])
a=a[a.date.between('2018-01-01','2023-12-31')&(a.tradestatus==1)]
a['raw_reference_log_return']=np.log(a.close/a.preclose);a['difference']=a.cache_log_return-a.raw_reference_log_return
a.loc[a.difference.abs()>.001].to_csv(root/'results/feature_return_discrepancies.csv',index=False)
breadth=e.loc['2018':'2023'].sum(axis=1)
metadata={'annual_industry_snapshots':[],'breadth':breadth.describe().to_dict(),'days_below_200':int((breadth<200).sum()),'feature_return_abs_difference_quantiles':{str(q):a.difference.abs().quantile(q) for q in [.5,.99,.999,1]},'return_discrepancies_gt_001':int((a.difference.abs()>.001).sum())}
for f in sorted(base.glob('*.csv')):
    df=pd.read_csv(f);assert (df.updateDate<=df.requested_date).all()
    metadata['annual_industry_snapshots'].append({'path':str(f.relative_to(root)),'rows':len(df),'max_update':df.updateDate.max(),'sha256':digest(f)})
dump(root/'results/reconciliation_and_breadth.json',metadata);print(json.dumps(metadata,indent=2),flush=True)
