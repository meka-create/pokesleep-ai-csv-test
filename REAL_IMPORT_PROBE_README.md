# v0.6 — 実CSVインポータ検証のためのGitHub Actionsパック

この版は v0.5 の画面・キット・マスター・本番停止ガードを**変更しません**。
公開中のpokesleep-toolをGitHub Actionsのブラウザから開き、専用の開発用CSVを実インポートし、可能ならCSVを再エクスポートして16セル＋ヘッダーをすべて比較します。

**注意**: 現時点ではブラウザ実操作の成功は未確認です。画面構造によっては`HOLD`になります。その場合は`PROBE_RESULT.json`とスクリーンショットに基づいて対象インポータの位置を特定してから改修します。UI操作で往復一致しても、現行公開サイトと同じgitコミットとの一致が証明されたわけではなく、本番CSVの解禁条件はすべて満たされません。

## テストリポジトリへの追加（GitHub Pages本体は変更なし）

GitHubの `meka-create/pokesleep-ai-csv-test` のルートに、次の**2ファイル**をディレクトリごと追加します。

- `.github/workflows/real-import-probe.yml`
- `probe/run_import_probe.py`

GitHub → **Actions** → **Probe real pokesleep-tool CSV import (NO RELEASE)** → **Run workflow** → `main` を実行してください。
終了後、ワークフロー画面の **Artifacts → importer-probe-evidence-NOT-PRODUCTION** をダウンロードして、結果ZIPをこの会話へ添付してください。

このワークフローは明示実行専用です。公開サイトに何も書き込まず、上流サイトへのインポートも隔離された一時ブラウザ内だけで試みます。

## パスに関する注意

GitHubのブラウザでフォルダアップロードが難しければ、2ファイルは **Add file → Create new file** からパスごと作成できます。既存の`index.html`や`kit-assets/`は変更しません。

## 判定の意味

- `UI_IMPORT_EXPORT_MATCH` : ブラウザで入力CSVと再エクスポートCSVがヘッダー・全セル一致。ただし手動レビュー前の暫定証拠。
- `HOLD` : UI操作失敗、再エクスポート未確認、またはセル不一致。**互換性PASSではありません**。
- いずれの場合も`productionCsvAllowed=false`は維持します。

テストCSVには架空のニックネーム「CSV接続テスト」の1行だけを使用し、ユーザー画像・個人情報は含みません。
