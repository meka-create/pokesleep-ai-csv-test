#!/usr/bin/env python3
"""DORMANT release exporter. Never activate from prototype kit flags.

Separately enforces release evidence, a user approval record, species audit,
Validator's real (non-prototype) guard and integrity-bound row mapping.
The evidence file is a locally supplied *review record*, NOT cryptographic
authentication of the user's chat identity. An independent human review is
mandatory before producing an approved release bundle.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib
import re
import sys
from PROTOTYPE_EXPORT_GATE import make_binding, sha, atomic_write
from VALIDATOR import build, load_json, ValidationError
from SPECIES_AUDIT import audit

CSV_NAME='pokesleep_import.csv'
BINDING_NAME='RELEASE_ROW_BINDING.json'
STATUS_NAME='RELEASE_GATE_STATUS.json'
RELEASE_FILES=(CSV_NAME,BINDING_NAME,STATUS_NAME)

def canonical(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')

def release_preflight(package_dir,evidence_file,explicit_release):
    pkg=pathlib.Path(package_dir).resolve()
    version=load_json(pkg/'KIT_VERSION.json')
    if not explicit_release:
        raise ValueError('Explicit --release-authorized is required; HOLD')
    if (version.get('productionCsvAllowed') is not True or
        version.get('compatibilityVerified') is not True or
        version.get('masterVerifiedAgainstLive') is not True or
        version.get('kitVersion')=='0.12.0-prototype' or
        not isinstance(version.get('sourceCommit'),str) or
        not re.fullmatch(r'[0-9a-f]{40}',version['sourceCommit'])):
        raise ValueError('Unverified prototype / master / sourceCommit; HOLD')
    if evidence_file is None:
        raise ValueError('External release evidence file missing; HOLD')
    evidence=load_json(pathlib.Path(evidence_file))
    if not isinstance(evidence,dict) or evidence.get('schemaVersion')!='release-evidence-v0.1':
        raise ValueError('Unreviewed release evidence schema; HOLD')
    for k in ('masterSha256','schemaSha256','manualRoundTripEvidenceSHA256',
              'goldenBlindEvidenceSHA256','browserEvidenceSHA256'):
        if not isinstance(evidence.get(k),str) or re.fullmatch('[0-9a-f]{64}',evidence[k]) is None:
            raise ValueError('Missing release evidence digest: '+k)
    if (evidence.get('sourceCommit')!=version['sourceCommit'] or
        evidence.get('kitVersion')!=version['kitVersion'] or
        evidence.get('masterSha256')!=version.get('assetSha256',{}).get('MASTER_DATA.json') or
        evidence.get('schemaSha256')!=version.get('assetSha256',{}).get('CSV_SCHEMA.json')):
        raise ValueError('Release evidence/version/master mismatch; HOLD')
    if (evidence.get('explicitUserApproval') is not True or
        evidence.get('approvalText')!='本番出力を明示承認: '+version['kitVersion']):
        raise ValueError('No explicit user approval record; HOLD')
    if sha(canonical(evidence)) != version.get('releaseEvidenceSHA256'):
        raise ValueError('Release evidence pin mismatch; HOLD')
    return version,evidence

def run(package_dir, records_path, observations_path, output_dir, evidence_file=None,
        *, explicit_release=False):
    pkg=pathlib.Path(package_dir).resolve()
    target=pathlib.Path(output_dir).resolve();target.mkdir(parents=True,exist_ok=True)
    # Do not let an earlier apparent successful run survive any failed attempt.
    for name in RELEASE_FILES:(target/name).unlink(missing_ok=True)
    version,evidence=release_preflight(pkg,evidence_file,explicit_release)
    records=load_json(pathlib.Path(records_path))
    manifest=load_json(pkg/'INPUT_MANIFEST.json')
    species=audit(pkg,pathlib.Path(records_path),
                  pathlib.Path(observations_path) if observations_path else None,
                  allow_release=True)
    if species['total']!=manifest['inputImageCount'] or species['hardConflicts'] or species['identityReviewRecommendations'] or species['speciesAutoChanges'] or species['candidateRemovalsByNumeric']:
        raise ValueError('SpeciesAudit conflict/review pending; HOLD')
    data,report=build(records,manifest,load_json(pkg/'MASTER_DATA.json'),
                     load_json(pkg/'CSV_SCHEMA.json'),version,pkg,prototype_test=False)
    if report['excluded']:
        # Manual confirmation records are structurally checked by Validator,
        # but the caller cannot authenticate chat authorship. Fail closed here.
        raise ValueError('Excluded images require separate human release review; HOLD')
    binding=make_binding(records,manifest,data,report,
        purpose='RELEASE_INTEGRITY_ROW_BINDING_NOT_GROUND_TRUTH')
    if binding['csvSHA256']!=sha(data) or binding['includedCount']!=report['included']:
        raise ValueError('Row binding integrity failed; HOLD')
    binding_bytes=(json.dumps(binding,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    status={'mode':'RELEASE_INTEGRATED_GATE_v0.1',
            'included':report['included'],'excluded':report['excluded'],
            'csvSHA256':sha(data),'bindingSHA256':sha(canonical(binding)),
            'releaseEvidenceSHA256':sha(canonical(evidence)),
            'sourceCommit':version['sourceCommit'],'status':'PASS'}
    try:
        atomic_write(target/CSV_NAME,data)
        atomic_write(target/BINDING_NAME,binding_bytes)
        atomic_write(target/STATUS_NAME,(json.dumps(status,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    except BaseException:
        for name in RELEASE_FILES:(target/name).unlink(missing_ok=True)
        raise
    return status

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package-dir',type=pathlib.Path,default=pathlib.Path('.'))
    p.add_argument('--records',type=pathlib.Path,required=True)
    p.add_argument('--observations',type=pathlib.Path)
    p.add_argument('--output-dir',type=pathlib.Path,required=True)
    p.add_argument('--release-evidence',type=pathlib.Path)
    p.add_argument('--release-authorized',action='store_true')
    args=p.parse_args()
    try:
        print(json.dumps(run(args.package_dir,args.records,args.observations,args.output_dir,
          args.release_evidence,explicit_release=args.release_authorized),ensure_ascii=False,indent=2))
        return 0
    except (ValueError,ValidationError,OSError,KeyError,TypeError,IndexError) as e:
        print('PRODUCTION CSV HOLD: '+str(e),file=sys.stderr)
        return 4
if __name__=='__main__':raise SystemExit(main())
