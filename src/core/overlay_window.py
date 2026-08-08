"""
Transparent overlay window for Live2D.
"""
import json
from pathlib import Path
import re
import sys

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..ui.drag_bar import DragBar
from .bridge import WebBridge
from .i18n import I18n, get_i18n
from .image_avatar import build_image_avatar_payload
from .live2d_parameter_overrides import (
    empty_live2d_parameter_payload,
    normalize_live2d_parameter_override_payload,
)
from .model_emotions import DEFAULT_MODEL_JSON_PATH, get_available_model_emotions, resolve_model_json_path
from .model_tracking_params import load_model_tracking_parameter_map_for_model_json


class OverlayWindow(QWidget):
    """Transparent always-on-top overlay hosting the Live2D web view."""

    def __init__(
        self,
        settings_manager,
        *,
        life_time_context=None,
        life_view_timezone: str = "UTC",
    ):
        super().__init__()
        self.settings = settings_manager
        self.life_time_context = life_time_context
        self.life_view_timezone = str(life_view_timezone or "UTC")
        self._page_loaded = False
        self._shutting_down = False
        self._last_sent_mouse_pos = None
        self._mouse_send_min_delta = 2
        self._live2d_parameter_window = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.bridge = WebBridge(settings=self.settings, parent=self)
        self._setup_ui()
        self._setup_webchannel()
        self._apply_settings()
        self._setup_mouse_tracking()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.web_view = QWebEngineView(self)
        self.web_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.web_view.setStyleSheet("background: transparent;")

        from PyQt6.QtGui import QColor
        from PyQt6.QtWebEngineCore import QWebEngineSettings

        page = self.web_view.page()
        page.setBackgroundColor(QColor(0, 0, 0, 0))
        self.web_view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        self.web_view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self.web_view.loadFinished.connect(self._on_page_loaded)

        html_path = self._get_html_path()
        if html_path.exists():
            self.web_view.setUrl(QUrl.fromLocalFile(str(html_path)))
        else:
            print(f"WARNING: HTML not found: {html_path}")

        layout.addWidget(self.web_view)

        self.drag_bar = DragBar(self)
        self.drag_bar.move(0, 0)
        self.drag_bar.resize(self.width(), 30)
        self.drag_bar.raise_()
        self.drag_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def _on_page_loaded(self, ok):
        if self._shutting_down:
            return
        if not ok:
            print("WARNING: Web page load failed")
            return

        self._page_loaded = True
        self.web_view.page().runJavaScript(
            """
            document.body.style.backgroundColor = 'transparent';
            document.documentElement.style.backgroundColor = 'transparent';
            """
        )
        self._apply_model_settings()
        self._sync_theme_to_js()
        self._sync_ui_strings_to_js()
        self._sync_mouse_tracking_state_to_js()
        self._sync_idle_motion_settings_to_js()
        self._sync_reroll_button_visibility_to_js()
        self._sync_edit_button_visibility_to_js()
        self._sync_manual_summary_button_visibility_to_js()
        self._sync_obsidian_note_button_visibility_to_js()
        self._sync_mood_toggle_button_visibility_to_js()
        self._sync_proactive_conversation_button_visibility_to_js()
        self._sync_goal_button_visibility_to_js()
        self._sync_token_usage_bubble_visibility_to_js()
        self._sync_typing_effect_settings_to_js()
        self._sync_message_split_settings_to_js()
        self._sync_thought_feature_settings_to_js()
        self._sync_chat_panel_height_to_js()
        print("Web page loaded")

    def open_live2d_parameter_inspector(self) -> None:
        from ..ui.live2d_parameter_window import Live2DParameterWindow

        if self._live2d_parameter_window is None:
            self._live2d_parameter_window = Live2DParameterWindow(self)
        self._live2d_parameter_window.show_and_refresh()

    def _get_base_path(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys._MEIPASS)
        return Path(__file__).parent.parent.parent

    def _resolve_settings_source(self, settings_source=None) -> dict:
        if isinstance(settings_source, dict):
            return settings_source
        config = getattr(settings_source, "config", None)
        if isinstance(config, dict):
            return config
        return self.settings.config

    def _resolve_model_path_payload(self, settings_source=None) -> dict:
        source = self._resolve_settings_source(settings_source)
        base_path = self._get_base_path()
        avatar_mode = str(source.get("avatar_mode", "live2d") or "live2d").strip().lower()
        if avatar_mode != "image":
            avatar_mode = "live2d"

        model_path = resolve_model_json_path(settings_source=source, base_path=base_path)
        image_avatar_payload = build_image_avatar_payload(source, base_path=base_path)
        if avatar_mode == "image":
            available_emotions = image_avatar_payload.get("availableEmotions", ["normal"])
        else:
            available_emotions = get_available_model_emotions(
                settings_source=source,
                base_path=base_path,
            )

        return {
            "avatarMode": avatar_mode,
            "modelPath": model_path.as_uri(),
            "emotionsBasePath": model_path.parent.joinpath("emotions").resolve().as_uri().rstrip("/") + "/",
            "availableEmotions": available_emotions,
            "imageAvatar": image_avatar_payload,
        }

    def _resolve_model_key(self, settings_source=None) -> str:
        source = self._resolve_settings_source(settings_source)
        raw_path = str(source.get("model_json_path", "") or "").strip()
        if raw_path:
            return raw_path.replace("\\", "/")
        return DEFAULT_MODEL_JSON_PATH

    def _resolve_live2d_parameter_overrides_payload(self, settings_source=None) -> dict:
        source = self._resolve_settings_source(settings_source)
        model_key = self._resolve_model_key(source)
        overrides = source.get("live2d_parameter_overrides", {})
        if not isinstance(overrides, dict):
            return empty_live2d_parameter_payload()
        payload = overrides.get(model_key, {})
        return normalize_live2d_parameter_override_payload(payload) or empty_live2d_parameter_payload()

    def _resolve_live2d_parameter_display_info_payload(self, settings_source=None) -> dict:
        source = self._resolve_settings_source(settings_source)
        model_path = resolve_model_json_path(
            settings_source=source,
            base_path=self._get_base_path(),
        )
        try:
            model_payload = json.loads(model_path.read_text(encoding="utf-8-sig"))
        except Exception:
            model_payload = {}

        display_info_path = None
        file_references = model_payload.get("FileReferences", {}) if isinstance(model_payload, dict) else {}
        raw_display_info = file_references.get("DisplayInfo") if isinstance(file_references, dict) else None
        if isinstance(raw_display_info, str) and raw_display_info.strip():
            display_info_path = (model_path.parent / raw_display_info).resolve()
        else:
            model_name = model_path.name
            if model_name.endswith(".model3.json"):
                display_info_path = model_path.with_name(f"{model_name[:-len('.model3.json')]}.cdi3.json")
            else:
                display_info_path = model_path.with_suffix(".cdi3.json")

        try:
            cdi_payload = json.loads(display_info_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {"parameters": {}, "groups": {}}

        groups: dict[str, dict[str, str]] = {}
        for item in cdi_payload.get("ParameterGroups", []) or []:
            if not isinstance(item, dict):
                continue
            group_id = str(item.get("Id", "")).strip()
            if not group_id:
                continue
            groups[group_id] = {
                "name": str(item.get("Name", "")).strip(),
                "parentGroupId": str(item.get("GroupId", "")).strip(),
            }

        parameters: dict[str, dict[str, str]] = {}
        for item in cdi_payload.get("Parameters", []) or []:
            if not isinstance(item, dict):
                continue
            param_id = str(item.get("Id", "")).strip()
            if not param_id:
                continue
            group_id = str(item.get("GroupId", "")).strip()
            parameters[param_id] = {
                "name": str(item.get("Name", "")).strip(),
                "groupId": group_id,
                "groupName": groups.get(group_id, {}).get("name", ""),
            }
        return {"parameters": parameters, "groups": groups}

    def _resolve_model_config_payload(
        self,
        settings_source=None,
        *,
        include_image_avatar_preview_emotion: bool = False,
    ) -> dict:
        source = self._resolve_settings_source(settings_source)
        path_payload = self._resolve_model_path_payload(source)
        if path_payload["avatarMode"] == "image":
            parameter_overrides = empty_live2d_parameter_payload()
            parameter_display_info = {"parameters": {}, "groups": {}}
            tracking_parameter_map = {}
        else:
            parameter_overrides = self._resolve_live2d_parameter_overrides_payload(source)
            parameter_display_info = self._resolve_live2d_parameter_display_info_payload(source)
            model_path = resolve_model_json_path(
                settings_source=source,
                base_path=self._get_base_path(),
            )
            tracking_parameter_map = load_model_tracking_parameter_map_for_model_json(model_path)
        payload = {
            "scale": source.get("model_scale", 1.0),
            "xPercent": source.get("model_x_percent", 50),
            "yPercent": source.get("model_y_percent", 50),
            "avatarMode": path_payload["avatarMode"],
            "modelPath": path_payload["modelPath"],
            "emotionsBasePath": path_payload["emotionsBasePath"],
            "availableEmotions": path_payload["availableEmotions"],
            "imageAvatar": path_payload["imageAvatar"],
            "modelKey": self._resolve_model_key(source),
            "parameterOverrides": parameter_overrides,
            "parameterDisplayInfo": parameter_display_info,
            "trackingParameterMap": tracking_parameter_map,
        }
        if include_image_avatar_preview_emotion:
            payload["imageAvatarPreviewEmotion"] = str(
                source.get("image_avatar_preview_emotion", "normal") or "normal"
            ).strip() or "normal"
        return payload

    def _format_model_config_js_object(self, payload: dict) -> str:
        preview_emotion_line = ""
        if "imageAvatarPreviewEmotion" in payload:
            preview_emotion_line = (
                "                imageAvatarPreviewEmotion: "
                f"{json.dumps(payload['imageAvatarPreviewEmotion'])},\n"
            )
        return (
            "{\n"
            f"                scale: {json.dumps(payload['scale'])},\n"
            f"                xPercent: {json.dumps(payload['xPercent'])},\n"
            f"                yPercent: {json.dumps(payload['yPercent'])},\n"
            f"                avatarMode: {json.dumps(payload['avatarMode'])},\n"
            f"                modelPath: {json.dumps(payload['modelPath'])},\n"
            f"                emotionsBasePath: {json.dumps(payload['emotionsBasePath'])},\n"
            f"                availableEmotions: {json.dumps(payload['availableEmotions'])},\n"
            f"                imageAvatar: {json.dumps(payload['imageAvatar'], ensure_ascii=False)},\n"
            f"{preview_emotion_line}"
            f"                modelKey: {json.dumps(payload['modelKey'])},\n"
            f"                parameterOverrides: {json.dumps(payload['parameterOverrides'])},\n"
            "                parameterDisplayInfo: "
            f"{json.dumps(payload['parameterDisplayInfo'], ensure_ascii=False)},\n"
            "                trackingParameterMap: "
            f"{json.dumps(payload.get('trackingParameterMap', {}), ensure_ascii=False)}\n"
            "            }"
        )

    def _normalize_theme_hex(self, raw_value: str, fallback: str) -> str:
        match = re.fullmatch(r"#?([0-9A-Fa-f]{6})", str(raw_value or "").strip())
        if not match:
            return fallback
        return f"#{match.group(1).upper()}"

    def _hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        normalized = self._normalize_theme_hex(hex_color, "#000000")
        return (
            int(normalized[1:3], 16),
            int(normalized[3:5], 16),
            int(normalized[5:7], 16),
        )

    def _hex_to_rgba_css(self, hex_color: str, alpha: float) -> str:
        r, g, b = self._hex_to_rgb(hex_color)
        safe_alpha = max(0.0, min(1.0, alpha))
        return f"rgba({r}, {g}, {b}, {safe_alpha:.2f})"

    def _theme_text_color(self, hex_color: str) -> str:
        r, g, b = self._hex_to_rgb(hex_color)
        luminance = (0.299 * r) + (0.587 * g) + (0.114 * b)
        return "#111214" if luminance >= 160 else "#F7F9FC"

    def _resolve_theme_payload(self, settings_source=None) -> dict:
        source = settings_source if isinstance(settings_source, dict) else self.settings.config
        defaults = {
            "accentColor": "#0071E3",
            "settingsWindowBgColor": "#EEF1F5",
            "settingsCardBgColor": "#FFFFFF",
            "settingsInputBgColor": "#F8FAFC",
            "chatPanelBgColor": "#111214",
            "chatInputBgColor": "#1B1D22",
            "chatAssistantBubbleColor": "#FFFFFF",
            "chatUserBubbleColor": "#0071E3",
        }
        key_map = {
            "accentColor": "theme_accent_color",
            "settingsWindowBgColor": "settings_window_bg_color",
            "settingsCardBgColor": "settings_card_bg_color",
            "settingsInputBgColor": "settings_input_bg_color",
            "chatPanelBgColor": "chat_panel_bg_color",
            "chatInputBgColor": "chat_input_bg_color",
            "chatAssistantBubbleColor": "chat_assistant_bubble_color",
            "chatUserBubbleColor": "chat_user_bubble_color",
        }
        return {
            payload_key: self._normalize_theme_hex(source.get(settings_key, fallback), fallback)
            for payload_key, settings_key in key_map.items()
            for fallback in [defaults[payload_key]]
        }

    def _sync_theme_to_js(self, settings_override: dict | None = None) -> None:
        if not self._page_loaded:
            return

        theme_payload = self._resolve_theme_payload(settings_override)
        js_code = f"""
        (function() {{
            window.eneThemeConfig = {json.dumps(theme_payload)};
            if (typeof window.applyENETheme === 'function') {{
                window.applyENETheme(window.eneThemeConfig);
            }}
        }})();
        """
        self.web_view.page().runJavaScript(js_code)

    def _build_ui_i18n(self, settings_override: dict | None = None) -> I18n:
        source = settings_override if isinstance(settings_override, dict) else self.settings.config
        runtime_i18n = get_i18n()
        return I18n(
            language=str(source.get("ui_language", "auto")),
            locales_dir=runtime_i18n.locales_dir,
        )

    def _resolve_ui_strings_payload(self, settings_override: dict | None = None) -> dict:
        i18n = self._build_ui_i18n(settings_override)
        return {
            "resolvedLanguage": i18n.language,
            "loading": i18n.t("chat.loading"),
            "loadingSearching": i18n.t("chat.loading.searching"),
            "input": {
                "placeholder": i18n.t("chat.input.placeholder"),
            },
            "send": i18n.t("chat.send"),
            "actions": {
                "summary": {
                    "label": i18n.t("chat.actions.summary"),
                    "title": i18n.t("chat.actions.summary.title"),
                },
                "note": {
                    "label": i18n.t("chat.actions.note"),
                    "title": i18n.t("chat.actions.note.title"),
                },
                "mood": {
                    "label": i18n.t("chat.actions.mood"),
                    "title": i18n.t("chat.actions.mood.title"),
                },
                "promises": {
                    "label": i18n.t("chat.actions.promises"),
                    "title": i18n.t("chat.actions.promises.title"),
                },
                "proactive": {
                    "label": i18n.t("chat.actions.proactive"),
                    "title": i18n.t("chat.actions.proactive.title"),
                },
                "live2dParameters": {
                    "label": i18n.t("chat.actions.live2dParameters.label"),
                    "title": i18n.t("chat.actions.live2dParameters.title"),
                },
                "goals": {
                    "label": i18n.t("chat.actions.goals"),
                    "title": i18n.t("chat.actions.goals.title"),
                },
            },
            "promiseNotice": {
                "saved": i18n.t("chat.promise.notice.saved"),
            },
            "promisePanel": {
                "empty": i18n.t("chat.promise.panel.empty"),
                "soon": i18n.t("chat.promise.panel.soon"),
                "queued": i18n.t("chat.promise.panel.queued"),
                "inMinutes": i18n.t("chat.promise.panel.in_minutes"),
                "overdueMinutes": i18n.t("chat.promise.panel.overdue_minutes"),
            },
            "proactivePanel": {
                "title": i18n.t("chat.proactive.panel.title"),
                "close": i18n.t("chat.proactive.panel.close"),
                "empty": i18n.t("chat.proactive.panel.empty"),
                "soon": i18n.t("chat.proactive.panel.soon"),
                "queued": i18n.t("chat.proactive.panel.queued"),
                "inMinutes": i18n.t("chat.proactive.panel.in_minutes"),
                "overdueMinutes": i18n.t("chat.proactive.panel.overdue_minutes"),
                "remove": i18n.t("chat.proactive.panel.remove"),
            },
            "live2dParameters": {
                "title": i18n.t("chat.live2dParameters.title"),
                "close": i18n.t("chat.live2dParameters.close"),
                "warning": i18n.t("chat.live2dParameters.warning"),
                "search": i18n.t("chat.live2dParameters.search"),
                "all": i18n.t("chat.live2dParameters.all"),
                "favorites": i18n.t("chat.live2dParameters.favorites"),
                "save": i18n.t("chat.live2dParameters.save"),
                "reset": i18n.t("chat.live2dParameters.reset"),
                "empty": i18n.t("chat.live2dParameters.empty"),
                "statusIdle": i18n.t("chat.live2dParameters.status_idle"),
                "statusLoading": i18n.t("chat.live2dParameters.status_loading"),
                "statusUnavailable": i18n.t("chat.live2dParameters.status_unavailable"),
                "statusError": i18n.t("chat.live2dParameters.status_error"),
                "toastLoadFirst": i18n.t("chat.live2dParameters.toast_load_first"),
                "toastMissingModel": i18n.t("chat.live2dParameters.toast_missing_model"),
                "toastMissingBridge": i18n.t("chat.live2dParameters.toast_missing_bridge"),
                "toastSaveSuccess": i18n.t("chat.live2dParameters.toast_save_success"),
                "toastSaveError": i18n.t("chat.live2dParameters.toast_save_error"),
            },
            "goalPanel": {
                "label": i18n.t("chat.goals.label"),
                "title": i18n.t("chat.goals.title"),
                "empty": i18n.t("chat.goals.empty"),
                "shortTerm": i18n.t("chat.goals.short_term"),
                "longTerm": i18n.t("chat.goals.long_term"),
                "close": i18n.t("chat.goals.close"),
            },
            "mood": {
                "label": i18n.t("chat.mood.label"),
                "loading": i18n.t("chat.mood.loading"),
                "collapse": i18n.t("chat.mood.collapse"),
                "axis": {
                    "valence": i18n.t("chat.mood.axis.valence"),
                    "bond": i18n.t("chat.mood.axis.bond"),
                    "energy": i18n.t("chat.mood.axis.energy"),
                    "stress": i18n.t("chat.mood.axis.stress"),
                },
                "states": {
                    "calm": i18n.t("chat.mood.state.calm"),
                    "cheerful": i18n.t("chat.mood.state.cheerful"),
                    "affectionate": i18n.t("chat.mood.state.affectionate"),
                    "tired": i18n.t("chat.mood.state.tired"),
                    "tense": i18n.t("chat.mood.state.tense"),
                    "sensitive": i18n.t("chat.mood.state.sensitive"),
                    "unknown": i18n.t("chat.mood.state.unknown"),
                },
                "temporaryStates": {
                    "steady": i18n.t("chat.mood.temporary.steady"),
                    "playful": i18n.t("chat.mood.temporary.playful"),
                    "focused": i18n.t("chat.mood.temporary.focused"),
                    "drained": i18n.t("chat.mood.temporary.drained"),
                    "guarded": i18n.t("chat.mood.temporary.guarded"),
                    "pout": i18n.t("chat.mood.temporary.pout"),
                },
            },
            "summaryConfirm": {
                "title": i18n.t("chat.summary.confirm.title"),
                "body": i18n.t("chat.summary.confirm.body"),
                "no": i18n.t("chat.summary.confirm.no"),
                "yes": i18n.t("chat.summary.confirm.yes"),
            },
            "thoughts": {
                "button": i18n.t("chat.thoughts.button"),
                "buttonTitle": i18n.t("chat.thoughts.button.title"),
                "panelTitle": i18n.t("chat.thoughts.panel.title"),
                "close": i18n.t("chat.thoughts.close"),
                "empty": i18n.t("chat.thoughts.empty"),
                "show": i18n.t("chat.thoughts.show"),
                "hide": i18n.t("chat.thoughts.hide"),
                "speaker": i18n.t("chat.thoughts.speaker"),
            },
        }

    def _resolve_typing_effect_payload(self, settings_override: dict | None = None) -> dict:
        source = settings_override if isinstance(settings_override, dict) else self.settings.config
        speed = str(source.get("typing_effect_speed", "normal")).strip().lower() or "normal"
        if speed not in {"fast", "normal", "slow"}:
            speed = "normal"
        return {
            "enabled": bool(source.get("typing_effect_enabled", True)),
            "speed": speed,
        }

    def _resolve_message_split_payload(self, settings_override: dict | None = None) -> dict:
        source = settings_override if isinstance(settings_override, dict) else self.settings.config
        return {
            "enabled": bool(source.get("message_split_enabled", False)),
        }

    def _resolve_thought_feature_payload(self, settings_override: dict | None = None) -> dict:
        source = settings_override if isinstance(settings_override, dict) else self.settings.config
        return {
            "enabled": bool(source.get("enable_ene_thoughts", True)),
        }

    def _resolve_chat_panel_height_payload(self, settings_override: dict | None = None) -> dict:
        source = settings_override if isinstance(settings_override, dict) else self.settings.config
        raw_height = source.get("chat_panel_height", 0)
        try:
            height = int(raw_height)
        except Exception:
            height = 0
        return {
            "height": max(0, height),
        }

    def _sync_ui_strings_to_js(self, settings_override: dict | None = None) -> None:
        if not self._page_loaded:
            return

        payload = self._resolve_ui_strings_payload(settings_override)
        js_code = f"""
        (function() {{
            window.eneUiStrings = {json.dumps(payload, ensure_ascii=False)};
            if (typeof window.applyENEUiStrings === 'function') {{
                window.applyENEUiStrings(window.eneUiStrings);
            }}
        }})();
        """
        self.web_view.page().runJavaScript(js_code)

    def _sync_typing_effect_settings_to_js(self, settings_override: dict | None = None) -> None:
        if not self._page_loaded:
            return

        payload = self._resolve_typing_effect_payload(settings_override)
        js_code = f"""
        (function() {{
            window.eneTypingEffectConfig = {json.dumps(payload)};
            if (typeof window.setTypingEffectConfig === 'function') {{
                window.setTypingEffectConfig(window.eneTypingEffectConfig);
            }}
        }})();
        """
        self.web_view.page().runJavaScript(js_code)

    def _sync_message_split_settings_to_js(self, settings_override: dict | None = None) -> None:
        if not self._page_loaded:
            return

        payload = self._resolve_message_split_payload(settings_override)
        js_code = f"""
        (function() {{
            window.eneMessageSplitConfig = {json.dumps(payload)};
            if (typeof window.setMessageSplitConfig === 'function') {{
                window.setMessageSplitConfig(window.eneMessageSplitConfig);
            }}
        }})();
        """
        self.web_view.page().runJavaScript(js_code)

    def _sync_thought_feature_settings_to_js(self, settings_override: dict | None = None) -> None:
        if not self._page_loaded:
            return

        payload = self._resolve_thought_feature_payload(settings_override)
        js_code = f"""
        (function() {{
            window.eneThoughtFeatureConfig = {json.dumps(payload)};
            if (typeof window.setThoughtFeatureEnabled === 'function') {{
                window.setThoughtFeatureEnabled(window.eneThoughtFeatureConfig.enabled);
            }}
        }})();
        """
        self.web_view.page().runJavaScript(js_code)

    def _sync_chat_panel_height_to_js(self, settings_override: dict | None = None) -> None:
        if not self._page_loaded:
            return

        payload = self._resolve_chat_panel_height_payload(settings_override)
        js_code = f"""
        (function() {{
            window.eneChatPanelConfig = {json.dumps(payload)};
            if (typeof window.setChatPanelHeight === 'function') {{
                window.setChatPanelHeight(window.eneChatPanelConfig.height);
            }}
        }})();
        """
        self.web_view.page().runJavaScript(js_code)

    def _apply_drag_bar_theme(self, settings_override: dict | None = None) -> None:
        theme_payload = self._resolve_theme_payload(settings_override)
        base_color = theme_payload["chatPanelBgColor"]
        text_color = self._theme_text_color(base_color)
        border_color = self._hex_to_rgba_css(text_color, 0.12)
        background = self._hex_to_rgba_css(base_color, 0.64)
        self.drag_bar.apply_theme(background, text_color, border_color)

    def _apply_model_settings(self):
        model_config = self._resolve_model_config_payload()
        scale = model_config["scale"]
        x_percent = model_config["xPercent"]
        y_percent = model_config["yPercent"]
        model_config_js = self._format_model_config_js_object(model_config)

        js_code = f"""
        (function() {{
            window.eneModelConfig = {model_config_js};

            function applyModelSettings() {{
                if (typeof window.applyENEModelSettings === 'function') {{
                    window.applyENEModelSettings(window.eneModelConfig);
                }} else {{
                    const model = window.live2dModel;
                    if (model) {{
                        const canvasWidth = window.innerWidth;
                        const canvasHeight = window.innerHeight;
                        model.scale.set({scale});
                        model.x = canvasWidth * {x_percent / 100};
                        model.y = canvasHeight * {y_percent / 100};
                    }} else {{
                        setTimeout(applyModelSettings, 100);
                    }}
                }}
            }}
            applyModelSettings();
        }})();
        """
        self.web_view.page().runJavaScript(js_code)

    def _get_html_path(self) -> Path:
        base_path = self._get_base_path()
        return base_path / "assets" / "web" / "index.html"

    def _apply_settings(self):
        self.move(self.settings.get("window_x", 100), self.settings.get("window_y", 100))
        self.resize(self.settings.get("window_width", 400), self.settings.get("window_height", 600))
        self.web_view.setZoomFactor(self.settings.get("zoom_level", 1.0))
        self.drag_bar.setVisible(self.settings.get("show_drag_bar", True))
        self._apply_drag_bar_theme()

    def apply_new_settings(self, new_settings: dict):
        old_tracking = self.settings.get("mouse_tracking_enabled", True)
        new_tracking = new_settings.get("mouse_tracking_enabled", True)

        self.settings.update(new_settings)
        self._apply_settings()
        self._apply_model_settings()
        self._sync_theme_to_js()
        self._sync_ui_strings_to_js(new_settings)
        self._apply_drag_bar_theme()

        if old_tracking != new_tracking:
            self._set_mouse_tracking_enabled(new_tracking)

        self._sync_idle_motion_settings_to_js()
        self._sync_reroll_button_visibility_to_js()
        self._sync_edit_button_visibility_to_js()
        self._sync_manual_summary_button_visibility_to_js()
        self._sync_obsidian_note_button_visibility_to_js()
        self._sync_mood_toggle_button_visibility_to_js()
        self._sync_proactive_conversation_button_visibility_to_js()
        self._sync_goal_button_visibility_to_js()
        self._sync_token_usage_bubble_visibility_to_js()
        self._sync_typing_effect_settings_to_js()
        self._sync_message_split_settings_to_js()
        self._sync_thought_feature_settings_to_js()
        self._sync_chat_panel_height_to_js()
        if hasattr(self, "bridge") and self.bridge:
            self.bridge.refresh_away_settings()
        self.settings.save()

    def preview_settings(self, new_settings: dict):
        self.move(new_settings.get("window_x", self.settings.get("window_x", 100)),
                  new_settings.get("window_y", self.settings.get("window_y", 100)))
        self.resize(
            new_settings.get("window_width", self.settings.get("window_width", 400)),
            new_settings.get("window_height", self.settings.get("window_height", 600)),
        )
        self.drag_bar.setVisible(new_settings.get("show_drag_bar", self.settings.get("show_drag_bar", True)))
        self._apply_drag_bar_theme(new_settings)

        preview_source = dict(self.settings.config)
        preview_source.update(new_settings)
        model_config_js = self._format_model_config_js_object(
            self._resolve_model_config_payload(
                preview_source,
                include_image_avatar_preview_emotion=True,
            )
        )
        js_code = f"""
        (function() {{
            window.eneModelConfig = {model_config_js};
            if (typeof window.applyENEModelSettings === 'function') {{
                window.applyENEModelSettings(window.eneModelConfig);
            }}
        }})();
        """
        self.web_view.page().runJavaScript(js_code)

        if self._page_loaded:
            self._sync_theme_to_js(new_settings)
            self._sync_ui_strings_to_js(new_settings)
            self._sync_idle_motion_settings_to_js(new_settings)
            self._sync_reroll_button_visibility_to_js(new_settings)
            self._sync_edit_button_visibility_to_js(new_settings)
            self._sync_manual_summary_button_visibility_to_js(new_settings)
            self._sync_obsidian_note_button_visibility_to_js(new_settings)
            self._sync_mood_toggle_button_visibility_to_js(new_settings)
            self._sync_proactive_conversation_button_visibility_to_js(new_settings)
            self._sync_goal_button_visibility_to_js(new_settings)
            self._sync_token_usage_bubble_visibility_to_js(new_settings)
            self._sync_typing_effect_settings_to_js(new_settings)
            self._sync_message_split_settings_to_js(new_settings)
            self._sync_thought_feature_settings_to_js(new_settings)
            self._sync_chat_panel_height_to_js(new_settings)

    def restore_settings(self):
        self._apply_settings()
        self._apply_model_settings()
        self._sync_theme_to_js()
        self._sync_ui_strings_to_js()
        self._apply_drag_bar_theme()
        self._sync_idle_motion_settings_to_js()
        self._sync_reroll_button_visibility_to_js()
        self._sync_edit_button_visibility_to_js()
        self._sync_manual_summary_button_visibility_to_js()
        self._sync_obsidian_note_button_visibility_to_js()
        self._sync_mood_toggle_button_visibility_to_js()
        self._sync_proactive_conversation_button_visibility_to_js()
        self._sync_goal_button_visibility_to_js()
        self._sync_token_usage_bubble_visibility_to_js()
        self._sync_typing_effect_settings_to_js()
        self._sync_message_split_settings_to_js()
        self._sync_thought_feature_settings_to_js()
        self._sync_chat_panel_height_to_js()

    def toggle_drag_bar(self):
        visible = not self.drag_bar.isVisible()
        self.drag_bar.setVisible(visible)
        self.settings.set("show_drag_bar", visible)
        self.settings.save()
        return visible

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.drag_bar.resize(self.width(), 30)

    def closeEvent(self, event):
        self.shutdown()
        self.settings.set("window_x", self.x())
        self.settings.set("window_y", self.y())
        self.settings.set("window_width", self.width())
        self.settings.set("window_height", self.height())
        self.settings.save()
        event.accept()

    def shutdown(self):
        """QWebEngine 관련 자원을 종료 전에 먼저 정리한다."""
        if self._shutting_down:
            return

        self._shutting_down = True
        self._page_loaded = False
        self._last_sent_mouse_pos = None

        if self._live2d_parameter_window is not None:
            self._live2d_parameter_window.hide()
            self._live2d_parameter_window.deleteLater()
            self._live2d_parameter_window = None

        if hasattr(self, "mouse_tracking_timer") and self.mouse_tracking_timer.isActive():
            self.mouse_tracking_timer.stop()

        try:
            self.web_view.loadFinished.disconnect(self._on_page_loaded)
        except Exception:
            pass

        try:
            page = self.web_view.page()
            page.setWebChannel(None)
        except Exception:
            pass

        try:
            self.web_view.stop()
        except Exception:
            pass

        try:
            self.web_view.setHtml("", QUrl("about:blank"))
        except Exception:
            pass

    def _setup_mouse_tracking(self):
        from PyQt6.QtCore import QTimer

        self.mouse_tracking_timer = QTimer(self)
        self.mouse_tracking_timer.setInterval(33)
        self.mouse_tracking_timer.timeout.connect(self._update_mouse_position)
        if self.settings.get("mouse_tracking_enabled", True):
            self.mouse_tracking_timer.start()

    def _update_mouse_position(self):
        from PyQt6.QtGui import QCursor

        if not self.mouse_tracking_timer.isActive() or not self._page_loaded:
            return

        global_pos = QCursor.pos()
        local_pos = self.web_view.mapFromGlobal(global_pos)
        x = local_pos.x()
        y = local_pos.y()

        if self._last_sent_mouse_pos is not None:
            last_x, last_y = self._last_sent_mouse_pos
            if abs(x - last_x) < self._mouse_send_min_delta and abs(y - last_y) < self._mouse_send_min_delta:
                return

        self._last_sent_mouse_pos = (x, y)
        self.web_view.page().runJavaScript(f"window.updateMousePosition({x}, {y});")

    def _sync_mouse_tracking_state_to_js(self):
        if not self._page_loaded:
            return
        enabled = "true" if self.mouse_tracking_timer.isActive() else "false"
        self.web_view.page().runJavaScript(f"window.setMouseTrackingEnabled({enabled});")

    def _sync_idle_motion_settings_to_js(self, settings_override: dict | None = None):
        if not self._page_loaded:
            return

        source = settings_override if settings_override is not None else self.settings.config
        enabled = "true" if bool(source.get("enable_idle_motion", True)) else "false"
        builtin_enabled = "true" if bool(source.get("enable_builtin_idle_motion", True)) else "false"
        auto_eye_blink_enabled = "true" if bool(source.get("enable_auto_eye_blink", True)) else "false"
        strength = float(source.get("idle_motion_strength", 1.0))
        speed = float(source.get("idle_motion_speed", 1.0))
        expressive_motion_enabled = "true" if bool(source.get("enable_expressive_motion", False)) else "false"
        expressive_motion_strength = max(0.2, min(2.5, float(source.get("expressive_motion_strength", 1.0) or 1.0)))
        expressive_motion_speed = max(0.4, min(2.0, float(source.get("expressive_motion_speed", 1.0) or 1.0)))
        expressive_motion_speech_boost = max(0.0, min(2.5, float(source.get("expressive_motion_speech_boost", 1.0))))
        expressive_pose_transitions_enabled = (
            "true" if bool(source.get("enable_expressive_pose_transitions", False)) else "false"
        )
        synthetic_gesture_scale = max(0.5, min(3.0, float(source.get("synthetic_gesture_scale", 1.0) or 1.0)))
        idle_synthetic_gestures_enabled = (
            "true" if bool(source.get("enable_idle_synthetic_gestures", False)) else "false"
        )
        idle_synthetic_gesture_frequency = str(
            source.get("idle_synthetic_gesture_frequency", "normal")
        ).strip().lower()
        if idle_synthetic_gesture_frequency not in {"low", "normal", "high"}:
            idle_synthetic_gesture_frequency = "normal"
        head_pat_enabled = "true" if bool(source.get("enable_head_pat", True)) else "false"
        head_pat_strength = float(source.get("head_pat_strength", 1.0))
        head_pat_fade_in_ms = int(source.get("head_pat_fade_in_ms", 180))
        head_pat_fade_out_ms = int(source.get("head_pat_fade_out_ms", 220))
        active_custom = str(source.get("head_pat_active_emotion_custom", "")).strip()
        active_default = str(source.get("head_pat_active_emotion_default", "normal")).strip() or "normal"
        active_resolved = str(source.get("head_pat_active_emotion", "")).strip()
        head_pat_active_emotion = active_custom or active_resolved or active_default or "normal"
        end_custom = str(source.get("head_pat_end_emotion_custom", "")).strip()
        end_default = str(source.get("head_pat_end_emotion_default", "normal")).strip() or "normal"
        end_resolved = str(source.get("head_pat_end_emotion", "")).strip()
        head_pat_end_emotion = end_custom or end_resolved or end_default or "normal"
        head_pat_duration_sec = int(source.get("head_pat_end_emotion_duration_sec", 5))

        self.web_view.page().runJavaScript(
            "(function(){"
            "if (typeof window.setBuiltinIdleMotionEnabled === 'function') {"
            f"window.setBuiltinIdleMotionEnabled({builtin_enabled});"
            "}"
            "})();"
        )
        self.web_view.page().runJavaScript(
            "(function(){"
            "if (typeof window.setAutoEyeBlinkEnabled === 'function') {"
            f"window.setAutoEyeBlinkEnabled({auto_eye_blink_enabled});"
            "}"
            "})();"
        )
        self.web_view.page().runJavaScript(
            "(function(){"
            "if (typeof window.setIdleMotionEnabled === 'function') {"
            f"window.setIdleMotionEnabled({enabled});"
            "}"
            "})();"
        )
        self.web_view.page().runJavaScript(
            "(function(){"
            "if (typeof window.setIdleMotionConfig === 'function') {"
            f"window.setIdleMotionConfig({strength:.3f}, {speed:.3f});"
            "}"
            "})();"
        )
        self.web_view.page().runJavaScript(
            "(function(){"
            "if (typeof window.setExpressiveMotionConfig === 'function') {"
            f"window.setExpressiveMotionConfig({expressive_motion_enabled}, "
            f"{expressive_motion_strength:.3f}, {expressive_motion_speed:.3f}, "
            f"{expressive_motion_speech_boost:.3f}, {expressive_pose_transitions_enabled});"
            "}"
            "})();"
        )
        self.web_view.page().runJavaScript(
            "(function(){"
            "if (typeof window.setSyntheticGestureScale === 'function') {"
            f"window.setSyntheticGestureScale({synthetic_gesture_scale:.3f});"
            "}"
            "})();"
        )
        self.web_view.page().runJavaScript(
            "(function(){"
            "if (typeof window.setIdleSyntheticGestureConfig === 'function') {"
            f"window.setIdleSyntheticGestureConfig({idle_synthetic_gestures_enabled}, "
            f"{json.dumps(idle_synthetic_gesture_frequency)});"
            "}"
            "})();"
        )
        self.web_view.page().runJavaScript(
            "(function(){"
            "if (typeof window.setHeadPatConfig === 'function') {"
            "window.setHeadPatConfig("
            f"{head_pat_enabled}, "
            f"{head_pat_strength:.3f}, "
            f"{head_pat_fade_in_ms}, "
            f"{head_pat_fade_out_ms}, "
            f"{json.dumps(head_pat_active_emotion)}, "
            f"{json.dumps(head_pat_end_emotion)}, "
            f"{head_pat_duration_sec}"
            ");"
            "}"
            "})();"
        )

    def _sync_reroll_button_visibility_to_js(self, settings_override: dict | None = None):
        if not self._page_loaded:
            return
        source = settings_override if settings_override is not None else self.settings.config
        enabled = "true" if bool(source.get("show_recent_reroll_button", True)) else "false"
        self.web_view.page().runJavaScript(f"window.setRerollButtonEnabled({enabled});")

    def _sync_edit_button_visibility_to_js(self, settings_override: dict | None = None):
        if not self._page_loaded:
            return
        source = settings_override if settings_override is not None else self.settings.config
        enabled = "true" if bool(source.get("show_recent_edit_button", True)) else "false"
        self.web_view.page().runJavaScript(f"window.setRecentEditButtonEnabled({enabled});")

    def _sync_manual_summary_button_visibility_to_js(self, settings_override: dict | None = None):
        if not self._page_loaded:
            return
        source = settings_override if settings_override is not None else self.settings.config
        enabled = "true" if bool(source.get("show_manual_summary_button", True)) else "false"
        self.web_view.page().runJavaScript(f"window.setManualSummaryButtonEnabled({enabled});")

    def _sync_obsidian_note_button_visibility_to_js(self, settings_override: dict | None = None):
        if not self._page_loaded:
            return
        source = settings_override if settings_override is not None else self.settings.config
        enabled = "true" if bool(source.get("show_obsidian_note_button", True)) else "false"
        self.web_view.page().runJavaScript(f"window.setObsidianNoteButtonEnabled({enabled});")

    def _sync_mood_toggle_button_visibility_to_js(self, settings_override: dict | None = None):
        if not self._page_loaded:
            return
        source = settings_override if settings_override is not None else self.settings.config
        enabled = "true" if (
            bool(source.get("show_mood_toggle_button", True))
            and bool(source.get("enable_response_analysis", True))
        ) else "false"
        self.web_view.page().runJavaScript(f"window.setMoodToggleButtonEnabled({enabled});")

    def _sync_proactive_conversation_button_visibility_to_js(self, settings_override: dict | None = None):
        if not self._page_loaded:
            return
        source = settings_override if settings_override is not None else self.settings.config
        enabled = "true" if bool(source.get("enable_proactive_conversation", True)) else "false"
        self.web_view.page().runJavaScript(f"window.setProactiveConversationButtonEnabled({enabled});")

    def _sync_goal_button_visibility_to_js(self, settings_override: dict | None = None):
        if not self._page_loaded:
            return
        source = settings_override if settings_override is not None else self.settings.config
        enabled = "true" if (
            bool(source.get("enable_ene_goals", True))
            and bool(source.get("show_ene_goal_button", True))
        ) else "false"
        self.web_view.page().runJavaScript(f"window.setGoalButtonEnabled({enabled});")

    def _sync_token_usage_bubble_visibility_to_js(self, settings_override: dict | None = None):
        if not self._page_loaded:
            return
        source = settings_override if settings_override is not None else self.settings.config
        enabled = "true" if bool(source.get("show_token_usage_bubble", False)) else "false"
        self.web_view.page().runJavaScript(f"window.setTokenUsageBubbleEnabled({enabled});")

    def _set_mouse_tracking_enabled(self, enabled: bool):
        if enabled:
            self.mouse_tracking_timer.start()
            self._last_sent_mouse_pos = None
        else:
            self.mouse_tracking_timer.stop()
        self.settings.set("mouse_tracking_enabled", bool(enabled))
        self._sync_mouse_tracking_state_to_js()

    def _setup_webchannel(self):
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        print("QWebChannel initialized")

    def set_llm_client(self, llm_client):
        self.bridge.set_llm_client(llm_client)

    def send_voice_text(self, text: str):
        """PTT로 인식된 텍스트를 웹 채팅 전송 경로로 주입한다."""
        if not self._page_loaded:
            print("[Overlay] 음성 텍스트 전송 실패: 웹 페이지 미로딩")
            return
        payload = json.dumps(str(text or ""), ensure_ascii=False)
        self.web_view.page().runJavaScript(
            "(function(){"
            "if (typeof window.submitVoiceText === 'function') {"
            f"window.submitVoiceText({payload});"
            "}"
            "})();"
        )

    def show_toast(self, message: str, level: str = "info"):
        """웹 UI 토스트로 상태 메시지를 표시한다."""
        if not self._page_loaded:
            return
        msg = json.dumps(str(message or ""), ensure_ascii=False)
        lv = json.dumps(str(level or "info"), ensure_ascii=False)
        self.web_view.page().runJavaScript(
            "(function(){"
            "if (typeof window.showToast === 'function') {"
            f"window.showToast({msg}, {lv});"
            "}"
            "})();"
        )

    def toggle_mouse_tracking(self):
        new_enabled = not self.mouse_tracking_timer.isActive()
        self._set_mouse_tracking_enabled(new_enabled)
        self.settings.save()
        return new_enabled
