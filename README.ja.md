# <p align="center"><img src="assets/icons/tray_icon.png" alt="ENE アイコン" width="96" /></p>

<h1 align="center">ENE</h1>

<p align="center">
  Live2D の存在感を持つ、長期記憶対応の AI デスクトップコンパニオン。
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.ko.md">한국어</a> |
  <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" />
  <img alt="PyQt6" src="https://img.shields.io/badge/PyQt6-Desktop-41CD52?logo=qt&logoColor=white" />
  <img alt="Live2D" src="https://img.shields.io/badge/Live2D-Overlay-FF6B81" />
  <img alt="Coverage" src="https://img.shields.io/badge/coverage%20gate-80%25-1f883d" />
  <img alt="Status" src="https://img.shields.io/badge/status-active%20development-1f883d" />
</p>

ENE は作業環境の上に常駐するデスクトップ AI パートナーです。Live2D オーバーレイ、長期記憶、個人化プロンプト、音声出力、ノート、目標、約束、気分状態、能動的な文脈を 1 つのコンパニオン型デスクトップアプリにまとめています。

単なるチャットウィンドウではありません。ENE はデスクトップ上の存在感、記憶、表情と動き、必要に応じた音声出力、ノートやリマインダーなどの日常的な流れを中心に設計されています。

> [!NOTE]
> ENE は活発に開発中の個人プロジェクトです。利用できる状態ではありますが、多くの環境やプロバイダー構成で十分に安定検証されたリリースではありません。

> [!IMPORTANT]
> メモリ用の embedding ワークフローは、現時点では Voyage との組み合わせが最も安定してテストされています。他のプロバイダーは今後改善される可能性があります。

> [!TIP]
> 実用的な基本構成としては、メイン LLM に `Google Gemini`、TTS に `GPT-SoVITS HTTP` をおすすめします。

## プレビュー

| デスクトップコンパニオン | チャットとコントロール |
| :---: | :---: |
| ![ENE デスクトッププレビュー](docs/screenshots/ene-desktop-preview.png) | ![ENE デスクトッププレビュー 2](docs/screenshots/ene-desktop-preview-2.png) |

## 主な機能

- トレイ常駐型のデスクトップアプリとして Live2D コンパニオンオーバーレイを表示します。
- 性格、プロンプト、メモリ、プロフィール、気分の文脈を使ってチャットします。
- 画像や文書の添付を会話に含められます。
- 要約、事実、メタデータ、検索文脈を含む長期記憶を保存します。
- ユーザープロフィールと ENE プロフィールを維持し、会話を少しずつ個人化します。
- 複数軸の気分状態を追跡し、口調、表情ガイド、UI フィードバックに反映します。
- ENE の短期目標と長期目標を管理します。
- 会話内の約束を記憶し、指定された時点で自然なフォローアップとして呼び戻します。
- `/diary` で日記形式の内容を保存します。
- `/note` でノート作成の計画と実行フローを使えます。
- Obsidian CLI 連携を有効にすると、選択したファイル文脈をプロンプトに含め、制御されたノート操作を実行できます。
- カレンダー風のイベントや会話アクティビティ信号を抽出します。
- TTS、ブラウザー音声、ストリーミング TTS、PTT 割り込み、モデル対応リップシンクをサポートします。
- 長い離席状態を検知し、必要に応じて先に話しかけることができます。
- 設定画面からモデル、プロンプト、プロフィール、TTS、テーマ、ホットキー、メモリ、Obsidian、目標、動作を調整できます。

## 現在の状態

ENE は実用的なローカル開発フローを持つアクティブな開発プロジェクトです。

- 同梱のデフォルト Live2D モデルは `hiyori` です。
- ユーザーが選択したモデルパスは再起動後も保持されます。
- Live2D モードに加えて画像アバターモードも利用でき、感情ごとの画像切り替えや画像ごとの配置調整が可能です。
- `ene_goals.json` によって ENE の目標状態を保持でき、短期・長期の目標文脈をコンパニオンの振る舞いに反映できます。
- LLM プロバイダー生成は、プロバイダー別モジュールと互換 facade に分離されています。
- アプリ起動責務は LLM、メモリ、TTS、プロフィールの bootstrap モジュールに分かれています。
- 大きな bridge の責務は、信頼性向上のためにより小さな bridge mixin と service 境界へ段階的に分割されています。
- CI は Linux と Windows で Python 3.11 を使って実行されます。
- 選別対象の coverage gate は現在 `80%` です。

