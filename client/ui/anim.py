"""Reusable animation helpers for the Medral client (design system v2).

All effects/animations are parented to their widget, so they are destroyed
together with it — no leaks, no dangling QObject references.

Note: a QWidget can hold only ONE graphics effect at a time, so fade_in /
pulse / glow are mutually exclusive on the same widget.  fade_in removes
its temporary opacity effect when finished, so a subsequent glow() is fine.
"""

from PyQt6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QObject, QParallelAnimationGroup,
    QPoint, QPropertyAnimation, Qt, QTimer,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect

ACCENT = "#6C63FF"   # kept in sync with styles.ACCENT

_PULSE_ATTR = "_medral_pulse_anim"


class _PauseWhenHidden(QObject):
    """Pauses a looping animation while its widget (or window) is not visible.

    Keeps timers quiet when the window is minimized — per the design system,
    background animations must stop when nothing is on screen.
    """

    def __init__(self, widget, anim) -> None:
        super().__init__(widget)
        self._widget = widget
        self._anim = anim
        widget.installEventFilter(self)
        win = widget.window()
        if win is not widget:
            win.installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() in (QEvent.Type.Hide, QEvent.Type.Show,
                         QEvent.Type.WindowStateChange):
            self._sync()
        return False

    def _sync(self) -> None:
        try:
            hidden = (not self._widget.isVisible()) or bool(
                self._widget.window().windowState()
                & Qt.WindowState.WindowMinimized
            )
            state = self._anim.state()
            if hidden and state == QAbstractAnimation.State.Running:
                self._anim.pause()
            elif not hidden and state == QAbstractAnimation.State.Paused:
                self._anim.resume()
        except RuntimeError:
            pass   # widget or animation already destroyed


def fade_in(widget, ms: int = 350, dy: int = 14, effect=None):
    """Fade a widget in with a soft upward slide (OutQuint).

    Reuses `effect` if the caller already installed a QGraphicsOpacityEffect
    (replacing an installed effect deletes it — Qt may crash if that happens
    while it is painting, so there must be exactly one effect per widget).
    The effect is detached AFTER the animation via a deferred singleShot —
    never synchronously from the finished signal.
    """
    if effect is None or widget.graphicsEffect() is not effect:
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)

    group = QParallelAnimationGroup(widget)

    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setDuration(ms)
    fade.setStartValue(effect.opacity())
    fade.setEndValue(1.0)
    fade.setEasingCurve(QEasingCurve.Type.OutQuint)
    group.addAnimation(fade)

    if dy:
        end = widget.pos()
        slide = QPropertyAnimation(widget, b"pos", group)
        slide.setDuration(ms)
        slide.setStartValue(end + QPoint(0, dy))
        slide.setEndValue(end)
        slide.setEasingCurve(QEasingCurve.Type.OutQuint)
        group.addAnimation(slide)

    def _detach() -> None:
        try:
            if widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)
        except RuntimeError:
            pass

    def _cleanup() -> None:
        # Deferred: detaching (= deleting) the effect inside the finished
        # handler can race the effect's own paint pass and crash natively
        QTimer.singleShot(0, _detach)

    group.finished.connect(_cleanup)
    group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return group


def pulse(widget, ms: int = 1800, low: float = 0.45):
    """Soft breathing for live indicators (opacity 1.0 → low → 1.0, looped).

    Idempotent: calling twice on the same widget returns the running
    animation.  Auto-pauses while the window is minimized.  Stop with
    stop_pulse(widget).
    """
    existing = getattr(widget, _PULSE_ATTR, None)
    if existing is not None:
        return existing

    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)

    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(1.0)
    anim.setKeyValueAt(0.5, low)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.InOutSine)
    anim.setLoopCount(-1)

    _PauseWhenHidden(widget, anim)
    setattr(widget, _PULSE_ATTR, anim)
    anim.start()
    return anim


def stop_pulse(widget) -> None:
    """Stop a pulse() started earlier and restore plain rendering."""
    anim = getattr(widget, _PULSE_ATTR, None)
    if anim is None:
        return
    setattr(widget, _PULSE_ATTR, None)
    try:
        anim.stop()
        anim.deleteLater()
        widget.setGraphicsEffect(None)
    except RuntimeError:
        pass


def glow(widget, color: str = ACCENT, blur: int = 24):
    """Accent glow around a widget (shadow with zero offset).

    Returns the effect so callers can tweak/remove it
    (widget.setGraphicsEffect(None)).
    """
    effect = QGraphicsDropShadowEffect(widget)
    effect.setOffset(0, 0)
    effect.setBlurRadius(blur)
    effect.setColor(QColor(color))
    widget.setGraphicsEffect(effect)
    return effect


def stagger(widgets, step_ms: int = 60, ms: int = 350, dy: int = 14) -> None:
    """Sequential fade_in over a list of widgets, step_ms apart.

    Widgets are hidden (opacity 0) immediately so late starters do not
    flash at full opacity before their turn.
    """
    for i, w in enumerate(widgets):
        effect = QGraphicsOpacityEffect(w)
        effect.setOpacity(0.0)
        w.setGraphicsEffect(effect)

        def _start(w=w, effect=effect) -> None:
            try:
                # Pass the pre-hide effect along — fade_in reuses it instead
                # of replacing it (replacement deletes the installed effect
                # and can crash Qt mid-paint)
                fade_in(w, ms, dy, effect=effect)
            except RuntimeError:
                pass   # widget destroyed before its turn

        if i == 0:
            _start()
        else:
            QTimer.singleShot(i * step_ms, _start)
