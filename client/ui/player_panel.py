import math
import random
import time

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget,
    QStyle, QToolTip, QGraphicsOpacityEffect,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QUrl, QPointF, QRect, QRectF, QSize,
    QEasingCurve, QPropertyAnimation, QVariantAnimation,
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QPainterPath, QColor, QLinearGradient, QRadialGradient,
    QBrush, QFont,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from ui.anim import glow


def _fmt(seconds: int) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _window_minimized(w: QWidget) -> bool:
    return bool(w.window().windowState() & Qt.WindowState.WindowMinimized)


class _SeekSlider(QSlider):
    """Progress slider with hover timestamps and click-to-jump.

    A plain click anywhere on the track moves the handle there and starts
    the normal press→release seek flow; hovering shows the time at the
    cursor as a tooltip.
    """

    def __init__(self, orientation, duration_provider, parent=None) -> None:
        super().__init__(orientation, parent)
        self._duration_provider = duration_provider
        self.setMouseTracking(True)

    def _value_at(self, x: float) -> int:
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), int(x), max(1, self.width())
        )

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            # Move the handle under the cursor first, then let the normal
            # press grab it — a click seeks, dragging still works.
            self.setSliderPosition(self._value_at(ev.position().x()))
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        duration = self._duration_provider()
        if duration > 0:
            secs = self._value_at(ev.position().x()) / max(1, self.maximum()) * duration
            QToolTip.showText(ev.globalPosition().toPoint(), _fmt(secs), self)
        super().mouseMoveEvent(ev)


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


_LOOP_ORDER = ["none", "all", "one"]        # click cycle: none → all → one → none
_LOOP_ICONS = {"none": "🔁︎", "all": "🔁︎", "one": "🔂︎"}
_LOOP_TIPS  = {"none": "Loop: off", "all": "Loop: queue", "one": "Loop: track"}
_LOOP_ACTIVE_QSS = (
    "QPushButton { color:#6C63FF; background-color:rgba(108,99,255,0.18);"
    " border:none; border-radius:20px; font-size:18px; }"
    "QPushButton:hover { background-color:rgba(108,99,255,0.30); }"
    "QPushButton:pressed { background-color:rgba(108,99,255,0.40); }"
)


class _MarqueeLabel(QLabel):
    """QLabel drop-in that scrolls its text when it does not fit.

    Back-and-forth marquee: 2 s pause at each edge, smooth scroll between.
    The timer runs only while scrolling is needed and the widget is visible.
    """

    _SPEED   = 40.0      # px per second
    _PAUSE   = 2.0       # seconds at each edge
    _TICK_MS = 30

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._off   = 0.0
        self._phase = 0          # 0 pause-left, 1 →right, 2 pause-right, 3 →left
        self._t0    = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._tick_marquee)

    def setText(self, text: str) -> None:
        if text == self.text():
            return               # frequent state updates must not reset scroll
        super().setText(text)
        self._restart()

    def minimumSizeHint(self) -> QSize:
        # never force the layout wider than the available space
        return QSize(0, super().minimumSizeHint().height())

    def _overflow(self) -> float:
        return max(0.0, float(self.fontMetrics().horizontalAdvance(self.text())
                              - self.contentsRect().width()))

    def _restart(self) -> None:
        self._off   = 0.0
        self._phase = 0
        self._t0    = time.monotonic()
        if self._overflow() > 0 and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._restart()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if self._overflow() > 0:
            self._timer.start()

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        self._timer.stop()

    def _tick_marquee(self) -> None:
        if not self.isVisible() or _window_minimized(self):
            return
        ov = self._overflow()
        if ov <= 0:
            self._off = 0.0
            self._timer.stop()
            self.update()
            return
        now  = time.monotonic()
        step = self._SPEED * self._TICK_MS / 1000.0
        if self._phase in (0, 2):
            if now - self._t0 >= self._PAUSE:
                self._phase = 1 if self._phase == 0 else 3
        elif self._phase == 1:
            self._off = min(ov, self._off + step)
            if self._off >= ov:
                self._phase = 2
                self._t0 = now
            self.update()
        else:
            self._off = max(0.0, self._off - step)
            if self._off <= 0:
                self._phase = 0
                self._t0 = now
            self.update()

    def paintEvent(self, ev) -> None:
        if self._overflow() <= 0:
            super().paintEvent(ev)
            return
        p = QPainter(self)
        cr = self.contentsRect()
        p.setClipRect(cr)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        tw = self.fontMetrics().horizontalAdvance(self.text())
        r = QRectF(cr.x() - self._off, cr.y(), tw + 4, cr.height())
        p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.text())
        p.end()


