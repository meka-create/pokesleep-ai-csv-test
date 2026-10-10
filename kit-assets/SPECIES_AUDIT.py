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
from numeric_observer import observed_numeric, current_species_carry_baseline, PINNED_LEGACY_MASTER_SHA256

FINGERPRINT_FILES = ('MASTER_DATA.json', 'CSV_SCHEMA.json')

# Image-observation and a human's explicit reply are distinct evidence channels.
# These names are intentionally fixed (not a general form-inference system).
HIGH_RISK_EVOLUTION_SPECIES = frozenset(('ジュプトル', 'ジュカイン', 'ラッキー', 'ハピナス'))
FORM_SIZES = ('こだましゅ', 'ちゅうだましゅ', 'おおだましゅ', 'ギガだましゅ')
USER_CONFIRMATION_PURPOSE = 'USER_DIRECT_FORM_CONFIRMATION_NOT_IMAGE_OBSERVATION'


def read_user_form_confirmations(path, manifest):
    if path is None: return {}
    if manifest is None:
        raise ValueError('User form confirmations require INPUT_MANIFEST.json')
    payload = load_json(path)
    if set(payload) != {'purpose', 'confirmations'} or payload['purpose'] != USER_CONFIRMATION_PURPOSE:
        raise ValueError('User form confirmation schema/purpose mismatch')
    if not isinstance(payload['confirmations'], list):
        raise ValueError('User form confirmations must be a list')
    by_id={x['id']:x for x in manifest['images']}
    confirmed={}
    for c in payload['confirmations']:
        expected_keys={'imageId','originalFilename','speciesFamily','confirmedSize','userAnswerText','responseOrigin'}
        optional_keys={'verificationSource','questionScope'}
        if (not isinstance(c, dict) or not expected_keys<=set(c) or
            not set(c)<=expected_keys|optional_keys):
            raise ValueError('User form confirmation keys mismatch')
        ident=c['imageId']
        if (not isinstance(ident,str) or ident not in by_id or ident in confirmed or
            c['originalFilename'] != by_id[ident]['originalFilename']):
            raise ValueError('User form image ID/filename mismatch or duplicate')
        if (c['speciesFamily'] not in FOUR_SIZE_GROUPS or
            c['confirmedSize'] not in FORM_SIZES or
            c['responseOrigin']!='direct-user-reply' or
            not isinstance(c['userAnswerText'], str)):
            raise ValueError('User form family/size/origin invalid')
        answer=c['userAnswerText'].strip()
        species=f"{c['speciesFamily']} ({c['confirmedSize']})"
        display_species=f"{c['speciesFamily']}（{c['confirmedSize']}）"
        source=c.get('verificationSource')
        scope=c.get('questionScope','four-size')
        if scope not in ('four-size','eight-form'):
            raise ValueError('Unknown questionScope')
        if source not in (None,'in-game-details'):
            raise ValueError('Unknown verificationSource')
        if scope=='eight-form':
            # The 1-8 numbering is reserved for a question explicitly showing
            # both evolutionary stages. Never confuse it with the 1-4 list.
            if source!='in-game-details':
                raise ValueError('Eight-form question requires actual in-game check')
            all_forms=tuple(f'{group} ({size})' for group in FOUR_SIZE_GROUPS
                            for size in FOUR_SIZE_GROUPS[group])
            valid_answers=(str(all_forms.index(species)+1), species, display_species)
        else:
            size_number=str(FORM_SIZES.index(c['confirmedSize'])+1)
            valid_answers=(size_number,c['confirmedSize'],species,display_species)
        if answer not in valid_answers:
            raise ValueError('User answer does not unambiguously confirm the chosen form')
        confirmed[ident]=c
    return confirmed
OPTIONAL_KEYS = (
    'quantities', 'sp', 'helpSeconds', 'carry', 'whiteMintMarkObserved',
    'sleepTogetherHoursObserved', 'shinyObserved', 'speciesVisualConfirmed',
    'carryVisualConfirmed', 'speciesFamilyVisualConfirmed', 'formSizeVisualConfirmed'
)



