#!/usr/bin/env python3
"""Stage a verified structural projection of pokesleep-tool data; NEVER auto-publish.

Run against a pinned Git checkout. This tool intentionally does not assert actual
CSV import compatibility or deployed-site compatibility; those require independent
verification before productionCsvAllowed may be enabled.

Upstream files read: src/data/pokemon.json, src/i18n/ja/{pokemons,data,skills}.json.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

class SyncError(Exception): pass

def require(value, message):
    if not value: raise SyncError(message)

def load_json(file):
    with Path(file).open(encoding='utf-8') as fh: return json.load(fh)

def dump_json(file, value):
    Path(file).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n',encoding='utf-8')

def source_commit(source, allow_fixture=False):
    if allow_fixture: return 'TEST-FIXTURE-NOT-A-REAL-COMMIT'
    try:
        value=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError) as e: raise SyncError('上流ソースに固定git commitがありません') from e
    require(re.fullmatch(r'[a-f0-9]{40}',value), 'git commitが不正')
    return value

def validate_upstream(source):
    base=source/'src'
    paths={
        'pokemon':base/'data/pokemon.json',
        'pokemonsJa':base/'i18n/ja/pokemons.json',
        'dataJa':base/'i18n/ja/data.json',
        'skillsJa':base/'i18n/ja/skills.json',
    }
    for label,path in paths.items():require(path.is_file(), f'上流に必要ファイルがありません: {label}: {path}')
    obj={key:load_json(path) for key,path in paths.items()}
    names=obj['pokemonsJa']['pokemons']
    ingredients=obj['dataJa']['ingredients']
    natures=obj['dataJa']['natures']
    subskills=obj['dataJa']['subskill']
    skills=obj['skillsJa']['skills']
    require(all(isinstance(a,dict) for a in (names,ingredients,natures,subskills,skills)), '翻訳スキーマが想定外')
    poke=obj['pokemon'];require(isinstance(poke,list) and len(poke)>100,'ポケモンの上流リストが異常')
    require(len(names)>=len(poke),'ポケモン翻訳件数が不足')
    require(len(ingredients)>=15 and len(natures)==25 and len(subskills)>=17,'翻訳定義の数が異常')
    return obj,paths

def project(source, legacy, allow_fixture=False):
    obj,paths=validate_upstream(source)
    commit=source_commit(source,allow_fixture)
    names=obj['pokemonsJa']['pokemons'];ja=obj['dataJa'];skills=obj['skillsJa']['skills']
    legacy_by_en={p['name_en']:p for p in legacy['pokemon']}
    ingredient_names=ja['ingredients']
    used_names=[];used_ids=[];result=[]
    for p in obj['pokemon']:
        en=p.get('name');uid=p.get('id')
        require(isinstance(en,str) and en in names and names[en], f'上流の種族に日本語名がありません: {en}')
        require(type(uid) is int and uid>0,f'上流の種族IDが不正: {en}')
        ja_name=names[en]
        used_names.append(en);used_ids.append((uid,p.get('form') or ''))
        skill=p.get('skill')
        require(isinstance(skill,str) and skill in skills and isinstance(skills[skill],dict) and skills[skill].get('name'),f'上流にメインスキル翻訳がありません: {en} {skill}')
        out={}
        out['name']=ja_name;out['name_en']=en;out['skill']=skill;out['mainSkill']=skills[skill]['name']
        for key in ('arrival','frequency','carryLimit','ingRate','skillRate','evolutionCount','evolutionLeft','specialty','type'):
            require(key in p and p[key] is not None,f'上流ポケモンの必須値欠損: {en}.{key}')
            out[key]=p[key]
        for i in (1,2,3):
            raw=p.get(f'ing{i}')
            if raw is None:
                require(i==3,f'上流の食材候補欠落: {en}, ing{i}')
                out[f'ing{i}']=None
                continue
            require(isinstance(raw,dict),f'食材情報の構造異常: {en}.ing{i}')
            key=raw.get('name')
            # The upstream uses `unknown` placeholders for mythical Pokemon.
            require(key in ingredient_names or (p.get('mythIng') and key in ('unknown','unknown1','unknown2','unknown3')),
                    f'未知の食材キー: {en}.ing{i} {key}')
            value={'key':key,'name':ingredient_names.get(key,key)}
            for count in ('c1','c2','c3'):value[count]=raw.get(count)
            out[f'ing{i}']=value
        if p.get('mythIng'):
            require(isinstance(p['mythIng'],list),'幻ポケモン食材情報の型が不正')
            out['mythIng']=[]
            for entry in p['mythIng']:
                key=entry.get('name')
                require(key in ingredient_names,f'未知の幻ポケモン食材: {en}:{key}')
                out['mythIng'].append({'key':key,'name':ingredient_names[key],**{k:entry.get(k) for k in ('c1','c2','c3')}})
        # The master is built from upstream data, never from guessed species mappings.
        result.append(out)
    require(len(set(used_names))==len(used_names),'上流に同名種族が重複')
    require(len(set(used_ids))==len(used_ids),'上流に種族ID＋フォルム重複')
    old_skills={s['en']:s for s in legacy['subskills']}
    require(all(isinstance(k,str) and k and isinstance(v,str) and v
                for k,v in ja['subskill'].items()), 'サブスキルのキー・翻訳が不正')
    all_subskills=[]
    # Keep subskill metadata of known entries; completely new entries are staged
    # without untrusted values, and compatibility must be verified separately.
    for name,translated in ja['subskill'].items():
        if name in old_skills:
            all_subskills.append({**old_skills[name], 'ja':translated})
        else:
            # Stage every new upstream key visibly, even if its naming differs;
            # do not guess missing metadata or promote it to the published master.
            require(isinstance(name,str) and name and isinstance(translated,str) and translated,
                    '新サブスキルの名前または日本語訳が不正')
            all_subskills.append({'en':name,'ja':translated})
    require(len(all_subskills)>=len(legacy['subskills']),'サブスキル定義が減少しています')
    old_natures={n['en']:n for n in legacy['natures']}
    require(set(ja['natures'])==set(old_natures),'せいかくのキー集合が変更されました。自動マージしません')
    new_natures=[{**old_natures[name], 'ja':value} for name,value in ja['natures'].items()]
    master={
        'cutoff':max(p['arrival'] for p in obj['pokemon']),
        'pokemon':result,
        'ingredients':dict(sorted(ingredient_names.items())),
        'natures':new_natures,
        'subskills':all_subskills,
        'provenance':{
            'origin':'pokesleep-tool directly (staged, NOT import verified)',
            'upstream':'https://github.com/nitoyon/pokesleep-tool',
            'sourceCommit':commit,
            'sourceFilesSha256':{label:hashlib.sha256(path.read_bytes()).hexdigest() for label,path in paths.items()},
            'verification':'SOURCE STRUCTURE ONLY; import/deployed-app/E2E NOT verified'
        }
    }
    existing={p['name_en']:p for p in legacy['pokemon']}
    newer={p['name_en']:p for p in result}
    added=sorted(set(newer)-set(existing));removed=sorted(set(existing)-set(newer))
    changed={}
    for name in set(existing)&set(newer):
        old=existing[name];new=newer[name]
        keys=set(old)|set(new)
        # Report even display-name changes. They may affect importer CSV semantics.
        diff={key:{'old':old.get(key),'new':new.get(key)} for key in keys if old.get(key)!=new.get(key)}
        if diff: changed[name]=diff
    old_ingredients=legacy['ingredients']
    old_subskills={x['en']:x['ja'] for x in legacy['subskills']}
    old_natures={x['en']:x['ja'] for x in legacy['natures']}
    new_subskills={x['en']:x['ja'] for x in all_subskills}
    def translation_changes(old_map, new_map):
        return {key:{'old':old_map[key],'new':new_map[key]}
                for key in sorted(set(old_map)&set(new_map)) if old_map[key]!=new_map[key]}
    return master,{
        'sourceCommit':commit,'sourcePokemonCount':len(result),'previousPokemonCount':len(existing),
        'addedSpecies':added,'removedSpecies':removed,'changedSpecies':changed,
        'newIngredientKeys':sorted(set(ingredient_names)-set(old_ingredients)),
        'removedIngredientKeys':sorted(set(old_ingredients)-set(ingredient_names)),
        'changedIngredientTranslations':translation_changes(old_ingredients,ingredient_names),
        'newSubskillKeys':sorted(set(new_subskills)-set(old_subskills)),
        'removedSubskillKeys':sorted(set(old_subskills)-set(new_subskills)),
        'changedSubskillTranslations':translation_changes(old_subskills,new_subskills),
        'newNatureKeys':sorted(set(ja['natures'])-set(old_natures)),
        'removedNatureKeys':sorted(set(old_natures)-set(ja['natures'])),
        'changedNatureTranslations':translation_changes(old_natures,ja['natures']),
        'status':'STAGED_ONLY_NOT_IMPORT_VERIFIED',
        'approvedForProduction':False,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--upstream',required=True)
    p.add_argument('--master',default='site/kit-assets/MASTER_DATA.json')
    p.add_argument('--out',default='upstream_staging')
    p.add_argument('--fixture',action='store_true',help='tests only: bypass real Git commit; never enable production')
    a=p.parse_args()
    source=Path(a.upstream).resolve();legacy=load_json(a.master)
    try:
        master,changes=project(source,legacy,allow_fixture=a.fixture)
        output=Path(a.out);output.mkdir(parents=True,exist_ok=True)
        dump_json(output/'MASTER_DATA.candidate.json',master)
        dump_json(output/'UPSTREAM_DIFF.json',changes)
        # Never modify site/kit-assets in this script.
        print(json.dumps({'candidate':str(output/'MASTER_DATA.candidate.json'),**{k:changes[k] for k in ('sourceCommit','sourcePokemonCount','addedSpecies','removedSpecies','newIngredientKeys')},'productionEnabled':False},ensure_ascii=False))
        return 0
    except (SyncError,KeyError,ValueError,TypeError,FileNotFoundError) as e:
        print('上流データの検証失敗（現行キットを変更しません）:',e,file=sys.stderr)
        return 2
if __name__=='__main__':raise SystemExit(main())