初回セットアップ、パッケージリリース、設定の import/export、公開ドキュメントは引き続き改善中です。

## 対応言語

アプリ UI の locale は次の言語を含みます。

- English
- Korean
- Japanese

プロンプト言語、実際の応答言語、TTS 言語は、選択したプロバイダー、プロンプト設定、モデルの挙動によって変わることがあります。

## クイックスタート

### 1. 仮想環境を作成

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2. ENE を起動

```powershell
python main.py
```

ENE は PyQt デスクトップアプリとして起動し、トレイアイコンを使います。設定画面はトレイアイコンを右クリックして開けます。

### 3. プロバイダーとキーを設定

ENE はユーザーが編集できるランタイムファイルをユーザーデータフォルダーに保存します。

- Windows: `%AppData%/ENE`

主なファイル:

- `config.json` - ランタイム設定と機能トグル
- `api_keys.json` - プロバイダーキーと秘密情報
- `memory.json` - 長期記憶ストレージ
- `user_profile.json` - ユーザープロフィールの事実
- `ene_goals.json` - ENE の目標状態
- `calendar.json`, `mood_state.json`, `obs_config.json` - 補助状態
- `prompts/*.md` - 編集可能なプロンプトファイル

> [!WARNING]
> 実際の秘密情報は `api_keys.json` に保存してください。個人 API キー、非公開モデル素材、メモリファイル、プロフィールファイルをコミットしないでください。

## 初回セットアップのおすすめ

1. `python main.py` で ENE を起動します。
2. トレイアイコンから設定画面を開きます。
3. LLM プロバイダー、モデル、API キーを設定します。
4. 同梱の `hiyori` モデルを使うか、任意の `.model3.json` ファイルを選びます。
5. 選択した Live2D モデルの表情名を確認します。
6. ユーザープロフィールと ENE プロフィールを入力します。
7. 安定したメモリを使いたい場合は Voyage embedding を設定します。
8. テキストチャットが動作してから TTS を有効化して調整します。
9. ローカルノート作業が必要な場合のみ Obsidian CLI 連携を有効化します。

## 推奨プロバイダー構成

ENE に合うシンプルな開始構成として、次の組み合わせをおすすめします。

- `LLM プロバイダー`: `Google Gemini API`
- `TTS プロバイダー`: `GPT-SoVITS HTTP`
- `Embedding プロバイダー`: `Voyage`

この組み合わせはセットアップの負担を比較的抑えつつ、一般的な会話品質、メモリの安定性、キャラクターらしい音声フローを両立しやすい構成です。

LLM 側では、設定画面で `Google Gemini API` を選び、Gemini API キーを入力し、特に理由がなければまずはデフォルトの Gemini モデルから始めるのがおすすめです。

TTS 側では、ENE 内で音声出力を試す前に GPT-SoVITS サーバーが先に起動していることを確認してください。

## GPT-SoVITS クイックセットアップ

GPT-SoVITS は ENE と相性の良い TTS 経路です。一般的なデフォルト TTS よりもキャラクターらしい雰囲気を作りやすく、ENE を単なるアシスタントではなくコンパニオンらしく感じさせやすくなります。

ENE に GPT-SoVITS で話させたい場合は、次の手順で設定できます。

1. 先に GPT-SoVITS HTTP サーバーを起動します。
2. ENE を開き、トレイアイコンから設定画面を開きます。
3. TTS セクションでプロバイダーを `GPT-SoVITS HTTP` に設定します。
4. `API URL` にサーバーアドレスを入力します。
5. `Reference Audio Path` に有効な参照音声ファイルのパスを設定します。
6. `Reference Text` にその参照音声に対応するテキストを入力します。
7. 参照言語と対象言語の値を確認してから設定を保存します。
8. まず通常のテキストチャットと基本的な音声再生が正しく動くことを確認し、その後で追加のオプションを順番に有効化するのがおすすめです。

最初の結果を良くするには、短くてきれいな参照音声を使い、その内容と正確に一致する参照テキストを設定することが大切です。参照音声、参照テキスト、言語設定が食い違っていると、音質や安定性が急に悪くなりやすいです。

