"""Read-only deployment classification and guarded local Git rollback tests."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
import verify_pages_live as pages
import safe_rollback as rollback

class PagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        (self.root/'kit-assets').mkdir()
        for name in pages.CHECK:
            (self.root/name).write_bytes(name.encode())
    def test_public_bytes_equal(self):
        def get(url):
            path=url.split('?')[0].split('/pokesleep-ai-csv-test/')[-1]
            return (self.root/path).read_bytes()
        with patch.object(pages,'get',side_effect=get):
            state,data=pages.classify(self.root,'https://example.test/pokesleep-ai-csv-test/','test')
        self.assertEqual('ALL_EXPECTED_ASSETS_LIVE',state)
        self.assertEqual({},data)
    def test_stale_never_rollback(self):
        with patch.object(pages,'get',return_value=b'old index'):
            self.assertEqual('STALE_HTML_OR_PENDING_DEPLOYMENT',pages.classify(self.root,'https://example.test/','test')[0])
    def test_transient_mixed_never_rollback(self):
        args=['verify_pages_live.py','--site',str(self.root),'--url','https://example.test/','--commit','a'*40,'--attempts','2','--delay','0','--out',str(self.root/'report.json')]
        with patch.object(sys,'argv',args),patch.object(pages,'classify',side_effect=[
             ('STALE_HTML_OR_PENDING_DEPLOYMENT',{}),('MIXED_ASSETS_CONFIRMED',{'app.js':'bad'})]),patch.object(pages.time,'sleep',return_value=None):
            self.assertEqual(3,pages.main())
        self.assertEqual('MIXED_ASSETS_NOT_STABLE',json.loads((self.root/'report.json').read_text())['result'])
    def test_consecutive_mixed_allows_guard_only(self):
        args=['verify_pages_live.py','--site',str(self.root),'--url','https://example.test/','--commit','a'*40,'--attempts','3','--delay','0','--out',str(self.root/'report.json')]
        with patch.object(sys,'argv',args),patch.object(pages,'classify',return_value=('MIXED_ASSETS_CONFIRMED',{'app.js':'bad'})),patch.object(pages.time,'sleep',return_value=None):
            self.assertEqual(2,pages.main())
    def test_network_not_rollback(self):
        with patch.object(pages,'get',side_effect=OSError('offline')):
            self.assertEqual('NETWORK_UNKNOWN',pages.classify(self.root,'https://example.test/','test')[0])

class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=pathlib.Path(self.tmp.name);self.repo=root/'repo';self.bare=root/'remote.git'
        self.git(None,'init','--bare',str(self.bare))
        self.git(None,'clone',str(self.bare),str(self.repo))
        self.git(self.repo,'checkout','-b','main')
        self.git(self.repo,'config','user.name','Test')
        self.git(self.repo,'config','user.email','tester@example.invalid')
        (self.repo/'kit-assets').mkdir()
        self.paths=['app.js','index.html','kit-assets/MASTER_DATA.json','kit-assets/KIT_VERSION.json','update-status.json']
        for name in self.paths:(self.repo/name).write_text('BASE_'+name)
        self.git(self.repo,'add','.')
        self.git(self.repo,'commit','-m','baseline')
        self.git(self.repo,'push','-u','origin','main')
        for name in self.paths:(self.repo/name).write_text('PROMOTED_'+name)
        self.git(self.repo,'add','.')
        self.git(self.repo,'commit','-m','auto update')
        self.git(self.repo,'push','origin','main')
        self.head=self.git(self.repo,'rev-parse','HEAD').strip()
        self.evidence=root/'health.json'
    @staticmethod
    def git(where,*args):
        return subprocess.check_output(['git']+(['-C',str(where)] if where else [])+list(args),stderr=subprocess.STDOUT,text=True)
    def run_rollback(self):
        argv=['safe_rollback.py','--repo',str(self.repo),'--expected-commit',self.head,'--confirmed-health-evidence',str(self.evidence)]
        with patch.object(sys,'argv',argv):return rollback.main()
    def test_real_local_git_push_and_restore(self):
        self.evidence.write_text(json.dumps({'result':'MIXED_ASSETS_CONFIRMED','checks':[{'result':'MIXED_ASSETS_CONFIRMED'}]*3}))
        self.assertEqual(0,self.run_rollback())
        for name in self.paths[:-1]:self.assertEqual('BASE_'+name,(self.repo/name).read_text())
        self.assertEqual('attention',json.loads((self.repo/'update-status.json').read_text())['state'])
        self.assertEqual('false',str(json.loads((self.repo/'update-status.json').read_text())['productionCsvAllowed']).lower())
        self.assertEqual(self.git(self.repo,'rev-parse','HEAD').strip(),self.git(self.repo,'ls-remote','origin','refs/heads/main').split()[0])
    def test_fake_health_refused(self):
        self.evidence.write_text(json.dumps({'result':'STALE_HTML_OR_PENDING_DEPLOYMENT','checks':[{'result':'STALE_HTML_OR_PENDING_DEPLOYMENT'}]}))
        self.assertEqual(2,self.run_rollback())
        self.assertEqual(self.head,self.git(self.repo,'rev-parse','HEAD').strip())
    def test_single_mixed_refused(self):
        self.evidence.write_text(json.dumps({'result':'MIXED_ASSETS_CONFIRMED','checks':[{'result':'MIXED_ASSETS_CONFIRMED'}]}))
        self.assertEqual(2,self.run_rollback())

if __name__=='__main__':unittest.main()
