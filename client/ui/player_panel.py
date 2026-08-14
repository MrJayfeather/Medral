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
    QBrush, QFont, QPen,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from i18n import tr
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
# i18n catalog keys — the module is imported before init_lang() runs, so the
# dict holds keys and tr() is applied at the call sites, not at import time
_LOOP_TIPS  = {"none": "loop_off", "all": "loop_queue", "one": "loop_track"}


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
    """Continuous "living wave" visualizer (Catmull-Rom curve, ~60 FPS).

    A smooth curve through 24 control points, same visual language as the
    splash screen wave: random targets refresh every ~90 ms while every
    16 ms frame only eases the heights toward them (exponential smoothing)
    and repaints.  A slow travelling phase makes the wave breathe and
    drift; a phase-shifted back layer adds depth, and a few glowing
    sparks ride the crest.  On pause the wave decays to a near-flat line
    in ~400 ms and the timer stops.
    """

    _N          = 24       # control points across the width
    _IDLE       = 0.04     # near-flat baseline level
    _TICK_MS    = 16       # ~60 FPS
    _RETARGET_S = 0.09     # seconds between random target refreshes
    _ATTACK_TAU = 0.12     # s — exp. easing toward targets while active
    _DECAY_TAU  = 0.09     # s — pause fade-out (settles in ~400 ms)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(44)
        self._active   = False
        self._decaying = False
        self._heights  = [self._IDLE] * self._N
        self._targets  = [self._IDLE] * self._N
        self._phase    = 0.0
        self._retarget_acc = self._RETARGET_S    # retarget on the first tick
        self._last_t   = time.monotonic()
        # Hann window: quiet at the edges, full amplitude in the middle
        n1 = self._N - 1
        self._profile = [math.sin(math.pi * i / n1) ** 2
                         for i in range(self._N)]
        # sparks riding the crest: [pos 0..1, drift/s, pulse phase, pulse hz]
        self._sparks = [
            [random.uniform(0.15, 0.85),
             random.uniform(0.03, 0.07) * random.choice((-1.0, 1.0)),
             random.uniform(0.0, math.tau),
             random.uniform(1.5, 2.6)]
            for _ in range(3)
        ]

        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._decaying = False
            self._retarget_acc = self._RETARGET_S
            self._last_t = time.monotonic()
            if self.isVisible():
                self._timer.start()
        else:
            # ease the wave down (~400 ms) instead of snapping flat
            self._targets = [self._IDLE] * self._N
            if self.isVisible():
                self._decaying = True
                self._last_t = time.monotonic()
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
            self._last_t = time.monotonic()
            self._timer.start()

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        self._timer.stop()
        if self._decaying:
            self._snap_idle()    # finish the decay while invisible

    # ── simulation ────────────────────────────────────────────────────────

    def _tick(self) -> None:
        if not self.isVisible() or _window_minimized(self):
            self._last_t = time.monotonic()   # no dt jump on resume
            return
        now = time.monotonic()
        dt = min(0.05, max(0.0, now - self._last_t))
        self._last_t = now

        self._phase += dt * 1.7               # slow travelling drift

        if self._active:
            self._retarget_acc += dt
            if self._retarget_acc >= self._RETARGET_S:
                self._retarget_acc = 0.0
                self._retarget()
            k = 1.0 - math.exp(-dt / self._ATTACK_TAU)
            for i in range(self._N):
                self._heights[i] += (self._targets[i] - self._heights[i]) * k
        else:
            k = 1.0 - math.exp(-dt / self._DECAY_TAU)
            done = True
            for i in range(self._N):
                self._heights[i] += (self._IDLE - self._heights[i]) * k
                if abs(self._heights[i] - self._IDLE) > 0.008:
                    done = False
            if done:
                self._snap_idle()
                return

        # sparks drift slowly along the crest, bouncing off the edges
        for s in self._sparks:
            s[0] += s[1] * dt
            if s[0] < 0.10:
                s[0], s[1] = 0.10, abs(s[1])
            elif s[0] > 0.90:
                s[0], s[1] = 0.90, -abs(s[1])
        self.update()

    def _retarget(self) -> None:
        t = [random.uniform(0.12, 1.0) for _ in range(self._N)]
        # one neighbour-averaging pass keeps the profile organic, not jagged
        self._targets = [
            (t[max(0, i - 1)] + 2.0 * t[i] + t[min(self._N - 1, i + 1)])
            * 0.25
            for i in range(self._N)
        ]

    # ── curve helpers ─────────────────────────────────────────────────────

    def _display(self, phase: float, scale: float) -> list:
        """Per-point displayed amplitude 0..1: Hann profile + breathing."""
        heights, profile = self._heights, self._profile
        return [
            heights[i] * profile[i]
            * (0.72 + 0.28 * math.sin(phase - i * 0.55)) * scale
            for i in range(self._N)
        ]

    def _sample(self, disp: list, u: float) -> float:
        """Catmull-Rom sample of the displayed amplitudes at fraction u."""
        f = u * (self._N - 1)
        i = min(self._N - 2, max(0, int(f)))
        t = f - i
        p0 = disp[max(0, i - 1)]
        p1 = disp[i]
        p2 = disp[i + 1]
        p3 = disp[min(self._N - 1, i + 2)]
        return 0.5 * ((2.0 * p1) + (-p0 + p2) * t
                      + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t * t
                      + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t * t * t)

    @staticmethod
    def _smooth_path(pts: list) -> QPainterPath:
        """Catmull-Rom spline through pts, emitted as cubic Béziers."""
        path = QPainterPath(pts[0])
        n = len(pts)
        for i in range(n - 1):
            p0 = pts[max(0, i - 1)]
            p1 = pts[i]
            p2 = pts[i + 1]
            p3 = pts[min(n - 1, i + 2)]
            c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                         p1.y() + (p2.y() - p0.y()) / 6.0)
            c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                         p2.y() - (p3.y() - p1.y()) / 6.0)
            path.cubicTo(c1, c2, p2)
        return path

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = float(self.width()), float(self.height())
        if w < 8.0:
            p.end()
            return
        base_y = h - 3.0
        span   = h - 9.0                 # max crest rise above the baseline
        step   = w / (self._N - 1)

        def pts(disp):
            return [QPointF(i * step, base_y - disp[i] * span)
                    for i in range(self._N)]

        # layer 1 — back wave: phase-shifted, half amplitude → depth
        back = self._smooth_path(pts(self._display(self._phase + 2.3, 0.5)))
        pen = QPen(QColor(167, 139, 250, 45), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(back)

        # layer 2 — main wave: gradient fill under the curve…
        crest = self._smooth_path(pts(self._display(self._phase, 1.0)))
        fill = QPainterPath(crest)
        fill.lineTo(w, h)
        fill.lineTo(0.0, h)
        fill.closeSubpath()
        grad = QLinearGradient(0.0, 0.0, 0.0, h)
        grad.setColorAt(0.0, QColor(108, 99, 255, 150))
        grad.setColorAt(1.0, QColor(108, 99, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(fill, QBrush(grad))

        # …then the crest: wide translucent glow + thin bright core
        line = QLinearGradient(0.0, 0.0, w, 0.0)
        line.setColorAt(0.0, QColor(108, 99, 255, 60))
        line.setColorAt(1.0, QColor(167, 139, 250, 60))
        pen = QPen(QBrush(line), 6.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(crest)

        line.setColorAt(0.0, QColor(108, 99, 255, 235))
        line.setColorAt(1.0, QColor(167, 139, 250, 235))
        pen = QPen(QBrush(line), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawPath(crest)

        # layer 3 — sparks: slow pulsing dots riding the crest, faded by
        # overall energy so they vanish together with the wave on pause
        energy = sum(self._heights) / self._N
        vis = max(0.0, min(1.0, (energy - self._IDLE) / 0.25))
        if vis > 0.02:
            disp = self._display(self._phase, 1.0)
            now = time.monotonic()
            p.setPen(Qt.PenStyle.NoPen)
            for u, _speed, ph, pulse_hz in self._sparks:
                x = u * w
                y = base_y - self._sample(disp, u) * span
                a = vis * (0.55 + 0.45 * math.sin(now * pulse_hz + ph))
                p.setBrush(QColor(167, 139, 250, int(70 * a)))
                p.drawEllipse(QPointF(x, y), 3.4, 3.4)
                p.setBrush(QColor(232, 232, 245, int(200 * a)))
                p.drawEllipse(QPointF(x, y), 1.3, 1.3)

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

        self._title = _MarqueeLabel(tr("nothing_playing"))
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

        self._shuffle_btn = _IconButton("shuffle", tr("shuffle_tip"))
        self._shuffle_btn.clicked.connect(self.shuffle_clicked)
        ctrl.addWidget(self._shuffle_btn)

        self._prev_btn = _IconButton("previous", tr("previous_tip"))
        self._prev_btn.clicked.connect(self.previous_clicked)
        ctrl.addWidget(self._prev_btn)

        self._play_btn = _PlayButton()
        self._play_btn.clicked.connect(self.play_pause_clicked)
        ctrl.addWidget(self._play_btn)

        self._skip_btn = _IconButton("next", tr("skip_tip"))
        self._skip_btn.clicked.connect(self.skip_clicked)
        ctrl.addWidget(self._skip_btn)

        self._loop_btn = _IconButton("loop", tr(_LOOP_TIPS["none"]), idle_muted=True)
        self._loop_btn.clicked.connect(self._on_loop_click)
        ctrl.addWidget(self._loop_btn)

        ctrl.addStretch()

        vol_icon = _VolumeIcon()
        ctrl.addWidget(vol_icon)

        self._vol = QSlider(Qt.Orientation.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(50)
        self._vol.setFixedWidth(96)
        self._vol.setToolTip(tr("volume_tip"))
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

        title    = str(current.get("title") or tr("unknown"))
        artist   = str(current.get("artist") or tr("unknown"))
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
        self._title.setText(tr("nothing_playing"))
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
        if mode not in _LOOP_TIPS or mode == self._loop_mode:
            return
        self._loop_mode = mode
        self._loop_btn.set_mode(mode)    # loop/loop_one glyph + accent state
        self._loop_btn.setToolTip(tr(_LOOP_TIPS[mode]))

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


class _IconButton(QPushButton):
    """Flat 40x40 transport button with a hand-drawn vector glyph.

    Everything is painted manually with QPainterPaths inside a 20x20 design
    box centered in the widget:
    - hover: accent-tinted backdrop fades in and the glyph lightens to
      #A78BFA (single QVariantAnimation, 150 ms OutCubic)
    - pressed: glyph shrinks to 0.9 (paint-only, layout untouched)
    - active (loop/shuffle toggles): accent glyph on rgba(108,99,255,0.18)
    Icon names: shuffle | previous | next | loop | loop_one | volume.
    """

    _IDLE   = QColor("#e8e8f5")
    _MUTED  = QColor("#6b6b8a")
    _HOVER  = QColor("#A78BFA")
    _ACCENT = QColor("#6C63FF")

    def __init__(self, icon: str, tip: str = "",
                 idle_muted: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._icon       = icon
        self._idle_muted = idle_muted
        self._active     = False
        self._hover      = 0.0            # animated 0..1 hover progress
        self.setFixedSize(40, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tip:
            self.setToolTip(tip)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(150)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover)

    # ── public ────────────────────────────────────────────────────────────

    def set_icon(self, icon: str) -> None:
        if icon != self._icon:
            self._icon = icon
            self.update()

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def set_mode(self, mode: str) -> None:
        """Loop-button helper: mode "none" | "all" | "one"."""
        self.set_icon("loop_one" if mode == "one" else "loop")
        self.set_active(mode != "none")

    # ── hover animation ───────────────────────────────────────────────────

    def _on_hover(self, v) -> None:
        self._hover = float(v)
        self.update()

    def _animate_hover(self, to: float) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(to)
        self._hover_anim.start()

    def enterEvent(self, ev) -> None:
        super().enterEvent(ev)
        self._animate_hover(1.0)

    def leaveEvent(self, ev) -> None:
        super().leaveEvent(ev)
        self._animate_hover(0.0)

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # backdrop: active tint + animated hover highlight
        if self._active:
            bg_alpha = 46 + int(20 * self._hover)   # 0.18 → ~0.26
        else:
            bg_alpha = int(38 * self._hover)        # 0 → 0.15
        if bg_alpha > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(108, 99, 255, bg_alpha))
            p.drawRoundedRect(QRectF(self.rect()), 20.0, 20.0)

        base = self._ACCENT if self._active else (
            self._MUTED if self._idle_muted else self._IDLE)
        color = self._mix(base, self._HOVER, self._hover)

        # pressed: shrink the glyph around the center (paint-only)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        p.translate(cx, cy)
        if self.isDown():
            p.scale(0.9, 0.9)
        p.translate(-10.0, -10.0)        # into the 20x20 icon box

        getattr(self, "_draw_" + self._icon)(p, color)
        p.end()

    @staticmethod
    def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
        return QColor(
            round(c1.red()   + (c2.red()   - c1.red())   * t),
            round(c1.green() + (c2.green() - c1.green()) * t),
            round(c1.blue()  + (c2.blue()  - c1.blue())  * t),
        )

    # ── glyphs (20x20 design box) ─────────────────────────────────────────

    @staticmethod
    def _stroke(color: QColor, width: float = 1.8) -> QPen:
        return QPen(color, width, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

    @staticmethod
    def _soft_fill(p: QPainter, color: QColor, path: QPainterPath,
                   pen_w: float = 1.4) -> None:
        """Fill a path and outline it with a round-join pen of the same
        color — cheap corner rounding for triangles/arrowheads."""
        p.setPen(_IconButton._stroke(color, pen_w))
        p.setBrush(QBrush(color))
        p.drawPath(path)

    @staticmethod
    def _add_arrow(path: QPainterPath, x: float, y: float,
                   angle: float, size: float = 2.5) -> None:
        """Append a triangular head centered at (x, y) pointing along
        `angle` (radians, screen coords: +x right, +y down)."""
        dx, dy = math.cos(angle), math.sin(angle)
        px, py = -dy, dx
        path.moveTo(x + dx * size, y + dy * size)
        path.lineTo(x - dx * size * 0.55 + px * size * 0.95,
                    y - dy * size * 0.55 + py * size * 0.95)
        path.lineTo(x - dx * size * 0.55 - px * size * 0.95,
                    y - dy * size * 0.55 - py * size * 0.95)
        path.closeSubpath()

    @staticmethod
    def _draw_shuffle(p: QPainter, color: QColor) -> None:
        # two crossing strands, arrowheads on the right ends
        lines = QPainterPath()
        lines.moveTo(1.8, 14.8)
        lines.lineTo(5.2, 14.8)
        lines.lineTo(12.6, 5.2)
        lines.lineTo(15.6, 5.2)
        lines.moveTo(1.8, 5.2)
        lines.lineTo(5.2, 5.2)
        lines.lineTo(12.6, 14.8)
        lines.lineTo(15.6, 14.8)
        p.setPen(_IconButton._stroke(color))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(lines)

        heads = QPainterPath()
        _IconButton._add_arrow(heads, 16.4, 5.2, 0.0)
        _IconButton._add_arrow(heads, 16.4, 14.8, 0.0)
        _IconButton._soft_fill(p, color, heads, pen_w=1.0)

    @staticmethod
    def _draw_previous(p: QPainter, color: QColor) -> None:
        # bar + two left-pointing triangles
        glyph = QPainterPath()
        glyph.addRoundedRect(QRectF(2.2, 4.8, 2.2, 10.4), 1.1, 1.1)
        for apex, base in ((5.6, 12.0), (11.8, 18.2)):
            glyph.moveTo(apex, 10.0)
            glyph.lineTo(base, 5.0)
            glyph.lineTo(base, 15.0)
            glyph.closeSubpath()
        _IconButton._soft_fill(p, color, glyph)

    @staticmethod
    def _draw_next(p: QPainter, color: QColor) -> None:
        p.save()
        p.translate(20.0, 0.0)
        p.scale(-1.0, 1.0)
        _IconButton._draw_previous(p, color)
        p.restore()

    @staticmethod
    def _draw_loop(p: QPainter, color: QColor) -> None:
        # two clockwise arcs with tangential arrowheads
        r = 6.4
        ring = QRectF(10.0 - r, 10.0 - r, 2 * r, 2 * r)
        arcs = QPainterPath()
        arcs.arcMoveTo(ring, 150.0)
        arcs.arcTo(ring, 150.0, -120.0)      # top arc, ends at 30 deg
        arcs.arcMoveTo(ring, -30.0)
        arcs.arcTo(ring, -30.0, -120.0)      # bottom arc, ends at 210 deg
        p.setPen(_IconButton._stroke(color))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(arcs)

        heads = QPainterPath()
        for end_deg in (30.0, 210.0):
            t = math.radians(end_deg)
            x = 10.0 + r * math.cos(t)
            y = 10.0 - r * math.sin(t)
            # clockwise tangent in screen coords: (sin t, cos t)
            ang = math.atan2(math.cos(t), math.sin(t))
            _IconButton._add_arrow(heads, x, y, ang, 2.4)
        _IconButton._soft_fill(p, color, heads, pen_w=1.0)

    @staticmethod
    def _draw_loop_one(p: QPainter, color: QColor) -> None:
        _IconButton._draw_loop(p, color)
        f = QFont()
        f.setFamilies(["DM Sans", "Segoe UI"])   # bundled font, OS fallback
        f.setPixelSize(8)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(color))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawText(QRectF(0.0, 0.0, 20.0, 20.0),
                   Qt.AlignmentFlag.AlignCenter, "1")

    @staticmethod
    def _draw_volume(p: QPainter, color: QColor) -> None:
        # speaker body + two sound arcs
        body = QPainterPath()
        body.moveTo(2.2, 7.6)
        body.lineTo(5.4, 7.6)
        body.lineTo(9.2, 4.0)
        body.lineTo(9.2, 16.0)
        body.lineTo(5.4, 12.4)
        body.lineTo(2.2, 12.4)
        body.closeSubpath()
        _IconButton._soft_fill(p, color, body)

        waves = QPainterPath()
        for wr in (3.2, 5.6):
            wave = QRectF(9.5 - wr, 10.0 - wr, 2 * wr, 2 * wr)
            waves.arcMoveTo(wave, 45.0)
            waves.arcTo(wave, 45.0, -90.0)
        p.setPen(_IconButton._stroke(color))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(waves)


class _VolumeIcon(QWidget):
    """Static speaker glyph next to the volume slider (no interaction).

    Reuses the _IconButton vector path at 80% scale so the transport row
    keeps a single visual language.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width() / 2.0, self.height() / 2.0)
        p.scale(0.8, 0.8)
        p.translate(-10.0, -10.0)
        _IconButton._draw_volume(p, QColor("#e8e8f5"))
        p.end()


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
        self.setToolTip(tr("play_pause_tip"))

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

        # glyph drawn as vector paths, same language as _IconButton:
        # play — triangle with rounded corners, pause — two rounded bars
        s = self._scale
        white = QColor("#ffffff")
        glyph = QPainterPath()
        if self.text() == "▶":
            hw, hh = 6.4 * s, 7.6 * s        # half-extents of the triangle
            ox = 1.6 * s                     # optical centering
            glyph.moveTo(cx - hw + ox, cy - hh)
            glyph.lineTo(cx - hw + ox, cy + hh)
            glyph.lineTo(cx + hw + ox, cy)
            glyph.closeSubpath()
            # round-join outline of the same color rounds the corners
            p.setPen(QPen(white, 3.0 * s, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        else:
            bw, bh, gap = 4.4 * s, 15.0 * s, 3.8 * s
            glyph.addRoundedRect(
                QRectF(cx - gap / 2 - bw, cy - bh / 2, bw, bh),
                2.1 * s, 2.1 * s)
            glyph.addRoundedRect(
                QRectF(cx + gap / 2, cy - bh / 2, bw, bh),
                2.1 * s, 2.1 * s)
            p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(white))
        p.drawPath(glyph)
        p.end()
