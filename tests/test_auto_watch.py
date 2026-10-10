"""Deterministic offline tests for monitoring and public status publication.
No test asserts that real upstream importer E2E exists.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from daily_watch import execute
from publish_watch_status import sanitize
from test_upstream_sync import UpstreamSyncTests

class WatchTests(UpstreamSyncTests):
    def setUp(self):
        super().setUp()
        self.kit=next(p for p in (ROOT/'site/kit-assets',ROOT/'kit-assets') if p.is_dir())
        self.out=self.base/'out'
    def test_no_change_is_healthy_and_never_promotes(self):
        status=execute(self.base,self.kit,self.out,fixture=True)
        self.assertEqual(status['state'],'healthy',status)
        self.assertEqual(status['reasonCode'],'NO_CHANGE')
        self.assertFalse(status['productionCsvAllowed'])
        self.assertTrue((self.out/'MASTER_DATA.candidate.json').is_file())
    def test_new_subskill_requires_verification_and_old_master_unchanged(self):
        self.data['subskill']['Future Nonstandard Subskill']='未来サブスキル'
        self.write()
        before=(self.kit/'MASTER_DATA.json').read_bytes()
        calls=[]
        def preflight_stub(*args):
            calls.append(1)
            return {'status':'HOLD'}
        status=execute(self.base,self.kit,self.out,fixture=True,preflight_fn=preflight_stub)
        self.assertEqual(status['state'],'attention')
        self.assertEqual(status['reasonCode'],'UPSTREAM_PREFLIGHT_FAILED')
        self.assertEqual(len(calls),1)
        self.assertIn('Future Nonstandard Subskill',json.loads((self.out/'UPSTREAM_DIFF.json').read_text())['newSubskillKeys'])
        self.assertEqual(before,(self.kit/'MASTER_DATA.json').read_bytes())
    def test_corrupt_upstream_warns_and_does_not_change_master(self):
        self.names.pop('Bulbasaur');self.write()
        status=execute(self.base,self.kit,self.out,fixture=True)
        self.assertEqual(status['state'],'attention')
        self.assertEqual(status['reasonCode'],'CHECK_FAILED')
        self.assertTrue((self.out/'WATCH_ERROR.json').is_file())
    def test_valid_status_publisher_and_failure_override(self):
        raw={'schemaVersion':'pokesleep-upstream-status-v1','state':'healthy',
          'checkedAt':'2099-01-01T00:00:00Z','upstreamCommit':None,'activeSourceCommit':None,
          'reasonCode':'NO_CHANGE','message':'OK','details':'ok','productionCsvAllowed':False}
        self.assertEqual(sanitize(raw,True,'123')['state'],'attention')
        raw['checkedAt']=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
        s=sanitize(raw,True,'123')
        self.assertEqual(s['state'],'healthy')
        self.assertEqual(s['runUrl'],'https://github.com/meka-create/pokesleep-ai-csv-test/actions/runs/123')
        self.assertEqual(sanitize(raw,False,'123')['state'],'attention')
        raw['productionCsvAllowed']=True
        self.assertEqual(sanitize(raw,True,'123')['state'],'attention')
    def test_workflow_is_jst_0400_and_write_isolated(self):
        text=(ROOT/'.github/workflows/upstream-watch.yml').read_text()
        self.assertIn("cron: '0 19 * * *'",text)
        self.assertIn('publish:',text)
        self.assertIn('contents: write',text)
        self.assertIn('contents: read',text)
        self.assertIn('git add -- update-status.json app.js index.html kit-assets/MASTER_DATA.json kit-assets/KIT_VERSION.json',text)
        self.assertIn('real browser success',text)
        self.assertIn('contents: read',text)
        self.assertNotIn('git add .',text)

if __name__=='__main__':unittest.main()
