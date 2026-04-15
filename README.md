# <p align="center"><img src="assets/icons/tray_icon.png" alt="ENE icon" width="96" /></p>

<h1 align="center">ENE</h1>

<p align="center">
  A memory-aware AI desktop companion with a Live2D presence.
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" />
  <img alt="PyQt6" src="https://img.shields.io/badge/PyQt6-Desktop-41CD52?logo=qt&logoColor=white" />
  <img alt="Live2D" src="https://img.shields.io/badge/Live2D-Overlay-FF6B81" />
  <img alt="Status" src="https://img.shields.io/badge/status-active%20development-1f883d" />
</p>

ENE is a desktop AI partner that stays on top of your workspace, chats with you through a dedicated on-screen interface, remembers context over time, and connects everyday interaction to notes, mood tracking, and personal memory flows.

It is designed as a personal companion rather than a plain chat window: something that feels present on your desktop, responds with personality, and becomes more useful as your daily context accumulates.

> [!NOTE]
> ENE is still a personal project under active development. It has not been tested broadly across different environments yet, so depending on your setup, you may run into instability or unexpected errors.

> [!IMPORTANT]
> The embedding workflow has only been tested with Voyage so far. If you want the most reliable setup, it is strongly recommended to issue a Voyage API key and use a Voyage embedding model.

## Preview

| Preview | Preview |
| :---: | :---: |
| ![ENE desktop preview](docs/screenshots/ene-desktop-preview.png) | ![ENE desktop preview 2](docs/screenshots/ene-desktop-preview-2.png) |

<p align="center">
  Current in-app desktop UI with quick actions, message input, settings access, and Live2D companion view.
</p>

## Why ENE?

- A desktop-native AI companion instead of a browser-only chat tool
- Live2D overlay presence with a dedicated app lifecycle and tray behavior
- Memory-aware interaction with notes, mood state, diary data, and profile context
- Voice-ready architecture with TTS, STT runtime preload, and lip-sync support
- Built for practical daily workflows, not only demo conversations

## Supported Languages

ENE currently includes interface translations for:

- English
- Japanese
- Korean

In practice, this means the app UI and settings experience can be used in those languages. Actual conversation language, tone, and voice output can still vary depending on the model, prompt, and provider settings you choose.

## What You Can Do With ENE

- Keep ENE visible on your desktop as a Live2D-based companion instead of opening a separate chat page every time you want to interact.
- Chat with ENE through the main on-screen interface while using memory, master-related settings, and profile context to make conversations feel more personal over time.
- Save notes, summaries, and diary-style content as part of your daily workflow instead of treating conversations as disposable.
- Talk about schedules and calendar-related plans, with extracted event information being added into ENE's calendar flow.
- Use quick actions such as summary, note, mood-related controls, and calendar-related support directly from the main experience.
- Configure your own character setup, including Live2D model path, expressions, prompt tone, and companion behavior.
- Open the settings window from the tray icon and adjust important options without manually editing raw files.
- Use voice-related features such as push-to-talk and TTS-ready interaction if you want ENE to feel more like a spoken desktop companion.
- Use the `/note` command to work with connected Obsidian documents, and when Obsidian CLI integration is enabled, let ENE modify those documents through the linked workflow.
- Let ENE detect long periods of inactivity, compare screen captures for activity changes, and proactively speak first when it thinks you have been away.

## Still Improving

- First-run onboarding and simpler initial setup
- Packaged desktop release workflow
- More polished public-facing documentation

## Getting Started

### 1. Create a virtual environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2. Prepare configuration

ENE stores user-editable runtime files in the user data directory.

- Windows: `%AppData%/ENE`

Typical files stored there:

- `config.json` for runtime settings and feature toggles
- `api_keys.json` for secrets and provider keys
- `user_profile.json` for user-specific profile data
- `memory.json` for long-term memory storage
- `calendar.json`, `mood_state.json`, `obs_config.json` for supporting state

At minimum, review these before running:

- LLM provider and model selection
- API keys for the selected LLM provider
- Embedding provider key
- TTS provider settings if voice output is enabled
- Live2D model path

> [!WARNING]
> Keep real secrets in `api_keys.json`, not in `config.json`, and do not commit personal keys to the repository.

### 3. Verify web runtime assets if needed

The repository already includes web assets for Live2D rendering. If you need to refresh the JavaScript runtime files, run:

```powershell
python setup.py
```

### 4. Run ENE

```powershell
python main.py
```

