"""
Transparent overlay window for Live2D.
"""
import json
from pathlib import Path
import sys

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..ui.drag_bar import DragBar
from .bridge import WebBridge


class OverlayWindow(QWidget):
    """Transparent always-on-top overlay hosting the Live2D web view."""

    def __init__(self, settings_manager):
        super().__init__()
        self.settings = settings_manager
        self._page_loaded = False
        self._last_sent_mouse_pos = None
        self._mouse_send_min_delta = 2

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
        self._sync_mouse_tracking_state_to_js()
        self._sync_idle_motion_settings_to_js()
        self._sync_reroll_button_visibility_to_js()
        self._sync_manual_summary_button_visibility_to_js()
        print("Web page loaded")

    def _apply_model_settings(self):
        scale = self.settings.get("model_scale", 1.0)
        x_percent = self.settings.get("model_x_percent", 50)
        y_percent = self.settings.get("model_y_percent", 50)

        js_code = f"""
        (function() {{
            window.eneModelConfig = {{
                scale: {scale},
                xPercent: {x_percent},
                yPercent: {y_percent}
            }};

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
        if getattr(sys, "frozen", False):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path(__file__).parent.parent.parent
        return base_path / "assets" / "web" / "index.html"

    def _apply_settings(self):
        self.move(self.settings.get("window_x", 100), self.settings.get("window_y", 100))
        self.resize(self.settings.get("window_width", 400), self.settings.get("window_height", 600))
        self.web_view.setZoomFactor(self.settings.get("zoom_level", 1.0))
        self.drag_bar.setVisible(self.settings.get("show_drag_bar", True))

    def apply_new_settings(self, new_settings: dict):
        old_tracking = self.settings.get("mouse_tracking_enabled", True)
        new_tracking = new_settings.get("mouse_tracking_enabled", True)

        self.settings.update(new_settings)
        self._apply_settings()
        self._apply_model_settings()

        if old_tracking != new_tracking:
            self._set_mouse_tracking_enabled(new_tracking)

        self._sync_idle_motion_settings_to_js()
        self._sync_reroll_button_visibility_to_js()
        self._sync_manual_summary_button_visibility_to_js()
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

        scale = new_settings.get("model_scale", self.settings.get("model_scale", 1.0))
        x_percent = new_settings.get("model_x_percent", self.settings.get("model_x_percent", 50))
        y_percent = new_settings.get("model_y_percent", self.settings.get("model_y_percent", 50))
        js_code = f"""
        (function() {{
            window.eneModelConfig = {{
                scale: {scale},
                xPercent: {x_percent},
                yPercent: {y_percent}
            }};
            if (typeof window.applyENEModelSettings === 'function') {{
                window.applyENEModelSettings(window.eneModelConfig);
            }}
        }})();
        """
        self.web_view.page().runJavaScript(js_code)

        if self._page_loaded:
            self._sync_idle_motion_settings_to_js(new_settings)
            self._sync_reroll_button_visibility_to_js(new_settings)
            self._sync_manual_summary_button_visibility_to_js(new_settings)

    def restore_settings(self):
        self._apply_settings()
        self._apply_model_settings()
        self._sync_idle_motion_settings_to_js()
        self._sync_reroll_button_visibility_to_js()
        self._sync_manual_summary_button_visibility_to_js()

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
        self.settings.set("window_x", self.x())
        self.settings.set("window_y", self.y())
        self.settings.set("window_width", self.width())
        self.settings.set("window_height", self.height())
        self.settings.save()
        event.accept()

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
        strength = float(source.get("idle_motion_strength", 1.0))
        speed = float(source.get("idle_motion_speed", 1.0))
        dynamic_mode = "true" if bool(source.get("idle_motion_dynamic_mode", False)) else "false"
        head_pat_enabled = "true" if bool(source.get("enable_head_pat", True)) else "false"
        head_pat_strength = float(source.get("head_pat_strength", 1.0))
        head_pat_fade_in_ms = int(source.get("head_pat_fade_in_ms", 180))
        head_pat_fade_out_ms = int(source.get("head_pat_fade_out_ms", 220))
        active_custom = str(source.get("head_pat_active_emotion_custom", "")).strip()
        active_default = str(source.get("head_pat_active_emotion_default", "eyeclose")).strip() or "eyeclose"
        active_resolved = str(source.get("head_pat_active_emotion", "")).strip()
        head_pat_active_emotion = active_custom or active_resolved or active_default or "eyeclose"
        end_custom = str(source.get("head_pat_end_emotion_custom", "")).strip()
        end_default = str(source.get("head_pat_end_emotion_default", "shy")).strip() or "shy"
        end_resolved = str(source.get("head_pat_end_emotion", "")).strip()
        head_pat_end_emotion = end_custom or end_resolved or end_default or "shy"
        head_pat_duration_sec = int(source.get("head_pat_end_emotion_duration_sec", 5))

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
            "if (typeof window.setIdleMotionDynamic === 'function') {"
            f"window.setIdleMotionDynamic({dynamic_mode});"
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

    def _sync_manual_summary_button_visibility_to_js(self, settings_override: dict | None = None):
        if not self._page_loaded:
            return
        source = settings_override if settings_override is not None else self.settings.config
        enabled = "true" if bool(source.get("show_manual_summary_button", True)) else "false"
        self.web_view.page().runJavaScript(f"window.setManualSummaryButtonEnabled({enabled});")

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

    def toggle_mouse_tracking(self):
        new_enabled = not self.mouse_tracking_timer.isActive()
        self._set_mouse_tracking_enabled(new_enabled)
        self.settings.save()
        return new_enabled