class _EqWidget(QWidget):
    """18-bar animated equalizer visualizer (rounded caps, soft decay)."""

    _N    = 18
    _IDLE = 0.05

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(36)
        self._active   = False
        self._decaying = False
        self._heights  = [self._IDLE] * self._N
        self._targets  = [self._IDLE] * self._N

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._decaying = False
            if self.isVisible():
                self._timer.start()
        else:
            # ease bars down (~400 ms) instead of snapping to the baseline
            self._targets = [self._IDLE] * self._N
            if self.isVisible():
                self._decaying = True
                self._timer.start()
            else:
                self._snap_idle()

    def _snap_idle(self) -> None:
        self._decaying = False
        self._heights = [self._IDLE] * self._N
        self._timer.stop()
        self.update()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if self._active or self._decaying:
            self._timer.start()

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        self._timer.stop()
        if self._decaying:
            self._snap_idle()    # finish the decay while invisible

    def _tick(self) -> None:
        if not self.isVisible() or _window_minimized(self):
            return
        if self._active:
            for i in range(self._N):
                self._targets[i] = random.uniform(0.08, 1.0)
                self._heights[i] += (self._targets[i] - self._heights[i]) * 0.35
        else:
            done = True
            for i in range(self._N):
                self._heights[i] += (self._IDLE - self._heights[i]) * 0.45
                if abs(self._heights[i] - self._IDLE) > 0.01:
                    done = False
            if done:
                self._snap_idle()
                return
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
        radius = bar_w / 2

        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            bh = max(3, int(self._heights[i] * (h - 2)))
            x = x0 + i * (bar_w + gap)
            y = h - bh

            grad = QLinearGradient(x, y, x, h)
            grad.setColorAt(0.0, QColor(108, 99, 255, 220))
            grad.setColorAt(1.0, QColor(167, 139, 250, 100))
            p.setBrush(QBrush(grad))
            # bottom edge extends past the widget so only the tops are rounded
            p.drawRoundedRect(QRectF(x, y, bar_w, bh + radius), radius, radius)

        p.end()


