#!/usr/bin/env python3
"""Run the real upstream project's OWN tests/build on a fixed, clean checkout.

This is a preflight, NOT our 16-column CSV importer E2E. It cannot approve
production CSV, even on PASS. Reports are developer-only GitHub Action artifacts.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

STEPS = [
    ('npm_ci', ['npm', 'ci', '--ignore-scripts']),
    ('typecheck', ['npm', 'run', 'typecheck']),
    ('unit_tests', ['npm', 'run', 'test', '--', 'run', '--reporter=dot']),
    ('build', ['npm', 'run', 'build', '--', '-l', 'silent']),
]

class PreflightError(Exception): pass

def run_command(cmd, cwd, timeout):
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                              errors='replace', timeout=timeout, check=False)
        return proc.returncode, (proc.stdout or '') + ('\n' if proc.stdout and proc.stderr else '') + (proc.stderr or '')
    except subprocess.TimeoutExpired as ex:
        return 124, f'TIMEOUT after {timeout} seconds: {ex}'
    except OSError as ex:
        return 127, f'COMMAND NOT RUN: {ex}'

def verify_checkout(repo):
    for path in ('package.json','package-lock.json'):
        if not (repo/path).is_file():
            raise PreflightError(f'Missing upstream file: {path}')
    r, head = run_command(['git','rev-parse','HEAD'],repo,20)
    if r or not re.fullmatch('[0-9a-f]{40}', head.strip()):
        raise PreflightError('Not a pinned 40-character git checkout')
    r, dirty = run_command(['git','status','--porcelain','--untracked-files=no'],repo,20)
    if r or dirty.strip():
        raise PreflightError('Tracked upstream source has local edits')
    package = json.loads((repo/'package.json').read_text(encoding='utf-8'))
    scripts = package.get('scripts',{})
    required = ('typecheck','test','build')
    if not all(isinstance(scripts.get(x),str) and scripts[x] for x in required):
        raise PreflightError('Upstream required npm scripts changed or missing')
    return head.strip(), package

def preflight(repo, out, *, executor=run_command, timeout=600):
    out = Path(out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    report = {'schemaVersion':'upstream-preflight-v0.4', 'kind':'UPSTREAM_BUILD_TEST_ONLY',
              'doesNotVerifyCsvImport':True,'productionCsvAllowed':False,
              'sourceCommit':None,'status':'HOLD', 'steps':[], 'errors':[]}
    try:
        repo=Path(repo).resolve()
        commit, package = verify_checkout(repo)
        report['sourceCommit'] = commit
        report['packageLockSha256'] = hashlib.sha256((repo/'package-lock.json').read_bytes()).hexdigest()
        report['packageJsonSha256'] = hashlib.sha256((repo/'package.json').read_bytes()).hexdigest()
        for label, cmd in STEPS:
            code, output = executor(cmd,repo,timeout)
            logfile = out/(label + '.log')
            logfile.write_text(output,encoding='utf-8')
            report['steps'].append({'name':label,'command':cmd,'exitCode':code,
                                    'logfile':logfile.name,'sha256':hashlib.sha256(output.encode()).hexdigest()})
            if code:
                report['errors'].append(f'{label}:exit_{code}')
                break
        if not report['errors'] and len(report['steps'])==len(STEPS):
            report['status'] = 'UPSTREAM_TESTS_PASS_IMPORT_E2E_REQUIRED'
    except (PreflightError,OSError,ValueError,TypeError,json.JSONDecodeError) as ex:
        report['errors'].append(str(ex))
    (out/'UPSTREAM_PREFLIGHT.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf-8')
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--upstream',required=True)
    p.add_argument('--out',default='upstream_staging/preflight')
    args=p.parse_args()
    report=preflight(args.upstream,args.out)
    print(json.dumps({k:report[k] for k in ('status','sourceCommit','errors','productionCsvAllowed')},ensure_ascii=False))
    return 0 if report['status']=='UPSTREAM_TESTS_PASS_IMPORT_E2E_REQUIRED' else 2

if __name__=='__main__': raise SystemExit(main())
