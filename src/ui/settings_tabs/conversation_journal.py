"""실제 대화 기록을 날짜·시간대별로 살펴보는 설정 패널."""

from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import QDate, QLocale, QRectF, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QBoxLayout, QDateEdit, QFrame, QHBoxLayout, QLabel, QScrollArea,
    QToolTip, QVBoxLayout, QWidget,
)


def _mix(base: QColor, ink: QColor, weight: float) -> QColor:
    return QColor.fromRgbF(
        *(a + (b - a) * weight for a, b in zip(base.getRgbF()[:3], ink.getRgbF()[:3]))
    )


class YearCalendar(QWidget):
    """월요일에 시작하는 주를 한 열씩 배치한 고정 연간 달력."""

    picked = pyqtSignal(object)
    top = 22
    row_height = 13

    def __init__(self, journal):
        super().__init__()
        self.journal = journal
        self.setFixedHeight(self.top + 7 * self.row_height + 2)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_year(self, year):
        self.first = date(year, 1, 1)
        self.last = date(year, 12, 31)
        self.leading = self.first.weekday()
        self.columns = (self.leading + (self.last - self.first).days) // 7 + 1

    def day_rect(self, day):
        column, row = divmod(self.leading + (day - self.first).days, 7)
        step = (self.width() - 4) / self.columns
        gap = 2 if step >= 9 else 1
        return QRectF(2 + column * step, self.top + row * self.row_height,
                      max(1, step - gap), self.row_height - 2)

    def paintEvent(self, event):
        if self.journal.stats is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(self.journal.ink)
        locale = self.journal.locale()
        # 칸 너비가 좁으면 모든 달의 위치를 유지하면서 월 숫자만 표시한다.
        for month in range(1, 13):
            bounds = self.day_rect(date(self.first.year, month, 1))
            text = locale.standaloneMonthName(month, QLocale.FormatType.ShortFormat)
            if self.width() < 470:
                text = str(month)
            width = p.fontMetrics().horizontalAdvance(text) + 1
            x = self.width() - width - 2 if month == 12 else bounds.left()
            p.drawText(QRectF(x, 0, width, self.top - 2), Qt.AlignmentFlag.AlignLeft, text)
        p.setPen(Qt.PenStyle.NoPen)
        stats = self.journal.stats
        for offset in range((self.last - self.first).days + 1):
            day = self.first + timedelta(days=offset)
            count = stats.daily_turns.get(day, 0)
            level = min(4, (count + 4) // 5)
            brush = self.journal.future_brush if day > stats.as_of else self.journal.levels[level]
            p.setBrush(brush)
            p.drawRoundedRect(self.day_rect(day), 1.5, 1.5)
        p.setPen(QPen(self.journal.ink, 2 if self.hasFocus() else 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(self.day_rect(self.journal.picker.date().toPyDate()).adjusted(-.6, -.6, .6, .6), 2, 2)

    def _day_at(self, position):
        step = (self.width() - 4) / self.columns
        column = int((position.x() - 2) // step)
        row = int((position.y() - self.top) // self.row_height)
        if 0 <= column < self.columns and 0 <= row < 7:
            offset = column * 7 + row - self.leading
            if 0 <= offset <= (self.last - self.first).days:
                return self.first + timedelta(days=offset)
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.journal.stats:
            day = self._day_at(event.position())
            if day:
                self.picked.emit(day)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.journal.stats:
            day = self._day_at(event.position())
            if day:
                QToolTip.showText(event.globalPosition().toPoint(),
                                  f"{day} · {self.journal.describe_day(day)}", self)
            else:
                QToolTip.hideText()

    def keyPressEvent(self, event):
        offsets = {Qt.Key.Key_Left: -7, Qt.Key.Key_Right: 7, Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}
        if self.journal.stats and event.key() in offsets:
            day = self.journal.picker.date().toPyDate() + timedelta(days=offsets[event.key()])
            self.picked.emit(max(self.first, min(day, self.last)))
            event.accept()
            return
        super().keyPressEvent(event)


class HourChart(QWidget):
    def __init__(self, journal):
        super().__init__()
        self.journal = journal
        self.setFixedHeight(83)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        stats = self.journal.stats
        if stats is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        baseline = self.height() - 23
        step = self.width() / 24
        peak = max(stats.hourly_turns)
        p.setPen(self.journal.levels[0])
        p.drawLine(0, baseline // 2, self.width(), baseline // 2)
        p.setPen(Qt.PenStyle.NoPen)
        for hour, count in enumerate(stats.hourly_turns):
            if count:
                p.setBrush(self.journal.levels[4] if count == peak else self.journal.neutral)
                height = max(1, (baseline - 2) * count / peak)
                p.drawRoundedRect(QRectF(hour * step + 1, baseline - height, step - 2, height), 1.5, 1.5)
        p.setPen(self.journal.ink)
        p.drawLine(0, baseline, self.width(), baseline)
        for hour in (0, 6, 12, 18, 23):
            text = f"{hour:02d}"
            x = min(hour * step, self.width() - p.fontMetrics().horizontalAdvance(text) - 1)
            p.drawText(QRectF(x, baseline + 3, step + 12, 19), Qt.AlignmentFlag.AlignLeft, text)

    def mouseMoveEvent(self, event):
        if self.journal.stats:
            hour = max(0, min(23, int(event.position().x() * 24 / self.width())))
            QToolTip.showText(event.globalPosition().toPoint(), self.journal.hour_detail(hour), self)


class ScaleKey(QWidget):
    def __init__(self, journal, future=False):
        super().__init__()
        self.journal = journal
        self.future = future
        self.setFixedSize(10 if future else 57, 12)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        colors = [self.journal.future_brush] if self.future else self.journal.levels
        for i, color in enumerate(colors):
            p.setBrush(color)
            p.drawRoundedRect(QRectF(i * 11.5, 1, 9, 9), 1.5, 1.5)


def _label(name):
    label = QLabel()
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class Metric(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.caption = _label("JournalCaption")
        self.value = _label("JournalValue")
        self.detail = _label("JournalDetail")
        for label in (self.caption, self.value, self.detail):
            layout.addWidget(label)
        layout.addStretch()


class ConversationJournal(QScrollArea):
    def __init__(self, dialog, load_activity):
        super().__init__()
        self.dialog = dialog
        self.load_activity = load_activity
        self.stats = None
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("ConversationJournal")
        page = QWidget()
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page.setObjectName("JournalPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)
        self.setWidget(page)

        self.title, self.as_of = self._heading(layout, "JournalTitle")
        self.source = _label("JournalDetail")
        layout.addWidget(self.source)
        self.first, self.turns, self.characters = Metric(), Metric(), Metric()
        self.ledger = self._metrics(layout, [self.first, self.turns, self.characters])
        self.days, self.active_days = self._heading(layout)
        self.calendar = YearCalendar(self)
        layout.addWidget(self.calendar)
        self.picker = QDateEdit()
        self.picker.setCalendarPopup(True)
        self.picker.setDisplayFormat("yyyy-MM-dd")
        self.readout = _label("JournalDetail")
        self.calendar.picked.connect(lambda day: self.picker.setDate(QDate(day.year, day.month, day.day)))
        self.picker.dateChanged.connect(self._update_readout)
        self.foot = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        selection = QHBoxLayout()
        selection.addWidget(self.picker)
        selection.addWidget(self.readout, 1)
        self.foot.addLayout(selection, 1)
        legend = QHBoxLayout()
        legend.setSpacing(4)
        self.less, self.more, self.future = (_label("JournalDetail") for _ in range(3))
        self.scale = ScaleKey(self)
        self.future_key = ScaleKey(self, future=True)
        for label in (self.less, self.scale, self.more, self.future_key, self.future):
            legend.addWidget(label)
        legend.addStretch()
        self.foot.addLayout(legend)
        layout.addLayout(self.foot)
        self.hours_title, self.hours_note = self._heading(layout)
        self.hours = HourChart(self)
        self.peak_note = _label("JournalDetail")
        layout.addWidget(self.hours)
        layout.addWidget(self.peak_note)
        self.records, _ = self._heading(layout)
        self.longest, self.streak = Metric(), Metric()
        self.record_row = self._metrics(layout, [self.longest, self.streak])
        layout.addStretch()
        self.apply_theme(getattr(dialog, "_theme_values", {}))
        self.retranslate_ui()

    def _heading(self, layout, name="JournalHeading"):
        row = QHBoxLayout()
        row.setContentsMargins(0, 7, 0, 0)
        title = _label(name)
        note = _label("JournalDetail")
        note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(title, 1)
        row.addWidget(note, 1)
        layout.addLayout(row)
        rule = QFrame()
        rule.setObjectName("JournalRule")
        rule.setFixedHeight(2 if name == "JournalTitle" else 1)
        layout.addWidget(rule)
        return title, note

    @staticmethod
    def _metrics(layout, metrics):
        row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        row.setContentsMargins(0, 4, 0, 3)
        row.setSpacing(16)
        for metric in metrics:
            row.addWidget(metric, 1)
        layout.addLayout(row)
        return row

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "record_row"):
            direction = (QBoxLayout.Direction.TopToBottom if self.viewport().width() < 460
                         else QBoxLayout.Direction.LeftToRight)
            for row in (self.ledger, self.foot, self.record_row):
                row.setDirection(direction)

    def apply_theme(self, values):
        panel = QColor(values.get("settings_card_bg_color", "#FFFFFF"))
        self.ink = QColor("#f4f1f6" if panel.lightnessF() < .55 else "#27232b")
        accent = QColor(values.get("theme_accent_color", "#87548e"))
        self.levels = [_mix(panel, self.ink, .13)] + [_mix(panel, accent, w) for w in (.28, .52, .76, 1)]
        self.neutral = _mix(panel, self.ink, .46)
        self.future_brush = QBrush(_mix(panel, self.ink, .30), Qt.BrushStyle.BDiagPattern)
        muted = _mix(panel, self.ink, .73).name()
        self.setStyleSheet(f"""
            QScrollArea#ConversationJournal {{ border: none; background: transparent; }}
            QWidget#JournalPage {{ background-color: {panel.name()}; }}
            QLabel#JournalTitle {{ color: {self.ink.name()}; font-size: 28px; font-weight: 750; }}
            QLabel#JournalHeading {{ color: {self.ink.name()}; font-size: 17px; font-weight: 700; }}
            QLabel#JournalCaption {{ color: {muted}; font-size: 12px; font-weight: 650; }}
            QLabel#JournalValue {{ color: {self.ink.name()}; font-size: 21px; font-weight: 700; }}
            QLabel#JournalDetail {{ color: {muted}; font-size: 12px; }}
            QFrame#JournalRule {{ background-color: {self.ink.name()}; border: none; }}
        """)
        for chart in (self.calendar, self.hours, self.scale, self.future_key):
            chart.update()

    def _text(self, key, fallback, **values):
        tr = getattr(self.dialog, "_translated_text", None)
        template = tr("settings.memory." + key, fallback) if tr else fallback
        return template.format(**values)

    def retranslate_ui(self):
        language = getattr(getattr(self.dialog, "_dialog_i18n", None), "language", "ko")
        self.setLocale(QLocale(language))
        for label, key, fallback in (
            (self.title, "tabs.together", "함께한 시간"),
            (self.source, "journal.source", "보관된 대화와 현재 대화 중 질문·답변과 시각을 확인할 수 있는 기록을 집계합니다."),
            (self.first.caption, "journal.first", "처음 대화한 날"),
            (self.turns.caption, "journal.exchanges", "주고받은 대화"),
            (self.turns.detail, "journal.turns_hint", "질문과 답변 한 쌍이 1턴"),
            (self.characters.caption, "journal.writing", "함께 쓴 글"),
            (self.characters.detail, "journal.characters_hint", "질문과 답변을 합친 글자 수"),
            (self.days, "journal.days", "만난 날들"), (self.less, "journal.less", "적음"),
            (self.more, "journal.more", "많음"), (self.future, "journal.future", "집계 전"),
            (self.hours_title, "journal.hours", "주로 만난 시간"), (self.hours_note, "journal.hourly", "시간대별 대화 횟수"),
            (self.records, "journal.records", "기록"), (self.longest.caption, "journal.longest", "가장 긴 대화"),
            (self.streak.caption, "journal.streak", "최장 연속 대화"),
        ):
            label.setText(self._text(key, fallback))
        self.picker.setAccessibleName(self._text("journal.date_picker", "확인할 날짜"))
        self.hours.setAccessibleName(self.hours_note.text())
        if self.stats:
            self._render_stats()

    def showEvent(self, event):
        super().showEvent(event)
        previous = self.picker.date().toPyDate() if self.stats else None
        self.stats = self.load_activity()
        year = self.stats.as_of.year
        self.calendar.set_year(year)
        days = {d: n for d, n in self.stats.daily_turns.items() if d.year == year and n}
        self.peak_day = min(days, key=lambda d: (-days[d], d)) if days else None
        selected = previous if previous and previous.year == year else self.peak_day or self.stats.as_of
        with QSignalBlocker(self.picker):
            self.picker.setDateRange(QDate(year, 1, 1), QDate(year, 12, 31))
            self.picker.setDate(QDate(selected.year, selected.month, selected.day))
        self._render_stats()

    def _turns(self, n):
        return self._text("journal.turns", "{count}턴", count=self.locale().toString(n))

    def _render_stats(self):
        s = self.stats
        year = s.as_of.year
        self.as_of.setText(self._text("journal.as_of", "{date} 기준", date=s.as_of))
        self.first.value.setText(str(s.first_day) if s.first_day else "—")
        self.first.detail.setText(self._text("journal.since", "{count}일째", count=(s.as_of - s.first_day).days + 1)
                                  if s.first_day else "")
        self.turns.value.setText(self._turns(s.total_turns))
        self.characters.value.setText(self._text("journal.characters", "{count}자", count=self.locale().toString(s.characters)))
        count = sum(d.year == year and n > 0 for d, n in s.daily_turns.items())
        self.active_days.setText(self._text("journal.active_days", "{year}년 대화한 날 {count}일", year=year, count=count))
        self.calendar.setAccessibleName(self._text(
            "journal.calendar", "{year}년 날짜별 대화. 1월부터 12월까지 각 열은 월요일부터 일요일 순서입니다.", year=year))
        self.hours.setAccessibleDescription(", ".join(self.hour_detail(h) for h in range(24)))
        n = max(s.hourly_turns)
        if n:
            h = s.hourly_turns.index(n)
            self.peak_note.setText(self._text("journal.peak", "가장 많이 대화한 시간은 {hour}–{end}시로, 총 {turns}을 주고받았어요.",
                                              hour=f"{h:02d}", end=f"{(h + 1) % 24:02d}", turns=self._turns(n)))
        else:
            self.peak_note.setText(self._text("journal.empty", "아직 집계할 대화 기록이 없습니다."))
        session = s.longest
        duration = "—"
        detail = ""
        if session:
            duration = (self._text("journal.minutes", "{count}분", count=session.minutes) if session.minutes
                        else self._text("journal.short_session", "1분 미만"))
            detail = self._text("journal.started", "{date} {time} 시작 · {turns}", date=session.started_at.date(),
                                time=session.started_at.strftime("%H:%M"), turns=self._turns(session.turns))
        self.longest.value.setText(duration)
        self.longest.detail.setText(detail)
        self.streak.value.setText(self._text("journal.day_count", "{count}일", count=s.streak_days) if s.streak_days else "—")
        self.streak.detail.setText(f"{s.streak_start} – {s.streak_end}" if s.streak_days else "")
        self.hours.update()
        self._update_readout()

    def hour_detail(self, hour):
        return f"{hour:02d}:00 · {self._turns(self.stats.hourly_turns[hour])}"

    def describe_day(self, day):
        if day > self.stats.as_of:
            return self.future.text()
        if self.stats.first_day and day < self.stats.first_day:
            return self._text("journal.before", "첫 대화 전")
        turns = self._turns(self.stats.daily_turns.get(day, 0))
        if day == self.peak_day:
            return self._text("journal.busiest", "{turns} · 가장 많이 대화한 날", turns=turns)
        return turns

    def _update_readout(self):
        day = self.picker.date().toPyDate()
        self.readout.setText(self.describe_day(day))
        self.picker.setAccessibleDescription(self.readout.text())
        self.calendar.setAccessibleDescription(f"{day} · {self.readout.text()}")
        self.calendar.update()