# Whitelisted forms have strictly increasing *minimum* inventory capacity.
# Ribbon and inventory-subskill bonuses only increase these minima. Therefore
# an actually visible carry below EVERY other form minimum can certify the
# smallest form without guessing ribbon hours, mint, helping speed, or SP.
# Other numeric matches remain strictly advisory; never auto-confirm them.
FOUR_SIZE_GROUPS={
    'バケッチャ': ('こだましゅ','ちゅうだましゅ','おおだましゅ','ギガだましゅ'),
    'パンプジン': ('こだましゅ','ちゅうだましゅ','おおだましゅ','ギガだましゅ')
}


def four_size_numeric_advisory(reported_species, candidates, numerics, obs):
    """Human-facing relative evidence, never a probability or decision.

    Compares BOTH evolution stages so an incorrectly read Pumpkaboo/Gourgeist
    stage cannot hide a better numeric match. A unique jointly-supported
    candidate is a suggestion, not a certificate. Any tie, missing support,
    or contradictory help/carry evidence yields no unique favorite.
    """
    all_forms=tuple(f'{group} ({size})' for group in FOUR_SIZE_GROUPS
                    for size in FOUR_SIZE_GROUPS[group])
    if reported_species not in all_forms:
        return None
    present=[x for x in all_forms if x in candidates]
    help_read=obs.get('helpSeconds') is not None
    carry_read=obs.get('carry') is not None
    # A form should not be preferred when helping-time and inventory cannot
    # be supported by the SAME plausible ribbon/mint state.
    rows=[]
    for name in present:
        n=numerics.get(name,{})
        match_joint=n.get('jointHelpCarrySupported') is True
        match_help=n.get('helpSupported') is True
        match_carry=n.get('carrySupported') is True
        if help_read and carry_read:
            score=3 if match_joint else 0
        elif help_read:
            score=2 if match_help else 0
        elif carry_read:
            score=1 if match_carry else 0
        else:
            score=0
        rows.append({
            'species':name,
            'size':next(size for size in FORM_SIZES if name.endswith(f'({size})')),
            'scoreForSortingOnly':score,
            'jointHelpCarrySupported':n.get('jointHelpCarrySupported'),
            'helpSupported':n.get('helpSupported'),
            'carrySupported':n.get('carrySupported'),
            'matchingNumericStates':n.get('matchingStateCount'),
            'numericModelStatus':n.get('status'),
        })
    rows.sort(key=lambda x:(-x['scoreForSortingOnly'],all_forms.index(x['species'])))
    top=rows[0]['scoreForSortingOnly'] if rows else 0
    tied=[r['species'] for r in rows if r['scoreForSortingOnly']==top]
    unique=top>0 and len(tied)==1
    if not help_read and not carry_read:
        status='NOT_ENOUGH_VISIBLE_NUMERIC_DATA'
    elif top==0:
        status='NO_SUPPORTED_NUMERIC_FAVORITE'
    elif unique:
        status='ONE_NUMERICALLY_PREFERRED_CANDIDATE_NOT_CONFIRMED'
    else:
        status='TIED_PREFERRED_CANDIDATES_NOT_CONFIRMED'
    suggestion=tied[0] if unique else None
    reported_stage=reported_species.split(' (')[0]
    suggestion_stage=suggestion.split(' (')[0] if suggestion else None
    return {
        'status':status,
        'suggestedSpecies':suggestion,
        'preferredCandidates':tied if top>0 else [],
        'reportedSpecies':reported_species,
        'suggestionDiffersFromReportedSpecies':suggestion is not None and suggestion != reported_species,
        'evolutionStageRecheckRequired':suggestion_stage is not None and suggestion_stage != reported_stage,
        'observedHelpSeconds':obs.get('helpSeconds'),
        'observedCarry':obs.get('carry'),
        'rankingBasis':('JOINT_HELP_AND_CARRY_SAME_HYPOTHESIS' if help_read and carry_read else
                        'HELP_ONLY_ADVISORY' if help_read else
                        'CARRY_ONLY_ADVISORY' if carry_read else 'NO_NUMERICS'),
        'allOptions':rows,
        'alwaysCompareBothEvolutionStages':True,
        'notCalibratedProbability':True,
        'neverAutoConfirmOrDiscardCandidates':True,
        'mustConfirmInGameWhenAmbiguous':True,
    }


