#!/usr/bin/env python3
"""Read-only Pokémon Sleep species evidence cross-check, prototype HOLD.

No CSV output or mutation of records; never discard species based on SP,
helping time or carry.  Explicit screenshot-evidence state remains separate
from output-policy defaults.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib
import sys
from collections import Counter
from species_evidence_lab import evaluate
from numeric_observer import observed_numeric, PINNED_LEGACY_MASTER_SHA256

FINGERPRINT_FILES = ('MASTER_DATA.json', 'CSV_SCHEMA.json')
OPTIONAL_KEYS = (
    'quantities', 'sp', 'helpSeconds', 'carry', 'whiteMintMarkObserved',
    'sleepTogetherHoursObserved', 'shinyObserved', 'speciesVisualConfirmed'
)


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def verify_bundle(pkg, *, allow_release=False):
    version=load_json(pkg/'KIT_VERSION.json')
    if allow_release:
        # Only the separate release gate may opt into release-mode auditing.
        # The original CLI and the prototype gate remain fail-closed.
        if (version.get('productionCsvAllowed') is not True or
            version.get('compatibilityVerified') is not True or
            version.get('masterVerifiedAgainstLive') is not True or
            not isinstance(version.get('sourceCommit'),str) or
            len(version['sourceCommit'])!=40 or
            any(c not in '0123456789abcdef' for c in version['sourceCommit']) or
            version.get('kitVersion') == '0.12.0-prototype'):
            raise ValueError('Release eligibility incomplete; HOLD')
    else:
        if version.get('productionCsvAllowed') is not False or version.get('kitVersion') != '0.12.0-prototype':
            raise ValueError('HOLD/version guard mismatch')
        if version.get('compatibilityVerified') is not False:
            raise ValueError('Compatibility guard mismatch')
    # Exactly the same *canonicalized JSON* digest calculation as VALIDATOR.py;
    # the assetSha256 entries are NOT raw-file hashes.
    for name in FINGERPRINT_FILES:
        payload=load_json(pkg/name)
        canonical=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
        actual=hashlib.sha256(canonical).hexdigest()
        if actual != version.get('assetSha256', {}).get(name):
            raise ValueError('Canonical asset sha mismatch: '+name)
    master_raw=(pkg/'MASTER_DATA.json').read_bytes()
    if hashlib.sha256(master_raw).hexdigest()!=PINNED_LEGACY_MASTER_SHA256:
        raise ValueError('Unreviewed carry master fingerprint; HOLD')
    master=json.loads(master_raw.decode('utf-8'))
    if len(master.get('pokemon', []))!=249: raise ValueError('Unexpected master species count')
    return master,version


def require_number_or_none(value,name,as_integer=True):
    if value is None: return
    if as_integer:
        if type(value) is not int: raise ValueError(f'{name}: expected integer or null')
    else:
        if type(value) not in (int,float): raise ValueError(f'{name}: expected number or null')
    if not 0<=value<1e12: raise ValueError(f'{name}: unreasonable or invalid')


def validate_observation(ob):
    if not isinstance(ob,dict): raise ValueError('Each observation must be object')
    if not isinstance(ob.get('imageId'),str): raise ValueError('observation imageId missing')
    for key in ob:
        if key not in OPTIONAL_KEYS and key!='imageId':
            raise ValueError(f'unknown observation key {key} for {ob["imageId"]}')
    q=ob.get('quantities')
    if q is not None:
        if not isinstance(q,list) or len(q)!=3: raise ValueError('quantities must be length 3 or null')
        for v in q:
            require_number_or_none(v,'quantities')
            if v is not None and v<=0: raise ValueError('quantities must be positive')
    for name in ('sp','helpSeconds','carry'):
        require_number_or_none(ob.get(name),name)
    require_number_or_none(ob.get('sleepTogetherHoursObserved'),'sleepTogetherHoursObserved',False)
    for name in ('whiteMintMarkObserved','speciesVisualConfirmed'):
        if ob.get(name) is not None and type(ob[name]) is not bool: raise ValueError(f'{name} not true/false/null')
    if ob.get('shinyObserved') is not None and (type(ob['shinyObserved']) is not int or ob['shinyObserved'] not in (0,1)):
        raise ValueError('shinyObserved must be integer 0/1 or null')


def read_observations(path):
    if path is None: return {}
    data=load_json(path)
    if data.get('purpose')!='READ_ONLY_AUDIT_NOT_GOLD': raise ValueError('Unsupported observations purpose')
    rows=data.get('imageObservations')
    if not isinstance(rows,list): raise ValueError('imageObservations must be array')
    obs={}
    for row in rows:
        validate_observation(row)
        image_id=row['imageId']
        if image_id in obs: raise ValueError(f'duplicate observation ID {image_id}')
        obs[image_id]=row
    return obs


def audit_record(master, dec, obs):
    id_=dec['imageId']
    if dec.get('decision') != 'include':
        return {'imageId':id_, 'status':'NOT_INCLUDED','candidateCount':None,
                'candidateSpecies':[], 'noAutoCorrection':True}
    d=dec.get('data')
    if not isinstance(d,dict): raise ValueError(f'{id_}: missing data')
    species=d.get('species')
    foods=d.get('foods')
    skill=d.get('mainSkill')
    if not isinstance(species,str) or not species: raise ValueError(f'{id_}: species unread')
    if not isinstance(foods,list) or len(foods)!=3: raise ValueError(f'{id_}: foods unread')
    if not isinstance(skill,str): raise ValueError(f'{id_}: skill missing')
    evidence=d.get('fieldEvidence',{})
    if not isinstance(evidence,dict): raise ValueError(f'{id_}: invalid evidence map')
    if evidence.get('sleepTogetherHours')=='user-policy-default' and obs.get('sleepTogetherHoursObserved') is not None:
        raise ValueError(f'{id_}: defaulted sleep hours cannot be used as observed ribbon evidence')
    if evidence.get('sleepTogetherHours')=='image-visible':
        if obs.get('sleepTogetherHoursObserved') is not None and d.get('sleepTogetherHours')!=obs['sleepTogetherHoursObserved']:
            raise ValueError(f'{id_}: observed sleep and CSV sleep mismatch')
    if evidence.get('shiny')=='user-policy-default' and obs.get('shinyObserved') is not None:
        raise ValueError(f'{id_}: defaulted shiny cannot be observed')
    if evidence.get('shiny')=='image-visible':
        if obs.get('shinyObserved') is not None and d.get('shiny')!=obs['shinyObserved']:
            raise ValueError(f'{id_}: shiny observation mismatch')
    qty=obs.get('quantities')
    basic=evaluate(master,{'species':species,'foods':foods,'mainSkill':skill,'quantities':qty})
    report={'imageId':id_, 'status':basic['status'], 'reportedSpecies':species,
      'candidateCount':len(basic['candidates']), 'candidateSpecies':basic['candidates'],
      'quantitiesReadFromImage':qty, 'numericObservationsAvailable':any(obs.get(x) is not None for x in ('helpSeconds','carry','sp')),
      'speciesVisualConfirmed':obs.get('speciesVisualConfirmed'),
      'noAutoCorrection':True, 'noNumericCandidateExclusion':True}
    numerics={}
    for candidate in basic['candidates']:
        r={'level':d.get('level'), 'nature':d.get('nature'), 'subskills':d.get('subskills'),
           'sp':obs.get('sp'), 'helpSeconds':obs.get('helpSeconds'), 'carry':obs.get('carry'),
           'sleepTogetherHoursObserved':obs.get('sleepTogetherHoursObserved'),
           'whiteMintMarkObserved':obs.get('whiteMintMarkObserved')}
        numerics[candidate]=observed_numeric(candidate,master,r)
    report['numericCandidateReports']=numerics
    report['numericJointCandidatesAdvisory']=[s for s,r in numerics.items() if r.get('jointHelpCarrySupported') is True]
    report['possibleNumericMismatchNeedsReview']=bool(species in numerics and numerics[species].get('jointHelpCarrySupported') is False)
    report['speciesIdentityReviewRecommended']=(len(basic['candidates'])>1 and obs.get('speciesVisualConfirmed') is not True)
    report['hardConflict']=basic['status'] in ('CONTRADICTION_HOLD','SPECIES_CONFLICT_HOLD')
    return report


def audit(package_dir,records_path,observations_path=None, *, allow_release=False):
    master,version=verify_bundle(package_dir, allow_release=allow_release)
    data=load_json(records_path)
    if data.get('schemaVersion')!='ai-reading-v0.1' or data.get('kitVersion')!=version['kitVersion']:
        raise ValueError('Reading data schema/version mismatch')
    decisions=data.get('decisions')
    if not isinstance(decisions,list): raise ValueError('decisions array required')
    manifest_path=package_dir/'INPUT_MANIFEST.json'
    if manifest_path.exists():
        manifest=load_json(manifest_path)
        expected=[x['id'] for x in manifest['images']]
        if len(expected)!=manifest.get('inputImageCount'):
            raise ValueError('manifest count mismatch')
        if [x.get('imageId') for x in decisions]!=expected:
            raise ValueError('decisions vs manifest image count/order mismatch')
    obs=read_observations(observations_path)
    expected_ids=[d.get('imageId') for d in decisions]
    if len(set(expected_ids))!=len(expected_ids): raise ValueError('duplicated image decisions')
    if set(obs)-set(expected_ids): raise ValueError('observations contain unknown image IDs')
    reports=[audit_record(master,d,obs.get(d.get('imageId'),{})) for d in decisions]
    statuses=Counter(x['status'] for x in reports)
    return {'mode':'READ_ONLY_SPECIES_AUDIT_v0.4','productionCsvAllowed':allow_release,
       'progressInstructionPolicy':'DEFAULT_ON_NO_INTERRUPT; not a runtime execution measurement',
       'numericEvidenceUsage':'ADVISORY_ONLY_NOT_EXCLUSION',
       'speciesAutoChanges':0,'candidateRemovalsByNumeric':0,
       'total':len(reports),'statuses':dict(statuses),
       'hardConflicts':[x['imageId'] for x in reports if x.get('hardConflict')],
       'identityReviewRecommendations':[x['imageId'] for x in reports if x.get('speciesIdentityReviewRecommended')],
       'records':reports}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package-dir',type=pathlib.Path,default=pathlib.Path('.'))
    p.add_argument('--records',type=pathlib.Path,required=True)
    p.add_argument('--observations',type=pathlib.Path)
    p.add_argument('--output',type=pathlib.Path,required=True)
    a=p.parse_args()
    try:
        result=audit(a.package_dir,a.records,a.observations)
        a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f'SPECIES AUDIT {result["total"]} records; {result["statuses"]}; conflicts {len(result["hardConflicts"])}; PROTOTYPE HOLD')
        if result['hardConflicts']:
            print('HOLD_CONFLICTS:',','.join(result['hardConflicts']))
            return 3
    except (ValueError,KeyError,TypeError,IndexError,FileNotFoundError) as exc:
        print(f'FAIL_CLOSED_SPECIES_AUDIT: {exc}',file=sys.stderr)
        return 4
    return 0

if __name__=='__main__':
    sys.exit(main())
