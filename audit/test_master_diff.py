#!/usr/bin/env python3
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('master_diff', ROOT / 'master_diff.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
BASE = json.loads((ROOT / 'MASTER_v011_BASELINE.json').read_text(encoding='utf-8'))

def make_upstream(base):
    names = {}
    skills = {}
    pokemon = []
    for p in base['pokemon']:
        en, skill = p['name_en'], p['skill']
        names[en] = p['name']
        if skill in skills and skills[skill]['name'] != p['mainSkill']:
            raise RuntimeError('Inconsistent skill fixture')
        skills[skill] = {'name': p['mainSkill']}
        row = {k: p.get(k) for k in audit.PROPS}
        row.update({'name': en, 'skill': skill})
        for i in (1,2,3):
            ing = p[f'ing{i}']
            row[f'ing{i}'] = None if ing is None else {'name': ing['key'], **{f'c{j}': ing.get(f'c{j}') for j in (1,2,3)}}
        if 'mythIng' in p:
            row['mythIng'] = [{'name': ing['key'], **{f'c{j}': ing.get(f'c{j}') for j in (1,2,3)}} for ing in p['mythIng']]
        pokemon.append(row)
    return {'pokemon': pokemon, 'pokemonsJa': {'pokemons': names},
            'skillsJa': {'skills': skills},
            'dataJa': {'ingredients': base['ingredients'],
                       'natures': {n['en']: n['ja'] for n in base['natures']},
                       'subskill': {s['en']: s['ja'] for s in base['subskills']}}}

class MasterAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = make_upstream(BASE)

    def compare(self, source):
        return audit.compare(BASE, source, {}, 'f'*40)

    def test_equal_snapshot_does_not_claim_compatibility(self):
        got = self.compare(self.data)
        self.assertEqual(got['status'], 'SOURCE_PROJECTION_MATCH_HOLD')
        self.assertFalse(got['productionCsvAllowed'])
        self.assertTrue(got['NOT_IMPORTER_VERIFIED'])
        self.assertFalse(got['deployedWebsiteCommitVerified'])
        self.assertEqual(got['summary'], dict(newSpecies=0, removedSpecies=0, changedSpecies=0, changedPokemonFields=0, changedTranslations=0))

    def test_new_species_detected(self):
        clone = copy.deepcopy(self.data)
        extra = copy.deepcopy(clone['pokemon'][0])
        extra['name'] = 'SyntheticNewPokemon'
        clone['pokemon'].append(extra)
        clone['pokemonsJa']['pokemons'][extra['name']] = 'テスト種'
        self.assertEqual(self.compare(clone)['summary']['newSpecies'], 1)

    def test_removed_species_detected(self):
        clone = copy.deepcopy(self.data)
        clone['pokemon'].pop(0)
        self.assertEqual(self.compare(clone)['summary']['removedSpecies'], 1)

    def test_ingredient_slot_change_detected(self):
        clone = copy.deepcopy(self.data)
        clone['pokemon'][0]['ing2']['c2'] = 999
        got = self.compare(clone)
        self.assertEqual(got['summary']['changedSpecies'], 1)
        self.assertTrue(any(row['field']=='ing2' for row in got['changedFields']))

    def test_skill_change_detected(self):
        clone = copy.deepcopy(self.data)
        key = clone['pokemon'][0]['skill']
        clone['skillsJa']['skills'][key]['name'] = '不正なスキル'
        self.assertGreater(self.compare(clone)['summary']['changedSpecies'], 0)

    def test_translation_change_detected(self):
        clone = copy.deepcopy(self.data)
        clone['dataJa']['ingredients']['honey'] = '別名'
        got = self.compare(clone)
        self.assertGreater(got['summary']['changedTranslations'], 0)

    def test_duplicate_species_fails_closed(self):
        clone = copy.deepcopy(self.data)
        clone['pokemon'].append(copy.deepcopy(clone['pokemon'][0]))
        with self.assertRaises(ValueError): self.compare(clone)

    def test_report_written_without_promotion(self):
        with tempfile.TemporaryDirectory() as d:
            got = self.compare(self.data)
            audit.write_report(Path(d), got)
            self.assertTrue((Path(d)/'MASTER_AUDIT.json').is_file())
            self.assertTrue((Path(d)/'CHANGED_FIELDS.csv').is_file())
            self.assertIn('NO DEPLOY', (Path(d)/'SUMMARY.md').read_text())

if __name__ == '__main__':
    unittest.main()
