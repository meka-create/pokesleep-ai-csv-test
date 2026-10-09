#!/usr/bin/env python3
"""Read-only optional corroboration of species using observed helping seconds and carry.

Old OCR timing/ribbon structure is advisory only. Carry follows the
version 2.9.0 species-stage rule: it does NOT depend on the individual
Pokemon's catch/evolution history or skill level. All mismatches are REVIEW
flags, never candidate exclusion. No production CSV is generated.
"""
from __future__ import annotations
import json
import hashlib
import math
from collections import Counter
from pathlib import Path
from species_evidence_lab import evaluate

RIBBON_CARRY = (0, 1, 3, 6, 8)
RIBBON_HOURS = (0, 200, 500, 1000, 2000)
HELP_TOLERANCE_SEC = 1
ACTIVATION_LEVELS = (10, 25, 50, 70, 80)
# Snapshot is an old-format carryLimit master; a future live-value master must
# be audited before the v2.9.0 stage adjustment may be applied again.
PINNED_LEGACY_MASTER_SHA256 = 'd60410ba1f92d80c67ca3ff40bc8aa7a2cd51d4c03fc33f9e99fa83bb8e77a38'
NEUTRAL = {'speed': 1.0, 'energy': 1.0, 'ing': 1.0, 'skill': 1.0}


def actual_ribbon_tier(sleep_hours):
    """Only call with an actually observed sleep-hour count, not CSV default."""
    if sleep_hours is None:
        return None
    if type(sleep_hours) not in (int, float) or not math.isfinite(sleep_hours) or sleep_hours < 0:
        raise ValueError('Observed hours must be nonnegative finite number or null')
    return max(i for i, cutoff in enumerate(RIBBON_HOURS) if sleep_hours >= cutoff)


def verified_optional_number(value, name, integer=True):
    if value is None:
        return None
    if (type(value) is not int) if integer else (type(value) not in (float,int)):
        raise ValueError(f'{name} must be a number or null, not a coercible string')
    if value < 0 or not math.isfinite(value):
        raise ValueError(f'{name}: must be finite and nonnegative')
    return value


def active_modifiers(master, subskills, level):
    needed=sum(level>=t for t in ACTIVATION_LEVELS)
    # None is unread, not 'no subskill'. For a numeric comparison the
    # activated subskills must all have been read; the locked ones may be null.
    if not isinstance(subskills,list) or len(subskills)!=5 or any(not x for x in subskills[:needed]):
        return None
    d={x['ja']:x for x in master['subskills']}
    mod={k:0 for k in ('hs','inv','sl')}
    for name in subskills[:needed]:
        if name not in d:
            return None
        for k in mod:
            mod[k]+=d[name].get(k,0)
    return mod


def ribbon_speed(sp,tier):
    el=sp.get('evolutionLeft',0)
    if el == 0: return 1
    if tier>=4: return .75 if el==2 else .88
    if tier>=2: return .89 if el==2 else .95
    return 1


def old_help_seconds(sp,level,nature_speed,help_subskills,ribbon):
    # Equivalent to the publicly published old classifier's time factor,
    # with its special Lv10 edge and JS truncation. Advisory only.
    if level<1 or level>70: return None  # Stay within independently tested level range.
    factor=((501-level)/500)*nature_speed*ribbon_speed(sp,ribbon)*(1-help_subskills*.07)
    factor=math.floor(float(f'{factor*10000:.6f}'))/10000
    odd=.1 if level==10 and sp['frequency']==2600 else 0
    return math.floor(sp['frequency']*factor-odd+1e-9)


def current_species_carry_baseline(p):
    """Derive current carry from this PINNED, legacy-shaped master record.

    The master field carryLimit is pre-v2.9.0 species inventory. Official
    v2.9.0 applies the historical +5 per species evolution STAGE to all
    members of that species, including directly caught evolved Pokemon.
    Here evolutionCount is the SPECIES stage, not actual player evolutions.
    Negative stage is treated as no standard evolution for this advisory
    report. Never use this estimate for hard species exclusion.
    """
    base=p.get('carryLimit')
    stage=p.get('evolutionCount')
    if type(base) is not int or base<0 or type(stage) is not int:
        raise ValueError('Master carryLimit/evolutionCount invalid')
    species_stage=max(0,stage)
    return base + 5*species_stage


