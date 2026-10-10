#!/usr/bin/env python3
"""Exercise actual CSV import/export in a preview of the EXACT pinned source build.

This script never fakes an importer. On missing Chromium, broken UI, incomplete
vectors, wrong git HEAD or a failed roundtrip it exits HOLD without a proof.
Must run in read-only CI audit job, never in a job with repository write token.
"""
import argparse, hashlib, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path
from urllib.error import URLError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'probe'))
sys.path.insert(0,str(ROOT/'scripts'))
from run_import_probe import browser_probe
from import_compat_gate import inspect_code


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path,ob):Path(path).write_text(json.dumps(ob,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def execute(upstream,candidate,diff,schema,validator,preflight,vector,coverage,out, *, run_id,base_sha):
    upstream=Path(upstream).resolve();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    commit=subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()
    if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('Unpinned upstream')
    if load(preflight).get('status')!='UPSTREAM_TESTS_PASS_IMPORT_E2E_REQUIRED' or load(preflight).get('sourceCommit')!=commit:
        raise ValueError('Preflight is not passing at this commit')
    cv=load(coverage);d=load(diff);candidate_json=load(candidate)
    if candidate_json.get('provenance',{}).get('sourceCommit')!=commit or d.get('sourceCommit')!=commit:
        raise ValueError('Source provenance mismatch')
    if cv['csvSha256']!=sha(vector) or cv['rows']<2:
        raise ValueError('Missing or incomplete test vector coverage')
    if sorted(cv['coveredNewSpecies'])!=sorted(d['addedSpecies']) or sorted(cv['coveredNewIngredientKeys'])!=sorted(d['newIngredientKeys']) or sorted(cv['coveredNewSubskillKeys'])!=sorted(d['newSubskillKeys']):
        raise ValueError('Not all new features have a CSV test')
    html=upstream/'dist/iv/index.ja.html'
    if not html.is_file():raise ValueError('Pinned upstream dist not built')
    # Vite base is /pokesleep-tool/. It must be served through actual Vite
    # preview, not page.set_content or a mocked importer.
    port=4173
    cmd=['npm','run','preview','--','--host','127.0.0.1','--port',str(port),'--strictPort']
    proc=subprocess.Popen(cmd,cwd=upstream,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,start_new_session=True)
    url=f'http://127.0.0.1:{port}/pokesleep-tool/iv/index.ja.html'
    try:
        online=False
        for _ in range(100):
            if proc.poll() is not None:break
            try:
                with urllib.request.urlopen(url,timeout=1) as response:
                    if response.status==200 and 'html' in response.headers.get('content-type','').lower():
                        online=True;break
            except (URLError,TimeoutError,OSError):pass
            time.sleep(.3)
        if not online:raise RuntimeError('Real upstream preview unavailable')
        result_code=browser_probe(url,out/'browser',input_csv=vector)
        probe=load(out/'browser/PROBE_RESULT.json')
        if result_code!=0 or probe.get('status')!='UI_IMPORT_EXPORT_MATCH' or probe.get('mockOnly') is not False or probe.get('upstreamImporterExecuted') is not True or probe.get('importRoundTripExact') is not True or probe.get('inputCsvRowCount')!=cv['rows']:
            raise ValueError('Real pinned-source importer E2E did not pass: '+str(probe.get('reason')))
        export_file=out/'browser/roundtrip_export.csv'
        if sha(export_file)!=sha(vector):
            # CSV parser value equality is acceptable for newline-only differences.
            from run_import_probe import compare_roundtrip
            exact,_=compare_roundtrip(vector,export_file)
            if not exact:raise ValueError('Export values differ from import fixture')
        # A pinned source build may precede the REAL public importer's deploy.
        # Both must accept precisely the same candidate-bound CSV; otherwise
        # publishing a new master may break the user's actual pokesleep-tool.
        public_url='https://nitoyon.github.io/pokesleep-tool/iv/index.ja.html'
        live_code=browser_probe(public_url,out/'live',input_csv=vector)
        live=load(out/'live/PROBE_RESULT.json')
        if live_code!=0 or live.get('targetUrl')!=public_url or live.get('status')!='UI_IMPORT_EXPORT_MATCH' or live.get('mockOnly') is not False or live.get('upstreamImporterExecuted') is not True or live.get('importRoundTripExact') is not True or live.get('inputCsvRowCount')!=cv['rows']:
            raise ValueError('Actual public pokesleep-tool importer is not ready: '+str(live.get('reason')))
        from run_import_probe import compare_roundtrip
        live_export=out/'live/roundtrip_export.csv'
        exact,_=compare_roundtrip(vector,live_export)
        if not exact:raise ValueError('Actual public importer CSV data differs')
        code=inspect_code(upstream)
        proof={'schemaVersion':'pokesleep-auto-promotion-proof-v1','sourceCommit':commit,
            'baseGitHubSha':base_sha,'runId':str(run_id),'sourceCodeSha256':code['sourceCodeSha256'],
            'candidateSha256':sha(candidate),'diffSha256':sha(diff),
            'csvSchemaSha256':sha(schema),'csvExporterSha256':sha(validator),
            'vectorCsvSha256':sha(vector),'coverageSha256':sha(coverage),
            'browserProbeSha256':sha(out/'browser/PROBE_RESULT.json'),
            'browserExportSha256':sha(export_file),'preflightSha256':sha(preflight),
            'liveBrowserProbeSha256':sha(out/'live/PROBE_RESULT.json'),
            'liveBrowserExportSha256':sha(live_export),'liveImporterVerified':True,
            'liveImporterUrl':public_url,
            'verifiedTestVectors':cv['rows'], 'actualUpstreamSourceBuildServed':True,
            'actualUpstreamImporterExecuted':True,'strictImportExportMatch':True,
            'browserMocked':False, 'productionCsvAllowed':False,
            'attestation':'Two REAL import/export probes: pinned source build and public importer; this does not prove exact public app commit'}
        save(out/'PROMOTION_PROOF.json',proof)
        return proof
    finally:
        proc.terminate()
        try:proc.wait(timeout=4)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()

def main():
    p=argparse.ArgumentParser()
    for a in ('upstream','candidate','diff','schema','validator','preflight','vector','coverage','out','run-id','base-sha'):
        p.add_argument('--'+a,required=True)
    a=p.parse_args()
    try:
        print(json.dumps(execute(a.upstream,a.candidate,a.diff,a.schema,a.validator,a.preflight,a.vector,a.coverage,a.out,run_id=a.run_id,base_sha=a.base_sha),ensure_ascii=False))
        return 0
    except Exception as ex:
        print('HOLD_NO_AUTOPROMOTION: '+repr(ex),file=sys.stderr)
        return 2
if __name__=='__main__':sys.exit(main())
