"""Embedded settings page (design system v2).

Replaces the old "Change server" QDialog: host/port editing, account row
with logout and the client version now live on a stacked page inside the
main window, with the aurora background visible behind a centered card.
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QAbstractButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QVariantAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QBrush


class ToggleSwitch(QAbstractButton):
    """iOS-style animated toggle: 40x22 track (radius 11), 18px knob.

    Checked — accent gradient #6C63FF -> #A78BFA, unchecked — #2a2a40.
    The knob position is animated over 150 ms (OutCubic) via QVariantAnimation.
    """

    _TRACK_W  = 40
    _TRACK_H  = 22
    _KNOB     = 18
    _MARGIN   = 2   # (22 - 18) / 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(self._TRACK_W, self._TRACK_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # 0.0 = knob left (off), 1.0 = knob right (on)
        self._pos = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)

        self.toggled.connect(self._animate_to_state)

    # ── animation ─────────────────────────────────────────────────────────

    def _on_anim_value(self, value) -> None:
        self._pos = float(value)
        self.update()

    def _animate_to_state(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    # ── public ────────────────────────────────────────────────────────────

    def set_checked_silent(self, checked: bool) -> None:
        """Sync the visual state without emitting toggled (no animation)."""
        self._anim.stop()
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._pos = 1.0 if checked else 0.0
        self.update()

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        p.setPen(Qt.PenStyle.NoPen)

        # track: blend between off-color and the accent gradient as the
        # knob travels, so mid-animation the background transitions too
        radius = self._TRACK_H / 2
        if self._pos > 0.0:
            grad = QLinearGradient(0, 0, self._TRACK_W, 0)
            on_l, on_r, off = QColor("#6C63FF"), QColor("#A78BFA"), QColor("#2a2a40")
            t = self._pos

            def _mix(a: QColor, b: QColor) -> QColor:
                return QColor(
                    round(a.red()   + (b.red()   - a.red())   * t),
                    round(a.green() + (b.green() - a.green()) * t),
                    round(a.blue()  + (b.blue()  - a.blue())  * t),
                )

            grad.setColorAt(0.0, _mix(off, on_l))
            grad.setColorAt(1.0, _mix(off, on_r))
            p.setBrush(QBrush(grad))
        else:
            p.setBrush(QColor("#2a2a40"))
        p.drawRoundedRect(0, 0, self._TRACK_W, self._TRACK_H, radius, radius)

        # knob
        x_off = self._MARGIN
        x_on  = self._TRACK_W - self._KNOB - self._MARGIN
        x = x_off + (x_on - x_off) * self._pos
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(int(round(x)), self._MARGIN, self._KNOB, self._KNOB)
        p.end()


def _read_version() -> str:
    """Same lookup order as main._read_version (importing main is circular)."""
    for candidate in (
        Path(__file__).parent.parent / "version.txt",           # client/version.txt
        Path(__file__).parent.parent.parent / "version.txt",    # project root
        Path(sys.executable).parent / "version.txt",            # next to frozen exe
    ):
        try:
            if candidate.exists():
                return candidate.read_text().strip()
        except OSError:
            pass
    return "0.0.0"


class SettingsView(QWidget):
    """Settings page: server address, account and client version.

    The page itself is transparent (aurora shows through); content sits on
    a centered surface card.  All persistence/apply logic stays in
    MainWindow — this view only collects input and emits signals.
    """

    back_requested    = pyqtSignal()
    connect_requested = pyqtSignal(str, int)   # host, port
    logout_requested  = pyqtSignal()
    settings_changed  = pyqtSignal(str, bool)  # key ("normalize"/"radio"), value

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsView")

        # used when the edits are blank / unparsable on "Connect"
        self._fallback_host = ""
        self._fallback_port = 8000

        self.setStyleSheet("""
            QWidget#settingsView { background: transparent; }
            QFrame#settingsCard {
                background-color: #0e0e1a;
                border: 1px solid #2a2a40;
                border-radius: 16px;
            }
            QLabel#settingsTitle {
                font-family: "Syne", "DM Sans", "Segoe UI", sans-serif;
                font-size: 24px;
                font-weight: 700;
                letter-spacing: 1px;
                color: #e8e8f5;
                background: transparent;
            }
            QPushButton#backBtn {
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #6b6b8a;
                font-size: 13px;
                padding: 6px 12px;
            }
            QPushButton#backBtn:hover {
                color: #e8e8f5;
                background: rgba(108,99,255,0.10);
            }
        """)

        self._build_ui()

    # ── layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 16)
        root.setSpacing(0)

        # back button — top left
        top = QHBoxLayout()
        back = QPushButton("←  Назад")
        back.setObjectName("backBtn")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back_requested)
        top.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        top.addStretch()
        root.addLayout(top)

        root.addStretch(1)

        title = QLabel("Настройки")
        title.setObjectName("settingsTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(title)
        root.addSpacing(20)

        # centered surface card
        card = QFrame()
        card.setObjectName("settingsCard")
        card.setFixedWidth(460)
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(28, 24, 28, 24)
        c_lay.setSpacing(12)

        srv_sec = QLabel("СЕРВЕР")
        srv_sec.setObjectName("sectionTitle")
        c_lay.addWidget(srv_sec)

        host_row = QHBoxLayout()
        host_lbl = QLabel("Host")
        host_lbl.setFixedWidth(40)
        host_lbl.setStyleSheet("color:#6b6b8a; background:transparent;")
        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("127.0.0.1  или  IP сервера")
        host_row.addWidget(host_lbl)
        host_row.addWidget(self._host_edit)
        c_lay.addLayout(host_row)

        port_row = QHBoxLayout()
        port_lbl = QLabel("Port")
        port_lbl.setFixedWidth(40)
        port_lbl.setStyleSheet("color:#6b6b8a; background:transparent;")
        self._port_edit = QLineEdit()
        self._port_edit.setPlaceholderText("8000")
        port_row.addWidget(port_lbl)
        port_row.addWidget(self._port_edit)
        c_lay.addLayout(port_row)

        c_lay.addSpacing(4)

        connect_btn = QPushButton("Подключиться")
        connect_btn.setObjectName("primaryBtn")
        connect_btn.clicked.connect(self._on_connect_clicked)
        c_lay.addWidget(connect_btn)

        c_lay.addSpacing(8)
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        c_lay.addWidget(divider)
        c_lay.addSpacing(8)

        play_sec = QLabel("ВОСПРОИЗВЕДЕНИЕ")
        play_sec.setObjectName("sectionTitle")
        c_lay.addWidget(play_sec)

        self._normalize_toggle = self._add_toggle_row(
            c_lay, "normalize",
            "Нормализация громкости",
            "Выравнивает громкость треков",
        )
        self._radio_toggle = self._add_toggle_row(
            c_lay, "radio",
            "Радио-режим",
            "Когда очередь кончается, бот продолжает похожими треками",
        )

        c_lay.addSpacing(8)
        divider2 = QFrame()
        divider2.setObjectName("divider")
        divider2.setFixedHeight(1)
        c_lay.addWidget(divider2)
        c_lay.addSpacing(8)

        acc_sec = QLabel("АККАУНТ")
        acc_sec.setObjectName("sectionTitle")
        c_lay.addWidget(acc_sec)

        acc_row = QHBoxLayout()
        self._user_lbl = QLabel("—")
        self._user_lbl.setStyleSheet("color:#e8e8f5; background:transparent;")
        acc_row.addWidget(self._user_lbl, 1)
        logout_btn = QPushButton("Выйти из аккаунта")
        logout_btn.setObjectName("disconnectBtn")
        logout_btn.clicked.connect(self.logout_requested)
        acc_row.addWidget(logout_btn, 0)
        c_lay.addLayout(acc_row)

        center = QHBoxLayout()
        center.addStretch()
        center.addWidget(card)
        center.addStretch()
        root.addLayout(center)

        root.addStretch(2)

        ver = QLabel(f"Medral Client v{_read_version()}")
        ver.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        ver.setStyleSheet("color:#6b6b8a; font-size:11px; background:transparent;")
        root.addWidget(ver)

    def _add_toggle_row(
        self, layout: QVBoxLayout, key: str, title: str, subtitle: str,
    ) -> ToggleSwitch:
        """One playback-settings row: title + muted subtitle, toggle on the right."""
        row = QHBoxLayout()
        row.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        t_lbl = QLabel(title)
        t_lbl.setStyleSheet("color:#e8e8f5; background:transparent;")
        s_lbl = QLabel(subtitle)
        s_lbl.setStyleSheet("color:#6b6b8a; font-size:11px; background:transparent;")
        s_lbl.setWordWrap(True)
        text_col.addWidget(t_lbl)
        text_col.addWidget(s_lbl)
        row.addLayout(text_col, 1)

        toggle = ToggleSwitch()
        toggle.toggled.connect(
            lambda checked, k=key: self.settings_changed.emit(k, checked)
        )
        row.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(row)
        return toggle

    # ── public ────────────────────────────────────────────────────────────

    def set_playback_settings(self, settings: dict) -> None:
        """Sync toggles to server state without re-emitting settings_changed."""
        if not isinstance(settings, dict):
            return
        for key, toggle in (
            ("normalize", self._normalize_toggle),
            ("radio",     self._radio_toggle),
        ):
            value = settings.get(key)
            if isinstance(value, bool) and toggle.isChecked() != value:
                toggle.set_checked_silent(value)

    def set_playback_enabled(self, enabled: bool) -> None:
        """Disable toggles (dimmed to 0.4 opacity) when no guild is selected."""
        self._normalize_toggle.setEnabled(enabled)
        self._radio_toggle.setEnabled(enabled)

    def set_values(self, host: str, port: int) -> None:
        self._fallback_host = host
        self._fallback_port = port
        self._host_edit.setText(host)
        self._port_edit.setText(str(port))

    def set_username(self, name: str) -> None:
        self._user_lbl.setText(name or "—")

    # ── private ───────────────────────────────────────────────────────────

    def _on_connect_clicked(self) -> None:
        host = self._host_edit.text().strip() or self._fallback_host
        try:
            port = int(self._port_edit.text().strip())
        except ValueError:
            port = self._fallback_port
        self.connect_requested.emit(host, port)
