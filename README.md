# <p align="center"><img src="assets/icons/tray_icon.png" alt="ENE icon" width="96" /></p>

<h1 align="center">ENE</h1>

<p align="center">
  A memory-aware AI desktop companion with a Live2D presence.
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

ENE is a desktop AI partner that stays with you on your workspace. It combines a Live2D overlay, long-term memory, personalized prompts, voice output, notes, goals, promises, mood state, and proactive context into one companion-style desktop app.

It is not meant to be a generic chat window. ENE is built around presence: a character on your desktop that remembers useful context, reacts through expressions and motion, speaks when configured, and helps with daily workflows such as notes, reminders, diary entries, and follow-up conversations.

> [!NOTE]
> ENE is a personal project under active development. It is usable, but it has not been hardened across many machines or provider setups yet.

> [!IMPORTANT]
> The memory embedding workflow has been tested most reliably with Voyage. Other providers may be added or improved later.

## Preview

| Desktop companion | Chat and controls |
| :---: | :---: |
| ![ENE desktop preview](docs/screenshots/ene-desktop-preview.png) | ![ENE desktop preview 2](docs/screenshots/ene-desktop-preview-2.png) |

## What ENE Can Do

- Show a persistent Live2D companion overlay with tray-based desktop app behavior.
- Chat through the on-screen interface with personality, prompt, memory, profile, and mood context.
- Use image and document attachments as part of a conversation.
- Store long-term memory with summaries, facts, metadata, and retrieval context.
- Maintain user and ENE profile information so conversations can become more personal over time.
- Track ENE mood state across multiple axes and reflect that state in tone, expression guidance, and UI feedback.
- Track ENE goals with short-term and long-term goal state.
- Remember conversational promises and bring them back as scheduled follow-up prompts.
- Save diary-style entries with `/diary`.
- Run note workflows with `/note`, including Obsidian-oriented planning and execution when configured.
- Browse checked Obsidian files and include selected context in prompts.
- Extract calendar-like events and conversation activity signals.
- Use TTS providers, browser speech, streaming TTS, push-to-talk interruption, and model-aware lip-sync.
- Detect long idle periods and optionally send proactive away nudges.
- Configure model, prompt, profile, TTS, theme, hotkeys, memory, Obsidian, goals, and behavior from the settings window.

## Current Status

ENE is in active development with a practical local workflow:

- The bundled default Live2D model is `hiyori`.
- User-selected model paths are preserved after restart.
- LLM provider creation is split into provider-specific modules behind a compatibility facade.
- App startup responsibilities are separated into focused bootstrap modules.
- CI runs on Linux and Windows with Python 3.11.
- The selected CI coverage gate is currently `80%`.

The project is still improving in first-run onboarding, packaged releases, settings import/export, and public documentation.

## Supported Languages

The application UI includes locale files for:

- English
- Korean
- Japanese

Prompt language, visible response language, and TTS language can still depend on your provider, prompt settings, and model behavior.

## Quick Start

### 1. Create a virtual environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2. Run ENE

```powershell
python main.py
```

ENE starts as a PyQt desktop app with tray behavior. Right-click the tray icon to open the settings window.

### 3. Configure providers and keys

ENE stores user-editable runtime files in the user data directory:

- Windows: `%AppData%/ENE`

Common files:

- `config.json` - runtime settings and feature toggles
- `api_keys.json` - provider keys and other secrets
- `memory.json` - long-term memory storage
- `user_profile.json` - user profile facts
- `ene_goals.json` - ENE goal state
- `calendar.json`, `mood_state.json`, `obs_config.json` - supporting state
- `prompts/*.md` - editable prompt files

> [!WARNING]
> Keep real secrets in `api_keys.json`. Do not commit personal API keys, private model assets, memory files, or profile files.

## Recommended First-Time Setup

1. Launch ENE with `python main.py`.
2. Open the settings window from the tray icon.
3. Select your LLM provider, model, and API key.
4. Keep the bundled `hiyori` model or choose your own `.model3.json` file.
5. Check expression names for your selected Live2D model.
6. Fill in user profile and ENE profile settings.
7. Configure Voyage embeddings if you want the most reliable memory setup.
8. Enable and tune TTS only after text chat is working.
9. Enable Obsidian CLI integration only if you want ENE to work with local notes.

## Prompt Files

ENE uses Markdown prompt files so character behavior can be edited without changing Python code.

Default location:

- Windows: `%AppData%/ENE/prompts`

Core files:

- `base_system_prompt.md` - ENE's identity, relationship, and core behavior
- `sub_prompt_body.md` - speaking style and extra behavior rules
- `emotion_guides.md` - emotion keys and usage guidance
- `analysis_system_appendix.md` - optional internal analysis guidance