def confirmed_four_size_by_lower_bound(master, reported_species, obs):
    """Explicit finite, auditable certificate; NONE is not a guessed form."""
    if obs.get('carryVisualConfirmed') is not True: return None
    carry=obs.get('carry')
    if type(carry) is not int: return None
    group=next((name for name in FOUR_SIZE_GROUPS
                if reported_species.startswith(name+' (')),None)
    if group is None:return None
    forms=[f'{group} ({size})' for size in FOUR_SIZE_GROUPS[group]]
    pokemon={p['name']:p for p in master['pokemon']}
    if not all(s in pokemon for s in forms):return None
    minima={name:current_species_carry_baseline(pokemon[name]) for name in forms}
    if not all(type(value) is int and value>=0 for value in minima.values()):return None
    if len(set(minima.values()))!=len(forms):return None
    # Without a visually confirmed family, account for BOTH evolution stages;
    # e.g. Gourgeist small (15) overlaps Pumpkaboo large (15).
    comparison_forms=forms if obs.get('speciesFamilyVisualConfirmed') is True else [
        f'{name} ({size})' for name in FOUR_SIZE_GROUPS for size in FOUR_SIZE_GROUPS[name]]
    if not all(name in pokemon for name in comparison_forms): return None
    comparison_mins={name:current_species_carry_baseline(pokemon[name])
                     for name in comparison_forms}
    other_mins=[value for name,value in comparison_mins.items() if name!=reported_species]
    if (reported_species in minima and
        minima[reported_species]<=carry<min(other_mins)):
        return {
          'status':'FORM_CONFIRMED_BY_VISIBLE_CARRY_LOWER_BOUND',
          'species':reported_species,'observedCarry':carry,
          'ownMinimum':minima[reported_species],
          'minimumAlternative':min(other_mins),
          'formCandidatesBefore':comparison_forms,
          'speciesFamilyVisuallyVerified':obs.get('speciesFamilyVisualConfirmed') is True,
          'cannotConfirmFromSPOrApproximateHelpTime':True,
          'speciesVisualConfirmedNotAssumed':True,
          'basis':'PINNED_V2_9_CARRY_MINIMA_INCREASE_ONLY; SCREENSHOT_CARRY_EXPLICIT',
          'maySkipFormSizeQuestion':True
        }
    return None


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
    for name in ('whiteMintMarkObserved','speciesVisualConfirmed','carryVisualConfirmed','speciesFamilyVisualConfirmed','formSizeVisualConfirmed'):
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


