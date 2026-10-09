# Pokémon Sleep AI→pokesleep-tool CSV変換キット（試作版v0.5）

このZIPには画像、共通読取規則、マスター、CSV仕様、検証・変換プログラムが含まれます。
最初に `AI_INSTRUCTIONS.md` を読み、全画像の処理を開始してください。

**重要：このキットは開発中（PROTOTYPE ONLY）です。**
`KIT_VERSION.json` の `productionCsvAllowed` が `false` の間、通常モードでの本番CSV出力は禁止されています。
利用者に未検証のCSVを「pokesleep-tool互換」と表示しないでください。

利用者に提供するダウンロード成果物は、互換性が検証された時点で生成する `pokesleep_import.csv` の1ファイルのみです。
中間JSONや解析報告ファイルは、利用者への提出物にしません。
