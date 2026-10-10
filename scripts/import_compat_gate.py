#!/usr/bin/env python3
"""Fail-closed upstream/importer fingerprint and release-evidence gate.

This gate does not execute the real pokesleep-tool importer. It checks that the
staged master, frozen upstream code, local CSV schema and exporter all match an
independently produced importer/deployed-app acceptance record. Without that
record the update MUST stay in staging. It never flips production flags.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HEADER = ['ニックネーム','ポケモン','レベル','スキルレベル','食材1','食材2','食材3',
          'メインスキル','せいかく','Lv10','Lv25','Lv50','Lv70','Lv80','一緒に眠った時間','色違い']
SOURCES = {'pokemon':'src/data/pokemon.json','pokemonsJa':'src/i18n/ja/pokemons.json',
           'dataJa':'src/i18n/ja/data.json','skillsJa':'src/i18n/ja/skills.json'}

class GateError(Exception):
    pass

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def actual_git_commit(repo, *, test_fixture=False):
    if test_fixture:
        return 'TEST-FIXTURE-NOT-A-REAL-COMMIT'
    try:
        commit = subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError) as e:
        raise GateError('git checkoutのcommitを取得できません') from e
    if not re.fullmatch(r'[a-f0-9]{40}',commit):
        raise GateError('上流のcommitが不正です')
    return commit

def inspect_code(repo):
    """Conservatively lock the ENTIRE TS/JS source; unknown importer path cannot bypass."""
    paths = []
    for parent in ('src','iv'):
        root = repo / parent
        if root.exists():
            paths.extend(p for p in root.rglob('*') if p.is_file() and p.suffix in {'.ts','.tsx','.js','.jsx','.mjs','.cjs'})
    paths.sort(key=lambda p: p.relative_to(repo).as_posix())
    if not paths:
        raise GateError('上流にインポータを含む実装コードが見つかりません')
    code_files = []
    importer_hits = []
    aggregate = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(repo).as_posix()
        content = path.read_bytes()
        digest = sha256(content)
        code_files.append({'path':relative,'sha256':digest})
        aggregate.update(relative.encode('utf-8')+b'\0'+bytes.fromhex(digest)+b'\n')
        if re.search(rb'BoxImporter|BoxExporter|CsvFormatter|(?:csv|CSV).{0,30}(?:import|parse|format)|(?:import|parse).{0,30}(?:csv|CSV)', content):
            importer_hits.append(relative)
    return {'sourceCodeSha256':aggregate.hexdigest(),'sourceCodeFileCount':len(paths),
            'importerRelatedFiles':importer_hits, 'codeFiles':code_files}

def gate(repo, master_path, schema_path, exporter_path, evidence_path=None, *, test_fixture=False):
    repo=Path(repo).resolve()
    master_path=Path(master_path)
    schema_path=Path(schema_path)
    exporter_path=Path(exporter_path)
    master=read_json(master_path)
    schema=read_json(schema_path)
    commit=actual_git_commit(repo,test_fixture=test_fixture)
    errors=[]
    provenance=master.get('provenance',{})
    if provenance.get('sourceCommit')!=commit:
        errors.append('STAGED_COMMIT_MISMATCH')
    for label,relative in SOURCES.items():
        path=repo/relative
        if not path.is_file() or provenance.get('sourceFilesSha256',{}).get(label)!=sha256(path.read_bytes()):
            errors.append('STAGED_SOURCE_MISMATCH:'+label)
    if schema.get('header')!=HEADER or schema.get('encoding')!='UTF-8 without BOM':
        errors.append('CSV_SCHEMA_MISMATCH')
    code=inspect_code(repo)
    if not code['importerRelatedFiles']:
        errors.append('IMPORTER_NOT_IDENTIFIED')
    master_digest=sha256(master_path.read_bytes())
    schema_digest=sha256(schema_path.read_bytes())
    exporter_digest=sha256(exporter_path.read_bytes())
    evidence={}
    if evidence_path is not None and Path(evidence_path).is_file():
        evidence=read_json(evidence_path)
    else:
        errors.append('NO_REAL_IMPORTER_EVIDENCE')
    expected={'sourceCommit':commit,'sourceCodeSha256':code['sourceCodeSha256'],
              'masterSha256':master_digest,'csvSchemaSha256':schema_digest,
              'csvExporterSha256':exporter_digest}
    if evidence:
        for key,value in expected.items():
            if evidence.get(key)!=value:
                errors.append('EVIDENCE_MISMATCH:'+key)
        if evidence.get('upstreamImporterExecuted') is not True:
            errors.append('IMPORTER_NOT_EXECUTED')
        if evidence.get('importRoundTripExact') is not True:
            errors.append('IMPORT_ROUNDTRIP_NOT_EXACT')
        if evidence.get('deployedAppChecked') is not True or not evidence.get('deployedAppReference'):
            errors.append('DEPLOYED_APP_NOT_CHECKED')
        if evidence.get('verifiedTestVectors',0)<1:
            errors.append('NO_VERIFIED_TEST_VECTORS')
    output={'schemaVersion':'import-gate-v0.3','sourceCommit':commit,
            'masterSha256':master_digest,'csvSchemaSha256':schema_digest,
            'csvExporterSha256':exporter_digest,
            'sourceCodeSha256':code['sourceCodeSha256'],
            'sourceCodeFileCount':code['sourceCodeFileCount'],
            'importerRelatedFiles':code['importerRelatedFiles'],
            'validationErrors':errors,
            'status':'HOLD' if errors else 'READY_FOR_MANUAL_PROMOTION',
            'productionCsvAllowed':False,
            'note':'Importer integration requires independent executed evidence. READY is not auto-deployment.'}
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--upstream',required=True)
    p.add_argument('--candidate-master',default='upstream_staging/MASTER_DATA.candidate.json')
    p.add_argument('--schema',default='site/kit-assets/CSV_SCHEMA.json')
    p.add_argument('--exporter',default='site/kit-assets/VALIDATOR.py')
    p.add_argument('--evidence',default=None)
    p.add_argument('--out',default='upstream_staging/IMPORT_COMPAT_GATE.json')
    p.add_argument('--require-ready',action='store_true')
    args=p.parse_args()
    try:
        report=gate(args.upstream,args.candidate_master,args.schema,args.exporter,args.evidence)
        path=Path(args.out);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('status','sourceCommit','sourceCodeFileCount','importerRelatedFiles','validationErrors','productionCsvAllowed')},ensure_ascii=False))
        return 2 if args.require_ready and report['status']!='READY_FOR_MANUAL_PROMOTION' else 0
    except (GateError,OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as e:
        print('FAIL_CLOSED: インポータ整合性ゲートを実行できません:',e,file=sys.stderr)
        return 2
if __name__=='__main__':raise SystemExit(main())
