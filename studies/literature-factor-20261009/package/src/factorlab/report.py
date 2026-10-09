"""Render only the validated metrics artifact; never open market outcome data."""
from pathlib import Path
import csv,json
from .common import dump,digest
from .evaluate import validate_metrics

def fmt(x,scale=1,digits=3):return 'unavailable' if x is None else f'{x*scale:.{digits}f}'

def render(root):
    root=Path(root);m=json.loads((root/'results/metrics.json').read_text());validate_metrics(m)
    rows=[];folds=[];overlaps=[]
    for r in m['candidate_results']:
        rows.append({'candidate_id':r['candidate_id'],'method_selected':r['candidate_id']==m['method_selected'],'evaluable':r['evaluable'],'distinct':r['distinct'],'validation_qualified':r['validation_qualified'],'mean_net_active_daily':r.get('mean_net_active'),'holm_p':r.get('holm_p'),'positive_folds':r.get('positive_folds'),'turnover':r.get('turnover'),'reason':r.get('unavailable_reason','')})
        for f in r.get('folds',[]):folds.append({'candidate_id':r['candidate_id'],**{k:v for k,v in f.items() if not isinstance(v,dict)},'mean_net_active':f['active']['mean'],'hac_lower':f['active']['ci95'][0] if f['active']['ci95'] else None,'hac_upper':f['active']['ci95'][1] if f['active']['ci95'] else None,**(f.get('annualized') or {})})
        for name,v in r.get('overlap',{}).items():overlaps.append({'candidate_id':r['candidate_id'],'control_id':name,**v})
    for name,records in [('candidate_summary',rows),('fold_summary',folds),('overlap_summary',overlaps)]:
        with (root/'results'/f'{name}.csv').open('w') as f:
            if records:w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
            else:f.write('status,reason\nunavailable,No evaluable return or overlap result\n')
    table='| Candidate | Evaluable | Mean net active, bp/day | Holm p | Qualified | Selected |\n|---|---|---:|---:|---|---|\n'
    table+='\n'.join(f"| {r['candidate_id']} | {r['evaluable']} | {fmt(r['mean_net_active_daily'],10000)} | {fmt(r['holm_p'])} | {r['validation_qualified']} | {r['method_selected']} |" for r in rows)
    selected=next((r for r in m['candidate_results'] if r['candidate_id']==m['method_selected']),None)
    outcome=m['research_outcome'];status=f"Research outcome: `{outcome}`. Method selected: `{m['method_selected'] or 'none'}`. Validation qualified: `{str(m['validation_qualified']).lower()}`."
    final=m.get('final');final_text=m.get('final_unavailable_reason','Not evaluated.')
    if final and final.get('evaluated'):
        b=final['diagnostics']['base']
        final_text=f"The unchanged selected method was evaluated on September21–24 and28–30,2026 (seven sessions), starting with CNY1m cash. Net account return: **{fmt(b['net_return'],100)}%**; benchmark: **{fmt(b['benchmark_net_return'],100)}%**; relative compounded return: **{fmt(b['relative_compounded_return'],100)}%**. Final cash: CNY{fmt(b['last_cash'],digits=2)}; remaining marked positions: CNY{fmt(b['last_positions_value'],digits=2)} in {b['last_position_count']} names. No October8 outcomes or holiday observations are used."
        final_text+='\n\n| Diagnostic | Net account % | Benchmark % | Relative % | Fees CNY | Failed orders |\n|---|---:|---:|---:|---:|---:|\n'
        for n,v in final['diagnostics'].items():final_text+=f"| {n} | {fmt(v['net_return'],100)} | {fmt(v['benchmark_net_return'],100)} | {fmt(v['relative_compounded_return'],100)} | {fmt(v['fees_cny'],digits=2)} | {v['failed_orders']} |\n"
        final_text+=f"\nMature daily IC dates: {final['rank_ic']['n']}. Dependence-aware inference: {final['rank_ic'].get('reason','see artifact')}. Annualized final headlines are deliberately unavailable."
    elif final:final_text=final.get('reason','Final result unavailable')
    findings=''
    if selected:
        p=selected['primary'];inc=selected['incremental_over_existing'];ic=selected['mature_daily_rank_ic']
        findings=f"For the selected method, pooled validation mean net active return was {fmt(p['mean'],10000)} bp/day over {p['n']} dates. The lag10 HAC95% interval was [{fmt(p['ci95'][0],10000)}, {fmt(p['ci95'][1],10000)}] bp/day; unadjusted one-sided p={fmt(p['p_one_sided'])}, Holm18 p={fmt(selected['holm_p'])}. Positive folds: {selected['positive_folds']}/3. Mean daily turnover was {fmt(selected['turnover'],100)}%.\n\nThe mean matched daily RankIC was {fmt(ic['mean'])}. The paired mean economic increment over the frozen existing-signal account was {fmt(inc['mean'],10000)} bp/day; its95% interval is retained in the metrics artifact. Sector checks use dated prior-year classifications. Existing-signal projection coefficients are fitted only in 2008–2017; validation labels never fit a transform.\n\n"
        findings+='| Validation fold | Sessions | Net account % | Benchmark % | Mean active bp/day | Max drawdown % |\n|---|---:|---:|---:|---:|---:|\n'
        for f in selected['folds']:findings+=f"| {f['first_date']}–{f['last_date']} | {f['sessions']} | {fmt(f['net_return'],100)} | {fmt(f['benchmark_net_return'],100)} | {fmt(f['active']['mean'],10000)} | {fmt(f['max_drawdown'],100)} |\n"
        findings+='\n\nRecorded qualification criteria not met: '+(', '.join(selected.get('qualification_failures',[])) or 'none')+'.\n'
        ordering=selected.get('ordering_diagnostics',{})
        findings+=f"\nTraining-fitted residual-score RankIC: {fmt(ordering.get('training_residual_rank_ic',{}).get('mean'))}; within-sector RankIC: {fmt(ordering.get('within_sector_rank_ic',{}).get('mean'))}; mean historical sector coverage: {fmt(ordering.get('industry_coverage_mean'),100)}%.\n"
        findings+='\n| Frozen historical diagnostic | Mean active bp/day | HAC 95% interval, bp/day |\n|---|---:|---|\n'
        for name,v in m.get('selected_diagnostics',{}).items():
            h=v['pooled_active'];ci=h.get('ci95')
            findings+=f"| {name} | {fmt(h['mean'],10000)} | {fmt(ci[0],10000) if ci else 'unavailable'} to {fmt(ci[1],10000) if ci else 'unavailable'} |\n"
    else:findings='No candidate has an evaluable primary return. No return, IC, confidence interval or overlap statistic is filled with a synthetic value. The exact blockers are in `results/history_data_audit.json`.\n'
    readme=f"# Cross-stock lead–lag study\n\n{status}\n\n{findings}\n\n{final_text}\n\nThe method ranks stocks using weighted smoothed returns of other stocks that historically led them. The executed controls represent inspected public teaching/student formulas; the implemented network adapts [Bennett, Cucuringu and Reinert(2022)](https://arxiv.org/abs/2201.08283). The claim is bounded to inspected public submissions, not global novelty or undisclosed private libraries.\n\nRead `SUBMISSION.md`, `research/method.md`, `research/overlap_audit.md` and `REPRODUCE.md`. Run `python -m factorlab.cli --root . verify` after installing the pinned environment. Raw market inputs and third-party PDFs/source snapshots are withheld from the archive; the full local work directory preserves them and the detailed simulated ledgers.\n\nCurrent distribution status is recorded in `RELEASE_STATUS.json`. Metrics preserve their original research-time publication fields.\n"
    (root/'README.md').write_text(readme)
    overlap_text='# Distinctness and matched overlap audit\n\nThe exclusion map covers inspected public course/student code and failed candidates. Private generated libraries remain unknown. A directed other-stock return graph changes the information relation; renaming or residualizing an own-stock formula would not. Low empirical correlation alone is insufficient.\n\n| Candidate | Control | Median absolute Spearman | Mean top-tail Jaccard | Matched dates |\n|---|---|---:|---:|---:|\n'
    for row in overlaps:overlap_text+=f"| {row['candidate_id']} | {row['control_id']} | {fmt(row['median_absolute_rho'])} | {fmt(row['mean_tail_jaccard'])} | {row['matched_dates']} |\n"
    overlap_text+='\nThe 0.80 absolute median threshold includes sign-reversed similarity. Daily files retain conditional event correlations and matched counts. Controls implement disclosed representative formulas; incomplete private expressions cannot be tested. The common-execution existing-signal account, frozen own-stock ablations, seeded leader permutation, and training-fitted score projection are recorded in the metrics artifact.\n\n'+findings
    (root/'research/overlap_audit.md').write_text(overlap_text)
    method=(root/'research/method.md').read_text();review=(root/'research/implementation_reference.md').read_text() if (root/'research/implementation_reference.md').exists() else ''
    submission=f"# Cross-stock lead–lag: a bounded retrospective A-share study\n\n{status}\n\nThe research asks whether past directed return links add economic value beyond inspected own-stock technical signals under a cash-constrained long-only account. Previously viewed2008–2017 dates support development diagnostics;2018–2019,2020–2021 and2022–2023 form the frozen validation folds. The primary result uses actual simulated net account returns, not overlapping forward-label spreads.\n\n## Complete candidate comparison\n\n{table}\n\n{findings}\n\n## One frozen final check\n\n{final_text}\n\n## Method, intuition and implementation\n\n{method}\n\n## Implementation reference\n\n{review}\n\n## Reproducibility and limitations\n\n`results/metrics.json` is the sole validated input to this report and its summary plots. Unavailable fields remain null with reasons. The18-slot registry, append-only experiment ledger, data fingerprints and exposure ledger are supplied. Original source files were preserved. Anonymous public downloads were supplemented with exchange rights-issue records and issuer special-dividend announcements; no student credentials were used.\n\nDaily-bar fills, conservative dividend provisions, annual sector snapshots and unverified archival vendor revisions limit interpretation. Costs, cash drag, failed fills and lot constraints are economic outcomes, not reasons to replace the method. The September interval contains only seven sessions and overlaps earlier student study coverage through September23. Independent download does not restore an untouched holdout. A new, adequately long, frozen future sample would be needed for a stronger claim; no future monitoring was scheduled.\n\nExact tested commands, exit codes, rights boundaries and package checks are recorded in `REPRODUCE.md` and `release/review_checklist.md`. The archive excludes raw provider panels, licensed course cache, third-party source files and PDFs, and detailed price-bearing ledgers whose redistribution rights were not established. Full local private outputs remain available in the work directory.\n\nCurrent distribution status is recorded in `RELEASE_STATUS.json`.\n"
    (root/'SUBMISSION.md').write_text(submission)
    chinese=f"# 中文提交摘要\n\n研究结论：`{outcome}`。选定方法：`{m['method_selected'] or '无可评估候选'}`；通过验证：`{str(m['validation_qualified']).lower()}`。\n\n本研究检验股票之间的收益领先—滞后关系。先用过去的数据估计有向关联，再用领先股票的平滑收益为目标股票打分。它区别于已检查公开作业中以股票自身价格、成交量和缺口为主的指标，但不声称全球首创，也不声称覆盖未公开公式。\n\n本研究实施1个机制族、6个版本，保留18个Holm检验名额。若全部未通过验证，仍按预定的验证期平均净超额收益选择最佳可评估版本；选择不等于验证成功。\n\n{table}\n\n{final_text}\n\n采用历史成分、次日执行、现金与股数账本、双边费用、停牌/涨跌停和容量约束。历史区间已有课程研究暴露；2026年9月21日至10月7日实际只有7个交易日，且部分日期与已有研究重叠。原始行情与第三方资料不进入发布压缩包；复现入口和限制见REPRODUCE.md。\n\n发布状态见 RELEASE_STATUS.json；指标保留研究完成时的发布字段。\n"
    (root/'SUMMARY_ZH.md').write_text(chinese)
    (root/'release').mkdir(exist_ok=True)
    # Plot only values already present in the validated artifact.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,4.6));valid=[r for r in m['candidate_results'] if r.get('mean_net_active') is not None]
    if valid:
        means=[r['mean_net_active']*1e4 for r in valid];ax.barh([r['candidate_id'] for r in valid],means,color=['#be7255' if x<0 else '#397e8d' for x in means]);ax.axvline(0,color='#555',lw=.8);ax.set_xlabel('Pooled validation mean net active return (bp/day)');ax.set_title('Frozen candidate batch · 2018–2023 · retrospective evidence')
    else:
        ax.axis('off');ax.text(.05,.72,'No evaluable candidate',size=22);ax.text(.05,.47,'Data/accounting integrity gate blocked returns.\nMissing performance is unavailable, not zero.',size=12);ax.set_title('Completed audit; no manufactured performance')
    fig.tight_layout();path=root/'results/figures';path.mkdir(exist_ok=True);fig.savefig(path/'validation.png',dpi=160);plt.close(fig)
    if final and final.get('evaluated'):
        import pandas as pd
        daily=pd.DataFrame(final['daily']);daily.to_csv(root/'results/final_daily_summary.csv',index=False)
        fig,ax=plt.subplots(figsize=(9,4.6))
        labels=[str(x)[5:] for x in daily.date]
        ax.plot(labels,(daily.net_equity/1e6-1)*100,marker='o',label='Net account')
        ax.plot(labels,(daily.gross_same_fills_equity/1e6-1)*100,marker='.',label='Gross, same fills')
        ax.plot(labels,((1+daily.benchmark_return).cumprod()-1)*100,marker='.',label='Investable benchmark')
        ax.axhline(0,color='#555',lw=.8);ax.set_ylabel('Actual period return (%)');ax.set_title('One frozen method · seven sessions · no annualization');ax.legend();fig.tight_layout();fig.savefig(path/'final_period.png',dpi=160);plt.close(fig)
    dump(root/'results/report_provenance.json',{'metrics_sha256':digest(root/'results/metrics.json'),'report_sources':['results/metrics.json','research/method.md','research/implementation_reference.md'],'raw_market_files_read':False,'final_labels_read':False})
    return {'outcome':outcome,'report':'SUBMISSION.md','method_selected':m['method_selected']}
