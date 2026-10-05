# 展示会レーダー（exhibition-radar）

日本国内で開催されるIT・無線関連（5G／6G／ローカル5G／Wi-Fi／LPWA／NTN／AI／DX／IoT／セキュリティ／ロボット／ドローン／スマートシティ等）の展示会情報を、公開Web情報から自動収集し、GitHub Pages で一覧表示・CSVダウンロードできるようにするツールです。

- 一覧：キーワード・期間・地域・会場・カテゴリ・ステータスで絞り込み、総合展ごとのまとめ表示、列ソート、詳細パネル
- CSV：表示中（詳細列付き）／Excel転記用（既存Excelの列構成）／今回新規・更新のみ。すべて UTF-8 BOM付き・CRLF
- データ：`docs/data/events.json`（正本）、`events.csv`、`events_detail.csv`、`runs.json`

> 公開情報を自動で収集したものです。正確な情報は各公式サイトで確認してください。

---

## 1. ローカルでの準備（Windows）

```powershell
cd exhibition-radar
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pytest -q
```

## 2. 既存リストからの初期データ取込（初回のみ）

既存の「展示会イベントリスト」（.xlsx または .csv）は**リポジトリの外に置いたまま**実行します（リポジトリ内のファイルは拒否します）。

```powershell
$env:PYTHONUTF8=1
.\.venv\Scripts\python -m collector.import_excel "C:\Users\...\展示会イベントリスト.xlsx" --dry-run   # 集計だけ確認
.\.venv\Scripts\python -m collector.import_excel "C:\Users\...\展示会イベントリスト.xlsx"
```

- 取り込む列：イベント名、開始日、終了日、会場、対応カテゴリ、概要、URL
- **取り込まない列：No、SA部アサイン、コムシスアサイン**（その他の列も読みません）
- 取り込んだイベントは「変更なし」になります（「今回新規・更新のみ」CSV に入らないようにするため）
- 次のものは「要確認」になります：開催年が分からないもの、URL列にリンク文字列しか入っていないもの
  - .csv で保存するとハイパーリンクのURLが失われます。**.xlsx から取り込むとリンク先のURLを読めます**
- 終了日から30日以上たったイベントは `data/archive/{年}.json` に移します（Webには表示しません）
- 既存リストのURLは `config/known_urls.yaml` に書き出し、収集処理で巡回します

## 3. 画面の確認（ローカル）

```powershell
.\.venv\Scripts\python -m http.server 8765 -d docs
```

ブラウザで http://localhost:8765/ を開きます。`index.html` をダブルクリックで開くとデータを読み込めないため、必ず簡易サーバを使ってください。
社内ルール上 GitHub Pages で公開できない場合も、この方法で同じ画面を使えます。

### フロントエンド手動確認チェックリスト
- [ ] 画面上部に最終更新日時、掲載件数・新規・更新・要確認・収集エラーの件数が出る
- [ ] キーワード検索（スペース区切りでAND検索）で絞り込める
- [ ] 期間プリセット（今月／来月／3か月以内／5か月以内／すべて）と From/To が効く
- [ ] 「日程未定を含める」をオフにすると、日程未定のイベントが消える
- [ ] 地域のチェック、カテゴリ・会場・ステータスの複数選択で絞り込める
- [ ] 「総合展でまとめる」で構成展が折りたたまれ、クリックで開閉できる
- [ ] 列見出しをクリックすると昇順・降順が切り替わる
- [ ] 行をクリックすると詳細（概要・判定理由・収集元・信頼度・更新履歴・公式URL）が出る
- [ ] イベント名のリンクで、公式ページが別タブで開く
- [ ] 絞り込み条件がURLに反映され、そのURLを開き直すと同じ表示になる
- [ ] CSV 3種類がダウンロードでき、Excelで開いても文字化けしない。Excel転記用CSVはアサイン列が空欄になっている
- [ ] スマホ幅でも横スクロールなしで操作できる

---

## 4. GitHub への公開手順

> 公開の前に、業務で外部Webサービス（GitHub）にサイトを公開してよいか、社内ルールを確認してください（設計書14章）。

