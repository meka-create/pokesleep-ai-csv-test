"""Offline contract tests for the staged upstream updater (no live network)."""
import copy
import json
import pathlib
import sys
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from sync_upstream import SyncError,project

class UpstreamSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=pathlib.Path(self.tmp.name)
        self.src=self.base/'src'
        self.legacy=json.loads((ROOT/'site/kit-assets/MASTER_DATA.json' if (ROOT/'site/kit-assets/MASTER_DATA.json').exists() else ROOT/'kit-assets/MASTER_DATA.json').read_text())
        self.assets=self.src/'i18n/ja';self.assets.mkdir(parents=True)
        (self.src/'data').mkdir()
        self.src_json=[]
        self.names={}
        self.skills={}
        for i,p in enumerate(self.legacy['pokemon'],1):
            self.names[p['name_en']]=p['name']
            self.skills[p['skill']]={'name':p['mainSkill']}
            item={'id':i,'name':p['name_en'],'skill':p['skill']}
            for k in ('arrival','frequency','carryLimit','ingRate','skillRate','evolutionCount','evolutionLeft','specialty','type'):
                item[k]=p[k]
            for j in (1,2,3):
                k='ing'+str(j)
                val=p.get(k)
                if val: item[k]={'name':val['key'],**{a:b for a,b in val.items() if a in ('c1','c2','c3') and b is not None}}
            if p.get('mythIng'):
                item['mythIng']=[{'name':x['key'],**{a:x[a] for a in ('c1','c2','c3')}} for x in p['mythIng']]
            self.src_json.append(item)
        self.data={'ingredients':copy.deepcopy(self.legacy['ingredients']),
                   'natures':{x['en']:x['ja'] for x in self.legacy['natures']},
                   'subskill':{x['en']:x['ja'] for x in self.legacy['subskills']}}
        self.write()
    def write(self):
        for path,obj in ((self.src/'data/pokemon.json',self.src_json),
                         (self.assets/'pokemons.json',{'pokemons':self.names}),
                         (self.assets/'data.json',self.data),
                         (self.assets/'skills.json',{'skills':self.skills})):
            path.write_text(json.dumps(obj,ensure_ascii=False))
    def generate(self):
        self.write()
        return project(self.base,self.legacy,allow_fixture=True)
    def test_legacy_fixture_projects_without_species_change(self):
        master,diff=self.generate()
        self.assertEqual(len(master['pokemon']),len(self.legacy['pokemon']))
        self.assertEqual(diff['addedSpecies'],[])
        self.assertEqual(diff['removedSpecies'],[])
        self.assertFalse(diff['approvedForProduction'])
    def test_new_pokemon_is_staged_not_promoted(self):
        new=copy.deepcopy(self.src_json[0]);new.update(id=100000,name='Testmon',arrival='2026-10-09')
        self.src_json.append(new);self.names['Testmon']='テストモン'
        master,diff=self.generate()
        self.assertIn('Testmon',diff['addedSpecies'])
        self.assertEqual(next(p['name'] for p in master['pokemon'] if p['name_en']=='Testmon'),'テストモン')
        self.assertEqual(diff['status'],'STAGED_ONLY_NOT_IMPORT_VERIFIED')
        self.assertEqual(len(self.legacy['pokemon'])+1,len(master['pokemon']))
    def test_missing_translation_is_fatal(self):
        self.names.pop('Bulbasaur')
        with self.assertRaisesRegex(SyncError,'翻訳件数|日本語名'):self.generate()
    def test_unknown_ingredient_is_fatal(self):
        self.src_json[0]['ing1']['name']='future-ingredient-unknown'
        with self.assertRaisesRegex(SyncError,'未知の食材'):self.generate()
    def test_unknown_main_skill_is_fatal(self):
        self.src_json[0]['skill']='Future Unknown Skill'
        with self.assertRaisesRegex(SyncError,'メインスキル翻訳'):self.generate()
    def test_dropped_species_is_reported_without_rewriting_legacy(self):
        self.src_json.pop()
        _,diff=self.generate()
        self.assertEqual(len(diff['removedSpecies']),1)
        self.assertGreaterEqual(len(self.legacy['pokemon']),249)  # auto-promoted masters may contain additional species
    def test_changed_ingredient_is_diffed(self):
        self.src_json[0]['ing2']['name']='apple'
        _,diff=self.generate()
        self.assertIn('Bulbasaur',diff['changedSpecies'])
        self.assertIn('ing2',diff['changedSpecies']['Bulbasaur'])
    def test_new_subskill_and_translations_are_explicitly_reported(self):
        self.data['ingredients']['apple']='りんご【新表記】'
        self.data['subskill']['Helping Bonus']='おてつだいボーナス【新表記】'
        self.data['subskill']['Future Nonstandard Subskill']='未来の追加サブスキル'
        self.data['natures']['Hardy']='がんばりや【新表記】'
        master,diff=self.generate()
        self.assertIn('Future Nonstandard Subskill',diff['newSubskillKeys'])
        self.assertIn('Future Nonstandard Subskill',[x['en'] for x in master['subskills']])
        self.assertIn('apple',diff['changedIngredientTranslations'])
        self.assertIn('Helping Bonus',diff['changedSubskillTranslations'])
        self.assertIn('Hardy',diff['changedNatureTranslations'])
        self.assertFalse(diff['approvedForProduction'])
    def test_removed_subskill_and_invalid_translation_fail_closed(self):
        self.data['subskill'].pop('Helping Bonus')
        with self.assertRaisesRegex(SyncError,'翻訳定義の数が異常|サブスキル定義が減少'):self.generate()
        self.data['subskill']['Helping Bonus']=''
        # Existing translations must not silently become empty.
        with self.assertRaisesRegex(SyncError,'サブスキル'):self.generate()
    def test_missing_upstream_file_is_fatal(self):
        (self.assets/'skills.json').unlink()
        with self.assertRaisesRegex(SyncError,'必要ファイル'):project(self.base,self.legacy,allow_fixture=True)

if __name__=='__main__':unittest.main()
