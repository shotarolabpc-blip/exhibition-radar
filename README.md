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
| GitHubのユーザー名 | STEP 1で決める | `config/settings.yaml` の `fetch.user_agent` にある `<GitHubユーザー名>` を置き換える（push前） |

**APIキーはファイル・チャット・コミットに絶対に書かないでください。** GitHub の Secrets だけに保存します。

### 4.2 手順（画面操作）

#### STEP 1　GitHubアカウントを作る（初回のみ）
1. https://github.com/signup を開き、メールアドレス・パスワード・ユーザー名を入力して登録する
2. 届いたメールの確認コードを入力する
3. ユーザー名は公開URLになる（`https://ユーザー名.github.io/exhibition-radar/`）

#### STEP 2　Gemini APIキーを取る
1. https://aistudio.google.com/ を開き、Googleアカウントでログインする（初回は利用規約に同意）
2. 画面の「Get API key」→「APIキーを作成」を押す
3. 表示されたキーを**コピーするだけ**にする（メモ帳・メール・チャットに貼らない。STEP 5で直接GitHubに貼る）
4. 同じAI Studioのモデル一覧で、無料枠で使えるモデル名（`gemini-` で始まる英数字の名前）を確認しておく

#### STEP 3　空のリポジトリを作る
1. GitHubにログインし、右上の「＋」→「New repository」
2. Repository name：`exhibition-radar`
3. 「Public」を選ぶ
4. 「Add a README file」などのチェックは**すべて外したまま**「Create repository」

#### STEP 4　手元のファイルをアップロード（push）する
```powershell
cd exhibition-radar
git remote add origin https://github.com/<ユーザー名>/exhibition-radar.git
git push -u origin main
```
初回はブラウザが開いて GitHub へのサインインを求められるので、「Sign in with your browser」→「Authorize」を押す（Git for Windows に同梱の Git Credential Manager が認証情報を保存する）。

#### STEP 5　APIキーとモデル名を登録する
1. GitHubのリポジトリ画面上部の「Settings」タブ
2. 左メニュー「Secrets and variables」→「Actions」
3. 「Secrets」タブ →「New repository secret」
   - Name：`GEMINI_API_KEY`
   - Secret：STEP 2でコピーしたキーを貼り付け →「Add secret」
4. 「Variables」タブ →「New repository variable」
   - Name：`GEMINI_MODEL`
   - Value：STEP 2で確認したモデル名 →「Add variable」

登録後は、キーの値は誰にも（自分にも）表示されない。

#### STEP 6　自動コミットを許可する
「Settings」→ 左メニュー「Actions」→「General」→ 一番下の「Workflow permissions」で「Read and write permissions」を選んで「Save」

#### STEP 7　Webサイトとして公開する
1. 「Settings」→ 左メニュー「Pages」
2. Source：「Deploy from a branch」
3. Branch：`main`、フォルダ：`/docs` を選んで「Save」
4. 1〜3分後、同じ画面の上部に公開URLが表示される

#### STEP 8　動作確認
1. 公開URLを開き、一覧が表示されることを確認する
2. 「Actions」タブ → 左の「collect」→「Run workflow」で手動実行し、終わったらサイトのデータが更新されていることを確認する

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

## 6. 収集処理

```powershell
$env:PYTHONUTF8=1
.\.venv\Scripts\python -m collector.main --dry-run --no-gemini --sources bigsight,makuhari   # 書き込まずに試す
.\.venv\Scripts\python -m collector.main                                                     # 本実行
```

| オプション | 内容 |
|---|---|
| `--dry-run` | ファイルを書き込まない |
| `--sources a,b` | 指定した収集元だけ実行 |
| `--no-gemini` | Geminiを使わない（構造化サイトのHTML抽出のみ） |
| `--today YYYY-MM-DD` | 基準日を指定（テスト用） |

### 6.1 収集元の状況（2026-10-05 確認）

