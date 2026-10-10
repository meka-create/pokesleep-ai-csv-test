#!/usr/bin/env python3
"""Generate 16-col candidate-dependent CSV vectors for REAL importer E2E.

No synthetic UI, no Golden data, and no production CSV. Unsupported new
semantics fail closed rather than silently omitting the changed feature.
"""
import argparse, csv, hashlib, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
KIT = ROOT/'site/kit-assets' if (ROOT/'site/kit-assets/VALIDATOR.py').is_file() else ROOT/'kit-assets'
sys.path.insert(0,str(KIT))
import VALIDATOR as v

class VectorError(ValueError):pass

def build(master_file,diff_file,out_file,coverage_file, *, validator=v):
    master=json.loads(Path(master_file).read_text(encoding='utf-8'))
    diff=json.loads(Path(diff_file).read_text(encoding='utf-8'))
    schema=json.loads((KIT/'CSV_SCHEMA.json').read_text(encoding='utf-8'))
    species={p['name']:p for p in master['pokemon']}
    english={p['name_en']:p for p in master['pokemon']}
    foods=set(master['ingredients'].values())
    natures={n['ja'] for n in master['natures']}
    subskills={n['ja'] for n in master['subskills']}
    if len(species)!=len(master['pokemon']) or len(subskills)<5 or 'きまぐれ' not in natures:
        raise VectorError('Master is missing necessary CSV test values')
    changed=diff.get('addedSpecies',[])
    if not isinstance(changed,list) or len(set(changed))!=len(changed):
        raise VectorError('Invalid species delta')
    # First a known-old control, then every new/modified species. Each changed
    # ingredient and subskill MUST occur in at least one generated row.
    modified=sorted(diff.get('changedSpecies',{}))
    legacy=next((p for p in master['pokemon'] if p['name_en'] not in set(changed+modified) and p['name']!='ストリンダー (ロー)'),None)
    if legacy is None:raise VectorError('No stable legacy control')
    chosen=[legacy]+[english[x] for x in sorted(set(changed+modified)) if x in english]
    if len(chosen)!=1+len(set(changed+modified)):
        raise VectorError('New species cannot be found in candidate')
    # A new ingredient may only appear on a previously known species.
    new_food_keys=set(diff.get('newIngredientKeys',[]))
    new_skills=set(diff.get('newSubskillKeys',[]))
    def can_represent_food(p,k):
        return any(p.get('ing'+str(i)) and p['ing'+str(i)].get('key')==k for i in (1,2,3))
    for key in sorted(new_food_keys):
        p=next((p for p in master['pokemon'] if can_represent_food(p,key)),None)
        if p is None:raise VectorError('New ingredient has no valid species source: '+key)
        if p not in chosen:chosen.append(p)
    # Existing frozen schema does not support all future semantics. Never claim
    # automatic compatibility for new nature keys / unknown CSV columns.
    if diff.get('newNatureKeys') or diff.get('removedNatureKeys'):
        raise VectorError('Unrecognized nature schema transition')
    new_subskill_jas={s['ja'] for s in master['subskills'] if s['en'] in new_skills}
    if len(new_subskill_jas)!=len(new_skills):raise VectorError('Missing new subskill translation')
    ordinary=sorted(subskills-new_subskill_jas)
    if len(ordinary)<5:raise VectorError('Insufficient stable subskills')
    output=[];actual_species=set();covered_food=set();covered_skill=set()
    # Extra rows guarantee each new subskill gets roundtripped (5 slots max).
    repeats=max(1,(len(new_subskill_jas)+4)//5)
    for i,p in enumerate(chosen):
        for repeat in range(repeats if i==0 else 1):
            foods_three=[]
            for slot in (1,2,3):
                options=validator.food_candidates_for_slot(p,slot,foods)
                if not options:raise VectorError('No food for '+p['name']+' slot '+str(slot))
                prioritized=[master['ingredients'][k] for k in sorted(new_food_keys) if master['ingredients'][k] in options]
                foods_three.append(prioritized[0] if prioritized else sorted(options)[0])
                covered_food.update(k for k in new_food_keys if foods_three[-1]==master['ingredients'][k])
            extras=sorted(new_subskill_jas)[repeat*5:repeat*5+5] if i==0 else []
            skillvals=(extras+ordinary)[:5]
            covered_skill.update(x for x in new_skills if any(s['en']==x and s['ja'] in skillvals for s in master['subskills']))
            row={'imageId':f'AUTO_{i:04d}_{repeat}', 'reviewComplete':True,'unresolved':[],
                 'data':{'nickname':f'検証{i:03d}_{repeat}', 'species':p['name'], 'level':60,'skillLevel':3,
                         'foods':foods_three, 'mainSkill':p['mainSkill'],
                         'nature':'てれや' if p['name']=='ストリンダー (ロー)' else 'きまぐれ',
                         'subskills':skillvals,'sleepTogetherHours':0,'shiny':0,
                         'fieldEvidence':{'sleepTogetherHours':'user-policy-default','shiny':'user-policy-default'}}}
            if p['name']=='ミュウ':row['data']['versatileSkill']='Berry Burst'
            try:values=validator.validate_included(row,species,foods,natures,subskills,schema['mewVersatileCsvLabels'],master,schema)
            except Exception as exc:raise VectorError(f'Frozen validator rejected {p["name"]}: {exc}') from exc
            if len(values)!=16:raise VectorError('CSV columns not 16')
            output.append(values);actual_species.add(p['name_en'])
    if covered_food!=new_food_keys or covered_skill!=new_skills:
        raise VectorError(f'Changed feature not covered: food {new_food_keys-covered_food}; subskills {new_skills-covered_skill}')
    out_file=Path(out_file);out_file.parent.mkdir(parents=True,exist_ok=True)
    with out_file.open('w',encoding='utf-8',newline='') as h:
        w=csv.writer(h,lineterminator='\n');w.writerow(validator.EXPECTED_HEADER);w.writerows(output)
    report={'schemaVersion':'auto-vector-coverage-v1','rows':len(output),
        'coveredSpecies':sorted(actual_species),'coveredNewSpecies':sorted(set(changed)&actual_species),
        'coveredNewIngredientKeys':sorted(covered_food),'coveredNewSubskillKeys':sorted(covered_skill),
        'csvSha256':hashlib.sha256(out_file.read_bytes()).hexdigest(), 'developmentOnly':True}
    Path(coverage_file).write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--master',required=True);ap.add_argument('--diff',required=True)
    ap.add_argument('--csv',required=True);ap.add_argument('--coverage',required=True)
    a=ap.parse_args()
    try:
        print(json.dumps(build(a.master,a.diff,a.csv,a.coverage),ensure_ascii=False))
    except Exception as e:
        print('HOLD: '+str(e),file=sys.stderr);sys.exit(2)
