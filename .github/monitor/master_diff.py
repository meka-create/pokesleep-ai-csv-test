#!/usr/bin/env python3
"""Compare a frozen v0.11 legacy master to ONE pinned upstream Git checkout.

Only emits audit evidence; never modifies the master or enables CSV release.
Does NOT prove the deployed web app commit or importer compatibility.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

FILES = {
    'pokemon': 'src/data/pokemon.json',
    'pokemonsJa': 'src/i18n/ja/pokemons.json',
    'dataJa': 'src/i18n/ja/data.json',
    'skillsJa': 'src/i18n/ja/skills.json',
}
PROPS = ('arrival', 'frequency', 'carryLimit', 'ingRate', 'skillRate',
         'evolutionCount', 'evolutionLeft', 'specialty', 'type')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def entry_of_ingredient(obj, translate):
    if obj is None:
        return None
    if not isinstance(obj, dict):
        raise ValueError('ingredient entry is not object')
    key = obj.get('name')
    # Unknown placeholders are preserved; unmatched keys must be visible in report.
    return {'key': key, 'name': translate.get(key, key),
            **{f'c{i}': obj.get(f'c{i}') for i in (1, 2, 3)}}


def project(upstream):
    pokemons = upstream['pokemon']
    if not isinstance(pokemons, list) or not pokemons:
        raise ValueError('upstream pokemon list missing')
    names = upstream['pokemonsJa']['pokemons']
    translations = upstream['dataJa']
    items = translations['ingredients']
    skills = upstream['skillsJa']['skills']
    out = {}
    for pokemon in pokemons:
        en = pokemon['name']
        if not isinstance(en, str) or en in out:
            raise ValueError(f'upstream Pokemon English-name collision: {en!r}')
        if en not in names or pokemon['skill'] not in skills:
            raise ValueError(f'upstream Pokemon translation/skill missing: {en!r}')
        row = {'name_en': en, 'name': names[en], 'skill': pokemon['skill'],
               'mainSkill': skills[pokemon['skill']]['name']}
        for key in PROPS:
            row[key] = pokemon.get(key)
        for i in (1, 2, 3):
            row[f'ing{i}'] = entry_of_ingredient(pokemon.get(f'ing{i}'), items)
        if 'mythIng' in pokemon:
            raw = pokemon['mythIng']
            if not isinstance(raw, list):
                raise ValueError('unexpected mythIng structure for ' + en)
            row['mythIng'] = [entry_of_ingredient(entry, items) for entry in raw]
        out[en] = row
    return out, translations


def compare(baseline, upstream, sha, commit):
    now, translations = project(upstream)
    old_list = baseline['pokemon']
    old = {p['name_en']: p for p in old_list}
    if len(old) != len(old_list):
        raise ValueError('baseline duplicate name_en')
    added = sorted(set(now) - set(old))
    removed = sorted(set(old) - set(now))
    changed = []
    for en in sorted(set(now) & set(old)):
        new_row, old_row = now[en], old[en]
        for field in sorted(set(new_row) | set(old_row)):
            if new_row.get(field) != old_row.get(field):
                changed.append({'pokemonEn': en, 'pokemonJa': new_row['name'],
                                'field': field, 'old': old_row.get(field),
                                'upstream': new_row.get(field)})
    old_nature = {n['en']: n['ja'] for n in baseline['natures']}
    old_sub = {n['en']: n['ja'] for n in baseline['subskills']}
    global_diff = []
    for domain, left, right in (
        ('ingredients', baseline['ingredients'], translations['ingredients']),
        ('natures', old_nature, translations['natures']),
        ('subskills', old_sub, translations['subskill']),
    ):
        for key in sorted(set(left) | set(right)):
            if left.get(key) != right.get(key):
                global_diff.append({'domain': domain, 'key': key,
                                    'old': left.get(key), 'upstream': right.get(key)})
    result = {
        'status': 'DIFFERENCES_FOUND_HOLD' if (added or removed or changed or global_diff) else 'SOURCE_PROJECTION_MATCH_HOLD',
        'NOT_IMPORTER_VERIFIED': True,
        'productionCsvAllowed': False,
        'deployedWebsiteCommitVerified': False,
        'sourceCommit': commit,
        'sourceFilesSha256': sha,
        'baselineMasterSha256': None,
        'baselinePokemonCount': len(old),
        'upstreamPokemonCount': len(now),
        'addedSpecies': [{'name_en': n, 'name_ja': now[n]['name']} for n in added],
        'removedSpecies': [{'name_en': n, 'name_ja': old[n]['name']} for n in removed],
        'changedFields': changed,
        'translationDifferences': global_diff,
        'summary': {
            'newSpecies': len(added), 'removedSpecies': len(removed),
            'changedSpecies': len({x['pokemonEn'] for x in changed}),
            'changedPokemonFields': len(changed),
            'changedTranslations': len(global_diff)
        },
        'auditScope': 'structural upstream JSON vs frozen v0.11 baseline; importer and deployed site NOT tested',
    }
    return result


def write_report(out, report):
    out.mkdir(parents=True, exist_ok=True)
    (out / 'MASTER_AUDIT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    summary = report.get('summary', {})
    lines = ['# pokesleep-tool v0.11 master audit', '',
             '**' + report['status'] + '** — NO DEPLOY / NO RELEASE', '',
             'Upstream commit: `' + str(report.get('sourceCommit', 'UNKNOWN')) + '`',
             'Baseline master SHA-256: `' + str(report.get('baselineMasterSha256', 'UNKNOWN')) + '`',
             '', '| Measure | Count |', '|---|---:|',
             '| baseline species | ' + str(report.get('baselinePokemonCount', 'unknown')) + ' |',
             '| upstream species | ' + str(report.get('upstreamPokemonCount', 'unknown')) + ' |']
    for key, title in [('newSpecies', 'new species'), ('removedSpecies', 'removed species'),
                       ('changedSpecies', 'changed species'), ('changedPokemonFields', 'changed fields'),
                       ('changedTranslations', 'translation differences')]:
        lines.append(f'| {title} | {summary.get(key, "unknown")} |')
    lines += ['', '## Added species (up to first 100)', '']
    lines += ['- ' + x['name_ja'] + ' (' + x['name_en'] + ')' for x in report.get('addedSpecies', [])[:100]] or ['(none)']
    lines += ['', '## Removed species (up to first 100)', '']
    lines += ['- ' + x['name_ja'] + ' (' + x['name_en'] + ')' for x in report.get('removedSpecies', [])[:100]] or ['(none)']
    lines += ['', '## Errors (if any)', '']
    lines += ['- ' + x for x in report.get('errors', [])] or ['(none)']
    lines += ['', '**Important:** PASS for this audit means only the structural JSON comparison ran. It does not mean CSV importer compatibility, deployed-site commit matching, or AI OCR accuracy.', '']
    (out / 'SUMMARY.md').write_text('\n'.join(lines), encoding='utf-8')
    with (out / 'CHANGED_FIELDS.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['種族EN', '種族JA', 'フィールド', 'v0.11', '上流'])
        for x in report.get('changedFields', []):
            w.writerow([x['pokemonEn'], x['pokemonJa'], x['field'],
                        json.dumps(x['old'], ensure_ascii=False, sort_keys=True),
                        json.dumps(x['upstream'], ensure_ascii=False, sort_keys=True)])


def audit(upstream_root, baseline_path, expected_baseline_sha256=None):
    upstream_root, baseline_path = Path(upstream_root), Path(baseline_path)
    if expected_baseline_sha256 and digest(baseline_path) != expected_baseline_sha256:
        raise ValueError('baseline master SHA-256 mismatch — do not accept changed baseline')
    commit = subprocess.check_output(['git', '-C', str(upstream_root), 'rev-parse', 'HEAD'], text=True).strip()
    if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('upstream checkout commit invalid')
    data, sha = {}, {}
    for key, filename in FILES.items():
        p = upstream_root / filename
        data[key] = load_json(p)
        sha[key] = digest(p)
    baseline = load_json(baseline_path)
    output = compare(baseline, data, sha, commit)
    output['baselineMasterSha256'] = digest(baseline_path)
    return output


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--upstream', required=True)
    p.add_argument('--baseline', required=True)
    p.add_argument('--out', default='audit_results')
    p.add_argument('--baseline-sha256', default=None)
    a = p.parse_args()
    try:
        result = audit(a.upstream, a.baseline, a.baseline_sha256)
    except (OSError, KeyError, IndexError, ValueError, TypeError, subprocess.CalledProcessError) as exc:
        result = {'status': 'AUDIT_ERROR_HOLD', 'productionCsvAllowed': False,
                  'NOT_IMPORTER_VERIFIED': True, 'errors': [type(exc).__name__ + ': ' + str(exc)]}
    write_report(Path(a.out), result)
    print(json.dumps({k: result.get(k) for k in ('status','sourceCommit','summary','errors','productionCsvAllowed')}, ensure_ascii=False))
    return 2 if result['status'] == 'AUDIT_ERROR_HOLD' else 0

if __name__ == '__main__':
    sys.exit(main())
