import queue
import time
from pathlib import Path
import pytest
from ctp_assignment.core import StopRun
from ctp_assignment.native import Native


def receiver():
    # Exercise real response handling without loading the SDK or opening a socket.
    n=Native.__new__(Native)
    n.q=queue.Queue();n.pending=[];n.latest={};n.trace=[];n.subscription_count=0
    n.market_status={};n.contracts={}
    return n


def push(n, side, event, data, req, last, error=0):
    n.q.put((side,event,(data,{"ErrorID":error},req,last),time.monotonic()))


def test_observed_md_login_zero_id():
    n=receiver();push(n,"MD","onRspUserLogin",{"TradingDay":"DAY"},0,True)
    assert n.wait("MD","onRspUserLogin",1,timeout=.05)==[{"TradingDay":"DAY"}]


def test_zero_id_is_not_accepted_for_td_query():
    n=receiver();push(n,"TD","onRspQryInvestorPosition",{},0,True)
    with pytest.raises(StopRun,match="TIMEOUT"):
        n.wait("TD","onRspQryInvestorPosition",10,timeout=.01)


def test_query_waits_for_matching_final_response():
    n=receiver()
    push(n,"TD","onRspQryOrder",{"VolumeTraded":0},10,False)
    push(n,"TD","onRspQryOrder",{},9,True)
    push(n,"TD","onRspQryOrder",{"VolumeTraded":1},10,True)
    assert n.wait("TD","onRspQryOrder",10,.05)==[{"VolumeTraded":0},{"VolumeTraded":1}]
    assert len(n.pending)==1


def test_empty_query_requires_final_marker():
    n=receiver();push(n,"TD","onRspQryOrder",{},1,False)
    with pytest.raises(StopRun,match="TIMEOUT"):
        n.wait("TD","onRspQryOrder",1,.01)
    n=receiver();push(n,"TD","onRspQryOrder",{},1,True)
    assert n.wait("TD","onRspQryOrder",1,.01)==[]


def test_query_error_does_not_leak_server_message():
    n=receiver();n.q.put(("TD","onRspQryOrder",({}, {"ErrorID":7,"ErrorMsg":"SECRET_CANARY"},1,True),time.monotonic()))
    with pytest.raises(StopRun) as error:n.wait("TD","onRspQryOrder",1,.01)
    assert str(error.value)=="CTP_REQUEST_REJECTED_CODE_7"


def test_disconnect_invalidates_wait():
    n=receiver();n.q.put(("TD","onFrontDisconnected",(4097,),time.monotonic()))
    with pytest.raises(StopRun,match="CONNECTION_OR_HEARTBEAT_LOST"):
        n.wait("TD","onRspQryOrder",1,.01)


def test_only_explicit_continuous_market_status_is_open():
    n=receiver();n.contracts["IF2612"]={"ExchangeID":"CFFEX","ProductID":"IF"}
    assert not n.market_open("IF2612")
    for status,expected in (("2",True),("0",False),("3",False),("6",False)):
        n.q.put(("TD","onRtnInstrumentStatus",({"ExchangeID":"CFFEX","InstrumentID":"IF","InstrumentStatus":status},),time.monotonic()))
        n.drain(0)
        assert n.market_open("IF2612")==expected
    n.market_status[("CFFEX","IF")]='2';n.market_status[("CFFEX","IF2612")]='6'
    assert not n.market_open("IF2612")


def test_changed_native_file_cannot_be_loaded(tmp_path):
    import json
    from ctp_assignment.native import load_native
    native=tmp_path/'native';native.mkdir();(native/'library.so').write_text('CHANGED')
    (tmp_path/'build_manifest.json').write_text(json.dumps({'outputs':{'library.so':'0'*64}}))
    with pytest.raises(StopRun,match='FINGERPRINT_MISMATCH'):load_native(native)
