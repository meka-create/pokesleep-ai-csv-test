#!/usr/bin/env python3
"""Read-only species evidence audit for Pokémon Sleep AI CSV v0.12.

No production CSV is generated. Never fill unknown sleeping-together hours
with the export policy's zero, or discard a species on help/SP/carry alone.

Source: pinned v0.12 MASTER_DATA.json. Older OCR classifier (separate project)
was reviewed as reference; no old Candidate source was modified or imported.
"""
from __future__ import annotations
import argparse
import csv
import json
import pathlib
import unicodedata
from collections import Counter

HEADER = ('ニックネーム','ポケモン','レベル','スキルレベル','食材1','食材2','食材3',
          'メインスキル','せいかく','Lv10','Lv25','Lv50','Lv70','Lv80',
          '一緒に眠った時間','色違い')
# Keep CSV blanks distinct from data that the AI simply could not read.
FOOD_BLANK_ALLOWED = {'ミュウ': frozenset((3,)), 'ダークライ': frozenset((2,3))}

def normalize_skill(v):
    return ''.join(unicodedata.normalize('NFKC', str(v or '')).split())

def skill_compatible(observed, master):
    o, m = normalize_skill(observed), normalize_skill(master)
    if not o:
        return True   # missing evidence, not a negative match
    if o == 'エナジーチャージS':
        return m in ('エナジーチャージS','エナジーチャージS(ランダム)')
    if o == 'ゆめのかけらゲットS':
        return m in ('ゆめのかけらゲットS','ゆめのかけらゲットS(ランダム)')
    if o.startswith('おてつだいブースト'):
        return m == 'おてつだいブースト'
    return o == m

def candidates_for_food_slot(pokemon, slot):
    """Emit (food-name, quantity) options for the specified slot.

    Reuses the accepted v0.12 rule: ing1 may appear in all three slots;
    ing2 in slots 2-3, ing3 only in slot 3. Mythic alternate foods apply
    the same slot quantity check.
    """
    results = set()
    for position in range(1, slot+1):
        entry = pokemon.get(f'ing{position}') or {}
        qty = entry.get(f'c{slot}')
        if isinstance(qty, int) and not isinstance(qty,bool) and qty > 0:
            name = entry.get('name')
            if name and name != 'unknown': results.add((name,qty))
    for entry in pokemon.get('mythIng',[]) or []:
        qty=entry.get(f'c{slot}')
        if isinstance(qty,int) and not isinstance(qty,bool) and qty>0:
            name=entry.get('name')
            if name and name!='unknown': results.add((name,qty))
    return results

def match_one(pokemon, skill, foods, quantities=None):
    if not skill_compatible(skill,pokemon.get('mainSkill')):
        return False
    for idx, food in enumerate(foods,1):
        if food is None:  # unread/occluded; no claim and no exclusion
            continue
        if food=='':
            if idx not in FOOD_BLANK_ALLOWED.get(pokemon.get('name'),frozenset()):
                return False
            continue
        opts=candidates_for_food_slot(pokemon,idx)
        qty=quantities[idx-1] if quantities is not None else None
        if qty is not None and (not isinstance(qty,int) or isinstance(qty,bool) or qty <= 0):
            raise ValueError(f'Quantity for slot {idx} must be positive int or null')
        if not any(v==food and (qty is None or qty==q) for v,q in opts):
            return False
    return True

def evaluate(master, input_record):
    food=input_record.get('foods', [None,None,None])
    qty=input_record.get('quantities')
    if not isinstance(food,list) or len(food)!=3:
        raise ValueError('foods requires exactly three values; null means unread, empty string means confirmed blank')
    if qty is not None and (not isinstance(qty,list) or len(qty)!=3):
        raise ValueError('quantities requires three values or null')
    skill=input_record.get('mainSkill')
    original=input_record.get('species')
    evidence_missing=any(x is None for x in food) or not skill
    candidate_names=[p['name'] for p in master['pokemon'] if match_one(p,skill,food,qty)]
    if not candidate_names:
        status='CONTRADICTION_HOLD'
    elif evidence_missing:
        status='INCOMPLETE_EVIDENCE_HOLD'
    elif len(candidate_names)>1:
        status='AMBIGUOUS_NEEDS_MORE_EVIDENCE'
    else:
        status='UNIQUE_BY_DATA'
    # Species is NEVER overwritten by this audit; conflict requires review.
    if original and original not in candidate_names:
        status='SPECIES_CONFLICT_HOLD'
    return {
        'status':status,
        'reportedSpecies':original,
        'candidates':candidate_names,
        'candidateCount':len(candidate_names),
        'observed':{'mainSkill':skill,'foods':food,'quantities':qty},
        'doNotAutoCorrect':True,
        'observedHelpSeconds':input_record.get('helpSeconds'),
        'observedCarry':input_record.get('carry'),
        'observedSp':input_record.get('sp'),
        # Output default 0 is NEVER used to instantiate a ribbon tier.
        'sleepTogetherHours':'UNKNOWN_FOR_CLASSIFICATION',
        'numericEvidence':('NOT_USED_FOR_EXCLUSION: ribbon/evolution and ±1s old-classifier '
                           'require separate proof; SP strict-equality not ported'),
    }

def run_csv(master, source):
    with open(source,encoding='utf-8-sig',newline='') as fh:
        rd=csv.DictReader(fh)
        if rd.fieldnames!=list(HEADER):
            raise ValueError('unexpected 16-column CSV header')
        result=[]
        for i,r in enumerate(rd,1):
            rec={'species':r['ポケモン'], 'mainSkill':r['メインスキル'],
                 'foods':[r[f'食材{x}'] for x in range(1,4)],
                 'imageId':f'{source.stem}-{i:03d}', 'nickname':r['ニックネーム']}
            report=evaluate(master,rec)
            report['imageId']=rec['imageId']
            report['nickname']=rec['nickname']
            report['csvSleepTogetherHours']=r['一緒に眠った時間']
            result.append(report)
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--master',type=pathlib.Path,default=pathlib.Path(__file__).with_name('MASTER_DATA.json'))
    p.add_argument('--csv', type=pathlib.Path, action='append',required=True)
    p.add_argument('--output',type=pathlib.Path, required=True)
    args=p.parse_args()
    master=json.loads(args.master.read_text(encoding='utf-8'))
    if len(master['pokemon'])!=249:
        raise ValueError('expected exactly the pinned 249 species; abort on unexpected master')
    results=[y for f in args.csv for y in run_csv(master,f)]
    summary=dict(Counter(x['status'] for x in results))
    output={'mode':'READ_ONLY_PROTOTYPE_HOLD','masterSpecies':len(master['pokemon']),
            'total':len(results),'statusCounts':summary,'results':results}
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"AUDIT {len(results)} rows / 249 master species / {summary}")
    for x in results:
        if x['status']!='UNIQUE_BY_DATA':
            print(f"  {x['nickname']} {x['reportedSpecies']}: {x['status']} "+
                  f"({x['candidateCount']} candidates: {', '.join(x['candidates'][:8])})")

if __name__=='__main__':
    main()
