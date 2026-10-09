from dataclasses import replace
import json
import socket
import sys
from pathlib import Path
import pytest
from ctp_assignment.core import Controller, Journal, Plan, Quote, StopRun
from ctp_assignment.runner import dry_run, LiveRunner
from ctp_assignment.security import verify_evidence, redact, write_public


@pytest.fixture
def run(tmp_path):
    now = [10.0]
    clock = lambda: now[0]
    p = Plan("SYNTHETIC", "SHFE", 100)
    j = Journal(tmp_path/"state.db", p, "fixture", clock)
    c = Controller(j, p, clock)
    c.session_ready(1, 2, 0, "DAY")
    yield c, j, p, now
    if j.lock.closed is False:
        j.close()


def proof(c, now, **kw):
    return {"completed": ["orders", "trades", "positions"], "day": c.day, "session": c.session,
            "started": now[0], "stable": True, "long": 0, "short": 0, "active_orders": 0,
            "preflight_ok": True, **kw}


def tick(c, now, **kw):
    c.tick(Quote(**{"instrument": c.plan.instrument, "last": 101, "bid": 100, "ask": 101,
                   "lower": 90, "upper": 110, "received": now[0], "source_age": 0, "tick": 1, **kw}))


def opening(run):
    c,j,p,now = run
    assert c.reconcile(proof(c, now))
    tick(c, now)
    a, = c.take_actions()
    return a


def fill(c, a, leg):
    c.order(a["ref"], c.front, c.session, "SYS"+a["ref"], "FILLED", 1, c.plan.instrument, 1)
    c.trade("T"+a["ref"], a["ref"], 1, a["price"], leg, c.plan.instrument)


def test_hand_ledger_and_no_live_claim(tmp_path):
    e = dry_run(tmp_path/"s.db", tmp_path/"e.json")
    assert verify_evidence(e)["status"] == "OFFLINE_PASS"
    assert e["live_acceptance"] == "NOT_PASSED"
    ledger = e["hand_calculated_example"]
    assert ledger["net_pnl"] == (100-101)*10 - (2+2) == -14
    assert e["fills"] == {"OPEN":1, "CLOSE":1}


def test_durable_intent_precedes_transport_and_single_open(run):
    c,j,p,now = run
    a = opening(run)
    assert j.get("opening_intent") is True
    assert len(j.orders()) == 1
    for _ in range(20):
        tick(c, now)
    assert c.take_actions() == []


@pytest.mark.parametrize("change", [
    {"completed":["orders","trades"]}, {"day":"WRONG"}, {"session":9},
    {"stable":False}, {"active_orders":1}, {"long":1}, {"short":1}, {"preflight_ok":False},
])
def test_preflight_queries_are_mandatory(run, change):
    c,j,p,now = run
    assert not c.reconcile(proof(c, now, **change))
    tick(c, now)
    assert not j.orders()


@pytest.mark.parametrize("change", [{"received":0}, {"source_age":40}, {"ask":float("nan")},
                                   {"bid":102}, {"ask":200}, {"last":100}, {"instrument":"OTHER"}])
def test_stale_invalid_and_nontrigger_quotes_do_not_trade(run, change):
    c,j,p,now=run
    c.reconcile(proof(c, now))
    tick(c, now, **change)
    assert not j.orders()


def test_duplicate_and_reordered_reports(run):
    c,j,p,now=run
    a=opening(run)
    c.trade("T1", a["ref"], 1,101,"OPEN",p.instrument)
    c.trade("T1", a["ref"], 1,101,"OPEN",p.instrument)
    assert not c.take_actions()  # fill alone does not establish terminal order state
    c.order(a["ref"],1,2,"SYS1","FILLED",1,p.instrument,1)
    close,=c.take_actions()
    c.order(a["ref"],1,2,"SYS1","WORKING",0,p.instrument,1)
    assert j.orders()[0]["status"] == "FILLED"
    assert j.totals()["OPEN"] == 1 and close["offset"] == "CLOSE_TODAY"


def test_fill_after_cancel_requires_reconciliation(run):
    c,j,p,now=run
    a=opening(run)
    now[0] += 11
    c.timeouts()
    cancel,=c.take_actions()
    assert cancel["action"] == "cancel"
    c.order(a["ref"],1,2,"SYS1","CANCELLED",1,p.instrument,1)
    c.trade("LATE",a["ref"],1,101,"OPEN",p.instrument)
    tick(c, now)
    assert not c.take_actions()
    assert c.reconcile(proof(c, now,long=1))
    close,=c.take_actions()
    assert close["leg"] == "CLOSE"


