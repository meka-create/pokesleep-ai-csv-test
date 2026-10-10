"""Synthetic OFFLINE contract tests; artificial E2E records are NOT real proof."""
import copy,hashlib,json, pathlib, shutil, sys, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from build_auto_vectors import build as build_vectors
from verified_auto_promotion import build_patch, PromotionHold, raw_json, canonical_digest, digest
from publish_auto_result import transact, execute
from verify_pages_live import classify
from sync_upstream import project
import test_upstream_sync as fixtures

SHA='a'*40
BASE='b'*40
RUN='12345'
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw_json(obj))

class AutoPromotionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        self.source=fixtures.UpstreamSyncTests();self.source.setUp();self.addCleanup(self.source.doCleanups)
        self.site=self.root/'site'
        src=ROOT/'site' if (ROOT/'site/kit-assets/MASTER_DATA.json').is_file() else ROOT
        self.real_kit=src/'kit-assets'
        self.site.mkdir()
        for f in ('app.js','index.html','zip-store.js','styles.css','update-status.js','update-status.json'):
            shutil.copy2(src/f,self.site/f)
        shutil.copytree(src/'kit-assets',self.site/'kit-assets')
        self.old=json.loads((self.site/'kit-assets/MASTER_DATA.json').read_text())
        self.expected_count=len(self.old['pokemon'])
        self.old['pokemon']=[p for p in self.old['pokemon'] if p['name_en'] not in ('Foongus','Amoonguss')]
        self.assertEqual(len(self.old['pokemon']),self.expected_count-2)
        v=json.loads((self.site/'kit-assets/KIT_VERSION.json').read_text())
        save(self.site/'kit-assets/MASTER_DATA.json',self.old)
        v['assetSha256']['MASTER_DATA.json']=canonical_digest(self.old)
        v['rawAssetSha256']['MASTER_DATA.json']=digest(self.site/'kit-assets/MASTER_DATA.json')
        save(self.site/'kit-assets/KIT_VERSION.json',v)
        self.bundle=self.root/'bundle';self.bundle.mkdir()
        for key,rel in (('pokemon','src/data/pokemon.json'),('pokemonsJa','src/i18n/ja/pokemons.json'),
                        ('dataJa','src/i18n/ja/data.json'),('skillsJa','src/i18n/ja/skills.json')):
            target=self.bundle/'upstream_source'/rel;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(self.source.base/rel,target)
        candidate,diff=project(self.source.base,self.old,allow_fixture=True)
        candidate['provenance']['sourceCommit']=SHA
        diff['sourceCommit']=SHA
        save(self.bundle/'MASTER_DATA.candidate.json',candidate)
        save(self.bundle/'UPSTREAM_DIFF.json',diff)
        self.assertEqual(diff['addedSpecies'],['Amoonguss','Foongus'])
        coverage=build_vectors(self.bundle/'MASTER_DATA.candidate.json',self.bundle/'UPSTREAM_DIFF.json',
             self.bundle/'AUTO_VECTORS.csv',self.bundle/'VECTOR_COVERAGE.json')
        self.assertGreaterEqual(coverage['rows'],3)
        shutil.copy2(self.bundle/'AUTO_VECTORS.csv',self.bundle/'roundtrip_export.csv')
        save(self.bundle/'PROBE_RESULT.json',dict(status='UI_IMPORT_EXPORT_MATCH',reason='STRICT_CSV_ROUNDTRIP_MATCH',
             upstreamImporterExecuted=True,importRoundTripExact=True,mockOnly=False,httpStatus=200,
             inputCsvRowCount=coverage['rows']))
        live=json.loads((self.bundle/'PROBE_RESULT.json').read_text())
        live['targetUrl']='https://nitoyon.github.io/pokesleep-tool/iv/index.ja.html'
        save(self.bundle/'LIVE_PROBE_RESULT.json',live)
        shutil.copy2(self.bundle/'AUTO_VECTORS.csv',self.bundle/'live_roundtrip_export.csv')
        save(self.bundle/'UPSTREAM_PREFLIGHT.json',dict(status='UPSTREAM_TESTS_PASS_IMPORT_E2E_REQUIRED',sourceCommit=SHA,errors=[]))
        names={'candidateSha256':'MASTER_DATA.candidate.json','diffSha256':'UPSTREAM_DIFF.json',
               'vectorCsvSha256':'AUTO_VECTORS.csv','coverageSha256':'VECTOR_COVERAGE.json',
               'browserProbeSha256':'PROBE_RESULT.json','browserExportSha256':'roundtrip_export.csv',
               'preflightSha256':'UPSTREAM_PREFLIGHT.json',
               'liveBrowserProbeSha256':'LIVE_PROBE_RESULT.json','liveBrowserExportSha256':'live_roundtrip_export.csv'}
        proof={a:digest(self.bundle/b) for a,b in names.items()}
        proof.update(schemaVersion='pokesleep-auto-promotion-proof-v1',sourceCommit=SHA,
            baseGitHubSha=BASE,runId=RUN,sourceCodeSha256='c'*64,
            csvSchemaSha256=digest(self.site/'kit-assets/CSV_SCHEMA.json'),
            csvExporterSha256=digest(self.site/'kit-assets/VALIDATOR.py'),
            verifiedTestVectors=coverage['rows'],actualUpstreamSourceBuildServed=True,
            actualUpstreamImporterExecuted=True,strictImportExportMatch=True,
            browserMocked=False,productionCsvAllowed=False,liveImporterVerified=True,
            liveImporterUrl='https://nitoyon.github.io/pokesleep-tool/iv/index.ja.html')
        save(self.bundle/'PROMOTION_PROOF.json',proof)
    def test_247_to_249_staged_patch_hold_and_pin(self):
        out=self.root/'staged'
        report=build_patch(self.bundle,self.site,out,run_id=RUN,base_sha=BASE,release_date='2026-10-10')
        master=json.loads((out/'kit-assets/MASTER_DATA.json').read_text())
        version=json.loads((out/'kit-assets/KIT_VERSION.json').read_text())
        self.assertEqual(len(master['pokemon']),self.expected_count)
        self.assertEqual(report['addedSpecies'],['Amoonguss','Foongus'])
        self.assertEqual(version['rawAssetSha256']['MASTER_DATA.json'],digest(out/'kit-assets/MASTER_DATA.json'))
        self.assertEqual(version['assetSha256']['MASTER_DATA.json'],canonical_digest(master))
        self.assertFalse(version['productionCsvAllowed']);self.assertFalse(version['compatibilityVerified'])
        self.assertIn('HOLD',version['status'])
        self.assertIn(digest(out/'kit-assets/KIT_VERSION.json'),(out/'app.js').read_text())
        self.assertIn('auto-'+SHA[:12],(out/'index.html').read_text())
        # Critical: generating a patch does NOT change active 247 master.
        self.assertEqual(len(json.loads((self.site/'kit-assets/MASTER_DATA.json').read_text())['pokemon']),self.expected_count-2)
        for file in ('VALIDATOR.py','CSV_SCHEMA.json','SPECIES_AUDIT.py'):
            self.assertEqual(digest(self.site/'kit-assets'/file),digest(self.real_kit/file))
    def test_missing_real_browser_proof_rejected(self):
        self.bundle.joinpath('PROBE_RESULT.json').unlink()
        with self.assertRaises(PromotionHold):build_patch(self.bundle,self.site,self.root/'out',run_id=RUN,base_sha=BASE)
    def test_fake_mock_browser_proof_rejected_even_with_hash(self):
        p=self.bundle/'PROBE_RESULT.json';o=json.loads(p.read_text());o['mockOnly']=True;save(p,o)
        proof=json.loads((self.bundle/'PROMOTION_PROOF.json').read_text());proof['browserProbeSha256']=digest(p)
        save(self.bundle/'PROMOTION_PROOF.json',proof)
        with self.assertRaisesRegex(PromotionHold,'ACTUAL_IMPORT_EXPORT_UNVERIFIED'):
            build_patch(self.bundle,self.site,self.root/'out',run_id=RUN,base_sha=BASE)
    def test_cross_run_evidence_rejected(self):
        with self.assertRaisesRegex(PromotionHold,'CROSS_RUN_OR_BASE_REPLAY'):
            build_patch(self.bundle,self.site,self.root/'out',run_id='new-run',base_sha=BASE)
    def test_changed_export_rows_rejected(self):
        with (self.bundle/'roundtrip_export.csv').open('a') as f:f.write('untrusted\n')
        proof=json.loads((self.bundle/'PROMOTION_PROOF.json').read_text());proof['browserExportSha256']=digest(self.bundle/'roundtrip_export.csv')
        save(self.bundle/'PROMOTION_PROOF.json',proof)
        with self.assertRaisesRegex(PromotionHold,'IMPORT_EXPORT_VALUES_DIFFER'):
            build_patch(self.bundle,self.site,self.root/'out',run_id=RUN,base_sha=BASE)
    def test_tampered_candidate_rejected(self):
        o=json.loads((self.bundle/'MASTER_DATA.candidate.json').read_text());o['pokemon'][0]['frequency']+=1
        save(self.bundle/'MASTER_DATA.candidate.json',o)
        proof=json.loads((self.bundle/'PROMOTION_PROOF.json').read_text());proof['candidateSha256']=digest(self.bundle/'MASTER_DATA.candidate.json')
        save(self.bundle/'PROMOTION_PROOF.json',proof)
        with self.assertRaisesRegex(PromotionHold,'SOURCE_PROJECTION_NOT_REPRODUCIBLE'):
            build_patch(self.bundle,self.site,self.root/'out',run_id=RUN,base_sha=BASE)
    def test_untrusted_source_file_changed_rejected(self):
        path=self.bundle/'upstream_source/src/data/pokemon.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(PromotionHold,'UPSTREAM_SOURCE_MISMATCH'):
            build_patch(self.bundle,self.site,self.root/'out',run_id=RUN,base_sha=BASE)
    def test_missing_public_importer_proof_rejected(self):
        (self.bundle/'LIVE_PROBE_RESULT.json').unlink()
        with self.assertRaisesRegex(PromotionHold,'MISSING_EVIDENCE'):
            build_patch(self.bundle,self.site,self.root/'out',run_id=RUN,base_sha=BASE)
    def test_public_importer_csv_mismatch_rejected_even_with_forged_hash(self):
        file=self.bundle/'live_roundtrip_export.csv'
        file.write_bytes(file.read_bytes()+b'INVALID,ROW\n')
        proof=json.loads((self.bundle/'PROMOTION_PROOF.json').read_text())
        proof['liveBrowserExportSha256']=digest(file)
        save(self.bundle/'PROMOTION_PROOF.json',proof)
        with self.assertRaisesRegex(PromotionHold,'IMPORT_EXPORT_VALUES_DIFFER'):
            build_patch(self.bundle,self.site,self.root/'out',run_id=RUN,base_sha=BASE)
    def test_reproducible_vector_check_rejects_wrong_new_species_rows(self):
        source=self.bundle/'AUTO_VECTORS.csv'
        rows=source.read_text(encoding='utf-8').splitlines()
        # Replace a new species by a known old one, while forging all meta hashes.
        source.write_text('\n'.join(x.replace('タマゲタケ','フシギダネ') for x in rows)+'\n',encoding='utf-8')
        shutil.copy2(source,self.bundle/'roundtrip_export.csv')
        shutil.copy2(source,self.bundle/'live_roundtrip_export.csv')
        coverage=json.loads((self.bundle/'VECTOR_COVERAGE.json').read_text())
        coverage['csvSha256']=digest(source)
        save(self.bundle/'VECTOR_COVERAGE.json',coverage)
        proof=json.loads((self.bundle/'PROMOTION_PROOF.json').read_text())
        for key,file in [('vectorCsvSha256','AUTO_VECTORS.csv'),('browserExportSha256','roundtrip_export.csv'),('coverageSha256','VECTOR_COVERAGE.json'),
                         ('liveBrowserExportSha256','live_roundtrip_export.csv')]:
            proof[key]=digest(self.bundle/file)
        save(self.bundle/'PROMOTION_PROOF.json',proof)
        with self.assertRaisesRegex(PromotionHold,'CHANGED_FEATURE_VECTORS_NOT_REPRODUCIBLE'):
            build_patch(self.bundle,self.site,self.root/'out',run_id=RUN,base_sha=BASE)
    def test_public_stale_html_is_never_hard_rollback(self):
        from unittest.mock import patch
        with patch('verify_pages_live.get',return_value=b'old html'):
            state,details=classify(self.site,'https://example.invalid/',SHA)
        self.assertEqual(state,'STALE_HTML_OR_PENDING_DEPLOYMENT')
    def test_public_new_html_and_wrong_script_is_confirmed_mixed(self):
        from unittest.mock import patch
        def fake_get(url):
            if 'index.html' in url:return (self.site/'index.html').read_bytes()
            if 'app.js' in url:return b'corrupt'
            return (self.site/url.split('/')[-1].split('?')[0]).read_bytes()
        with patch('verify_pages_live.get',side_effect=fake_get):
            state,details=classify(self.site,'https://example.invalid/',SHA)
        self.assertEqual(state,'MIXED_ASSETS_CONFIRMED')
        self.assertIn('app.js',details)
    def test_disk_failure_rolls_back_every_path(self):
        before={f:(self.site/f).read_bytes() for f in ('app.js','index.html','kit-assets/MASTER_DATA.json')}
        with self.assertRaisesRegex(RuntimeError,'INJECTED'):
            transact(self.site,{f:b'INVALID' for f in before},inject_failure_at=1)
        self.assertEqual(before,{f:(self.site/f).read_bytes() for f in before})
    def test_rejected_update_publishes_warning_only(self):
        status=self.root/'status.json';save(status,dict(schemaVersion='pokesleep-upstream-status-v1',state='attention',
            checkedAt='2026-10-10T00:00:00Z',upstreamCommit=None,activeSourceCommit=None,
            reasonCode='UPDATE_REQUIRES_VALIDATION',message='a',details='b',productionCsvAllowed=False))
        original={x:digest(self.site/x) for x in ('app.js','index.html','kit-assets/MASTER_DATA.json','kit-assets/KIT_VERSION.json')}
        res=execute(self.site,self.bundle,self.source.base,audit_status=status,audit_result='failure',run_id=RUN,base_sha=BASE)
        self.assertFalse(res['promoted'])
        self.assertEqual(original,{x:digest(self.site/x) for x in original})
        self.assertEqual(json.loads((self.site/'update-status.json').read_text())['state'],'attention')

if __name__=='__main__':unittest.main()
