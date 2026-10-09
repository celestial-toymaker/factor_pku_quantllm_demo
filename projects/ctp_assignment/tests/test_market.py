from dataclasses import replace
import pytest
from ctp_assignment.core import Plan, Quote, StopRun
from ctp_assignment.market import contract, margin_check


def instrument(**kw):
    return dict(InstrumentID="rb2701", ProductID="rb", ExchangeID="SHFE", ProductClass="1",
                IsTrading=1, PriceTick=1, VolumeMultiple=10, MinLimitOrderVolume=1,
                MaxLimitOrderVolume=100, LongMarginRatio=.12, **kw)


def test_exact_contract_survives_prefix_option_results():
    d=instrument()
    rows=[{**d,"InstrumentID":"rb2701C3500","ProductClass":"2"},d]
    assert contract(rows,"rb2701","SHFE")==d


@pytest.mark.parametrize("change", [{"ProductClass":"2"},{"IsTrading":0},{"PriceTick":float("nan")},
                                    {"VolumeMultiple":0},{"MinLimitOrderVolume":2},{"ExchangeID":"UNKNOWN"}])
def test_ineligible_contract_rejected(change):
    with pytest.raises(StopRun):contract([{**instrument(),**change}],"rb2701")


def test_missing_duplicate_wrong_exchange_contract_rejected():
    for rows,exchange in (([],None),([instrument(),instrument()],None),([instrument()],"DCE")):
        with pytest.raises(StopRun,match="NOT_UNIQUE"):contract(rows,"rb2701",exchange)


def risks():
    q=Quote("rb2701",3500,3499,3500,3200,3800,10,0,1)
    m={"InstrumentID":"rb2701","ExchangeID":"SHFE","HedgeFlag":"1","LongMarginRatioByMoney":.12,"LongMarginRatioByVolume":0}
    f={"InstrumentID":"rb","ExchangeID":"SHFE","OpenRatioByMoney":.0001,"CloseTodayRatioByMoney":.0002}
    a={"CurrencyID":"CNY","Available":10000}
    return instrument(),q,[m],[f],[a]


def test_margin_uses_price_limit_and_bilateral_charges():
    d,q,m,f,a=risks()
    # 3800*10*.12*1.1 + (3800*10*.0003) + 10*1*10 = 5127.40.
    a[0]["Available"]=5127.39
    with pytest.raises(StopRun,match="INSUFFICIENT"):margin_check(d,q,m,f,a)
    a[0]["Available"]=5127.41
    assert margin_check(d,q,m,f,a)["margin_sufficient"]


@pytest.mark.parametrize("kind",["margin","fee","account","nan","foreign","hedge"])
def test_incomplete_or_invalid_risk_queries_block(kind):
    d,q,m,f,a=risks()
    if kind=="margin":m=[]
    elif kind=="fee":f=[]
    elif kind=="account":a=[]
    elif kind=="nan":a[0]["Available"]=float("nan")
    elif kind=="foreign":m[0]["InstrumentID"]="OTHER"
    elif kind=="hedge":m[0]["HedgeFlag"]="2"
    with pytest.raises(StopRun):margin_check(d,q,m,f,a)


@pytest.mark.parametrize("symbol",["rb2701\x00other","x"*100,"rb2701C3500","", "../rb2701"])
def test_live_plan_rejects_nonfutures_symbols(symbol):
    with pytest.raises(StopRun):Plan(symbol,"SHFE",3500,mode="SIMNOW").validate()


def test_empty_exchange_in_exact_risk_response_is_supported():
    d,q,m,f,a=risks();m[0]['ExchangeID']='';f[0]['ExchangeID']=''
    assert margin_check(d,q,m,f,a)['margin_sufficient']
    m[0]['ExchangeID']='DCE'
    with pytest.raises(StopRun,match='INCOMPLETE'):margin_check(d,q,m,f,a)