def audit_record(master, dec, obs, user_form_confirmation=None):
    id_=dec['imageId']
    decision=dec.get('decision')
    if decision not in ('include','exclude'):
        raise ValueError(f'{id_}: invalid image decision {decision!r}; HOLD')
    if decision == 'exclude':
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
    report['fourSizeNumericAdvisory']=four_size_numeric_advisory(species,basic['candidates'],numerics,obs)
    report['possibleNumericMismatchNeedsReview']=bool(species in numerics and numerics[species].get('jointHelpCarrySupported') is False)
    # A high-risk conflict is NOT a numerical species selector. It only asks
    # for a second, independent in-game check of BOTH stage and size. The old
    # rule missed IMG-0085 because a form-size review could be discharged by a
    # size certificate even though helping time strongly supported another stage.
    adv=report['fourSizeNumericAdvisory']
    numeric_stage_conflict=bool(
        adv and obs.get('helpSeconds') is not None and obs.get('carry') is not None
        and adv.get('evolutionStageRecheckRequired') is True
        and adv.get('suggestedSpecies') is not None
        and adv['suggestedSpecies'] != species)
    report['strongCrossStageNumericConflictNeedsReview']=numeric_stage_conflict
    form_cert=confirmed_four_size_by_lower_bound(master,species,obs)
    report['formSizeMinimumCarryCertificate']=form_cert
    # The lower-bound proof is valid only for explicit 8-form families, not
    # a generic claim that all other matching Pokémon have been ruled out.
    allowed_form_candidates={f'{name} ({size})' for name in FOUR_SIZE_GROUPS
                             for size in FOUR_SIZE_GROUPS[name]}
    form_cert_overrides_review=(form_cert is not None and
                                set(basic['candidates']) <= allowed_form_candidates)
    is_four_size_form=species in allowed_form_candidates
    user_verified=False
    if user_form_confirmation is not None:
        conf=user_form_confirmation
        confirmed=f"{conf['speciesFamily']} ({conf['confirmedSize']})"
        if not is_four_size_form or confirmed!=species:
            raise ValueError(f'{id_}: user confirmed a different form than the record; HOLD')
        # The respondent may check in-game details and explicitly name BOTH
        # evolution stage and size. That is user testimony, never screenshot
        # visual proof. A mere size number cannot establish the family.
        explicit_game_check=(conf.get('verificationSource')=='in-game-details' and
                             (conf['userAnswerText'].strip() in (confirmed, f"{conf['speciesFamily']}（{conf['confirmedSize']}）") or
                              (conf.get('questionScope')=='eight-form' and
                               conf['userAnswerText'].strip() in tuple(str(i) for i in range(1,9)))))
        if obs.get('speciesFamilyVisualConfirmed') is not True and not explicit_game_check:
            raise ValueError(f'{id_}: size-only reply cannot establish species FAMILY/evolution stage; HOLD')
        user_verified=True
    # A visual size alone is not proof of the evolution stage.
    visual_verified=(obs.get('formSizeVisualConfirmed') is True and
                     obs.get('speciesFamilyVisualConfirmed') is True)
    # An observed carry below the stated form's baseline is a review flag;
    # it must not be silently 'fixed' by a user-size response.
    min_carry=next((current_species_carry_baseline(p) for p in master['pokemon']
                    if p['name']==species),None) if is_four_size_form else None
    carry_below_minimum=(is_four_size_form and obs.get('carryVisualConfirmed') is True and
                          type(obs.get('carry')) is int and min_carry is not None and
                          obs['carry'] < min_carry)
    form_verified=(form_cert_overrides_review or visual_verified or user_verified) and not carry_below_minimum
    report['formSizeEvidenceSource']=(
        ('USER_DIRECT_IN_GAME_STAGE_AND_SIZE' if user_form_confirmation.get('verificationSource')=='in-game-details'
         else 'USER_DIRECT_REPLY') if user_verified and not carry_below_minimum else
        'SCREEN_VISUAL_FORM_AND_FAMILY' if visual_verified and not carry_below_minimum else
        'VISIBLE_CARRY_LOWER_BOUND' if form_cert_overrides_review else
        'UNRESOLVED')
    report['userFormConfirmation']=(
        {'source':'USER_DIRECT_REPLY_NOT_IMAGE_VISUAL',
         'imageId':id_, 'originalFilename':user_form_confirmation['originalFilename'],
         'confirmedSize':user_form_confirmation['confirmedSize'],
         'userAnswerText':user_form_confirmation['userAnswerText'],
         'verificationSource':user_form_confirmation.get('verificationSource','not-asserted'),
         'questionScope':user_form_confirmation.get('questionScope','four-size')}
        if user_verified else None)
    report['possibleCarryBelowMinimumNeedsReview']=bool(carry_below_minimum)
    # User-provided in-game confirmation outranks an uncalibrated old timing
    # formula, but image-only or numeric-only certification cannot clear an
    # unresolved disagreement about the evolution stage.
    in_game_stage_size_confirmed=bool(
        user_verified and user_form_confirmation is not None and
        user_form_confirmation.get('verificationSource')=='in-game-details' and
        user_form_confirmation.get('questionScope')=='eight-form')
    report['strongCrossStageNumericConflictResolvedByUser']=bool(
        numeric_stage_conflict and in_game_stage_size_confirmed)
    report['formSizeReviewRecommended']=(is_four_size_form and not form_verified)
    report['highRiskEvolutionVisualReviewRecommended']=(
        species in HIGH_RISK_EVOLUTION_SPECIES and
        obs.get('speciesVisualConfirmed') is not True)
    report['speciesIdentityReviewRecommended']=(
        report['highRiskEvolutionVisualReviewRecommended'] or
        (numeric_stage_conflict and not in_game_stage_size_confirmed) or
        (is_four_size_form and not form_verified) or
        (not is_four_size_form and len(basic['candidates'])>1 and
         obs.get('speciesVisualConfirmed') is not True))
    report['hardConflict']=basic['status'] in ('CONTRADICTION_HOLD','SPECIES_CONFLICT_HOLD')
    return report


