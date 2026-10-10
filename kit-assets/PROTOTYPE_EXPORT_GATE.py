#!/usr/bin/env python3
"""DEVELOPMENT-ONLY output orchestrator. Mandatory SpeciesAudit before Validator.

This is deliberately NOT an alternative production exporter: the v0.12
production guard is never bypassed for general users; --prototype-test is
required, filenames mark unverified test outputs, and golden labels are absent.
Image ID/row binding sidecar is derived from VALIDATOR.build, not heuristically
from nickname or CSV row order. Caller still bears responsibility for truthful
screenshot reading / user confirmations.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import os
import pathlib
import sys
import tempfile

from VALIDATOR import build, load_json, ValidationError
from SPECIES_AUDIT import audit

EXPORT_NAME = 'DEVELOPMENT_ONLY_pokesleep_16col.csv'
BINDING_NAME = 'DEVELOPMENT_ONLY_ROW_BINDING.json'
STATUS_NAME = 'DEVELOPMENT_ONLY_GATE_STATUS.json'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_row(row):
    return json.dumps(row,ensure_ascii=False,separators=(',',':')).encode('utf-8')


def make_binding(records,manifest,csv_bytes,report, *, purpose='DEVELOPMENT_ONLY_INTEGRITY_NOT_AUTHORITATIVE_GROUND_TRUTH'):
    # Validator.build emits include decisions in manifest order. Independently
    # check row count and mapping here instead of assuming row position is safe.
    rows=list(csv.reader(io.StringIO(csv_bytes.decode('utf-8'),newline=''),strict=True))
    if not rows or len(rows)-1 != report['included']:
        raise ValueError('CSV rows mismatch validator result')
    by_id={d['imageId']:d for d in records['decisions']}
    included=[im for im in manifest['images'] if by_id[im['id']]['decision']=='include']
    if len(included)!=len(rows)-1:
        raise ValueError('Included row/manifest mismatch')
    return {
      'schemaVersion':'prototype-image-row-binding-v0.1',
      'purpose':purpose,
      'inputManifestSHA256':sha(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')),
      'csvSHA256':sha(csv_bytes),
      'header':rows[0],
      'includedCount':len(included),
      'rows':[{
        'csvRowNumber':i+1, 'imageId':im['id'],
        'originalFilename':im['originalFilename'],
        'rowSHA256':sha(canonical_row(rows[i+1]))
      } for i,im in enumerate(included)]
    }


def atomic_write(path,body:bytes):
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode='wb',dir=path.parent,prefix='.'+path.name+'.',suffix='.tmp',delete=False) as f:
            temp=pathlib.Path(f.name);f.write(body);f.flush();os.fsync(f.fileno())
        os.replace(temp,path);temp=None
    finally:
        if temp is not None:temp.unlink(missing_ok=True)


def run(package_dir,records_path,observations_path,output_dir,prototype_test, *, user_confirmations_path=None):
    package_dir=pathlib.Path(package_dir).resolve()
    output_dir=pathlib.Path(output_dir).resolve();output_dir.mkdir(parents=True,exist_ok=True)
    # Fail closed; never allow an old PASS or CSV to survive a failed new attempt.
    for f in (EXPORT_NAME,BINDING_NAME,STATUS_NAME): (output_dir/f).unlink(missing_ok=True)
    if not prototype_test:raise ValueError('Production remains HOLD: explicit --prototype-test required')
    version=load_json(package_dir/'KIT_VERSION.json')
    if (version.get('productionCsvAllowed') is not False
            or version.get('compatibilityVerified') is not False
            or version.get('kitVersion')!='0.12.0-prototype'):
        raise ValueError('v0.12 PROTOTYPE / HOLD guard differs; refuse')
    records=load_json(pathlib.Path(records_path))
    manifest=load_json(package_dir/'INPUT_MANIFEST.json')
    species=audit(package_dir,pathlib.Path(records_path),pathlib.Path(observations_path) if observations_path else None,
                  user_confirmations_path=pathlib.Path(user_confirmations_path) if user_confirmations_path else None)
    if species['hardConflicts']:
        raise ValueError('SPECIES_CONFLICT_HOLD: '+','.join(species['hardConflicts']))
    if species['total']!=manifest['inputImageCount']:
        raise ValueError('SpeciesAudit/input count mismatch')
    if species['identityReviewRecommendations']:
        raise ValueError('SPECIES_IDENTITY_REVIEW_HOLD: '+','.join(species['identityReviewRecommendations'])+
                         '; visually verify species and set speciesVisualConfirmed only if truly verified')
    # Never turn a numeric disagreement into silent exclusion or correction.
    if species['speciesAutoChanges'] or species['candidateRemovalsByNumeric']:
        raise ValueError('SpeciesAudit auto-correction must remain forbidden')
    data, report=build(records,manifest,load_json(package_dir/'MASTER_DATA.json'),
      load_json(package_dir/'CSV_SCHEMA.json'),version,package_dir,prototype_test=True)
    binding=make_binding(records,manifest,data,report)
    # Final in-memory roundtrip before publishing any of these three files.
    if len(binding['rows'])!=report['included'] or binding['csvSHA256']!=sha(data):
        raise ValueError('CSV/row binding invalid')
    status={
      'mode':'DEVELOPMENT_ONLY_IntegratedGate_v0.8',
      'productionCsvAllowed':False,'compatibilityVerified':False,
      'speciesAuditHardConflicts':[], 'speciesIdentityReviewRecommendations':[],
      'userFormConfirmationCount':species.get('userFormConfirmationCount',0),
      'userFormConfirmations':[r['userFormConfirmation'] for r in species['records'] if r.get('userFormConfirmation')],
      'included':report['included'], 'excluded':report['excluded'],
      'csvSHA256':sha(data),'bindingSHA256':sha(json.dumps(binding,ensure_ascii=False,sort_keys=True).encode('utf-8')),
      'warning':'This CSV is a PROTOTYPE test artifact, NOT proven pokesleep-tool compatible.'
    }
    # A single atomic_write per file does not make a three-file transaction.
    # STATUS_NAME is the last commit marker; no file is deliverable without it.
    # On any Python-level failure, remove the entire attempted delivery.
    try:
        atomic_write(output_dir/EXPORT_NAME,data)
        atomic_write(output_dir/BINDING_NAME,(json.dumps(binding,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        atomic_write(output_dir/STATUS_NAME,(json.dumps(status,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    except BaseException:
        for filename in (EXPORT_NAME,BINDING_NAME,STATUS_NAME):
            (output_dir/filename).unlink(missing_ok=True)
        raise
    return status


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package-dir',type=pathlib.Path,default=pathlib.Path('.'))
    p.add_argument('--records',type=pathlib.Path,required=True)
    p.add_argument('--observations',type=pathlib.Path)
    p.add_argument('--user-confirmations',type=pathlib.Path)
    p.add_argument('--output-dir',type=pathlib.Path,required=True)
    p.add_argument('--prototype-test',action='store_true')
    a=p.parse_args()
    try:
        result=run(a.package_dir,a.records,a.observations,a.output_dir,a.prototype_test,
                   user_confirmations_path=a.user_confirmations)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,ValidationError,OSError,KeyError,TypeError,json.JSONDecodeError) as e:
        print('DEVELOPMENT CSV HOLD: '+str(e),file=sys.stderr)
        return 3

if __name__=='__main__':raise SystemExit(main())
