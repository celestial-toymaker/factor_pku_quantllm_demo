"""End-to-end orchestration with a provider-shaped fake, never a live account."""
import time
from ctp_assignment.core import Plan, Quote, StopRun
from ctp_assignment.runner import run_simnow
from ctp_assignment.security import verify_evidence


class Provider:
    def __init__(self):
        self.session={"FrontID":1,"SessionID":2,"MaxOrderRef":0,"TradingDay":"DAY"}
        self.contracts={};self.orders=[];self.trades=[];self.pending=[];self.sent=[];self.trace=[]
        self.closed=False

    def connect(self):pass
    def subscribe(self,symbols):pass
    def close(self):self.closed=True
    def quote(self,symbol):return Quote(symbol,101,100,101,90,110,time.monotonic(),0,1)
    def market_open(self,symbol):return True
    def drain(self,seconds):
        time.sleep(min(seconds,.005))
        events,self.pending=self.pending,[]
        return events
    def query(self,kind,instrument=""):
        if kind=="instrument":return [{"InstrumentID":"rb2701","ExchangeID":"SHFE","ProductID":"rb",
            "ProductClass":"1","IsTrading":1,"PriceTick":1,"VolumeMultiple":10,
            "MinLimitOrderVolume":1,"MaxLimitOrderVolume":100,"LongMarginRatio":.12}]
        if kind=="margin":return [{"InstrumentID":"rb2701","ExchangeID":"SHFE","HedgeFlag":"1","LongMarginRatioByMoney":.12}]
        if kind=="commission":return [{"InstrumentID":"rb2701","ExchangeID":"SHFE","OpenRatioByVolume":2,"CloseTodayRatioByVolume":2}]
        if kind=="account":return [{"CurrencyID":"CNY","Available":100000}]
        if kind=="orders":return self.orders.copy()
        if kind=="trades":return self.trades.copy()
        if kind=="positions":return [] if len(self.trades) in {0,2} else [{"InstrumentID":"rb2701","PosiDirection":"2","HedgeFlag":"1","Position":1}]
        raise AssertionError(kind)
    def send(self,a,p):
        self.sent.append(a)
        assert len([a for a in self.sent if a["leg"]=="OPEN"])==1
        order={"OrderRef":a["ref"],"FrontID":1,"SessionID":2,"OrderSysID":"S"+a["ref"],
               "OrderStatus":"0","VolumeTraded":1,"VolumeTotalOriginal":1,"InstrumentID":p.instrument}
        trade={"OrderRef":a["ref"],"OrderSysID":order["OrderSysID"],"ExchangeID":p.exchange,"TradingDay":"DAY",
               "Direction":"0" if a["leg"]=="OPEN" else "1","OffsetFlag":"0" if a["leg"]=="OPEN" else "3",
               "TradeID":"T"+a["ref"],"Volume":1,"Price":a["price"],"InstrumentID":p.instrument}
        self.orders.append(order);self.trades.append(trade)
        # Trade callback deliberately precedes order mapping; both are duplicated.
        self.pending += [("TD",n,(d,),time.monotonic()) for n,d in
                         [("onRtnTrade",trade),("onRtnOrder",order),("onRtnTrade",trade),("onRtnOrder",order)]]
    def cancel(self,a,p):raise AssertionError("Completed orders should never be cancelled")


def test_full_orchestration_and_restart_reconcile(tmp_path):
    n=Provider();p=Plan("rb2701","SHFE",100,mode="DRY_RUN")
    cfg={"broker_id":"SYNTHETIC_BROKER","user_id":"SYNTHETIC_USER"}
    e=run_simnow(n,cfg,p,tmp_path/"s.db",tmp_path/"e.json")
    assert verify_evidence(e)["status"]=="OFFLINE_PASS"
    assert e["fills"]=={"OPEN":1,"CLOSE":1} and len(n.sent)==2 and n.closed
    n.closed=False
    e2=run_simnow(n,cfg,p,tmp_path/"s.db",tmp_path/"e2.json",True)
    assert verify_evidence(e2)["status"]=="OFFLINE_PASS"
    assert len(n.sent)==2 and n.closed


def test_unexpected_failure_preserves_journal_and_redacts_message(tmp_path):
    class Broken(Provider):
        def connect(self):raise ValueError("SECRET_SYNTHETIC_PASSWORD")
        def close(self):raise RuntimeError("SECRET_SYNTHETIC_PASSWORD")
    p=Plan("rb2701","SHFE",100)
    cfg={"broker_id":"SYNTHETIC_BROKER","user_id":"SYNTHETIC_USER","password":"SECRET_SYNTHETIC_PASSWORD"}
    e=run_simnow(Broken(),cfg,p,tmp_path/"s.db",tmp_path/"e.json")
    assert e["reason"]=="UNEXPECTED_ValueError" and e["cleanup_error_type"]=="RuntimeError"
    assert e["live_acceptance"]!="PASS" and e["fills"]=={"OPEN":0,"CLOSE":0}
    assert cfg["password"] not in (tmp_path/"e.json").read_text()