### 4.1 用意するもの

| 用意するもの | 入手先 | 置き場所 |
|---|---|---|
| GitHubアカウント | https://github.com/ | — |
| 公開リポジトリ `exhibition-radar` | GitHubの「New repository」で作成（Public） | — |
| Gemini APIキー | Google AI Studio の「Get API key」 | GitHub の **Secrets** → `GEMINI_API_KEY` |
| Geminiのモデル名 | Google AI Studio で、無料枠で使えるモデル名を確認 | GitHub の **Variables** → `GEMINI_MODEL` |
| GitHubのユーザー名 | — | `config/settings.yaml` の `fetch.user_agent` にある `<GitHubユーザー名>` を置き換える |

**APIキーはファイル・チャット・コミットに絶対に書かないでください。** GitHub の Secrets だけに保存します。

### 4.2 手順

1. `config/settings.yaml` の `<GitHubユーザー名>` を自分のユーザー名に置き換えてコミットする
2. GitHub で空の公開リポジトリ `exhibition-radar` を作成し、push する
   ```powershell
   git remote add origin https://github.com/<GitHubユーザー名>/exhibition-radar.git
   git push -u origin main
   ```
3. Secrets を登録：リポジトリの **Settings → Secrets and variables → Actions → Secrets タブ → New repository secret**
   - Name：`GEMINI_API_KEY`／Secret：AI Studio で発行したキー
4. Variables を登録：同じ画面の **Variables タブ → New repository variable**
   - Name：`GEMINI_MODEL`／Value：AI Studio で確認したモデル名
5. Actions の書き込み権限：**Settings → Actions → General → Workflow permissions** で「Read and write permissions」を選ぶ（収集結果を自動でコミットするため）
6. Pages：**Settings → Pages → Build and deployment** で Source を「Deploy from a branch」、Branch を `main` と `/docs` にする
7. 数分後に `https://<GitHubユーザー名>.github.io/exhibition-radar/` で表示されることを確認する
8. **Actions タブ → collect → Run workflow** で手動実行し、データが更新されることを確認する

### 4.3 ローカルで Gemini を試す場合（任意）

キーはご自身のターミナルで、そのセッションの間だけ環境変数として設定します（ファイルには保存しません）。

```powershell
$env:GEMINI_API_KEY = "（AI Studioで発行したキー）"
$env:GEMINI_MODEL = "（モデル名）"
.\.venv\Scripts\python -m collector.main
```

---

## 5. 運用

- 自動：毎週月曜と毎月25日の 05:00（JST）に GitHub Actions が収集し、サイトを更新します
- 誤検出・重複・修正は `data/overrides.yaml` を GitHub 上で直接編集します（書き方はファイル内のコメントを参照）。イベントIDは詳細パネルか詳細CSVで確認できます
- 本番Excelへの反映：「今回新規・更新のみ」または「Excel転記用CSV」をダウンロード → 貼り付け → Noの採番とアサインの記入 → SharePoint へアップロード

## 6. 構成

```
collector/   収集処理（Python）
config/      設定（収集元・キーワード・カテゴリ・会場辞書・既知URL）
data/        人手補正（overrides.yaml）、アーカイブ、キャッシュ（Git管理外）
docs/        GitHub Pages 公開ディレクトリ（静的HTML＋JS）
tests/       pytest（外部通信なし）
```

## 7. 設計書からの補足・判断事項

- **イベントIDの衝突回避**：設計書のID（総合展名＋構成展名＋開催年）では、同じ年に東京と大阪で開かれる同名の展示会が同じIDになります。そのため、衝突したときだけ会場名を加えた別IDにしています
- Event に `year`（開催年）フィールドを追加しました（IDの再計算と日程未定イベントの管理に使います）
- `excluded` のイベントは events.json に残して再検出を防ぎ、画面とCSVからは除外しています
- `confirm` を適用したイベントは「変更なし」になり、履歴に「確認済み」と残ります
- カテゴリは `config/categories.yaml` の別名辞書で8つの固定カテゴリに割り当て、どれにも当たらないものは「その他IT」にしています
