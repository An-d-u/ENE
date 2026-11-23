"""설정 하위 탭과 현재 보이는 그룹으로 이동하는 메뉴."""

from PyQt6.QtCore import QEvent, QPoint
from PyQt6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)


def section_group(dialog, key, title, layout_type):
    group = QGroupBox()
    dialog._bind_group_title(group, "settings.sections." + key, title)
    layout = layout_type(group)
    layout.setSpacing(8)
    return group, layout


def scroll_page(content):
    for form in content.findChildren(QFormLayout):
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(content)
    return scroll


def group_page(*groups):
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(12)
    for group in groups:
        layout.addWidget(group)
    layout.addStretch()
    return scroll_page(content)


class _GroupJump(QWidget):
    def __init__(self, parent, dialog, pages, minimum):
        super().__init__(parent)
        self._minimum = minimum
        self._scroll = pages[0]
        self._groups = {
            page: [
                widget for widget in page.widget().findChildren(QWidget)
                if isinstance(widget, QGroupBox) or (isinstance(widget, QLabel) and widget.property("settingsJumpTitle"))
            ]
            for page in pages
        }
        self._choices = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addStretch()
        label = QLabel()
        self._combo = QComboBox()
        self._combo.setObjectName("settingsGroupJump")
        self._combo.setMaximumWidth(190)
        label.setBuddy(self._combo)
        dialog._bind_widget_text(label, "settings.sections.jump", "그룹 이동")
        dialog._register_text_binding(self._combo.setAccessibleName, "settings.sections.jump", "그룹 이동")
        row.addWidget(label)
        row.addWidget(self._combo)
        self._combo.activated.connect(self._jump)
        for page, groups in self._groups.items():
            watched = set()
            for group in groups:
                parent = group
                while parent is not page.widget() and parent not in watched:
                    parent.installEventFilter(self)
                    watched.add(parent)
                    parent = parent.parentWidget()
        dialog._register_text_binding(self._translate, "settings.sections.choose_group", "그룹 선택")

    def _translate(self, placeholder):
        self._combo.setPlaceholderText(placeholder)
        self._refresh()

    def set_page(self, page):
        self._scroll = page
        page.verticalScrollBar().setValue(0)
        self._refresh()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.ShowToParent, QEvent.Type.HideToParent):
            self._refresh()
        return super().eventFilter(watched, event)

    def _refresh(self):
        content = self._scroll.widget()
        self._choices = [group for group in self._groups[self._scroll] if group.isVisibleTo(content)]
        self._combo.clear()
        self._combo.addItems([
            group.title() if isinstance(group, QGroupBox) else group.text()
            for group in self._choices
        ])
        self._combo.setCurrentIndex(-1)
        self.setVisible(len(self._choices) >= self._minimum)

    def _jump(self, index):
        if 0 <= index < len(self._choices):
            group = self._choices[index]
            top = group.mapTo(self._scroll.widget(), QPoint(0, 0)).y()
            self._scroll.verticalScrollBar().setValue(top)
        self._combo.setCurrentIndex(-1)


def add_group_navigation(dialog, scroll, *, minimum=2):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(_GroupJump(page, dialog, [scroll], minimum))
    layout.addWidget(scroll, 1)
    return page


def section_tabs(dialog, name, sections):
    tabs = QTabWidget()
    tabs.setObjectName(name + "SectionTabs")
    tabs.setDocumentMode(True)
    tabs.setUsesScrollButtons(True)
    pages = []
    for key, title, page in sections:
        index = tabs.addTab(page, title)
        dialog._register_text_binding(lambda text, i=index: tabs.setTabText(i, text), key, title)
        pages.append(page)
    jump = _GroupJump(tabs, dialog, pages, minimum=4)
    tabs.setCornerWidget(jump)
    tabs.currentChanged.connect(lambda i: jump.set_page(tabs.widget(i)))
    return tabs
