# exhibition-radar 開発ルール（Claude Code向け）

日本国内のIT・無線関連展示会情報を公開Webから収集し、GitHub Pages（docs/）で一覧・CSV配布するツール。
**リポジトリは公開**。社内情報を一切含めないこと。

## 実装ルール
- Python 3.12、型ヒント必須、`ruff check` / `ruff format` で整形
- 設定値をコードに直書きしない（`config/` 配下から読む。`collector/settings.py` 経由）
- ネットワークアクセスは `collector/fetcher.py` に集約する
- テストで外部通信を行わない（`tests/fixtures/` の保存済みHTMLを使う。Geminiはモック）
- 1収集元の失敗で処理全体を止めない
- フロントエンドはビルド不要の静的ファイルのみ（`docs/`、外部ライブラリ原則不使用）
- APIキー・社内情報（アサイン列・社内メモ）・`.xlsx`・既存リストの元ファイルをコミットしない
- 日付を推測で補完しない（年省略の日付は、同じページに年が明記されている場合のみ解釈）

## データの約束
- 正本は `docs/data/events.json`（excluded も保持して再検出を防ぐ。Web・CSVには出さない）
- CSV列構成は `collector/exporter.py` と `docs/assets/csv.js` の両方で同じにする
- イベントIDは `parent + sub + 開催年` のハッシュ。同名同年で別会場の回と衝突した場合のみ会場を加える（`models.edition_id`）
- 人手補正 `data/overrides.yaml` は毎回最優先で適用する

## よく使うコマンド
```bash
python -m pytest -q
ruff check collector tests && ruff format collector tests
python -m collector.main                 # 収集（Phase 2以降）
python -m http.server 8765 -d docs       # 画面確認
```
