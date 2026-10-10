"""Regression: no stale success, corrupted masters, unsafe pushes, or fabricated Pages health."""
import json,pathlib,shutil,subprocess,sys,tempfile,unittest
from datetime import datetime,timezone
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import audit_daily_health as audit

class PostpublishAuditTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root=pathlib.Path(self.t.name)
        (self.root/'kit-assets').mkdir()
        for p in ('app.js','index.html','update-status.json'):
            shutil.copyfile(ROOT/p,self.root/p)
        for p in (ROOT/'kit-assets').iterdir():
            if p.is_file():shutil.copyfile(p,self.root/'kit-assets'/p.name)
        self.now=datetime(2026,10,10,6,0,tzinfo=timezone.utc)
        s=audit.load(self.root/'update-status.json')
        s.update(checkedAt='2026-10-10T04:46:48Z',state='healthy',reasonCode='NO_CHANGE',
                 runUrl='https://github.com/meka-create/pokesleep-ai-csv-test/actions/runs/38025210341')
        (self.root/'update-status.json').write_text(json.dumps(s)+'\n')
        self.runs={'workflow_runs':[{'id':38025210341,'status':'completed','conclusion':'success',
           'event':'workflow_dispatch','head_branch':'main','path':'.github/workflows/upstream-watch.yml',
           'created_at':'2026-10-10T04:46:08Z'}]}
        self.git('init','-q')
        self.git('config','user.name','Fixture')
        self.git('config','user.email','unit@example.invalid')
        self.commit('baseline')
    def git(self,*args):
        subprocess.run(['git','-C',str(self.root),*args],check=True,capture_output=True)
    def commit(self,msg):
        self.git('add','.')
        self.git('commit','-qm',msg)
    def run_audit(self,**kw):
        return audit.execute(self.root,now=self.now,runs=self.runs,check_public_files=False,**kw)
    def test_no_change_healthy(self):
        result=self.run_audit()
        self.assertEqual('PASS',result['state'],result['problems'])
        self.assertEqual(249,result['local']['speciesCount'])
    def test_failure_masking_rejected(self):
        self.runs['workflow_runs'][0]['conclusion']='failure'
        self.assertIn('GITHUB_WATCH_LATEST_NOT_SUCCESS',self.run_audit()['problems'])
    def test_stale_date_rejected(self):
        s=audit.load(self.root/'update-status.json');s['checkedAt']='2026-10-08T00:00:00Z'
        (self.root/'update-status.json').write_text(json.dumps(s))
        self.assertIn('UPSTREAM_WATCH_STALE_OR_FUTURE',self.run_audit()['problems'])
    def test_nonhealthy_status_rejected(self):
        s=audit.load(self.root/'update-status.json');s.update(state='attention',reasonCode='UPDATE_REQUIRES_VALIDATION')
        (self.root/'update-status.json').write_text(json.dumps(s))
        self.assertIn('UPSTREAM_WATCH_REQUIRES_ATTENTION',self.run_audit()['problems'])
    def test_mismatched_run_reference_rejected(self):
        self.runs['workflow_runs'][0]['id']=1234
        self.assertIn('STATUS_LATEST_RUN_NOT_MATCHED',self.run_audit()['problems'])
    def test_bad_master_sha_rejected(self):
        p=self.root/'kit-assets/MASTER_DATA.json';master=audit.load(p)
        master['pokemon'].pop();p.write_text(json.dumps(master))
        errors=self.run_audit()['problems']
        self.assertIn('KIT_ASSET_HASH_MISMATCH:MASTER_DATA.json',errors)
        self.assertIn('MASTER_SPECIES_COUNT_REGRESSED',errors)
    def test_hold_disabled_rejected(self):
        p=self.root/'kit-assets/KIT_VERSION.json';v=audit.load(p)
        v['productionCsvAllowed']=True;p.write_text(json.dumps(v))
        self.assertIn('CSV_HOLD_BROKEN',self.run_audit()['problems'])
    def test_app_version_pin_rejected(self):
        p=self.root/'app.js';p.write_text(p.read_text().replace('KIT_VERSION_RAW_SHA256','WRONG_SHA_CONST'))
        self.assertIn('APP_VERSION_RAW_PIN_MISMATCH',self.run_audit()['problems'])
    def test_auto_commit_forbidden_path(self):
        (self.root/'unrelated.txt').write_text('not allowed')
        self.commit('auto: accidental write')
        self.assertTrue(any(s.startswith('AUTO_COMMIT_CHANGED_FORBIDDEN_FILES:')
                            for s in self.run_audit()['problems']))
    def test_public_status_must_match_exactly(self):
        healthy=lambda *args:('ALL_EXPECTED_ASSETS_LIVE',{})
        bad=lambda *args:b'outdated'
        problem=[]
        audit.check_public(self.root,problem,attempts=1,delay=0,classifier=healthy,fetcher=bad)
        self.assertIn('PUBLIC_PAGES_OR_STATUS_NOT_CONFIRMED',problem)
        good=lambda *args:(self.root/'update-status.json').read_bytes()
        problem=[]
        audit.check_public(self.root,problem,attempts=1,delay=0,classifier=healthy,fetcher=good)
        self.assertFalse(problem)
    def test_pages_eventual_consistency_recovered(self):
        observations=iter([('MIXED_ASSETS_CONFIRMED',{}),('ALL_EXPECTED_ASSETS_LIVE',{})])
        with patch.object(audit.time,'sleep',return_value=None):
            result=audit.execute(self.root,now=self.now,runs=self.runs,
                 public_attempts=2,public_delay=0,
                 public_classifier=lambda *args:next(observations),
                 public_fetcher=lambda *args:(self.root/'update-status.json').read_bytes())
        self.assertEqual('PASS',result['state'],result['problems'])
        self.assertEqual(2,len(result['publicObservations']))

    def test_previous_jst_day_inside_34h_is_not_pass(self):
        # 10 Oct 15:00 JST audit, 9 Oct 13:46 JST run and healthy status.
        status=audit.load(self.root/'update-status.json')
        status['checkedAt']='2026-10-09T04:46:48Z'
        (self.root/'update-status.json').write_text(json.dumps(status))
        self.runs['workflow_runs'][0]['created_at']='2026-10-09T04:46:08Z'
        result=self.run_audit()
        self.assertEqual('DELAYED',result['state'],result)
        self.assertIn('SCHEDULED_JST_DAY_STATUS_MISSING',result['problems'])
        self.assertIn('SCHEDULED_JST_DAY_RUN_MISSING',result['problems'])
        self.assertNotIn('UPSTREAM_WATCH_STALE_OR_FUTURE',result['problems'])

    def test_utc_previous_date_but_jst_today_is_accepted(self):
        self.now=datetime(2026,10,11,0,0,tzinfo=timezone.utc)  # 09:00 JST
        status=audit.load(self.root/'update-status.json')
        status['checkedAt']='2026-10-10T19:10:00Z'  # 04:10 JST on 11 Oct
        (self.root/'update-status.json').write_text(json.dumps(status))
        self.runs['workflow_runs'][0]['created_at']='2026-10-10T19:00:08Z'
        self.assertEqual('PASS',self.run_audit()['state'])

    def test_last_day_of_month_and_year(self):
        self.assertEqual('2025-12-31',audit.scheduled_jst_day(
            datetime(2025,12,31,18,30,tzinfo=timezone.utc)).isoformat()) # 03:30 on Jan 1
        self.assertEqual('2026-01-01',audit.scheduled_jst_day(
            datetime(2025,12,31,19,0,tzinfo=timezone.utc)).isoformat()) # 04:00 on Jan 1

    def test_late_running_cycle_not_a_success_or_failure(self):
        status=audit.load(self.root/'update-status.json')
        status['checkedAt']='2026-10-09T04:46:48Z'
        (self.root/'update-status.json').write_text(json.dumps(status))
        self.runs['workflow_runs'][0].update(status='in_progress',conclusion=None)
        result=self.run_audit()
        self.assertEqual('DELAYED',result['state'],result)
        self.assertIn('SCHEDULED_JST_DAY_RUN_IN_PROGRESS',result['problems'])

    def test_actual_failed_today_distinct_from_delay(self):
        self.runs['workflow_runs'][0].update(status='completed',conclusion='failure')
        result=self.run_audit()
        self.assertEqual('ATTENTION',result['state'],result)
        self.assertIn('GITHUB_WATCH_LATEST_NOT_SUCCESS',result['problems'])

    def test_latest_today_success_but_yesterday_status_is_failure(self):
        status=audit.load(self.root/'update-status.json')
        status['checkedAt']='2026-10-09T18:30:00Z'  # 03:30 JST today
        (self.root/'update-status.json').write_text(json.dumps(status))
        result=self.run_audit()
        self.assertEqual('ATTENTION',result['state'],result)
        self.assertIn('SCHEDULED_JST_DAY_STATUS_MISSING',result['problems'])

    def test_offset_time_and_naive_timestamp(self):
        status=audit.load(self.root/'update-status.json')
        status['checkedAt']='2026-10-10T13:46:48+09:00'
        (self.root/'update-status.json').write_text(json.dumps(status))
        self.assertEqual('PASS',self.run_audit()['state'])
        status['checkedAt']='2026-10-10T04:46:48'
        (self.root/'update-status.json').write_text(json.dumps(status))
        self.assertIn('UPSTREAM_WATCH_TIMESTAMP_INVALID',self.run_audit()['problems'])

    def test_missing_created_at_fails_closed(self):
        self.runs['workflow_runs'][0].pop('created_at')
        self.assertIn('GITHUB_WATCH_CREATED_AT_INVALID',self.run_audit()['problems'])

    def test_run_list_is_not_order_dependent(self):
        self.runs['workflow_runs'].insert(0,{
            'id':12,'status':'completed','conclusion':'success',
            'event':'schedule','head_branch':'main',
            'path':'.github/workflows/upstream-watch.yml',
            'created_at':'2026-10-09T04:00:00Z'
        })
        self.assertEqual('PASS',self.run_audit()['state'])

    def test_before_daily_due_hour_uses_previous_day(self):
        self.assertEqual('2026-10-09',audit.scheduled_jst_day(
            datetime(2026,10,09,18,59,tzinfo=timezone.utc)).isoformat())
        self.assertEqual('2026-10-10',audit.scheduled_jst_day(
            datetime(2026,10,09,19,0,tzinfo=timezone.utc)).isoformat())

    def test_unrelated_corruption_is_not_classified_as_delay(self):
        status=audit.load(self.root/'update-status.json')
        status['checkedAt']='2026-10-09T04:46:48Z'
        (self.root/'update-status.json').write_text(json.dumps(status))
        self.runs['workflow_runs'][0]['created_at']='2026-10-09T04:46:08Z'
        version=self.root/'kit-assets/KIT_VERSION.json'
        v=audit.load(version);v['productionCsvAllowed']=True
        version.write_text(json.dumps(v))
        result=self.run_audit()
        self.assertEqual('ATTENTION',result['state'],result)
        self.assertIn('CSV_HOLD_BROKEN',result['problems'])

if __name__=='__main__':unittest.main()
