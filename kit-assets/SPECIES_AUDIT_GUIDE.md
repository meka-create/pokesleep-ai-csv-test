# v0.12 種族候補の独立監査 — SpeciesAudit v0.4（開発専用 / HOLD）

## 最優先
- 従来の16列と `VALIDATOR.py` は変更しない。本番出力は `productionCsvAllowed=false` のまま。旧OCR Candidate系列へは書き戻さない。
- 確定したv0.8b進捗方式：**約1分**経過し、自然な処理の区切りがある場合に限り、グラフィカルな進捗ゲージを優先して途中メッセージを試みる。**非中断**を最優先し、強制分割・ユーザーへの「続き」要求・再読込・待機・時刻ポーリングを禁止する。途中メッセージを送れない環境では解析を優先する。詳細は `PROGRESS_PROTOCOL.md`。
- 一緒に眠った時間・色違いは、元画像で明確に分かれば実値。そうでなければCSV既定の各0。**CSV用0は観測値ではない**ためリボン計算に流用しない。
- 食材数量 / SP / おてつだい時間（秒） / 最大所持数は、通常の画像解析で確認できたときだけ補助JSONに記載。不明ならnull。推測で補完しない。

## 読取済みレコードの監査

`WORKING_RECORDS.json` は既存のAI読み取り結果形式（`RECORDS_TEMPLATE.json`）で、`decisions` にimageIdとdataを持つ。

省略可能な観察ファイルの形式は `SPECIES_OBSERVATIONS_TEMPLATE.json` を参照し、各imageIdについて追加情報のみ指定。`speciesVisualConfirmed` は元画像のポケモン像を独立に確認できた場合だけtrue。候補の単一性、マスター整合、前回CSV、数値上の一致だけでは true と記録しない。不明ならnull。

同梱のマスターを使い、次を実行（ファイルは実際の作業パスに置き換える）：

```
python3 SPECIES_AUDIT.py --package-dir . --records WORKING_RECORDS.json --observations SPECIES_OBSERVATIONS.json --output SPECIES_REVIEW_RESULT.json
```

補助数値を読めなかった場合は `--observations` を省略して監査できる。CLIが使えなければ未実施と報告して安全側に留める。

## 判断の優先順位

1. 食材3枠の種類、**画像で確認できた数量のみ**、メインスキルから249種マスターの候補を列挙。
2. 報告した種族が候補になければ `SPECIES_CONFLICT_HOLD`。解決するまで従来のCSV検証を進めない。
3. 複数種が成立する場合、SP / おてつだい時間 / 最大所持数の補助数値を記録して参照する。ゲーム仕様と旧マスターの推定差があるため、**数値だけで候補を消さず、自動確定もしない**。
4. 数値が1種だけ一致していても、他の候補を除外できた証明ではない。必要に応じ元画像のアイコン、種族固有特徴を確認する。解決できなければユーザーへ確認してHOLD。
5. おてつだい時間の±1秒許容は補助計算であり、SPは厳密照合に使用しない。最大所持数は現行仕様で入手経路そのものに依存せず、種族段階とリボン・解放済みサブスキルに依存する。将来マスター変更時は安全のため監査を停止する。
6. `SPECIES_AUDIT.py` はCSVを**一切出力・修正しない**。正常終了後も本番CSVを許可しない。データの競合・不足はAIが画像と照合し解決する。

## 安全上の限界

本監査は画像の読取正解を直接保証しない。ChatGPTが誤って読んだ複数項目はマスター整合だけでは発見できないことがある。`SPECIES_REVIEW_RESULT.json` は開発監査データであり、最終的な一般ユーザー納品物ではない。20枚および10枚の既知画像とオフライン数値試験は独立した新規画像の正解率を示さない。進捗表示の採用は確定済みで、進捗なし方式への速度比較は行わない。


## v0.8の統合安全装置

種族監査はこれまでどおり単独の読み取り専用処理です。ただし開発用CSVの納品は必ず `PROTOTYPE_EXPORT_GATE.py --prototype-test --records WORKING_RECORDS.json --package-dir . --output-dir ./dev-output` を経由します。必要に応じて `--observations SPECIES_OBSERVATIONS.json` を追加します。矛盾・種族の未解決確認があればHOLDします。出力にはCSVの行と画像IDを結び付ける `DEVELOPMENT_ONLY_ROW_BINDING.json` を添付します。`VALIDATOR.py` とマスター/16列スキーマを変更せず、数値からの種族自動確定もしません。