Normal chat prompt assembly uses the base prompt, generated runtime contract, sub-prompt body, model-aware emotion guidance, and optional analysis appendix. `/note` planning uses a more constrained context and does not follow the normal sub-prompt path in the same way.

## Voice, TTS, and Lip-Sync

ENE supports several voice paths:

- HTTP TTS providers such as GPT-SoVITS-style endpoints
- OpenAI-compatible audio speech
- ElevenLabs
- browser speech synthesis
- streaming TTS where supported

The app can synchronize visible responses, audio playback, and Live2D mouth movement. For models with richer mouth parameters, ENE can use model-aware lip-sync profiles and viseme blending. For simpler models, it falls back to basic mouth-open behavior.

Push-to-talk can interrupt active TTS playback so voice input does not compete with ENE speaking.

## Notes and Obsidian

ENE includes two note-oriented command paths:

- `/diary` for diary-style local writing
- `/note` for plan-and-execute note workflows

When Obsidian CLI integration is enabled, ENE can inspect checked files, include selected context in prompts, and run controlled note operations through the configured workflow.

## Project Structure

```text
main.py                     PyQt entry point and runtime preload
src/core/app.py             application composition
src/core/app_*_bootstrap.py app startup helpers for LLM, memory, TTS, profile
src/core/bridge.py          QWebChannel bridge facade
src/core/bridge_mixins/     bridge feature areas
src/ai/                     LLM clients, memory, prompts, profiles, goals, mood
src/ui/                     settings dialogs and desktop UI helpers
assets/web/                 Live2D web runtime
assets/live2d_models/       bundled release-safe model assets
scripts/                    setup and release scripts
tests/                      regression and unit tests
```

The current architecture keeps `app.py` close to composition code and moves startup responsibilities into focused bootstrap modules. `WebBridge` still acts as the QWebChannel integration point, while feature behavior is split across bridge mixins and service modules.

## Development

Install development dependencies:

```powershell
pip install -r requirements-dev.txt
```

Run the fast syntax/lint gate:

```powershell
python -m ruff check . --select E9,F63,F7,F82
```

Run the CI-style coverage gate:

```powershell
python -m coverage run --source=src --omit="src/core/app.py,src/core/audio_player.py,src/core/global_ptt.py,src/core/overlay_window.py,src/core/bridge_workers.py,src/core/bridge_mixins/attachments.py,src/core/bridge_mixins/away.py,src/core/bridge_mixins/memory_summary.py,src/core/bridge_mixins/mood.py,src/core/bridge_mixins/obsidian.py,src/ui/drag_bar.py,src/ui/settings_dialog_hotkeys.py,src/ui/settings_dialog_profile.py,src/ui/settings_dialog_prompt.py,src/ui/settings_dialog_theme.py,src/ui/settings_dialog_tts.py,src/ui/settings_dialog_widgets.py,src/ai/http_llm_clients.py,src/ai/http_llm_common.py,src/ai/http_llm_openai.py,src/ai/http_llm_custom_providers.py,src/ai/http_llm_anthropic.py,src/ai/http_llm_ollama.py,src/ai/llm_client.py" -m pytest -q
python -m coverage report --show-missing --skip-empty --fail-under=80
```

See [TESTING.md](TESTING.md) for the maintained test guide and focused regression groups.

## Web Runtime Assets

The repository includes the Live2D web runtime assets needed by the desktop overlay. If you need to refresh generated web libraries:

```powershell
python scripts/setup_web_libs.py
```

## Windows Release Build

Build a portable Windows release locally:

```powershell
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python scripts/build_windows_release.py --version v0.1.0
```

The build creates a zip under `release/` containing `ENE.exe` and bundled runtime files.

Release-safe built-in assets include:

- `assets/icons`
- `assets/web`
- `assets/live2d_models/hiyori`

Personal Live2D purchases, private reference audio, provider keys, memory files, and profile data should stay outside the public release bundle.

## Roadmap

- Improve first-run onboarding and setup validation.
- Polish packaged desktop releases.
- Add import/export for settings, prompts, profiles, and memory.
- Improve memory controls and eventually move Memory 2.0 storage from JSON to SQLite.
- Improve expression selection and proactive conversation timing.
- Add richer provider setup guidance.
- Continue reducing large bridge/runtime surfaces only where it improves reliability.

## Third-Party Licenses

- ENE uses inline Lucide SVG icons for several controls in the web UI, including `paperclip`, `pencil`, and `rotate-ccw`.
- These icons are used directly in the project UI and are not provided through the Forui framework.
- Lucide icons are distributed under the ISC License.
- When redistributing these icon assets or adapted SVG markup, keep the appropriate upstream attribution and license notices for Lucide.
