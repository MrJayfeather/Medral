from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QFrame, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt, QEasingCurve, QEvent, QRectF, QVariantAnimation
from PyQt6.QtGui import QKeyEvent, QColor, QPainter, QPainterPath, QPen

from i18n import tr
from ui.anim import glow, stagger
from ui.elide import ElideLabel


class SearchPanel(QWidget):
    search_submitted = pyqtSignal(str)
    play_requested   = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._build_ui()

    # ── layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText(tr("search_placeholder"))
        self._input.returnPressed.connect(self._on_submit)
        bar.addWidget(self._input, 1)

        self._btn = QPushButton(tr("search_button"))
        self._btn.setObjectName("searchBtn")
        self._btn.setFixedWidth(88)
        self._btn.clicked.connect(self._on_submit)
        bar.addWidget(self._btn)

        root.addLayout(bar)

        # Results live in a floating frameless Tool window (the QCompleter
        # approach): a plain child of the main window gets restacked under
        # the central widget, and inside the panel's layout five rows do not
        # fit above the player. A Tool window always stays on top of its
        # parent window and never fights the layout.
        self._results_widget = QFrame(
            self.window(),
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        self._results_widget.setObjectName("searchDropdown")
        self._results_widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._results_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._results_widget.setVisible(False)
        r_lay = QVBoxLayout(self._results_widget)
        r_lay.setContentsMargins(8, 8, 8, 8)
        r_lay.setSpacing(4)

        self._result_rows: list[_ResultRow] = []
        for _ in range(5):
            row = _ResultRow()
            row.play_clicked.connect(self._on_result_play)
            row.setVisible(False)
            r_lay.addWidget(row)
            self._result_rows.append(row)

        self._win_filter_installed = False
        # Esc in the input (or inside the dropdown) hides the results
        self._input.installEventFilter(self)
        self._results_widget.installEventFilter(self)

    # ── public ────────────────────────────────────────────────────────────

    def show_results(self, tracks: list[dict]) -> None:
        self._set_loading(False)
        if not tracks:
            self._results_widget.hide()
            return
        shown: list[_ResultRow] = []
        for i, row in enumerate(self._result_rows):
            if i < len(tracks):
                row.set_track(tracks[i])
                row.setVisible(True)
                shown.append(row)
            else:
                row.setVisible(False)

        win = self.window()
        if self._results_widget.parentWidget() is not win:
            self._results_widget.setParent(
                win, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            )
        if not self._win_filter_installed:
            win.installEventFilter(self)
            self._win_filter_installed = True
        self._position_dropdown()
        self._results_widget.show()
        self._results_widget.raise_()

        # Opacity-only cascade: rows are layout-managed, so animating
        # their pos fights the layout (rows stuck shifted/clipped after
        # a resize mid-animation — e.g. going fullscreen)
        stagger(shown, step_ms=55, ms=320, dy=0)

    def _position_dropdown(self) -> None:
        # The dropdown is a top-level Tool window — global coordinates
        top_left = self.mapToGlobal(self._input.geometry().bottomLeft())
        n = sum(1 for r in self._result_rows if r.isVisible())
        height = 16 + n * 54 + max(0, n - 1) * 4     # margins + rows + spacing
        self._results_widget.setGeometry(
            top_left.x(), top_left.y() + 8, self.width(), height
        )

    def eventFilter(self, obj, ev) -> bool:
        # Esc closes the results (unhandled keys from the row buttons bubble
        # up to the dropdown frame, so this covers focus inside it too)
        if (ev.type() == QEvent.Type.KeyPress
                and obj in (self._input, self._results_widget)
                and ev.key() == Qt.Key.Key_Escape
                and self._results_widget.isVisible()):
            self._results_widget.hide()
            return True
        if obj is self.window() and self._results_widget.isVisible():
            # Glued to the search bar while the window moves or resizes
            if ev.type() in (QEvent.Type.Resize, QEvent.Type.Move):
                self._position_dropdown()
            # A Tool window floats above OTHER apps too — hide it when the
            # main window is minimized or loses the foreground
            elif ev.type() in (QEvent.Type.WindowStateChange,
                               QEvent.Type.WindowDeactivate):
                if self.window().isMinimized() or not self.window().isActiveWindow():
                    self._results_widget.hide()
        return super().eventFilter(obj, ev)

    def hideEvent(self, ev) -> None:
        # e.g. switching to the settings page — the dropdown floats at
        # window level and would linger over it otherwise
        super().hideEvent(ev)
        self._results_widget.hide()

    def clear(self) -> None:
        self._input.clear()
        self._results_widget.hide()
        self._set_loading(False)

    def set_loading(self) -> None:
        self._set_loading(True)

    def reset_loading(self) -> None:
        """Re-enable input after a failed request (no results will arrive)."""
        self._set_loading(False)

    def _set_loading(self, loading: bool) -> None:
        # Only the button reflects loading — a disabled (greyed) input reads
        # as "the app froze" during slow searches
        self._btn.setText("…" if loading else tr("search_button"))
        self._btn.setEnabled(not loading)

    # ── slots ─────────────────────────────────────────────────────────────

    def _on_submit(self) -> None:
        q = self._input.text().strip()
        if not q:
            return
        if q.startswith("http://") or q.startswith("https://"):
            self.play_requested.emit(q)
            self.clear()
        else:
            self.search_submitted.emit(q)

    def _on_result_play(self, url: str) -> None:
        self.play_requested.emit(url)
        self.clear()


# ── result row widget ──────────────────────────────────────────────────────

class _GlowButton(QPushButton):
    """Push button with an accent glow while hovered and a vector play glyph.

    The "▶" character renders as a colored emoji on Windows and ignores QSS
    color, so the triangle is painted by hand on top of the styled frame.
    """

    def enterEvent(self, ev) -> None:
        glow(self, blur=18)
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        if self.graphicsEffect() is not None:
            self.setGraphicsEffect(None)
        super().leaveEvent(ev)

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)   # QSS background + border
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#A78BFA") if self.underMouse() else QColor("#6C63FF")
        w, h = self.width(), self.height()
        s = 10.0                       # triangle size in px
        cx, cy = w / 2 + 0.8, h / 2    # slight optical shift to the right
        path = QPainterPath()
        path.moveTo(cx - s * 0.42, cy - s * 0.55)
        path.lineTo(cx + s * 0.58, cy)
        path.lineTo(cx - s * 0.42, cy + s * 0.55)
        path.closeSubpath()
        p.setPen(QPen(color, 2.4, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(color)
        p.drawPath(path)
        p.end()


class _ResultRow(QFrame):
    play_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("searchResultRow")
        # frame background is painted here (animated hover) — mute the QSS one
        self.setStyleSheet(
            "QFrame#searchResultRow { background: transparent; border: none; }"
        )
        self._url = ""
        self._hover = 0.0
        self.setFixedHeight(54)   # rows must not stretch with the panel
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(150)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_tick)
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        info = QVBoxLayout()
        info.setSpacing(2)

        # labels shrink with the row (elided dynamically) instead of
        # pushing the play button past the panel edge in narrow windows
        self._title = ElideLabel()
        self._title.setStyleSheet(
            "font-size:13px; font-weight:600; color:#e8e8f5; background:transparent;"
        )
        info.addWidget(self._title)

        self._meta = ElideLabel()
        self._meta.setStyleSheet("font-size:11px; color:#6b6b8a; background:transparent;")
        info.addWidget(self._meta)

        lay.addLayout(info, 1)

        btn = _GlowButton("")   # glyph is painted, not a text character
        btn.setObjectName("resultPlayBtn")
        btn.setFixedSize(32, 32)
        btn.setToolTip(tr("add_to_queue_tip"))
        btn.clicked.connect(lambda: self.play_clicked.emit(self._url))
        # stretch 0 — the button keeps its fixed 32x32 and is never squeezed
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_track(self, track: dict) -> None:
        self._url = track.get("webpage_url", "")
        title  = str(track.get("title") or tr("unknown_title"))
        artist = str(track.get("artist") or tr("unknown_artist"))
        dur    = int(track.get("duration") or 0)
        m, s   = divmod(dur, 60)

        self._title.setText(title)
        meta = f"{artist}  •  {m}:{s:02d}"
        # Non-YouTube results are labelled with their source
        source = track.get("source")
        if source == "soundcloud":
            meta += "  •  SoundCloud"
        elif source == "spotify":
            meta += "  •  Spotify"
        self._meta.setText(meta)

    # ── animated hover ────────────────────────────────────────────────────

    def _on_hover_tick(self, v) -> None:
        self._hover = float(v)
        self.update()

    def _animate_hover(self, end: float) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(end)
        self._hover_anim.start()

    def enterEvent(self, ev) -> None:
        self._animate_hover(1.0)
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._animate_hover(0.0)
        super().leaveEvent(ev)

    def paintEvent(self, ev) -> None:
        # SURFACE2 → SURFACE2 + 7% accent tint, border fades in with hover
        t = self._hover
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = QColor(22 + round(6 * t), 22 + round(5 * t), 42 + round(15 * t))
        border = QColor(0x6C, 0x63, 0xFF)
        border.setAlphaF(t)
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(rect, 12.0, 12.0)
