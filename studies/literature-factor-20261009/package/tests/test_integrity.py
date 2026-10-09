"""Invented fixtures verify software only; they are never research evidence."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from factorlab.account import Account,charges,simulate
from factorlab.features import graph_weights,network_score,eligibility,target_weights
from factorlab.outcomes import calendar_labels,read_bars,DataBoundaryError
from factorlab.statistics import select_method,holm,hac_mean
from factorlab.common import dump

def bar(price=10.,**kw):
    return {'open':price,'close':price,'high':price+.5,'low':price-.5,'preclose':price,'volume':1e7,'amount':price*1e7,'tradestatus':1,'isST':0,**kw}

def test_independent_hand_account():
    # Hand ledger: buy 100 at10 on2023-09-21:1000+5+.01=1005.01.
    # Sell100 at11:1100-5-.011-.55=1094.439. Ending10089.429.
    a=Account(10_000,slippage=0,max_position=1)
    a.trade('2023-09-21','A','buy',100,bar(),1e8,10_000)
    assert a.cash==pytest.approx(8994.99)
    a.settled=dict(a.shares)
    a.trade('2023-09-22','A','sell',100,bar(11,preclose=10.5),1e8,10_100)
    assert a.cash==pytest.approx(10089.429)
    assert a.fees==pytest.approx(10.571)
    assert not a.shares

def test_dated_both_side_charges():
    assert charges('2022-04-28','buy',10000)['transfer']==.2
    assert charges('2022-04-29','buy',10000)['transfer']==.1
    assert charges('2023-08-25','sell',10000)['stamp']==10
    assert charges('2023-08-28','sell',10000)['stamp']==5
    a=charges('2023-08-28','sell',10000,3);b=charges('2023-08-28','sell',10000,1)
    assert a['commission']==3*b['commission']
    assert a['stamp']==b['stamp'] and a['transfer']==b['transfer']

def test_suspension_limits_and_t_plus_one():
    a=Account(10000,slippage=0,max_position=1)
    a.trade('2023-09-21','A','buy',100,bar(tradestatus=0),1e8,10000)
    assert not a.fills
    a.trade('2023-09-21','A','buy',100,bar(11,preclose=10),1e8,10000)
    assert not a.fills
    a.trade('2023-09-21','A','buy',100,bar(),1e8,10000)
    a.trade('2023-09-21','A','sell',100,bar(),1e8,10000)
    assert len(a.fills)==1

def test_cash_cannot_go_negative():
    a=Account(1001,slippage=0,max_position=1)
    a.trade('2023-09-21','A','buy',1000,bar(),1e8,1001)
    assert a.cash>=0 and not a.fills

def test_corporate_entitlement_payment_and_bonus_delay():
    a=Account(100,slippage=0,shares={'A':100},marks={'A':10})
    actions=[{'id':'x','symbol':'A','record_date':'2023-06-01','ex_date':'2023-06-02','pay_date':'2023-06-05','list_date':'2023-06-06','cash_ps':1.,'bonus_ps':.5}]
    a.record_entitlements('2023-06-01',actions);a.corporate_actions('2023-06-02',actions)
    assert a.cash==100 and a.pending[0]['cash']==80
    assert a.shares['A']==100 and a.marks['A']==6
    assert a.equity()==pytest.approx(1080)
    a.corporate_actions('2023-06-05',actions);assert a.cash==180
    a.corporate_actions('2023-06-06',actions);assert a.shares['A']==150 and not a.pending

def test_calendar_holiday_missing_and_purge():
    d=pd.to_datetime(['2026-09-18','2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-28','2026-09-29','2026-09-30'])
    p=pd.DataFrame({'A':[10,11,np.nan,13,14,15,16,17]},index=d)
    y=calendar_labels(p,1,'2026-09-24')
    assert np.isnan(y.loc['2026-09-18','A'])
    assert y.loc['2026-09-22','A']==pytest.approx(14/13-1)
    assert np.isnan(y.loc['2026-09-23','A'])
    assert '2026-09-25' not in y.index

def test_membership_not_all_cached_symbols():
    d=pd.bdate_range('2020-01-01',periods=25);c=pd.DataFrame(10.,index=d,columns=['600001.SSE','600002.SSE'])
    m=pd.DataFrame([['600001.SSE',str(d[0].date()),str(d[10].date())]],columns=['symbol','start','end'])
    panel={'close':c,'volume':c*1e7,'amount':c*1e8}
    e=eligibility(panel,m,minimum_history=1)
    assert not e.iloc[-1].any() and not e['600002.SSE'].any()

def test_ties_not_arbitrary_deciles():
    i=[str(x) for x in range(250)];e=pd.Series(True,index=i)
    assert target_weights(pd.Series(1.,index=i),e).sum()==0
    s=pd.Series(np.repeat(np.arange(5),50),index=i)
    w=target_weights(s,e);assert (w>0).sum()==50

def test_cross_stock_direction_and_no_self_edges():
    rng=np.random.default_rng(42);a=rng.normal(size=1000);b=np.r_[0,a[:-1]];x=np.column_stack([a,b,rng.normal(size=1000)])
    w=graph_weights(x,np.ones(3,dtype=bool),leaders=1,min_pairs=200)
    assert w[0,1]>.99 and np.all(np.diag(w)==0)

def test_future_perturbation_cannot_change_earlier_scores():
    rng=np.random.default_rng(1);d=pd.bdate_range('2008-01-01',periods=320)
    c=pd.DataFrame(np.exp(rng.normal(0,.01,(320,4)).cumsum(0)),index=d)
    e=pd.DataFrame(True,index=d,columns=c.columns)
    s,f=network_score(c,e,2,.2,min_pairs=25)
    changed=c.copy();changed.iloc[230:]*=np.exp(rng.normal(size=(90,4)))
    t,g=network_score(changed,e,2,.2,min_pairs=25)
    pd.testing.assert_frame_equal(s.iloc[:230],t.iloc[:230])
    assert all(x['training_end']<x['date'] for x in f)

def test_search_cannot_open_final_labels(tmp_path,monkeypatch):
    touched=[]
    def forbidden(path,*a,**kw):touched.append(str(path));raise AssertionError('reader should not be called')
    monkeypatch.setattr(pd,'read_parquet',forbidden)
    with pytest.raises(DataBoundaryError):read_bars(tmp_path,'final')
    assert touched==[]
    with pytest.raises(AssertionError):read_bars(tmp_path,'validation')
    assert touched==[str(tmp_path/'private/processed/history_bars.parquet')]

def test_search_rejects_injected_final_dates(tmp_path,monkeypatch):
    monkeypatch.setattr(pd,'read_parquet',lambda *a,**k:pd.DataFrame({'date':['2026-09-21']}))
    with pytest.raises(DataBoundaryError):read_bars(tmp_path,'validation')

def test_holm_eighteen_and_fallback_least_negative():
    assert holm({'A':.001,'B':None})==pytest.approx({'A':.018,'B':1.})
    base={'evaluable':True,'distinct':True,'validation_qualified':False,'complexity':5,'turnover':.1}
    rows=[{**base,'candidate_id':'A','mean_net_active':-.002},{**base,'candidate_id':'B','mean_net_active':-.001}]
    assert select_method(rows)['candidate_id']=='B'
    rows[1]['evaluable']=False;assert select_method(rows)['candidate_id']=='A'
    rows[0]['evaluable']=False;assert select_method(rows) is None

def test_qualified_precedes_higher_unqualified_mean_and_exact_ties():
    b={'evaluable':True,'distinct':True,'complexity':5,'turnover':.1,'mean_net_active':.001}
    rows=[{**b,'candidate_id':'Z','validation_qualified':True},{**b,'candidate_id':'A','mean_net_active':.002,'validation_qualified':False}]
    assert select_method(rows)['candidate_id']=='Z'
    rows[0]['validation_qualified']=False;rows[1]['mean_net_active']=.001
    assert select_method(rows)['candidate_id']=='A'

def test_seven_dates_inference_is_unavailable():
    assert hac_mean([.001]*7)['ci95'] is None

def test_no_pickle_execution(tmp_path):
    from factorlab.cache import read_membership
    malicious=tmp_path/'m.pkl';malicious.write_bytes(b"cos\nsystem\n(S'touch /tmp/forbidden-test-marker'\ntR.")
    with pytest.raises(Exception):read_membership(malicious)

def test_today_open_cannot_size_preopening_intentions():
    days=pd.bdate_range('2023-01-02',periods=30)
    bars=pd.DataFrame([{'date':d,'symbol':'A',**bar()} for d in days])
    targets={days[24]:pd.Series({'A':.04})}
    a=simulate(bars,targets,days[25:27])
    bars.loc[bars.date>=days[25],'open']=10.2
    b=simulate(bars,targets,days[25:27])
    pd.testing.assert_frame_equal(a['intentions'],b['intentions'])
    assert a['fills'].iloc[0].price!=b['fills'].iloc[0].price

def test_missing_execution_is_kept_as_failure_and_cash():
    days=pd.bdate_range('2023-01-02',periods=30)
    bars=pd.DataFrame([{'date':d,'symbol':s,**bar()} for d in days for s in ['A','B'] if not(s=='A' and d==days[25])])
    targets={days[24]:pd.Series({'A':.04})}
    a=simulate(bars,targets,days[25:26])
    assert a['failures'].iloc[0].reason=='missing_execution_bar'
    assert a['daily'].iloc[0].cash==1e6

def test_frozen_inputs_and_cache_keys_change(tmp_path):
    from factorlab.protocol import fingerprint,cache_key,verify_input_bytes,ProtocolError
    from factorlab.common import digest
    names=['research/protocol.md','research/method.md','configs/research.yaml','configs/candidate_registry.json','data/data_manifest.json','data/history_fingerprints.json','data/industry_fingerprints.json','results/history_data_audit.json','research/exposure_ledger.json','requirements.lock','pyproject.toml']
    for name in names:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('[]' if 'fingerprints' in name else '{}')
    p=tmp_path/'src/factorlab';p.mkdir(parents=True);(p/'a.py').write_text('a=1')
    before=cache_key(tmp_path,{'horizon':5});(p/'a.py').write_text('a=2')
    assert cache_key(tmp_path,{'horizon':5})!=before
    raw=tmp_path/'raw';raw.write_text('original');dump(tmp_path/'data/history_fingerprints.json',[{'path':'raw','sha256':digest(raw)}]);verify_input_bytes(tmp_path)
    raw.write_text('mutated')
    with pytest.raises(ProtocolError):verify_input_bytes(tmp_path)

def test_projection_does_not_fit_validation_or_labels():
    from factorlab.diagnostics import fit_control_projection
    rng=np.random.default_rng(16);dates=pd.bdate_range('2017-01-02',periods=270);columns=range(10)
    control=pd.DataFrame(rng.normal(size=(270,10)),index=dates,columns=columns)
    score=control*.3+pd.DataFrame(rng.normal(size=(270,10)),index=dates,columns=columns)
    _,fit=fit_control_projection(score,{'control':control})
    changed=score.copy();changed.loc['2018':]*=-100
    _,after=fit_control_projection(changed,{'control':control})
    assert fit['coefficients']==after['coefficients'] and not fit['outcomes_used']

def test_industry_snapshot_future_timestamp_rejected(tmp_path):
    from factorlab.diagnostics import industry_panel
    p=tmp_path/'private/downloads/industry';p.mkdir(parents=True)
    pd.DataFrame([{'code':'sh.600001','industry':'test','updateDate':'2018-01-01','requested_date':'2017-12-29'}]).to_csv(p/'2018.csv',index=False)
    with pytest.raises(ValueError):industry_panel(tmp_path,pd.to_datetime(['2018-01-02']),['600001.SSE'])

def test_report_reads_only_validated_metrics(tmp_path,monkeypatch):
    from factorlab.evaluate import skeleton,validate_metrics
    from factorlab.report import render
    from factorlab.verify import verify
    (tmp_path/'results').mkdir();(tmp_path/'research').mkdir()
    dump(tmp_path/'results/metrics.json',skeleton())
    for name in ['method.md','implementation_reference.md']:(tmp_path/'research'/name).write_text('Invented test fixture, not empirical evidence.')
    monkeypatch.setattr(pd,'read_parquet',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Report accessed raw outcomes')))
    render(tmp_path);assert verify(tmp_path)['ok']
    m=skeleton();m['research_outcome']='INCONCLUSIVE';dump(tmp_path/'results/metrics.json',m)
    assert not verify(tmp_path)['ok']

def test_empty_targets_cash_account():
    days=pd.bdate_range('2023-01-02',periods=30)
    bars=pd.DataFrame([{'date':d,'symbol':'A',**bar()} for d in days])
    a=simulate(bars,{days[24]:pd.Series({'A':0.})},days[25:])
    assert a['daily'].net_equity.eq(1e6).all() and a['fills'].empty

def test_selected_final_report_fixture_consistency(tmp_path):
    from factorlab.evaluate import skeleton,measure
    from factorlab.report import render
    from factorlab.verify import verify
    (tmp_path/'results').mkdir();(tmp_path/'research').mkdir()
    for name in ['method.md','implementation_reference.md']:(tmp_path/'research'/name).write_text('Invented fixture only.')
    dates=pd.to_datetime(['2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-28','2026-09-29','2026-09-30'])
    history=pd.bdate_range('2026-08-01','2026-09-30')
    bars=pd.DataFrame([{'date':d,'symbol':'A',**bar()} for d in history])
    account=simulate(bars,{},dates);summary,daily=measure(account,account,short=True)
    h=hac_mean(np.zeros(60));m=skeleton()
    row={'candidate_id':'INVENTED','evaluable':True,'distinct':True,'validation_qualified':False,'mean_net_active':0.,'turnover':0.,'holm_p':1.,'positive_folds':0,'folds':[],'primary':h,'incremental_over_existing':h,'mature_daily_rank_ic':h,'overlap':{},'qualification_failures':['Holm_5pct']}
    m.update(method_selected='INVENTED',research_outcome='NO_FACTOR_PASSED',candidate_results=[row],final={'evaluated':True,'candidate_id':'INVENTED','sessions':7,'first_date':'2026-09-21','last_date':'2026-09-30','diagnostics':{'base':summary},'rank_ic':hac_mean([]),'daily':daily.to_dict('records')})
    dump(tmp_path/'results/metrics.json',m);render(tmp_path)
    assert verify(tmp_path)['ok'] and (tmp_path/'results/figures/final_period.png').exists()

def test_suspended_positive_quote_is_not_an_executable_label():
    dates=pd.bdate_range('2023-01-02',periods=8)
    prices=pd.DataFrame({'A':np.arange(10.,18.)},index=dates)
    traded=pd.DataFrame(True,index=dates,columns=['A']);traded.iloc[2]=False
    labels=calendar_labels(prices,1,'2023-12-31',traded)
    assert np.isnan(labels.iloc[0,0]) and np.isnan(labels.iloc[1,0])
    assert labels.iloc[2,0]==pytest.approx(14/13-1)
    assert len(labels)==len(prices)