def observed_numeric(candidate,master,rec):
    """Return reports; none of this may drive exclusion/autocorrection."""
    level=rec.get('level')
    if type(level) is not int or not 1<=level<=70:
        return {'status':'INSUFFICIENT_LEVEL', 'canCorroborate':False}
    nat={x['ja']:x for x in master['natures']}.get(rec.get('nature'))
    mod=active_modifiers(master,rec.get('subskills'),level)
    if nat is None or mod is None:
        return {'status':'INSUFFICIENT_NATURE_OR_SUBSKILLS','canCorroborate':False}
    helpval=verified_optional_number(rec.get('helpSeconds'), 'helpSeconds')
    carryval=verified_optional_number(rec.get('carry'), 'carry')
    spval=verified_optional_number(rec.get('sp'), 'sp')
    sleep=verified_optional_number(rec.get('sleepTogetherHoursObserved'), 'sleepTogetherHoursObserved',False)
    mint=rec.get('whiteMintMarkObserved')
    if mint not in (None,True,False):
        raise ValueError('whiteMintMarkObserved must be boolean or null')
    if helpval is None and carryval is None and spval is None:
        return {'status':'NO_NUMERIC_VALUES','canCorroborate':False}
    p=next(x for x in master['pokemon'] if x['name']==candidate)
    tiers=range(5) if sleep is None else (actual_ribbon_tier(sleep),)
    natures=(('normal',nat),('neutralized',NEUTRAL)) if mint is None else ((('neutralized',NEUTRAL),) if mint else (('normal',nat),))
    # IMPORTANT: maximum carry is independent of capture route after v2.9.0.
    # Species evolution STAGE is a master attribute; player evolution HISTORY
    # and observed skillLevel are irrelevant to helping-time/carry matching.
    baseline=current_species_carry_baseline(p)
    species_stage=max(0,p['evolutionCount'])
    possibilities=[]
    for tier in tiers:
        for mode,nature in natures:
            help_time=old_help_seconds(p,level,nature['speed'],mod['hs'],tier)
            carry=baseline+RIBBON_CARRY[tier]+mod['inv']*6
            possibilities.append({'ribbonTier':tier,'mintEffect':mode,
                 'calculatedHelpSeconds':help_time,'calculatedCarry':carry,
                 'helpMatches':None if helpval is None else abs(help_time-helpval)<=HELP_TOLERANCE_SEC,
                 'carryMatches':None if carryval is None else carry==carryval})
    any_help = None if helpval is None else any(x['helpMatches'] for x in possibilities)
    any_carry = None if carryval is None else any(x['carryMatches'] for x in possibilities)
    joint = None if helpval is None or carryval is None else any(x['helpMatches'] and x['carryMatches'] for x in possibilities)
    supports=[x for x in possibilities if (helpval is None or x['helpMatches']) and (carryval is None or x['carryMatches'])]
    # SP is deliberately NOT compared or used as an exclusion filter.
    return {'status':'ADVISORY_ONLY','canCorroborate':True,'helpSupported':any_help,
      'carrySupported':any_carry,'jointHelpCarrySupported':joint,
      'observedSpRecordedNotCompared':spval, 'ribbonTiersConsidered':list(tiers),
      'currentSpeciesCarryBaselineEstimate':baseline, 'legacyMasterCarryLimit':p['carryLimit'],
      'speciesEvolutionStageBonusAppliedUniversally':species_stage*5,
      'carryIndependentOfActualEvolutionHistory':True,
      'skillLevelNotUsedForCarryOrHelpingTime':True,
      'carryBaselineProvenance':'PINNED_MASTER_LEGACY_BASE_PLUS_V2_9_SPECIES_STAGE_BONUS_ADVISORY',
      'natureModesConsidered':[t[0] for t in natures],
      'matchingStateCount':len(supports), 'matchingStates':supports[:4],
      'noCandidateRemoval':True, 'noAutoSelection':True}


def evaluate_observation(master,rec):
    base=evaluate(master,{'species':rec.get('species'),'foods':rec.get('foods',[None]*3),
                          'mainSkill':rec.get('mainSkill'),'quantities':rec.get('quantities')})
    numerics={s:observed_numeric(s,master,rec) for s in base['candidates']}
    h={s for s,v in numerics.items() if v.get('jointHelpCarrySupported') is True}
    base['numericCandidateReports']=numerics
    base['numericSupportedCandidates']=sorted(h)
    base['numericEvidencePolicy']='READ_ONLY_NO_EXCLUSION_NO_AUTOCORRECT_NO_SP_STRICT'
    base['csvSleepTogetherHours']=rec.get('csvSleepTogetherHours')
    base['sleepTogetherHoursObserved']=rec.get('sleepTogetherHoursObserved')
    base['sleepHoursDefaultNeverUsedForRibbon']=True
    base['shinyObserved']=rec.get('shinyObserved')
    base['shinyPolicy']='IMAGE_VISIBLE_IF_CLEAR_ELSE_CSV_DEFAULT_ZERO'
    base['imageId']=rec.get('imageId')
    base['referenceIdentityVerification']=rec.get('referenceIdentityVerification')
    return base


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--observations',type=Path,required=True)
    parser.add_argument('--master',type=Path,default=Path(__file__).with_name('MASTER_DATA.json'))
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args()
    master_bytes=a.master.read_bytes()
    if hashlib.sha256(master_bytes).hexdigest()!=PINNED_LEGACY_MASTER_SHA256:
        raise ValueError('Unreviewed master: legacy carryLimit semantics cannot be assumed; HOLD')
    master=json.loads(master_bytes.decode('utf-8'))
    if len(master['pokemon'])!=249: raise ValueError('unexpected master count')
    obs=json.loads(a.observations.read_text(encoding='utf-8'))
    if obs.get('purpose')!='READ_ONLY_AUDIT_NOT_GOLD': raise ValueError('untrusted purpose or observations')
    results=[evaluate_observation(master,x) for x in obs['imageObservations']]
    summary=dict(Counter(x['status'] for x in results))
    out={'status':'PROTOTYPE_HOLD','noProductionCsv':True,'count':len(results),'summary':summary,
         'observationsSource':obs.get('sourceDescription'),'results':results}
    a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('READ_ONLY',len(results),summary)
    for r in results:
        total=len(r['candidates']); joint=len(r['numericSupportedCandidates']);
        print(r['imageId'],r['reportedSpecies'],f'food-skill={total}',f'jointNumericSupport={joint}',
              'reportedSupported='+str(r.get('reportedSpecies') in r['numericSupportedCandidates']))

if __name__=='__main__':main()
