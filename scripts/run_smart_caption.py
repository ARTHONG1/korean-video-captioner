"""Entry point for the resumable, Codex-driven caption workflow."""
import argparse, json
from pathlib import Path
from kvc.caption_state import initialize_caption_workflow, next_caption_action

def main() -> int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    i=sub.add_parser('init'); i.add_argument('--input',required=True); i.add_argument('--run',required=True)
    n=sub.add_parser('next'); n.add_argument('--state',required=True)
    a=p.parse_args()
    if a.cmd=='init': result={'state':str(initialize_caption_workflow(Path(a.input),Path(a.run)))}
    else: result=next_caption_action(Path(a.state))
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
