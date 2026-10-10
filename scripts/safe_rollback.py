#!/usr/bin/env python3
"""Guarded revert of only our own HEAD commit after PROVEN mixed assets.

Never force push; never revert an unrelated user commit. In a CI script GitHub
push is rejected if branch advanced, so no unrelated changes are overwritten.
"""
import argparse,json,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

ALLOWED={'app.js','index.html','update-status.json','kit-assets/MASTER_DATA.json','kit-assets/KIT_VERSION.json'}
def git(repo,*args):
    return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
def guard(repo,commit):
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('Invalid commit')
    if git(repo,'rev-parse','HEAD')!=commit:raise ValueError('HEAD changed - no rollback')
    remote=dict((ref,sha) for sha,ref in (line.split('\t',1) for line in git(repo,'ls-remote','origin','refs/heads/main').splitlines())).get('refs/heads/main')
    if remote!=commit:raise ValueError('Remote HEAD changed - no rollback')
    if git(repo,'status','--porcelain','--untracked-files=no')!='':raise ValueError('Dirty working tree - no rollback')
    changed=set(git(repo,'diff-tree','--no-commit-id','--name-only','-r','HEAD').splitlines())
    if not changed or not changed<=ALLOWED or not {'kit-assets/MASTER_DATA.json','kit-assets/KIT_VERSION.json'}<=changed:
        raise ValueError('Not an auto master update commit')
    return changed

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repo',required=True);p.add_argument('--expected-commit',required=True)
    p.add_argument('--confirmed-health-evidence',required=True)
    a=p.parse_args();repo=Path(a.repo)
    try:
        evidence=json.loads(Path(a.confirmed_health_evidence).read_text(encoding='utf-8'))
        checks=evidence.get('checks')
        if evidence.get('result')!='MIXED_ASSETS_CONFIRMED' or not isinstance(checks,list) or len(checks)<3 or any(c.get('result')!='MIXED_ASSETS_CONFIRMED' for c in checks[-3:]):
            raise ValueError('No verified mixed-assets failure')
        changed=guard(repo,a.expected_commit)
        subprocess.run(['git','-C',str(repo),'revert','--no-commit',a.expected_commit],check=True)
        status_path=repo/'update-status.json'
        status={'schemaVersion':'pokesleep-upstream-status-v1','state':'attention',
                'checkedAt':datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),
                'upstreamCommit':None,'activeSourceCommit':None,'reasonCode':'AUTO_DEPLOY_ROLLED_BACK',
                'message':'自動更新の配信に問題があり、前のデータへ戻しました',
                'details':'新しいHTMLとキットの内容に不一致が確認されたため更新を取り消しました。GitHub Actionsのログを確認してください。',
                'runUrl':None,'productionCsvAllowed':False}
        status_path.write_text(json.dumps(status,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
        subprocess.run(['git','-C',str(repo),'add','--',*sorted(ALLOWED)],check=True)
        subprocess.run(['git','-C',str(repo),'commit','-m','rollback: verified asset deployment failure (HOLD)'],check=True)
        subprocess.run(['git','-C',str(repo),'push','origin','HEAD:main'],check=True)
        print('ROLLED_BACK_AFTER_CONFIRMED_MIXED_ASSETS',a.expected_commit)
        return 0
    except Exception as e:
        print('ROLLBACK_FAIL_CLOSED:',repr(e),file=sys.stderr)
        return 2
if __name__=='__main__':raise SystemExit(main())
