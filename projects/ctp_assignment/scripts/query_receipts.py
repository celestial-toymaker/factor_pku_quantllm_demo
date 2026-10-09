"""Read-only, allowlisted provider evidence; no order methods are called."""
from datetime import datetime,UTC
from pathlib import Path
import sqlite3
import argparse
from ctp_assignment.native import Native
from ctp_assignment.security import load_private,write_public

parser=argparse.ArgumentParser()
parser.add_argument('--simnow',action='store_true')
for key in ('config','state','native-dir','output'):parser.add_argument('--'+key,type=Path,required=True)
a=parser.parse_args()
if not a.simnow:parser.error('Explicit --simnow required; this command is read-only')
cfg=load_private(a.config)
if a.state.resolve().parent!=a.config.resolve().parent:parser.error('Journal must remain beside the private config')
with sqlite3.connect('file:'+str(a.state.resolve())+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    own=[dict(row) for row in db.execute('SELECT ref,front,session,sysid,leg FROM orders')]
assert len(own)==2
n=Native(a.native_dir,cfg,a.config.resolve().parent/'native-flow')
result={'mode':'SIMNOW','orders_sent':0,'instrument':cfg['instrument'],
        'started_utc':datetime.now(UTC).isoformat(),'completed_queries':[]}
try:
    n.connect()
    rows=n.query('orders');result['completed_queries'].append('orders')
    result['active_orders']=sum(d.get('OrderStatus') not in {'0','2','4','5'} and d.get('OrderSubmitStatus')!='4' for d in rows)
    matched=[d for d in rows if any(str(d.get('OrderRef','')).strip()==o['ref'] and d.get('FrontID')==o['front'] and d.get('SessionID')==o['session'] and str(d.get('OrderSysID','')).strip()==o['sysid'] for o in own)]
    keys=('InstrumentID','ExchangeID','OrderRef','FrontID','SessionID','OrderSysID','Direction','CombOffsetFlag','LimitPrice','VolumeTotalOriginal','VolumeTraded','OrderStatus','OrderSubmitStatus','InsertDate','InsertTime')
    result['orders']=[{k:d.get(k) for k in keys} for d in matched]
    rows=n.query('trades');result['completed_queries'].append('trades')
    matched=[d for d in rows if d.get('InstrumentID')==cfg['instrument'] and d.get('ExchangeID')==cfg['exchange'] and any(str(d.get('OrderRef','')).strip()==o['ref'] and str(d.get('OrderSysID','')).strip()==o['sysid'] for o in own)]
    keys=('InstrumentID','ExchangeID','OrderRef','OrderSysID','TradeID','TradingDay','TradeDate','TradeTime','Direction','OffsetFlag','Price','Volume')
    result['trades']=[{k:d.get(k) for k in keys} for d in matched]
    rows=n.query('positions',cfg['instrument']);result['completed_queries'].append('positions')
    rows=[d for d in rows if d.get('InstrumentID')==cfg['instrument']]
    assert all(d.get('PosiDirection') in {'2','3'} and d.get('HedgeFlag')=='1' for d in rows)
    result['long']=sum(d.get('Position',0) for d in rows if d['PosiDirection']=='2')
    result['short']=sum(d.get('Position',0) for d in rows if d['PosiDirection']=='3')
    result['attributed_order_count']=len(result['orders']);result['attributed_trade_count']=len(result['trades'])
    assert len(result['orders'])==len(result['trades'])==2
    assert result['long']==result['short']==result['active_orders']==0
    assert all(d['OrderStatus']=='0' and d['VolumeTraded']==1 for d in result['orders'])
    result['verified']=True
finally:
    n.close();result['completed_utc']=datetime.now(UTC).isoformat()
    result['callback_trace']=n.trace
    write_public(a.output,result,cfg)
