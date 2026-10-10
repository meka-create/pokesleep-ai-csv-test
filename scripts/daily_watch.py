#!/usr/bin/env python3
"""Read-only daily upstream audit. NO importer E2E proof => NO promotion.

Only the GitHub status publisher, in a separate job with write permission,
may write update-status.json. Untrusted upstream code runs with read-only perms.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from sync_upstream import load_json, project
from upstream_preflight import preflight
from importer_surface_inventory import inventory
from import_compat_gate import gate

STATES = {'healthy', 'attention'}
def write_json(path, item):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(item,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def changed(diff):
    return bool(diff['addedSpecies'] or diff['removedSpecies'] or diff['changedSpecies'] or any(
        diff[k] for k in ('newIngredientKeys','removedIngredientKeys','changedIngredientTranslations',
          'newSubskillKeys','removedSubskillKeys','changedSubskillTranslations','newNatureKeys',
          'removedNatureKeys','changedNatureTranslations')))

def execute(upstream,kit,out, *, fixture=False, preflight_fn=preflight):
    """A result is healthy only if upstream projection agrees with active master.
    Do not treat a successful source build as CSV importer-compatibility evidence.
    """
    upstream,kit,out=Path(upstream),Path(kit),Path(out)
    output={'schemaVersion':'pokesleep-upstream-status-v1','state':'attention',
            'checkedAt':datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),
            'upstreamCommit':None,'activeSourceCommit':None,'reasonCode':'CHECK_FAILED',
            'message':'上流の自動確認に失敗しました',
            'details':'前回の検証済みマスターを維持しています。GitHub Actionsのログを確認してください。',
            'runUrl':None,'productionCsvAllowed':False}
    try:
        current=load_json(kit/'MASTER_DATA.json')
        version=load_json(kit/'KIT_VERSION.json')
        if version.get('productionCsvAllowed') is not False or version.get('compatibilityVerified') is not False:
            raise ValueError('HOLD条件の不一致')
        output['activeSourceCommit']=version.get('sourceCommit')
        candidate,diff=project(upstream,current,allow_fixture=fixture)
        output['upstreamCommit']=diff['sourceCommit']
        write_json(out/'UPSTREAM_DIFF.json',diff)
        write_json(out/'MASTER_DATA.candidate.json',candidate)
        if not changed(diff):
            output.update(state='healthy',reasonCode='NO_CHANGE',
                          message='上流データの更新確認は正常です',
                          details='現在の公開マスターと上流の対象データに差分はありません。本番CSVのHOLD状態は継続しています。')
        else:
            counts=[]
            for key,label in [('addedSpecies','新ポケモン'),('newIngredientKeys','新食材'),('newSubskillKeys','新サブスキル')]:
                if diff[key]:counts.append(f'{label} {len(diff[key])}件')
            if diff['changedSpecies']:counts.append(f'既存ポケモン変更 {len(diff["changedSpecies"])}件')
            summary='、'.join(counts) if counts else '日本語訳・既存定義などの変更'
            output.update(state='attention',reasonCode='UPDATE_REQUIRES_VALIDATION',
              message='上流データに変更があります。検証待ちです',
              details=f'{summary}を検出しました。互換性の自動証明が完了するまで、従来のマスターを使用します。')
            preflight_report=preflight_fn(upstream,out/'preflight')
            write_json(out/'UPSTREAM_PREFLIGHT_SUMMARY.json',preflight_report)
            if preflight_report.get('status')!='UPSTREAM_TESTS_PASS_IMPORT_E2E_REQUIRED':
                output.update(reasonCode='UPSTREAM_PREFLIGHT_FAILED',
                    message='新データの検証でエラーが発生しました',
                    details='上流のビルド・テストが失敗しました。既存のマスターを維持し、更新内容の確認が必要です。')
            else:
                # This gate deliberately holds without separately executed, pinned
                # importer/deployed-site evidence. Never synthesize such evidence.
                gate_report=gate(upstream,out/'MASTER_DATA.candidate.json',
                    kit/'CSV_SCHEMA.json',kit/'VALIDATOR.py',test_fixture=fixture)
                write_json(out/'IMPORT_COMPAT_GATE.json',gate_report)
                if gate_report.get('status')!='READY_FOR_MANUAL_PROMOTION':
                    output.update(reasonCode='IMPORTER_E2E_NOT_VERIFIED',
                        message='新しいデータを検出しました。互換性の確認が必要です',
                        details=f'{summary}。上流のビルド・テストは通過しましたが、実CSV取り込み・書き戻しの自動証明が不足しています。公開マスターは更新していません。')
                else:
                    # Even a manually supplied gate record is not a trusted
                    # automated end-to-end test. Never auto-promote here.
                    output.update(reasonCode='AUTOMATIC_RELEASE_NOT_VERIFIED',
                        message='新しいデータがあります。公開条件の確認が必要です',
                        details='CSV互換性ゲートは通過しましたが、自動公開に必要な同一実行内の証拠・配布前検証が未実装です。公開マスターは更新していません。')
    except Exception as error:
        output['details']=f'監視処理で {type(error).__name__} が発生しました。GitHub Actionsの証拠を確認してください。マスターは変更していません。'
        write_json(out/'WATCH_ERROR.json',{'type':type(error).__name__,'error':str(error)[:1500]})
    write_json(out/'update-status.json',output)
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--upstream',required=True);p.add_argument('--kit-dir',required=True)
    p.add_argument('--out',default='upstream_staging');a=p.parse_args()
    result=execute(a.upstream,a.kit_dir,a.out)
    print(json.dumps({k:result[k] for k in ('state','reasonCode','upstreamCommit','message')},ensure_ascii=False))
    # A detected upstream change needing E2E is NOT a healthy release.
    # A valid status JSON is still published, and job remains informative.
    return 0 if result['reasonCode'] in ('NO_CHANGE','IMPORTER_E2E_NOT_VERIFIED','AUTOMATIC_RELEASE_NOT_VERIFIED','UPSTREAM_PREFLIGHT_FAILED','UPDATE_REQUIRES_VALIDATION') else 2
if __name__=='__main__':raise SystemExit(main())
