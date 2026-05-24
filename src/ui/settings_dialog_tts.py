"""
설정 대화상자 TTS 제어 mixin.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QFileDialog

from ..ai.tts_client import get_tts_provider_defaults
from ..core.audio_player import AudioPlayer


class SettingsDialogTtsMixin:
    def _browse_tts_audio_path_into(self, target_edit, title_key: str, title_fallback: str):
        start_dir = self._bundle_root / "assets" / "ref_audio"
        if not start_dir.exists():
            start_dir = self._user_data_root / "assets" / "ref_audio"
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self._translated_text(title_key, title_fallback),
            str(start_dir),
            self._translated_text(
                "settings.tts.gpt.reference.audio.dialog.filter",
                "Audio Files (*.wav *.mp3 *.flac *.ogg);;모든 파일 (*.*)",
            ),
        )
        if not selected:
            return
        target_edit.setText(self._normalize_path_for_storage(selected))

    def _browse_tts_ref_audio_path(self):
        self._browse_tts_audio_path_into(
            self.tts_ref_audio_path_edit,
            "settings.tts.gpt.reference.audio.dialog.title",
            "참조 오디오 선택",
        )

    @staticmethod
    def _build_tts_output_device_items(devices: list[dict], selected_device_id: str | None) -> list[tuple[str, str]]:
        selected = str(selected_device_id or "").strip()
        items: list[tuple[str, str]] = [
            ("시스템 기본 장치 (현재 사용 중)" if not selected else "시스템 기본 장치", ""),
        ]

        normalized_devices = []
        for device in devices:
            if not isinstance(device, dict):
                continue
            normalized_devices.append(
                {
                    "id": str(device.get("id", "")).strip(),
                    "name": str(device.get("name", "")).strip() or "이름 없는 장치",
                    "is_default": bool(device.get("is_default", False)),
                }
            )

        normalized_devices.sort(
            key=lambda device: (
                0 if device["is_default"] else 1,
                device["name"].lower(),
                device["id"],
            )
        )

        found_selected = False
        for device in normalized_devices:
            tags = []
            if device["is_default"]:
                tags.append("기본")
            if device["id"] == selected:
                tags.append("현재 사용 중")
                found_selected = True
            suffix = f" ({', '.join(tags)})" if tags else ""
            items.append((f"{device['name']}{suffix}", device["id"]))

        if selected and not found_selected:
            items.append((f"저장된 장치 (현재 없음, 현재 사용 중): {selected}", selected))

        return items

    def _refresh_tts_output_devices(self, selected_device_id: str | None = None) -> None:
        selected = str(selected_device_id or "").strip()
        try:
            devices = AudioPlayer.list_output_devices()
        except Exception:
            devices = []
        self._tts_output_devices = devices

        if not hasattr(self, "tts_output_device_combo"):
            return

        combo = self.tts_output_device_combo
        combo.blockSignals(True)
        combo.clear()
        for label, device_id in self._build_tts_output_device_items(devices, selected):
            combo.addItem(label, device_id)
        selected_index = combo.findData(selected) if selected else 0
        if selected_index < 0:
            selected_index = 0
        combo.setCurrentIndex(max(0, selected_index))
        combo.blockSignals(False)

    def _on_tts_output_device_refresh_clicked(self):
        current_device_id = ""
        if hasattr(self, "tts_output_device_combo"):
            current_device_id = str(self.tts_output_device_combo.currentData() or "").strip()
        self._refresh_tts_output_devices(current_device_id)
        self._on_setting_changed()

    def _get_overlay_web_page(self):
        if not self._bridge:
            return None
        parent = self._bridge.parent()
        if not parent or not hasattr(parent, "web_view"):
            return None
        try:
            return parent.web_view.page()
        except Exception:
            return None

    def _set_browser_voice_status(self, key: str, fallback: str, **kwargs) -> None:
        if hasattr(self, "tts_browser_voice_status_label"):
            self.tts_browser_voice_status_label.setText(
                self._translated_text_format(key, fallback, **kwargs)
            )

    def _refresh_browser_voice_status_label(self) -> None:
        if not hasattr(self, "tts_browser_voice_status_label"):
            return
        if self._browser_voice_request_inflight:
            self._set_browser_voice_status(
                "settings.tts.browser.status.loading",
                "현재 환경의 브라우저 음성 목록을 불러오는 중입니다...",
            )
            return
        if self._browser_tts_voices:
            selected_lang = ""
            if hasattr(self, "tts_browser_voice_lang_filter_combo"):
                selected_lang = str(self.tts_browser_voice_lang_filter_combo.currentData() or "").strip().lower()
            voices = list(self._browser_tts_voices)
            if selected_lang:
                voices = [
                    voice for voice in voices
                    if str(voice.get("lang", "")).strip().lower().startswith(selected_lang)
                ]
                self._set_browser_voice_status(
                    "settings.tts.browser.status.loaded_filtered",
                    "현재 환경에서 사용 가능한 음성 {total}개를 불러왔고, {language} 기준 {visible}개를 표시 중입니다.",
                    total=len(self._browser_tts_voices),
                    language=selected_lang,
                    visible=len(voices),
                )
                return
            self._set_browser_voice_status(
                "settings.tts.browser.status.loaded",
                "현재 환경에서 사용 가능한 음성 {total}개를 불러왔습니다.",
                total=len(self._browser_tts_voices),
            )
            return
        if self._get_overlay_web_page() is None:
            self._set_browser_voice_status(
                "settings.tts.browser.status.no_webview",
                "현재 웹뷰를 찾을 수 없어 음성 목록을 읽지 못했습니다.",
            )
            return
        if self._browser_voice_refresh_attempts > 0:
            self._set_browser_voice_status(
                "settings.tts.browser.status.waiting",
                "아직 음성 목록을 받지 못했습니다. 시스템 음성 초기화 뒤 다시 시도합니다.",
            )
            return
        self._set_browser_voice_status(
            "settings.tts.browser.status.idle",
            "설정창이 열려 있는 현재 ENE 웹뷰 환경에서 음성 목록을 읽습니다. 다른 PC에서는 그 환경 기준 목록이 다시 표시됩니다.",
        )

    def _request_browser_tts_voices(self):
        if self._browser_voice_request_inflight:
            return
        page = self._get_overlay_web_page()
        if page is None:
            self._refresh_browser_voice_status_label()
            return

        self._browser_voice_request_inflight = True
        self._refresh_browser_voice_status_label()
        page.runJavaScript(
            "(function(){"
            "if (typeof window.getBrowserTTSVoices === 'function') {"
            "return window.getBrowserTTSVoices();"
            "}"
            "return [];"
            "})();",
            self._handle_browser_tts_voices_result,
        )

    def _handle_browser_tts_voices_result(self, result):
        self._browser_voice_request_inflight = False
        voices = result if isinstance(result, list) else []
        normalized_voices = []
        for item in voices:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            lang = str(item.get("lang", "")).strip()
            if not name:
                continue
            normalized_voices.append(
                {
                    "name": name,
                    "lang": lang,
                    "default": bool(item.get("default", False)),
                }
            )

        if normalized_voices:
            self._browser_voice_refresh_attempts = 0
            self._browser_tts_voices = normalized_voices
            self._populate_browser_tts_language_filter(normalized_voices)
            self._populate_browser_tts_voice_combo()
            return

        self._browser_voice_refresh_attempts += 1
        self._refresh_browser_voice_status_label()
        if self._browser_voice_refresh_attempts < 4:
            self._browser_voice_refresh_timer.start(450)

    def _populate_browser_tts_language_filter(self, voices: list[dict]) -> None:
        if not hasattr(self, "tts_browser_voice_lang_filter_combo"):
            return
        current_data = self.tts_browser_voice_lang_filter_combo.currentData()
        current_lang = self.tts_browser_lang_edit.text().strip()
        languages = sorted({str(voice.get("lang", "")).strip() for voice in voices if str(voice.get("lang", "")).strip()})

        self.tts_browser_voice_lang_filter_combo.blockSignals(True)
        self.tts_browser_voice_lang_filter_combo.clear()
        self.tts_browser_voice_lang_filter_combo.addItem(
            self._translated_text("settings.tts.browser.filter.all", "전체 언어"),
            "",
        )
        for lang in languages:
            self.tts_browser_voice_lang_filter_combo.addItem(lang, lang)

        matched_index = -1
        if current_data:
            matched_index = self.tts_browser_voice_lang_filter_combo.findData(current_data)
        if matched_index < 0 and current_lang:
            matched_index = self.tts_browser_voice_lang_filter_combo.findData(current_lang)
        self.tts_browser_voice_lang_filter_combo.setCurrentIndex(matched_index if matched_index >= 0 else 0)
        self.tts_browser_voice_lang_filter_combo.blockSignals(False)

    def _populate_browser_tts_voice_combo(self) -> None:
        if not hasattr(self, "tts_browser_voice_combo"):
            return
        voices = list(self._browser_tts_voices)
        current_text = self.tts_browser_voice_combo.currentText().strip()
        selected_lang = ""
        if hasattr(self, "tts_browser_voice_lang_filter_combo"):
            selected_lang = str(self.tts_browser_voice_lang_filter_combo.currentData() or "").strip().lower()
        if selected_lang:
            voices = [
                voice for voice in voices
                if str(voice.get("lang", "")).strip().lower().startswith(selected_lang)
            ]
        self.tts_browser_voice_combo.blockSignals(True)
        self.tts_browser_voice_combo.clear()
        for voice in sorted(
            voices,
            key=lambda item: (
                0 if item.get("default") else 1,
                str(item.get("lang", "")),
                str(item.get("name", "")).lower(),
            ),
        ):
            label = str(voice["name"])
            lang = str(voice.get("lang", "")).strip()
            if lang:
                label = f"{label} ({lang})"
            if voice.get("default"):
                label = f"{label} · {self._translated_text('settings.tts.browser.voice.default_suffix', '기본')}"
            self.tts_browser_voice_combo.addItem(label, str(voice["name"]))

        if current_text:
            matched_index = self.tts_browser_voice_combo.findData(current_text)
            if matched_index >= 0:
                self.tts_browser_voice_combo.setCurrentIndex(matched_index)
            else:
                self.tts_browser_voice_combo.setEditText(current_text)
        self.tts_browser_voice_combo.blockSignals(False)

        self._refresh_browser_voice_status_label()

    def _on_browser_tts_language_filter_changed(self, *_):
        self._populate_browser_tts_voice_combo()

    def _on_browser_tts_lang_changed(self, *_):
        self._on_setting_changed()
        if not hasattr(self, "tts_browser_voice_lang_filter_combo"):
            return
        current_lang = self.tts_browser_lang_edit.text().strip()
        if not current_lang:
            return
        matched_index = self.tts_browser_voice_lang_filter_combo.findData(current_lang)
        if matched_index >= 0 and self.tts_browser_voice_lang_filter_combo.currentIndex() != matched_index:
            self.tts_browser_voice_lang_filter_combo.setCurrentIndex(matched_index)

    def _on_tts_provider_changed(self, *_):
        self._sync_tts_provider_ui()
        self._on_setting_changed()

    def _sync_tts_provider_ui(self):
        provider = str(self.tts_provider_combo.currentData() or "gpt_sovits_http")
        if hasattr(self, "tts_provider_stack"):
            page = self._tts_provider_pages.get(provider)
            if page is not None:
                self.tts_provider_stack.setCurrentWidget(page)
        if hasattr(self, "tts_provider_hint_label"):
            meta = self._tts_catalog.get(provider)
            self.tts_provider_hint_label.setText(self._tts_provider_hint(provider, meta))
        if provider == "browser_speech":
            self._browser_voice_refresh_attempts = 0
            self._request_browser_tts_voices()

    def _collect_tts_provider_configs(self) -> dict:
        return {
            "gpt_sovits_http": {
                "api_url": self.tts_api_url_edit.text().strip() or "http://127.0.0.1:9880",
                "ref_audio_path": self.tts_ref_audio_path_edit.text().strip() or "assets/ref_audio/refvoice.wav",
                "ref_text": self.tts_ref_text_edit.toPlainText().strip(),
                "ref_language": self.tts_ref_language_edit.text().strip() or "ja",
                "target_language": self.tts_target_language_edit.text().strip() or "ja",
                "speed_factor": round(self.tts_gpt_speed_factor_spin.value(), 2),
                "top_k": self.tts_gpt_top_k_spin.value(),
                "top_p": round(self.tts_gpt_top_p_spin.value(), 2),
                "temperature": round(self.tts_gpt_temperature_spin.value(), 2),
                "text_split_method": str(self.tts_gpt_text_split_combo.currentData() or "cut5"),
            },
            "genie_tts_http": {
                "api_url": self.tts_genie_api_url_edit.text().strip() or "http://127.0.0.1:7860",
                "character_name": self.tts_genie_character_name_edit.text().strip(),
                "onnx_model_dir": self.tts_genie_model_dir_edit.text().strip(),
                "model_language": self.tts_genie_model_language_edit.text().strip() or "ja",
                "ref_audio_path": self.tts_genie_ref_audio_path_edit.text().strip() or "assets/ref_audio/refvoice.wav",
                "ref_text": self.tts_genie_ref_text_edit.toPlainText().strip(),
                "ref_language": self.tts_genie_ref_language_edit.text().strip() or "ja",
                "split_sentence": self.tts_genie_split_sentence_check.isChecked(),
            },
            "openai_audio_speech": {
                "api_url": self.tts_openai_api_url_edit.text().strip() or "https://api.openai.com/v1",
                "model": str(self.tts_openai_model_combo.currentData() or "gpt-4o-mini-tts"),
                "voice": str(self.tts_openai_voice_combo.currentData() or "alloy"),
                "speed": round(self.tts_openai_speed_spin.value(), 2),
                "response_format": "wav",
            },
            "openai_compatible_audio_speech": {
                "api_url": self.tts_compatible_api_url_edit.text().strip() or "http://127.0.0.1:8000/v1",
                "model": self.tts_compatible_model_edit.text().strip() or "tts-1",
                "voice": self.tts_compatible_voice_edit.text().strip() or "alloy",
                "speed": round(self.tts_compatible_speed_spin.value(), 2),
                "response_format": "wav",
            },
            "elevenlabs": {
                "api_url": self.tts_elevenlabs_api_url_edit.text().strip() or "https://api.elevenlabs.io/v1",
                "model": str(self.tts_elevenlabs_model_combo.currentData() or "eleven_multilingual_v2"),
                "voice": self.tts_elevenlabs_voice_edit.text().strip() or "EXAVITQu4vr4xnSDxMaL",
                "speed": round(self.tts_elevenlabs_speed_spin.value(), 2),
                "stability": round(self.tts_elevenlabs_stability_spin.value(), 2),
                "similarity_boost": round(self.tts_elevenlabs_similarity_spin.value(), 2),
                "style": round(self.tts_elevenlabs_style_spin.value(), 2),
                "use_speaker_boost": self.tts_elevenlabs_speaker_boost_check.isChecked(),
                "output_format": "pcm_44100",
            },
            "browser_speech": {
                "lang": self.tts_browser_lang_edit.text().strip() or "ja-JP",
                "voice": self.tts_browser_voice_combo.currentData() or self.tts_browser_voice_combo.currentText().strip(),
                "rate": round(self.tts_browser_rate_spin.value(), 2),
                "pitch": round(self.tts_browser_pitch_spin.value(), 2),
                "volume": round(self.tts_browser_volume_spin.value(), 2),
            },
        }

    def _collect_tts_api_keys(self) -> dict:
        return {
            "openai_audio_speech": self.tts_openai_api_key_edit.text().strip(),
            "openai_compatible_audio_speech": self.tts_compatible_api_key_edit.text().strip(),
            "elevenlabs": self.tts_elevenlabs_api_key_edit.text().strip(),
        }

    def _load_tts_values(self):
        configs = self._tts_provider_configs
        gpt_sovits = {**get_tts_provider_defaults("gpt_sovits_http"), **configs.get("gpt_sovits_http", {})}
        genie = {**get_tts_provider_defaults("genie_tts_http"), **configs.get("genie_tts_http", {})}
        openai = {**get_tts_provider_defaults("openai_audio_speech"), **configs.get("openai_audio_speech", {})}
        compatible = {**get_tts_provider_defaults("openai_compatible_audio_speech"), **configs.get("openai_compatible_audio_speech", {})}
        elevenlabs = {**get_tts_provider_defaults("elevenlabs"), **configs.get("elevenlabs", {})}
        browser = {**get_tts_provider_defaults("browser_speech"), **configs.get("browser_speech", {})}

        self.enable_tts_check.setChecked(self._original_settings.get("enable_tts", True))
        tts_language = str(self._original_settings.get("tts_language", "ja") or "ja").strip()
        tts_language_index = self.tts_language_combo.findData(tts_language)
        if tts_language_index < 0:
            tts_language_index = self.tts_language_combo.findData("ja")
        self.tts_language_combo.setCurrentIndex(max(0, tts_language_index))
        self.tts_streaming_enabled_check.setChecked(
            self._original_settings.get("tts_streaming_enabled", False)
        )
        self.viseme_lipsync_enabled_check.setChecked(
            bool(self._original_settings.get("viseme_lipsync_enabled", True))
        )
        self._refresh_tts_output_devices(str(self._original_settings.get("tts_output_device_id", "")).strip())
        self.tts_output_volume_spin.setValue(
            int(round(float(self._original_settings.get("tts_output_volume", 0.8) or 0.8) * 100))
        )

        tts_provider = str(self._original_settings.get("tts_provider", "gpt_sovits_http")).strip().lower()
        tts_provider_index = self.tts_provider_combo.findData(tts_provider)
        if tts_provider_index < 0:
            tts_provider_index = 0
        self.tts_provider_combo.setCurrentIndex(tts_provider_index)

        self.tts_api_url_edit.setText(str(gpt_sovits.get("api_url", "http://127.0.0.1:9880")))
        self.tts_ref_audio_path_edit.setText(str(gpt_sovits.get("ref_audio_path", "assets/ref_audio/refvoice.wav")))
        self.tts_ref_text_edit.setPlainText(str(gpt_sovits.get("ref_text", "")))
        self.tts_ref_language_edit.setText(str(gpt_sovits.get("ref_language", "ja")))
        self.tts_target_language_edit.setText(str(gpt_sovits.get("target_language", "ja")))
        self.tts_gpt_speed_factor_spin.setValue(float(gpt_sovits.get("speed_factor", 1.0) or 1.0))
        self.tts_gpt_top_k_spin.setValue(int(gpt_sovits.get("top_k", 15) or 15))
        self.tts_gpt_top_p_spin.setValue(float(gpt_sovits.get("top_p", 1.0) or 1.0))
        self.tts_gpt_temperature_spin.setValue(float(gpt_sovits.get("temperature", 1.0) or 1.0))
        gpt_text_split_method = str(gpt_sovits.get("text_split_method", "cut5") or "cut5")
        gpt_text_split_index = self.tts_gpt_text_split_combo.findData(gpt_text_split_method)
        if gpt_text_split_index < 0:
            self.tts_gpt_text_split_combo.addItem(gpt_text_split_method, gpt_text_split_method)
            gpt_text_split_index = self.tts_gpt_text_split_combo.count() - 1
        self.tts_gpt_text_split_combo.setCurrentIndex(gpt_text_split_index)

        self.tts_genie_api_url_edit.setText(str(genie.get("api_url", "http://127.0.0.1:7860")))
        self.tts_genie_character_name_edit.setText(str(genie.get("character_name", "")))
        self.tts_genie_model_dir_edit.setText(str(genie.get("onnx_model_dir", "")))
        self.tts_genie_model_language_edit.setText(str(genie.get("model_language", "ja")))
        self.tts_genie_ref_audio_path_edit.setText(str(genie.get("ref_audio_path", "assets/ref_audio/refvoice.wav")))
        self.tts_genie_ref_text_edit.setPlainText(str(genie.get("ref_text", "")))
        self.tts_genie_ref_language_edit.setText(str(genie.get("ref_language", "ja")))
        self.tts_genie_split_sentence_check.setChecked(bool(genie.get("split_sentence", True)))

        self.tts_openai_api_key_edit.setText(str(self._tts_api_keys.get("openai_audio_speech", "")))
        self.tts_openai_api_url_edit.setText(str(openai.get("api_url", "https://api.openai.com/v1")))
        openai_model_index = self.tts_openai_model_combo.findData(str(openai.get("model", "gpt-4o-mini-tts")))
        if openai_model_index < 0:
            openai_model_index = 0
        self.tts_openai_model_combo.setCurrentIndex(openai_model_index)
        openai_voice_index = self.tts_openai_voice_combo.findData(str(openai.get("voice", "alloy")))
        if openai_voice_index < 0:
            openai_voice_index = 0
        self.tts_openai_voice_combo.setCurrentIndex(openai_voice_index)
        self.tts_openai_speed_spin.setValue(float(openai.get("speed", 1.0) or 1.0))

        self.tts_compatible_api_key_edit.setText(str(self._tts_api_keys.get("openai_compatible_audio_speech", "")))
        self.tts_compatible_api_url_edit.setText(str(compatible.get("api_url", "http://127.0.0.1:8000/v1")))
        self.tts_compatible_model_edit.setText(str(compatible.get("model", "tts-1")))
        self.tts_compatible_voice_edit.setText(str(compatible.get("voice", "alloy")))
        self.tts_compatible_speed_spin.setValue(float(compatible.get("speed", 1.0) or 1.0))

        self.tts_elevenlabs_api_key_edit.setText(str(self._tts_api_keys.get("elevenlabs", "")))
        self.tts_elevenlabs_api_url_edit.setText(str(elevenlabs.get("api_url", "https://api.elevenlabs.io/v1")))
        elevenlabs_model_index = self.tts_elevenlabs_model_combo.findData(str(elevenlabs.get("model", "eleven_multilingual_v2")))
        if elevenlabs_model_index < 0:
            elevenlabs_model_index = 0
        self.tts_elevenlabs_model_combo.setCurrentIndex(elevenlabs_model_index)
        self.tts_elevenlabs_voice_edit.setText(str(elevenlabs.get("voice", "EXAVITQu4vr4xnSDxMaL")))
        self.tts_elevenlabs_speed_spin.setValue(float(elevenlabs.get("speed", 1.0) or 1.0))
        self.tts_elevenlabs_stability_spin.setValue(float(elevenlabs.get("stability", 0.5) or 0.5))
        self.tts_elevenlabs_similarity_spin.setValue(float(elevenlabs.get("similarity_boost", 0.75) or 0.75))
        self.tts_elevenlabs_style_spin.setValue(float(elevenlabs.get("style", 0.0) or 0.0))
        self.tts_elevenlabs_speaker_boost_check.setChecked(bool(elevenlabs.get("use_speaker_boost", True)))

        self.tts_browser_lang_edit.setText(str(browser.get("lang", "ja-JP")))
        self.tts_browser_voice_combo.setEditText(str(browser.get("voice", "")))
        self.tts_browser_rate_spin.setValue(float(browser.get("rate", 1.0) or 1.0))
        self.tts_browser_pitch_spin.setValue(float(browser.get("pitch", 1.0) or 1.0))
        self.tts_browser_volume_spin.setValue(float(browser.get("volume", 1.0) or 1.0))
        self._sync_tts_provider_ui()
