#!/usr/bin/env python3
"""Read-only Pokémon Sleep upstream structural monitor (NOT CSV importer).

Publishes only public-safe update-status.json; NEVER edits the master, the kit,
script pins or production CSV permission. Failure -> explicit attention.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from master_diff import audit

STATUS_SCHEMA = 'pokesleep-upstream-status-v1'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def run(site, upstream, now=None, audit_fn=audit):
    when = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    stamp = when.isoformat().replace('+00:00','Z')
    output = {
        'schemaVersion': STATUS_SCHEMA,
        'state': 'attention', 'checkedAt': stamp,
        'upstreamCommit': None, 'activeSourceCommit': None,
        'reasonCode': 'UPSTREAM_PREFLIGHT_FAILED',
        'message': '更新状況の確認が必要です。',
        'details': '上流データのチェックに失敗しました。',
        'runUrl': None, 'productionCsvAllowed': False,
        'monitorMode': 'READ_ONLY_NO_IMPORTER_NO_AUTOPROMOTION'
    }
    try:
        base = site / 'kit-assets' / 'MASTER_DATA.json'
        version = json.loads((site / 'kit-assets' / 'KIT_VERSION.json').read_text(encoding='utf-8'))
        if version['productionCsvAllowed'] is not False or version['compatibilityVerified'] is not False or version['masterVerifiedAgainstLive'] is not False or 'HOLD' not in version['status']:
            raise ValueError('CSV HOLD integrity failure')
        if sha256(base.read_bytes()) != version['rawAssetSha256']['MASTER_DATA.json']:
            raise ValueError('MASTER_DATA raw SHA integrity failure')
        report = audit_fn(upstream, base, sha256(base.read_bytes()))
        commit = report.get('sourceCommit')
        if not isinstance(commit,str) or len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):
            raise ValueError('Invalid pinned upstream git SHA')
        output['upstreamCommit'] = commit
        if report.get('productionCsvAllowed') is not False or report.get('NOT_IMPORTER_VERIFIED') is not True:
            raise ValueError('Upstream report invalid or permission changed')
        if report['status'] == 'SOURCE_PROJECTION_MATCH_HOLD':
            output.update(state='healthy',reasonCode='UPSTREAM_STRUCTURE_MATCH',
                          message='上流データの確認が完了しました。', details='構造上の変更は見つかっていません。CSV互換性は未検証です。')
        elif report['status'] == 'DIFFERENCES_FOUND_HOLD':
            output.update(state='attention',reasonCode='UPDATE_REQUIRES_VALIDATION',
                          message='上流データの確認が必要です。',details='上流データに差分があります。自動更新せず確認待ちです。')
        else:
            raise ValueError('Unknown upstream report status')
    except Exception as error:
        output.update(state='attention',reasonCode='UPSTREAM_PREFLIGHT_FAILED',
                      message='更新状況の確認が必要です。', details='上流監視が正常に完了しませんでした。')
        # Diagnostics only appear in Actions logs, not the publicly hosted status JSON.
        print('MONITOR_ERROR:', type(error).__name__, str(error))
    return output


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--site',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result=run(args.site,args.upstream)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('MONITOR_RESULT:',result['state'],result['reasonCode'])
    # Attention is a valid result, not proof of upstream compatibility.

if __name__=='__main__':main()