def test_disconnect_does_not_resubmit(run):
    c,j,p,now=run
    opening(run)
    c.disconnected()
    tick(c,now)
    assert not c.take_actions()
    assert j.get("state") == "RECONCILE_REQUIRED"


def test_unknown_cancel_and_unowned_report(run):
    c,j,p,now=run
    a=opening(run)
    assert not c.order(a["ref"],99,99,"FOREIGN","FILLED",1,p.instrument,1)
    assert j.totals()["OPEN"] == 0
    now[0]+=11;c.timeouts();c.take_actions()
    now[0]+=11;c.timeouts();tick(c,now)
    assert not any(a["action"] == "send" for a in c.take_actions())


def test_restart_and_changed_freeze(run, tmp_path):
    c,j,p,now=run
    a=opening(run)
    j.close()
    with pytest.raises(StopRun, match="BINDING_OR_PLAN"):
        Journal(tmp_path/"state.db",replace(p,trigger_price=90),"fixture")
    j2=Journal(tmp_path/"state.db",p,"fixture",lambda:now[0])
    try:
        c2=Controller(j2,p,lambda:now[0]);c2.session_ready(3,4,2,"DAY")
        tick(c2,now)
        assert not c2.take_actions()
        # Reconnect session cannot claim ownership of a similarly numbered order.
        assert not c2.order(a["ref"],3,4,"S","FILLED",1,p.instrument,1)
    finally:j2.close()


def test_single_process_lock(run, tmp_path):
    c,j,p,now=run
    with pytest.raises(StopRun,match="ANOTHER_PROCESS"):
        Journal(tmp_path/"other.db",p,"fixture")


def test_fills_are_insufficient_without_final_queries(run):
    c,j,p,now=run
    a=opening(run);fill(c,a,"OPEN")
    b,=c.take_actions();fill(c,b,"CLOSE")
    assert j.get("state") != "OFFLINE_PASS"
    assert not c.reconcile(proof(c,now,started=0))
    assert c.reconcile(proof(c,now))
    assert j.get("state") == "OFFLINE_PASS"


def test_flat_net_with_offsetting_positions_cannot_pass(run):
    c,j,p,now=run
    a=opening(run);fill(c,a,"OPEN")
    b,=c.take_actions();fill(c,b,"CLOSE")
    assert not c.reconcile(proof(c,now,long=1,short=1))


@pytest.mark.parametrize("exchange,offset",[("SHFE","CLOSE_TODAY"),("INE","CLOSE_TODAY"),("DCE","CLOSE"),("CZCE","CLOSE")])
def test_exchange_closing_offsets(tmp_path, exchange, offset):
    p=Plan("SYNTHETIC",exchange,100); now=[10.]
    j=Journal(tmp_path/"x.db",p,"fixture",lambda:now[0]);c=Controller(j,p,lambda:now[0])
    try:
        c.session_ready(1,2,0,"DAY");c.reconcile(proof(c,now));tick(c,now)
        a,=c.take_actions();fill(c,a,"OPEN")
        b,=c.take_actions();assert b["offset"]==offset
    finally:j.close()


def test_rejected_close_needs_new_snapshot(run):
    c,j,p,now=run
    a=opening(run);fill(c,a,"OPEN");b,=c.take_actions()
    c.order(b["ref"],1,2,"S2","REJECTED",0,p.instrument,1)
    tick(c,now)
    assert not c.take_actions()
    assert c.reconcile(proof(c,now,long=1))
    b2,=c.take_actions();assert b2["leg"]=="CLOSE"


def test_read_only_reconciliation_cannot_create_close_intent(run):
    c,j,p,now=run
    a=opening(run)
    c.allow_orders=False
    fill(c,a,"OPEN")
    c.reconcile(proof(c,now,long=1))
    assert len(j.orders())==1 and not c.take_actions()


def test_pending_send_is_dropped_on_fault(run):
    c,j,p,now=run
    c.reconcile(proof(c,now));tick(c,now)
    c.fault("TEST_FAULT")
    assert not any(a["action"]=="send" for a in c.take_actions())
    assert j.orders()[0]["status"]=="REJECTED"


def test_conflicting_duplicate_fill_stops(run):
    c,j,p,now=run
    a=opening(run);fill(c,a,"OPEN");c.take_actions()
    c.trade("T"+a["ref"],a["ref"],1,999,"OPEN",p.instrument)
    assert not c.reconciled


