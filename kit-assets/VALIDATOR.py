#!/usr/bin/env python3
"""Deterministic, fail-closed pokesleep-tool CSV exporter for AI hand-off packages.

Usage, from the extracted ZIP directory:
    python3 VALIDATOR.py --records /tmp/working_records.json --package-dir .

Normal mode refuses a source snapshot not yet verified against live pokesleep-tool.
Engineers can use --prototype-test ONLY for local smoke tests. NEVER tell end users
that the resulting prototype CSV was verified to import.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import pathlib
import os
import tempfile
import struct
import zlib
import re
import sys

# Pinned importer header: never take the expected names only from the mutable schema.
FOOD_BLANK_ALLOWED = {'ミュウ': (3,), 'ダークライ': (2, 3)}

# Observed pokesleep-tool CSV round-trip compatibility guard (2026-10-09).
# For the two Toxtricity forms, mismatched natures were silently changed by
# the LIVE importer/exporter. Fail closed; NEVER guess a replacement nature.
# Only these two exact species names are constrained by this evidence.
TOXTRICITY_FORM_NATURES = {
    'ストリンダー (ハイ)': frozenset((
        'いじっぱり', 'やんちゃ', 'ゆうかん', 'なまいき', 'うっかりや',
        'わんぱく', 'のうてんき', 'ようき', 'せっかち', 'むじゃき',
        'がんばりや', 'きまぐれ', 'すなお',
    )),
    'ストリンダー (ロー)': frozenset((
        'さみしがり', 'しんちょう', 'おとなしい', 'おだやか',
        'ずぶとい', 'のんき', 'おっとり', 'れいせい', 'ひかえめ',
        'おくびょう', 'てれや', 'まじめ',
    )),
}

EXPECTED_HEADER = (
    'ニックネーム', 'ポケモン', 'レベル', 'スキルレベル', '食材1',
    '食材2', '食材3', 'メインスキル', 'せいかく',
    'Lv10', 'Lv25', 'Lv50', 'Lv70', 'Lv80',
    '一緒に眠った時間', '色違い',
)

class ValidationError(Exception):
    pass


def require(cond, message):
    if not cond:
        raise ValidationError(message)


def load_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


# Conservative stdlib-only binary/structure check; hashes alone do not show that
# purported image bytes are actually PNG/JPEG/WebP. This does NOT prove that an
# image is a Pokémon Sleep screenshot or guarantee a successful full decode.
def check_image_format(path):
    name = path.name.lower()
    size = path.stat().st_size
    require(size >= 20, f'画像形式が不正/短すぎます: {path.name}')
    # Only read the header and trailer; never allocate a second full-size
    # in-memory copy of user screenshots merely to check their signatures.
    with path.open('rb') as fh:
        head = fh.read(64)
        fh.seek(max(0, size - 16))
        tail = fh.read()
    if name.endswith('.png'):
        valid = (head[:8] == b'\x89PNG\r\n\x1a\n'
                 and head[12:16] == b'IHDR'
                 and struct.unpack('>I', head[8:12])[0] == 13
                 and size >= 45 and tail[-12:-8] == b'\x00\x00\x00\x00'
                 and tail[-8:-4] == b'IEND'
                 and zlib.crc32(head[12:29]) & 0xffffffff == struct.unpack('>I', head[29:33])[0])
    elif name.endswith(('.jpg', '.jpeg')):
        valid = head.startswith(b'\xff\xd8\xff') and tail.endswith(b'\xff\xd9')
    elif name.endswith('.webp'):
        valid = (head[:4] == b'RIFF' and head[8:12] == b'WEBP'
                 and head[12:16] in (b'VP8 ', b'VP8L', b'VP8X')
                 and struct.unpack('<I', head[4:8])[0] + 8 == size)
    else:
        valid = False
    require(valid, f'拡張子と画像バイナリ形式が一致しない/破損の疑い: {path.name}')


def food_candidates_for_slot(poke, slot, ingredient_set):
    """All species: allowed ingredient iff its CURRENT SLOT quantity is >0.

    ing1 can be present in slots 1/2/3; ing2 in slots 2/3; ing3 in slot 3.
    Mythical per-slot alternatives are subject to the SAME c1/c2/c3 test.
    """
    require(slot in (1, 2, 3), '食材位置が不正です')
    allowed = set()
    for position in range(1, slot + 1):
        entry = poke.get(f'ing{position}') or {}
        qty = entry.get(f'c{slot}')
        if entry.get('name') in ingredient_set and type(qty) is int and qty > 0:
            allowed.add(entry['name'])
    for entry in poke.get('mythIng', []):
        qty = entry.get(f'c{slot}')
        if entry.get('name') in ingredient_set and type(qty) is int and qty > 0:
            allowed.add(entry['name'])
    return allowed


def safe_image_path(directory, raw):
    require(isinstance(raw, str) and raw.startswith('images/'), f'危険な画像パス: {raw!r}')
    path = (directory / raw).resolve()
    require(path.is_relative_to(directory.resolve()) and path.is_file(), f'画像が見つかりません: {raw}')
    return path


def image_integrity(directory, manifest):
    require(manifest.get('schemaVersion') == 'ai-input-manifest-v0.1', '画像manifestのスキーマが不正です')
    images = manifest.get('images')
    require(isinstance(images, list) and images, '画像一覧が空です')
    image_count = manifest.get('inputImageCount')
    selected_count = manifest.get('sourceSelectedCount')
    policy = manifest.get('duplicatePolicy')
    require(type(image_count) is int and image_count == len(images),
            f'画像manifestのinputImageCountが不一致: {image_count!r} vs {len(images)}')
    require(type(selected_count) is int and selected_count >= image_count,
            '画像manifestのsourceSelectedCountが不正です')
    require(policy in ('user-selected-keep-all', 'user-selected-remove-exact'),
            '画像manifestの重複処理が不明です')
    if policy == 'user-selected-keep-all':
        require(selected_count == image_count, '画像manifest: 重複を保持したのに選択件数が一致しません')
    else:
        require(selected_count > image_count, '画像manifest: 重複除外を指定したのに件数差がありません')
    seen_ids, seen_paths, seen_hashes = set(), set(), set()
    for item in images:
        image_id, rel = item.get('id'), item.get('path')
        require(image_id and image_id not in seen_ids, f'画像IDが重複/不正: {image_id!r}')
        require(rel not in seen_paths, f'画像パスが重複: {rel}')
        seen_ids.add(image_id)
        seen_paths.add(rel)
        require(isinstance(item.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', item['sha256']),
                f'画像SHA-256の書式不正: {image_id}')
        if policy == 'user-selected-remove-exact':
            require(item['sha256'] not in seen_hashes, f'重複除外指定なのに画像SHAが重複: {image_id}')
        seen_hashes.add(item['sha256'])
        path = safe_image_path(directory, rel)
        h = hashlib.sha256()
        with path.open('rb') as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b''):
                h.update(chunk)
        require(h.hexdigest() == item.get('sha256'), f'画像ハッシュが一致しません: {image_id}')
        require(path.stat().st_size == item.get('size'), f'画像サイズが一致しません: {image_id}')
        check_image_format(path)
    extras = {p.relative_to(directory).as_posix() for p in (directory / 'images').rglob('*') if p.is_file()} - seen_paths
    require(not extras, f'マニフェストに存在しない画像があります: {sorted(extras)[:3]}')
    return images


def is_int(value, lower, upper):
    return type(value) is int and lower <= value <= upper


def validate_included(row, pokemon_by_name, ingredient_set, natures, subskills, labels, master, schema):
    image_id = row['imageId']
    d = row.get('data')
    require(isinstance(d, dict), f'{image_id}: 読取データがありません')
    require(row.get('unresolved') == [], f'{image_id}: 未解決の確認項目があります')
    require(row.get('reviewComplete') is True, f'{image_id}: ユーザー確認完了フラグがありません')
    nickname, species = d.get('nickname'), d.get('species')
    require(isinstance(nickname, str) and nickname.strip(), f'{image_id}: ニックネーム未確定')
    require('\r' not in nickname and '\n' not in nickname,
            f'{image_id}: ニックネーム内の改行は実インポートで破損を確認。ユーザーに改行なしの名前を確認してください')
    require(not any(ord(c) < 32 or ord(c) == 127 for c in nickname),
            f'{image_id}: ニックネームに制御文字があります。勝手に置換せず確認してください')
    require(isinstance(species, str) and species in pokemon_by_name, f'{image_id}: 種族が未対応/不明: {species}')
    poke = pokemon_by_name[species]
    level, skill_level = d.get('level'), d.get('skillLevel')
    require(is_int(level, 1, 100), f'{image_id}: レベル未確定/範囲外')
    require(is_int(skill_level, 1, 10), f'{image_id}: スキルレベル未確定/範囲外')
    nature = d.get('nature')
    require(nature in natures, f'{image_id}: せいかく不明/未対応: {nature}')
    if species in TOXTRICITY_FORM_NATURES:
        require(nature in TOXTRICITY_FORM_NATURES[species],
                f'{image_id}: {species} とせいかく「{nature}」は実インポート往復で値が変化する恐れがあります。'
                '自動修正せず画像を再確認し、必要に応じてユーザーに確認してください')
    foods = d.get('foods')
    require(isinstance(foods, list) and len(foods) == 3, f'{image_id}: 食材3枠がそろっていません')
    # Applies to EVERY species, including mythical ones. A name appearing
    # somewhere in a species list does not make it legal at every food slot.
    possible = [food_candidates_for_slot(poke, slot, ingredient_set) for slot in (1, 2, 3)]
    empty_confirmed = d.get('emptyFoodsConfirmed', [])
    require(isinstance(empty_confirmed, list) and all(is_int(x, 2, 3) for x in empty_confirmed)
            and len(set(empty_confirmed)) == len(empty_confirmed),
            f'{image_id}: emptyFoodsConfirmedは食材2・3の重複のない位置配列のみ許可')
    # Cross-check the pinned schema rule with a code-side invariant to prevent a
    # mutable, self-reported compatibility label from silently authorizing blanks.
    require(schema.get('foodBlankAllowedBySpecies') == {'ミュウ': [3], 'ダークライ': [2, 3]},
            f'{image_id}: 食材空欄の正式種族別ルールが未検証です')
    allowed_blanks = FOOD_BLANK_ALLOWED.get(species, ())
    expected_food_blanks = [i + 1 for i, value in enumerate(foods) if value == '']
    require(empty_confirmed == expected_food_blanks,
            f'{image_id}: 空欄食材と確認済み位置の記録が一致しません')
    for i, value in enumerate(foods):
        require(isinstance(value, str), f'{image_id}: 食材{i+1}の型が不正')
        if value == '':
            require(i+1 in allowed_blanks and i+1 in empty_confirmed,
                    f'{image_id}: {species}の食材{i+1}はゲーム仕様上空欄を許可しません')
        else:
            require(value in ingredient_set and value in possible[i],
                    f'{image_id}: 食材{i+1}が種族/候補と不整合: {value}')
    raw_skill = d.get('mainSkill')
    require(isinstance(raw_skill, str) and raw_skill, f'{image_id}: メインスキル未確定')
    if species == 'ミュウ':
        require(raw_skill == 'オールマイティー', f'{image_id}: ミュウはオールマイティーが必要')
        key = d.get('versatileSkill')
        require(key in labels, f'{image_id}: ミュウの具体スキルが未確定')
        csv_skill = labels[key]
    else:
        require(raw_skill == poke.get('mainSkill'), f'{image_id}: 種族のメインスキル不一致: {raw_skill}')
        csv_skill = raw_skill
    skills = d.get('subskills')
    require(isinstance(skills, list) and len(skills) == 5, f'{image_id}: サブスキル5枠がそろっていません')
    empty_sub_confirmed = d.get('emptySubskillsConfirmed', [])
    require(isinstance(empty_sub_confirmed, list)
            and all(is_int(x, 1, 5) for x in empty_sub_confirmed)
            and len(set(empty_sub_confirmed)) == len(empty_sub_confirmed),
            f'{image_id}: emptySubskillsConfirmedは1〜5の重複のない位置配列のみ許可')
    expected_sub_blanks = [i+1 for i, value in enumerate(skills) if value == '']
    require(empty_sub_confirmed == expected_sub_blanks,
            f'{image_id}: サブスキル空欄の確認が未完了です')
    if expected_sub_blanks:
        require(poke.get('mythIng'), f'{image_id}: この種族ではサブスキル空欄を許可しません')
    for i, value in enumerate(skills):
        require(isinstance(value, str) and (value in subskills or (value == '' and i+1 in empty_sub_confirmed)),
                f'{image_id}: サブスキルLv{[10,25,50,70,80][i]}未対応/不明: {value}')
    non_empty_skills = [x for x in skills if x]
    require(len(set(non_empty_skills)) == len(non_empty_skills),
            f'{image_id}: サブスキルの重複（誤認識の疑い）')
    # "User policy" is distinct from a *verified semantic default*. The 0/0
    # values have one observed importer round-trip, but neither represents an
    # observation of the actual Pokemon. Never label these image-visible.
    policy = schema.get('optionalFieldPolicy')
    require(policy == {
        'noQuestions': ['sleepTogetherHours', 'shiny'],
        'whenUnobserved': {'sleepTogetherHours': 0, 'shiny': 0},
        'provenance': 'user-policy-default'
    }, f'{image_id}: 未確認項目の既定値ポリシーが想定と異なります')
    evidence = d.get('fieldEvidence', {})
    require(isinstance(evidence, dict), f'{image_id}: fieldEvidenceが不正です')
    verified_defaults = schema.get('verifiedSafeDefaults', {})
    optional = {}
    for field, values, description in (
        ('sleepTogetherHours', (0, 200, 500, 1000, 2000), '一緒に眠った時間'),
        ('shiny', (0, 1), '色違い'),
    ):
        fallback = policy['whenUnobserved'][field]
        has_explicit_value = field in d
        value = d[field] if has_explicit_value else fallback
        provenance = evidence.get(field, 'user-policy-default' if value == fallback else None)
        require(type(value) is int and value in values,
                f'{image_id}: {description}の値が未対応/不正: {value!r}')
        require(provenance in ('user-policy-default', 'image-visible',
                               'user-confirmed', 'verified-safe-default'),
                f'{image_id}: {description}の取得根拠が不正です')
        if provenance == 'user-policy-default':
            require(value == fallback,
                    f'{image_id}: {description}のユーザー方針による既定値は{fallback}のみ')
        elif provenance == 'verified-safe-default':
            require(field in verified_defaults and value == verified_defaults[field],
                    f'{image_id}: {description}に検証済みでない既定値を使用しています')
        else:
            require(has_explicit_value,
                    f'{image_id}: {description}を実際に観察/確認していません')
        optional[field] = value
    sleep, shiny = optional['sleepTogetherHours'], optional['shiny']
    return [nickname, species, level, skill_level, *foods, csv_skill, nature, *skills, sleep, shiny]


def build(records, manifest, master, schema, version, directory, prototype_test=False):
    for name, value in [('records', records), ('manifest', manifest), ('master', master),
                        ('schema', schema), ('version', version)]:
        require(isinstance(value, dict), f'{name}のJSONルートはオブジェクトである必要があります')
    require(isinstance(master.get('pokemon'), list)
            and isinstance(master.get('ingredients'), dict)
            and isinstance(master.get('natures'), list)
            and isinstance(master.get('subskills'), list), 'マスターの構造が不正です')
    require(prototype_test or (version.get('productionCsvAllowed') is True
                               and version.get('compatibilityVerified') is True
                               and version.get('masterVerifiedAgainstLive') is True
                               and bool(version.get('sourceCommit'))),
            '現在のマスターはpokesleep-tool実インポート互換性が未検証です。本番CSVの生成を停止しました。')
    require(schema.get('header') == list(EXPECTED_HEADER)
            and schema.get('encoding') == 'UTF-8 without BOM'
            and schema.get('lineEnding') == 'LF', 'CSV仕様・ヘッダーが検証済み定義と一致しません')
    # Version pins are independent of the parsed schema and master; a changed
    # payload is rejected rather than silently becoming a "new verified" source.
    pinned = version.get('assetSha256')
    require(isinstance(pinned, dict), 'マスター・CSV仕様のバージョン固定がありません')
    for label, payload in [('MASTER_DATA.json', master), ('CSV_SCHEMA.json', schema)]:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        actual = hashlib.sha256(canonical).hexdigest()
        require(actual == pinned.get(label), f'{label} が同梱版の固定ハッシュと一致しません')
    images = image_integrity(directory, manifest)
    require(manifest.get('kitVersion') == version.get('kitVersion'), '画像manifestのキット版が一致しません')
    require(records.get('schemaVersion') == 'ai-reading-v0.1', '認識データのスキーマが異なります')
    require(records.get('kitVersion') == version.get('kitVersion'), 'キットのバージョンが違います')
    decisions = records.get('decisions')
    require(isinstance(decisions, list), 'decisions配列がありません')
    by_id = {r.get('imageId'): r for r in decisions if isinstance(r, dict)}
    ids = {x['id'] for x in images}
    require(len(by_id) == len(decisions) == len(images) and set(by_id) == ids,
            f'画像件数と決定件数が不一致: 画像{len(images)}枚、決定{len(decisions)}件')
    pokemon = {x['name']: x for x in master['pokemon']}
    ingredients = set(master['ingredients'].values())
    natures = {x['ja'] for x in master['natures']}
    subskills = {x['ja'] for x in master['subskills']}
    rows = []
    excluded = []
    for item in images:
        row = by_id[item['id']]
        decision = row.get('decision')
        if decision == 'exclude':
            # An AI-authored boolean or claim is not evidence of human approval.
            # This record is only a *structural* check. The AI agent MUST obtain
            # a real user response in chat; Python cannot authenticate chat roles.
            approval = row.get('userConfirmation')
            require(isinstance(approval, dict)
                    and approval.get('imageId') == item['id']
                    and approval.get('action') == 'exclude'
                    and approval.get('source') == 'user-chat-message'
                    and isinstance(approval.get('verbatimUserReply'), str)
                    and len(approval['verbatimUserReply'].strip()) >= 4
                    and isinstance(approval.get('reason'), str)
                    and len(approval['reason'].strip()) >= 4
                    and approval['verbatimUserReply'].strip() != approval['reason'].strip(),
                    f"{item['id']}: 除外にはユーザーの実際の返答記録が必要です（AIの承認フラグ不可）")
            # Confirmation must be a deliberate, unambiguous response identifying
            # the exact affected image(s). Merely saying "approved" is insufficient.
            response = approval['verbatimUserReply'].strip()
            matched = re.fullmatch(r'除外承認[：:]\s*(IMG-\d{4}(?:\s*[,、]\s*IMG-\d{4})*)', response)
            require(matched is not None,
                    f"{item['id']}: 除外承認の回答は『除外承認: IMG-0001』の形式が必要です")
            approved_ids = set(re.findall(r'IMG-\d{4}', matched.group(1)))
            require(item['id'] in approved_ids and len(approved_ids) == len(re.findall(r'IMG-\d{4}',matched.group(1))),
                    f"{item['id']}: 除外承認の対象IDが不一致/重複しています")
            excluded.append(item['id'])
        elif decision == 'include':
            rows.append(validate_included(row, pokemon, ingredients, natures, subskills,
                                          schema['mewVersatileCsvLabels'], master, schema))
        else:
            raise ValidationError(f"{item['id']}: 処理が未確定です（{decision!r}）")
    require(rows, 'すべての画像が除外されました。空CSVを作りません')
    output = io.StringIO(newline='')
    writer = csv.writer(output, dialect='excel', lineterminator='\n')
    writer.writerow(schema['header'])
    writer.writerows(rows)
    text = output.getvalue()
    require(not text.startswith('\ufeff'), 'CSVシリアライズ異常: BOM')
    # CSV logical records (not physical newlines): quoted nicknames can include LF.
    try:
        parsed = list(csv.reader(io.StringIO(text, newline=''), dialect='excel', strict=True))
    except csv.Error as exc:
        raise ValidationError(f'CSVシリアライズ異常: {exc}') from exc
    require(len(parsed) == len(rows) + 1 and parsed[0] == list(EXPECTED_HEADER),
            'CSVシリアライズ異常: 行数またはヘッダーが一致しません')
    require(all(len(r) == 16 for r in parsed), 'CSVシリアライズ異常: 列数が一致しません')
    for idx, (encoded_row, source_row) in enumerate(zip(parsed[1:], rows), 1):
        require(encoded_row == [str(x) for x in source_row],
                f'CSVシリアライズ異常: {idx}行目の値が一致しません')
    return text.encode('utf-8'), {'images':len(images),'included':len(rows),
                                  'excluded':len(excluded),'excludedIds':excluded}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('--package-dir', default='.')
    cli.add_argument('--records', required=True)
    cli.add_argument('--prototype-test', action='store_true', help='for DEVELOPMENT TEST ONLY, not for general user')
    args = cli.parse_args()
    directory = pathlib.Path(args.package_dir).resolve()
    output_path = directory / 'pokesleep_import.csv'
    try:
        data, report = build(
            load_json(pathlib.Path(args.records)),
            load_json(directory / 'INPUT_MANIFEST.json'),
            load_json(directory / 'MASTER_DATA.json'),
            load_json(directory / 'CSV_SCHEMA.json'),
            load_json(directory / 'KIT_VERSION.json'),
            directory,
            prototype_test=args.prototype_test,
        )
        # Replace only after COMPLETE validation. On validation failure an old
        # CSV is preserved, but it must NEVER be represented as newly generated.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='wb', prefix='.pokesleep_csv_', suffix='.tmp',
                                             dir=directory, delete=False) as fh:
                temporary = pathlib.Path(fh.name)
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, output_path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        print(f"CSV生成: {report['included']}行、除外{report['excluded']}行、入力画像{report['images']}枚")
        if args.prototype_test:
            print('注意: プロトタイプ試験出力です。実際のpokesleep-tool互換性は未保証。')
        return 0
    except (ValidationError, ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as e:
        print(f'CSV作成を停止: {e}。既存のpokesleep_import.csvは今回生成されたものではありません', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