ENE の現在の標準的なコンパニオンらしさに近づけたい場合は、GPT-SoVITS でもまず日本語ベースで始めるのがいちばん簡単です。

### ストリーミングモードを有効にする

ストリーミングモードを有効にするには、TTS 設定の `GPT-SoVITS ストリーミング TTS を使う` をオンにしてください。

ストリーミングを使うと、音声全体が完成するのを待たずに少し早く話し始められるため、ENE の応答がより即時的に感じられます。特に短い往復会話では体感しやすいです。

ただし、まず通常の GPT-SoVITS 再生が安定していることを確認してからストリーミングを有効にするのがおすすめです。基本の非ストリーミング経路が安定していれば、ストリーミング特有の問題も切り分けやすくなります。

### GPT-SoVITS でよくあるつまずき

- `まったく音が出ない`: GPT-SoVITS サーバーが起動していない、`API URL` が違う、または TTS プロバイダーが実際には `GPT-SoVITS HTTP` になっていないことが多いです。
- `音声が不自然、または不安定`: 参照音声、参照テキスト、言語設定の整合性が十分に取れていないことがよくあります。
- `テキスト応答は出るのに話さない`: プロバイダー設定だけでなく、TTS 自体が有効になっているか確認してください。
- `ストリーミングが不安定、または遅い`: いったんストリーミングをオフにして通常再生が安定するか確認し、その後でもう一度オンにして比べるのがおすすめです。
- `音質が弱い`: よりきれいな参照音声、より正確な参照テキスト、サンプルに正しく合った言語設定を試してください。
- `声は出るが ENE らしくない`: `sub_prompt_body.md` で spoken style を調整した上で、TTS 設定も一緒に見直すのが有効です。

## 画像アバターモード

ENE は Live2D モデルに加えて、画像アバターモードも使用できます。同じキャラクターの複数の感情画像を 1 つのフォルダーに入れ、設定画面でアバターモードを `image` に切り替えると、静止画像ベースのコンパニオンとして表示されます。生成画像のように、同一性を保った Live2D 素材一式を作るのが難しいワークフローに向いています。

画像フォルダーは感情別のファイル名で準備します。`normal` 画像は必須で、たとえば `normal.png`, `happy.png`, `sad.png`, `angry.webp` のように英語の感情キーをファイル名に使います。対応拡張子は `.png`, `.webp`, `.jpg`, `.jpeg` です。

登録された感情ファイル名は、内部プロンプトで使う利用可能な感情一覧に反映されます。そのため、フォルダーに実在する感情だけをモデルが選ぶように案内できます。

設定画面では画像フォルダーを選び、感情別画像をプレビューしながら、各画像の scale、x、y 位置を個別に調整できます。TTS 再生中の発話状態は、口開閉画像の差し替えではなく、アバターが上下に軽く動くことで表現されます。

## プロンプトファイル

ENE は Python コードを変更せずにキャラクター挙動を調整できるよう、Markdown プロンプトファイルを使用します。

デフォルトの場所:

- Windows: `%AppData%/ENE/prompts`

主要ファイル:

- `base_system_prompt.md` - ENE のアイデンティティ、関係性、基本動作
- `sub_prompt_body.md` - 話し方と追加の振る舞いルール
- `emotion_guides.md` - 表情キーと使い分けのガイド

通常チャットでは、基本プロンプト、コードで生成される分析・予定・約束ルール、生成されたランタイム契約、補助プロンプト本文、モデル対応の表情ガイドを組み合わせます。`/note` の計画フローはより制限された文脈を使うため、通常の補助プロンプト経路とは異なります。

## 音声、TTS、リップシンク

ENE は複数の音声経路をサポートします。

- GPT-SoVITS 系 HTTP TTS
- OpenAI compatible audio speech
- ElevenLabs
- ブラウザー speech synthesis
- 対応している場合のストリーミング TTS

アプリは画面上の応答、音声再生、Live2D の口の動きの開始タイミングを合わせようとします。口パラメーターが豊かなモデルではモデル対応リップシンクプロファイルと viseme blending を使えます。単純なモデルでは基本の口開閉にフォールバックします。

PTT は ENE が話している途中でも TTS を止めて入力を始められるようにします。

## ノートと Obsidian

ENE には 2 つのノート向けコマンドがあります。

- `/diary` - 日記形式のローカル書き込み
- `/note` - 計画と実行に基づくノート作業