| 収集元 | 方式 | 状態 | 備考 |
|---|---|---|---|
| 東京ビッグサイト | 専用パーサー（HTML） | ✅ 有効 | `/visitor/event/search.php?page=N`。名称・会期・公式URL・説明を直接抽出 |
| 幕張メッセ | 専用パーサー（HTML） | ✅ 有効 | `/event/?month=YYYYMM&page=N`。「展示会・見本市」のみ。公式URLは詳細ページから取得 |
| ポートメッセなごや | 汎用（本文→Gemini） | ✅ 有効 | `https://portmesse.com/events` |
| 有明GYM-EX | 専用パーサー（ビッグサイトと同じ構造） | ✅ 有効 | `/organizer/buildings/gym-ex/event/` |
| 東京国際フォーラム／産業貿易センター浜松町館／Aichi Sky Expo／京都パルスプラザ／神戸国際展示場／ATCホール／札幌コンベンションセンター／夢メッセみやぎ／仙台国際センター／朱鷺メッセ／石川県産業展示館／広島県立広島産業会館／沖縄コンベンションセンター／ツインメッセ静岡 | 汎用（本文→Gemini） | ✅ 有効 | URLは `config/sources.yaml` |
| Interop Tokyo | 汎用主催者（本文→Gemini） | ✅ 有効 | |
| 既知イベントURL | 巡回（本文→Gemini） | ✅ 有効 | `config/known_urls.yaml`。1回200件まで、本文が変化したページだけGeminiへ |
| J-messe | — | ⛔ 無効 | 検索フォームの送信先 `/j-messe/tradefair/search.html` が404。検索結果を取得できない |
| パシフィコ横浜 | — | ⛔ 無効 | 設計書のURL `/visitor/calendar` は404。サイトがSTUDIO製になり、イベント一覧はJavaScriptで描画される |
| インテックス大阪 | — | ⛔ 無効 | `/jp/event/` はカレンダーの枠だけで、イベント部分がJavaScript描画 |
| マリンメッセ福岡 | — | ⛔ 無効 | `/messe/event/` のイベント部分がJavaScript描画 |
| みやこめっせ／福岡国際センター／アクセスサッポロ／グランメッセ熊本 | — | 見送り | イベント部分がJavaScript描画 |
| マイドームおおさか／吹上ホール／西日本総合展示場 | — | 見送り | 一覧の掲載が1件程度で、網羅性が低い |

無効の収集元の開催分は、既知URL巡回（既存リストの公式URL）と、主催者HPで補います。
JavaScript描画のサイトは Playwright で対応できますが、Actionsの実行時間とインストール負荷が増えるため、導入するかは別途判断してください（設計書2.2）。

### 6.2 Gemini の使い方
- 構造化サイト（ビッグサイト・幕張）：キーワード判定を通過したイベントを15件ずつまとめて送り、関連性・カテゴリ・概要だけを付与する
- 汎用サイト・既知URL：ページ本文を送って全項目を抽出する（会場カレンダーはキーワード判定を省略）
- 1回の実行の上限（`gemini.max_requests_per_run`）に達した、またはレート制限が続いた場合、残りのページは処理せず、次回の実行に持ち越す（`runs.json` の `gemini_pending` に件数を記録）

## 7. 構成

```
collector/   収集処理（Python）
config/      設定（収集元・キーワード・カテゴリ・会場辞書・既知URL）
data/        人手補正（overrides.yaml）、アーカイブ、キャッシュ（Git管理外）
docs/        GitHub Pages 公開ディレクトリ（静的HTML＋JS）
tests/       pytest（外部通信なし）
```

## 8. 設計書からの補足・判断事項

- **イベントIDの衝突回避**：設計書のID（総合展名＋構成展名＋開催年）では、同じ年に東京と大阪で開かれる同名の展示会が同じIDになります。そのため、衝突したときだけ会場名を加えた別IDにしています
- Event に `year`（開催年）フィールドを追加しました（IDの再計算と日程未定イベントの管理に使います）
- `excluded` のイベントは events.json に残して再検出を防ぎ、画面とCSVからは除外しています
- `confirm` を適用したイベントは「変更なし」になり、履歴に「確認済み」と残ります
- カテゴリは `config/categories.yaml` の別名辞書で8つの固定カテゴリに割り当て、どれにも当たらないものは「その他IT」にしています
- **重複判定（collector/dedup.py）**
  - 名称の類似度が90以上で、開始日と会場も一致する場合は「同じイベント」として扱います（設計書では「重複疑い→要確認」）。会場HPと主催者HPで同じ回を拾うたびに要確認になるのを避けるためです。開始日が違う・未定の場合は、設計書どおり要確認です
  - 類似度75〜89でも、両方に公式URLがあってURLが別なら、別のイベント（同じシリーズの別の構成展）として扱います
  - URLの一致判定は「同じホスト＋同じファイル名」で行います（主催者サイトは同じページを複数のパスで公開しているため）
- **更新判定**：概要は、既存が空のときだけ埋めます（Geminiの要約は実行ごとに表現が変わり、毎回「更新」になってしまうため）。URLは、既存が空のときか、主催者公式ページから取れたときだけ差し替えます
- **Geminiの上限到達時**：設計書では「残りを要確認で保持」ですが、日付も名称もまだ分からないページを要確認として載せても意味がないため、次回の実行に持ち越します