def audit(package_dir,records_path,observations_path=None, *, allow_release=False, user_confirmations_path=None):
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
    manifest=None
    if manifest_path.exists():
        manifest=load_json(manifest_path)
    user_conf=read_user_form_confirmations(user_confirmations_path,manifest)
    # Direct user confirmations are evidence for included output rows only.
    # Silently counting confirmations against excluded/unknown rows would make
    # the userFormConfirmationCount disagree with the actual audit records.
    included_ids={d.get('imageId') for d in decisions if d.get('decision')=='include'}
    confirmation_outside_output=set(user_conf)-included_ids
    if confirmation_outside_output:
        raise ValueError('User form confirmation references excluded/non-included image(s): '+
                         ', '.join(sorted(confirmation_outside_output)))
    obs=read_observations(observations_path)
    expected_ids=[d.get('imageId') for d in decisions]
    if len(set(expected_ids))!=len(expected_ids): raise ValueError('duplicated image decisions')
    if set(obs)-set(expected_ids): raise ValueError('observations contain unknown image IDs')
    reports=[audit_record(master,d,obs.get(d.get('imageId'),{}),user_conf.get(d.get('imageId'))) for d in decisions]
    statuses=Counter(x['status'] for x in reports)
    return {'mode':'READ_ONLY_SPECIES_AUDIT_v0.4','productionCsvAllowed':allow_release,
       'progressInstructionPolicy':'DEFAULT_ON_NO_INTERRUPT; not a runtime execution measurement',
       'numericEvidenceUsage':'ADVISORY_ONLY_NOT_EXCLUSION',
       'speciesAutoChanges':0,'candidateRemovalsByNumeric':0,
       'userFormConfirmationCount':len(user_conf),
       'total':len(reports),'statuses':dict(statuses),
       'hardConflicts':[x['imageId'] for x in reports if x.get('hardConflict')],
       'identityReviewRecommendations':[x['imageId'] for x in reports if x.get('speciesIdentityReviewRecommended')],
       'records':reports}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package-dir',type=pathlib.Path,default=pathlib.Path('.'))
    p.add_argument('--records',type=pathlib.Path,required=True)
    p.add_argument('--observations',type=pathlib.Path)
    p.add_argument('--user-confirmations',type=pathlib.Path)
    p.add_argument('--output',type=pathlib.Path,required=True)
    a=p.parse_args()
    try:
        result=audit(a.package_dir,a.records,a.observations,user_confirmations_path=a.user_confirmations)
        a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f'SPECIES AUDIT {result["total"]} records; {result["statuses"]}; conflicts {len(result["hardConflicts"])}; PROTOTYPE HOLD')
        if result['hardConflicts']:
            print('HOLD_CONFLICTS:',','.join(result['hardConflicts']))
            return 3
        if result['identityReviewRecommendations']:
            print('HOLD_IDENTITY_REVIEW:',','.join(result['identityReviewRecommendations']))
            return 3
    except (ValueError,KeyError,TypeError,IndexError,FileNotFoundError) as exc:
        print(f'FAIL_CLOSED_SPECIES_AUDIT: {exc}',file=sys.stderr)
        return 4
    return 0

if __name__=='__main__':
    sys.exit(main())
