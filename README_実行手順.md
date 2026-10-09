# v0.11 → pokesleep-tool最新HEAD マスター独立差分監査

**試作版限定／自動公開なし／本番CSV禁止のまま。** この監査はCSVの実インポートを試験しません。GitHub Actionsの実行時点の上流 `main` を固定コミットとして取得し、v0.11の静的マスターとの差分を記録します。

## GitHubに追加する3ファイル

既存リポジトリ `meka-create/pokesleep-ai-csv-test` の `main` へ、次の構造を**変えずに**追加します。

```
.github/workflows/master-audit-v011.yml
audit/master_diff.py
audit/MASTER_v011_BASELINE.json
```

`audit/test_master_diff.py` はローカル用の単体テストで、GitHubへ追加しなくても動きます。

**既存の `.github/workflows/real-import-probe.yml`、`probe/`、`index.html`、`kit-assets/` は変更しません。** GitHubでは `.github` が見えない場合、`Add file → Create new file` から完全なファイルパス `.github/workflows/master-audit-v011.yml` を入力して内容を貼り付けます。`audit/` の2ファイルもアップロードします。

## 実行

1. `https://github.com/meka-create/pokesleep-ai-csv-test/actions`
2. 左の **Compare pokesleep-tool current master to v0.11 (NO DEPLOY)** を選択。
3. **Run workflow** → `main` → **Run workflow**。
4. その実行履歴の下部の **Artifacts** → `pokesleep-master-audit-NOT-PRODUCTION` をダウンロード。
5. ダウンロードしたZIPをChatGPTへ添付。

## 証拠ZIPの中身

- `MASTER_AUDIT.json`: 上流コミット、4つのソースファイルSHA-256、現行／上流種族数、追加／削除種族、全フィールド／翻訳差分。
- `SUMMARY.md`: 結果と概要。
- `CHANGED_FIELDS.csv`: 差分を表形式で確認するためのCSV。

`SOURCE_PROJECTION_MATCH_HOLD` は上流データの**構造上の一致**であり、インポータの受理／実デプロイとの一致を示しません。`DIFFERENCES_FOUND_HOLD` は差分が存在する状態、`AUDIT_ERROR_HOLD` は監査自体に失敗した状態です。**いずれの場合も本番CSV出力の停止を維持します。**

## 技術・安全上の注意

- ソース4ファイル（`src/data/pokemon.json`、日本語翻訳3ファイル）の比較に限定。
- git cloneで得た最新コミットを必ず結果に記録。ただし、GitHub Pagesで稼働する実デプロイのコミットとは同一と断言しません。
- GitHub Actions権限は `contents: read` のみ。`npm install` / `npm test` / 上流コード実行／master自動更新は行いません。上流JSONをデータとして読み取るだけです。
- 静的マスターのSHA-256は `d60410ba1f92d80c67ca3ff40bc8aa7a2cd51d4c03fc33f9e99fa83bb8e77a38` に固定されています。途中で改変されればFAIL/HOLDにします。
- 249種のCSV実取込・エクスポート照合は、別途、手動互換性試験を行います。
