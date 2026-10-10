#!/usr/bin/env python3
"""Strictly sanitize the read-only CI result before publishing status JSON.

The write-permission job may ONLY commit this validated status file, never the
candidate master or any kit asset. A failed/missing audit becomes attention.
"""
import argparse
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import re

def fallback(reason='WATCH_JOB_FAILED'):
    return dict(schemaVersion='pokesleep-upstream-status-v1',state='attention',
      checkedAt=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),
      upstreamCommit=None,activeSourceCommit=None,reasonCode=reason,
      message='上流データの定期監視に失敗しました',
      details='GitHub Actionsの実行に問題が発生しました。既存の公開マスターは変更していません。ログを確認してください。',
      runUrl=None,productionCsvAllowed=False)

def sanitize(raw,audit_success,run_id):
    if not audit_success or not isinstance(raw,dict) or raw.get('schemaVersion')!='pokesleep-upstream-status-v1' or raw.get('productionCsvAllowed') is not False:
        raw=fallback()
    else:
        state=raw.get('state');ts=raw.get('checkedAt')
        try:
            checked=datetime.fromisoformat(ts.replace('Z','+00:00'))
            valid_time=(checked.tzinfo is not None and
                        datetime.now(timezone.utc)-timedelta(hours=2)<checked<datetime.now(timezone.utc)+timedelta(minutes=10))
        except (AttributeError, ValueError):valid_time=False
        keys=('upstreamCommit','activeSourceCommit')
        valid_commits=all(raw.get(k) is None or (isinstance(raw[k],str) and bool(re.fullmatch('[0-9a-f]{40}',raw[k]))) for k in keys)
        valid_strings=all(isinstance(raw.get(k),str) and 0<len(raw[k])<=limit for k,limit in [('reasonCode',80),('message',250),('details',1000)])
        if state not in ('healthy','attention') or not valid_time or not valid_commits or not valid_strings:
            raw=fallback('MALFORMED_AUDIT_OUTPUT')
    clean={k:raw[k] for k in ('schemaVersion','state','checkedAt','upstreamCommit','activeSourceCommit','reasonCode','message','details','productionCsvAllowed')}
    clean['runUrl']=f'https://github.com/meka-create/pokesleep-ai-csv-test/actions/runs/{run_id}' if str(run_id).isdigit() else None
    return clean

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    p.add_argument('--audit-result',required=True);p.add_argument('--run-id',default='')
    a=p.parse_args()
    try: raw=json.loads(Path(a.input).read_text(encoding='utf-8'))
    except (OSError,ValueError):raw=None
    s=sanitize(raw,a.audit_result=='success',a.run_id)
    dest=Path(a.out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(s,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(s['state'],s['reasonCode'])
if __name__=='__main__':main()
