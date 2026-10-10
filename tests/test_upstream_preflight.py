"""Local fixture tests; do NOT claim the real upstream was executed."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from upstream_preflight import preflight, STEPS
from importer_surface_inventory import inventory

class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name)/'upstream'
        self.repo.mkdir()
        def run(*args):
            subprocess.run(['git',*args],cwd=self.repo,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        run('init');run('config','user.email','dev@example.test');run('config','user.name','Fixture')
        (self.repo/'package.json').write_text(json.dumps({'scripts':{a:'echo ok' for a in ('typecheck','test','build')}}))
        (self.repo/'package-lock.json').write_text('{}')
        path=self.repo/'src/box/BoxImporter.ts'
        path.parent.mkdir(parents=True)
        path.write_text('export const BoxImporter = { parseCsv: (x:string) => x };\n// CSV ニックネーム')
        run('add','.');run('commit','-m','test fixture only')
        self.out=Path(self.tmp.name)/'evidence'
    def test_simulated_pass_never_calls_it_import_e2e(self):
        calls=[]
        def mock_executor(cmd,repo,timeout):
            calls.append(cmd)
            return 0,'SIMULATED TEST ONLY\n'
        res=preflight(self.repo,self.out,executor=mock_executor)
        self.assertEqual(res['status'],'UPSTREAM_TESTS_PASS_IMPORT_E2E_REQUIRED')
        self.assertTrue(res['doesNotVerifyCsvImport'])
        self.assertIs(res['productionCsvAllowed'],False)
        self.assertEqual(calls,[cmd for _,cmd in STEPS])
    def test_first_failure_stops_remaining_steps(self):
        seq=[]
        def mock_executor(cmd,repo,timeout):
            seq.append(cmd)
            if len(seq)==2: return 1, 'fixture failure\n'
            return 0,'fixture ok\n'
        res=preflight(self.repo,self.out,executor=mock_executor)
        self.assertEqual(res['status'],'HOLD')
        self.assertEqual(len(res['steps']),2)
        self.assertTrue((self.out/'UPSTREAM_PREFLIGHT.json').is_file())
    def test_dirty_tracked_source_holds(self):
        (self.repo/'package.json').write_text('{}')
        res=preflight(self.repo,self.out,executor=lambda *a: (0,'should not run'))
        self.assertEqual(res['status'],'HOLD')
        self.assertIn('local edits',res['errors'][0])
    def test_missing_node_scripts_holds(self):
        (self.repo/'package.json').write_text('{}')
        subprocess.run(['git','add','.'],cwd=self.repo,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','commit','-m','remove scripts'],cwd=self.repo,check=True,stdout=subprocess.DEVNULL)
        res=preflight(self.repo,self.out,executor=lambda *a: (0,'should not run'))
        self.assertEqual(res['status'],'HOLD')
        self.assertIn('scripts',res['errors'][0])
    def test_inventory_only_is_not_importer_execution(self):
        res=inventory(self.repo)
        self.assertEqual(res['candidateCount'],1)
        self.assertFalse(res['actualImporterExecuted'])
        self.assertFalse(res['productionCsvAllowed'])
        self.assertIn('box_importer',res['candidateFiles'][0]['occurrences'][0]['categories'])
    def test_empty_inventory_cannot_falsely_claim_import(self):
        (self.repo/'src/box/BoxImporter.ts').unlink()
        res=inventory(self.repo)
        self.assertEqual(res['candidateCount'],0)
        self.assertFalse(res['actualImporterExecuted'])
    def test_workflow_readonly_audit_and_proof_bound_writer(self):
        import yaml
        wf=yaml.load((ROOT/'.github/workflows/upstream-watch.yml').read_text(),Loader=yaml.BaseLoader)
        audit=wf['jobs']['audit'];publisher=wf['jobs']['publish']
        self.assertEqual(audit['permissions']['contents'],'read')
        self.assertEqual(publisher['permissions']['contents'],'write')
        self.assertIn('daily_watch.py',str(audit['steps']))
        self.assertIn('git add -- update-status.json app.js index.html kit-assets/MASTER_DATA.json kit-assets/KIT_VERSION.json',str(publisher['steps']))
        self.assertIn('publish_auto_result.py',str(publisher['steps']))
        self.assertIn('run_pinned_import_e2e.py',str(audit['steps']))
        self.assertNotIn('push',wf['on'])
        self.assertNotIn('pull_request_target',wf['on'])
        v=json.loads(next(x for x in (ROOT/'site/kit-assets/KIT_VERSION.json', ROOT/'kit-assets/KIT_VERSION.json') if x.exists()).read_text())
        self.assertFalse(v['productionCsvAllowed'])
        self.assertFalse(v['compatibilityVerified'])
        self.assertFalse(v['masterVerifiedAgainstLive'])

if __name__=='__main__':unittest.main()