When launched, ENE starts as a desktop application with tray behavior and overlay-oriented UI flow.

### 5. Open the settings window from the tray icon

After ENE is running, right-click the tray icon to open the settings window. This is the easiest place to adjust the model, prompt, profile, and behavior settings without editing files by hand.

## Recommended First-Time Setup

If this is your first time using ENE, the following setup flow is recommended:

1. Open the settings window from the tray icon.
2. Set your Live2D model path so ENE loads the character you want to use.
3. Add or organize expressions that match your model so reactions feel natural.
4. Write or refine the ENE prompt so the assistant speaks and behaves the way you want.
5. Fill in master-related settings and profile information so ENE has a better understanding of who it is talking to.
6. Set up your API keys, especially your Voyage embedding key if you want the most reliable memory setup.

These steps are not mandatory, but they are highly recommended if you want ENE to feel more personal and stable from the beginning.

## First-Time Setup Tips

- `Included model`: ENE already includes the `hiyori` model, so you can start there if you just want to get the app running.
- `Recommended model setup`: For a more personal setup, it is recommended to purchase and use another Live2D model from marketplaces such as [BOOTH](https://booth.pm/).
- `Live2D model`: Pick the model JSON path first. It affects how ENE appears, moves, and responds on screen.
- `Expressions`: If your purchased model already includes emotion files, organize those first. If it does not, you can create expression files through VTube Studio and use those to improve emotional feedback in ENE.
- `ENE prompt`: Spend a little time writing the prompt that defines ENE's personality and behavior. This has a big impact on how the companion feels in daily use.
- `Master settings`: It is a good idea to fill in your master-related information and profile details early. ENE becomes more useful when it has some stable context about you.
- `Embedding`: Voyage is the safest choice for now because that is the provider this project has actually been tested with.

## Prompt Markdown Files

ENE uses Markdown files inside the user prompt folder so you can adjust personality and behavior without directly editing Python code.

- Windows: `%AppData%/ENE/prompts`

Prompt content is arranged into the runtime context in this order during normal chat:

1. `base_system_prompt.md`
2. generated sub-prompt wrapper
3. `sub_prompt_body.md`
4. generated emotion usage section based on `emotion_guides.md`
5. `analysis_system_appendix.md` when that appendix is enabled for the current prompt path

- `prompts/base_system_prompt.md`
  Write ENE's core identity here: who ENE is, how it should generally speak, what kind of relationship it should have with the user, and what attitude or tone it should maintain consistently.

- `prompts/sub_prompt_body.md`
  Write additional behavioral instructions here: how ENE should respond in daily situations, how affectionate, playful, calm, or serious it should feel, and any extra response rules you want on top of the base prompt.

- `prompts/emotion_guides.md`
  Write the list of emotion keys and short usage guidance here. This is where you explain what each emotion means and when ENE should choose it.

- `prompts/analysis_system_appendix.md`
  Write supporting analysis rules here if you want ENE to follow extra internal guidance for interpretation or structured reasoning. This is more of an advanced tuning file than a first-setup file. It is not loaded for `/note` planning flows that run without the normal sub-prompt path.

For `/note` planning flows, ENE does not use the normal sub-prompt path, so `sub_prompt_body.md`, `emotion_guides.md`, and `analysis_system_appendix.md` are not placed into the planning context in the same way.

If you are just starting, the most important files are `base_system_prompt.md`, `sub_prompt_body.md`, and `emotion_guides.md`.

## Configuration Notes

The settings window already covers most of what you will want to change in normal use, including:

- model selection and provider-specific parameters
- TTS provider switching
- embedding model configuration
- global PTT behavior
- Obsidian CLI integration settings
- `viseme 립싱크` toggle for speech-time mouth shaping
- Live2D model placement and scale

You can use ENE without touching most internals, but if something does not behave the way you expect, the settings window is the first place to check before editing the raw configuration files.

### `viseme 립싱크`

The `viseme 립싱크` setting controls how ENE shapes the mouth while voice output is playing.

- When enabled, ENE uses viseme-style mouth poses and blends them with expression mouth bias during speech.
- When disabled, ENE falls back to the legacy RMS-only open path, so the mouth behaves like a simple open/close lip-sync signal.
- This applies to supported in-app audio TTS providers; `browser_speech` keeps its existing browser `speechSynthesis` path.

### TTS 동기화 버퍼와 립싱크 시작 시점

지원되는 앱 내부 오디오 TTS 공급자에서는 메시지 표시, 오디오 재생, 립싱크 시작을 가능한 한 같은 시점으로 맞춘다.

- `gpt_sovits_http` 스트리밍 ON에서는 적응형 `80~120ms` 동기화 버퍼를 사용한다.
- viseme 준비가 최소 버퍼 안에서 끝나면 그 시점에 메시지와 오디오를 함께 시작한다.
- viseme 준비가 늦으면 `120ms`를 넘겨 기다리지 않고 현재 RMS 기반 립싱크로 폴백해 재생을 시작한다.
- `gpt_sovits_http` 스트리밍 OFF, `openai_audio_speech`, `openai_compatible_audio_speech`, `elevenlabs`, `genie_tts_http`는 완성된 오디오를 받은 뒤 같은 시작 계약을 사용한다.
- `browser_speech`는 브라우저 내부 `speechSynthesis` 재생이라서 이 V1 동기화 버퍼 범위에는 포함되지 않는다.

### 모델 적응형 립싱크

ENE의 립싱크는 이제 Live2D 모델이 가진 입 파라미터 구성을 읽어 자동으로 모드를 고른다.

- `ParamMouthOpenY`만 있으면 `open_only`
- `ParamMouthOpenY + ParamMouthForm`이면 `open_form`
- `ParamMouthOpenY + ParamMouthForm + ParamMouthFunnel + ParamMouthPuckerWiden + ParamJawOpen` 조합이면 `vbridger`
- 직접 `A/I/U/E/O` 계열 파라미터가 있으면 `phoneme_direct`

기본 동작은 자동 감지이며, 모델 폴더에 `lip_sync_profile.json` 파일이 있으면 그 파일의 값만 부분적으로 덮어쓴다.

- 파일이 없으면 자동 감지 결과만 사용한다.
- override 파일이 깨졌거나 일부 키만 있어도 재생을 막지 않고 자동 감지 결과로 자연스럽게 폴백한다.
- viseme 품질이 낮거나 준비가 늦으면 `shape` 계열만 약해지고, 입 개폐는 RMS 기반으로 계속 유지된다.

즉, 새 모델을 추가할 때는 먼저 그냥 연결해 보고, 입모양 강도만 더 다듬고 싶을 때만 `lip_sync_profile.json`을 추가하면 된다.

### Genie-TTS HTTP Provider

ENE now includes a dedicated `Genie-TTS HTTP` provider for Genie-TTS style servers.

Before using it:

- start the Genie-TTS API server first
- open ENE settings and switch the TTS provider to `Genie-TTS HTTP`
- fill in `API URL`, `Character Name`, and `ONNX Model Folder`
- set the reference voice path, reference transcript, and reference language

This provider uses a fixed character flow. On first synthesis, ENE loads the configured character, registers the reference audio, and then requests speech from the Genie server. If the reference audio path is wrong or the server is not already running, synthesis will fail until those values are corrected.

## Windows Release Build

To build a portable Windows release locally:

```powershell
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python scripts/build_windows_release.py --version v0.1.0
```

The build produces a zip file in `release/` that contains the `ENE/` folder with `ENE.exe` and its bundled runtime files.

The portable release intentionally bundles only release-safe built-in assets:

- `assets/icons`
- `assets/web`
- `assets/live2d_models/hiyori`

Personal Live2D purchases, private reference audio, and other user-specific assets should be provided through external paths after install, not committed into the public release bundle.

GitHub Releases automation is configured so that pushing a tag such as `v0.1.0` builds the same portable zip on `windows-latest` and uploads it to the release.

## Roadmap

- [ ] improve first-run setup and configuration guidance
- [ ] improve stability
- [ ] start conversations first with an appropriate topic when it is not already in an active conversation
- [ ] add internet search capabilities
- [ ] add better memory controls
- [ ] upgrade ENE Memory 2.0 from JSON to SQLite
- [ ] make expression and emotion switching feel more natural
- [ ] import and export settings, prompts, and profile data
- [ ] add relationship and personality tuning presets
- [ ] improve context-aware proactive conversations

## Third-Party Licenses

- ENE uses inline Lucide SVG icons for several controls in the web UI, including `paperclip`, `pencil`, and `rotate-ccw`.
- These icons are used directly in the project UI and are not provided through the Forui framework.
- Lucide icons are distributed under the ISC License.
- When redistributing these icon assets or their adapted SVG markup, please keep the appropriate upstream attribution and license notices for Lucide.