def test_offline_path_cannot_import_sdk_or_connect(tmp_path, monkeypatch):
    import builtins
    old=builtins.__import__
    def guarded(name,*a,**k):
        if name in {"vnctpmd","vnctptd","ctp_assignment.native"}:
            raise AssertionError("native import on offline path")
        return old(name,*a,**k)
    def reject(*a,**k):raise AssertionError("offline network attempt")
    monkeypatch.setattr(builtins,"__import__",guarded)
    monkeypatch.setattr(socket,"socket",reject)
    dry_run(tmp_path/"s.db",tmp_path/"e.json")


def test_export_rejects_secret_canaries(tmp_path):
    cfg={"password":"CANARY_SECRET_X9","user_id":"CANARY_USER_Q1","auth_code":"CANARY_AUTH_Y7"}
    for s in cfg.values():
        assert s not in redact("log "+s,cfg)
        with pytest.raises(StopRun,match="SECRET_IN_EXPORT"):
            write_public(tmp_path/"e.json",{"reason":s},cfg)
    with pytest.raises(StopRun,match="PRIVATE_FIELD"):
        write_public(tmp_path/"e.json",{"Balance":123})


def test_evidence_tampering_detected(tmp_path):
    e=dry_run(tmp_path/"s.db",tmp_path/"e.json")
    e["live_acceptance"]="PASS"
    with pytest.raises(StopRun,match="SIMULATION_CANNOT"):
        verify_evidence(e)


def test_close_attempt_limit_does_not_create_fourth_order(run):
    c,j,p,now=run
    a=opening(run);fill(c,a,"OPEN")
    for attempt in range(3):
        b,=c.take_actions()
        c.order(b["ref"],1,2,"C"+str(attempt),"REJECTED",0,p.instrument,1)
        c.reconcile(proof(c,now,long=1))
    assert not c.take_actions()
    assert len([o for o in j.orders() if o["leg"]=="CLOSE"])==3
    assert not c.reconciled


def test_preflight_expires_before_opening(run):
    c,j,p,now=run;c.reconcile(proof(c,now));now[0]+=16;tick(c,now)
    assert not j.orders()


def test_snapshot_cannot_emit_close_before_all_queries_complete(run):
    c,j,p,now=run;a=opening(run)
    class Fake:
        def drain(self,seconds):return []
        def query(self,kind,*args):
            if kind=="orders":
                return [{"OrderRef":a["ref"],"FrontID":1,"SessionID":2,"OrderSysID":"S",
                         "OrderStatus":"0","VolumeTraded":1,"InstrumentID":p.instrument,"VolumeTotalOriginal":1}]
            if kind=="trades":
                return [{"OrderRef":a["ref"],"OrderSysID":"S","ExchangeID":p.exchange,"TradingDay":"DAY",
                         "Direction":"0","OffsetFlag":"0","TradeID":"T","Volume":1,"Price":101,"InstrumentID":p.instrument}]
            assert not c.take_actions()
            raise StopRun("CTP_REQUEST_TIMEOUT")
    with pytest.raises(StopRun,match="TIMEOUT"):LiveRunner(Fake(),c).snapshot()
    assert not c.reconciled and not c.take_actions()


def test_trade_attribution_checks_offset_and_direction(run):
    c,j,p,now=run;a=opening(run)
    c.order(a["ref"],1,2,"S","FILLED",1,p.instrument,1)
    d={"OrderRef":a["ref"],"OrderSysID":"S","ExchangeID":p.exchange,"TradingDay":"DAY",
       "Direction":"1","OffsetFlag":"0","TradeID":"T","Volume":1,"Price":101,"InstrumentID":p.instrument}
    LiveRunner(None,c).trade(d)
    assert j.totals()["OPEN"]==0 and not c.reconciled


@pytest.mark.parametrize("age,allowed",[(-1.001,False),(-1.0,True),(-.789,True),(3.0,True),(3.001,False)])
def test_bounded_source_clock_skew_and_staleness(run,age,allowed):
    c,j,p,now=run;c.reconcile(proof(c,now));tick(c,now,source_age=age)
    assert bool(j.orders())==allowed


def test_future_local_receipt_is_rejected(run):
    c,j,p,now=run;c.reconcile(proof(c,now));tick(c,now,received=now[0]+.01)
    assert not j.orders()