Obsidian CLI 連携を有効にすると、選択されたファイルを確認し、その文脈をプロンプトへ入れ、設定されたフローを通じて制御されたノート操作を実行できます。

## プロジェクト構成

```text
main.py                     PyQt エントリーポイントとランタイムプリロード
src/core/app.py             アプリケーション構成
src/core/app_*_bootstrap.py LLM、メモリ、TTS、プロフィール起動ヘルパー
src/core/bridge.py          QWebChannel bridge facade
src/core/bridge_mixins/     bridge の機能領域
src/ai/                     LLM、メモリ、プロンプト、プロフィール、目標、気分
src/ui/                     設定画面とデスクトップ UI ヘルパー
assets/web/                 Live2D Web ランタイム
assets/live2d_models/       同梱可能なモデル素材
scripts/                    setup と release スクリプト
tests/                      回帰テストとユニットテスト
```

現在の構造では `app.py` を構成コードに近づけ、起動責務を bootstrap モジュールへ分離しています。`WebBridge` は QWebChannel の統合点として残り、機能ごとの振る舞いは bridge mixin と service モジュールに分かれています。

## 開発

開発依存関係をインストール:

```powershell
pip install -r requirements-dev.txt
```

高速な構文/静的チェック:

```powershell
python -m ruff check . --select E9,F63,F7,F82
```

CI と同じ coverage gate:

```powershell
python -m coverage run --source=src --omit="src/core/app.py,src/core/audio_player.py,src/core/global_ptt.py,src/core/overlay_window.py,src/core/bridge_workers.py,src/core/bridge_mixins/attachments.py,src/core/bridge_mixins/away.py,src/core/bridge_mixins/memory_summary.py,src/core/bridge_mixins/mood.py,src/core/bridge_mixins/obsidian.py,src/ui/drag_bar.py,src/ui/settings_dialog_hotkeys.py,src/ui/settings_dialog_profile.py,src/ui/settings_dialog_prompt.py,src/ui/settings_dialog_theme.py,src/ui/settings_dialog_tts.py,src/ui/settings_dialog_widgets.py,src/ai/http_llm_clients.py,src/ai/http_llm_common.py,src/ai/http_llm_openai.py,src/ai/http_llm_custom_providers.py,src/ai/http_llm_anthropic.py,src/ai/http_llm_ollama.py,src/ai/llm_client.py" -m pytest -q
python -m coverage report --show-missing --skip-empty --fail-under=80
```

維持されているテストガイドと集中回帰セットについては [TESTING.md](TESTING.md) を参照してください。

## Web ランタイム素材

リポジトリにはデスクトップオーバーレイに必要な Live2D Web ランタイム素材が含まれています。生成された Web ライブラリを更新する場合は次を実行します。

```powershell
python scripts/setup_web_libs.py
```

## Windows リリースビルド

ローカルで portable Windows リリースをビルドします。

```powershell
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python scripts/build_windows_release.py --version v0.1.0
```

ビルドは `release/` 以下に `ENE.exe` と同梱ランタイムファイルを含む zip を作成します。

公開リリースに含める安全な基本素材:

- `assets/icons`
- `assets/web`
- `assets/live2d_models/hiyori`

個人の Live2D 購入素材、非公開の参照音声、プロバイダーキー、メモリファイル、プロフィールデータは公開リリースバンドルの外に置いてください。

## ロードマップ

- 初回オンボーディングと設定検証の改善
- パッケージ化されたデスクトップリリースの改善
- 設定、プロンプト、プロフィール、メモリの import/export
- メモリ制御の改善と Memory 2.0 の JSON ストレージから SQLite への移行
- 表情選択と能動的な会話タイミングの改善
- プロバイダー設定ガイドの強化
- 安定性に役立つ範囲でのみ大きな bridge/runtime 表面を縮小

## サードパーティライセンス

- ENE は Web UI の複数のコントロールで `paperclip`, `pencil`, `rotate-ccw` などの Lucide SVG アイコンをインライン使用しています。
- これらのアイコンはプロジェクト UI で直接使われており、Forui framework 経由で提供されているものではありません。
- Lucide アイコンは ISC License で配布されています。
- これらのアイコン素材や変更した SVG markup を再配布する場合は、適切な upstream attribution と license notice を保持してください。
