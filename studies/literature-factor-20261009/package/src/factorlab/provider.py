"""Anonymous public data retrieval. Final acquisition requires a valid freeze."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import signal
import socket
import time
import pandas as pd
from .common import dump, digest, now, append

FIELDS = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST"

def code(symbol):
    a,b=symbol.split(".")
    return ("sh." if b == "SSE" else "sz.") + a

def rows(q):
    if q.error_code != "0": raise RuntimeError(f"Provider error {q.error_code}: {q.error_msg}")
    values=[]
    while q.next(): values.append(q.get_row_data())
    if q.error_code != "0": raise RuntimeError(f"Provider stream error {q.error_code}")
    return pd.DataFrame(values, columns=q.fields)

def initialize():
    import baostock as bs
    socket.setdefaulttimeout(25)
    signal.signal(signal.SIGALRM,lambda *a: (_ for _ in ()).throw(TimeoutError("provider operation timeout")))
    signal.alarm(30)
    r=bs.login()
    signal.alarm(0)
    if r.error_code != "0": raise RuntimeError("Anonymous provider login failed")

def fetch_symbol(task):
    import baostock as bs
    symbol, start, end, years, out = task
    out=Path(out); d=out/symbol;d.mkdir(parents=True,exist_ok=True)
    records=[]
    requests=[("bars", lambda:bs.query_history_k_data_plus(code(symbol),FIELDS,start_date=start,end_date=end,frequency="d",adjustflag="3")),
              ("adjustments", lambda:bs.query_adjust_factor(code(symbol),start_date=start,end_date=end))]
    for year in years:
        requests.append((f"dividends_{year}",lambda year=year:bs.query_dividend_data(code(symbol),year=str(year),yearType="operate")))
    for name, call in requests:
        path=d/(name+".csv")
        if path.exists():
            records.append({"kind":name,"file":str(path),"sha256":digest(path),"status":"cached"});continue
        error=None
        for attempt in range(2):
            try:
                signal.alarm(45)
                df=rows(call())
                signal.alarm(0)
                df.to_csv(path,index=False)
                records.append({"kind":name,"file":str(path),"sha256":digest(path),"rows":len(df),"status":"ok"})
                error=None;break
            except Exception as exc:
                signal.alarm(0);error=f"{type(exc).__name__}: {exc}"
                time.sleep(.25)
        if error: records.append({"kind":name,"status":"error","error":error})
        time.sleep(.03)
    return {"symbol":symbol,"start":start,"end":end,"accessed_utc":now(),"requests":records}

def acquire(root, stage="history", workers=4):
    import baostock as bs
    root=Path(root).resolve()
    if stage == "final":
        from .protocol import check_finalist
        finalist=check_finalist(root)
        # No post-test dates, including October 8, are requested.
        # Expanding refits require the full prior return history, not one year.
        # Only 2026 actions can affect the seven-session cash account.
        start,end,years="2007-12-28","2026-10-07",[2026]
        initialize()
        dated=[]
        for date in ['2026-08-31','2026-09-18']+finalist['final_sessions']:
            signal.alarm(45);d=rows(bs.query_hs300_stocks(date=date));signal.alarm(0)
            if len(d)<200 or ('updateDate' in d and (d.updateDate>date).any()):
                raise ValueError('Missing or future-dated final membership snapshot: '+date)
            d['requested_date']=date;dated.append(d)
        members=pd.concat(dated,ignore_index=True)
        memberfile=root/'private/downloads/final/membership.csv';memberfile.parent.mkdir(parents=True,exist_ok=True);members.to_csv(memberfile,index=False)
        bs.logout()
        symbols=sorted({c[3:]+('.SSE' if c.startswith('sh.') else '.SZSE') for c in members.code})
    else:
        start,end,years="2017-01-01","2023-12-31",list(range(2018,2024))
        symbols=sorted(pd.read_parquet(root/"private/course/prices.parquet",columns=["symbol"]).symbol.unique())
    out=root/"private/downloads"/stage;out.mkdir(parents=True,exist_ok=True)
    dump(out/"request.json",{"stage":stage,"start":start,"end":end,"symbol_count":len(symbols),"provider":"BaoStock","anonymous":True,"time_utc":now(),"final_prices_requested":stage=="final"})
    initialize()
    for label,q in [("calendar",bs.query_trade_dates(start_date=start,end_date=end)),("security_master",bs.query_stock_basic())]:
        signal.alarm(45)
        rows(q).to_csv(out/(label+".csv"),index=False)
        signal.alarm(0)
    bs.logout()
    errors=0
    with ProcessPoolExecutor(max_workers=workers,initializer=initialize) as pool:
        jobs=[pool.submit(fetch_symbol,(s,start,end,years,str(out))) for s in symbols]
        for i,job in enumerate(as_completed(jobs),1):
            try:
                rec=job.result();errors+=sum(x["status"]=="error" for x in rec["requests"])
                append(out/"acquisition.jsonl",rec)
            except Exception as e:
                errors+=1;append(out/"acquisition.jsonl",{"error":str(e),"time_utc":now()})
            if i%50==0 or i==len(jobs): print(f"{stage}: {i}/{len(jobs)} symbols; request errors {errors}",flush=True)
    dump(out/"completion.json",{"completed_utc":now(),"request_errors":errors,"symbols":len(symbols)})
    return errors

if __name__ == "__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",default=".");p.add_argument("--stage",choices=["history","final"],default="history");p.add_argument("--workers",type=int,default=4)
    args=p.parse_args();raise SystemExit(0 if acquire(args.root,args.stage,args.workers)==0 else 2)
