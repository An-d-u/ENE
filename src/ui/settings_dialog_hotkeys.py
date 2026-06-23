"""
설정 대화상자 PTT 단축키 캡처 mixin.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt

from ..core.hotkey_utils import hotkey_to_display, normalize_hotkey_text


class SettingsDialogHotkeyMixin:
    def _qt_key_to_hotkey_token(self, event) -> str:
        key = event.key()
        special_map = {
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Escape: "esc",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_Insert: "insert",
            Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end",
            Qt.Key.Key_PageUp: "page_up",
            Qt.Key.Key_PageDown: "page_down",
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Minus: "minus",
            Qt.Key.Key_Equal: "plus",
            Qt.Key.Key_Comma: "comma",
            Qt.Key.Key_Period: "period",
            Qt.Key.Key_Slash: "slash",
            Qt.Key.Key_Backslash: "backslash",
            Qt.Key.Key_Semicolon: "semicolon",
            Qt.Key.Key_Apostrophe: "quote",
            Qt.Key.Key_QuoteLeft: "backquote",
            Qt.Key.Key_BracketLeft: "left_bracket",
            Qt.Key.Key_BracketRight: "right_bracket",
            Qt.Key.Key_Control: "ctrl",
            Qt.Key.Key_Shift: "shift",
            Qt.Key.Key_Alt: "alt",
            Qt.Key.Key_Meta: "meta",
        }
        if key in special_map:
            return special_map[key]
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(ord("a") + (key - Qt.Key.Key_A))
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return chr(ord("0") + (key - Qt.Key.Key_0))
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
            return f"f{key - Qt.Key.Key_F1 + 1}"

        text = str(event.text() or "").strip().lower()
        if not text:
            return ""
        if text == "+":
            return "plus"
        if text == "-":
            return "minus"
        if text == ",":
            return "comma"
        if text == ".":
            return "period"
        if text == "/":
            return "slash"
        if text == "\\":
            return "backslash"
        if text == ";":
            return "semicolon"
        if text == "'":
            return "quote"
        if text == "`":
            return "backquote"
        if text == "[":
            return "left_bracket"
        if text == "]":
            return "right_bracket"
        if len(text) == 1 and text.isprintable():
            return text
        return ""

    def _build_hotkey_from_event(self, event) -> str:
        modifier_tokens: list[str] = []
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            modifier_tokens.append("ctrl")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            modifier_tokens.append("shift")
        if mods & Qt.KeyboardModifier.AltModifier:
            modifier_tokens.append("alt")
        if mods & Qt.KeyboardModifier.MetaModifier:
            modifier_tokens.append("meta")

        trigger = self._qt_key_to_hotkey_token(event)
        if not trigger:
            return ""
        modifier_tokens = [mod for mod in modifier_tokens if mod != trigger]

        ordered = [mod for mod in ("ctrl", "shift", "alt", "meta") if mod in modifier_tokens]
        if trigger not in ordered:
            ordered.append(trigger)
        return normalize_hotkey_text("+".join(ordered), default="alt")

    def _update_ptt_hotkey_ui(self):
        self.global_ptt_hotkey_value_label.setText(hotkey_to_display(self._ptt_hotkey_value, default="alt"))
        if self._capturing_ptt_hotkey:
            self.global_ptt_hotkey_set_button.setText(
                self._translated_text("settings.behavior.ptt.hotkey.waiting", "입력 대기 중...")
            )
            self.global_ptt_hotkey_hint_label.setText(
                self._translated_text(
                    "settings.behavior.ptt.hotkey.waiting_hint",
                    "설정할 키를 누르세요. Esc를 누르면 취소됩니다.",
                )
            )
        else:
            self.global_ptt_hotkey_set_button.setText(
                self._translated_text("settings.behavior.ptt.hotkey.set", "단축키 설정")
            )
            self.global_ptt_hotkey_hint_label.setText(
                self._translated_text(
                    "settings.behavior.ptt.hotkey.hint",
                    "누르고 있는 동안만 녹음됩니다.",
                )
            )

    def _start_ptt_hotkey_capture(self):
        if self._capturing_ptt_hotkey:
            return
        self._capturing_ptt_hotkey = True
        self._update_ptt_hotkey_ui()
        self.grabKeyboard()

    def _stop_ptt_hotkey_capture(self):
        if not self._capturing_ptt_hotkey:
            return
        self._capturing_ptt_hotkey = False
        self.releaseKeyboard()
        self._update_ptt_hotkey_ui()

    def _reset_ptt_hotkey(self):
        self._ptt_hotkey_value = normalize_hotkey_text("alt", default="alt")
        self._update_ptt_hotkey_ui()
        self._on_setting_changed()
