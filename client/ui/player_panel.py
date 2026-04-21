import math
import random
import time

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl, QPointF, QRect
from PyQt6.QtGui import (
    QPixmap, QPainter, QPainterPath, QColor, QLinearGradient, QRadialGradient,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply


def _fmt(seconds: int) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _rounded_pixmap(px: QPixmap, r: int = 12) -> QPixmap:
    out = QPixmap(px.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(px.width()), float(px.height()), r, r)
    p.setClipPath(path)
    p.drawPixmap(0, 0, px)
    p.end()
    return out


class _EqWidget(QWidget):
    """18-bar animated equalizer visualizer."""

    _N = 18

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(36)
        self._active  = False
        self._heights = [0.05] * self._N
        self._targets = [0.05] * self._N

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._timer.start()
        else:
            self._timer.stop()
            self._heights = [0.05] * self._N
            self.update()

    def _tick(self) -> None:
        for i in range(self._N):
            self._targets[i] = random.uniform(0.08, 1.0)
            self._heights[i] += (self._targets[i] - self._heights[i]) * 0.35
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        n = self._N
        gap = 2
        bar_w = max(2, (w - gap * (n - 1)) // n)
        total_w = n * bar_w + gap * (n - 1)
        x0 = (w - total_w) // 2

        for i in range(n):
            bh = max(3, int(self._heights[i] * (h - 2)))
            x = x0 + i * (bar_w + gap)
            y = h - bh

            grad = QLinearGradient(x, y, x, h)
            grad.setColorAt(0.0, QColor(108, 99, 255, 220))
            grad.setColorAt(1.0, QColor(167, 139, 250, 100))
            p.fillRect(x, y, bar_w, bh, grad)

        p.end()


class PlayerPanel(QFrame):
    play_pause_clicked = pyqtSignal()
    skip_clicked       = pyqtSignal()
    previous_clicked   = pyqtSignal()
    volume_changed     = pyqtSignal(float)
    seek_requested     = pyqtSignal(float)

    _ART_SIZE = 150

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("playerCard")

        self._is_playing   = False
        self._is_paused    = False
        self._duration     = 0
        self._position     = 0.0
        self._seeking      = False
        self._thumb_url    = ""
        self._seek_timer   = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self._do_seek)

        self._nam = QNetworkAccessManager(self)
        self._nam.finished.connect(self._on_image_loaded)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(500)
        self._tick_timer.timeout.connect(self._tick)

        self._build_ui()
        self._reset()

    # ── layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        # ── track info row ──
        info_row = QHBoxLayout()
        info_row.setSpacing(20)

        self._art = QLabel()
        self._art.setFixedSize(self._ART_SIZE, self._ART_SIZE)
        self._art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 #16162a, stop:1 #0e0e1a);"
            f" border-radius:12px; font-size:40px; color:#6b6b8a;"
        )
        info_row.addWidget(self._art)

        meta = QVBoxLayout()
        meta.setSpacing(6)
        meta.addStretch()

        self._title = QLabel("Nothing playing")
        self._title.setObjectName("trackTitle")
        self._title.setWordWrap(True)
        self._title.setMaximumWidth(420)
        meta.addWidget(self._title)

        self._artist = QLabel("")
        self._artist.setObjectName("trackArtist")
        meta.addWidget(self._artist)

        meta.addSpacing(10)

        self._eq = _EqWidget()
        meta.addWidget(self._eq)

        meta.addStretch()
        info_row.addLayout(meta, 1)
        root.addLayout(info_row)

        # ── progress ──
        prog_wrap = QVBoxLayout()
        prog_wrap.setSpacing(4)

        self._progress = QSlider(Qt.Orientation.Horizontal)
        self._progress.setRange(0, 1000)
        self._progress.setValue(0)
        self._progress.sliderPressed.connect(self._on_seek_press)
        self._progress.sliderReleased.connect(self._on_seek_release)
        prog_wrap.addWidget(self._progress)

        times = QHBoxLayout()
        self._elapsed = QLabel("0:00")
        self._elapsed.setObjectName("timeLabel")
        self._total = QLabel("0:00")
        self._total.setObjectName("timeLabel")
        self._total.setAlignment(Qt.AlignmentFlag.AlignRight)
        times.addWidget(self._elapsed)
        times.addStretch()
        times.addWidget(self._total)
        prog_wrap.addLayout(times)
        root.addLayout(prog_wrap)

        # ── transport ──
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        ctrl.addStretch()

        self._prev_btn = _TransportButton("⏮", "Previous")
        self._prev_btn.clicked.connect(self.previous_clicked)
        ctrl.addWidget(self._prev_btn)

        self._play_btn = QPushButton("▶")
        self._play_btn.setObjectName("playBtn")
        self._play_btn.setFixedSize(48, 48)
        self._play_btn.setToolTip("Play / Pause")
        self._play_btn.clicked.connect(self.play_pause_clicked)
        ctrl.addWidget(self._play_btn)

        self._skip_btn = _TransportButton("⏭", "Skip")
        self._skip_btn.clicked.connect(self.skip_clicked)
        ctrl.addWidget(self._skip_btn)

        ctrl.addStretch()

        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet("background:transparent; font-size:15px;")
        ctrl.addWidget(vol_icon)

        self._vol = QSlider(Qt.Orientation.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(50)
        self._vol.setFixedWidth(96)
        self._vol.setToolTip("Volume")
        self._vol.valueChanged.connect(lambda v: self.volume_changed.emit(v / 100.0))
        ctrl.addWidget(self._vol)

        root.addLayout(ctrl)

    # ── public ────────────────────────────────────────────────────────────

    def update_state(self, state: dict) -> None:
        current = state.get("current")

        if not current:
            self._reset()
            return

        title    = current.get("title",  "Unknown")
        artist   = current.get("artist", "Unknown")
        duration = int(current.get("duration") or 0)
        thumb    = current.get("thumbnail", "") or ""

        self._title.setText(title)
        self._artist.setText(artist)
        self._duration = duration
        self._total.setText(_fmt(duration))

        if thumb and thumb != self._thumb_url:
            self._thumb_url = thumb
            self._nam.get(QNetworkRequest(QUrl(thumb)))

        self._is_playing = state.get("is_playing", False)
        self._is_paused  = state.get("is_paused",  False)
        self._play_btn.setText("⏸" if self._is_playing else "▶")
        self._eq.set_active(self._is_playing and not self._is_paused)

        pos = float(state.get("position") or 0.0)
        self._position = pos
        if not self._seeking and self._duration > 0:
            self._progress.setValue(int(pos / self._duration * 1000))
        self._elapsed.setText(_fmt(pos))

        if not self._vol.isSliderDown():
            v = int(state.get("volume", 0.5) * 100)
            self._vol.blockSignals(True)
            self._vol.setValue(v)
            self._vol.blockSignals(False)

        if self._is_playing:
            self._tick_timer.start()
        else:
            self._tick_timer.stop()

    # ── private ───────────────────────────────────────────────────────────

    def _reset(self) -> None:
        self._is_playing = False
        self._is_paused  = False
        self._duration   = 0
        self._position   = 0.0
        self._thumb_url  = ""
        self._title.setText("Nothing playing")
        self._artist.setText("")
        self._total.setText("0:00")
        self._elapsed.setText("0:00")
        self._progress.setValue(0)
        self._play_btn.setText("▶")
        self._art.clear()
        self._art.setText("♪")
        self._art.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 #16162a, stop:1 #0e0e1a);"
            f" border-radius:12px; font-size:40px; color:#6b6b8a;"
        )
        self._eq.set_active(False)
        self._tick_timer.stop()

    def _tick(self) -> None:
        if not self._is_playing or self._seeking or self._duration <= 0:
            return
        self._position = min(self._position + 0.5, self._duration)
        self._progress.setValue(int(self._position / self._duration * 1000))
        self._elapsed.setText(_fmt(self._position))

    def _on_seek_press(self) -> None:
        self._seeking = True
        self._seek_timer.stop()

    def _on_seek_release(self) -> None:
        if self._duration > 0:
            self._position = self._progress.value() / 1000 * self._duration
            self._elapsed.setText(_fmt(self._position))
            self._seek_timer.start(300)

    def _do_seek(self) -> None:
        self.seek_requested.emit(self._position)
        QTimer.singleShot(2500, self._end_seek_lock)

    def _end_seek_lock(self) -> None:
        self._seeking = False

    def _on_image_loaded(self, reply: QNetworkReply) -> None:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            reply.deleteLater()
            return
        data = reply.readAll()
        px = QPixmap()
        if px.loadFromData(data):
            s = self._ART_SIZE
            px = px.scaled(s, s,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
            x = (px.width()  - s) // 2
            y = (px.height() - s) // 2
            px = px.copy(x, y, s, s)
            px = _rounded_pixmap(px, r=12)
            self._art.setPixmap(px)
            self._art.setStyleSheet("background:transparent;")
        reply.deleteLater()


class _TransportButton(QPushButton):
    def __init__(self, icon: str, tip: str, parent=None) -> None:
        super().__init__(icon, parent)
        self.setObjectName("transportBtn")
        self.setFixedSize(40, 40)
        self.setToolTip(tip)
