#!/usr/bin/env python3
"""Fail-closed, byte-consistent automatic master promotion transaction.

Only accepts evidence of actual pinned-source browser import/export executed in
THIS read-only workflow run. NEVER changes production CSV HOLD flags. Publisher
reruns these deterministic checks in a separate trusted write-permission job.
Failing at any point leaves the old site unchanged (atomic git commit/push).
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys, tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from sync_upstream import project

class PromotionHold(Exception):pass
SOURCES={'pokemon':'src/data/pokemon.json','pokemonsJa':'src/i18n/ja/pokemons.json',
         'dataJa':'src/i18n/ja/data.json','skillsJa':'src/i18n/ja/skills.json',
         'subskillType':'src/util/SubSkill.ts'}
FROZEN=('CSV_SCHEMA.json','VALIDATOR.py','SPECIES_AUDIT.py',
        'PROTOTYPE_EXPORT_GATE.py','RELEASE_EXPORT_GATE.py')

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def raw_json(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
def canonical_digest(obj):return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def need(x,msg):
    if not x:raise PromotionHold(msg)

def validate_package(bundle,site,*,run_id,base_sha,upstream_code_dir=None):
    bundle,site=Path(bundle),Path(site)
    assert_files={k:bundle/k for k in ('MASTER_DATA.candidate.json','UPSTREAM_DIFF.json','PROMOTION_PROOF.json',
        'AUTO_VECTORS.csv','VECTOR_COVERAGE.json','PROBE_RESULT.json','roundtrip_export.csv',
        'LIVE_PROBE_RESULT.json','live_roundtrip_export.csv','UPSTREAM_PREFLIGHT.json')}
    assert_files.update({k:bundle/'upstream_source'/k for k in SOURCES.values()})
    for name,path in assert_files.items():need(path.is_file(),f'MISSING_EVIDENCE:{name}')
    proof=load(assert_files['PROMOTION_PROOF.json']);candidate=load(assert_files['MASTER_DATA.candidate.json'])
    diff=load(assert_files['UPSTREAM_DIFF.json']);coverage=load(assert_files['VECTOR_COVERAGE.json'])
    probe=load(assert_files['PROBE_RESULT.json']);preflight=load(assert_files['UPSTREAM_PREFLIGHT.json'])
    version=load(site/'kit-assets/KIT_VERSION.json');old=load(site/'kit-assets/MASTER_DATA.json')
    need(version.get('kitVersion')=='0.12.0-prototype' and
         version.get('productionCsvAllowed') is False and
         version.get('compatibilityVerified') is False and
         'HOLD' in version.get('status',''), 'PRODUCTION_HOLD_NOT_INTACT')
    need(proof.get('schemaVersion')=='pokesleep-auto-promotion-proof-v1','PROOF_SCHEMA')
    need(str(proof.get('runId'))==str(run_id) and str(proof.get('baseGitHubSha'))==str(base_sha),'CROSS_RUN_OR_BASE_REPLAY')
    commit=proof.get('sourceCommit')
    need(isinstance(commit,str) and bool(re.fullmatch(r'[0-9a-f]{40}',commit)),'INVALID_SOURCE_COMMIT')
    for a,b in [('candidateSha256','MASTER_DATA.candidate.json'),('diffSha256','UPSTREAM_DIFF.json'),
                ('vectorCsvSha256','AUTO_VECTORS.csv'),('coverageSha256','VECTOR_COVERAGE.json'),
                ('browserProbeSha256','PROBE_RESULT.json'),('browserExportSha256','roundtrip_export.csv'),('liveBrowserProbeSha256','LIVE_PROBE_RESULT.json'),
                ('liveBrowserExportSha256','live_roundtrip_export.csv'),
                ('preflightSha256','UPSTREAM_PREFLIGHT.json')]:
        need(proof.get(a)==digest(assert_files[b]),'PROOF_HASH_MISMATCH:'+a)
    for a,b in [('csvSchemaSha256','CSV_SCHEMA.json'),('csvExporterSha256','VALIDATOR.py')]:
        need(proof.get(a)==digest(site/'kit-assets'/b),'FROZEN_CONTRACT_CHANGED:'+b)
    need(proof.get('actualUpstreamSourceBuildServed') is True and
         proof.get('actualUpstreamImporterExecuted') is True and
         proof.get('strictImportExportMatch') is True and
         proof.get('browserMocked') is False and
         proof.get('liveImporterVerified') is True and
         proof.get('liveImporterUrl')=='https://nitoyon.github.io/pokesleep-tool/iv/index.ja.html' and
         proof.get('productionCsvAllowed') is False,'REAL_E2E_PROOF_MISSING')
    need(probe.get('status')=='UI_IMPORT_EXPORT_MATCH' and
         probe.get('reason')=='STRICT_CSV_ROUNDTRIP_MATCH' and
         probe.get('upstreamImporterExecuted') is True and
         probe.get('importRoundTripExact') is True and
         probe.get('mockOnly') is False and probe.get('httpStatus')==200,
         'ACTUAL_IMPORT_EXPORT_UNVERIFIED')
    live_probe=load(assert_files['LIVE_PROBE_RESULT.json'])
    need(live_probe.get('status')=='UI_IMPORT_EXPORT_MATCH' and
         live_probe.get('reason')=='STRICT_CSV_ROUNDTRIP_MATCH' and
         live_probe.get('targetUrl')=='https://nitoyon.github.io/pokesleep-tool/iv/index.ja.html' and
         live_probe.get('upstreamImporterExecuted') is True and
         live_probe.get('importRoundTripExact') is True and
         live_probe.get('mockOnly') is False and live_probe.get('httpStatus')==200,
         'REAL_PUBLIC_IMPORTER_NOT_VERIFIED')
    from csv import reader
    with open(assert_files['AUTO_VECTORS.csv'],encoding='utf-8',newline='') as f: rows=list(reader(f))
    with open(assert_files['roundtrip_export.csv'],encoding='utf-8-sig',newline='') as f: exported=list(reader(f))
    with open(assert_files['live_roundtrip_export.csv'],encoding='utf-8-sig',newline='') as f: live_exported=list(reader(f))
    need(rows==exported==live_exported and len(rows)>=3 and all(len(x)==16 for x in rows),'IMPORT_EXPORT_VALUES_DIFFER')
    need(coverage.get('rows')==len(rows)-1 and probe.get('inputCsvRowCount')==len(rows)-1 and live_probe.get('inputCsvRowCount')==len(rows)-1 and
         proof.get('verifiedTestVectors')==len(rows)-1,'VECTOR_COUNT_MISMATCH')
    need(coverage.get('csvSha256')==digest(assert_files['AUTO_VECTORS.csv']),'VECTOR_COVERAGE_SHA')
    # Rebuild vector contents using the frozen Validator, rather than trusting
    # claims in the read-only worker's coverage metadata.
    from build_auto_vectors import build as rebuild_vectors
    with tempfile.TemporaryDirectory(prefix='recheck-autovectors-') as td:
        td=Path(td)
        replay_coverage=rebuild_vectors(assert_files['MASTER_DATA.candidate.json'],
            assert_files['UPSTREAM_DIFF.json'],td/'vectors.csv',td/'coverage.json')
        need((td/'vectors.csv').read_bytes()==assert_files['AUTO_VECTORS.csv'].read_bytes(),
            'CHANGED_FEATURE_VECTORS_NOT_REPRODUCIBLE')
        need(replay_coverage==coverage,'VECTOR_COVERAGE_NOT_REPRODUCIBLE')
    for key,cover in [('addedSpecies','coveredNewSpecies'),('newIngredientKeys','coveredNewIngredientKeys'),('newSubskillKeys','coveredNewSubskillKeys')]:
        need(sorted(diff.get(key,[]))==sorted(coverage.get(cover,[])),'INCOMPLETE_COVERAGE:'+key)
    need(preflight.get('status')=='UPSTREAM_TESTS_PASS_IMPORT_E2E_REQUIRED' and
         preflight.get('sourceCommit')==commit and not preflight.get('errors'), 'PINNED_SOURCE_TEST_FAILED')
    need(candidate.get('provenance',{}).get('sourceCommit')==commit and diff.get('sourceCommit')==commit,'CANDIDATE_SOURCE_PIN')
    need(proof.get('sourceCodeSha256') and re.fullmatch('[0-9a-f]{64}',proof['sourceCodeSha256']), 'SOURCE_CODE_FINGERPRINT_MISSING')
    # In release CI we independently re-fetch the exact immutable upstream git
    # commit and inspect its code fingerprint WITHOUT executing upstream code.
    if upstream_code_dir is not None:
        import subprocess
        from import_compat_gate import inspect_code
        root=Path(upstream_code_dir)
        head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
        need(head==commit,'PINNED_SOURCE_CHECKOUT_MISMATCH')
        need(inspect_code(root)['sourceCodeSha256']==proof['sourceCodeSha256'],'UPSTREAM_CODE_FINGERPRINT_MISMATCH')
        for label,name in SOURCES.items():need(digest(root/name)==digest(assert_files[name]),'UPSTREAM_REAL_SOURCE_MISMATCH:'+label)
    # Recreate the candidate from the pinned verified source data and TypeScript skill definitions; do not
    # execute any upstream Python/Node in the privileged publication process.
    actual_sha=candidate['provenance'].get('sourceFilesSha256',{})
    for label,path in SOURCES.items():need(actual_sha.get(label)==digest(assert_files[path]),'UPSTREAM_SOURCE_MISMATCH:'+label)
    synthetic_root=bundle/'upstream_source'
    replay,_=project(synthetic_root,old,allow_fixture=True)
    replay['provenance']['sourceCommit']=commit
    need(replay==candidate,'SOURCE_PROJECTION_NOT_REPRODUCIBLE')
    legacy={p['name_en']:p for p in old['pokemon']};new={p['name_en']:p for p in candidate['pokemon']}
    added=sorted(set(new)-set(legacy));removed=sorted(set(legacy)-set(new))
    need(added==diff['addedSpecies'] and removed==diff['removedSpecies'] and
         len(candidate['pokemon'])==diff['sourcePokemonCount'] and
         len(old['pokemon'])==diff['previousPokemonCount'], 'INACCURATE_SPECIES_DIFF')
    # Block all removals, nature-key changes, unsupported structural rewrites.
    need(not removed and not diff['removedIngredientKeys'] and not diff['removedSubskillKeys'] and
         not diff['newNatureKeys'] and not diff['removedNatureKeys'], 'DANGEROUS_REMOVAL_OR_NATURE_CHANGE')
    need(added or diff['changedSpecies'] or diff['newIngredientKeys'] or diff['newSubskillKeys'] or
         diff['changedIngredientTranslations'] or diff['changedSubskillTranslations'] or diff['changedNatureTranslations'],
         'NO_CHANGE_NO_PROMOTION')
    # Old records must not disappear from the candidate silently.
    need(all(x in new for x in legacy),'OLD_SPECIES_MISSING')
    return proof,candidate,diff,version

def build_patch(bundle,site,out,*,run_id,base_sha,release_date=None,upstream_code_dir=None):
    bundle,site,out=Path(bundle),Path(site),Path(out)
    proof,master,diff,version=validate_package(bundle,site,run_id=run_id,base_sha=base_sha,upstream_code_dir=upstream_code_dir)
    out.mkdir(parents=True,exist_ok=True)
    old_version=deepcopy(version)
    commit=proof['sourceCommit']
    # The staged master is unapproved until this point; annotate the PROMOTED
    # development version accurately without changing the source candidate.
    master=deepcopy(master)
    master['provenance']['origin']='pokesleep-tool (automatically validated development master)'
    master['provenance']['verification']='PINNED_SOURCE_AND_LIVE_PUBLIC_IMPORTER_CSV_ROUNDTRIP_PASS; PRODUCTION_CSV_HOLD'
    master['provenance']['importerProofSha256']=digest(bundle/'PROMOTION_PROOF.json')
    # Never promote an older baseline as a new source. Commit timestamps are not
    # a trustworthy ordering, but identical SHA replay must be blocked.
    need(version.get('sourceCommit')!=commit,'SAME_SOURCE_ALREADY_PROMOTED')
    version=deepcopy(version)
    version['asOf']=release_date or datetime.now(timezone.utc).date().isoformat()
    version['sourceCommit']=commit
    version['siteHotfixId']='v08c-autopromote-'+commit[:12]
    version['assetSha256']['MASTER_DATA.json']=canonical_digest(master)
    version['rawAssetSha256']['MASTER_DATA.json']=hashlib.sha256(raw_json(master)).hexdigest()
    version['status']='PROTOTYPE ONLY / HOLD - pinned-source and public-importer CSV fixture roundtrip tested; full production CSV compatibility NOT verified'
    version['compatibilityVerified']=False
    version['productionCsvAllowed']=False
    version['masterVerifiedAgainstLive']=False
    # The source master becomes an accepted version of the _development_ kit;
    # canonical and raw hashes are intentionally separate.
    master_bytes=raw_json(master);version_bytes=raw_json(version)
    need(canonical_digest(load(site/'kit-assets/CSV_SCHEMA.json'))==old_version['assetSha256']['CSV_SCHEMA.json'], 'FROZEN_CSV_SCHEMA_CANONICAL_HASH_CHANGED')
    need(old_version['assetSha256']['MASTER_DATA.json']==canonical_digest(load(site/'kit-assets/MASTER_DATA.json')),
         'BASELINE_MASTER_CANONICAL_HASH_INVALID')
    app=(site/'app.js').read_text(encoding='utf-8')
    def replace_const(name,newvalue,source):
        pattern=r"(?m)^(const "+re.escape(name)+r" = ')[^']+(';)$"
        fixed,n=re.subn(pattern,lambda m:m.group(1)+newvalue+m.group(2),source)
        need(n==1,'APP_PIN_NOT_UNIQUE:'+name)
        return fixed
    app=replace_const('SITE_HOTFIX_ID',version['siteHotfixId'],app)
    app=replace_const('KIT_VERSION_RAW_SHA256',hashlib.sha256(version_bytes).hexdigest(),app)
    # Force a new module request for both app and its ZIP dependency after an update.
    url_tag='auto-'+commit[:12]
    app,n=re.subn(r"(from '\./zip-store\.js\?v=)[^']+(';)",lambda m:m.group(1)+url_tag+m.group(2),app)
    need(n==1,'ZIP_MODULE_CACHE_PIN_UNEXPECTED')
    html=(site/'index.html').read_text(encoding='utf-8')
    for filename in ('styles.css','app.js','update-status.js'):
        pat=r'('+re.escape(filename)+r'\?v=)[^"\s]+'
        html,n=re.subn(pat,lambda m:m.group(1)+url_tag,html)
        need(n==1,'INDEX_CACHE_PIN_UNEXPECTED:'+filename)
    # Atomic on-disk patch generation. It DOES NOT edit the site; the trusted
    # CI script commits it as a single Git commit only after independent check.
    patches={'kit-assets/MASTER_DATA.json':master_bytes,'kit-assets/KIT_VERSION.json':version_bytes,
             'app.js':app.encode('utf-8'),'index.html':html.encode('utf-8')}
    for name,data in patches.items():
        p=out/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    receipt={'schemaVersion':'pokesleep-automatic-promotion-plan-v1',
      'status':'VERIFIED_PATCH_STAGED_NOT_DEPLOYED','commit':commit,'baseGithubSha':base_sha,
      'runId':str(run_id),'affectedFiles':{name:hashlib.sha256(data).hexdigest() for name,data in patches.items()},
      'addedSpecies':diff['addedSpecies'],'productionCsvAllowed':False,'compatibilityVerified':False,
      'kitVersion':'0.12.0-prototype'}
    (out/'AUTO_PROMOTION_PLAN.json').write_bytes(raw_json(receipt))
    return receipt

def main():
    a=argparse.ArgumentParser()
    a.add_argument('--bundle',required=True);a.add_argument('--site',required=True);a.add_argument('--out',required=True)
    a.add_argument('--run-id',required=True);a.add_argument('--base-sha',required=True)
    a.add_argument('--upstream-code-dir',required=True,help='Independent immutable upstream git checkout, no source execution')
    z=a.parse_args()
    try:
        print(json.dumps(build_patch(z.bundle,z.site,z.out,run_id=z.run_id,base_sha=z.base_sha,upstream_code_dir=z.upstream_code_dir),ensure_ascii=False));return 0
    except (PromotionHold,ValueError,OSError,KeyError,TypeError) as e:
        print('HOLD / NO MASTER CHANGE: '+str(e),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
