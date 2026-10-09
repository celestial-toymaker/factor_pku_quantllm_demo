import argparse,json,sys,traceback
from pathlib import Path
from .common import append,now

def main():
    p=argparse.ArgumentParser(description='Unpublished bounded research; final requires a frozen method')
    p.add_argument('--root',default='.')
    p.add_argument('command',choices=['audit-cache','acquire-history','audit-data','freeze-protocol','validate','freeze-finalist','final-evaluate','report','verify'])
    p.add_argument('--cache-dir');args=p.parse_args();root=Path(args.root).resolve();started=now();exitcode=0;summary=None
    try:
        if args.command=='audit-cache':
            from .cache import audit_cache
            if not args.cache_dir:p.error('--cache-dir is required')
            summary=audit_cache(root,args.cache_dir)
        elif args.command=='acquire-history':
            from .provider import acquire
            exitcode=0 if acquire(root)==0 else 2;summary={'exit_code':exitcode}
        elif args.command=='audit-data':
            from .data import assemble
            summary=assemble(root);exitcode=0 if summary['integrity_pass'] else 2
        elif args.command=='freeze-protocol':
            from .protocol import freeze_protocol
            summary=freeze_protocol(root)
        elif args.command=='validate':
            from .evaluate import historical
            result=historical(root);summary={k:result[k] for k in ['research_outcome','method_selected','validation_qualified']};exitcode=2 if result['research_outcome']=='BLOCKED_DATA' else 0
        elif args.command=='freeze-finalist':
            from .protocol import freeze_finalist
            summary=freeze_finalist(root)
        elif args.command=='final-evaluate':
            from .evaluate import final_evaluation
            result=final_evaluation(root);summary={k:result[k] for k in ['research_outcome','method_selected','validation_qualified']};exitcode=2 if result['research_outcome']=='BLOCKED_DATA' else 0
        elif args.command=='report':
            from .report import render
            summary=render(root)
        elif args.command=='verify':
            from .verify import verify
            summary=verify(root);exitcode=0 if summary['ok'] else 2
    except Exception as e:
        exitcode=3;summary={'error':type(e).__name__,'message':str(e)};traceback.print_exc()
    append(root/'logs/commands.jsonl',{'started':started,'finished':now(),'argv':sys.argv,'command':args.command,'exit_code':exitcode,'summary':summary})
    # Keep terminal summaries compact; full artifacts retain details.
    print(json.dumps(summary,default=str,ensure_ascii=False)[:5000]);raise SystemExit(exitcode)

if __name__=='__main__':main()