class PlayerPanel(QFrame):
    play_pause_clicked = pyqtSignal()
    skip_clicked       = pyqtSignal()
    previous_clicked   = pyqtSignal()
    volume_changed     = pyqtSignal(float)
    seek_requested     = pyqtSignal(float)
    shuffle_clicked    = pyqtSignal()
    loop_clicked       = pyqtSignal(str)     # next mode: "none" | "one" | "all"

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
        self._loop_mode    = "none"
        self._seek_timer   = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.timeout.connect(self._do_seek)

        # Post-seek lock: keeps server state from snapping the slider back.
        # A persistent timer (not QTimer.singleShot) so a NEW drag can cancel
        # the previous lock — an old lock expiring mid-drag let a state_update
        # yank the slider out of the user's hand and cancel the seek.
        self._seek_lock_timer = QTimer(self)
        self._seek_lock_timer.setSingleShot(True)
        self._seek_lock_timer.setInterval(2500)
        self._seek_lock_timer.timeout.connect(self._end_seek_lock)

        self._pending_vol: float | None = None
        self._vol_timer = QTimer(self)
        self._vol_timer.setSingleShot(True)
        self._vol_timer.setInterval(250)
        self._vol_timer.timeout.connect(self._emit_volume)

        self._nam = QNetworkAccessManager(self)
        self._nam.finished.connect(self._on_image_loaded)

        # cover crossfade + blurred-backdrop state
        self._art_anim: QVariantAnimation | None = None
        self._pending_art: QPixmap | None = None
        self._bg_small: QPixmap | None = None       # ~24px "blur" source
        self._bg_old_small: QPixmap | None = None
        self._bg_cache: QPixmap | None = None       # upscaled, per card size
        self._bg_old_cache: QPixmap | None = None
        self._bg_fade = 1.0
        self._bg_anim: QVariantAnimation | None = None

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
        # overlay label used for the 300 ms cover crossfade
        self._art_overlay = QLabel(self._art)
        self._art_overlay.setGeometry(0, 0, self._ART_SIZE, self._ART_SIZE)
        self._art_overlay.setStyleSheet("background: transparent;")
        self._art_overlay.hide()

        info_row.addWidget(self._art)

        meta = QVBoxLayout()
        meta.setSpacing(6)
        meta.addStretch()

        self._title = _MarqueeLabel("Nothing playing")
        self._title.setObjectName("trackTitle")
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

        self._progress = _SeekSlider(Qt.Orientation.Horizontal, lambda: self._duration)
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

        self._shuffle_btn = _TransportButton("🔀︎", "Shuffle queue")
        self._shuffle_btn.clicked.connect(self.shuffle_clicked)
        ctrl.addWidget(self._shuffle_btn)

        self._prev_btn = _TransportButton("⏮︎", "Previous")
        self._prev_btn.clicked.connect(self.previous_clicked)
        ctrl.addWidget(self._prev_btn)

        self._play_btn = _PlayButton()
        self._play_btn.clicked.connect(self.play_pause_clicked)
        ctrl.addWidget(self._play_btn)

        self._skip_btn = _TransportButton("⏭︎", "Skip")
        self._skip_btn.clicked.connect(self.skip_clicked)
        ctrl.addWidget(self._skip_btn)

        self._loop_btn = _TransportButton(_LOOP_ICONS["none"], _LOOP_TIPS["none"])
        self._loop_btn.clicked.connect(self._on_loop_click)
        ctrl.addWidget(self._loop_btn)

        ctrl.addStretch()

        vol_icon = QLabel("🔊︎")
        vol_icon.setStyleSheet("background:transparent; font-size:15px;")
        ctrl.addWidget(vol_icon)

        self._vol = QSlider(Qt.Orientation.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(50)
        self._vol.setFixedWidth(96)
        self._vol.setToolTip("Volume")
        self._vol.valueChanged.connect(self._on_vol_changed)
        self._vol.sliderReleased.connect(self._on_vol_released)
        ctrl.addWidget(self._vol)

        root.addLayout(ctrl)

    # ── public ────────────────────────────────────────────────────────────

    def update_state(self, state: dict) -> None:
        # loop mode persists on the server regardless of playback — sync it
        # even when nothing is playing (no signals emitted, no feedback loop)
        self._set_loop_mode(state.get("loop_mode", "none"))

        current = state.get("current")

        if not current:
            self._reset()
            return

        title    = str(current.get("title") or "Unknown")
        artist   = str(current.get("artist") or "Unknown")
        duration = int(current.get("duration") or 0)
        thumb    = current.get("thumbnail", "") or ""

        self._title.setText(title)
        self._artist.setText(artist)
        self._duration = duration
        self._total.setText(_fmt(duration))

        if thumb and thumb != self._thumb_url:
            self._thumb_url = thumb
            self._nam.get(QNetworkRequest(QUrl(thumb)))
        elif not thumb and self._thumb_url:
            # new track has no cover — don't keep showing the previous one
            self._thumb_url = ""
            self._set_placeholder_art()

        self._is_playing = state.get("is_playing", False)
        self._is_paused  = state.get("is_paused",  False)
        self._play_btn.setText("⏸" if self._is_playing else "▶")
        self._eq.set_active(self._is_playing and not self._is_paused)

        pos = float(state.get("position") or 0.0)
        self._position = pos
        if (not self._seeking and not self._progress.isSliderDown()
                and self._duration > 0):
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
        self._set_placeholder_art()
        self._eq.set_active(False)
        self._tick_timer.stop()

    def _set_placeholder_art(self) -> None:
        self._cancel_art_fade()
        self._clear_bg_art()
        self._art.clear()
        self._art.setText("♪")
        self._art.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 #16162a, stop:1 #0e0e1a);"
            f" border-radius:12px; font-size:40px; color:#6b6b8a;"
        )

    # ── cover crossfade ───────────────────────────────────────────────────

    def _show_art(self, px: QPixmap) -> None:
        """Crossfade the new cover over the current one (300 ms)."""
        self._finish_art_fade()
        self._pending_art = px
        self._art_overlay.setPixmap(px)
        effect = QGraphicsOpacityEffect(self._art_overlay)
        effect.setOpacity(0.0)
        self._art_overlay.setGraphicsEffect(effect)
        self._art_overlay.show()

        anim = QVariantAnimation(self._art_overlay)
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(effect.setOpacity)
        anim.finished.connect(self._finish_art_fade)
        self._art_anim = anim
        anim.start()

    def _finish_art_fade(self) -> None:
        # commit the pending cover to the base label, drop the overlay
        if self._pending_art is not None:
            self._art.setPixmap(self._pending_art)
            self._art.setStyleSheet("background: transparent;")
        self._cancel_art_fade()

    def _cancel_art_fade(self) -> None:
        anim, self._art_anim = self._art_anim, None
        if anim is not None:
            anim.stop()
            anim.deleteLater()
        self._pending_art = None
        self._art_overlay.hide()
        self._art_overlay.setGraphicsEffect(None)

    # ── blurred backdrop ──────────────────────────────────────────────────

    def _set_bg_art(self, px: QPixmap) -> None:
        """Fake-blur backdrop: heavy downscale now, smooth upscale in paint."""
        if self._bg_anim is not None:
            anim, self._bg_anim = self._bg_anim, None
            anim.stop()
            anim.deleteLater()
            self._bg_old_small = None    # commit the interrupted fade
            self._bg_old_cache = None
            self._bg_fade = 1.0
        self._bg_old_small = self._bg_small
        self._bg_old_cache = self._bg_cache
        self._bg_small = px.scaled(
            QSize(24, 24),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._bg_cache = None
        self._bg_fade = 0.0

        anim = QVariantAnimation(self)
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_bg_fade)
        anim.finished.connect(self._end_bg_fade)
        self._bg_anim = anim
        anim.start()

    def _on_bg_fade(self, v) -> None:
        self._bg_fade = float(v)
        self.update()

    def _end_bg_fade(self) -> None:
        if self._bg_anim is None:
            return
        self._bg_anim.deleteLater()
        self._bg_anim = None
        self._bg_fade = 1.0
        self._bg_old_small = None
        self._bg_old_cache = None
        self.update()

    def _clear_bg_art(self) -> None:
        if self._bg_anim is not None:
            anim, self._bg_anim = self._bg_anim, None
            anim.stop()
            anim.deleteLater()
        self._bg_small = None
        self._bg_old_small = None
        self._bg_cache = None
        self._bg_old_cache = None
        self._bg_fade = 1.0
        self.update()

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        if self._bg_small is None and self._bg_old_small is None:
            super().paintEvent(event)    # stylesheet card (no art)
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, 16.0, 16.0)
        p.setClipPath(path)

        p.fillRect(self.rect(), QColor(14, 14, 26, 224))   # base surface

        first = self._bg_old_small is None   # fading in over the plain card
        if self._bg_old_small is not None:
            self._bg_old_cache = self._draw_cover(
                p, self._bg_old_small, self._bg_old_cache, 1.0)
        if self._bg_small is not None:
            self._bg_cache = self._draw_cover(
                p, self._bg_small, self._bg_cache, self._bg_fade)

        alpha = int(204 * self._bg_fade) if first else 204  # 80% dark overlay
        p.fillRect(self.rect(), QColor(6, 6, 12, alpha))

        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor("#2a2a40"))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 16.0, 16.0)
        p.end()

    def _draw_cover(self, p: QPainter, small: QPixmap,
                    cache: QPixmap | None, opacity: float) -> QPixmap:
        """Draw `small` scaled to cover the card; returns the (re)built cache."""
        if cache is None:
            cache = small.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        x = (self.width()  - cache.width())  // 2
        y = (self.height() - cache.height()) // 2
        if opacity < 1.0:
            p.setOpacity(opacity)
        p.drawPixmap(x, y, cache)
        p.setOpacity(1.0)
        return cache

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._bg_cache = None
        self._bg_old_cache = None

    def _set_loop_mode(self, mode: str) -> None:
        if mode not in _LOOP_ICONS or mode == self._loop_mode:
            return
        self._loop_mode = mode
        self._loop_btn.setText(_LOOP_ICONS[mode])
        self._loop_btn.setToolTip(_LOOP_TIPS[mode])
        # active modes glow purple; "none" falls back to the app stylesheet
        self._loop_btn.setStyleSheet(_LOOP_ACTIVE_QSS if mode != "none" else "")

    def _on_loop_click(self) -> None:
        nxt = _LOOP_ORDER[(_LOOP_ORDER.index(self._loop_mode) + 1) % len(_LOOP_ORDER)]
        self._set_loop_mode(nxt)     # optimistic; server state_update confirms
        self.loop_clicked.emit(nxt)

    def _on_vol_changed(self, v: int) -> None:
        self._pending_vol = v / 100.0
        self._vol_timer.start()          # debounce: one POST /volume per ~250 ms

    def _on_vol_released(self) -> None:
        if self._vol_timer.isActive():
            self._vol_timer.stop()
            self._emit_volume()

    def _emit_volume(self) -> None:
        if self._pending_vol is not None:
            self.volume_changed.emit(self._pending_vol)
            self._pending_vol = None

    def _tick(self) -> None:
        if not self._is_playing or self._seeking or self._duration <= 0:
            return
        self._position = min(self._position + 0.5, self._duration)
        self._progress.setValue(int(self._position / self._duration * 1000))
        self._elapsed.setText(_fmt(self._position))

    def _on_seek_press(self) -> None:
        self._seeking = True
        self._seek_timer.stop()
        self._seek_lock_timer.stop()   # a new drag supersedes the old lock

    def _on_seek_release(self) -> None:
        if self._duration > 0:
            self._position = self._progress.value() / 1000 * self._duration
            self._elapsed.setText(_fmt(self._position))
            self._seek_timer.start(300)

    def _do_seek(self) -> None:
        self.seek_requested.emit(self._position)
        self._seek_lock_timer.start()

    def _end_seek_lock(self) -> None:
        self._seeking = False

    def _on_image_loaded(self, reply: QNetworkReply) -> None:
        if (reply.error() != QNetworkReply.NetworkError.NoError
                or reply.request().url().toString() != self._thumb_url):
            reply.deleteLater()          # failed or stale (track already changed)
            return
        data = reply.readAll()
        px = QPixmap()
        if px.loadFromData(data):
            self._set_bg_art(px)             # blurred card backdrop
            s = self._ART_SIZE
            px = px.scaled(s, s,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
            x = (px.width()  - s) // 2
            y = (px.height() - s) // 2
            px = px.copy(x, y, s, s)
            px = _rounded_pixmap(px, r=12)
            self._show_art(px)               # 300 ms crossfade
        reply.deleteLater()


class _TransportButton(QPushButton):
    def __init__(self, icon: str, tip: str, parent=None) -> None:
        super().__init__(icon, parent)
        self.setObjectName("transportBtn")
        self.setFixedSize(40, 40)
        self.setToolTip(tip)


class _PlayButton(QPushButton):
    """Round accent play/pause button: glow + hover scale, painted manually.

    Fixed 56x56 widget with a 48px circle inside — hover growth happens in
    paint (never in layout), so nothing around it moves.
    """

    _CIRCLE = 48

    def __init__(self, parent=None) -> None:
        super().__init__("▶", parent)
        self.setObjectName("playBtn")
        self.setFixedSize(56, 56)
        self.setToolTip("Play / Pause")

        self._scale = 1.0
        self._scale_anim = QVariantAnimation(self)
        self._scale_anim.setDuration(150)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scale_anim.valueChanged.connect(self._on_scale)

        self._glow = glow(self, blur=22)
        self._glow_anim = QPropertyAnimation(self._glow, b"blurRadius", self)
        self._glow_anim.setDuration(150)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _on_scale(self, v) -> None:
        self._scale = float(v)
        self.update()

    def _animate_hover(self, scale_to: float, blur_to: float) -> None:
        self._scale_anim.stop()
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(scale_to)
        self._scale_anim.start()
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow.blurRadius())
        self._glow_anim.setEndValue(blur_to)
        self._glow_anim.start()

    def enterEvent(self, ev) -> None:
        super().enterEvent(ev)
        self._animate_hover(1.07, 36.0)

    def leaveEvent(self, ev) -> None:
        super().leaveEvent(ev)
        self._animate_hover(1.0, 22.0)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        d = self._CIRCLE * self._scale
        cx, cy = self.width() / 2, self.height() / 2
        r = QRectF(cx - d / 2, cy - d / 2, d, d)

        if self.isDown():
            brush = QBrush(QColor("#5b53e6"))
        else:
            grad = QLinearGradient(r.topLeft(), r.bottomRight())
            if self.underMouse():
                grad.setColorAt(0.0, QColor("#8b85ff"))
                grad.setColorAt(1.0, QColor("#b9a8ff"))
            else:
                grad.setColorAt(0.0, QColor("#6C63FF"))
                grad.setColorAt(1.0, QColor("#A78BFA"))
            brush = QBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(brush)
        p.drawEllipse(r)

        f = QFont(self.font())
        f.setPixelSize(round(18 * self._scale))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        tr = QRectF(self.rect())
        if self.text() == "▶":
            tr.translate(2.0, 0.0)   # optical centering for the triangle
        p.drawText(tr, Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()
