"""Offline integration-gate tests. These do NOT stand in for upstream import E2E."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from import_compat_gate import GateError, gate, inspect_code
from sync_upstream import project
import test_upstream_sync as upstream_tests

class ImportGateTests(unittest.TestCase):
    write = upstream_tests.UpstreamSyncTests.write
    """Reuses a consistent mocked upstream repository from previous tests."""
    def setUp(self):
        upstream_tests.UpstreamSyncTests.setUp(self)
        code=self.base/'src/box/BoxImporter.ts'
        code.parent.mkdir(exist_ok=True)
        code.write_text('export class BoxImporter { parseCsv(line:string) { return line; }}')
        self.code_path=code
        self.master_path=self.base/'candidate.json'
        kit=ROOT/'site/kit-assets' if (ROOT/'site/kit-assets').exists() else ROOT/'kit-assets'
        self.schema_path=kit/'CSV_SCHEMA.json'
        self.exporter_path=kit/'VALIDATOR.py'
    def run_gate(self,evidence=None,mutate=None):
        self.write()
        master,_=project(self.base,self.legacy,allow_fixture=True)
        self.master_path.write_text(json.dumps(master,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
        if mutate:
            mutate(master)
        return gate(self.base,self.master_path,self.schema_path,self.exporter_path,evidence,test_fixture=True)
    def make_evidence(self):
        initial=self.run_gate()
        return {k:initial[k] for k in ('sourceCommit','sourceCodeSha256','masterSha256','csvSchemaSha256','csvExporterSha256')} | {
            'upstreamImporterExecuted':True, 'importRoundTripExact':True,
            'deployedAppChecked':True,'deployedAppReference':'test-deployment-only', 'verifiedTestVectors':3}
    def test_missing_evidence_holds(self):
        r=self.run_gate()
        self.assertIn('NO_REAL_IMPORTER_EVIDENCE',r['validationErrors'])
        self.assertFalse(r['productionCsvAllowed'])
    def test_valid_artificial_evidence_only_marks_ready_for_manual(self):
        ev=self.make_evidence();path=self.base/'evidence.json'
        path.write_text(json.dumps(ev))
        r=self.run_gate(path)
        self.assertEqual(r['status'],'READY_FOR_MANUAL_PROMOTION')
        self.assertFalse(r['productionCsvAllowed'])
    def test_code_change_blocks_old_evidence(self):
        ev=self.make_evidence();path=self.base/'evidence.json';path.write_text(json.dumps(ev))
        self.code_path.write_text('export class BoxImporter { parseCsv(s:string) { return s.trim(); }}')
        r=self.run_gate(path)
        self.assertIn('EVIDENCE_MISMATCH:sourceCodeSha256',r['validationErrors'])
    def test_master_change_blocks_old_evidence(self):
        ev=self.make_evidence();path=self.base/'evidence.json';path.write_text(json.dumps(ev))
        self.src_json[0]['carryLimit']+=1
        r=self.run_gate(path)
        self.assertIn('EVIDENCE_MISMATCH:masterSha256',r['validationErrors'])
    def test_importer_not_found_holds(self):
        self.code_path.write_text('export function foo(){return 1}')
        r=self.run_gate()
        self.assertIn('IMPORTER_NOT_IDENTIFIED',r['validationErrors'])
    def test_staging_source_tamper_holds(self):
        self.write();m,_=project(self.base,self.legacy,allow_fixture=True)
        self.master_path.write_text(json.dumps(m,ensure_ascii=False))
        self.data['ingredients']['apple']='強制変更';self.write()
        r=gate(self.base,self.master_path,self.schema_path,self.exporter_path,test_fixture=True)
        self.assertIn('STAGED_SOURCE_MISMATCH:dataJa',r['validationErrors'])
    def test_no_upstream_source_fails_closed(self):
        self.code_path.unlink()
        with self.assertRaisesRegex(GateError,'見つかりません'):self.run_gate()
    def test_false_claim_of_deployed_test_blocks(self):
        ev=self.make_evidence();ev['deployedAppChecked']=False
        path=self.base/'evidence.json';path.write_text(json.dumps(ev))
        r=self.run_gate(path)
        self.assertIn('DEPLOYED_APP_NOT_CHECKED',r['validationErrors'])
    def test_fake_import_round_trip_blocks(self):
        ev=self.make_evidence();ev['importRoundTripExact']=False
        path=self.base/'evidence.json';path.write_text(json.dumps(ev))
        r=self.run_gate(path)
        self.assertIn('IMPORT_ROUNDTRIP_NOT_EXACT',r['validationErrors'])

if __name__=='__main__':unittest.main()
